import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Point, box

from wildfire.apn import normalize_apn
from wildfire.evaluate import assign_block_folds, block_ids, splits
from wildfire.features import neighbor_stats
from wildfire.join import points_to_footprints


# ---------- APN normalization ----------

@pytest.mark.parametrize("raw, expected", [
    ("4420030015", "4420030015"),
    ("4420-030-015", "4420030015"),
    (" 4420 030 015 ", "4420030015"),
    (4420030015, "4420030015"),
    (4420030015.0, "4420030015"),
    ("0420030015", "0420030015"),     # leading zero kept
])
def test_normalize_apn(raw, expected):
    assert normalize_apn(raw) == expected


@pytest.mark.parametrize("raw", [None, float("nan"), "", "442003001", "44200300150", "ABCD-030-015"])
def test_normalize_apn_rejects(raw):
    assert normalize_apn(raw) is None


# ---------- point-to-footprint join ----------

def footprints():
    return gpd.GeoDataFrame({"fp_id": [10, 11, 12]},
                            geometry=[box(0, 0, 10, 10), box(20, 0, 30, 10), box(5, 20, 8, 23)], crs="EPSG:3310")


def test_point_inside_footprint():
    pts = gpd.GeoDataFrame(geometry=[Point(5, 5), Point(25, 5)], crs="EPSG:3310")
    fp_id, how = points_to_footprints(pts, footprints(), max_m=5)
    assert fp_id.tolist() == [10, 11] and how.tolist() == ["within", "within"]


def test_point_snaps_to_nearest_within_limit():
    pts = gpd.GeoDataFrame(geometry=[Point(13, 5), Point(15, 5), Point(50, 50)], crs="EPSG:3310")
    fp_id, how = points_to_footprints(pts, footprints(), max_m=5)
    assert fp_id.iloc[0] == 10                  # 3 m from footprint 10
    assert fp_id.iloc[1] == 10                  # 5 m from both 10 and 11: either is fine, but it must match
    assert np.isnan(fp_id.iloc[2]) and how.iloc[2] == "none"   # too far from everything


def test_point_on_shared_wall_takes_smaller_footprint():
    f = gpd.GeoDataFrame({"fp_id": [1, 2]}, geometry=[box(0, 0, 10, 10), box(2, 2, 4, 4)], crs="EPSG:3310")
    fp_id, _ = points_to_footprints(gpd.GeoDataFrame(geometry=[Point(3, 3)], crs="EPSG:3310"), f, max_m=5)
    assert fp_id.iloc[0] == 2


# ---------- neighbor distance ----------

def test_neighbor_stats_toy():
    # four 2x2 m squares in a row, 3 m gaps, plus one far away
    squares = [box(x, 0, x + 2, 2) for x in (0, 5, 10, 15)] + [box(500, 0, 502, 2)]
    s = neighbor_stats(squares, squares, radii=[3, 10], target_ids=range(5), other_ids=range(5))
    assert s["dist"][:4].tolist() == pytest.approx([3, 3, 3, 3])
    assert s["dist"][4] == pytest.approx(483)   # 500 - 17, beyond the 200 m search reach, found the slow way
    assert s["n_3"].tolist() == [1, 2, 2, 1, 0]
    assert s["n_10"].tolist() == [2, 3, 3, 2, 0]


def test_neighbor_stats_excludes_self_only():
    sq = [box(0, 0, 2, 2), box(0, 0, 2, 2)]      # two identical outlines (e.g. a duplicated footprint)
    s = neighbor_stats([sq[0]], sq, radii=[1], target_ids=[0], other_ids=[0, 1])
    assert s["dist"][0] == 0 and s["n_1"][0] == 1


# ---------- spatial folds ----------

def test_blocks_never_cross_folds():
    rng = np.random.default_rng(0)
    pts = gpd.GeoSeries([Point(x, y) for x, y in rng.uniform(0, 5000, (3000, 2))], crs="EPSG:3310")
    df = pd.DataFrame({"block": block_ids(pts, 500)})
    df["fold"] = assign_block_folds(df.block.values, 5, seed=1)
    assert df.groupby("block").fold.nunique().max() == 1
    c = {"validation": {"n_folds": 5}}
    for _, tr, te in splits(df, "block_cv", c):
        assert not set(df.block[tr]) & set(df.block[te])
        assert tr.sum() + te.sum() == len(df)
    sizes = np.bincount(df.fold)
    assert sizes.max() - sizes.min() <= df.block.value_counts().max()


def test_folds_are_reproducible():
    blocks = np.array([f"b{i % 37}" for i in range(500)])
    assert (assign_block_folds(blocks, 5, 7) == assign_block_folds(blocks, 5, 7)).all()


def test_cross_fire_split_is_disjoint():
    df = pd.DataFrame({"fire": ["EATON"] * 4 + ["PALISADES"] * 3})
    for _, tr, te in splits(df, "cross_fire", {}):
        assert not (tr & te).any() and set(df.fire[tr]) != set(df.fire[te])
