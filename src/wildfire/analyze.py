"""Step 6: destruction rates by group, for the main population (inside the perimeters, residential, accessible).

Writes data/processed/aggregates/*.csv: by community, block group, hazard zone (in effect and 2025 LRA),
build era, and neighbor-distance bins, each split by fire.
"""
import geopandas as gpd
import numpy as np
import pandas as pd

from wildfire.config import PROCESSED, interim

ERAS = [0, 1939, 1959, 1979, 1999, 2008, 2100]
ERA_LABELS = ["before 1940", "1940-1959", "1960-1979", "1980-1999", "2000-2008", "2009 and later"]
NEIGHBOR_BINS = [-0.01, 0, 2, 5, 10, 20, np.inf]
NEIGHBOR_LABELS = ["touching (0 m)", "0-2 m", "2-5 m", "5-10 m", "10-20 m", "over 20 m"]


def log(msg):
    print(f"  {msg}")


def rates(df, by):
    g = df.groupby(by, observed=True)
    out = pd.DataFrame({"buildings": g.size(), "destroyed": g.destroyed.sum(),
                        "destroyed_pct": (g.destroyed.mean() * 100).round(1)})
    return out.reset_index()


def main():
    b = gpd.read_parquet(interim("04_features"))
    m = b[b.pop_main].copy()
    m["build_era"] = pd.cut(m.year_built, ERAS, labels=ERA_LABELS)
    m["neighbor_distance"] = pd.cut(m.dist_nearest_building_m, NEIGHBOR_BINS, labels=NEIGHBOR_LABELS)
    out = PROCESSED / "aggregates"
    out.mkdir(parents=True, exist_ok=True)
    tables = {
        "by_community": ["fire", "community"],
        "by_block_group": ["fire", "block_group"],
        "by_hazard_zone_in_effect": ["fire", "fhsz_in_effect"],
        "by_hazard_zone_lra_2025_postfire": ["fire", "fhsz_lra_2025"],
        "by_build_era": ["fire", "build_era"],
        "by_neighbor_distance": ["fire", "neighbor_distance"],
    }
    for name, by in tables.items():
        t = rates(m, by)
        if name in ("by_community", "by_block_group"):
            t = t.sort_values(["fire", "buildings"], ascending=[True, False])
        t.to_csv(out / f"{name}.csv", index=False)
        show = t if name not in ("by_block_group",) else t[t.buildings >= 100]
        log(f"{name} ({len(t)} rows{', showing groups with 100+ buildings' if name == 'by_block_group' else ''}):\n"
            f"{show.head(40).to_string(index=False)}")
    bg = rates(m, ["block_group"])
    bg = bg[bg.buildings >= 30]
    log(f"block groups with 30+ buildings: {len(bg)}, destroyed share ranges "
        f"{bg.destroyed_pct.min():.0f}%-{bg.destroyed_pct.max():.0f}% (median {bg.destroyed_pct.median():.0f}%)")


if __name__ == "__main__":
    main()
