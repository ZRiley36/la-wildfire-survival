"""Step 7: final building table and web-ready layers.

data/processed/buildings_wildfire.parquet   every residential DINS building: features, outcome, flags, and the
                                            out-of-fold predictions (main population only; NaN elsewhere)
data/processed/web/buildings.geojson        building points (EPSG:4326), outcome and predicted risk
data/processed/web/perimeters.geojson       CAL FIRE perimeters (EPSG:4326), lightly simplified
data/processed/web/fuel_<fire>.tif          LF2023 FBFM40 clipped to perimeter + 1 km, Cloud-Optimized GeoTIFF in
                                            EPSG:4326 (nearest neighbor, because fuel models are categories)

Every prediction in these files is out of sample: block-CV out-of-fold for `risk_*`, and the other fire's model
for `risk_xfire_*`.
"""
import json

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import rasterio.shutil
from rasterio.io import MemoryFile
from rasterio.mask import mask as rio_mask
from rasterio.warp import Resampling, calculate_default_transform, reproject

from wildfire.config import PROCESSED, RAW, cfg, interim

WEB = PROCESSED / "web"
GEOGRAPHIC = "EPSG:4326"


def log(msg):
    print(f"  {msg}")


def building_table():
    c = cfg()
    b = gpd.read_parquet(interim("04_features"))
    pred = pd.read_parquet(interim("05_predictions")).drop(columns=["fire", "destroyed"])
    b = b.merge(pred, on="dins_id", how="left")
    drop = ["shape"]  # footprint geometry duplicate; keep the DINS point as geometry and the sample point as WKB
    out = b.drop(columns=drop)
    out["sample_point"] = gpd.GeoSeries(out.sample_point, crs=b.crs).to_wkb()
    out = gpd.GeoDataFrame(out, geometry="geometry", crs=b.crs)
    out.to_parquet(PROCESSED / "buildings_wildfire.parquet")
    log(f"buildings_wildfire.parquet: {len(out):,} rows, {len(out.columns)} columns, "
        f"{out.oof_hgb.notna().sum():,} with out-of-fold predictions")
    return b


def round_coords(c):
    if isinstance(c[0], (int, float)):
        return [round(c[0], 6), round(c[1], 6)]
    return [round_coords(x) for x in c]


def write_geojson(g, name):
    gj = json.loads(g.to_crs(GEOGRAPHIC).to_json(na="null", drop_id=True))
    for f in gj["features"]:
        f["geometry"]["coordinates"] = round_coords(f["geometry"]["coordinates"])
    p = WEB / name
    p.write_text(json.dumps(gj, separators=(",", ":")))
    log(f"{name}: {len(g):,} features, {p.stat().st_size / 1e6:.2f} MB")


def web_buildings(b):
    keep = b[b.pop_main | (b.perimeter_band == "outside_0_300ft")].copy()
    pts = gpd.GeoDataFrame({
        "id": keep.dins_id, "fire": keep.fire.str.title(), "addr": keep.SITEADDRESS.str.strip().str.title(),
        "damage": keep.damage, "destroyed": keep.destroyed.astype(int), "inside": keep.inside_perimeter.astype(int),
        "yr": keep.year_built.round(0).astype("Int64"), "zone": keep.fhsz_in_effect,
        "near_m": keep.dist_nearest_building_m.round(1), "wild_m": keep.dist_wildland_m.round(0),
        "n50": keep.n_buildings_50m, "slope": keep.slope_deg.round(1),
        "risk": keep.oof_hgb.round(3), "risk_xfire": keep.xfire_hgb.round(3), "risk_logit": keep.oof_logistic.round(3),
    }, geometry=gpd.GeoSeries(keep.sample_point, crs=b.crs), crs=b.crs)
    write_geojson(pts, "buildings.geojson")


def web_perimeters():
    per = gpd.read_parquet(interim("01_perimeters"))
    per = per.assign(geometry=per.simplify(2), acres=per.area / 4046.856)[["FIRE_NAME", "INC_NUM", "acres", "geometry"]]
    per["acres"] = per.acres.round(0)
    write_geojson(per, "perimeters.geojson")


def fuel_cogs():
    c = cfg()
    per = gpd.read_parquet(interim("01_perimeters"))
    for r in per.itertuples():
        src_path = RAW / f"landfire_fbfm40/lf2023_fbfm40_{r.FIRE_NAME.lower()}.tif"
        area = gpd.GeoSeries([r.geometry.buffer(c["study_area"]["clip_buffer_m"])], crs=per.crs)
        with rasterio.open(src_path) as src:
            clipped, ct = rio_mask(src, area.to_crs(src.crs), crop=True, nodata=src.nodata)
            prof = src.profile
        h, w = clipped.shape[1:]
        left, top = ct.c, ct.f
        bounds = (left, top + ct.e * h, left + ct.a * w, top)
        dt, dw, dh = calculate_default_transform(prof["crs"], GEOGRAPHIC, w, h, *bounds)
        dst = np.full((dh, dw), prof["nodata"], dtype=clipped.dtype)
        reproject(clipped[0], dst, src_transform=ct, src_crs=prof["crs"], dst_transform=dt, dst_crs=GEOGRAPHIC,
                  src_nodata=prof["nodata"], dst_nodata=prof["nodata"], resampling=Resampling.nearest)
        out = WEB / f"fuel_{r.FIRE_NAME.lower()}.tif"
        with MemoryFile() as mem:
            with mem.open(driver="GTiff", width=dw, height=dh, count=1, dtype=dst.dtype, crs=GEOGRAPHIC,
                          transform=dt, nodata=prof["nodata"]) as tmp:
                tmp.write(dst, 1)
                tmp.update_tags(source="LANDFIRE LF2023 FBFM40 (CONUS image service), clipped to the CAL FIRE "
                                       f"perimeter + {c['study_area']['clip_buffer_m']} m, nearest-neighbor to EPSG:4326",
                                burnable="codes 101-204", nonburnable="91 urban, 93 agriculture, 98 water, 99 barren")
                rasterio.shutil.copy(tmp, out, driver="COG", compress="DEFLATE", overview_resampling="nearest")
        with rasterio.open(out) as chk:
            a = chk.read(1)
            log(f"{out.name}: {chk.width}x{chk.height}, {chk.res[0] * 1e5:.1f}e-5 deg cells, "
                f"layout {chk.tags(ns='IMAGE_STRUCTURE').get('LAYOUT')}, codes {sorted(set(np.unique(a)) - {prof['nodata']})[:6]}...")


def main():
    WEB.mkdir(parents=True, exist_ok=True)
    b = building_table()
    web_buildings(b)
    web_perimeters()
    fuel_cogs()


if __name__ == "__main__":
    main()
