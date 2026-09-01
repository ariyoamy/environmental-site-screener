"""Shared synthetic backend result builders for the app-level test modules.

Not a test module itself (no ``test_`` prefix). Both ``test_app_helpers.py`` and
``test_app_qa.py`` import these to construct :class:`ScreeningResult` objects
without loading any real datasets or running any spatial analysis.
"""

from __future__ import annotations

import geopandas as gpd
from shapely.geometry import Polygon

from environmental_site_screener import screening
from environmental_site_screener.ancient_woodland import AncientWoodlandOverlapResult
from environmental_site_screener.app_data import demo_site
from environmental_site_screener.distance import NearestSssiResult
from environmental_site_screener.flood_zones import FloodZoneOverlapResult
from environmental_site_screener.overlap import SssiOverlapResult
from environmental_site_screener.priority_habitats import PriorityHabitatOverlapResult
from environmental_site_screener.screening import ScreeningResult
from environmental_site_screener.sssi_irz import SssiIrzContextResult

CRS = "EPSG:27700"


def rect(xmin, ymin, xmax, ymax):
    return Polygon(
        [(xmin, ymin), (xmin, ymax), (xmax, ymax), (xmax, ymin), (xmin, ymin)]
    )


def empty_gdf(columns):
    return gpd.GeoDataFrame(
        {c: [] for c in columns if c != "geometry"}, geometry=[], crs=CRS
    )


def mk_sssi(*, has_overlap=True, area_ha=0.3838, pct=48.34, feature_count=1):
    cols = [
        "ref_code",
        "name",
        "measure",
        "intersection_area_m2",
        "intersection_area_ha",
        "geometry",
    ]
    if has_overlap:
        feats = gpd.GeoDataFrame(
            {
                "ref_code": ["S1"],
                "name": ["Test SSSI"],
                "measure": ["Lowland fen"],
                "intersection_area_m2": [area_ha * 10_000],
                "intersection_area_ha": [area_ha],
            },
            geometry=[rect(0, 0, 62, 62)],
            crs=CRS,
        )
    else:
        feats = empty_gdf(cols)
    return SssiOverlapResult(
        has_overlap=has_overlap,
        feature_count=feature_count if has_overlap else 0,
        features=feats,
        site_area_m2=10_000.0,
        affected_area_m2=area_ha * 10_000 if has_overlap else 0.0,
        affected_area_ha=area_ha if has_overlap else 0.0,
        affected_pct=pct if has_overlap else 0.0,
    )


def mk_nearest(*, distance_m=2659.06, name="Far SSSI"):
    feats = gpd.GeoDataFrame(
        {"ref_code": ["S9"], "name": [name], "measure": ["Broadleaved woodland"]},
        geometry=[rect(5_000, 5_000, 5_100, 5_100)],
        crs=CRS,
    )
    return NearestSssiResult(
        distance_m=distance_m,
        distance_km=distance_m / 1_000,
        feature_count=1,
        features=feats,
    )


def mk_irz(*, zone_count=2):
    cols = ["irzurl", "irz_code", "geometry"]
    if zone_count:
        urls = [f"https://example.test/?irzcode={i:013d}" for i in range(zone_count)]
        zones = gpd.GeoDataFrame(
            {"irzurl": urls, "irz_code": [f"{i:013d}" for i in range(zone_count)]},
            geometry=[rect(0, 0, 80, 80) for _ in range(zone_count)],
            crs=CRS,
        )
        advice = tuple(sorted(set(urls)))
    else:
        zones = empty_gdf(cols)
        advice = ()
    return SssiIrzContextResult(
        has_irz_context=bool(zone_count),
        zone_count=zone_count,
        zones=zones,
        advice_urls=advice,
    )


def mk_phi(*, has=True, area_ha=2.5688, pct=64.22, habitat_count=2, with_context=False):
    hcols = [
        "habitat_code",
        "habitat_name",
        "intersection_area_m2",
        "intersection_area_ha",
        "geometry",
    ]
    ccols = ["uid", "context_codes", "context_habitats", "primsource", "geometry"]
    if has:
        habitats = gpd.GeoDataFrame(
            {
                "habitat_code": ["DWOOD", "LMEAD"][:habitat_count],
                "habitat_name": ["Deciduous woodland", "Lowland meadow"][:habitat_count],
                "intersection_area_m2": [area_ha * 10_000, 1_000.0][:habitat_count],
                "intersection_area_ha": [area_ha, 0.1][:habitat_count],
            },
            geometry=[rect(0, 0, 50, 50), rect(10, 10, 20, 20)][:habitat_count],
            crs=CRS,
        )
    else:
        habitats = empty_gdf(hcols)
    if with_context:
        context = gpd.GeoDataFrame(
            {
                "uid": ["PHI9"],
                "context_codes": ["GMOOR"],
                "context_habitats": ["Grass moorland"],
                "primsource": ["test survey"],
            },
            geometry=[rect(0, 0, 30, 30)],
            crs=CRS,
        )
    else:
        context = empty_gdf(ccols)
    return PriorityHabitatOverlapResult(
        has_priority_overlap=has,
        habitat_count=habitat_count if has else 0,
        habitats=habitats,
        context=context,
        site_area_m2=10_000.0,
        affected_area_m2=area_ha * 10_000 if has else 0.0,
        affected_area_ha=area_ha if has else 0.0,
        affected_pct=pct if has else 0.0,
    )


def mk_aw(*, has=True, area_ha=1.0961, pct=27.40, feature_count=1):
    cols = [
        "inventory",
        "category_code",
        "category_name",
        "intersection_area_m2",
        "intersection_area_ha",
        "geometry",
    ]
    if has:
        feats = gpd.GeoDataFrame(
            {
                "inventory": ["revised"],
                "category_code": ["ASNW"],
                "category_name": ["Ancient & Semi-Natural Woodland"],
                "intersection_area_m2": [area_ha * 10_000],
                "intersection_area_ha": [area_ha],
            },
            geometry=[rect(0, 0, 40, 40)],
            crs=CRS,
        )
    else:
        feats = empty_gdf(cols)
    return AncientWoodlandOverlapResult(
        has_overlap=has,
        feature_count=feature_count if has else 0,
        features=feats,
        site_area_m2=10_000.0,
        revised_coverage_area_m2=10_000.0,
        fallback_area_m2=0.0,
        affected_area_m2=area_ha * 10_000 if has else 0.0,
        affected_area_ha=area_ha if has else 0.0,
        affected_pct=pct if has else 0.0,
    )


def mk_fz(*, has=True, area_ha=3.3739, pct=84.35, zones_present=("FZ2", "FZ3")):
    cols = [
        "flood_zone",
        "intersection_area_m2",
        "intersection_area_ha",
        "site_pct",
        "flood_sources",
        "origins",
        "geometry",
    ]
    if has:
        n = len(zones_present)
        zones = gpd.GeoDataFrame(
            {
                "flood_zone": list(zones_present),
                "intersection_area_m2": [area_ha * 10_000 / n] * n,
                "intersection_area_ha": [area_ha / n] * n,
                "site_pct": [pct / n] * n,
                "flood_sources": ["river"] * n,
                "origins": ["modelled"] * n,
            },
            geometry=[rect(0, 0, 50, 50) for _ in range(n)],
            crs=CRS,
        )
        sources, origins = ("river",), ("modelled",)
    else:
        zones = empty_gdf(cols)
        sources, origins = (), ()
    return FloodZoneOverlapResult(
        has_flood_zone_overlap=has,
        zone_count=len(zones_present) if has else 0,
        zones=zones,
        site_area_m2=10_000.0,
        affected_area_m2=area_ha * 10_000 if has else 0.0,
        affected_area_ha=area_ha if has else 0.0,
        affected_pct=pct if has else 0.0,
        flood_sources=sources,
        origins=origins,
    )


def mk_result(*, sssi=None, nearest=..., irz=None, phi=None, aw=None, fz=None, site=None):
    sssi = sssi if sssi is not None else mk_sssi(has_overlap=False)
    if nearest is ...:
        nearest = None if sssi.has_overlap else mk_nearest()
    irz = irz if irz is not None else mk_irz(zone_count=2)
    phi = phi if phi is not None else mk_phi(has=True)
    aw = aw if aw is not None else mk_aw(has=True)
    fz = fz if fz is not None else mk_fz(has=True)
    summary = screening._build_summary(sssi, nearest, irz, phi, aw, fz)
    return ScreeningResult(
        site=site if site is not None else demo_site(),
        sssi=sssi,
        nearest_sssi=nearest,
        sssi_irz=irz,
        priority_habitats=phi,
        ancient_woodland=aw,
        flood_zones=fz,
        summary=summary,
    )
