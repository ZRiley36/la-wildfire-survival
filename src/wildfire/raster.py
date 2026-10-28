"""Raster helpers. Nothing here knows about fires, so another hazard or city can reuse it.

sample()          value of the cell under each point, read in the raster's own CRS (no warping)
terrain()         elevation, slope and aspect. Slope needs a grid in meters, so this is the one place a
                  raster is warped: the DEM window around the study area goes to the project CRS at 10 m
                  (bilinear), and slope/aspect come from Horn's 3x3 method on that grid
focal_share()     share of a circular buffer that's in a class, respecting partial cells by supersampling
patches()         polygons of contiguous cells in a class, at least a minimum size
"""
import numpy as np
import rasterio
from rasterio.features import shapes
from rasterio.warp import Resampling, calculate_default_transform, reproject
from scipy import ndimage
from scipy.signal import fftconvolve
from shapely.geometry import shape


def sample(path_or_ds, points, band=1):
    """Cell values under `points` (a GeoSeries in any CRS), read in the raster's CRS. Nodata -> NaN."""
    ds = rasterio.open(path_or_ds) if isinstance(path_or_ds, (str, bytes)) or hasattr(path_or_ds, "as_posix") else path_or_ds
    pts = points.to_crs(ds.crs)
    vals = np.array([v[0] for v in ds.sample([(p.x, p.y) for p in pts], indexes=band)], dtype="float64")
    if ds.nodata is not None:
        vals[vals == ds.nodata] = np.nan
    return vals


def sample_array(arr, transform, points):
    """Like sample(), for an in-memory array whose transform matches the points' CRS."""
    rows, cols = rasterio.transform.rowcol(transform, points.x.values, points.y.values)
    rows, cols = np.asarray(rows), np.asarray(cols)
    ok = (rows >= 0) & (rows < arr.shape[0]) & (cols >= 0) & (cols < arr.shape[1])
    out = np.full(len(points), np.nan)
    out[ok] = arr[rows[ok], cols[ok]]
    return out


def warp_window(src_path, bounds_dst, dst_crs, res, resampling=Resampling.bilinear):
    """Cut `bounds_dst` (in dst_crs) out of a raster and warp it onto a `res` grid in dst_crs."""
    with rasterio.open(src_path) as src:
        left, bottom, right, top = bounds_dst
        width, height = int(np.ceil((right - left) / res)), int(np.ceil((top - bottom) / res))
        transform = rasterio.transform.from_origin(left, top, res, res)
        out = np.full((height, width), np.nan, dtype="float32")
        reproject(rasterio.band(src, 1), out, src_nodata=src.nodata, dst_transform=transform, dst_crs=dst_crs,
                  dst_nodata=np.nan, resampling=resampling)
    return out, transform


def horn_slope_aspect(z, res):
    """Slope (degrees) and aspect (degrees clockwise from north, downslope direction) by Horn (1981)."""
    p = np.pad(z, 1, mode="edge")
    a, b, c = p[:-2, :-2], p[:-2, 1:-1], p[:-2, 2:]
    d, f = p[1:-1, :-2], p[1:-1, 2:]
    g, h, i = p[2:, :-2], p[2:, 1:-1], p[2:, 2:]
    dzdx = ((c + 2 * f + i) - (a + 2 * d + g)) / (8 * res)   # east positive
    dzdy = ((g + 2 * h + i) - (a + 2 * b + c)) / (8 * res)   # south positive (rows increase southward)
    slope = np.degrees(np.arctan(np.hypot(dzdx, dzdy)))
    # downslope vector is (east: -dz/dx, north: +dzdy), so its compass bearing is atan2(-dzdx, dzdy)
    aspect = np.degrees(np.arctan2(-dzdx, dzdy)) % 360
    aspect[(dzdx == 0) & (dzdy == 0)] = np.nan
    return slope, aspect


def disk(radius_cells):
    r = int(np.ceil(radius_cells))
    y, x = np.mgrid[-r:r + 1, -r:r + 1]
    k = (x ** 2 + y ** 2 <= radius_cells ** 2).astype("float32")
    return k / k.sum()


def focal_share(mask, transform, radius_m, supersample):
    """Share of a circle of `radius_m` around every point that's True in `mask`.

    The mask is split into supersample x supersample sub-cells first, so a 30 m buffer around a point in the
    corner of a 30 m cell counts the neighboring cells it really covers. Returns (share grid, its transform).
    """
    fine = np.kron(mask.astype("float32"), np.ones((supersample, supersample), dtype="float32"))
    cell = transform.a / supersample
    share = fftconvolve(fine, disk(radius_m / cell), mode="same")
    fine_t = rasterio.transform.Affine(cell, 0, transform.c, 0, transform.e / supersample, transform.f)
    return np.clip(share, 0, 1), fine_t


def patches(mask, transform, crs, min_cells):
    """Polygons of 8-connected True regions with at least `min_cells` cells (a GeoSeries in `crs`)."""
    import geopandas as gpd
    labels, n = ndimage.label(mask, structure=np.ones((3, 3)))
    sizes = ndimage.sum(mask, labels, index=np.arange(1, n + 1))
    keep = np.isin(labels, np.flatnonzero(sizes >= min_cells) + 1)
    geoms = [shape(g) for g, v in shapes(keep.astype("uint8"), mask=keep, transform=transform) if v == 1]
    return gpd.GeoSeries(geoms, crs=crs), int(n), int((sizes >= min_cells).sum())
