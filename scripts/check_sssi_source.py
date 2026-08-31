"""Manual validation of the real local SSSI GeoPackage.

Run from anywhere; paths are resolved relative to the repository root::

    python scripts/check_sssi_source.py

This calls :func:`environmental_site_screener.sssi.load_sssi` (it does not
re-implement any validation) and prints a short summary of the loaded data. For
the source inspected on 31 August 2026 it also asserts a handful of known
characteristics.

Exits non-zero with a clear message if the local source file is absent, if
``load_sssi`` rejects it, or if an assertion fails.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from environmental_site_screener.sssi import load_sssi  # noqa: E402

SOURCE = (
    REPO_ROOT
    / "data"
    / "raw"
    / "sssi"
    / "Sites_of_Special_Scientific_Interest_England.gpkg"
)


def main() -> int:
    if not SOURCE.exists():
        print(f"ERROR: local SSSI source not found: {SOURCE}", file=sys.stderr)
        return 1

    gdf = load_sssi(SOURCE)

    geom_type_counts = gdf.geometry.geom_type.value_counts()
    minx, miny, maxx, maxy = gdf.total_bounds

    print(f"source         : {SOURCE}")
    print(f"row count      : {len(gdf)}")
    print(f"CRS            : {gdf.crs.to_string()} (EPSG:{gdf.crs.to_epsg()})")
    print(f"output columns : {list(gdf.columns)}")
    print("geometry types :")
    for geom_type, count in geom_type_counts.items():
        print(f"    {geom_type}: {count}")
    print(f"total bounds   : ({minx:.1f}, {miny:.1f}, {maxx:.1f}, {maxy:.1f})")

    # Known characteristics of the 31 August 2026 source.
    assert len(gdf) == 4128, f"expected 4128 rows, got {len(gdf)}"
    assert gdf.crs.to_epsg() == 27700, f"expected EPSG:27700, got {gdf.crs.to_epsg()}"
    assert list(gdf.columns) == ["ref_code", "name", "measure", "geometry"], (
        f"unexpected columns: {list(gdf.columns)}"
    )
    assert set(geom_type_counts.index) == {"MultiPolygon"}, (
        f"unexpected geometry types: {set(geom_type_counts.index)}"
    )
    assert gdf["ref_code"].notna().all(), "null ref_code values present"
    assert gdf["ref_code"].is_unique, "duplicate ref_code values present"
    assert gdf["name"].notna().all(), "null name values present"

    print("\nAll 31 August 2026 source assertions passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
