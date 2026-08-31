"""Manual real-data smoke check of the full screening orchestration.

Run from anywhere; paths are resolved relative to the repository root::

    python scripts/check_full_screening.py

This loads the reusable environmental layers once, then runs ``screen_site``
against one deterministic candidate site and prints the compact summary plus a
few per-theme details. It reports the reusable-dataset load time and the single
``screen_site`` time separately, so we can see whether the national layers other
than Flood Zones need the same site-bbox treatment before a UI is built.

Broad assertions only - the site is not expected to overlap every theme.
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
import pandas as pd  # noqa: E402
from shapely.geometry import box  # noqa: E402

from environmental_site_screener.screening import (  # noqa: E402
    SUMMARY_COLUMNS,
    SUMMARY_THEMES,
    load_screening_datasets,
    screen_site,
)

RAW = REPO_ROOT / "data" / "raw"
SOURCES = {
    "sssi_path": RAW / "sssi" / "Sites_of_Special_Scientific_Interest_England.gpkg",
    "sssi_irz_path": RAW / "sssi_irz" / "SSSI_Impact_Risk_Zones_England.gpkg",
    "priority_habitats_path": RAW / "priority_habitats" / "Priority_Habitats_Inventory_England.gpkg",
    "ancient_woodland_revised_path": RAW
    / "ancient_woodland"
    / "revised"
    / "Ancient_Woodland_Revised_England_Completed_Counties.gpkg",
    "ancient_woodland_legacy_path": RAW
    / "ancient_woodland"
    / "legacy"
    / "Ancient_Woodland_England.gpkg",
    "revised_coverage_path": RAW
    / "ancient_woodland"
    / "coverage"
    / "Boundary-line-ceremonial-counties_region.shp",
    "flood_zones_path": RAW / "flood_zones" / "Flood_Map_for_Planning_Flood_Zones.gpkg",
}

# Deterministic candidate site: a 200 m square in the Essex/Suffolk area that
# earlier per-theme checks showed sits on revised ancient woodland.
_CENTRE = (565_247.0, 195_257.0)
_HALF = 100.0


def main() -> int:
    for key, path in SOURCES.items():
        if not path.exists():
            print(f"ERROR: local source not found ({key}): {path}", file=sys.stderr)
            return 1

    t0 = time.perf_counter()
    with warnings.catch_warnings(record=True) as load_caught:
        warnings.simplefilter("always")
        datasets = load_screening_datasets(**SOURCES)
    load_seconds = time.perf_counter() - t0
    load_warnings = [str(w.message) for w in load_caught if issubclass(w.category, UserWarning)]

    site = gpd.GeoDataFrame(
        geometry=[
            box(
                _CENTRE[0] - _HALF,
                _CENTRE[1] - _HALF,
                _CENTRE[0] + _HALF,
                _CENTRE[1] + _HALF,
            )
        ],
        crs="EPSG:27700",
    )

    t1 = time.perf_counter()
    with warnings.catch_warnings(record=True) as screen_caught:
        warnings.simplefilter("always")
        result = screen_site(site, datasets)
    screen_seconds = time.perf_counter() - t1
    screen_warnings = [str(w.message) for w in screen_caught if issubclass(w.category, UserWarning)]

    minx, miny, maxx, maxy = result.site.total_bounds
    site_area_m2 = float(result.site.geometry.iloc[0].area)

    print("== timings ==")
    print(f"reusable dataset load : {load_seconds:.1f} s")
    print(f"one screen_site() call: {screen_seconds:.1f} s")
    if load_warnings:
        print("load warnings         :")
        for m in load_warnings:
            print(f"    - {m}")
    if screen_warnings:
        print("screen warnings       :")
        for m in screen_warnings:
            print(f"    - {m}")

    print("\n== candidate site ==")
    print(f"bounds : ({minx:.1f}, {miny:.1f}, {maxx:.1f}, {maxy:.1f})")
    print(f"area   : {site_area_m2:,.1f} m^2 ({site_area_m2 / 10_000:.4f} ha)")
    print(f"CRS    : EPSG:{result.site.crs.to_epsg()}")

    print("\n== summary ==")
    print(result.summary.to_string(index=False))

    print("\n== per-theme detail ==")
    if result.sssi.has_overlap:
        print(f"SSSI            : overlap, {result.sssi.feature_count} feature(s), "
              f"{result.sssi.affected_area_ha:.4f} ha ({result.sssi.affected_pct:.2f}%)")
    else:
        nd = result.nearest_sssi
        print(f"SSSI            : no overlap; nearest {nd.distance_m:,.1f} m "
              f"({nd.feature_count} feature(s))")
    print(f"SSSI IRZ        : has_context={result.sssi_irz.has_irz_context}, "
          f"zone_count={result.sssi_irz.zone_count}")
    print(f"Priority Habitats: has_overlap={result.priority_habitats.has_priority_overlap}, "
          f"{result.priority_habitats.affected_area_ha:.4f} ha "
          f"({result.priority_habitats.affected_pct:.2f}%)")
    print(f"Ancient Woodland: has_overlap={result.ancient_woodland.has_overlap}, "
          f"{result.ancient_woodland.affected_area_ha:.4f} ha "
          f"({result.ancient_woodland.affected_pct:.2f}%)")
    print(f"Flood Zones     : has_overlap={result.flood_zones.has_flood_zone_overlap}, "
          f"{result.flood_zones.affected_area_ha:.4f} ha "
          f"({result.flood_zones.affected_pct:.2f}%)")

    summary = result.summary
    assert len(summary) == 5, "expected five summary rows"
    assert list(summary.columns) == SUMMARY_COLUMNS, "unexpected summary schema"
    assert tuple(summary["theme"]) == SUMMARY_THEMES, "unexpected summary theme order"
    assert result.site.crs.to_epsg() == 27700, "validated site not EPSG:27700"

    irz_row = summary.loc[summary["theme"] == "SSSI Impact Risk Zone"].iloc[0]
    assert irz_row["result_type"] == "context", "IRZ row should be contextual"
    assert pd.isna(irz_row["affected_area_ha"]), "IRZ affected_area_ha should be null"
    assert pd.isna(irz_row["affected_pct"]), "IRZ affected_pct should be null"

    for theme in ("SSSI", "Priority Habitats", "Ancient Woodland", "Flood Zones"):
        row = summary.loc[summary["theme"] == theme].iloc[0]
        pct = row["affected_pct"]
        if not pd.isna(pct):
            assert 0 <= pct <= 100, f"{theme} affected_pct out of range: {pct}"

    assert set(summary.columns) == set(SUMMARY_COLUMNS), "summary has an unexpected column"
    assert set(vars(result)) == {
        "site", "sssi", "nearest_sssi", "sssi_irz",
        "priority_habitats", "ancient_woodland", "flood_zones", "summary",
    }, "ScreeningResult exposes an unexpected field (no combined score allowed)"

    print("\nAll broad full-screening assertions passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
