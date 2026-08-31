"""Manual real-data smoke check of the Ancient Woodland overlap analysis.

Run from anywhere; paths are resolved relative to the repository root::

    python scripts/check_ancient_woodland_overlap.py

This runs the implemented pipeline against the real Natural England sources:

1. ``load_ancient_woodland_revised`` / ``load_ancient_woodland_legacy`` read and
   check the two inventories (loader warnings, such as the 69 invalid geometries
   in the revised source, are printed).
2. ``load_revised_coverage`` builds the project-inferred ceremonial-county
   coverage from the OS Boundary-Line layer.
3. A small deterministic candidate site is placed on a revised woodland that
   sits inside the inferred coverage, so the revised precedence path is
   exercised and there is real woodland overlap to report.
4. ``validate_site`` prepares that site.
5. ``calculate_ancient_woodland_overlap`` reports the overlap.

It prints a short summary and applies only broad sanity assertions. No specific
woodland, category or numeric overlap result is pinned. Exits non-zero with a
clear message if a local source is absent or if no overlapping site can be
found. Loading the two ~250-300 MB sources takes tens of seconds.
"""

from __future__ import annotations

import sys
import time
import warnings
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import geopandas as gpd  # noqa: E402
from shapely.geometry import box  # noqa: E402

from environmental_site_screener.ancient_woodland import (  # noqa: E402
    LEGACY_CATEGORIES,
    REVISED_CATEGORIES,
    REVISED_COVERAGE_COUNTIES,
    FEATURE_COLUMNS,
    calculate_ancient_woodland_overlap,
    load_ancient_woodland_legacy,
    load_ancient_woodland_revised,
    load_revised_coverage,
)
from environmental_site_screener.site import validate_site  # noqa: E402

AW_DIR = REPO_ROOT / "data" / "raw" / "ancient_woodland"
REVISED_SOURCE = AW_DIR / "revised" / "Ancient_Woodland_Revised_England_Completed_Counties.gpkg"
LEGACY_SOURCE = AW_DIR / "legacy" / "Ancient_Woodland_England.gpkg"
COVERAGE_SOURCE = AW_DIR / "coverage" / "Boundary-line-ceremonial-counties_region.shp"

SITE_SIZE_M = 100
_HALF = SITE_SIZE_M / 2


def main() -> int:
    for label, path in (
        ("revised", REVISED_SOURCE),
        ("legacy", LEGACY_SOURCE),
        ("coverage", COVERAGE_SOURCE),
    ):
        if not path.exists():
            print(f"ERROR: local {label} source not found: {path}", file=sys.stderr)
            return 1

    t0 = time.perf_counter()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        revised = load_ancient_woodland_revised(REVISED_SOURCE)
    revised_seconds = time.perf_counter() - t0
    revised_warnings = [
        str(w.message) for w in caught if issubclass(w.category, UserWarning)
    ]

    t1 = time.perf_counter()
    with warnings.catch_warnings(record=True) as caught_leg:
        warnings.simplefilter("always")
        legacy = load_ancient_woodland_legacy(LEGACY_SOURCE)
    legacy_seconds = time.perf_counter() - t1
    legacy_warnings = [
        str(w.message) for w in caught_leg if issubclass(w.category, UserWarning)
    ]

    t2 = time.perf_counter()
    coverage = load_revised_coverage(COVERAGE_SOURCE)
    coverage_seconds = time.perf_counter() - t2

    # Deterministic site: the lowest-index revised polygon whose interior
    # representative point lies within a coverage polygon. A spatial join picks
    # the point; coverage is never derived from these points.
    t3 = time.perf_counter()
    rep_points = gpd.GeoDataFrame(
        geometry=revised.geometry.representative_point(), crs=revised.crs
    )
    joined = gpd.sjoin(rep_points, coverage, predicate="within", how="inner")
    if len(joined) == 0:
        print(
            "ERROR: no revised woodland representative point lies within coverage",
            file=sys.stderr,
        )
        return 1
    pick = joined.sort_index().geometry.iloc[0]
    site_box = box(pick.x - _HALF, pick.y - _HALF, pick.x + _HALF, pick.y + _HALF)
    site = validate_site(gpd.GeoDataFrame(geometry=[site_box], crs=revised.crs))
    result = calculate_ancient_woodland_overlap(site, revised, legacy, coverage)
    analysis_seconds = time.perf_counter() - t3

    minx, miny, maxx, maxy = site.total_bounds

    print(f"revised source        : {REVISED_SOURCE}")
    print(f"legacy source         : {LEGACY_SOURCE}")
    print(f"coverage source       : {COVERAGE_SOURCE}")
    print(f"revised row count     : {len(revised)}")
    print(f"legacy row count      : {len(legacy)}")
    print(f"load time             : revised {revised_seconds:.1f} s, legacy {legacy_seconds:.1f} s, "
          f"coverage {coverage_seconds:.1f} s")
    print(f"analysis time         : {analysis_seconds:.1f} s")
    if revised_warnings:
        print("revised loader warns  :")
        for message in revised_warnings:
            print(f"    - {message}")
    else:
        print("revised loader warns  : none")
    if legacy_warnings:
        print("legacy loader warns   :")
        for message in legacy_warnings:
            print(f"    - {message}")
    else:
        print("legacy loader warns   : none")
    print(f"coverage counties     : {len(coverage)}")
    print(f"    {', '.join(coverage['county_name'])}")
    print(f"candidate-site bounds : ({minx:.1f}, {miny:.1f}, {maxx:.1f}, {maxy:.1f})")
    print(
        f"site area split       : {result.revised_coverage_area_m2:,.1f} m^2 in revised "
        f"coverage, {result.fallback_area_m2:,.1f} m^2 fallback "
        f"(site {result.site_area_m2:,.1f} m^2)"
    )
    print(f"has_overlap           : {result.has_overlap}")
    print(f"feature_count         : {result.feature_count}")
    print("woodland features     :")
    for row in result.features.itertuples(index=False):
        print(
            f"    {row.inventory:7s} | {row.category_code:5s} | {row.category_name} | "
            f"{row.intersection_area_ha:.4f} ha"
        )
    print(
        f"affected area         : {result.affected_area_m2:,.1f} m^2 "
        f"({result.affected_area_ha:.4f} ha, {result.affected_pct:.2f}% of site)"
    )

    assert result.has_overlap is True, "expected ancient woodland overlap"
    assert result.feature_count >= 1, "expected at least one woodland feature"
    assert len(result.features) == result.feature_count, "feature_count / features mismatch"
    assert result.affected_area_m2 > 0, "expected a positive affected area"
    assert 0 < result.affected_pct <= 100, f"affected_pct out of range: {result.affected_pct}"
    assert abs(result.affected_area_ha - result.affected_area_m2 / 10_000) < 1e-9, "ha != m2/10_000"
    assert abs(
        (result.revised_coverage_area_m2 + result.fallback_area_m2) - result.site_area_m2
    ) < 1e-6 * result.site_area_m2, "coverage + fallback != site area"
    assert list(result.features.columns) == FEATURE_COLUMNS, (
        f"unexpected features columns: {list(result.features.columns)}"
    )
    assert result.features.crs.to_epsg() == 27700, "features not in EPSG:27700"
    assert len(coverage) == len(REVISED_COVERAGE_COUNTIES), "coverage county count mismatch"
    _allowed = {"revised": set(REVISED_CATEGORIES), "legacy": set(LEGACY_CATEGORIES)}
    for row in result.features.itertuples(index=False):
        assert row.inventory in _allowed, f"unexpected inventory: {row.inventory}"
        assert row.category_code in _allowed[row.inventory], (
            f"category {row.category_code} not valid for {row.inventory}"
        )

    print("\nAll broad ancient-woodland overlap assertions passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
