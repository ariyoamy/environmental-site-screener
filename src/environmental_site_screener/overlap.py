"""Candidate-site overlap analysis against SSSI polygons.

:func:`calculate_sssi_overlap` reports where a single candidate site polygon
overlaps one or more Sites of Special Scientific Interest, how much of the site
is affected, and which SSSI features are involved. It performs no nearest-feature
distance calculation and produces no user-facing wording.

Inputs are expected to have been prepared by
:func:`environmental_site_screener.site.validate_site` and
:func:`environmental_site_screener.sssi.load_sssi`, so both are already valid,
polygonal and in EPSG:27700. This function does not re-run that validation; it
only applies a small set of guards (see :func:`calculate_sssi_overlap`).
"""

from __future__ import annotations

from dataclasses import dataclass

import geopandas as gpd
import pandas as pd
from shapely import union_all

EXPECTED_EPSG = 27700

REQUIRED_SSSI_COLUMNS = ("ref_code", "name", "measure")

_ATTR_COLUMNS = [
    "ref_code",
    "name",
    "measure",
    "intersection_area_m2",
    "intersection_area_ha",
]
FEATURE_COLUMNS = [*_ATTR_COLUMNS, "geometry"]


@dataclass(frozen=True)
class SssiOverlapResult:
    """Result of a candidate-site / SSSI overlap analysis.

    Attributes
    ----------
    has_overlap:
        True when at least one SSSI overlaps the site with positive area. SSSIs
        that only touch the site boundary do not count.
    feature_count:
        Number of SSSI features involved (rows in ``features``).
    features:
        One row per overlapping SSSI, columns ``ref_code``, ``name``,
        ``measure``, ``intersection_area_m2``, ``intersection_area_ha`` and
        ``geometry`` (the clipped site/SSSI intersection), EPSG:27700, sorted by
        descending ``intersection_area_m2``. Empty with this exact schema when
        there is no overlap.
    site_area_m2:
        Area of the candidate site polygon, square metres.
    affected_area_m2:
        Area of the candidate site covered by any SSSI, square metres,
        de-duplicated so that area under several SSSIs is counted once.
    affected_area_ha:
        ``affected_area_m2 / 10_000``.
    affected_pct:
        ``100 * affected_area_m2 / site_area_m2``.
    """

    has_overlap: bool
    feature_count: int
    features: gpd.GeoDataFrame
    site_area_m2: float
    affected_area_m2: float
    affected_area_ha: float
    affected_pct: float


def calculate_sssi_overlap(
    site: gpd.GeoDataFrame, sssi: gpd.GeoDataFrame
) -> SssiOverlapResult:
    """Calculate positive-area overlap between a candidate site and SSSI polygons.

    Parameters
    ----------
    site:
        Single-row GeoDataFrame from ``validate_site`` (EPSG:27700).
    sssi:
        SSSI layer from ``load_sssi`` (EPSG:27700), with columns ``ref_code``,
        ``name`` and ``measure``.

    Returns
    -------
    SssiOverlapResult

    Raises
    ------
    TypeError
        If either input is not a GeoDataFrame.
    ValueError
        If either input has no CRS, if either input does not resolve to
        EPSG:27700, if ``site`` does not contain exactly one row, or if ``sssi``
        is missing a required column.

    Notes
    -----
    Inputs are not reprojected and geometry is not repaired. Geometry validity
    and ``ref_code`` uniqueness are assumed to have been established by
    ``validate_site`` / ``load_sssi``.
    """
    if not isinstance(site, gpd.GeoDataFrame):
        raise TypeError(
            f"site must be a geopandas.GeoDataFrame, got {type(site).__name__}"
        )
    if not isinstance(sssi, gpd.GeoDataFrame):
        raise TypeError(
            f"sssi must be a geopandas.GeoDataFrame, got {type(sssi).__name__}"
        )

    if site.crs is None:
        raise ValueError("site has no CRS defined; EPSG:27700 is required")
    if sssi.crs is None:
        raise ValueError("sssi has no CRS defined; EPSG:27700 is required")

    if site.crs.to_epsg() != EXPECTED_EPSG:
        raise ValueError(
            f"site CRS must be EPSG:27700; got EPSG:{site.crs.to_epsg()}"
        )
    if sssi.crs.to_epsg() != EXPECTED_EPSG:
        raise ValueError(
            f"sssi CRS must be EPSG:27700; got EPSG:{sssi.crs.to_epsg()}"
        )

    if len(site) != 1:
        raise ValueError(f"site must contain exactly one row; got {len(site)}")

    missing = [c for c in REQUIRED_SSSI_COLUMNS if c not in sssi.columns]
    if missing:
        raise ValueError(f"sssi is missing required column(s): {missing}")

    site_geom = site.geometry.iloc[0]
    site_area_m2 = float(site_geom.area)

    candidates = sssi.loc[sssi.geometry.intersects(site_geom)]

    records = []
    clipped_geoms = []
    for ref_code, name, measure, geom in zip(
        candidates["ref_code"],
        candidates["name"],
        candidates["measure"],
        candidates.geometry,
    ):
        clipped = geom.intersection(site_geom)
        area_m2 = float(clipped.area)
        if area_m2 <= 0:
            continue
        records.append(
            {
                "ref_code": ref_code,
                "name": name,
                "measure": measure,
                "intersection_area_m2": area_m2,
                "intersection_area_ha": area_m2 / 10_000,
            }
        )
        clipped_geoms.append(clipped)

    attr_df = pd.DataFrame.from_records(records, columns=_ATTR_COLUMNS).astype(
        {"intersection_area_m2": "float64", "intersection_area_ha": "float64"}
    )
    features = gpd.GeoDataFrame(
        attr_df,
        geometry=gpd.GeoSeries(clipped_geoms, index=attr_df.index, crs=site.crs),
    )
    features = (
        features.sort_values(
            "intersection_area_m2", ascending=False, kind="stable"
        )
        .reset_index(drop=True)
        .loc[:, FEATURE_COLUMNS]
    )

    if clipped_geoms:
        affected_area_m2 = float(union_all(clipped_geoms).area)
    else:
        affected_area_m2 = 0.0

    feature_count = len(features)
    return SssiOverlapResult(
        has_overlap=feature_count > 0,
        feature_count=feature_count,
        features=features,
        site_area_m2=site_area_m2,
        affected_area_m2=affected_area_m2,
        affected_area_ha=affected_area_m2 / 10_000,
        affected_pct=100.0 * affected_area_m2 / site_area_m2,
    )
