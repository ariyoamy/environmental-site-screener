"""Manual real-data smoke check of the Priority Habitats overlap analysis.

Run from anywhere; paths are resolved relative to the repository root::

    python scripts/check_priority_habitats_overlap.py

This runs the implemented pipeline against the real Natural England Priority
Habitats Inventory GeoPackage:

1. ``load_priority_habitats`` reads and checks the PHI layer (any loader
   warnings, such as the invalid-geometry count in the authoritative source,
   are printed).
2. A small deterministic 100 m x 100 m candidate site is found by stepping
   through a fixed sequence of offsets until it overlaps a priority habitat.
3. ``validate_site`` prepares that site.
4. ``calculate_priority_habitat_overlap`` reports the overlap.

It prints a short summary and applies only broad sanity assertions. No specific
habitat, uid or numeric overlap result is pinned. Exits non-zero with a clear
message if the local source is absent or if no site with priority overlap can be
found. Note: loading the ~2.6 GB source into memory takes tens of seconds.
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

from environmental_site_screener.priority_habitats import (  # noqa: E402
    PRIORITY_HABITAT_CODES,
    calculate_priority_habitat_overlap,
    load_priority_habitats,
)
from environmental_site_screener.site import validate_site  # noqa: E402

SOURCE = (
    REPO_ROOT
    / "data"
    / "raw"
    / "priority_habitats"
    / "Priority_Habitats_Inventory_England.gpkg"
)

SITE_SIZE_M = 100
_HALF = SITE_SIZE_M / 2
_START = (400_000.0, 300_000.0)  # habitat-dense area of central England
_STEP_M = 500
_MAX_RINGS = 80

CANDIDATE_OFFSETS = [
    (i * _STEP_M, j * _STEP_M)
    for ring in range(_MAX_RINGS)
    for i in range(-ring, ring + 1)
    for j in range(-ring, ring + 1)
    if max(abs(i), abs(j)) == ring
]


def main() -> int:
    if not SOURCE.exists():
        print(f"ERROR: local Priority Habitats source not found: {SOURCE}", file=sys.stderr)
        return 1

    t0 = time.perf_counter()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        phi = load_priority_habitats(SOURCE)
    load_seconds = time.perf_counter() - t0
    loader_warnings = [
        str(w.message) for w in caught if issubclass(w.category, UserWarning)
    ]

    sindex = phi.sindex  # used only to locate a candidate site quickly

    t1 = time.perf_counter()
    site = None
    chosen_offset = None
    result = None
    for dx, dy in CANDIDATE_OFFSETS:
        cx, cy = _START[0] + dx, _START[1] + dy
        candidate_box = box(cx - _HALF, cy - _HALF, cx + _HALF, cy + _HALF)
        if not len(sindex.query(candidate_box, predicate="intersects")):
            continue
        candidate = validate_site(gpd.GeoDataFrame(geometry=[candidate_box], crs=phi.crs))
        candidate_result = calculate_priority_habitat_overlap(candidate, phi)
        if candidate_result.has_priority_overlap:
            site, chosen_offset, result = candidate, (dx, dy), candidate_result
            break
    search_seconds = time.perf_counter() - t1

    if result is None:
        print(
            f"ERROR: no candidate site with priority-habitat overlap found within "
            f"{_MAX_RINGS} rings of {_START}",
            file=sys.stderr,
        )
        return 1

    minx, miny, maxx, maxy = site.total_bounds

    print(f"source               : {SOURCE}")
    print(f"source row count     : {len(phi)}")
    print(f"load time            : {load_seconds:.1f} s")
    print(f"site-search time     : {search_seconds:.1f} s")
    if loader_warnings:
        print("loader warnings      :")
        for message in loader_warnings:
            print(f"    - {message}")
    else:
        print("loader warnings      : none")
    print(
        f"candidate offset     : {chosen_offset[0]:.0f} m east, "
        f"{chosen_offset[1]:.0f} m north of {_START}"
    )
    print(
        f"candidate-site bounds: ({minx:.1f}, {miny:.1f}, {maxx:.1f}, {maxy:.1f})"
    )
    print(f"has_priority_overlap : {result.has_priority_overlap}")
    print(f"habitat_count        : {result.habitat_count}")
    print("priority habitats    :")
    for row in result.habitats.itertuples(index=False):
        print(
            f"    {row.habitat_code} | {row.habitat_name} | "
            f"{row.intersection_area_ha:.4f} ha"
        )
    print(
        f"affected area        : {result.affected_area_m2:,.1f} m^2 "
        f"({result.affected_area_ha:.4f} ha, {result.affected_pct:.2f}% of site)"
    )
    if len(result.context):
        print("context rows         :")
        for row in result.context.itertuples(index=False):
            print(f"    {row.uid} | {row.context_codes} | {row.context_habitats}")
    else:
        print("context rows         : none")

    assert result.has_priority_overlap is True, "expected priority-habitat overlap"
    assert result.habitat_count >= 1, "expected at least one priority habitat"
    assert len(result.habitats) == result.habitat_count, "habitat_count / habitats mismatch"
    assert result.affected_area_m2 > 0, "expected a positive affected area"
    assert 0 < result.affected_pct <= 100, f"affected_pct out of range: {result.affected_pct}"
    assert abs(result.affected_area_ha - result.affected_area_m2 / 10_000) < 1e-9, "ha != m2/10_000"
    assert list(result.habitats.columns) == [
        "habitat_code", "habitat_name", "intersection_area_m2", "intersection_area_ha", "geometry",
    ], f"unexpected habitats columns: {list(result.habitats.columns)}"
    assert result.habitats.crs.to_epsg() == 27700, "habitats not in EPSG:27700"
    assert all(c in PRIORITY_HABITAT_CODES for c in result.habitats["habitat_code"]), (
        "a habitats row is not a priority habitat code"
    )
    assert list(result.context.columns) == [
        "uid", "context_codes", "context_habitats", "primsource", "geometry",
    ], f"unexpected context columns: {list(result.context.columns)}"

    print("\nAll broad priority-habitat overlap assertions passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
