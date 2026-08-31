"""Orchestration layer: screen one candidate site against every theme at once.

This module wires the existing per-theme loaders and analysis functions together.
It adds no new spatial logic. :func:`screen_site` validates a candidate site,
runs each theme's existing analysis, and returns a :class:`ScreeningResult` that
keeps every individual result object plus a small tabular :attr:`summary` for a
later UI.

Deliberately absent: any overall score, total constraint count, combined
cross-theme area or percentage, weighting, or red/amber/green style rating.
Areas from different themes can spatially overlap and mean fundamentally
different things, so they are never added together.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass

import geopandas as gpd
import pandas as pd

from environmental_site_screener.ancient_woodland import (
    AncientWoodlandOverlapResult,
    calculate_ancient_woodland_overlap,
    load_ancient_woodland_legacy,
    load_ancient_woodland_revised,
    load_revised_coverage,
)
from environmental_site_screener.distance import (
    NearestSssiResult,
    calculate_nearest_sssi,
)
from environmental_site_screener.flood_zones import (
    FloodZoneOverlapResult,
    calculate_flood_zone_overlap,
    load_flood_zones,
)
from environmental_site_screener.overlap import (
    SssiOverlapResult,
    calculate_sssi_overlap,
)
from environmental_site_screener.priority_habitats import (
    PriorityHabitatOverlapResult,
    calculate_priority_habitat_overlap,
    load_priority_habitats,
)
from environmental_site_screener.site import validate_site
from environmental_site_screener.sssi import load_sssi
from environmental_site_screener.sssi_irz import (
    SssiIrzContextResult,
    calculate_sssi_irz_context,
    load_sssi_irz,
)

# One row per user-visible theme, in this fixed order.
SUMMARY_THEMES = (
    "SSSI",
    "SSSI Impact Risk Zone",
    "Priority Habitats",
    "Ancient Woodland",
    "Flood Zones",
)

SUMMARY_COLUMNS = [
    "theme",
    "has_result",
    "result_type",
    "feature_count",
    "affected_area_ha",
    "affected_pct",
    "nearest_distance_m",
]

# Controlled vocabulary for ``result_type`` - no qualitative ranking.
RESULT_TYPE_OVERLAP = "overlap"
RESULT_TYPE_CONTEXT = "context"


@dataclass(frozen=True)
class ScreeningDatasets:
    """The already-prepared environmental layers a screening run needs.

    Every field except ``flood_zones_path`` is the output of that theme's loader
    (``load_sssi``, ``load_sssi_irz``, ``load_priority_habitats``,
    ``load_ancient_woodland_revised`` / ``_legacy``, ``load_revised_coverage``),
    already in EPSG:27700. These are reusable across many sites.

    Flood Zones is different: its production loader is site-bbox based (the
    national layer is ~5.9 GB / 800k+ features), so only the *path* is held here
    and :func:`screen_site` calls ``load_flood_zones(path, bbox=site bounds)``
    after the site has been validated.
    """

    sssi: gpd.GeoDataFrame
    sssi_irz: gpd.GeoDataFrame
    priority_habitats: gpd.GeoDataFrame
    ancient_woodland_revised: gpd.GeoDataFrame
    ancient_woodland_legacy: gpd.GeoDataFrame
    ancient_woodland_revised_coverage: gpd.GeoDataFrame
    flood_zones_path: str | pathlib.Path


@dataclass(frozen=True)
class ScreeningResult:
    """Everything one screening run produced.

    The individual theme result objects are kept as-is (not flattened) so a
    caller can drill into any of them. ``summary`` is a compact
    :class:`pandas.DataFrame` for display.

    Attributes
    ----------
    site:
        The validated candidate site (one row, EPSG:27700). A copy - the input
        GeoDataFrame is not mutated.
    sssi:
        :class:`~environmental_site_screener.overlap.SssiOverlapResult`.
    nearest_sssi:
        :class:`~environmental_site_screener.distance.NearestSssiResult`, or
        ``None`` when ``sssi.has_overlap`` is ``True`` (no separate nearest
        calculation is run for an overlapping site). No nearest-distance
        calculation exists for the other themes.
    sssi_irz:
        :class:`~environmental_site_screener.sssi_irz.SssiIrzContextResult`.
    priority_habitats:
        :class:`~environmental_site_screener.priority_habitats.PriorityHabitatOverlapResult`.
    ancient_woodland:
        :class:`~environmental_site_screener.ancient_woodland.AncientWoodlandOverlapResult`
        (revised-over-legacy precedence already applied).
    flood_zones:
        :class:`~environmental_site_screener.flood_zones.FloodZoneOverlapResult`
        for the site-bbox subset.
    summary:
        One row per theme in :data:`SUMMARY_THEMES` order, columns
        :data:`SUMMARY_COLUMNS`. ``feature_count`` uses each theme's own count
        and is **not** comparable across themes (SSSI features vs IRZ zones vs
        priority-habitat classes vs ancient-woodland category rows vs flood-zone
        rows). ``None``/``NaN`` marks a metric that does not apply to a theme;
        ``0.0`` marks an applicable metric whose measured value is genuinely
        zero.
    """

    site: gpd.GeoDataFrame
    sssi: SssiOverlapResult
    nearest_sssi: NearestSssiResult | None
    sssi_irz: SssiIrzContextResult
    priority_habitats: PriorityHabitatOverlapResult
    ancient_woodland: AncientWoodlandOverlapResult
    flood_zones: FloodZoneOverlapResult
    summary: pd.DataFrame


def load_screening_datasets(
    *,
    sssi_path: str | pathlib.Path,
    sssi_irz_path: str | pathlib.Path,
    priority_habitats_path: str | pathlib.Path,
    ancient_woodland_revised_path: str | pathlib.Path,
    ancient_woodland_legacy_path: str | pathlib.Path,
    revised_coverage_path: str | pathlib.Path,
    flood_zones_path: str | pathlib.Path,
) -> ScreeningDatasets:
    """Load the reusable layers once and keep the Flood Zones path for later.

    A convenience constructor for :class:`ScreeningDatasets`; loader errors
    propagate unchanged.
    """
    return ScreeningDatasets(
        sssi=load_sssi(sssi_path),
        sssi_irz=load_sssi_irz(sssi_irz_path),
        priority_habitats=load_priority_habitats(priority_habitats_path),
        ancient_woodland_revised=load_ancient_woodland_revised(ancient_woodland_revised_path),
        ancient_woodland_legacy=load_ancient_woodland_legacy(ancient_woodland_legacy_path),
        ancient_woodland_revised_coverage=load_revised_coverage(revised_coverage_path),
        flood_zones_path=pathlib.Path(flood_zones_path),
    )


def _build_summary(
    sssi: SssiOverlapResult,
    nearest_sssi: NearestSssiResult | None,
    sssi_irz: SssiIrzContextResult,
    priority_habitats: PriorityHabitatOverlapResult,
    ancient_woodland: AncientWoodlandOverlapResult,
    flood_zones: FloodZoneOverlapResult,
) -> pd.DataFrame:
    records = [
        {
            "theme": "SSSI",
            "has_result": bool(sssi.has_overlap),
            "result_type": RESULT_TYPE_OVERLAP,
            "feature_count": int(sssi.feature_count),
            "affected_area_ha": float(sssi.affected_area_ha),
            "affected_pct": float(sssi.affected_pct),
            # populated only when no overlap was found and nearest was run
            "nearest_distance_m": (
                float(nearest_sssi.distance_m) if nearest_sssi is not None else None
            ),
        },
        {
            "theme": "SSSI Impact Risk Zone",
            "has_result": bool(sssi_irz.has_irz_context),
            "result_type": RESULT_TYPE_CONTEXT,
            "feature_count": int(sssi_irz.zone_count),
            # area / percentage / distance are not meaningful IRZ metrics
            "affected_area_ha": None,
            "affected_pct": None,
            "nearest_distance_m": None,
        },
        {
            "theme": "Priority Habitats",
            "has_result": bool(priority_habitats.has_priority_overlap),
            "result_type": RESULT_TYPE_OVERLAP,
            # count of priority habitat classes, not raw polygons
            "feature_count": int(priority_habitats.habitat_count),
            # priority metric only; context-only polygons do not count here
            "affected_area_ha": float(priority_habitats.affected_area_ha),
            "affected_pct": float(priority_habitats.affected_pct),
            "nearest_distance_m": None,
        },
        {
            "theme": "Ancient Woodland",
            "has_result": bool(ancient_woodland.has_overlap),
            "result_type": RESULT_TYPE_OVERLAP,
            # count of (inventory, category) output rows
            "feature_count": int(ancient_woodland.feature_count),
            "affected_area_ha": float(ancient_woodland.affected_area_ha),
            "affected_pct": float(ancient_woodland.affected_pct),
            "nearest_distance_m": None,
        },
        {
            "theme": "Flood Zones",
            "has_result": bool(flood_zones.has_flood_zone_overlap),
            "result_type": RESULT_TYPE_OVERLAP,
            # count of overlapping flood-zone rows (0, 1 or 2)
            "feature_count": int(flood_zones.zone_count),
            "affected_area_ha": float(flood_zones.affected_area_ha),
            "affected_pct": float(flood_zones.affected_pct),
            "nearest_distance_m": None,
        },
    ]
    summary = pd.DataFrame.from_records(records, columns=SUMMARY_COLUMNS)
    return summary.astype(
        {
            "theme": "object",
            "has_result": "bool",
            "result_type": "object",
            "feature_count": "int64",
            "affected_area_ha": "float64",
            "affected_pct": "float64",
            "nearest_distance_m": "float64",
        }
    )


def screen_site(
    site: gpd.GeoDataFrame, datasets: ScreeningDatasets
) -> ScreeningResult:
    """Screen one candidate site against all five environmental themes.

    Parameters
    ----------
    site:
        A single-feature GeoDataFrame with a defined CRS. It is validated and
        reprojected to EPSG:27700 by ``validate_site``; the input object is not
        mutated.
    datasets:
        A :class:`ScreeningDatasets` holding the already-loaded reusable layers
        and the Flood Zones source path.

    Returns
    -------
    ScreeningResult

    Raises
    ------
    TypeError
        If ``datasets`` is not a :class:`ScreeningDatasets`.
    Exception
        Any error from ``validate_site`` or a theme loader/analysis propagates
        unchanged - a broken required dataset fails visibly rather than becoming
        a false "no constraint" result.

    Notes
    -----
    Order of work: validate the site; SSSI overlap; nearest SSSI only when there
    is no positive-area SSSI overlap; SSSI IRZ context; Priority Habitats
    overlap; Ancient Woodland overlap (revised-over-legacy precedence); load the
    Flood Zones subset for ``tuple(site.total_bounds)`` and run Flood Zones
    overlap; build the summary. No cross-theme totals or scores are produced.
    """
    if not isinstance(datasets, ScreeningDatasets):
        raise TypeError(
            f"datasets must be a ScreeningDatasets, got {type(datasets).__name__}"
        )

    validated = validate_site(site)

    sssi_result = calculate_sssi_overlap(validated, datasets.sssi)
    if sssi_result.has_overlap:
        nearest_sssi: NearestSssiResult | None = None
    else:
        nearest_sssi = calculate_nearest_sssi(validated, datasets.sssi)

    sssi_irz_result = calculate_sssi_irz_context(validated, datasets.sssi_irz)

    priority_habitats_result = calculate_priority_habitat_overlap(
        validated, datasets.priority_habitats
    )

    ancient_woodland_result = calculate_ancient_woodland_overlap(
        validated,
        datasets.ancient_woodland_revised,
        datasets.ancient_woodland_legacy,
        datasets.ancient_woodland_revised_coverage,
    )

    flood_zones_layer = load_flood_zones(
        datasets.flood_zones_path, bbox=tuple(validated.total_bounds)
    )
    flood_zones_result = calculate_flood_zone_overlap(validated, flood_zones_layer)

    summary = _build_summary(
        sssi_result,
        nearest_sssi,
        sssi_irz_result,
        priority_habitats_result,
        ancient_woodland_result,
        flood_zones_result,
    )

    return ScreeningResult(
        site=validated,
        sssi=sssi_result,
        nearest_sssi=nearest_sssi,
        sssi_irz=sssi_irz_result,
        priority_habitats=priority_habitats_result,
        ancient_woodland=ancient_woodland_result,
        flood_zones=flood_zones_result,
        summary=summary,
    )
