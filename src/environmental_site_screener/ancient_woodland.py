"""Loaders and overlap analysis for the Ancient Woodland screening theme.

Two Natural England inventories are involved:

* **Ancient Woodland - Revised (England) - Completed Counties** - the ongoing
  county-by-county re-survey. Delivered categories: ``ASNW`` (Ancient &
  Semi-Natural Woodland), ``ARW`` (Ancient Replanted Woodland), ``AWPP``
  (Ancient Wood Pasture), ``IAWPP`` (Infilled Ancient Wood Pasture).
* **Ancient Woodland (England)** - the legacy national inventory, used only
  where the revised inventory does not yet have coverage. Delivered categories:
  ``ASNW``, ``PAWS`` (Plantations on Ancient Woodland Sites), ``AWP`` (Ancient
  Wood Pasture).

Natural England publishes the revised data as a single polygon layer titled
"Completed Counties" and states, in the legacy dataset's own metadata, that
"where a county has been updated and is included in that dataset, the revised
information takes precedence" and the legacy inventory "should be used as the
primary reference" elsewhere. There is **no** published coverage layer and no
completed-county field in the GeoPackage.

This module therefore drives the precedence rule from a dated, project-inferred
allow-list of ceremonial counties (:data:`REVISED_COVERAGE_COUNTIES`), assembled
from the current revised dataset snapshot plus an OS Boundary-Line diagnostic.
That allow-list is a **project inference, not Natural England metadata**.

Nothing here derives a woodland score, a severity ranking, or any planning,
legal, ecological-harm or suitability conclusion. Revised and legacy categories
are always reported separately and are never mapped onto one another.
"""

from __future__ import annotations

import math
import pathlib
import warnings
from dataclasses import dataclass

import geopandas as gpd
import pandas as pd
from shapely import union_all
from shapely.geometry import Polygon

EXPECTED_EPSG = 27700

_ALLOWED_GEOM_TYPES = frozenset({"Polygon", "MultiPolygon"})

# --------------------------------------------------------------------------- #
# Coverage: project-inferred ceremonial-county allow-list
# --------------------------------------------------------------------------- #

# Ceremonial counties where the Natural England revised Ancient Woodland
# inventory is judged to be a whole-county replacement of the legacy inventory.
# Assembled from the revised dataset snapshot (local copy dated 2026-08-13)
# cross-checked against the OS Boundary-Line ceremonial counties layer on
# 2026-08-31 (representative-point county assignment, nearest-neighbour and
# grid-coverage diagnostics). This is a PROJECT INFERENCE, not Natural England
# metadata - it must be revised whenever the revised dataset is refreshed.
REVISED_COVERAGE_COUNTIES = (
    "Bedfordshire",
    "Bristol",
    "Cambridgeshire",
    "Cheshire",
    "Derbyshire",
    "Devon",
    "Dorset",
    "Durham",
    "Essex",
    "Gloucestershire",
    "Greater London",
    "Greater Manchester",
    "Hampshire",
    "Hertfordshire",
    "Lancashire",
    "Leicestershire",
    "Lincolnshire",
    "Merseyside",
    "Northamptonshire",
    "Northumberland",
    "Rutland",
    "South Yorkshire",
    "Suffolk",
    "Tyne & Wear",
    "Warwickshire",
    "West Midlands",
    "West Yorkshire",
    "Wiltshire",
    "Worcestershire",
)

# Deliberately excluded from the allow-list:
#  * "Somerset" - only the former-Avon north/east of the ceremonial county is
#    revised; the western half (Exmoor, Quantocks, west Somerset) is not.
#  * "City and County of the City of London" - carries no ancient woodland.
#  * Counties with only cross-border / spill revised polygons: North Yorkshire,
#    Cornwall, Herefordshire, Shropshire, Staffordshire, Nottinghamshire,
#    Buckinghamshire, Surrey, Cumbria, Berkshire, Oxfordshire, Kent.
#  * Counties with zero revised polygons: East Sussex, West Sussex, Norfolk,
#    Isle of Wight, East Riding of Yorkshire.
REVISED_COVERAGE_EXCLUDED = (
    "Somerset",
    "City and County of the City of London",
)

_COVERAGE_NAME_FIELD = "NAME"
COVERAGE_OUTPUT_COLUMNS = ["county_name", "geometry"]

# --------------------------------------------------------------------------- #
# Category code -> name maps, taken from the delivered GeoPackages (not the
# supporting PDFs, which disagree with the data on the replanted-woodland code).
# --------------------------------------------------------------------------- #

REVISED_CATEGORIES = {
    "ASNW": "Ancient & Semi-Natural Woodland",
    "ARW": "Ancient Replanted Woodland",
    "AWPP": "Ancient Wood Pasture",
    "IAWPP": "Infilled Ancient Wood Pasture",
}
LEGACY_CATEGORIES = {
    "ASNW": "Ancient & Semi-Natural Woodland",
    "PAWS": "Ancient Replanted Woodland",
    "AWP": "Ancient Wood Pasture",
}

# Source attribute columns each loader reads (geometry is always returned too).
_REVISED_SOURCE_COLUMNS = ("name", "status", "themename", "themeid")
_LEGACY_SOURCE_COLUMNS = ("name", "status", "themname", "themid")

AW_OUTPUT_COLUMNS = [
    "aw_name",
    "category_code",
    "category_name",
    "theme_id",
    "inventory",
    "geometry",
]

_ANALYSIS_REQUIRED_COLUMNS = (
    "aw_name",
    "category_code",
    "category_name",
    "theme_id",
    "inventory",
)

FEATURE_COLUMNS = [
    "inventory",
    "category_code",
    "category_name",
    "intersection_area_m2",
    "intersection_area_ha",
    "geometry",
]


def _clean_theme_id(value) -> str:
    """Return a clean string identifier, dropping a trailing ``.0`` on integers.

    The legacy source stores ``themid`` as a float (``1481207.0``); the revised
    source stores ``themeid`` as text (``"ESS-2501"``). Both are opaque here.
    """
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    if pd.isna(value):
        return ""
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isfinite(as_float) and as_float.is_integer():
        return str(int(as_float))
    return str(value)


# --------------------------------------------------------------------------- #
# Coverage loader
# --------------------------------------------------------------------------- #


def load_revised_coverage(path: str | pathlib.Path) -> gpd.GeoDataFrame:
    """Load the project-inferred revised-coverage polygons from OS Boundary-Line.

    Reads the OS Boundary-Line ceremonial counties layer and filters it to the
    fixed :data:`REVISED_COVERAGE_COUNTIES` allow-list, so the exact coverage
    inference used for this source revision stays reproducible and auditable.
    Counties are never inferred dynamically from the Ancient Woodland polygons.

    Parameters
    ----------
    path:
        Path to the OS Boundary-Line ceremonial counties layer (the project uses
        ``Boundary-line-ceremonial-counties_region.shp``).

    Returns
    -------
    geopandas.GeoDataFrame
        Columns ``county_name`` and ``geometry`` (in that order), one row per
        allow-list county, sorted by ``county_name``, in EPSG:27700, with a
        clean ``RangeIndex``.

    Raises
    ------
    FileNotFoundError
        If ``path`` does not exist.
    ValueError
        If the source has no active geometry column, no ``NAME`` column, no CRS
        or a CRS that is not EPSG:27700; if any allow-list county is missing or
        appears more than once; or if any *selected* county has null, empty,
        non-polygonal or invalid geometry.

    Notes
    -----
    The source is not reprojected. Invalid geometry **outside** the allow-list
    (for example the Boundary-Line ``Shetland`` polygon) is never inspected and
    does not matter; invalid geometry in a *selected* coverage county raises
    rather than being repaired.
    """
    source = pathlib.Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Revised coverage source file not found: {source}")

    gdf = gpd.read_file(source)

    try:
        gdf.geometry.name
    except AttributeError as exc:
        raise ValueError("Revised coverage source has no active geometry column") from exc

    if _COVERAGE_NAME_FIELD not in gdf.columns:
        raise ValueError(
            f"Revised coverage source is missing required column: {_COVERAGE_NAME_FIELD!r}"
        )

    if gdf.crs is None:
        raise ValueError("Revised coverage source has no CRS defined; expected EPSG:27700")
    epsg = gdf.crs.to_epsg()
    if epsg != EXPECTED_EPSG:
        raise ValueError(
            f"Revised coverage source CRS is {gdf.crs.name!r} (EPSG:{epsg}); expected "
            "EPSG:27700. This loader does not reproject the coverage source."
        )

    wanted = set(REVISED_COVERAGE_COUNTIES)
    selected = gdf.loc[gdf[_COVERAGE_NAME_FIELD].isin(wanted)].copy()

    present = list(selected[_COVERAGE_NAME_FIELD])
    missing = sorted(wanted - set(present))
    if missing:
        raise ValueError(
            f"Revised coverage source is missing required allow-list county/counties: {missing}"
        )
    duplicated = sorted({n for n in present if present.count(n) > 1})
    if duplicated:
        raise ValueError(
            "Revised coverage source has duplicate rows for allow-list "
            f"county/counties: {duplicated}"
        )

    geometry = selected.geometry
    null_geom = int(geometry.isna().sum())
    if null_geom:
        raise ValueError(
            f"Revised coverage source has {null_geom} null geometries among selected counties"
        )
    empty_geom = int(geometry.is_empty.sum())
    if empty_geom:
        raise ValueError(
            f"Revised coverage source has {empty_geom} empty geometries among selected counties"
        )
    bad_types = sorted(set(geometry.geom_type) - _ALLOWED_GEOM_TYPES)
    if bad_types:
        raise ValueError(
            "Revised coverage source has non-polygonal geometry among selected counties "
            f"(types found: {bad_types})"
        )
    invalid = int((~geometry.is_valid).sum())
    if invalid:
        raise ValueError(
            f"Revised coverage source has {invalid} invalid geometr(y/ies) among the "
            "selected allow-list counties; fix the boundary source rather than letting "
            "this loader repair it"
        )

    result = gpd.GeoDataFrame(
        {"county_name": selected[_COVERAGE_NAME_FIELD].to_numpy()},
        geometry=geometry.to_numpy(),
        crs=selected.crs,
    )
    result = result.sort_values("county_name", kind="stable").reset_index(drop=True)
    return result.loc[:, COVERAGE_OUTPUT_COLUMNS]


# --------------------------------------------------------------------------- #
# Ancient Woodland loaders
# --------------------------------------------------------------------------- #


def _load_ancient_woodland(
    path: str | pathlib.Path,
    *,
    inventory: str,
    source_columns: tuple[str, ...],
    categories: dict[str, str],
    code_col: str,
    name_col: str,
    theme_col: str,
    label: str,
) -> gpd.GeoDataFrame:
    """Shared loader/validator for the revised and legacy Ancient Woodland sources."""
    source = pathlib.Path(path)
    if not source.exists():
        raise FileNotFoundError(f"{label} source file not found: {source}")

    gdf = gpd.read_file(source, columns=list(source_columns))

    try:
        gdf.geometry.name
    except AttributeError as exc:
        raise ValueError(f"{label} source has no active geometry column") from exc

    if len(gdf) == 0:
        raise ValueError(f"{label} source contains no features")

    missing = [c for c in source_columns if c not in gdf.columns]
    if missing:
        raise ValueError(f"{label} source is missing required column(s): {missing}")

    if gdf.crs is None:
        raise ValueError(f"{label} source has no CRS defined; expected EPSG:27700")
    epsg = gdf.crs.to_epsg()
    if epsg != EXPECTED_EPSG:
        raise ValueError(
            f"{label} source CRS is {gdf.crs.name!r} (EPSG:{epsg}); expected EPSG:27700. "
            f"This loader does not reproject the authoritative {label} source."
        )

    geometry = gdf.geometry
    null_geom = int(geometry.isna().sum())
    if null_geom:
        raise ValueError(f"{label} source contains {null_geom} null geometries")
    empty_geom = int(geometry.is_empty.sum())
    if empty_geom:
        raise ValueError(f"{label} source contains {empty_geom} empty geometries")
    bad_types = sorted(set(geometry.geom_type) - _ALLOWED_GEOM_TYPES)
    if bad_types:
        raise ValueError(
            f"{label} source contains non-polygonal geometry (types found: {bad_types})"
        )
    invalid_count = int((~geometry.is_valid).sum())
    if invalid_count:
        warnings.warn(
            f"{label} source contains {invalid_count} invalid geometries; they are "
            "left unchanged (this loader does not repair authoritative source data)",
            UserWarning,
            stacklevel=3,
        )

    codes = gdf[code_col].astype("string")
    if codes.isna().any():
        raise ValueError(
            f"{label} source has {int(codes.isna().sum())} null category codes"
        )
    unknown = sorted(set(codes) - set(categories))
    if unknown:
        raise ValueError(
            f"{label} source has unexpected category_code(s): {unknown}. "
            f"Allowed codes for this inventory: {sorted(categories)}"
        )

    names = gdf[name_col].astype("string")
    if names.isna().any():
        raise ValueError(f"{label} source has null category_name values")
    expected_names = codes.map(categories)
    mismatch = names != expected_names
    if mismatch.any():
        examples = sorted(
            {(c, n) for c, n in zip(codes[mismatch], names[mismatch])}
        )[:5]
        raise ValueError(
            f"{label} source has {int(mismatch.sum())} row(s) where category_code and "
            f"category_name disagree with the delivered schema (e.g. {examples})"
        )

    result = gpd.GeoDataFrame(
        {
            "aw_name": gdf["name"].to_numpy(),
            "category_code": codes.to_numpy(dtype=object),
            "category_name": names.to_numpy(dtype=object),
            "theme_id": [_clean_theme_id(v) for v in gdf[theme_col]],
            "inventory": inventory,
        },
        geometry=geometry.to_numpy(),
        crs=gdf.crs,
    )
    result = result.loc[:, AW_OUTPUT_COLUMNS]
    return result.reset_index(drop=True)


def load_ancient_woodland_revised(path: str | pathlib.Path) -> gpd.GeoDataFrame:
    """Load and validate the Natural England revised Ancient Woodland source.

    Parameters
    ----------
    path:
        Path to the revised Ancient Woodland GeoPackage
        (``Ancient_Woodland_Revised_England_Completed_Counties.gpkg``).

    Returns
    -------
    geopandas.GeoDataFrame
        Columns ``aw_name``, ``category_code``, ``category_name``, ``theme_id``,
        ``inventory`` and ``geometry`` (in that order), ``inventory == "revised"``,
        in EPSG:27700, with a clean ``RangeIndex``.

    Raises
    ------
    FileNotFoundError
        If ``path`` does not exist.
    ValueError
        If the source has no features, no active geometry column, is missing a
        required column, has no CRS or a CRS that is not EPSG:27700, has null,
        empty or non-polygonal geometry, has a ``status`` code outside
        ``{ASNW, ARW, AWPP, IAWPP}``, or has a ``status``/``themename`` pair that
        disagrees with :data:`REVISED_CATEGORIES`.

    Warns
    -----
    UserWarning
        Once, with a count, if the source contains invalid geometry. The
        geometry is left unchanged (the real source has 69 such polygons).

    Notes
    -----
    Source mapping: ``name -> aw_name``, ``status -> category_code``,
    ``themename -> category_name``, ``themeid -> theme_id``. ``theme_id`` is not
    required to be unique and blank ``aw_name`` values are allowed. The source
    ``area`` and ``perimeter`` fields are not read and take no part in any
    calculation. The source is not reprojected.
    """
    return _load_ancient_woodland(
        path,
        inventory="revised",
        source_columns=_REVISED_SOURCE_COLUMNS,
        categories=REVISED_CATEGORIES,
        code_col="status",
        name_col="themename",
        theme_col="themeid",
        label="Ancient Woodland (revised)",
    )


def load_ancient_woodland_legacy(path: str | pathlib.Path) -> gpd.GeoDataFrame:
    """Load and validate the Natural England legacy Ancient Woodland source.

    Parameters
    ----------
    path:
        Path to the legacy Ancient Woodland GeoPackage
        (``Ancient_Woodland_England.gpkg``).

    Returns
    -------
    geopandas.GeoDataFrame
        Columns ``aw_name``, ``category_code``, ``category_name``, ``theme_id``,
        ``inventory`` and ``geometry`` (in that order), ``inventory == "legacy"``,
        in EPSG:27700, with a clean ``RangeIndex``.

    Raises
    ------
    FileNotFoundError
        If ``path`` does not exist.
    ValueError
        As for :func:`load_ancient_woodland_revised`, but the allowed ``status``
        codes are ``{ASNW, PAWS, AWP}`` and the pairing is checked against
        :data:`LEGACY_CATEGORIES`.

    Warns
    -----
    UserWarning
        Once, with a count, if the source contains invalid geometry (the real
        legacy source has none).

    Notes
    -----
    Source mapping: ``name -> aw_name``, ``status -> category_code``,
    ``themname -> category_name``, ``themid -> theme_id``. The numeric ``themid``
    is converted to a clean string without a trailing ``.0``. Legacy categories
    ``PAWS`` and ``AWP`` are preserved as-is and are never normalised onto the
    revised ``ARW``/``AWPP`` codes. ``area`` and ``perimeter`` are not read.
    """
    return _load_ancient_woodland(
        path,
        inventory="legacy",
        source_columns=_LEGACY_SOURCE_COLUMNS,
        categories=LEGACY_CATEGORIES,
        code_col="status",
        name_col="themname",
        theme_col="themid",
        label="Ancient Woodland (legacy)",
    )


# --------------------------------------------------------------------------- #
# Overlap analysis
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AncientWoodlandOverlapResult:
    """Result of a candidate-site / Ancient Woodland overlap analysis.

    Attributes
    ----------
    has_overlap:
        ``True`` when the site overlaps at least one ancient woodland polygon
        with positive area, after the revised/legacy precedence split. It is not
        a finding that development will harm woodland or that the site is
        unsuitable.
    feature_count:
        Number of rows in ``features`` (one per ``(inventory, category_code)``).
    features:
        One row per ``(inventory, category_code)`` the site overlaps, columns
        ``inventory``, ``category_code``, ``category_name``,
        ``intersection_area_m2``, ``intersection_area_ha`` and ``geometry`` (the
        unioned clipped overlap for that category), EPSG:27700, sorted by
        descending area then by ``inventory`` then ``category_code``. Revised and
        legacy categories are kept separate. A polygon counted under several
        categories contributes its clipped geometry to each, so the per-category
        areas can sum to more than ``affected_area_m2``.
    site_area_m2:
        Area of the candidate site polygon, square metres.
    revised_coverage_area_m2:
        Area of the site that falls inside the project-inferred revised coverage
        (analysed against the revised inventory only).
    fallback_area_m2:
        Area of the site outside revised coverage (analysed against the legacy
        inventory only). ``revised_coverage_area_m2 + fallback_area_m2`` equals
        ``site_area_m2`` up to floating-point error.
    affected_area_m2:
        Area of the site covered by any ancient woodland, square metres,
        de-duplicated by unioning every kept clipped geometry so ground under
        several woodland polygons (or several categories) is counted once.
    affected_area_ha:
        ``affected_area_m2 / 10_000``.
    affected_pct:
        ``100 * affected_area_m2 / site_area_m2``.
    """

    has_overlap: bool
    feature_count: int
    features: gpd.GeoDataFrame
    site_area_m2: float
    revised_coverage_area_m2: float
    fallback_area_m2: float
    affected_area_m2: float
    affected_area_ha: float
    affected_pct: float


def _empty_features(crs) -> gpd.GeoDataFrame:
    attr = pd.DataFrame(
        {
            "inventory": pd.Series(dtype="object"),
            "category_code": pd.Series(dtype="object"),
            "category_name": pd.Series(dtype="object"),
            "intersection_area_m2": pd.Series(dtype="float64"),
            "intersection_area_ha": pd.Series(dtype="float64"),
        }
    )
    return gpd.GeoDataFrame(attr, geometry=gpd.GeoSeries([], crs=crs))[FEATURE_COLUMNS]


def _require_gdf(obj, name: str) -> None:
    if not isinstance(obj, gpd.GeoDataFrame):
        raise TypeError(
            f"{name} must be a geopandas.GeoDataFrame, got {type(obj).__name__}"
        )


def _require_crs_27700(obj: gpd.GeoDataFrame, name: str) -> None:
    if obj.crs is None:
        raise ValueError(f"{name} has no CRS defined; EPSG:27700 is required")
    if obj.crs.to_epsg() != EXPECTED_EPSG:
        raise ValueError(f"{name} CRS must be EPSG:27700; got EPSG:{obj.crs.to_epsg()}")


def _clip_layer(part_geom, layer: gpd.GeoDataFrame) -> list[tuple]:
    """Positive-area clips of ``layer`` against one site part.

    Returns ``(inventory, category_code, category_name, clipped_geometry)`` for
    every layer polygon whose intersection with ``part_geom`` has positive area.
    Boundary/point touches (zero area) are dropped.
    """
    if part_geom is None or part_geom.is_empty or part_geom.area <= 0:
        return []
    idx = layer.sindex.query(part_geom, predicate="intersects")
    candidates = layer.iloc[idx]
    kept: list[tuple] = []
    for inv, code, name, geom in zip(
        candidates["inventory"],
        candidates["category_code"],
        candidates["category_name"],
        candidates.geometry,
    ):
        clipped = geom.intersection(part_geom)
        if clipped.area > 0:
            kept.append((inv, code, name, clipped))
    return kept


def calculate_ancient_woodland_overlap(
    site: gpd.GeoDataFrame,
    revised: gpd.GeoDataFrame,
    legacy: gpd.GeoDataFrame,
    revised_coverage: gpd.GeoDataFrame,
) -> AncientWoodlandOverlapResult:
    """Calculate ancient woodland overlap for one site under the precedence rule.

    Parameters
    ----------
    site:
        Single-row GeoDataFrame from ``validate_site`` (EPSG:27700).
    revised:
        Revised inventory from :func:`load_ancient_woodland_revised` (EPSG:27700).
    legacy:
        Legacy inventory from :func:`load_ancient_woodland_legacy` (EPSG:27700).
    revised_coverage:
        Coverage polygons from :func:`load_revised_coverage` (EPSG:27700).

    Returns
    -------
    AncientWoodlandOverlapResult

    Raises
    ------
    TypeError
        If any input is not a GeoDataFrame.
    ValueError
        If any input has no CRS or does not resolve to EPSG:27700; if ``site``
        does not contain exactly one row; if ``revised`` or ``legacy`` is missing
        a normalised required column; if ``revised_coverage`` is empty or not
        polygonal; or if the site needs a revised (respectively fallback) portion
        but the ``revised`` (respectively ``legacy``) layer is empty.

    Notes
    -----
    The site is partitioned by the coverage geometry:
    ``revised_part = site.intersection(coverage)`` is analysed against the
    revised inventory only; ``fallback_part = site.difference(coverage)`` is
    analysed against the legacy inventory only. The two parts are disjoint, so
    the headline affected area cannot double-count across the boundary. Only
    positive-area intersection counts; inputs are not reprojected or repaired.
    Values are returned unrounded.
    """
    _require_gdf(site, "site")
    _require_gdf(revised, "revised")
    _require_gdf(legacy, "legacy")
    _require_gdf(revised_coverage, "revised_coverage")

    for obj, name in (
        (site, "site"),
        (revised, "revised"),
        (legacy, "legacy"),
        (revised_coverage, "revised_coverage"),
    ):
        _require_crs_27700(obj, name)

    if len(site) != 1:
        raise ValueError(f"site must contain exactly one row; got {len(site)}")

    for layer, name in ((revised, "revised"), (legacy, "legacy")):
        miss = [c for c in _ANALYSIS_REQUIRED_COLUMNS if c not in layer.columns]
        if miss:
            raise ValueError(f"{name} is missing required column(s): {miss}")

    if len(revised_coverage) == 0:
        raise ValueError(
            "revised_coverage is empty; at least one coverage polygon is required"
        )
    cov_bad = sorted(set(revised_coverage.geometry.geom_type) - _ALLOWED_GEOM_TYPES)
    if cov_bad:
        raise ValueError(
            f"revised_coverage must be polygonal; geometry types found: {cov_bad}"
        )

    site_geom = site.geometry.iloc[0]
    site_area_m2 = float(site_geom.area)

    # A candidate site normally intersects zero, one or a few coverage counties.
    # Union only the coverage polygons the site actually touches, found via the
    # spatial index, instead of unioning all of them on every call.
    cov_idx = revised_coverage.sindex.query(site_geom, predicate="intersects")
    if len(cov_idx):
        coverage_geom = union_all(revised_coverage.geometry.iloc[cov_idx].to_numpy())
        revised_part = site_geom.intersection(coverage_geom)
        fallback_part = site_geom.difference(coverage_geom)
    else:
        revised_part = Polygon()  # empty polygonal geometry: no revised coverage here
        fallback_part = site_geom  # the whole site falls through to the legacy path
    revised_coverage_area_m2 = float(revised_part.area)
    fallback_area_m2 = float(fallback_part.area)

    if revised_part.area > 0 and len(revised) == 0:
        raise ValueError(
            "site has a portion inside revised coverage but the revised inventory "
            "layer is empty; refusing to report a zero result for a missing required "
            "source"
        )
    if fallback_part.area > 0 and len(legacy) == 0:
        raise ValueError(
            "site has a portion outside revised coverage but the legacy inventory "
            "layer is empty; refusing to report a zero result for a missing required "
            "source"
        )

    records = _clip_layer(revised_part, revised) + _clip_layer(fallback_part, legacy)

    if records:
        groups: dict[tuple[str, str], dict] = {}
        for inv, code, name, geom in records:
            bucket = groups.setdefault((inv, code), {"name": name, "geoms": []})
            bucket["geoms"].append(geom)

        feat_records = []
        feat_geoms = []
        for (inv, code), bucket in groups.items():
            merged = union_all(bucket["geoms"])
            area_m2 = float(merged.area)
            feat_records.append(
                {
                    "inventory": inv,
                    "category_code": code,
                    "category_name": bucket["name"],
                    "intersection_area_m2": area_m2,
                    "intersection_area_ha": area_m2 / 10_000,
                }
            )
            feat_geoms.append(merged)

        attrs = pd.DataFrame.from_records(
            feat_records, columns=[c for c in FEATURE_COLUMNS if c != "geometry"]
        ).astype(
            {"intersection_area_m2": "float64", "intersection_area_ha": "float64"}
        )
        features = gpd.GeoDataFrame(
            attrs, geometry=gpd.GeoSeries(feat_geoms, index=attrs.index, crs=site.crs)
        )
        features = (
            features.sort_values(
                ["intersection_area_m2", "inventory", "category_code"],
                ascending=[False, True, True],
                kind="stable",
            )
            .reset_index(drop=True)
            .loc[:, FEATURE_COLUMNS]
        )
        affected_area_m2 = float(union_all([g for _, _, _, g in records]).area)
    else:
        features = _empty_features(site.crs)
        affected_area_m2 = 0.0

    feature_count = len(features)
    return AncientWoodlandOverlapResult(
        has_overlap=feature_count > 0,
        feature_count=feature_count,
        features=features,
        site_area_m2=site_area_m2,
        revised_coverage_area_m2=revised_coverage_area_m2,
        fallback_area_m2=fallback_area_m2,
        affected_area_m2=affected_area_m2,
        affected_area_ha=affected_area_m2 / 10_000,
        affected_pct=100.0 * affected_area_m2 / site_area_m2,
    )
