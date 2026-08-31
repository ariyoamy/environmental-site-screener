"""Loader and overlap analysis for the Natural England Priority Habitats Inventory (PHI).

The PHI maps habitats of principal importance under section 41 of the Natural
Environment and Rural Communities Act 2006. Natural England's catalogue for this
release states the inventory contains 27 priority habitat classes plus four
classes that are *not* priority habitat:

- ``FHEAT`` - Fragmented heath
- ``GMOOR`` - Grass moorland
- ``GQSIG`` - Good quality semi-improved grassland
- ``NMHAB`` - No main habitat

This module treats those four as *context* classes, not priority habitat, so
that the screener does not report every PHI polygon as priority habitat.

Each PHI polygon carries a main habitat classification in ``mainhabs`` (names)
and ``habcodes`` (codes), which are positionally paired and may list more than
one habitat for a single polygon. Classification here is done per code token,
not per polygon: a polygon can contribute a priority habitat *and* a context
class at the same time (the real source has polygons coded ``GQSIG,TORCH``).

Nothing here derives an ecological quality score, a habitat severity ranking, or
any planning, legal or ecological-harm conclusion.
"""

from __future__ import annotations

import pathlib
import warnings
from dataclasses import dataclass

import geopandas as gpd
import pandas as pd
from shapely import union_all

EXPECTED_EPSG = 27700

# The 27 priority habitat codes observed and documented for this PHI release.
PRIORITY_HABITAT_CODES = frozenset(
    {
        "DWOOD", "CFPGM", "TORCH", "UHEAT", "LHEAT", "SALTM", "LCGRA", "BLBOG",
        "LFENS", "LMEAD", "LDAGR", "UFFSW", "MUDFL", "PMGRP", "MCSLP", "LRBOG",
        "RBEDS", "CSDUN", "UCGRA", "LPAVE", "UHMEA", "CVSHI", "SLAGO", "CALAM",
        "MHWSC", "LAKES", "PONDS",
    }
)

# The four PHI classes that are explicitly not priority habitat.
CONTEXT_HABITAT_CODES = frozenset({"FHEAT", "GMOOR", "GQSIG", "NMHAB"})

_KNOWN_HABITAT_CODES = PRIORITY_HABITAT_CODES | CONTEXT_HABITAT_CODES

_ALLOWED_GEOM_TYPES = frozenset({"Polygon", "MultiPolygon"})

REQUIRED_SOURCE_COLUMNS = ("uid", "mainhabs", "habcodes", "featdesc", "addhabs", "primsource")

PHI_OUTPUT_COLUMNS = [
    "uid", "mainhabs", "habcodes", "is_priority", "featdesc", "addhabs", "primsource", "geometry",
]

HABITAT_COLUMNS = [
    "habitat_code", "habitat_name", "intersection_area_m2", "intersection_area_ha", "geometry",
]

CONTEXT_COLUMNS = ["uid", "context_codes", "context_habitats", "primsource", "geometry"]

_REQUIRED_ANALYSIS_COLUMNS = ("uid", "mainhabs", "habcodes", "primsource")


def _split_tokens(value: str) -> list[str]:
    """Split a comma-separated ``mainhabs``/``habcodes`` value and strip each token."""
    return [token.strip() for token in str(value).split(",")]


def load_priority_habitats(path: str | pathlib.Path) -> gpd.GeoDataFrame:
    """Load and validate the Natural England Priority Habitats Inventory source.

    Parameters
    ----------
    path:
        Path to the PHI spatial file (the official GeoPackage).

    Returns
    -------
    geopandas.GeoDataFrame
        Columns ``uid``, ``mainhabs``, ``habcodes``, ``is_priority``,
        ``featdesc``, ``addhabs``, ``primsource`` and ``geometry`` (in that
        order), in EPSG:27700, with a clean ``RangeIndex``. ``is_priority`` is
        ``True`` when at least one ``habcodes`` token is in
        :data:`PRIORITY_HABITAT_CODES`.

    Raises
    ------
    FileNotFoundError
        If ``path`` does not exist.
    ValueError
        If the source has no features, no active geometry column, is missing a
        required column, has no CRS or a CRS that is not EPSG:27700, has null,
        empty or non-polygonal geometry, has null/empty/duplicate ``uid``, has
        null/empty ``mainhabs`` or ``habcodes``, has a row where the
        ``mainhabs`` and ``habcodes`` token counts differ, or contains a
        ``habcodes`` token that is neither a known priority nor a known context
        code.

    Warns
    -----
    UserWarning
        Once, with a count, if the source contains invalid geometry. The
        geometry is left unchanged; this loader does not repair authoritative
        source data.

    Notes
    -----
    Only the required attribute columns (``uid``, ``mainhabs``, ``habcodes``,
    ``featdesc``, ``addhabs``, ``primsource``) plus geometry are read from the
    source. Other fields such as ``areaha``, ``featcodes``, ``otherclass`` and
    ``version`` are not read, so ``areaha`` plays no part in any calculation
    here. The complete national dataset is still loaded (no bounding-box or
    site filtering). Read errors for an existing but unreadable source propagate
    from GeoPandas/pyogrio unchanged. The source is not reprojected. ``addhabs``
    (additional habitats present) is preserved as provenance/context only and
    never contributes to the priority classification.
    """
    source = pathlib.Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Priority Habitats source file not found: {source}")

    # Read only the attribute columns we keep, plus geometry. GeoPandas/pyogrio
    # always returns the geometry column; ``columns`` filters attributes only.
    gdf = gpd.read_file(source, columns=list(REQUIRED_SOURCE_COLUMNS))

    try:
        geom_col = gdf.geometry.name
    except AttributeError as exc:
        raise ValueError("Priority Habitats source has no active geometry column") from exc

    if len(gdf) == 0:
        raise ValueError("Priority Habitats source contains no features")

    missing = [c for c in REQUIRED_SOURCE_COLUMNS if c not in gdf.columns]
    if missing:
        raise ValueError(f"Priority Habitats source is missing required column(s): {missing}")

    if gdf.crs is None:
        raise ValueError("Priority Habitats source has no CRS defined; expected EPSG:27700")
    epsg = gdf.crs.to_epsg()
    if epsg != EXPECTED_EPSG:
        raise ValueError(
            f"Priority Habitats source CRS is {gdf.crs.name!r} (EPSG:{epsg}); expected "
            "EPSG:27700. This loader does not reproject the authoritative Priority Habitats "
            "source."
        )

    geometry = gdf.geometry
    null_geom = int(geometry.isna().sum())
    if null_geom:
        raise ValueError(f"Priority Habitats source contains {null_geom} null geometries")
    empty_geom = int(geometry.is_empty.sum())
    if empty_geom:
        raise ValueError(f"Priority Habitats source contains {empty_geom} empty geometries")
    bad_types = sorted(set(geometry.geom_type) - _ALLOWED_GEOM_TYPES)
    if bad_types:
        raise ValueError(
            f"Priority Habitats source contains non-polygonal geometry (types found: {bad_types})"
        )
    invalid_count = int((~geometry.is_valid).sum())
    if invalid_count:
        warnings.warn(
            f"Priority Habitats source contains {invalid_count} invalid geometries; they are "
            "left unchanged (this loader does not repair authoritative source data)",
            UserWarning,
            stacklevel=2,
        )

    uid = gdf["uid"]
    if uid.isna().any():
        raise ValueError(
            f"Priority Habitats source has {int(uid.isna().sum())} null uid values"
        )
    if (uid.astype("string").str.len() == 0).any():
        raise ValueError("Priority Habitats source has empty uid values")
    duplicate_uid = int(uid.duplicated().sum())
    if duplicate_uid:
        examples = sorted(str(v) for v in uid[uid.duplicated(keep=False)].unique())[:5]
        raise ValueError(
            f"Priority Habitats source has {duplicate_uid} duplicate uid values (e.g. {examples})"
        )

    for col in ("mainhabs", "habcodes"):
        series = gdf[col]
        if series.isna().any():
            raise ValueError(
                f"Priority Habitats source has {int(series.isna().sum())} null {col} values"
            )
        if (series.astype("string").str.strip().str.len() == 0).any():
            raise ValueError(f"Priority Habitats source has empty {col} values")

    main_counts = gdf["mainhabs"].str.split(",").map(len)
    code_counts = gdf["habcodes"].str.split(",").map(len)
    mismatch = main_counts.ne(code_counts)
    if mismatch.any():
        examples = gdf.loc[mismatch, "uid"].head(5).tolist()
        raise ValueError(
            f"Priority Habitats source has {int(mismatch.sum())} row(s) where mainhabs and "
            f"habcodes token counts differ (e.g. uid {examples})"
        )

    code_tokens = gdf["habcodes"].str.split(",").explode().str.strip()
    unknown = sorted(set(code_tokens) - _KNOWN_HABITAT_CODES)
    if unknown:
        raise ValueError(
            f"Priority Habitats source has unexpected main-habitat code token(s): {unknown}. "
            "Each habcode must be one of the 27 priority or 4 context codes for this release."
        )

    is_priority = (
        code_tokens.isin(PRIORITY_HABITAT_CODES)
        .groupby(level=0)
        .any()
        .reindex(range(len(gdf)), fill_value=False)
        .to_numpy()
    )

    result = gdf.loc[
        :, ["uid", "mainhabs", "habcodes", "featdesc", "addhabs", "primsource", geom_col]
    ].copy()
    result["is_priority"] = is_priority
    if geom_col != "geometry":
        result = result.rename_geometry("geometry")
    result = result.loc[:, PHI_OUTPUT_COLUMNS]
    return result.reset_index(drop=True)


@dataclass(frozen=True)
class PriorityHabitatOverlapResult:
    """Result of a candidate-site / Priority Habitats Inventory overlap analysis.

    Attributes
    ----------
    has_priority_overlap:
        ``True`` when the site overlaps at least one priority habitat with
        positive area. It is not a finding that development will harm a habitat
        or that the site is unsuitable.
    habitat_count:
        Number of distinct priority habitat classes in ``habitats``.
    habitats:
        One row per priority habitat class the site overlaps, columns
        ``habitat_code``, ``habitat_name``, ``intersection_area_m2``,
        ``intersection_area_ha`` and ``geometry`` (the unioned clipped overlap
        for that class), EPSG:27700, sorted by descending area then by code.
        A polygon with several priority main habitats contributes its clipped
        geometry to each class, so the per-class areas can sum to more than
        ``affected_area_m2``.
    context:
        One row per intersecting polygon that carries a context class code
        (``FHEAT``/``GMOOR``/``GQSIG``/``NMHAB``), even if the same polygon also
        carries a priority habitat, columns ``uid``, ``context_codes``,
        ``context_habitats``, ``primsource`` and ``geometry`` (the original,
        unclipped polygon), EPSG:27700, sorted by ``uid``. No area or percentage
        is reported for context.
    site_area_m2:
        Area of the candidate site polygon, square metres.
    affected_area_m2:
        Area of the site covered by any priority habitat, square metres,
        de-duplicated by unioning the clipped priority geometries so ground
        under several priority habitats is counted once.
    affected_area_ha:
        ``affected_area_m2 / 10_000``.
    affected_pct:
        ``100 * affected_area_m2 / site_area_m2``.
    """

    has_priority_overlap: bool
    habitat_count: int
    habitats: gpd.GeoDataFrame
    context: gpd.GeoDataFrame
    site_area_m2: float
    affected_area_m2: float
    affected_area_ha: float
    affected_pct: float


def _empty_like(columns: list[str], float_columns: dict[str, str], crs) -> gpd.GeoDataFrame:
    attr_columns = [c for c in columns if c != "geometry"]
    attr_df = pd.DataFrame({c: pd.Series(dtype="object") for c in attr_columns})
    if float_columns:
        attr_df = attr_df.astype(float_columns)
    return gpd.GeoDataFrame(attr_df, geometry=gpd.GeoSeries([], crs=crs))[columns]


def calculate_priority_habitat_overlap(
    site: gpd.GeoDataFrame, phi: gpd.GeoDataFrame
) -> PriorityHabitatOverlapResult:
    """Calculate positive-area overlap between a candidate site and priority habitat.

    Parameters
    ----------
    site:
        Single-row GeoDataFrame from ``validate_site`` (EPSG:27700).
    phi:
        Priority Habitats layer from ``load_priority_habitats`` (EPSG:27700),
        with columns ``uid``, ``mainhabs``, ``habcodes`` and ``primsource``.

    Returns
    -------
    PriorityHabitatOverlapResult

    Raises
    ------
    TypeError
        If either input is not a GeoDataFrame.
    ValueError
        If either input has no CRS, if either input does not resolve to
        EPSG:27700, if ``site`` does not contain exactly one row, or if ``phi``
        is missing a required column.

    Notes
    -----
    Inputs are not reprojected and geometry is not repaired. Classification is
    per ``habcodes`` token: for each positive-area polygon intersection, every
    token in :data:`PRIORITY_HABITAT_CODES` attributes that polygon's clipped
    geometry to the matching priority class, and every token in
    :data:`CONTEXT_HABITAT_CODES` adds the polygon to ``context``. ``addhabs``
    is never consulted. Only positive-area intersection counts; a site that
    merely touches a boundary line or corner has no overlap. Values are returned
    unrounded.
    """
    if not isinstance(site, gpd.GeoDataFrame):
        raise TypeError(
            f"site must be a geopandas.GeoDataFrame, got {type(site).__name__}"
        )
    if not isinstance(phi, gpd.GeoDataFrame):
        raise TypeError(
            f"phi must be a geopandas.GeoDataFrame, got {type(phi).__name__}"
        )

    if site.crs is None:
        raise ValueError("site has no CRS defined; EPSG:27700 is required")
    if phi.crs is None:
        raise ValueError("phi has no CRS defined; EPSG:27700 is required")

    if site.crs.to_epsg() != EXPECTED_EPSG:
        raise ValueError(f"site CRS must be EPSG:27700; got EPSG:{site.crs.to_epsg()}")
    if phi.crs.to_epsg() != EXPECTED_EPSG:
        raise ValueError(f"phi CRS must be EPSG:27700; got EPSG:{phi.crs.to_epsg()}")

    if len(site) != 1:
        raise ValueError(f"site must contain exactly one row; got {len(site)}")

    missing = [c for c in _REQUIRED_ANALYSIS_COLUMNS if c not in phi.columns]
    if missing:
        raise ValueError(f"phi is missing required column(s): {missing}")

    site_geom = site.geometry.iloc[0]
    site_area_m2 = float(site_geom.area)

    candidate_idx = phi.sindex.query(site_geom, predicate="intersects")
    candidates = phi.iloc[candidate_idx]

    priority_geoms: dict[str, list] = {}
    priority_names: dict[str, str] = {}
    all_priority_clipped: list = []
    context_records: list[dict] = []
    context_geoms: list = []

    for uid, mainhabs, habcodes, primsource, geom in zip(
        candidates["uid"],
        candidates["mainhabs"],
        candidates["habcodes"],
        candidates["primsource"],
        candidates.geometry,
    ):
        clipped = geom.intersection(site_geom)
        if clipped.area <= 0:
            continue

        code_tokens = _split_tokens(habcodes)
        name_tokens = _split_tokens(mainhabs)

        polygon_is_priority = False
        polygon_context: dict[str, str] = {}
        for code, name in zip(code_tokens, name_tokens):
            if code in PRIORITY_HABITAT_CODES:
                priority_geoms.setdefault(code, []).append(clipped)
                priority_names.setdefault(code, name)
                polygon_is_priority = True
            if code in CONTEXT_HABITAT_CODES:
                polygon_context.setdefault(code, name)

        if polygon_is_priority:
            all_priority_clipped.append(clipped)

        if polygon_context:
            ordered = sorted(polygon_context)
            context_records.append(
                {
                    "uid": uid,
                    "context_codes": ",".join(ordered),
                    "context_habitats": ",".join(polygon_context[c] for c in ordered),
                    "primsource": primsource,
                }
            )
            context_geoms.append(geom)  # original, unclipped

    # Per-class overlap. Each class unions its own clipped pieces before the
    # area is taken. A polygon coded with several priority habitats is counted
    # in every one of those classes, so sum(intersection_area_m2) can exceed
    # affected_area_m2 - that is expected, not a bug.
    if priority_geoms:
        habitat_records = []
        habitat_geoms = []
        for code, geoms in priority_geoms.items():
            merged = union_all(geoms)
            area_m2 = float(merged.area)
            habitat_records.append(
                {
                    "habitat_code": code,
                    "habitat_name": priority_names[code],
                    "intersection_area_m2": area_m2,
                    "intersection_area_ha": area_m2 / 10_000,
                }
            )
            habitat_geoms.append(merged)
        habitat_attrs = pd.DataFrame.from_records(
            habitat_records, columns=[c for c in HABITAT_COLUMNS if c != "geometry"]
        ).astype({"intersection_area_m2": "float64", "intersection_area_ha": "float64"})
        habitats = gpd.GeoDataFrame(
            habitat_attrs,
            geometry=gpd.GeoSeries(habitat_geoms, index=habitat_attrs.index, crs=site.crs),
        )
        habitats = (
            habitats.sort_values(
                ["intersection_area_m2", "habitat_code"],
                ascending=[False, True],
                kind="stable",
            )
            .reset_index(drop=True)
            .loc[:, HABITAT_COLUMNS]
        )
    else:
        habitats = _empty_like(
            HABITAT_COLUMNS,
            {"intersection_area_m2": "float64", "intersection_area_ha": "float64"},
            site.crs,
        )

    if context_records:
        context_attrs = pd.DataFrame.from_records(
            context_records, columns=[c for c in CONTEXT_COLUMNS if c != "geometry"]
        )
        context = gpd.GeoDataFrame(
            context_attrs,
            geometry=gpd.GeoSeries(context_geoms, index=context_attrs.index, crs=site.crs),
        )
        context = (
            context.sort_values("uid", kind="stable")
            .reset_index(drop=True)
            .loc[:, CONTEXT_COLUMNS]
        )
    else:
        context = _empty_like(CONTEXT_COLUMNS, {}, site.crs)

    # Overall affected area: union of every clipped geometry that belongs to at
    # least one priority class. Never a sum of the per-class areas.
    if all_priority_clipped:
        affected_area_m2 = float(union_all(all_priority_clipped).area)
    else:
        affected_area_m2 = 0.0

    habitat_count = len(habitats)
    return PriorityHabitatOverlapResult(
        has_priority_overlap=habitat_count > 0,
        habitat_count=habitat_count,
        habitats=habitats,
        context=context,
        site_area_m2=site_area_m2,
        affected_area_m2=affected_area_m2,
        affected_area_ha=affected_area_m2 / 10_000,
        affected_pct=100.0 * affected_area_m2 / site_area_m2,
    )
