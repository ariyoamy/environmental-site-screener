"""Nearest-SSSI distance analysis for a validated candidate site.

:func:`calculate_nearest_sssi` reports the closest Site of Special Scientific
Interest to a candidate site and the edge-to-edge distance in metres. It is
intended mainly for the case where
:func:`environmental_site_screener.overlap.calculate_sssi_overlap` found no
positive-area overlap.

Inputs are expected to have been prepared by
:func:`environmental_site_screener.site.validate_site` and
:func:`environmental_site_screener.sssi.load_sssi`, so both are already valid,
polygonal and in EPSG:27700. This function does not re-run that validation; it
applies only the small guard set described in :func:`calculate_nearest_sssi`.
"""

from __future__ import annotations

from dataclasses import dataclass

import geopandas as gpd

EXPECTED_EPSG = 27700

REQUIRED_SSSI_COLUMNS = ("ref_code", "name", "measure")

FEATURE_COLUMNS = ["ref_code", "name", "measure", "geometry"]


@dataclass(frozen=True)
class NearestSssiResult:
    """Result of a nearest-SSSI distance analysis.

    Attributes
    ----------
    distance_m:
        Minimum edge-to-edge distance from the candidate site to the nearest
        SSSI, in metres. ``0.0`` when the site touches or overlaps an SSSI; a
        zero distance only means there is no spatial separation. Positive-area
        overlap is determined by ``calculate_sssi_overlap``, not here.
    distance_km:
        ``distance_m / 1000``.
    feature_count:
        Number of SSSI features returned. Normally 1; greater than 1 only when
        several SSSIs are exactly the same minimum distance away.
    features:
        The nearest SSSI feature(s), columns ``ref_code``, ``name``, ``measure``
        and ``geometry`` (the original, unclipped SSSI geometry), EPSG:27700,
        sorted by ``ref_code``.
    """

    distance_m: float
    distance_km: float
    feature_count: int
    features: gpd.GeoDataFrame


def calculate_nearest_sssi(
    site: gpd.GeoDataFrame, sssi: gpd.GeoDataFrame
) -> NearestSssiResult:
    """Find the nearest SSSI to a candidate site and the edge-to-edge distance.

    Parameters
    ----------
    site:
        Single-row GeoDataFrame from ``validate_site`` (EPSG:27700).
    sssi:
        SSSI layer from ``load_sssi`` (EPSG:27700), with columns ``ref_code``,
        ``name`` and ``measure`` and at least one feature.

    Returns
    -------
    NearestSssiResult

    Raises
    ------
    TypeError
        If either input is not a GeoDataFrame.
    ValueError
        If either input has no CRS, if either input does not resolve to
        EPSG:27700, if ``site`` does not contain exactly one row, if ``sssi`` is
        missing a required column, or if ``sssi`` contains no features (nearest
        distance is undefined with nothing to measure to).

    Notes
    -----
    Inputs are not reprojected and geometry is not repaired. Geometry validity,
    polygonal geometry and ``ref_code`` validity are assumed to have been
    established by ``validate_site`` / ``load_sssi``. Distance is a planar
    edge-to-edge calculation in EPSG:27700; centroid distance is not used. Only
    exactly equal calculated distances are treated as ties; no numeric tolerance
    is applied.
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

    if len(sssi) == 0:
        raise ValueError(
            "sssi contains no features; nearest distance is undefined without "
            "at least one SSSI to measure to"
        )

    site_geom = site.geometry.iloc[0]
    distances = sssi.geometry.distance(site_geom)
    distance_m = float(distances.min())

    features = sssi.loc[distances == distance_m, FEATURE_COLUMNS].copy()
    features = features.sort_values("ref_code", kind="stable").reset_index(drop=True)

    return NearestSssiResult(
        distance_m=distance_m,
        distance_km=distance_m / 1000.0,
        feature_count=len(features),
        features=features,
    )
