"""Loader for the Natural England Sites of Special Scientific Interest (SSSI) source.

:func:`load_sssi` reads the official SSSI spatial file, checks that it matches the
characteristics this project relies on, and returns a trimmed GeoDataFrame with
only the fields the screening step needs. It performs no spatial analysis: no
intersections, distances, areas, scores or screening conclusions.

The loader is deliberately strict. The SSSI dataset is an authoritative national
source, so anything unexpected (wrong CRS, invalid geometry, missing or duplicated
identifiers) is treated as a reason to stop and inspect the source file rather
than something to silently work around or repair.
"""

from __future__ import annotations

import pathlib

import geopandas as gpd

SSSI_REQUIRED_COLUMNS = ("ref_code", "name", "measure")
SSSI_OUTPUT_COLUMNS = ("ref_code", "name", "measure", "geometry")
SSSI_EXPECTED_EPSG = 27700

_ALLOWED_GEOM_TYPES = ("Polygon", "MultiPolygon")


def load_sssi(path: str | pathlib.Path) -> gpd.GeoDataFrame:
    """Load and validate the Natural England SSSI source file.

    Parameters
    ----------
    path:
        Path to the SSSI spatial file (for example the official GeoPackage).

    Returns
    -------
    geopandas.GeoDataFrame
        The SSSI features with columns ``ref_code``, ``name``, ``measure`` and
        ``geometry`` (in that order), in EPSG:27700, with a clean ``RangeIndex``.

    Raises
    ------
    FileNotFoundError
        If ``path`` does not exist.
    ValueError
        If the source has no features, no active geometry column, is missing a
        required column, has no CRS, is not in EPSG:27700, contains null, empty,
        non-polygonal or invalid geometry, or has null/duplicate ``ref_code`` or
        null ``name`` values.

    Notes
    -----
    Read errors for an existing but unreadable source are allowed to propagate
    from GeoPandas/pyogrio unchanged. ``measure`` is required as a column but its
    values may be null. ``label``, ``hyperlink``, ``contact_no``,
    ``shape_length`` and ``shape_area`` are neither used nor returned.
    """
    source = pathlib.Path(path)
    if not source.exists():
        raise FileNotFoundError(f"SSSI source file not found: {source}")

    gdf = gpd.read_file(source)

    try:
        geom_col = gdf.geometry.name
    except AttributeError as exc:
        raise ValueError("SSSI source has no active geometry column") from exc

    if len(gdf) == 0:
        raise ValueError("SSSI source contains no features")

    missing = [c for c in SSSI_REQUIRED_COLUMNS if c not in gdf.columns]
    if missing:
        raise ValueError(f"SSSI source is missing required column(s): {missing}")

    if gdf.crs is None:
        raise ValueError("SSSI source has no CRS defined; expected EPSG:27700")

    epsg = gdf.crs.to_epsg()
    if epsg != SSSI_EXPECTED_EPSG:
        raise ValueError(
            f"SSSI source CRS is {gdf.crs.name!r} (EPSG:{epsg}); expected EPSG:27700. "
            "This loader does not reproject the authoritative SSSI source."
        )

    geometry = gdf.geometry

    null_count = int(geometry.isna().sum())
    if null_count:
        raise ValueError(f"SSSI source contains {null_count} null geometries")

    empty_count = int(geometry.is_empty.sum())
    if empty_count:
        raise ValueError(f"SSSI source contains {empty_count} empty geometries")

    bad_types = sorted(set(geometry.geom_type) - set(_ALLOWED_GEOM_TYPES))
    if bad_types:
        raise ValueError(
            f"SSSI source contains non-polygonal geometry (types found: {bad_types})"
        )

    invalid_count = int((~geometry.is_valid).sum())
    if invalid_count:
        raise ValueError(
            f"SSSI source contains {invalid_count} invalid geometries; "
            "this loader does not repair authoritative source data"
        )

    ref_code = gdf["ref_code"]
    null_ref = int(ref_code.isna().sum())
    if null_ref:
        raise ValueError(f"SSSI source has {null_ref} null ref_code values")

    duplicate_ref = int(ref_code.duplicated().sum())
    if duplicate_ref:
        examples = sorted(str(v) for v in ref_code[ref_code.duplicated(keep=False)].unique())
        raise ValueError(
            f"SSSI source has {duplicate_ref} duplicate ref_code values "
            f"(e.g. {examples[:5]})"
        )

    null_name = int(gdf["name"].isna().sum())
    if null_name:
        raise ValueError(f"SSSI source has {null_name} null name values")

    result = gdf.loc[:, ["ref_code", "name", "measure", geom_col]].copy()
    if geom_col != "geometry":
        result = result.rename_geometry("geometry")
    return result.reset_index(drop=True)
