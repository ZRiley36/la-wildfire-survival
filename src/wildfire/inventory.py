"""Step 1 inventory: open every raw file and report what's actually in it.

python -m wildfire.inventory > docs/data_inventory.json
Distances and areas are measured in EPSG:3310 (California Albers, meters) here.
"""
import json
import sys
import warnings
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from shapely.geometry import box

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data/raw"
M = 3310
FT300 = 300 * 0.3048
RESIDENTIAL = {"Single Residence", "Multiple Residence", "Mixed Commercial/Residential"}
POST_FIRE_FIELDS = {
    "ROOFCONSTRUCTION": "roof material, recorded by the inspector after the fire",
    "EAVES": "eave type, recorded after the fire",
    "VENTSCREEN": "vent screen, recorded after the fire",
    "EXTERIORSIDING": "siding material, recorded after the fire",
    "WINDOWPANE": "window glazing, recorded after the fire",
    "DECKPORCHONGRADE": "deck on grade, recorded after the fire",
    "DECKPORCHELEVATED": "elevated deck, recorded after the fire",
    "PATIOCOVERCARPORT": "patio cover / carport, recorded after the fire",
    "FENCEATTACHEDTOSTRUCTURE": "attached fence, recorded after the fire",
    "PROPANETANKDISTANCE": "propane tank distance, recorded after the fire",
    "UTILITYMISCSTRUCTUREDISTANCE": "distance to outbuildings, recorded after the fire",
    "NOOUTBUILDINGSDAMAGED": "count of outbuildings damaged (outcome of the fire itself)",
    "NOOUTBUILDINGSNOTDAMAGED": "count of outbuildings not damaged (outcome of the fire itself)",
    "NOOFCARSONPROPERTY": "cars on the property at inspection",
    "WHEREFIRESTARTEDONSTRUCTURE": "ignition point on the structure (only filled for damaged buildings)",
    "WHATDIDFIRESTARTFROM": "ignition mechanism (only filled for damaged buildings)",
    "DEFENSIVEACTIONS": "firefighting actions during the fire",
    "DAMAGE": "the outcome itself",
}


def vec(g, keys=()):
    out = {"rows": int(len(g)), "crs": g.crs.to_string() if g.crs else None,
           "geometry_types": {k: int(v) for k, v in g.geom_type.value_counts().items()},
           "invalid": int((~g.is_valid & g.geometry.notna()).sum()), "null_geometry": int(g.geometry.isna().sum()),
           "bounds": [round(float(x), 5) for x in g.total_bounds], "columns": [c for c in g.columns if c != "geometry"]}
    for k in keys:
        s = g[k]
        out.setdefault("key_fields", {})[k] = {"nulls": int(s.isna().sum()), "unique": int(s.nunique()),
                                               "top": {str(a): int(b) for a, b in s.value_counts().head(12).items()}}
    return out


def perimeters():
    p = gpd.read_file(RAW / "perimeters_calfire/perimeters_calfire.geojson").to_crs(M)
    out = {"calfire": vec(p, ["FIRE_NAME"])}
    p["geometry"] = p.make_valid()
    out["calfire"]["acres_after_make_valid"] = dict(zip(p.FIRE_NAME, (p.area / 4046.856).round(0).tolist()))
    out["calfire"]["gis_acres"] = dict(zip(p.FIRE_NAME, p.GIS_ACRES.round(0).tolist()))
    la = gpd.read_file(RAW / "perimeters_lacounty/perimeters_lacounty.geojson")
    out["lacounty"] = vec(la, ["FIRE_NAME"])
    out["lacounty"]["note"] = "Named 'Palisades and Eaton' but holds only the Eaton perimeter."
    return out, p


def dins(per):
    d = gpd.read_file(RAW / "dins_master/dins_master.geojson")
    out = vec(d, ["INCIDENTNAME", "DAMAGE", "STRUCTURECATEGORY", "STRUCTURETYPE"])
    out["damage_by_fire"] = pd.crosstab(d.DAMAGE, d.INCIDENTNAME).to_dict()
    res = d[d.STRUCTURECATEGORY.isin(RESIDENTIAL)]
    out["residential_damage_by_fire"] = pd.crosstab(res.DAMAGE, res.INCIDENTNAME).to_dict()
    out["residential_rows"] = int(len(res))
    yb = pd.to_numeric(d.YEARBUILT, errors="coerce")
    ok = (yb >= 1850) & (yb <= 2025)
    out["yearbuilt"] = {"all_with_year_pct": round(float(ok.mean()) * 100, 1),
                        "residential_with_year_pct": round(float(ok[res.index].mean()) * 100, 1),
                        "zero": int((yb == 0).sum()), "min": int(yb[ok].min()), "median": int(yb[ok].median()),
                        "max": int(yb[ok].max()), "built_after_2008_residential": int((yb[res.index] > 2008).sum())}
    out["apn"] = {"nulls": int(d.APN.isna().sum()),
                  "lengths": {int(k): int(v) for k, v in d.APN.dropna().astype(str).str.len().value_counts().items()},
                  "sample": d.APN.dropna().astype(str).sample(6, random_state=0).tolist()}
    # inside each fire's own perimeter, or within 300 ft outside it
    dm = d.to_crs(M)
    rows = {}
    for fire, geom in zip(per.FIRE_NAME, per.geometry):
        sub = dm[dm.INCIDENTNAME.str.upper() == fire]
        dist = sub.distance(geom)
        rows[fire] = {"total": int(len(sub)), "inside": int((dist == 0).sum()),
                      "outside_within_300ft": int(((dist > 0) & (dist <= FT300)).sum()),
                      "outside_beyond_300ft": int((dist > FT300).sum()),
                      "max_distance_outside_m": round(float(dist.max()), 1)}
    out["inside_vs_buffer"] = rows
    # leakage: share recorded as Unknown, destroyed vs not
    destroyed = d.DAMAGE.str.startswith("Destroyed")
    out["post_fire_fields"] = {}
    for f, why in POST_FIRE_FIELDS.items():
        s = d[f]
        entry = {"why": why, "filled_pct": round(float(s.notna().mean()) * 100, 1)}
        if f != "DAMAGE" and not pd.api.types.is_numeric_dtype(s):
            entry["unknown_pct_destroyed"] = round(float((s[destroyed] == "Unknown").mean()) * 100, 1)
            entry["unknown_pct_not_destroyed"] = round(float((s[~destroyed] == "Unknown").mean()) * 100, 1)
        out["post_fire_fields"][f] = entry
    pub = pd.concat([gpd.read_file(RAW / f"dins_public_{f}/dins_public_{f}.geojson").assign(fire=f)
                     for f in ["palisades", "eaton"]])
    out["public_views"] = {"rows": pub.groupby("fire").size().to_dict(),
                           "damage": pd.crosstab(pub.DAMAGE, pub.fire).to_dict(),
                           "globalid_overlap_with_master": int(pub.GLOBALID.isin(d.GLOBALID).sum())}
    return out, d


def parcels():
    p = gpd.read_file(RAW / "parcels_dins/parcels_dins.geojson")
    out = vec(p, ["Fire_Name", "DAMAGE_1", "STRUCTURECATEGORY", "UseType", "UseCode_2", "DINS_Count", "LCITY",
                  "COMMUNITY"])
    out["ain_apn"] = {"AIN_1_lengths": {int(k): int(v) for k, v in p.AIN_1.dropna().str.len().value_counts().items()},
                      "APN_1_sample": p.APN_1.dropna().head(3).tolist(), "AIN_1_sample": p.AIN_1.dropna().head(3).tolist(),
                      "AIN_equals_APN_without_dashes": int((p.AIN_1 == p.APN_1.str.replace("-", "")).sum()),
                      "duplicate_AIN": int(p.AIN_1.duplicated().sum())}
    yb = {i: pd.to_numeric(p[f"YearBuilt{i}"], errors="coerce") for i in range(1, 6)}
    out["buildings_on_parcel"] = {f"with_YearBuilt{i}": int((v > 0).sum()) for i, v in yb.items()}
    out["YearBuilt1"] = {"nulls": int(yb[1].isna().sum()), "zero": int((yb[1] == 0).sum()),
                         "median": float(yb[1][yb[1] > 0].median())}
    out["EffectiveYear1_nulls"] = int(pd.to_numeric(p.EffectiveYear1, errors="coerce").isna().sum())
    out["UseCode_sample"] = p.UseCode.dropna().sample(10, random_state=1).tolist()
    return out, p


def buildings():
    b = gpd.read_file(RAW / "buildings_2023_dins/buildings_2023_dins.geojson")
    out = vec(b, ["CODE", "DAMAGE", "STRUCTURET", "STATUS", "SOURCE", "DATE_"])
    out["duplicate_BLD_ID"] = int(b.BLD_ID.duplicated().sum())
    out["AREA_sqft"] = {k: round(float(v), 1) for k, v in pd.to_numeric(b.AREA).describe().items()}
    out["note"] = "AREA is square feet (matches Shape__Area in Web Mercator m2 after the cos(lat)^2 correction)."
    return out, b


def joins(d, p, b, per):
    dm = d.to_crs(M)
    bm = b.to_crs(M)
    bm["geometry"] = bm.make_valid()
    bm = bm[bm.CODE == "Building"].reset_index(drop=True)
    res = dm[dm.STRUCTURECATEGORY.isin(RESIDENTIAL)]
    pip = gpd.sjoin(res[["geometry"]], bm[["geometry"]], predicate="within")
    inside = pip.groupby(level=0).size()
    out = {"residential_dins": int(len(res)),
           "point_in_footprint": int(inside.reindex(res.index).notna().sum()),
           "point_in_more_than_one_footprint": int((inside > 1).sum())}
    miss = res[~res.index.isin(inside.index)]
    nn = gpd.sjoin_nearest(miss[["geometry"]], bm[["geometry"]], distance_col="d")
    nd = nn.groupby(level=0).d.min()
    out["nearest_footprint_for_misses_m"] = {k: round(float(v), 1) for k, v in nd.describe().items()}
    for t in [2, 5, 10, 20]:
        out[f"matched_within_{t}m_pct"] = round((out["point_in_footprint"] + int((nd <= t).sum())) / len(res) * 100, 2)
    hits = pip.index_right
    out["footprints_hit_by_several_dins"] = int(hits.value_counts().gt(1).sum())
    ain = set(p.AIN_1.dropna())
    apn = d.APN.astype(str).str.replace(r"\D", "", regex=True)
    out["dins_apn_in_parcels_pct"] = round(float(apn.isin(ain).mean()) * 100, 2)
    out["residential_dins_apn_in_parcels_pct"] = round(float(apn[res.index].isin(ain).mean()) * 100, 2)
    per_parcel = apn[res.index].value_counts()
    out["parcels_with_several_residential_dins"] = int((per_parcel > 1).sum())
    out["residential_dins_on_multi_building_parcels"] = int(per_parcel[per_parcel > 1].sum())
    return out


def hazard_zones(per):
    out = {}
    meta = {
        "fhsz_lacounty": "LACoFD 'Los Angeles County Fire Hazard Severity Zones' (CAL FIRE data). Created 2019-04-02, "
                         "modified 2023-03-23. 2007 SRA / 2007-2011 LRA-era schema (FID_c19fhs).",
        "fhsz_sra_2023": "CAL FIRE FHSZ in SRA, adopted April 1, 2024.",
        "fhsz_lra_2025": "CAL FIRE recommended FHSZ in LRA, map dated March 24, 2025 (after the fires).",
        "vhfhsz_la_city": "City of Los Angeles VHFHSZ, last updated 2019-09-03.",
    }
    for name, note in meta.items():
        g = gpd.read_file(RAW / name / f"{name}.geojson")
        s = vec(g, [c for c in ["HAZ_CLASS", "SRA", "INCORP", "FHSZ_Description"] if c in g])
        s["dates"] = note
        gi = g.to_crs(M)
        gi["geometry"] = gi.make_valid()
        col = next((c for c in ["HAZ_CLASS", "FHSZ_Description"] if c in gi), None)
        s["share_of_perimeter_pct"] = {}
        for fire, geom in zip(per.FIRE_NAME, per.geometry):
            c = gi.clip(geom)
            s["share_of_perimeter_pct"][fire] = ({k: round(float(v), 1) for k, v in
                                                  (c.assign(a=c.area).groupby(col).a.sum() / geom.area * 100).items()}
                                                 if col else round(float(c.area.sum() / geom.area * 100), 1))
        out[name] = s
    return out


def rasters(per):
    out = {}
    for f in ["palisades", "eaton"]:
        with rasterio.open(RAW / f"landfire_fbfm40/lf2023_fbfm40_{f}.tif") as r:
            a = r.read(1)
            vals, cnt = np.unique(a, return_counts=True)
            pf = per.to_crs(r.crs)
            geom = pf[pf.FIRE_NAME.str.lower() == f].geometry.iloc[0]
            out[f"landfire_{f}"] = {
                "crs": r.crs.to_string(), "res": list(r.res), "size": [r.width, r.height], "dtype": r.dtypes[0],
                "nodata": r.nodata, "bounds": [round(x) for x in r.bounds], "covers_perimeter": box(*r.bounds).contains(geom),
                "codes": {int(v): int(c) for v, c in zip(vals, cnt)},
                "burnable_pct": round(float(((a >= 101) & (a <= 204)).sum() / (a != r.nodata).sum() * 100), 1)}
    with rasterio.open(RAW / "usgs_3dep/USGS_13_n35w119_20240207.tif") as r:
        pf = per.to_crs(r.crs)
        win = rasterio.windows.from_bounds(*pf.total_bounds, transform=r.transform)
        s = r.read(1, window=win)
        out["dem"] = {"crs": r.crs.to_string(), "res_deg": list(r.res), "approx_res_m": [round(r.res[0] * 92400, 1), round(r.res[1] * 111000, 1)],
                      "size": [r.width, r.height], "dtype": r.dtypes[0], "nodata": r.nodata,
                      "bounds": [round(x, 4) for x in r.bounds], "covers_both_perimeters": box(*r.bounds).contains(pf.union_all()),
                      "elevation_over_fires_m": [round(float(s.min()), 1), round(float(s.max()), 1)],
                      "nodata_cells_over_fires": int((s == r.nodata).sum())}
    return out


def main():
    rep = {"files": [{"path": str(p.relative_to(RAW)), "mb": round(p.stat().st_size / 1e6, 2)}
                     for p in sorted(RAW.rglob("*")) if p.is_file()]}
    rep["perimeters"], per = perimeters()
    print("dins", file=sys.stderr)
    rep["dins"], d = dins(per)
    print("parcels / buildings", file=sys.stderr)
    rep["parcels"], p = parcels()
    rep["buildings"], b = buildings()
    print("joins", file=sys.stderr)
    rep["joins"] = joins(d, p, b, per)
    print("zones / rasters", file=sys.stderr)
    rep["hazard_zones"] = hazard_zones(per)
    rep["rasters"] = rasters(per)
    bg = gpd.read_file("zip://" + str(RAW / "census/cb_2024_06_bg_500k.zip"))
    rep["block_groups"] = {"rows_ca": int(len(bg)), "la_county": int((bg.COUNTYFP == "037").sum()), "crs": bg.crs.to_string()}
    json.dump(rep, sys.stdout, indent=1, default=str)


if __name__ == "__main__":
    main()
