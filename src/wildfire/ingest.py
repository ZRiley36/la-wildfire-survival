"""Step 1: read raw vectors, reproject to the project CRS, repair geometry, and clip to the study area.

Writes data/interim/01_*.parquet. Rasters are not touched here. They stay in their native grids and
raster.py samples them where they are.

read_vector() and study_area() don't know anything about fires, so another hazard or city can reuse them.
"""
import warnings

import geopandas as gpd

from wildfire.config import RAW, cfg, interim

warnings.filterwarnings("ignore", message=".*geographic CRS.*")


def log(msg):
    print(f"  {msg}")


def read_vector(path, crs, columns=None, clip_to=None, how="intersects"):
    """Read a vector file, keep `columns`, reproject, make geometries valid, and limit to `clip_to`.

    how="intersects" keeps whole features that touch the area (buildings, parcels, points).
    how="clip" cuts features at the boundary (zones, where area inside is what matters).
    """
    g = gpd.read_file(path, columns=columns) if columns else gpd.read_file(path)
    n_null = int(g.geometry.isna().sum())
    g = g[g.geometry.notna()].to_crs(crs)
    bad = ~g.is_valid
    if bad.any():
        g.loc[bad, "geometry"] = g.loc[bad].make_valid()
    if clip_to is not None:
        if how == "clip":
            g = g.clip(clip_to)
            g = g[~g.is_empty]
        else:
            g = g[g.intersects(clip_to)]
    return g.reset_index(drop=True), {"null_geometry_dropped": n_null, "repaired": int(bad.sum())}


def study_area(perimeters, buffer_m):
    return perimeters.union_all().buffer(buffer_m)


def main():
    c = cfg()
    crs = c["crs"]
    per, info = read_vector(RAW / "perimeters_calfire/perimeters_calfire.geojson", crs,
                            columns=["FIRE_NAME", "INC_NUM", "ALARM_DATE", "GIS_ACRES"])
    per = per[per.FIRE_NAME.isin(c["study_area"]["fires"])]
    per.to_parquet(interim("01_perimeters"))
    log(f"perimeters: {len(per)}, repaired {info['repaired']}, acres "
        f"{dict(zip(per.FIRE_NAME, (per.area / 4046.856).round(0)))}")
    area = study_area(per, c["study_area"]["clip_buffer_m"])
    gpd.GeoDataFrame(geometry=[area], crs=crs).to_parquet(interim("01_study_area"))
    log(f"study area: perimeters + {c['study_area']['clip_buffer_m']} m, {area.area / 1e6:.1f} km2")

    layers = {
        "dins": ("dins_master/dins_master.geojson", "intersects"),
        "parcels": ("parcels_dins/parcels_dins.geojson", "intersects"),
        "footprints": ("buildings_2023_dins/buildings_2023_dins.geojson", "intersects"),
        "fhsz_lacounty": ("fhsz_lacounty/fhsz_lacounty.geojson", "clip"),
        "fhsz_sra_2023": ("fhsz_sra_2023/fhsz_sra_2023.geojson", "clip"),
        "fhsz_lra_2025": ("fhsz_lra_2025/fhsz_lra_2025.geojson", "clip"),
        "vhfhsz_la_city": ("vhfhsz_la_city/vhfhsz_la_city.geojson", "clip"),
    }
    for name, (path, how) in layers.items():
        g, info = read_vector(RAW / path, crs, clip_to=area, how=how)
        g.to_parquet(interim(f"01_{name}"))
        log(f"{name}: {len(g):,} in the study area (repaired {info['repaired']}, "
            f"null geometry dropped {info['null_geometry_dropped']})")

    bg, _ = read_vector("zip://" + str(RAW / "census/cb_2024_06_bg_500k.zip"), crs,
                        columns=["GEOID", "COUNTYFP", "TRACTCE", "NAMELSADCO"], clip_to=area)
    bg.to_parquet(interim("01_block_groups"))
    log(f"block groups touching the study area: {len(bg)}")


if __name__ == "__main__":
    main()
