"""Step 4: pre-fire features for every building. Writes data/interim/04_features.parquet.

Terrain   elevation (native DEM), slope and aspect (DEM warped to 10 m in EPSG:3310, Horn's method)
Fuels     LF2023 FBFM40 class at the building, burnable share within 30/100/300 m, and distance to the nearest
          contiguous wildland patch (burnable, >= min_patch_ha). LANDFIRE is read in its native EPSG:5070 grid
Neighbors distance to the nearest other building and counts within 10/30/50 m, footprint to footprint, using
          every 2023 building outline (not just the inspected ones, since an unlisted garage still carries fire)
Age       year built, built after 2008 (Chapter 7A)
Zones     hazard class in the map in effect in January 2025, and in the 2025 LRA map (labeled as post-fire)

A building's location for sampling is its footprint's representative point, or the DINS point if there's no
footprint.
"""
import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import shapely

from wildfire import raster
from wildfire.config import RAW, cfg, interim

DEM = RAW / "usgs_3dep/USGS_13_n35w119_20240207.tif"
DEM_RES_M = 10


def log(msg):
    print(f"  {msg}")


def neighbor_stats(targets, others, radii, target_ids=None, other_ids=None):
    """For each target geometry: distance to the nearest *other* geometry and counts within each radius.

    targets, others: arrays of shapely geometries in a metric CRS. target_ids / other_ids mark which `others`
    entry is the target itself (so a footprint isn't its own neighbor). Distances are edge to edge.
    """
    tree = shapely.STRtree(others)
    targets = np.asarray(targets)
    tid = np.asarray(target_ids) if target_ids is not None else np.full(len(targets), -1)
    oid = np.asarray(other_ids) if other_ids is not None else np.arange(len(others))
    out = {"dist": np.full(len(targets), np.nan)}
    reach = max(max(radii), 200)
    pairs = tree.query(targets, predicate="dwithin", distance=reach)
    ti, oi = pairs
    keep = oid[oi] != tid[ti]
    ti, oi = ti[keep], oi[keep]
    d = shapely.distance(targets[ti], np.asarray(others)[oi])
    df = pd.DataFrame({"t": ti, "d": d})
    nearest = df.groupby("t").d.min()
    out["dist"][nearest.index] = nearest.values
    # anything with no neighbor inside `reach` gets its true nearest distance the slow way
    far = np.setdiff1d(np.arange(len(targets)), nearest.index)
    for i in far:
        idx, dist = tree.query_nearest(targets[i], return_distance=True, all_matches=True, exclusive=False)
        cand = [(dd, j) for j, dd in zip(idx, dist) if oid[j] != tid[i]]
        if not cand:
            idx, dist = tree.query(targets[i], predicate="dwithin", distance=5000), None
            cand = [(shapely.distance(targets[i], others[j]), j) for j in idx if oid[j] != tid[i]]
        out["dist"][i] = min(cand)[0] if cand else np.nan
    for r in radii:
        out[f"n_{r}"] = df[df.d <= r].groupby("t").size().reindex(range(len(targets)), fill_value=0).values
    return out


def terrain(b, study_area):
    c = cfg()
    pts = gpd.GeoSeries(b.sample_point, crs=b.crs)
    b["elevation_m"] = raster.sample(DEM, pts)
    bounds = study_area.buffer(100).bounds
    z, t = raster.warp_window(DEM, bounds, c["crs"], DEM_RES_M)
    slope, aspect = raster.horn_slope_aspect(z, DEM_RES_M)
    b["slope_deg"] = raster.sample_array(slope, t, pts)
    asp = raster.sample_array(aspect, t, pts)
    b["aspect_deg"] = asp
    b["aspect_sin"] = np.sin(np.radians(asp))   # east-west component (1 = east-facing)
    b["aspect_cos"] = np.cos(np.radians(asp))   # north-south component (1 = north-facing)
    b[["aspect_sin", "aspect_cos"]] = b[["aspect_sin", "aspect_cos"]].fillna(0)  # flat ground: no direction
    log(f"terrain: elevation {b.elevation_m.min():.0f}-{b.elevation_m.max():.0f} m, slope median "
        f"{b.slope_deg.median():.1f} deg (max {b.slope_deg.max():.1f}), missing {b.slope_deg.isna().sum()}")
    return b


def fuels(b, per):
    c = cfg()["features"]
    lo, hi = c["burnable_codes"]
    cells_per_ha = 10_000 / 900
    out = {k: np.full(len(b), np.nan) for k in ["fuel_code", *[f"burnable_share_{r}m" for r in c["fuel_buffers_m"]],
                                               "dist_wildland_m"]}
    wild_all = []
    for fire in per.FIRE_NAME:
        path = RAW / f"landfire_fbfm40/lf2023_fbfm40_{fire.lower()}.tif"
        sel = (b.fire == fire).values
        with rasterio.open(path) as ds:
            arr = ds.read(1)
            mask = (arr >= lo) & (arr <= hi)          # nodata (ocean) and 91-99 are not burnable
            pts = gpd.GeoSeries(b.loc[sel, "sample_point"], crs=b.crs).to_crs(ds.crs)
            out["fuel_code"][sel] = raster.sample(ds, gpd.GeoSeries(b.loc[sel, "sample_point"], crs=b.crs))
            for r in c["fuel_buffers_m"]:
                share, ft = raster.focal_share(mask, ds.transform, r, c["fuel_supersample"])
                out[f"burnable_share_{r}m"][sel] = raster.sample_array(share, ft, pts)
            wild, n_all, n_kept = raster.patches(mask, ds.transform, ds.crs, c["wildland_min_patch_ha"] * cells_per_ha)
            wild = wild.to_crs(b.crs)
            wild_all.append(wild)
            geoms = gpd.GeoSeries(b.loc[sel, "shape"], crs=b.crs)
            u = wild.union_all()
            out["dist_wildland_m"][sel] = geoms.distance(u).values
            log(f"{fire}: {n_all:,} burnable patches, {n_kept} of at least {c['wildland_min_patch_ha']} ha "
                f"covering {wild.area.sum() / 1e6:.1f} km2")
    for k, v in out.items():
        b[k] = v
    b["fuel_burnable_at_building"] = ((b.fuel_code >= lo) & (b.fuel_code <= hi)).astype(int)
    log(f"fuel at building: {b.fuel_code.value_counts().head(6).to_dict()}; burnable {b.fuel_burnable_at_building.mean():.1%}")
    log(f"distance to wildland: median {b.dist_wildland_m.median():.0f} m, 0 m (touching) {(b.dist_wildland_m == 0).mean():.1%}")
    gpd.GeoDataFrame(geometry=pd.concat(wild_all), crs=b.crs).to_parquet(interim("04_wildland_patches"))
    return b


def neighbors(b, f):
    radii = cfg()["features"]["neighbor_radii_m"]
    has_fp = b.fp_id.notna()
    fp_geom = f.set_index("fp_id").geometry
    targets = np.where(has_fp, fp_geom.reindex(b.fp_id).values, b.geometry.values)
    s = neighbor_stats(targets, f.geometry.values, radii, target_ids=b.fp_id.fillna(-1).values,
                       other_ids=f.fp_id.values)
    b["dist_nearest_building_m"] = s["dist"]
    for r in radii:
        b[f"n_buildings_{r}m"] = s[f"n_{r}"]
    log(f"nearest building: median {b.dist_nearest_building_m.median():.1f} m, touching (0 m) "
        f"{(b.dist_nearest_building_m == 0).mean():.1%}; within 10/30/50 m medians "
        f"{[int(b[f'n_buildings_{r}m'].median()) for r in radii]}")
    return b


def zones(b):
    pts = gpd.GeoDataFrame(geometry=gpd.GeoSeries(b.sample_point, crs=b.crs), index=b.index)
    for name, col in [("02_fhsz_in_effect", "fhsz_in_effect"), ("02_fhsz_lra_2025", "fhsz_lra_2025")]:
        z = gpd.read_parquet(interim(name))
        j = gpd.sjoin(pts, z[["fhsz", "source", "geometry"]], predicate="within")
        j = j[~j.index.duplicated()]
        b[col] = j.fhsz.reindex(b.index).fillna("Not in a zone")
        if col == "fhsz_in_effect":
            b["fhsz_in_effect_source"] = j.source.reindex(b.index)
    b["vhfhsz_in_effect"] = (b.fhsz_in_effect == "Very High").astype(int)
    b["vhfhsz_lra_2025"] = (b.fhsz_lra_2025 == "Very High").astype(int)
    m = b[b.pop_main]
    log(f"in-effect zone (main population): {m.fhsz_in_effect.value_counts().to_dict()}")
    log(f"2025 LRA zone (main population): {m.fhsz_lra_2025.value_counts().to_dict()}")
    return b


def main():
    c = cfg()
    b = gpd.read_parquet(interim("03_buildings"))
    f = gpd.read_parquet(interim("02_footprints"))
    per = gpd.read_parquet(interim("01_perimeters"))
    area = gpd.read_parquet(interim("01_study_area")).geometry.iloc[0]
    fp_geom = f.set_index("fp_id").geometry
    shape_ = fp_geom.reindex(b.fp_id).values
    b["shape"] = gpd.GeoSeries(np.where(b.fp_id.notna(), shape_, b.geometry.values), crs=b.crs)
    b["sample_point"] = gpd.GeoSeries(b["shape"], crs=b.crs).representative_point()
    b["footprint_area_m2"] = b.footprint_area_m2  # NaN where no footprint matched
    b = terrain(b, area)
    b = fuels(b, per)
    b = neighbors(b, f)
    b["built_after_2008"] = (b.year_built > c["features"]["wui_code_year"]).astype(float).where(b.year_built.notna())
    log(f"year built: median {b.year_built.median():.0f}, after 2008: {int(b.built_after_2008.sum())}")
    b = zones(b)
    missing = b.loc[b.pop_main, c["features"]["model"]].isna().sum()
    log(f"missing values in model features (main population): {missing[missing > 0].to_dict()}")
    b.to_parquet(interim("04_features"))


if __name__ == "__main__":
    main()
