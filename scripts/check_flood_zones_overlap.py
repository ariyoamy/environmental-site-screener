"""Manual real-data smoke check of the Flood Zones overlap analysis.

Run from anywhere; paths are resolved relative to the repository root::

    python scripts/check_flood_zones_overlap.py

This runs the intended site-screening workflow and never loads the whole
national GeoPackage:

1. ``pyogrio.read_info`` reports the national feature count (metadata only).
2. One source feature is read (``max_features=1``) purely to pick a deterministic
   real site - its interior representative point becomes a 100 m x 100 m square.
3. ``validate_site`` prepares that site.
4. ``load_flood_zones(SOURCE, bbox=tuple(site.total_bounds))`` reads only the
   flood polygons whose bounding box intersects the site (native GeoPackage
   spatial index).
5. ``calculate_flood_zone_overlap`` reports the overlap; exact positive-area
   intersection removes any bbox false positives.

Broad sanity assertions only - no specific zone mix, source or numeric area is
pinned. Exits non-zero if the local source is absent.
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
import pyogrio  # noqa: E402
from shapely.geometry import box  # noqa: E402

from environmental_site_screener.flood_zones import (  # noqa: E402
    ZONE_COLUMNS,
    calculate_flood_zone_overlap,
    load_flood_zones,
)
from environmental_site_screener.site import validate_site  # noqa: E402

SOURCE = (
    REPO_ROOT
    / "data"
    / "raw"
    / "flood_zones"
    / "Flood_Map_for_Planning_Flood_Zones.gpkg"
)

SITE_SIZE_M = 100
_HALF = SITE_SIZE_M / 2


def main() -> int:
    if not SOURCE.exists():
        print(f"ERROR: local Flood Zones source not found: {SOURCE}", file=sys.stderr)
        return 1

    t0 = time.perf_counter()
    info = pyogrio.read_info(SOURCE)
    national_count = int(info.get("features") or 0)
    first = pyogrio.read_dataframe(SOURCE, max_features=1)
    pick = first.geometry.iloc[0].representative_point()
    site_box = box(pick.x - _HALF, pick.y - _HALF, pick.x + _HALF, pick.y + _HALF)
    site = validate_site(gpd.GeoDataFrame(geometry=[site_box], crs=first.crs))
    meta_site_seconds = time.perf_counter() - t0

    t1 = time.perf_counter()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        flood_zones = load_flood_zones(SOURCE, bbox=tuple(site.total_bounds))
    bbox_load_seconds = time.perf_counter() - t1
    loader_warnings = [
        str(w.message) for w in caught if issubclass(w.category, UserWarning)
    ]

    t2 = time.perf_counter()
    result = calculate_flood_zone_overlap(site, flood_zones)
    analysis_seconds = time.perf_counter() - t2

    minx, miny, maxx, maxy = site.total_bounds

    print(f"source                    : {SOURCE}")
    print(f"national feature count    : {national_count} (pyogrio.read_info metadata)")
    print(f"features loaded for bbox  : {len(flood_zones)}")
    print(f"metadata + site selection : {meta_site_seconds:.2f} s")
    print(f"bbox load time            : {bbox_load_seconds:.2f} s")
    print(f"analysis time             : {analysis_seconds:.2f} s")
    if loader_warnings:
        print("loader warnings           :")
        for message in loader_warnings:
            print(f"    - {message}")
    else:
        print("loader warnings           : none")
    print(f"candidate-site bounds     : ({minx:.1f}, {miny:.1f}, {maxx:.1f}, {maxy:.1f})")
    print(f"has_flood_zone_overlap    : {result.has_flood_zone_overlap}")
    print(f"zone_count                : {result.zone_count}")
    print("zones                     :")
    for row in result.zones.itertuples(index=False):
        print(
            f"    {row.flood_zone} | {row.intersection_area_ha:.4f} ha | "
            f"{row.site_pct:.2f}% of site | sources={row.flood_sources!r} | "
            f"origins={row.origins!r}"
        )
    print(
        f"affected area             : {result.affected_area_m2:,.1f} m^2 "
        f"({result.affected_area_ha:.4f} ha, {result.affected_pct:.2f}% of site)"
    )
    print(f"distinct flood_sources    : {result.flood_sources}")
    print(f"distinct origins          : {result.origins}")

    per_zone_sum = float(result.zones["intersection_area_m2"].sum())

    assert result.has_flood_zone_overlap is True, "expected flood-zone overlap"
    assert 1 <= result.zone_count <= 2, f"zone_count out of range: {result.zone_count}"
    assert len(result.zones) == result.zone_count, "zone_count / zones mismatch"
    assert result.affected_area_m2 > 0, "expected a positive affected area"
    assert 0 < result.affected_pct <= 100, f"affected_pct out of range: {result.affected_pct}"
    assert abs(result.affected_area_ha - result.affected_area_m2 / 10_000) < 1e-9, "ha != m2/10_000"
    assert result.affected_area_m2 <= per_zone_sum + 1e-6, "headline exceeds sum of per-zone areas"
    assert list(result.zones.columns) == ZONE_COLUMNS, (
        f"unexpected zones columns: {list(result.zones.columns)}"
    )
    assert result.zones.crs.to_epsg() == 27700, "zones not in EPSG:27700"
    assert set(result.zones["flood_zone"]) <= {"FZ2", "FZ3"}, "unexpected flood_zone value"
    assert len(flood_zones) <= national_count, "bbox subset larger than the national source"

    print("\nAll broad flood-zone overlap assertions passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
