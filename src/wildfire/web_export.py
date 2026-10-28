"""Step 9: data for the web map, written to web/data/ (committed, served by GitHub Pages).

buildings.geojson     one point per building (inside the perimeters plus the 300 ft band) with everything the
                      popup shows. Every prediction is out of sample.
footprints.geojson    the same buildings' outlines with only id, outcome and risk; the map looks up the rest
perimeters.geojson    CAL FIRE perimeters
zones.geojson         Very High hazard zones in effect in January 2025, clipped to the study area
fuel_<fire>.png       burnable LANDFIRE 2023 cells as a transparent overlay, with fuel_bounds.json for its corners
stats.json            headline numbers for the panel and the guide
Figures are copied to web/img/.
"""
import json
import shutil

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from PIL import Image

from wildfire.config import FIGURES, PROCESSED, ROOT, cfg, interim

OUT = ROOT / "web/data"
IMG = ROOT / "web/img"
GEO = "EPSG:4326"
FUEL_RGBA = (56, 176, 72, 120)  # burnable fuel, translucent green that reads on the dark basemap


def log(msg):
    print(f"  {msg}")


def round_coords(c):
    if isinstance(c[0], (int, float)):
        return [round(c[0], 6), round(c[1], 6)]
    return [round_coords(x) for x in c]


def write(g, name):
    gj = json.loads(g.to_crs(GEO).to_json(na="null", drop_id=True))
    for f in gj["features"]:
        if f["geometry"]:
            f["geometry"]["coordinates"] = round_coords(f["geometry"]["coordinates"])
    p = OUT / name
    p.write_text(json.dumps(gj, separators=(",", ":")))
    log(f"{name}: {len(g):,} features, {p.stat().st_size / 1e6:.2f} MB")


def outcome_group(d):
    return np.select([d == "Destroyed", d.isin(["Major", "Minor", "Affected"])], ["destroyed", "damaged"], "none")


def buildings():
    b = gpd.read_parquet(PROCESSED / "buildings_wildfire.parquet")
    b = b[b.pop_main | ((b.perimeter_band == "outside_0_300ft") & ~b.inaccessible)].copy()
    pt = gpd.GeoSeries.from_wkb(b.sample_point, crs=b.crs)
    props = pd.DataFrame({
        "id": b.dins_id, "fire": b.fire.str.title(), "addr": b.SITEADDRESS.fillna("").str.strip().str.title().str.replace(r", Ca(?= \d{5}|$)", ", CA", regex=True),
        "outcome": outcome_group(b.damage), "damage": b.damage, "inside": b.inside_perimeter.astype(int),
        "yr": b.year_built.round(0).astype("Int64"), "zone": b.fhsz_in_effect, "near_m": b.dist_nearest_building_m.round(1),
        "n50": b.n_buildings_50m.astype(int), "wild_m": b.dist_wildland_m.round(0).astype(int),
        "slope": b.slope_deg.round(1), "risk": b.oof_hgb.round(3), "risk_x": b.xfire_hgb.round(3),
        "comm": b.community.fillna(b.CITY.fillna("")),
    })
    write(gpd.GeoDataFrame(props, geometry=pt.values, crs=b.crs), "buildings.geojson")
    f = gpd.read_parquet(interim("04_features"))
    f = f[f.dins_id.isin(b.dins_id) & f.fp_id.notna()]
    shapes = gpd.GeoSeries(f["shape"], crs=f.crs).simplify(0.3)
    fp = gpd.GeoDataFrame({"id": f.dins_id.values,
                           "outcome": outcome_group(f.damage).tolist()},
                          geometry=shapes.values, crs=f.crs)
    fp = fp.merge(props[["id", "risk"]], on="id", how="left")
    write(fp, "footprints.geojson")
    return b


def perimeters_and_zones():
    per = gpd.read_parquet(interim("01_perimeters"))
    write(per.assign(geometry=per.simplify(3))[["FIRE_NAME", "geometry"]], "perimeters.geojson")
    z = gpd.read_parquet(interim("02_fhsz_in_effect"))
    z = z[z.fhsz == "Very High"].dissolve(by="source").reset_index()
    z["geometry"] = z.simplify(5)
    write(z[["source", "geometry"]], "zones.geojson")


def fuel():
    lo, hi = cfg()["features"]["burnable_codes"]
    bounds = {}
    for name in ["palisades", "eaton"]:
        with rasterio.open(PROCESSED / f"web/fuel_{name}.tif") as r:
            a = r.read(1)
            rgba = np.zeros((*a.shape, 4), dtype=np.uint8)
            rgba[(a >= lo) & (a <= hi)] = FUEL_RGBA
            Image.fromarray(rgba, "RGBA").save(OUT / f"fuel_{name}.png", optimize=True)
            l, btm, rt, t = r.bounds
            bounds[name] = [[l, t], [rt, t], [rt, btm], [l, btm]]
            log(f"fuel_{name}.png: {a.shape[1]}x{a.shape[0]}, burnable {((a >= lo) & (a <= hi)).mean():.0%} of cells")
    (OUT / "fuel_bounds.json").write_text(json.dumps(bounds))


def stats(b):
    m = json.loads((PROCESSED / "model_metrics.json").read_text())
    fm = m["main"]["block_cv"]["fold_mean"]
    xf = m["main"]["cross_fire"]["splits"]
    main = b[b.pop_main]
    s = {
        "buildings": int(len(main)), "destroyed": int(main.destroyed.sum()),
        "destroyed_pct": round(float(main.destroyed.mean()) * 100, 1),
        "by_fire": {f.title(): {"buildings": int(len(g)), "destroyed_pct": round(float(g.destroyed.mean()) * 100, 1)}
                    for f, g in main.groupby("fire")},
        "auc": {k: fm[k]["roc_auc"] for k in ["hgb", "logistic", "fhsz_in_effect", "fhsz_lra_2025_postfire"]},
        "brier": {k: fm[k]["brier"] for k in ["hgb", "logistic", "fhsz_in_effect", "constant"]},
        "auc_diff_ci": m["main"]["block_cv"]["auc_diff_ci95"]["hgb_minus_fhsz_in_effect"],
        "xfire": {k: {mm: v[mm]["roc_auc"] for mm in ["hgb", "logistic", "fhsz_in_effect"]} for k, v in xf.items()},
        "xfire_logistic_no_elev": {k: v["logistic"]["roc_auc"] for k, v in
                                   m["sensitivity_no_elevation"]["cross_fire"]["splits"].items()},
        "leakage_auc": {k: v["roc_auc"] for k, v in m["leakage_demo_not_main_model"].items()},
        "zone_rates_eaton": {z: round(float(g.destroyed.mean()) * 100, 1)
                             for z, g in main[main.fire == "EATON"].groupby("fhsz_in_effect")},
    }
    (OUT / "stats.json").write_text(json.dumps(s, indent=1))
    log(f"stats.json: {len(s)} keys")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    IMG.mkdir(parents=True, exist_ok=True)
    b = buildings()
    perimeters_and_zones()
    fuel()
    stats(b)
    for f in FIGURES.glob("*.png"):
        shutil.copy(f, IMG / f.name)
    log(f"copied {len(list(FIGURES.glob('*.png')))} figures to web/img/")


if __name__ == "__main__":
    main()
