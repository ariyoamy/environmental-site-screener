"""Manual real-data smoke check of the SSSI IRZ context analysis.

Run from anywhere; paths are resolved relative to the repository root::

    python scripts/check_sssi_irz_context.py

This runs the implemented pipeline against the real Natural England SSSI Impact
Risk Zones GeoPackage:

1. ``load_sssi_irz`` reads and checks the IRZ layer (any loader warnings, such as
   the invalid-geometry count in the authoritative source, are printed).
2. A small deterministic 100 m x 100 m candidate site is found by stepping
   through a fixed sequence of offsets until it falls inside an IRZ polygon with
   positive area.
3. ``validate_site`` prepares that site.
4. ``calculate_sssi_irz_context`` reports the IRZ context.

It prints a short summary and applies only broad sanity assertions. No specific
URL or code is pinned. Exits non-zero with a clear message if the local source
is absent or if no site with IRZ context can be found.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import geopandas as gpd  # noqa: E402
from shapely.geometry import box  # noqa: E402

from environmental_site_screener.site import validate_site  # noqa: E402
from environmental_site_screener.sssi_irz import (  # noqa: E402
    calculate_sssi_irz_context,
    load_sssi_irz,
)

SOURCE = (
    REPO_ROOT
    / "data"
    / "raw"
    / "sssi_irz"
    / "SSSI_Impact_Risk_Zones_England.gpkg"
)

SITE_SIZE_M = 100
_HALF = SITE_SIZE_M / 2
_START = (425_000.0, 250_000.0)  # dense IRZ area of the English Midlands
_STEP_M = 500
_MAX_RINGS = 40

# Deterministic offsets from the start point: expanding square rings, start first.
CANDIDATE_OFFSETS = [
    (i * _STEP_M, j * _STEP_M)
    for ring in range(_MAX_RINGS)
    for i in range(-ring, ring + 1)
    for j in range(-ring, ring + 1)
    if max(abs(i), abs(j)) == ring
]


def main() -> int:
    if not SOURCE.exists():
        print(f"ERROR: local SSSI IRZ source not found: {SOURCE}", file=sys.stderr)
        return 1

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        irz = load_sssi_irz(SOURCE)
    loader_warnings = [
        str(w.message) for w in caught if issubclass(w.category, UserWarning)
    ]

    # Use the spatial index only to locate a good candidate quickly; the real
    # analysis function is still called on the chosen site.
    sindex = irz.sindex

    site = None
    chosen_offset = None
    result = None
    for dx, dy in CANDIDATE_OFFSETS:
        cx, cy = _START[0] + dx, _START[1] + dy
        candidate_box = box(cx - _HALF, cy - _HALF, cx + _HALF, cy + _HALF)
        hits = list(sindex.query(candidate_box, predicate="intersects"))
        if not hits:
            continue
        if not any(
            irz.geometry.iloc[h].intersection(candidate_box).area > 0 for h in hits
        ):
            continue
        candidate = validate_site(
            gpd.GeoDataFrame(geometry=[candidate_box], crs=irz.crs)
        )
        candidate_result = calculate_sssi_irz_context(candidate, irz)
        if candidate_result.has_irz_context:
            site, chosen_offset, result = candidate, (dx, dy), candidate_result
            break

    if result is None:
        print(
            f"ERROR: no candidate site with IRZ context found within {_MAX_RINGS} "
            f"rings of {_START}",
            file=sys.stderr,
        )
        return 1

    minx, miny, maxx, maxy = site.total_bounds

    print(f"source               : {SOURCE}")
    print(f"source row count     : {len(irz)}")
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
    print(f"has_irz_context      : {result.has_irz_context}")
    print(f"zone_count           : {result.zone_count}")
    print(f"returned irz_code(s) : {list(result.zones['irz_code'])}")
    print("returned advice URL(s):")
    for url in result.advice_urls:
        print(f"    - {url}")

    assert result.has_irz_context is True, "expected the candidate site to have IRZ context"
    assert result.zone_count >= 1, "expected at least one IRZ zone"
    assert len(result.zones) == result.zone_count, "zone_count does not match len(zones)"
    assert list(result.zones.columns) == ["irzurl", "irz_code", "geometry"], (
        f"unexpected zone columns: {list(result.zones.columns)}"
    )
    assert result.zones.crs.to_epsg() == 27700, "zones are not in EPSG:27700"
    assert all(
        isinstance(u, str) and u.startswith("http") for u in result.zones["irzurl"]
    ), "zone irzurl values are not all non-empty http URLs"
    assert len(result.advice_urls) >= 1, "expected at least one advice URL"

    print("\nAll broad IRZ context assertions passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
