"""Step 3: the building table. One row per residential DINS building.

  footprint   the 2023 footprint the DINS point falls in, else the nearest within a few meters
  parcel      assessor attributes by APN, else the parcel under the point
  year built  DINS (assessor value carried by the inspection), else the parcel's first building
  perimeter   inside its own fire's perimeter or not, and the signed distance to the edge. These are for
              choosing the population and describing results only. They are never model inputs, because the
              perimeter is drawn from where the fire went.

Every match records how it was made, and unmatched rows stay in the table with a flag.
Writes data/interim/03_buildings.parquet.
"""
import geopandas as gpd
import numpy as np
import pandas as pd

from wildfire.config import cfg, interim


def log(msg):
    print(f"  {msg}")


def rate(s, label, total=None):
    total = total or len(s)
    for k, v in s.value_counts(dropna=False).items():
        log(f"{label} {k}: {v:,} ({v / total:.1%})")


def points_to_footprints(points, footprints, max_m):
    """fp_id for each point: the footprint containing it, else the nearest within max_m, else NaN.

    Returns (fp_id Series, how Series) aligned to points.index.
    """
    fp_id = pd.Series(np.nan, index=points.index)
    how = pd.Series("none", index=points.index)
    inside = gpd.sjoin(points[["geometry"]], footprints[["fp_id", "geometry"]], predicate="within")
    # a point on a shared wall can touch two footprints. Take the smaller one, which is the more specific match.
    inside = inside.assign(area=footprints.set_index("fp_id").loc[inside.fp_id].area.values) \
        .sort_values("area").groupby(level=0).first()
    fp_id.loc[inside.index] = inside.fp_id
    how.loc[inside.index] = "within"
    rest = points.index.difference(inside.index)
    if len(rest):
        near = gpd.sjoin_nearest(points.loc[rest, ["geometry"]], footprints[["fp_id", "geometry"]],
                                 max_distance=max_m, distance_col="d")
        near = near.sort_values("d").groupby(level=0).first()
        fp_id.loc[near.index] = near.fp_id
        how.loc[near.index] = f"nearest<={max_m}m"
    return fp_id, how


def main():
    c = cfg()
    d = gpd.read_parquet(interim("02_dins"))
    f = gpd.read_parquet(interim("02_footprints"))
    p = gpd.read_parquet(interim("02_parcels"))
    per = gpd.read_parquet(interim("01_perimeters"))
    n = len(d)
    log(f"residential DINS buildings: {n:,}")

    d["fp_id"], d["footprint_match"] = points_to_footprints(d, f, c["join"]["nearest_footprint_max_m"])
    rate(d.footprint_match, "footprint", n)
    shared = d.groupby("fp_id").fp_id.transform("size")
    d["footprint_shared"] = shared.fillna(1).astype(int)
    log(f"footprints holding more than one DINS building: {(d.groupby('fp_id').size() > 1).sum()} "
        f"({(d.footprint_shared > 1).sum()} buildings)")
    d = d.merge(f[["fp_id", "BLD_ID", "SOURCE", "footprint_date", "footprint_area_m2"]], on="fp_id", how="left")
    d = gpd.GeoDataFrame(d, geometry="geometry", crs=f.crs)

    # parcels: APN first, the parcel under the point for the rest
    pa = p.drop(columns="geometry").set_index("apn")
    d["parcel_match"] = np.where(d.apn.isin(pa.index), "apn", None)
    miss = d.parcel_match.isna()
    sp = gpd.sjoin(d.loc[miss, ["geometry"]], p[["apn", "geometry"]], predicate="within")
    sp = sp[~sp.index.duplicated()]
    d.loc[sp.index, "apn"] = sp.apn
    d.loc[sp.index, "parcel_match"] = "point_in_parcel"
    d["parcel_match"] = d.parcel_match.fillna("none")
    rate(d.parcel_match, "parcel", n)
    d = d.join(pa[["community", "LCITY", "UseCode", "UseDescription", "year_built_1", "effective_year_1",
                   "buildings_on_parcel"]], on="apn")
    d["dins_on_parcel"] = d.groupby("apn").apn.transform("size")
    d["multi_building_parcel"] = (d.buildings_on_parcel > 1) | (d.dins_on_parcel > 1)
    log(f"buildings on multi-building parcels: {d.multi_building_parcel.sum():,} "
        f"({d.multi_building_parcel.mean():.1%})")

    d["year_built"] = d.year_built_dins
    d["year_built_source"] = np.where(d.year_built.notna(), "dins", None)
    fill = d.year_built.isna() & d.year_built_1.notna()
    d.loc[fill, "year_built"] = d.loc[fill, "year_built_1"]
    d.loc[fill, "year_built_source"] = "parcel_building_1"
    d["year_built_source"] = d.year_built_source.fillna("missing")
    rate(d.year_built_source, "year built", n)
    agree = d.year_built_dins.notna() & d.year_built_1.notna()
    log(f"DINS vs parcel year built agree exactly on {(d.loc[agree, 'year_built_dins'] == d.loc[agree, 'year_built_1']).mean():.1%} "
        f"of {agree.sum():,} buildings with both")

    # perimeter: population and description only
    own = per.set_index("FIRE_NAME").geometry
    edge = {k: g.boundary for k, g in own.items()}
    d["inside_perimeter"] = [own[fi].contains(pt) for fi, pt in zip(d.fire, d.geometry)]
    dist = np.array([edge[fi].distance(pt) for fi, pt in zip(d.fire, d.geometry)])
    d["perimeter_dist_m"] = np.where(d.inside_perimeter, -dist, dist)  # negative = inside
    band_m = c["study_area"]["outside_band_m"]
    d["perimeter_band"] = np.select([d.inside_perimeter, d.perimeter_dist_m <= band_m],
                                    ["inside", "outside_0_300ft"], "outside_beyond_300ft")
    d["pop_main"] = d.inside_perimeter & ~d.inaccessible
    d["pop_buffer"] = (d.perimeter_band != "outside_beyond_300ft") & ~d.inaccessible
    log(f"perimeter bands: {d.groupby(['fire', 'perimeter_band']).size().to_dict()}")
    log(f"main population (inside, accessible): {d.pop_main.sum():,}. With the 300 ft band: {d.pop_buffer.sum():,}")

    bg = gpd.read_parquet(interim("01_block_groups"))
    j = gpd.sjoin(d[["geometry"]], bg[["GEOID", "geometry"]], predicate="within")
    d["block_group"] = j[~j.index.duplicated()].GEOID
    log(f"block group assigned: {d.block_group.notna().sum():,} of {n:,}")

    for fire, g in d[d.pop_main].groupby("fire"):
        log(f"{fire}: {len(g):,} buildings in the main population, destroyed {g.destroyed.mean():.1%}, "
            f"destroyed or major {g.destroyed_or_major.mean():.1%}")
    d.to_parquet(interim("03_buildings"))


if __name__ == "__main__":
    main()
