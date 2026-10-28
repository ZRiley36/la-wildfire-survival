"""Download every raw source into data/raw/<name>/ with a SOURCE.txt next to it.

Run once: python -m wildfire.download [step ...] [--force]
Raw files are never edited after this. Filtering happens server-side (fire names, an area of
interest around both fires) and each SOURCE.txt says exactly what was asked for.
"""
import argparse
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"
CALFIRE = "https://services1.arcgis.com/jUJYIo9tSA7EHvfZ/arcgis/rest/services"
LACO = "https://services.arcgis.com/RmCCgQtiZLDCtblq/ArcGIS/rest/services"
# One box around both fires with a few km of margin (lon/lat). Used for the zone layers.
AOI = (-118.80, 33.98, -117.95, 34.30)
FIRE_BUFFER_M = 3000  # raster clips extend this far past each perimeter

session = requests.Session()
session.headers["User-Agent"] = "la-wildfire-survival portfolio project"


def write_source(folder, url, note, rows=None):
    lines = [f"url: {url}", f"fetched: {datetime.now(timezone.utc).isoformat(timespec='seconds')}"]
    if rows is not None:
        lines.append(f"rows: {rows}")
    lines.append(f"note: {note}")
    (folder / "SOURCE.txt").write_text("\n".join(lines) + "\n")


def fetch(url, dest, params=None):
    dest.parent.mkdir(parents=True, exist_ok=True)
    with session.get(url, params=params, stream=True, timeout=900) as r:
        r.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
        # ArcGIS image services report errors as a 200 with a JSON body (even labeled image/tiff),
        # so check the TIFF signature before accepting the file
        if dest.suffix == ".tif" and tmp.read_bytes()[:4] not in (b"II*\x00", b"MM\x00*"):
            msg = tmp.read_bytes()[:300]
            tmp.unlink()
            raise RuntimeError(f"{url} did not return a TIFF: {msg!r}")
        tmp.rename(dest)
    print(f"  {dest.relative_to(RAW)}  {dest.stat().st_size / 1e6:.1f} MB")
    return dest


def retry(fn, attempts=6, wait=20):
    """LANDFIRE's image service fails intermittently ("General function failure"), so retry."""
    for i in range(attempts):
        try:
            return fn()
        except RuntimeError as e:
            if i == attempts - 1:
                raise
            print(f"  retry {i + 1}/{attempts - 1} in {wait * (i + 1)} s: {str(e)[:120]}")
            time.sleep(wait * (i + 1))


def arcgis_layer(url, where="1=1", bbox=None, page=2000):
    """Every feature of a FeatureServer layer as a GeoJSON FeatureCollection (EPSG:4326)."""
    feats, offset = [], 0
    while True:
        params = {"where": where, "outFields": "*", "f": "geojson", "outSR": 4326,
                  "resultOffset": offset, "resultRecordCount": page, "orderByFields": "OBJECTID"}
        if bbox:
            params.update(geometry=",".join(map(str, bbox)), geometryType="esriGeometryEnvelope", inSR=4326,
                          spatialRel="esriSpatialRelIntersects")
        r = session.post(f"{url}/query", data=params, timeout=900)
        r.raise_for_status()
        d = r.json()
        if "error" in d:
            raise RuntimeError(f"{url}: {d['error']}")
        feats += d["features"]
        more = d.get("exceededTransferLimit") or d.get("properties", {}).get("exceededTransferLimit")
        if not more or not d["features"]:
            break
        offset += len(d["features"])
    return {"type": "FeatureCollection", "features": feats}


def save_layer(name, url, note, where="1=1", bbox=None, force=False):
    d = RAW / name
    out = d / f"{name}.geojson"
    if out.exists() and not force:
        return
    fc = arcgis_layer(url, where, bbox)
    d.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(fc))
    n = len(fc["features"])
    print(f"  {out.relative_to(RAW)}  {n:,} features, {out.stat().st_size / 1e6:.1f} MB")
    extra = f" where: {where}." if where != "1=1" else ""
    extra += f" bbox (EPSG:4326): {bbox}." if bbox else ""
    write_source(d, url, note + extra + " Saved as GeoJSON, so coordinates are EPSG:4326.", n)


def dins(force):
    save_layer("dins_master", f"{CALFIRE}/POSTFIRE_MASTER_DATA_SHARE/FeatureServer/0",
               "CAL FIRE Damage Inspection (DINS) Data, statewide master. Filtered to the two fires.",
               where="INCIDENTNAME IN ('Palisades','Eaton') AND INCIDENTSTARTDATE >= DATE '2025-01-01'", force=force)
    for fire in ["Palisades", "Eaton"]:
        save_layer(f"dins_public_{fire.lower()}", f"{CALFIRE}/DINS_2025_{fire}_Public_View/FeatureServer/0",
                   f"CAL FIRE DINS 2025 {fire} Public View (damage and structure type only). Kept as a cross-check.",
                   force=force)


def county(force):
    save_layer("parcels_dins", f"{LACO}/2025_Parcels_with_DINS_data/FeatureServer/5",
               "LA County 2025 Parcels with DINS data (Eaton and Palisades). One row per parcel, with the most "
               "damaged structure's DINS result.", force=force)
    save_layer("buildings_2023_dins", f"{LACO}/Buildings_2023_with_DINS/FeatureServer/4",
               "LA County Buildings_2023_with_DINS: 2023 LARIAC building footprints within 1/4 mile of the "
               "perimeters, with DINS as of 2025-01-27.", force=force)


def perimeters(force):
    save_layer("perimeters_calfire", f"{CALFIRE}/2025_California_Fire_Perimeters_View/FeatureServer/0",
               "CAL FIRE FRAP 2025 fire perimeters.", where="FIRE_NAME IN ('PALISADES','EATON')", force=force)
    save_layer("perimeters_lacounty",
               f"{LACO}/Palisades_and_Eaton_Dissolved_Fire_Perimeters_as_of_20250121/FeatureServer/0",
               "LA County Palisades and Eaton dissolved fire perimeters as of 2025-01-21. Kept for comparison.",
               force=force)


def hazard_zones(force):
    layers = {
        "fhsz_lacounty": (f"{LACO}/FHSZ_for_LACo/FeatureServer/0",
                          "LA County FHSZ layer (CAL FIRE 2007 SRA / 2007-2011 LRA-era schema, field FID_c19fhs)."),
        "fhsz_sra_2023": (f"{CALFIRE}/FHSZSRA_23_3/FeatureServer/0",
                          "CAL FIRE FHSZ in State Responsibility Areas, 2023 map (in effect April 1, 2024)."),
        "fhsz_lra_2025": (f"{CALFIRE}/FHSALRA25_v1_All/FeatureServer/0",
                          "CAL FIRE 2025 recommended FHSZ in Local Responsibility Areas, map dated March 24, 2025 "
                          "(after the fires)."),
        "vhfhsz_la_city": ("https://services5.arcgis.com/7nsPwEMP38bSkCjy/arcgis/rest/services/"
                           "Very_High_Fire_Hazard_Severity_Zones/FeatureServer/0",
                           "City of Los Angeles Very High Fire Hazard Severity Zones (city hub, 2019 item)."),
    }
    for name, (url, note) in layers.items():
        save_layer(name, url, note, bbox=AOI, force=force)


def fire_boxes(crs):
    """Bounding box of each fire perimeter, buffered, in the given CRS."""
    import geopandas as gpd
    p = gpd.read_file(RAW / "perimeters_calfire/perimeters_calfire.geojson").to_crs(crs)
    return {r.FIRE_NAME.lower(): r.geometry.buffer(FIRE_BUFFER_M).bounds for r in p.itertuples()}


def landfire(force):
    """LF2023 FBFM40 at native 30 m in EPSG:5070, one clip per fire, from LANDFIRE's image service."""
    svc = "https://lfps.usgs.gov/arcgis/rest/services/Landfire_LF2023/LF2023_FBFM40_CONUS/ImageServer"
    info = session.get(svc, params={"f": "json"}, timeout=120).json()
    x0, y0, cell = info["extent"]["xmin"], info["extent"]["ymax"], info["pixelSizeX"]

    def snap(v, origin, rnd):
        return origin + rnd((v - origin) / cell) * cell

    d = RAW / "landfire_fbfm40"
    for fire, (xmin, ymin, xmax, ymax) in fire_boxes(5070).items():
        out = d / f"lf2023_fbfm40_{fire}.tif"
        if out.exists() and not force:
            continue
        # snap to the service's own 30 m grid so no cell is resampled
        bx = (snap(xmin, x0, math.floor), snap(ymin, y0, math.floor), snap(xmax, x0, math.ceil), snap(ymax, y0, math.ceil))
        w, h = round((bx[2] - bx[0]) / cell), round((bx[3] - bx[1]) / cell)
        retry(lambda: fetch(f"{svc}/exportImage", out, params={
            "bbox": ",".join(map(str, bx)), "bboxSR": 5070, "imageSR": 5070, "size": f"{w},{h}", "format": "tiff",
            "pixelType": "S16", "noData": -9999, "interpolation": "RSP_NearestNeighbor", "f": "image"}))
    write_source(d, svc, "LANDFIRE 2023 (LF 2.4.0) 40 Scott and Burgan Fire Behavior Fuel Models, CONUS image "
                 f"service. exportImage per fire: perimeter bounds + {FIRE_BUFFER_M} m, snapped to the native 30 m "
                 "grid in EPSG:5070, nearest neighbor, so values are unresampled.")


def dem(force):
    d = RAW / "usgs_3dep"
    url = ("https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/historical/n35w119/"
           "USGS_13_n35w119_20240207.tif")
    out = d / "USGS_13_n35w119_20240207.tif"
    if not out.exists() or force:
        fetch(url, out)
    write_source(d, url, "USGS 3DEP 1/3 arc-second DEM, 1x1 degree tile n35w119 (34-35N, 118-119W), version "
                 "published 2024-02-07: the latest before the fires.")


def block_groups(force):
    d = RAW / "census"
    url = "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_06_bg_500k.zip"
    out = d / "cb_2024_06_bg_500k.zip"
    if not out.exists() or force:
        fetch(url, out)
    write_source(d, url, "Census 2024 cartographic boundary block groups, California, for aggregates.")


STEPS = {"dins": dins, "county": county, "perimeters": perimeters, "hazard_zones": hazard_zones,
         "landfire": landfire, "dem": dem, "block_groups": block_groups}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("only", nargs="*", help=f"steps to run (default: all): {', '.join(STEPS)}")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    unknown = set(args.only) - set(STEPS)
    if unknown:
        ap.error(f"unknown steps: {', '.join(sorted(unknown))}")
    for name in args.only or STEPS:
        print(name)
        STEPS[name](args.force)


if __name__ == "__main__":
    main()
