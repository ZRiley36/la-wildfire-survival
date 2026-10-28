"""Step 2: fix values and label outcomes. Writes data/interim/02_*.parquet.

DINS is cut to residential structures and given the outcome labels. Every field an inspector recorded after
the fire is renamed with a `post_` prefix, so it can never be picked up as a model feature by accident.
"""
import geopandas as gpd
import numpy as np
import pandas as pd

from wildfire.apn import normalize_apn
from wildfire.config import cfg, interim

POST_FIRE = ["ROOFCONSTRUCTION", "EAVES", "VENTSCREEN", "EXTERIORSIDING", "WINDOWPANE", "DECKPORCHONGRADE",
             "DECKPORCHELEVATED", "PATIOCOVERCARPORT", "FENCEATTACHEDTOSTRUCTURE", "PROPANETANKDISTANCE",
             "UTILITYMISCSTRUCTUREDISTANCE", "NOOUTBUILDINGSDAMAGED", "NOOUTBUILDINGSNOTDAMAGED",
             "NOOFCARSONPROPERTY", "WHEREFIRESTARTEDONSTRUCTURE", "WHATDIDFIRESTARTFROM", "DEFENSIVEACTIONS"]


def log(msg):
    print(f"  {msg}")


def year_or_nan(s):
    y = pd.to_numeric(s, errors="coerce")
    return y.where((y >= 1850) & (y <= 2025))


def dins():
    c = cfg()
    d = gpd.read_parquet(interim("01_dins"))
    n = len(d)
    d = d[d.STRUCTURECATEGORY.isin(c["outcome"]["residential_categories"])].copy()
    log(f"DINS: {n:,} structures -> {len(d):,} residential")
    d["fire"] = d.INCIDENTNAME.str.upper()
    d["damage"] = d.DAMAGE.str.split().str[0].replace({"No": "No Damage"})
    unknown = set(d.damage) - set(c["outcome"]["ordinal"]) - set(c["outcome"]["drop"])
    if unknown:
        raise ValueError(f"unexpected damage classes {unknown}")
    d["inaccessible"] = d.damage.isin(c["outcome"]["drop"])
    d["damage_ordinal"] = d.damage.map(c["outcome"]["ordinal"])
    d["destroyed"] = d.damage.isin(c["outcome"]["destroyed"])
    d["destroyed_or_major"] = d.damage.isin(c["outcome"]["destroyed_sensitivity"])
    d["apn"] = d.APN.map(normalize_apn)
    d["year_built_dins"] = year_or_nan(d.YEARBUILT)
    d = d.rename(columns={f: f"post_{f.lower()}" for f in POST_FIRE})
    keep = ["GLOBALID", "fire", "DAMAGE", "damage", "damage_ordinal", "destroyed", "destroyed_or_major",
            "inaccessible", "STRUCTURETYPE", "STRUCTURECATEGORY", "NUMBEROFUNITPERSTRUCTURE", "apn",
            "year_built_dins", "ASSESSEDIMPROVEDVALUE", "SITEADDRESS", "CITY",
            *[f"post_{f.lower()}" for f in POST_FIRE], "geometry"]
    d = d[keep].reset_index(drop=True)
    d.insert(0, "dins_id", range(len(d)))
    log(f"DINS residential by fire and class:\n{pd.crosstab(d.damage, d.fire).to_string()}")
    log(f"inaccessible: {d.inaccessible.sum()}, APN missing: {d.apn.isna().sum()}, "
        f"year built missing: {d.year_built_dins.isna().sum()} ({d.year_built_dins.isna().mean():.1%})")
    d.to_parquet(interim("02_dins"))


def parcels():
    p = gpd.read_parquet(interim("01_parcels"))
    p["apn"] = p.AIN_1.map(normalize_apn)
    for i in range(1, 6):
        p[f"year_built_{i}"] = year_or_nan(p[f"YearBuilt{i}"])
    p["effective_year_1"] = year_or_nan(p.EffectiveYear1)
    p["buildings_on_parcel"] = p[[f"year_built_{i}" for i in range(1, 6)]].notna().sum(axis=1)
    p["community"] = p.COMMUNITY.str.strip().replace("", np.nan)
    keep = ["apn", "UseCode", "UseType", "UseDescription", "community", "LCITY", "Roll_Year", "year_built_1",
            "effective_year_1", "buildings_on_parcel", "SQFTmain1", "Units1", "DAMAGE_1", "DINS_Count", "geometry"]
    p = p[keep]
    log(f"parcels: {len(p):,}, APN missing {p.apn.isna().sum()}, duplicate APN {p.apn.duplicated().sum()}, "
        f"buildings on parcel {p.buildings_on_parcel.value_counts().sort_index().to_dict()}")
    p.to_parquet(interim("02_parcels"))


def footprints():
    c = cfg()
    f = gpd.read_parquet(interim("01_footprints"))
    n = len(f)
    f = f[f.CODE.isin(c["join"]["footprint_codes"])].copy()
    f["footprint_area_m2"] = f.area
    f["footprint_date"] = pd.to_numeric(f.DATE_, errors="coerce")
    f = f[["BLD_ID", "SOURCE", "footprint_date", "STATUS", "HEIGHT", "footprint_area_m2", "geometry"]].reset_index(drop=True)
    f.insert(0, "fp_id", range(len(f)))
    log(f"footprints: {n:,} -> {len(f):,} buildings (dropped courtyards and solar structures). "
        f"Area m2 median {f.footprint_area_m2.median():.0f}, under 10 m2: {(f.footprint_area_m2 < 10).sum()}")
    f.to_parquet(interim("02_footprints"))


def hazard_zones():
    """One layer per map version, with a common `fhsz` class (Very High / High / Moderate / NonWildland)."""
    la = gpd.read_parquet(interim("01_fhsz_lacounty"))
    sra = gpd.read_parquet(interim("01_fhsz_sra_2023"))
    lra = gpd.read_parquet(interim("01_fhsz_lra_2025"))
    # In effect January 2025: CAL FIRE SRA 2023 wherever it applies, the LA County map everywhere else.
    sra_u = sra.union_all()
    la_rest = la.assign(geometry=la.difference(sra_u))
    la_rest = la_rest[~la_rest.is_empty]
    in_effect = pd.concat([
        sra.assign(fhsz=sra.FHSZ_Description, source="CAL FIRE SRA 2023 (eff. 2024-04-01)")[["fhsz", "source", "geometry"]],
        la_rest.assign(fhsz=la_rest.HAZ_CLASS, source=la_rest.SRA.radd("LA County FHSZ, "))[["fhsz", "source", "geometry"]],
    ], ignore_index=True)
    gpd.GeoDataFrame(in_effect, crs=la.crs).to_parquet(interim("02_fhsz_in_effect"))
    lra.assign(fhsz=lra.FHSZ_Description, source="CAL FIRE LRA 2025 (map dated 2025-03-24)")[
        ["fhsz", "source", "geometry"]].to_parquet(interim("02_fhsz_lra_2025"))
    log(f"hazard zones in effect: {in_effect.groupby('source').size().to_dict()}")


def main():
    dins()
    parcels()
    footprints()
    hazard_zones()


if __name__ == "__main__":
    main()
