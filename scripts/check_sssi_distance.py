"""Manual real-data smoke check of the nearest-SSSI distance analysis.

Run from anywhere; paths are resolved relative to the repository root::

    python scripts/check_sssi_distance.py

This runs the implemented pipeline against the real Natural England SSSI
GeoPackage:

1. ``load_sssi`` reads and validates the SSSI layer.
2. A small deterministic 100 m x 100 m candidate site is constructed. It starts
   at the centre of the SSSI layer bounds and steps through a fixed sequence of
   offsets until ``calculate_sssi_overlap`` reports no positive-area overlap.
3. ``validate_site`` prepares that site.
4. ``calculate_nearest_sssi`` reports the nearest SSSI feature(s) and distance.

It prints a short summary and applies only broad sanity assertions. The exact
nearest distance and SSSI name are not pinned, because the source may change.
Exits non-zero with a clear message if the local SSSI source file is absent or
if no non-overlapping candidate site can be found.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import geopandas as gpd  # noqa: E402
from shapely.geometry import box  # noqa: E402

from environmental_site_screener.distance import calculate_nearest_sssi  # noqa: E402
from environmental_site_screener.overlap import calculate_sssi_overlap  # noqa: E402
from environmental_site_screener.site import validate_site  # noqa: E402
from environmental_site_screener.sssi import load_sssi  # noqa: E402

SOURCE = (
    REPO_ROOT
    / "data"
    / "raw"
    / "sssi"
    / "Sites_of_Special_Scientific_Interest_England.gpkg"
)

SITE_SIZE_M = 100
_HALF = SITE_SIZE_M / 2
_STEP_M = 200
_MAX_RINGS = 60

# Deterministic offsets from the layer centre: expanding square rings, centre first.
CANDIDATE_OFFSETS = [
    (i * _STEP_M, j * _STEP_M)
    for ring in range(_MAX_RINGS)
    for i in range(-ring, ring + 1)
    for j in range(-ring, ring + 1)
    if max(abs(i), abs(j)) == ring
]


def main() -> int:
    if not SOURCE.exists():
        print(f"ERROR: local SSSI source not found: {SOURCE}", file=sys.stderr)
        return 1

    sssi = load_sssi(SOURCE)

    minx, miny, maxx, maxy = sssi.total_bounds
    centre_x = (minx + maxx) / 2
    centre_y = (miny + maxy) / 2

    site = None
    chosen_offset = None
    overlap = None
    for dx, dy in CANDIDATE_OFFSETS:
        cx = centre_x + dx
        cy = centre_y + dy
        candidate = gpd.GeoDataFrame(
            geometry=[box(cx - _HALF, cy - _HALF, cx + _HALF, cy + _HALF)],
            crs=sssi.crs,
        )
        candidate = validate_site(candidate)
        candidate_overlap = calculate_sssi_overlap(candidate, sssi)
        if not candidate_overlap.has_overlap:
            site = candidate
            chosen_offset = (dx, dy)
            overlap = candidate_overlap
            break

    if site is None:
        print(
            "ERROR: no non-overlapping candidate site found within "
            f"{_MAX_RINGS} rings of the layer centre",
            file=sys.stderr,
        )
        return 1

    nearest = calculate_nearest_sssi(site, sssi)

    site_minx, site_miny, site_maxx, site_maxy = site.total_bounds

    print(f"source               : {SOURCE}")
    print(
        f"SSSI layer bounds    : ({minx:.1f}, {miny:.1f}, {maxx:.1f}, {maxy:.1f})"
    )
    print(f"layer centre         : ({centre_x:.1f}, {centre_y:.1f})")
    print(f"candidate offset     : {chosen_offset[0]:.0f} m east, {chosen_offset[1]:.0f} m north")
    print(
        "candidate-site bounds: "
        f"({site_minx:.1f}, {site_miny:.1f}, {site_maxx:.1f}, {site_maxy:.1f})"
    )
    print(f"positive-area overlap : {overlap.has_overlap}")
    print(f"nearest distance     : {nearest.distance_m:,.2f} m")
    print(f"nearest distance     : {nearest.distance_km:,.5f} km")
    print(f"nearest feature count: {nearest.feature_count}")
    print("nearest SSSI feature(s):")
    for row in nearest.features.itertuples(index=False):
        print(f"    {row.ref_code} | {row.name} | measure={row.measure}")

    # Broad sanity checks only - the exact nearest result is not pinned.
    assert overlap.has_overlap is False, (
        "selected candidate site unexpectedly overlaps an SSSI"
    )
    assert nearest.distance_m > 0, "expected a positive nearest distance"
    assert nearest.distance_km == nearest.distance_m / 1000, "km / m mismatch"
    assert nearest.feature_count >= 1, "expected at least one nearest feature"
    assert len(nearest.features) == nearest.feature_count, (
        "feature_count does not match len(features)"
    )
    assert list(nearest.features.columns) == ["ref_code", "name", "measure", "geometry"], (
        f"unexpected nearest feature columns: {list(nearest.features.columns)}"
    )
    assert nearest.features.crs.to_epsg() == 27700, (
        "nearest features are not in EPSG:27700"
    )

    print("\nAll broad nearest-distance assertions passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
