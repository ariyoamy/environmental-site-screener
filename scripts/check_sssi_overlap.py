"""Manual end-to-end check of the SSSI overlap analysis against real data.

Run from anywhere; paths are resolved relative to the repository root::

    python scripts/check_sssi_overlap.py

This builds a small demonstration candidate site from the real Natural England
SSSI GeoPackage and runs it through the implemented pipeline:

1. ``load_sssi`` reads and validates the SSSI layer.
2. The first SSSI feature is taken as the target.
3. A representative interior point of that feature is buffered by 50 m to act as
   a demonstration candidate site.
4. ``validate_site`` prepares that site.
5. ``calculate_sssi_overlap`` reports the overlap.

It prints a short summary and applies only broad sanity assertions (it does not
pin the exact overlap percentage). Exits non-zero with a clear message if the
local SSSI source file is absent.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import geopandas as gpd  # noqa: E402

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

BUFFER_METRES = 50


def main() -> int:
    if not SOURCE.exists():
        print(f"ERROR: local SSSI source not found: {SOURCE}", file=sys.stderr)
        return 1

    sssi = load_sssi(SOURCE)

    target = sssi.iloc[0]
    target_ref = target["ref_code"]
    target_name = target["name"]

    demo_site_geom = target.geometry.representative_point().buffer(BUFFER_METRES)
    site = gpd.GeoDataFrame(geometry=[demo_site_geom], crs=sssi.crs)
    site = validate_site(site)

    result = calculate_sssi_overlap(site, sssi)

    print(f"source              : {SOURCE}")
    print(f"target SSSI ref_code : {target_ref}")
    print(f"target SSSI name     : {target_name}")
    print(
        f"demo site           : {BUFFER_METRES} m buffer of the target's "
        "representative point"
    )
    print(
        f"site area           : {result.site_area_m2:,.1f} m^2 "
        f"({result.site_area_m2 / 10_000:,.4f} ha)"
    )
    print(f"has_overlap         : {result.has_overlap}")
    print(f"overlapping SSSIs   : {result.feature_count}")
    print(
        f"affected area       : {result.affected_area_m2:,.1f} m^2 "
        f"({result.affected_area_ha:,.4f} ha)"
    )
    print(f"affected percentage : {result.affected_pct:.2f}%")
    print("overlapping SSSI rows:")
    for row in result.features.itertuples(index=False):
        print(
            f"    {row.ref_code} | {row.name} | "
            f"{row.intersection_area_m2:,.1f} m^2 | "
            f"{row.intersection_area_ha:,.4f} ha"
        )

    # Broad sanity checks only - the exact overlap percentage is not pinned.
    assert result.has_overlap is True, "expected the demo site to overlap an SSSI"
    assert result.feature_count >= 1, "expected at least one overlapping SSSI"
    assert result.affected_area_m2 > 0, "expected a positive affected area"
    assert 0 < result.affected_pct <= 100, (
        f"affected_pct out of range: {result.affected_pct}"
    )
    assert target_ref in set(result.features["ref_code"]), (
        "target SSSI ref_code missing from the overlap features"
    )

    print("\nAll broad end-to-end assertions passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
