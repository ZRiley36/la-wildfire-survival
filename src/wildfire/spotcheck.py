"""Hand checks: re-derive a few buildings straight from the raw files, without the pipeline's code paths.

  outcome     raw DINS master, matched by GLOBALID
  footprint   brute-force point-in-polygon over the raw footprint GeoJSON
  year built  raw DINS YEARBUILT, and the raw parcel YearBuilt1 by AIN
  elevation   the raw DEM read directly at the point (EPSG:4269)
  fuel        the raw LANDFIRE clip read directly at the point (EPSG:5070)
  zone        point-in-polygon against the raw LA County and SRA 2023 zone layers
  neighbor    brute-force minimum distance to every other raw footprint within 200 m

python -m wildfire.spotcheck
"""
import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from shapely.geometry import Point

from wildfire.config import RAW, cfg, interim

SEED = 11


def main():
    c = cfg()
    b = gpd.read_parquet(interim("04_features"))
    m = b[b.pop_main]
    picks = pd.concat([m[(m.fire == f) & (m.destroyed == d)].sample(1, random_state=SEED)
                       for f in ["EATON", "PALISADES"] for d in [True, False]]
                      + [m[m.footprint_match.str.startswith("nearest")].sample(1, random_state=SEED),
                         m[m.multi_building_parcel].sample(1, random_state=SEED)])
    dins = gpd.read_file(RAW / "dins_master/dins_master.geojson").set_index("GLOBALID")
    fps = gpd.read_file(RAW / "buildings_2023_dins/buildings_2023_dins.geojson")
    fps = fps[fps.CODE == "Building"]
    fps3 = fps.to_crs(c["crs"])
    fps3["geometry"] = fps3.make_valid()
    parcels = gpd.read_file(RAW / "parcels_dins/parcels_dins.geojson", columns=["AIN_1", "YearBuilt1"]).set_index("AIN_1")
    la = gpd.read_file(RAW / "fhsz_lacounty/fhsz_lacounty.geojson").to_crs(4326)
    sra = gpd.read_file(RAW / "fhsz_sra_2023/fhsz_sra_2023.geojson").to_crs(4326)
    dem = rasterio.open(RAW / "usgs_3dep/USGS_13_n35w119_20240207.tif")
    rows = []
    for _, r in picks.iterrows():
        raw = dins.loc[r.GLOBALID]
        pt4326 = gpd.GeoSeries([r.sample_point], crs=b.crs).to_crs(4326).iloc[0]
        dpt = gpd.GeoSeries([r.geometry], crs=b.crs).to_crs(4326).iloc[0]
        hit = fps[fps.contains(dpt)]
        lf = rasterio.open(RAW / f"landfire_fbfm40/lf2023_fbfm40_{r.fire.lower()}.tif")
        lfpt = gpd.GeoSeries([pt4326], crs=4326).to_crs(lf.crs).iloc[0]
        own = fps3[fps3.BLD_ID == r.BLD_ID] if pd.notna(r.BLD_ID) else fps3.iloc[0:0]
        shape = own.geometry.iloc[0] if len(own) else r.geometry
        near = fps3[fps3.distance(shape) <= 200]
        near = near[~near.geometry.apply(lambda g: g.equals(shape))]
        sra_hit = sra[sra.contains(pt4326)].FHSZ_Description.tolist()
        zone = sra_hit[0] if sra_hit else (la[la.contains(pt4326)].HAZ_CLASS.tolist() or ["Not in a zone"])[0]
        rows.append({
            "dins_id": r.dins_id, "fire": r.fire,
            "damage pipeline": r.damage, "damage raw": raw.DAMAGE.split()[0].replace("No", "No Damage"),
            "footprint pipeline": r.footprint_match, "point in raw footprint": len(hit),
            "year pipeline": r.year_built, "year raw DINS": raw.YEARBUILT,
            "year raw parcel": parcels.YearBuilt1.get(r.apn),
            "elev pipeline": round(r.elevation_m, 1), "elev raw": round(float(next(dem.sample([(pt4326.x, pt4326.y)]))[0]), 1),
            "fuel pipeline": r.fuel_code, "fuel raw": int(next(lf.sample([(lfpt.x, lfpt.y)]))[0]),
            "zone pipeline": r.fhsz_in_effect, "zone raw": zone,
            "nearest bldg pipeline": round(r.dist_nearest_building_m, 2),
            "nearest bldg raw": round(float(near.distance(shape).min()), 2) if len(near) else None,
        })
    out = pd.DataFrame(rows)
    pd.set_option("display.width", 250)
    print(out.T.to_string())
    ok = ((out["damage pipeline"] == out["damage raw"]) & (out["elev pipeline"] == out["elev raw"])
          & (out["fuel pipeline"] == out["fuel raw"]) & (out["zone pipeline"] == out["zone raw"])
          & np.isclose(out["nearest bldg pipeline"], out["nearest bldg raw"], atol=0.05))
    print(f"\n{ok.sum()} of {len(out)} buildings agree on outcome, elevation, fuel, zone and nearest building")


if __name__ == "__main__":
    main()
