import numpy as np
import pytest
from rasterio.transform import from_origin

from wildfire.raster import focal_share, horn_slope_aspect, patches


def ramp(direction, n=7, res=10.0, rise=1.0):
    """A plane rising `rise` m per cell toward `direction` ('east' or 'south')."""
    y, x = np.mgrid[0:n, 0:n].astype(float)
    return (x if direction == "east" else y) * rise


@pytest.mark.parametrize("direction, rises_toward, faces", [("east", "east", 270), ("south", "south", 0)])
def test_aspect_faces_downhill(direction, rises_toward, faces):
    slope, aspect = horn_slope_aspect(ramp(direction), 10.0)
    assert aspect[3, 3] == pytest.approx(faces)
    assert slope[3, 3] == pytest.approx(np.degrees(np.arctan(0.1)))


def test_flat_ground_has_no_aspect():
    slope, aspect = horn_slope_aspect(np.zeros((5, 5)), 10.0)
    assert slope[2, 2] == 0 and np.isnan(aspect[2, 2])


def test_focal_share_all_and_none():
    t = from_origin(0, 300, 30, 30)
    full, _ = focal_share(np.ones((10, 10), bool), t, 30, 6)
    empty, _ = focal_share(np.zeros((10, 10), bool), t, 30, 6)
    assert full[30, 30] == pytest.approx(1.0, abs=1e-5) and empty[30, 30] == pytest.approx(0.0, abs=1e-6)


def test_focal_share_half_plane():
    """Left half burnable: a circle centred on the boundary is half burnable."""
    m = np.zeros((20, 20), bool)
    m[:, :10] = True
    share, ft = focal_share(m, from_origin(0, 600, 30, 30), 60, 6)
    assert share[60, 60] == pytest.approx(0.5, abs=0.05)


def test_patches_drop_small_regions():
    m = np.zeros((10, 10), bool)
    m[0:4, 0:4] = True     # 16 cells
    m[8, 8] = True         # 1 cell
    polys, n, kept = patches(m, from_origin(0, 300, 30, 30), "EPSG:3310", min_cells=5)
    assert n == 2 and kept == 1 and polys.area.sum() == pytest.approx(16 * 900)
