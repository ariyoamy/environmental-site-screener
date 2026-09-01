"""Lightweight real-data QA sweep for the Streamlit app's screening path.

Loads the reusable environmental datasets once, then walks a set of deterministic
candidate sites (the five built-in demo sites plus the QA GeoJSON fixtures),
applies the England product-geography check, and screens the eligible ones. It
prints a compact per-scenario summary. Intended for occasional regression
checks - it deliberately does not reproduce the pytest suite.

    python scripts/check_app_scenarios.py
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

from environmental_site_screener.app_data import (  # noqa: E402
    default_data_sources,
    demo_gallery,
    missing_sources,
    read_geojson_site,
    rectangle_site,
)
from environmental_site_screener.england import (  # noqa: E402
    ELIGIBLE,
    classify_site_england_eligibility,
    load_england_boundary,
)
from environmental_site_screener.screening import (  # noqa: E402
    load_screening_datasets,
    screen_site,
)
from environmental_site_screener.site import validate_site  # noqa: E402

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "sites"

# (label, raw-site provider). A provider returns a candidate GeoDataFrame.
_DEMO_SCENARIOS: list[tuple[str, object]] = [
    (f"demo: {site.label}", site.geodataframe) for site in demo_gallery()
]


def _fixture_provider(name: str):
    return lambda: read_geojson_site((FIXTURES / name).read_bytes())


_FIXTURE_SCENARIOS: list[tuple[str, object]] = [
    ("upload: England - Newbury (WGS84 GeoJSON)", _fixture_provider("valid_wgs84_polygon.geojson")),
    ("upload: MultiPolygon feature", _fixture_provider("valid_multipolygon.geojson")),
    (
        "upload: invalid self-intersection (repaired)",
        _fixture_provider("invalid_self_intersection.geojson"),
    ),
    ("fixture: England - Lincolnshire Wolds", _fixture_provider("no_overlap_site.geojson")),
    ("fixture: Wales - Aberystwyth (OUT OF SCOPE)", _fixture_provider("wales_site.geojson")),
    (
        "fixture: Outside GB - Dublin (OUT OF SCOPE)",
        _fixture_provider("offshore_or_outside_gb_site.geojson"),
    ),
    (
        "fixture: England/Wales border crossing (OUT OF SCOPE)",
        _fixture_provider("border_crossing_site.geojson"),
    ),
]

# "Define area" convenience input: the same rectangle whether typed or drawn.
_DEFINE_AREA_SCENARIOS: list[tuple[str, object]] = [
    (
        "define-area: Cambridge rectangle (0.100,52.200,0.109,52.206)",
        lambda: rectangle_site(0.10000, 52.20000, 0.10900, 52.20600),
    ),
]

SCENARIOS = _DEMO_SCENARIOS + _FIXTURE_SCENARIOS + _DEFINE_AREA_SCENARIOS


def main() -> int:
    sources = default_data_sources(REPO_ROOT)
    absent = missing_sources(sources)
    if absent:
        print("Missing local source data:")
        for path in absent:
            print(f"  - {path}")
        return 1

    england = load_england_boundary(sources["revised_coverage_path"])
    print(f"England boundary: {len(england)} row, EPSG:{england.crs.to_epsg()}")

    print("Loading reusable datasets (once)…")
    t0 = time.perf_counter()
    with warnings.catch_warnings(record=True) as load_warnings:
        warnings.simplefilter("always")
        datasets = load_screening_datasets(
            **{key: str(path) for key, path in sources.items()}
        )
    load_seconds = time.perf_counter() - t0
    print(f"  loaded in {load_seconds:.1f} s")
    for warning in load_warnings:
        if issubclass(warning.category, UserWarning):
            print(f"  load warning: {warning.message}")
    print()

    for label, provider in SCENARIOS:
        print("=" * 78)
        print(label)
        try:
            raw = provider()
        except ValueError as exc:
            print(f"  read FAILED: {exc}")
            continue

        try:
            with warnings.catch_warnings(record=True) as validate_warnings:
                warnings.simplefilter("always")
                validated = validate_site(raw)
        except (TypeError, ValueError) as exc:
            print(f"  validate_site REJECTED: {exc}")
            continue
        for warning in validate_warnings:
            if issubclass(warning.category, UserWarning):
                print(f"  validate warning: {warning.message}")
        bounds = tuple(round(float(v), 1) for v in validated.total_bounds)
        area_ha = float(validated.geometry.iloc[0].area) / 10_000
        print(
            f"  validated: 1 {validated.geometry.iloc[0].geom_type}, "
            f"EPSG:{validated.crs.to_epsg()}, {area_ha:,.1f} ha, bounds {bounds}"
        )

        eligibility = classify_site_england_eligibility(validated, england)
        if eligibility != ELIGIBLE:
            print(f"  England eligibility: {eligibility.upper()} - not screened")
            continue
        print("  England eligibility: eligible")

        try:
            with warnings.catch_warnings(record=True) as screen_warnings:
                warnings.simplefilter("always")
                started = time.perf_counter()
                result = screen_site(validated, datasets)
                seconds = time.perf_counter() - started
        except Exception as exc:  # noqa: BLE001 - QA visibility
            print(f"  screen_site RAISED {type(exc).__name__}: {exc}")
            continue

        print(f"  screened in {seconds:.2f} s")
        for warning in screen_warnings:
            if issubclass(warning.category, UserWarning):
                print(f"  screen warning: {warning.message}")

        summary = result.summary
        print("  summary:")
        for _, row in summary.iterrows():
            area = row["affected_area_ha"]
            pct = row["affected_pct"]
            dist = row["nearest_distance_m"]
            bits = [f"has_result={bool(row['has_result'])}", f"type={row['result_type']}"]
            if area == area:  # not NaN
                bits.append(f"area_ha={area:.4f}")
            if pct == pct:
                bits.append(f"pct={pct:.2f}")
            if dist == dist:
                bits.append(f"nearest_m={dist:.1f}")
            print(f"    {row['theme']:24s} " + "  ".join(bits))
        if result.nearest_sssi is not None:
            names = list(result.nearest_sssi.features["name"])
            print(f"  nearest SSSI feature(s): {names}")

    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
