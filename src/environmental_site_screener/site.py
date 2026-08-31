"""Validation and normalisation of candidate site boundaries.

The screening MVP analyses one England site polygon at a time. :func:`validate_site`
is the single entry point that turns a caller-supplied GeoDataFrame into a clean,
single-feature GeoDataFrame in the analytical CRS (EPSG:27700 / British National
Grid), ready for intersection, area and distance operations.
"""

from __future__ import annotations

import warnings

import geopandas as gpd
from shapely import make_valid

ANALYTICAL_CRS = "EPSG:27700"

_ALLOWED_GEOM_TYPES = ("Polygon", "MultiPolygon")


def validate_site(site: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Validate a candidate site boundary and return it in the analytical CRS.

    Parameters
    ----------
    site:
        A single-feature GeoDataFrame holding the candidate site polygon, with a
        defined CRS.

    Returns
    -------
    geopandas.GeoDataFrame
        A copy of ``site`` with exactly one row, a valid non-empty
        Polygon/MultiPolygon geometry, reprojected to EPSG:27700. Non-geometry
        attribute columns are preserved.

    Raises
    ------
    TypeError
        If ``site`` is not a GeoDataFrame.
    ValueError
        If ``site`` does not have exactly one row, has no CRS, has a missing,
        empty, non-polygonal or unrepairable geometry, or has non-positive area
        after reprojection.

    Warns
    -----
    UserWarning
        If the input geometry is invalid and repair via
        :func:`shapely.make_valid` is attempted.
    """
    if not isinstance(site, gpd.GeoDataFrame):
        raise TypeError(
            f"site must be a geopandas.GeoDataFrame, got {type(site).__name__}"
        )

    row_count = len(site)
    if row_count == 0:
        raise ValueError("site is empty; exactly one site feature is required")
    if row_count > 1:
        raise ValueError(
            f"site has {row_count} rows; exactly one site feature is required"
        )

    if site.crs is None:
        raise ValueError(
            "site has no CRS defined; a CRS is required to reproject to "
            f"{ANALYTICAL_CRS}"
        )

    validated = site.copy()
    geom_column = validated.geometry.name
    geometry = validated.geometry.iloc[0]

    if geometry is None or geometry.is_empty:
        raise ValueError("site geometry is missing or empty")

    if geometry.geom_type not in _ALLOWED_GEOM_TYPES:
        raise ValueError(
            f"site geometry must be a Polygon or MultiPolygon; got {geometry.geom_type}"
        )

    if not geometry.is_valid:
        warnings.warn(
            "site geometry is invalid; attempting repair with shapely.make_valid()",
            UserWarning,
            stacklevel=2,
        )
        repaired = make_valid(geometry)
        if (
            repaired is None
            or repaired.is_empty
            or not repaired.is_valid
            or repaired.geom_type not in _ALLOWED_GEOM_TYPES
        ):
            raise ValueError(
                "site geometry is invalid and could not be repaired to a valid "
                "Polygon or MultiPolygon"
            )
        validated[geom_column] = gpd.GeoSeries(
            [repaired], index=validated.index, crs=validated.crs
        )

    if validated.crs.to_epsg() != 27700:
        validated = validated.to_crs(ANALYTICAL_CRS)

    if validated.geometry.iloc[0].area <= 0:
        raise ValueError(
            f"site geometry has non-positive area after reprojection to {ANALYTICAL_CRS}"
        )

    return validated
