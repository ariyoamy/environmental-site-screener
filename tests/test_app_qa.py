"""Product-level QA for the Environmental Site Screener app.

Three groups:

* **input path** - the real route an uploaded file takes,
  ``file bytes -> read_geojson_site() -> validate_site()``, driven by the
  hand-written GeoJSON fixtures in ``tests/fixtures/sites/``;
* **result profiles** - every card / legend / layer-control / detail combination
  built from synthetic :class:`ScreeningResult` objects (no datasets loaded);
* **Streamlit interaction** - ``streamlit.testing.v1.AppTest`` state transitions
  (skipped when the local raw datasets are absent, because ``app.main`` stops
  early in that case).

Low-level dataset behaviour is covered by the ``test_<dataset>.py`` modules and
is not repeated here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from environmental_site_screener.app_data import (
    carto_tile_layer,
    default_data_sources,
    demo_gallery,
    demo_site,
    demo_site_by_key,
    friendly_repair_notice,
    friendly_site_error,
    missing_sources,
    read_geojson_site,
    rect_bounds_from_drawing,
    rectangle_site,
)
from environmental_site_screener.app_format import (
    THEME_KEYS,
    build_overlap_summary,
    build_theme_cards,
    build_theme_detail,
)
from environmental_site_screener.app_map import (
    available_layer_control_keys,
    available_layer_controls,
    build_map_layers,
    legend_entries,
)
from environmental_site_screener.england import (
    BOUNDARY_TOLERANCE_M2,
    CROSSES,
    ELIGIBLE,
    OUTSIDE,
    classify_site_england_eligibility,
    load_england_boundary,
)
from environmental_site_screener.site import validate_site
from synthetic_results import mk_aw, mk_fz, mk_irz, mk_nearest, mk_phi, mk_result, mk_sssi

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "sites"

# Verdict / score wording the product must never emit (see test_app_helpers).
_BANNED = re.compile(
    r"(risk\s+(score|level|rating|category|band)|(low|high|moderate)\s+risk|"
    r"traffic[\s-]*light|pass/fail|\bpass\b|\bfail\b|\bsafe\b|\bunsafe\b|"
    r"\bscore\b|\brating\b|suitab\w*|\bgrade\b|permitted|planning permission)",
    re.IGNORECASE,
)


# Marks the opening <div> of a rendered result card (not the CSS rule).
_CARD_MARK = '<div class="ess-card '


def _count_cards(app_test) -> int:
    return sum(1 for m in app_test.markdown if _CARD_MARK in m.value)


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _upload(name: str):
    """Full app input path for a fixture: bytes -> read -> validate."""
    return validate_site(read_geojson_site(_fixture(name)))


# --------------------------------------------------------------------------- #
# Part C - candidate-site upload path
# --------------------------------------------------------------------------- #


def test_valid_wgs84_polygon_is_accepted_and_reprojected():
    validated = _upload("valid_wgs84_polygon.geojson")

    assert len(validated) == 1
    assert validated.crs.to_epsg() == 27700
    assert validated.geometry.iloc[0].geom_type == "Polygon"
    assert validated.geometry.iloc[0].area > 0


def test_named_bng_crs_is_honoured_without_reprojection():
    raw = read_geojson_site(_fixture("valid_bng_polygon.geojson"))
    assert raw.crs.to_epsg() == 27700

    validated = validate_site(raw)
    assert validated.crs.to_epsg() == 27700
    # already British National Grid: bounds unchanged
    assert tuple(round(v) for v in validated.total_bounds) == (
        566000,
        196000,
        566200,
        196200,
    )


def test_valid_multipolygon_single_feature_is_accepted():
    validated = _upload("valid_multipolygon.geojson")

    assert len(validated) == 1
    assert validated.geometry.iloc[0].geom_type == "MultiPolygon"
    assert validated.crs.to_epsg() == 27700


def test_malformed_geojson_gives_useful_message_not_traceback():
    with pytest.raises(ValueError) as exc_info:
        read_geojson_site(_fixture("malformed.geojson"))

    message = str(exc_info.value)
    assert "could not be parsed as JSON" in message
    assert "Traceback" not in message


def test_multiple_features_rejected_clearly():
    raw = read_geojson_site(_fixture("multiple_features.geojson"))
    assert len(raw) == 2  # reader passes them through untouched

    with pytest.raises(ValueError, match="exactly one site feature"):
        validate_site(raw)


def test_non_polygon_rejected_clearly():
    raw = read_geojson_site(_fixture("non_polygon.geojson"))

    with pytest.raises(ValueError, match="Polygon or MultiPolygon"):
        validate_site(raw)


def test_empty_geometry_rejected_clearly():
    raw = read_geojson_site(_fixture("empty_geometry.geojson"))

    with pytest.raises(ValueError, match="missing or empty"):
        validate_site(raw)


def test_self_intersecting_site_is_repaired_with_a_warning():
    raw = read_geojson_site(_fixture("invalid_self_intersection.geojson"))

    with pytest.warns(UserWarning, match="invalid"):
        validated = validate_site(raw)

    geom = validated.geometry.iloc[0]
    assert geom.is_valid and not geom.is_empty and geom.area > 0
    assert geom.geom_type in ("Polygon", "MultiPolygon")


def test_ambiguous_crs_name_falls_back_to_wgs84_and_validates():
    # CRS84 carries no EPSG code for the reader to parse; it is lon/lat WGS84,
    # so the EPSG:4326 fallback is correct and the site still validates.
    raw = read_geojson_site(_fixture("no_crs_or_ambiguous_crs.geojson"))
    assert raw.crs.to_epsg() == 4326

    validated = validate_site(raw)
    assert validated.crs.to_epsg() == 27700


def test_feature_properties_survive_validation():
    raw = read_geojson_site(_fixture("valid_wgs84_polygon.geojson"))
    assert list(raw["site_ref"]) == ["QA-WGS84"]

    validated = validate_site(raw)
    assert list(validated["site_ref"]) == ["QA-WGS84"]
    assert "note" in validated.columns


def test_upload_path_does_not_mutate_the_read_object():
    raw = read_geojson_site(_fixture("valid_wgs84_polygon.geojson"))
    before_wkt = raw.geometry.iloc[0].wkt
    before_epsg = raw.crs.to_epsg()

    validate_site(raw)

    assert raw.geometry.iloc[0].wkt == before_wkt
    assert raw.crs.to_epsg() == before_epsg == 4326


def test_very_small_valid_site_still_validates():
    # ~1 m square in British National Grid
    tiny = (
        '{"type":"Feature","properties":{},'
        '"geometry":{"type":"Polygon","coordinates":'
        "[[[566000,196000],[566000,196001],[566001,196001],[566001,196000],[566000,196000]]]}}"
    )
    raw = read_geojson_site(tiny.encode())
    raw = raw.set_crs("EPSG:27700", allow_override=True)

    validated = validate_site(raw)
    assert validated.geometry.iloc[0].area == pytest.approx(1.0, abs=0.01)


def test_moderately_large_valid_site_is_not_arbitrarily_rejected():
    # ~10 km square in British National Grid (10,000 ha) - large, but a legitimate
    # infrastructure-scale search area; the app must not impose a size cap.
    big = (
        '{"type":"Feature","properties":{},'
        '"geometry":{"type":"Polygon","coordinates":'
        "[[[400000,300000],[400000,310000],[410000,310000],[410000,300000],[400000,300000]]]}}"
    )
    raw = read_geojson_site(big.encode()).set_crs("EPSG:27700", allow_override=True)

    validated = validate_site(raw)
    assert validated.geometry.iloc[0].area == pytest.approx(1e8, rel=1e-6)


# --------------------------------------------------------------------------- #
# Part F - result-profile sweep (synthetic, no datasets)
# --------------------------------------------------------------------------- #

_PROFILES = {
    "everything overlaps": mk_result(
        sssi=mk_sssi(has_overlap=True),
        phi=mk_phi(has=True),
        aw=mk_aw(has=True),
        fz=mk_fz(has=True),
    ),
    "no sssi overlap, nearest only": mk_result(
        sssi=mk_sssi(has_overlap=False), nearest=mk_nearest(distance_m=740.0)
    ),
    "irz absent": mk_result(irz=mk_irz(zone_count=0)),
    "no priority habitat": mk_result(phi=mk_phi(has=False)),
    "context habitat only": mk_result(phi=mk_phi(has=False, with_context=True)),
    "no ancient woodland": mk_result(aw=mk_aw(has=False)),
    "flood zone 2 only": mk_result(fz=mk_fz(has=True, zones_present=("FZ2",))),
    "flood zone 3 only": mk_result(fz=mk_fz(has=True, zones_present=("FZ3",))),
    "no flood zones": mk_result(fz=mk_fz(has=False)),
    "sparse - only irz + nearest": mk_result(
        sssi=mk_sssi(has_overlap=False),
        nearest=mk_nearest(distance_m=1423.0),
        phi=mk_phi(has=False),
        aw=mk_aw(has=False),
        fz=mk_fz(has=False),
    ),
}


@pytest.mark.parametrize("label", list(_PROFILES))
def test_result_profile_renders_sensible_helpers(label):
    result = _PROFILES[label]

    cards = build_theme_cards(result)
    assert len(cards) == 5

    control_keys = set(available_layer_control_keys(result))
    legend_labels = {lbl for lbl, _ in legend_entries(result)}
    layer_ids = {layer.id for layer in build_map_layers(result)}

    # absent themes must not create map layers, legend rows or layer toggles
    if not result.priority_habitats.has_priority_overlap:
        assert "priority_habitats" not in control_keys
        assert "phi" not in layer_ids
        assert "Priority habitat" not in legend_labels
    if not result.ancient_woodland.has_overlap:
        assert "ancient_woodland" not in control_keys
        assert "aw" not in layer_ids
    if not result.sssi_irz.has_irz_context:
        assert "irz" not in control_keys
        assert "irz" not in layer_ids
    if not result.flood_zones.has_flood_zone_overlap:
        assert not {"flood_zone_2", "flood_zone_3"} & control_keys
        assert not {"fz-fz2", "fz-fz3"} & layer_ids

    # candidate site is always present and never a toggle
    assert "site" in layer_ids
    assert "site" not in control_keys

    # nearest SSSI is distinct from an intersecting SSSI
    if not result.sssi.has_overlap and result.nearest_sssi is not None:
        assert "sssi-nearest" in layer_ids
        assert "sssi" not in layer_ids
        assert cards[0].secondary_metric.startswith("Nearest:")
        assert cards[0].primary_metric is None

    # IRZ stays contextual, never a percentage / severity
    irz_card = cards[1]
    assert irz_card.tone == "context"
    assert irz_card.primary_metric is None

    # zero overlap reads as "no overlap", not blank
    for card in cards:
        assert card.state_label.strip()
        if card.tone == "none":
            assert "No " in card.state_label

    # no Flood Zone 1 anywhere
    blob = " ".join(legend_labels | control_keys | layer_ids)
    assert "Flood Zone 1" not in blob and "fz-fz1" not in blob

    # every detail tab builds and carries no verdict language
    texts: list[str] = []
    for card in cards:
        texts += [
            card.theme,
            card.state_label,
            card.primary_metric or "",
            card.secondary_metric or "",
            card.context_line or "",
        ]
    for key in THEME_KEYS:
        detail = build_theme_detail(result, key)
        assert detail.headline.strip()
        assert detail.what_it_means.strip()
        texts += [detail.headline, detail.what_it_means, detail.note or ""]
        texts += list(detail.metrics)
        for table in detail.tables:
            for row in table.rows:
                texts += [str(v) for v in row.values()]
    offenders = sorted({m.group(0).lower() for t in texts for m in [_BANNED.search(t)] if m})
    assert not offenders, f"{label}: verdict language leaked: {offenders}"


# --------------------------------------------------------------------------- #
# Part I regression - layer-visibility reset helper (no Streamlit context)
# --------------------------------------------------------------------------- #


def _import_app():
    import sys

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    import app  # noqa: PLC0415 - deliberately lazy; app.py only runs on __main__

    return app


def test_clear_layer_visibility_removes_only_layer_keys():
    app = _import_app()
    state = {
        "lyr_sssi": False,
        "lyr_priority_habitats": False,
        "lyr_show_all": True,
        "result": "keep me",
        "elapsed": 2.0,
        "result_site_bounds": (1, 2, 3, 4),
    }

    app._clear_layer_visibility(state, ["sssi", "priority_habitats", "ancient_woodland"])

    assert "lyr_sssi" not in state
    assert "lyr_priority_habitats" not in state
    assert state["lyr_show_all"] is True  # not a control key -> untouched
    assert state["result"] == "keep me"
    assert state["elapsed"] == 2.0
    assert state["result_site_bounds"] == (1, 2, 3, 4)


def test_bounds_key_is_a_stable_rounded_fingerprint():
    app = _import_app()
    key = app._bounds_key(validate_site(demo_site()))
    assert key == app._bounds_key(validate_site(demo_site()))
    assert key == (565147.0, 195157.0, 565347.0, 195357.0)


# --------------------------------------------------------------------------- #
# Part D - Streamlit interaction (needs the local raw datasets present)
# --------------------------------------------------------------------------- #

_DATA_MISSING = bool(missing_sources(default_data_sources(REPO_ROOT)))
_APP = str(REPO_ROOT / "app.py")
pytestmark_apptest = pytest.mark.skipif(
    _DATA_MISSING, reason="local raw datasets absent; app.main() stops before the workspace"
)


def _demo_bounds_key():
    validated = validate_site(demo_site())
    return tuple(round(float(v), 3) for v in validated.total_bounds)


def _app_test():
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(_APP)


def _inject_demo_result(at, result=None):
    at.session_state["result"] = result if result is not None else mk_result()
    at.session_state["result_site_bounds"] = _demo_bounds_key()
    at.session_state["elapsed"] = 1.23
    at.session_state["screen_warnings"] = []


@pytestmark_apptest
def test_app_opens_with_demo_ready_and_no_errors():
    at = _app_test()
    at.run(timeout=120)

    assert not list(at.exception)
    assert not at.error
    assert at.radio[0].value == "Demo site"
    assert at.button[0].label == "Screen site"
    assert at.button[0].disabled is False


@pytestmark_apptest
def test_injected_demo_result_shows_five_cards_five_tabs_and_layer_controls():
    at = _app_test()
    _inject_demo_result(at)
    at.run(timeout=120)

    assert not list(at.exception)
    assert len(at.tabs) == 5
    assert _count_cards(at) == 5
    assert {c.key for c in at.checkbox} == {
        "lyr_sssi",
        "lyr_irz",
        "lyr_priority_habitats",
        "lyr_ancient_woodland",
        "lyr_flood_zone_2",
        "lyr_flood_zone_3",
    }
    assert all(at.checkbox(key=k).value for k in [c.key for c in at.checkbox])


@pytestmark_apptest
def test_layer_toggle_does_not_re_screen_or_drop_the_result():
    at = _app_test()
    result = mk_result()
    _inject_demo_result(at, result)
    at.run(timeout=120)
    result_id = id(at.session_state["result"])

    at.checkbox(key="lyr_flood_zone_2").set_value(False)
    at.run(timeout=60)

    assert not list(at.exception)
    assert id(at.session_state["result"]) == result_id  # same object, no re-screen
    assert at.session_state["elapsed"] == 1.23  # unchanged
    assert at.session_state["lyr_flood_zone_2"] is False


@pytestmark_apptest
def test_site_only_then_show_all_buttons():
    at = _app_test()
    _inject_demo_result(at)
    at.run(timeout=120)
    keys = [c.key for c in at.checkbox]

    at.button(key="lyr_site_only").click()
    at.run(timeout=60)
    assert all(at.checkbox(key=k).value is False for k in keys)

    at.button(key="lyr_show_all").click()
    at.run(timeout=60)
    assert all(at.checkbox(key=k).value is True for k in keys)
    assert not list(at.exception)


@pytestmark_apptest
def test_switching_to_upload_with_no_file_hides_the_stale_demo_result():
    at = _app_test()
    _inject_demo_result(at)
    at.run(timeout=120)
    assert len(at.tabs) == 5  # result visible for the demo

    at.radio[0].set_value("Upload GeoJSON")
    at.run(timeout=60)

    assert not list(at.exception)
    assert len(at.tabs) == 0  # Explore-results tabs gone
    assert _count_cards(at) == 0
    assert at.button[0].disabled is True  # Screen site disabled, no boundary
    assert any("no longer applies" in i.value.lower() for i in at.info)


@pytestmark_apptest
def test_switching_upload_back_to_demo_restores_that_sites_result():
    at = _app_test()
    _inject_demo_result(at)
    at.run(timeout=120)

    at.radio[0].set_value("Upload GeoJSON")
    at.run(timeout=60)
    assert len(at.tabs) == 0

    at.radio[0].set_value("Demo site")
    at.run(timeout=60)
    # same boundary as the stored result -> it is legitimately shown again
    assert len(at.tabs) == 5
    assert not list(at.exception)


@pytestmark_apptest
def test_changing_to_a_different_valid_site_marks_the_old_result_stale():
    at = _app_test()
    _inject_demo_result(at)
    # pretend a screening happened for a *different* boundary
    at.session_state["result_site_bounds"] = (0.0, 0.0, 1.0, 1.0)
    at.run(timeout=120)

    assert not list(at.exception)
    assert len(at.tabs) == 0  # stale result not presented for the demo boundary
    assert any("screen the site again" in i.value.lower() for i in at.info)


@pytestmark_apptest
def test_real_demo_screening_produces_five_cards_and_tabs():
    at = _app_test()
    at.run(timeout=180)
    at.button[0].click()
    at.run(timeout=600)

    assert not list(at.exception)
    assert not at.error
    assert len(at.tabs) == 5
    assert _count_cards(at) == 5
    assert any("Screened in" in c.value for c in at.caption)
    assert {c.key for c in at.checkbox} == {
        "lyr_sssi",
        "lyr_irz",
        "lyr_priority_habitats",
        "lyr_ancient_woodland",
        "lyr_flood_zone_2",
        "lyr_flood_zone_3",
    }


@pytestmark_apptest
def test_screening_a_different_site_resets_hidden_layers():
    at = _app_test()
    at.run(timeout=180)
    # a previous screening for a different boundary, with two layers hidden
    at.session_state["result_site_bounds"] = (1.0, 2.0, 3.0, 4.0)
    at.session_state["lyr_priority_habitats"] = False
    at.session_state["lyr_flood_zone_3"] = False

    at.button[0].click()  # screen the (different) demo site
    at.run(timeout=600)

    assert not list(at.exception)
    keys = [c.key for c in at.checkbox]
    assert keys, "layer toggles should be present after screening"
    assert all(at.checkbox(key=k).value is True for k in keys)


@pytestmark_apptest
def test_screening_the_same_site_twice_keeps_state_consistent():
    at = _app_test()
    at.run(timeout=180)
    at.button[0].click()
    at.run(timeout=600)
    first_bounds = at.session_state["result_site_bounds"]

    at.button[0].click()  # screen the identical demo site again
    at.run(timeout=600)

    assert not list(at.exception)
    assert at.session_state["result_site_bounds"] == first_bounds
    assert len(at.tabs) == 5
    assert _count_cards(at) == 5  # no duplicated cards


# --------------------------------------------------------------------------- #
# England product-geography guard
# --------------------------------------------------------------------------- #

_BOUNDARY_PATH = default_data_sources(REPO_ROOT)["revised_coverage_path"]
_BOUNDARY_MISSING = not _BOUNDARY_PATH.exists()
pytestmark_boundary = pytest.mark.skipif(
    _BOUNDARY_MISSING, reason="OS Boundary-Line ceremonial-counties source absent"
)


@pytest.fixture(scope="module")
def england_boundary():
    if _BOUNDARY_MISSING:
        pytest.skip("OS Boundary-Line ceremonial-counties source absent")
    return load_england_boundary(_BOUNDARY_PATH)


@pytest.fixture(scope="module")
def screening_datasets():
    if _DATA_MISSING:
        pytest.skip("local raw datasets absent")
    from environmental_site_screener.screening import load_screening_datasets

    sources = default_data_sources(REPO_ROOT)
    return load_screening_datasets(**{k: str(p) for k, p in sources.items()})


@pytestmark_boundary
def test_england_boundary_is_one_valid_bng_polygon(england_boundary):
    assert len(england_boundary) == 1
    assert england_boundary.crs.to_epsg() == 27700
    geom = england_boundary.geometry.iloc[0]
    assert geom.is_valid and not geom.is_empty
    assert geom.geom_type in ("Polygon", "MultiPolygon")


@pytestmark_boundary
@pytest.mark.parametrize(
    "fixture",
    [
        "valid_wgs84_polygon.geojson",
        "valid_bng_polygon.geojson",
        "alternate_england_site.geojson",
        "no_overlap_site.geojson",
        "valid_multipolygon.geojson",
    ],
)
def test_england_fixtures_are_eligible(england_boundary, fixture):
    validated = validate_site(read_geojson_site(_fixture(fixture)))
    assert classify_site_england_eligibility(validated, england_boundary) == ELIGIBLE


@pytestmark_boundary
def test_wales_site_is_outside_england(england_boundary):
    validated = validate_site(read_geojson_site(_fixture("wales_site.geojson")))
    assert classify_site_england_eligibility(validated, england_boundary) == OUTSIDE


@pytestmark_boundary
def test_outside_gb_site_is_outside_england(england_boundary):
    validated = validate_site(
        read_geojson_site(_fixture("offshore_or_outside_gb_site.geojson"))
    )
    assert classify_site_england_eligibility(validated, england_boundary) == OUTSIDE


@pytestmark_boundary
def test_border_crossing_site_is_classified_as_crossing(england_boundary):
    validated = validate_site(read_geojson_site(_fixture("border_crossing_site.geojson")))
    assert classify_site_england_eligibility(validated, england_boundary) == CROSSES


@pytestmark_boundary
def test_all_demo_sites_are_england_eligible(england_boundary):
    for site in demo_gallery():
        validated = validate_site(site.geodataframe())
        assert (
            classify_site_england_eligibility(validated, england_boundary) == ELIGIBLE
        ), site.key


@pytestmark_boundary
def test_classify_requires_bng(england_boundary):
    raw = read_geojson_site(_fixture("valid_wgs84_polygon.geojson"))  # EPSG:4326
    with pytest.raises(ValueError, match="EPSG:27700"):
        classify_site_england_eligibility(raw, england_boundary)


def test_boundary_tolerance_is_a_tiny_numerical_value_not_a_buffer():
    # a square-metre-scale tolerance cannot meaningfully grow England
    assert 0 < BOUNDARY_TOLERANCE_M2 <= 1.0


@pytestmark_apptest
def test_define_area_over_ireland_blocks_screening_and_hides_stale_result():
    at = _app_test()
    _inject_demo_result(at)
    at.run(timeout=120)
    assert len(at.tabs) == 5  # demo result visible to start

    at.radio[0].set_value("Define area")
    at.run(timeout=60)
    at.number_input(key="draw_w").set_value(-6.30)
    at.number_input(key="draw_e").set_value(-6.20)
    at.number_input(key="draw_s").set_value(53.30)
    at.number_input(key="draw_n").set_value(53.40)
    at.run(timeout=60)

    assert not list(at.exception)
    assert _screen_button(at).disabled is True  # Screen site disabled
    assert _count_cards(at) == 0
    assert len(at.tabs) == 0
    assert any("England only" in e.value for e in at.error)


@pytestmark_apptest
def test_define_area_with_default_england_rectangle_enables_screening():
    at = _app_test()
    at.run(timeout=120)

    at.radio[0].set_value("Define area")
    at.run(timeout=60)

    assert not list(at.exception)
    assert not at.error
    assert _screen_button(at).disabled is False  # defaults are a small Cambridge site


@pytestmark_apptest
def test_border_crossing_rectangle_is_blocked():
    at = _app_test()
    at.run(timeout=120)

    at.radio[0].set_value("Define area")
    at.run(timeout=60)
    # straddles the Herefordshire / Powys boundary
    at.number_input(key="draw_w").set_value(-3.117)
    at.number_input(key="draw_e").set_value(-3.073)
    at.number_input(key="draw_s").set_value(52.036)
    at.number_input(key="draw_n").set_value(52.061)
    at.run(timeout=60)

    assert not list(at.exception)
    assert _screen_button(at).disabled is True
    assert any("outside" in e.value.lower() for e in at.error)


@pytestmark_apptest
def test_switching_demo_example_marks_the_old_result_stale():
    at = _app_test()
    _inject_demo_result(at)  # result stored for the Suffolk demo bounds
    at.run(timeout=120)
    assert len(at.tabs) == 5

    at.selectbox(key="demo_choice").set_value("Multi-part site - Newbury")
    at.run(timeout=60)

    assert not list(at.exception)
    assert len(at.tabs) == 0  # different boundary -> stale result hidden
    assert _count_cards(at) == 0
    assert any("screen the site again" in i.value.lower() for i in at.info)


def _screen_button(at):
    return next(b for b in at.button if b.label == "Screen site")


@pytestmark_apptest
def test_define_area_draw_mode_renders_and_defaults_to_cambridge():
    at = _app_test()
    at.run(timeout=120)

    at.radio[0].set_value("Define area")
    at.run(timeout=60)

    assert not list(at.exception)
    # the Draw/Enter toggle is present and the drawing surface did not crash AppTest
    assert any(r.label == "Define area mode" for r in at.radio)
    assert at.radio(key="draw_mode").value == "Draw on map"
    # the compact map offers the larger view
    assert any(b.key == "draw_expand_btn" for b in at.button)
    # shared coordinate state seeded to the Cambridge extent, screening enabled
    assert at.number_input(key="draw_w").value == 0.10000
    assert at.number_input(key="draw_n").value == 52.20600
    assert _screen_button(at).disabled is False


@pytestmark_apptest
def test_define_area_large_view_opens_collapses_and_shares_bounds():
    at = _app_test()
    at.run(timeout=120)
    at.radio[0].set_value("Define area")
    at.run(timeout=60)

    # edit a coordinate in the compact fine-tune inputs first
    at.number_input(key="draw_e").set_value(0.11500)
    at.run(timeout=60)

    at.button(key="draw_expand_btn").click()
    at.run(timeout=60)
    assert not list(at.exception)
    assert at.session_state["draw_expanded"] is True
    # the large view replaces the result map and offers a collapse control
    assert any(b.key == "draw_collapse_btn" for b in at.button)
    assert not any(b.key == "draw_expand_btn" for b in at.button)
    assert _screen_button(at).disabled is False  # screening still available
    # the large view reads the same rectangle state as the compact map
    assert any("E 0.11500" in c.value for c in at.caption)

    at.button(key="draw_collapse_btn").click()
    at.run(timeout=60)

    assert not list(at.exception)
    assert at.session_state["draw_expanded"] is False
    # back in compact mode the shared rectangle is unchanged
    assert at.number_input(key="draw_e").value == 0.11500
    assert any(b.key == "draw_expand_btn" for b in at.button)


@pytestmark_apptest
def test_switching_away_from_define_area_closes_the_large_view():
    at = _app_test()
    at.run(timeout=120)
    at.radio[0].set_value("Define area")
    at.run(timeout=60)
    at.button(key="draw_expand_btn").click()
    at.run(timeout=60)
    assert at.session_state["draw_expanded"] is True

    at.radio[0].set_value("Demo site")
    at.run(timeout=60)
    assert not list(at.exception)
    assert at.session_state["draw_expanded"] is False


@pytestmark_apptest
def test_define_area_enter_coordinates_mode_still_works():
    at = _app_test()
    at.run(timeout=120)
    at.radio[0].set_value("Define area")
    at.run(timeout=60)
    at.radio(key="draw_mode").set_value("Enter coordinates")
    at.run(timeout=60)

    at.number_input(key="draw_e").set_value(0.11500)
    at.run(timeout=60)

    assert not list(at.exception)
    assert at.button[0].disabled is False  # still an England rectangle


@pytestmark_apptest
def test_large_london_demo_warns_but_stays_screenable():
    at = _app_test()
    at.run(timeout=120)
    at.selectbox(key="demo_choice").set_value("Large-area screening - London")
    at.run(timeout=60)

    assert not list(at.exception)
    assert at.button[0].disabled is False  # advisory only, never blocks
    assert any("may take longer" in i.value.lower() for i in at.info)


# --------------------------------------------------------------------------- #
# Demo gallery
# --------------------------------------------------------------------------- #


def test_demo_gallery_has_exactly_five_sites():
    assert len(demo_gallery()) == 5


def test_demo_gallery_labels_and_keys_are_unique():
    gallery = demo_gallery()
    assert len({s.label for s in gallery}) == 5
    assert len({s.key for s in gallery}) == 5


def test_every_demo_site_validates_to_a_single_bng_polygon():
    for site in demo_gallery():
        validated = validate_site(site.geodataframe())
        assert len(validated) == 1
        assert validated.crs.to_epsg() == 27700
        assert validated.geometry.iloc[0].area > 0


def test_every_demo_site_is_labelled_as_a_fictional_demo():
    for site in demo_gallery():
        name = site.geodataframe()["site_name"].iloc[0].lower()
        assert "demo" in name and "not a real proposed development" in name


def test_multi_part_demo_is_genuinely_a_multipolygon():
    site = demo_site_by_key("newbury_multipart")
    assert site.geometry.geom_type == "MultiPolygon"
    validated = validate_site(site.geodataframe())
    assert validated.geometry.iloc[0].geom_type == "MultiPolygon"
    assert len(validated.geometry.iloc[0].geoms) == 2


def test_demo_site_by_key_rejects_unknown_key():
    with pytest.raises(KeyError):
        demo_site_by_key("not_a_demo")


def test_first_demo_site_matches_the_standalone_demo_site_helper():
    gallery_first = validate_site(demo_gallery()[0].geodataframe())
    standalone = validate_site(demo_site())
    assert tuple(round(v, 3) for v in gallery_first.total_bounds) == tuple(
        round(v, 3) for v in standalone.total_bounds
    )


def test_cambridge_demo_uses_the_requested_coordinates():
    west, south, east, north = demo_site_by_key("cambridge_urban").geometry.bounds
    assert (round(west, 5), round(south, 5), round(east, 5), round(north, 5)) == (
        0.10000,
        52.20000,
        0.10900,
        52.20600,
    )


def test_london_demo_uses_the_requested_coordinates_and_is_large():
    london = demo_site_by_key("london_large")
    west, south, east, north = london.geometry.bounds
    assert (round(west, 5), round(south, 5), round(east, 5), round(north, 5)) == (
        -0.23600,
        51.44000,
        -0.01900,
        51.57500,
    )
    # far larger than a normal site - the label/blurb must make that clear
    area_ha = validate_site(london.geodataframe()).geometry.iloc[0].area / 10_000
    assert area_ha > 15_000
    assert "large" in london.label.lower()
    assert "not a real proposal" in london.blurb.lower()


@pytestmark_apptest
def test_demo_sites_produce_several_distinct_screening_profiles(screening_datasets):
    from environmental_site_screener.screening import screen_site

    profiles = set()
    for site in demo_gallery():
        result = screen_site(validate_site(site.geodataframe()), screening_datasets)
        profiles.add(
            (
                result.sssi.has_overlap,
                result.nearest_sssi is not None,
                result.priority_habitats.has_priority_overlap,
                result.ancient_woodland.has_overlap,
                result.flood_zones.has_flood_zone_overlap,
            )
        )
    # not five lookalike rectangles: at least three materially different outcomes
    assert len(profiles) >= 3


# --------------------------------------------------------------------------- #
# "Define area" convenience input
# --------------------------------------------------------------------------- #


def test_rectangle_site_builds_one_polygon_with_a_crs():
    gdf = rectangle_site(0.10, 52.20, 0.11, 52.21)
    assert len(gdf) == 1
    assert gdf.crs.to_epsg() == 4326
    assert gdf.geometry.iloc[0].geom_type == "Polygon"


def test_rectangle_site_flows_through_validation():
    validated = validate_site(rectangle_site(0.10, 52.20, 0.11, 52.21))
    assert validated.crs.to_epsg() == 27700
    assert validated.geometry.iloc[0].area > 0


@pytestmark_boundary
def test_rectangle_site_in_england_is_eligible_and_over_water_is_not(england_boundary):
    england_rect = validate_site(rectangle_site(0.10, 52.20, 0.11, 52.21))
    assert classify_site_england_eligibility(england_rect, england_boundary) == ELIGIBLE

    irish_rect = validate_site(rectangle_site(-6.30, 53.30, -6.20, 53.40))
    assert classify_site_england_eligibility(irish_rect, england_boundary) == OUTSIDE


@pytest.mark.parametrize(
    "args, needle",
    [
        ((0.11, 52.20, 0.10, 52.21), "west"),
        ((0.10, 52.21, 0.11, 52.20), "south"),
        ((0.10, 52.20, 0.10, 52.21), "west"),
        ((float("nan"), 52.20, 0.11, 52.21), "finite"),
    ],
)
def test_rectangle_site_rejects_bad_coordinates(args, needle):
    with pytest.raises(ValueError, match=needle):
        rectangle_site(*args)


def test_large_area_warning_is_advisory_and_never_a_hard_cap():
    app = _import_app()
    # a generous advisory threshold, well above any normal development site
    assert isinstance(app.LARGE_AREA_WARN_HA, float)
    assert 5_000 <= app.LARGE_AREA_WARN_HA <= 1_000_000
    assert not hasattr(app, "DRAWN_AREA_MAX_HA")  # the old hard cap is gone

    # a plausibly-typed small rectangle stays below the advisory line...
    small = validate_site(rectangle_site(0.10, 52.20, 0.11, 52.21))
    assert small.geometry.iloc[0].area / 10_000 < app.LARGE_AREA_WARN_HA
    # ...a very large one is above it (advisory only - still screenable)
    big = validate_site(rectangle_site(-0.236, 51.440, -0.019, 51.575))
    assert big.geometry.iloc[0].area / 10_000 > app.LARGE_AREA_WARN_HA


# --------------------------------------------------------------------------- #
# "Define area" - interactive drawing -> rectangle (pure conversion)
# --------------------------------------------------------------------------- #


def _draw_feature(west, south, east, north):
    """A GeoJSON rectangle the shape streamlit-folium hands back for a draw."""
    return {
        "type": "Feature",
        "properties": {},
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [west, south],
                    [west, north],
                    [east, north],
                    [east, south],
                    [west, south],
                ]
            ],
        },
    }


def test_rect_bounds_from_drawing_extracts_wsen():
    assert rect_bounds_from_drawing(_draw_feature(0.10, 52.20, 0.109, 52.206)) == (
        0.10,
        52.20,
        0.109,
        52.206,
    )
    # a bare geometry dict (no Feature wrapper) also works
    assert rect_bounds_from_drawing(
        _draw_feature(0.10, 52.20, 0.109, 52.206)["geometry"]
    ) == (0.10, 52.20, 0.109, 52.206)


def test_drawing_rectangle_matches_the_numeric_input_rectangle():
    bounds = rect_bounds_from_drawing(_draw_feature(0.10, 52.20, 0.109, 52.206))
    from_draw = validate_site(rectangle_site(*bounds)).total_bounds
    from_numbers = validate_site(rectangle_site(0.10, 52.20, 0.109, 52.206)).total_bounds
    assert tuple(round(v, 6) for v in from_draw) == tuple(
        round(v, 6) for v in from_numbers
    )


def test_drawn_rectangle_flows_through_validation_and_eligibility(england_boundary):
    bounds = rect_bounds_from_drawing(_draw_feature(0.10, 52.20, 0.109, 52.206))
    gdf = rectangle_site(*bounds)
    assert gdf.crs.to_epsg() == 4326
    validated = validate_site(gdf)
    assert validated.crs.to_epsg() == 27700
    assert classify_site_england_eligibility(validated, england_boundary) == ELIGIBLE


@pytest.mark.parametrize(
    "payload",
    [
        None,
        "not a dict",
        {},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]}},
        {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": []}},
        {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[0, 0]]]}},
        {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[float("nan"), 0], [1, 1], [2, 2], [3, 3]]]}},
    ],
)
def test_rect_bounds_from_drawing_rejects_bad_payloads_without_raising(payload):
    assert rect_bounds_from_drawing(payload) is None


def test_rect_bounds_from_drawing_uses_the_last_of_several_drawings():
    # the app takes all_drawings[-1]; a later rectangle replaces an earlier one
    drawings = [
        _draw_feature(0.0, 51.0, 0.1, 51.1),
        _draw_feature(1.0, 52.0, 1.2, 52.3),
    ]
    assert rect_bounds_from_drawing(drawings[-1]) == (1.0, 52.0, 1.2, 52.3)


# --------------------------------------------------------------------------- #
# "Mapped overlap by theme" - compact bars (not a pie)
# --------------------------------------------------------------------------- #


def test_overlap_summary_has_four_area_bars_and_no_irz_bar():
    summary = build_overlap_summary(mk_result(sssi=mk_sssi(has_overlap=True)))
    assert [bar.theme_key for bar in summary.bars] == [
        "sssi",
        "priority_habitats",
        "ancient_woodland",
        "flood_zones",
    ]
    assert "irz" not in {bar.theme_key for bar in summary.bars}


def test_overlap_summary_irz_is_context_only():
    present = build_overlap_summary(mk_result(irz=mk_irz(zone_count=3)))
    assert present.irz_present is True
    assert "3 contextual zones" == present.irz_label
    absent = build_overlap_summary(mk_result(irz=mk_irz(zone_count=0)))
    assert absent.irz_present is False
    assert "no contextual zones" in absent.irz_label.lower()


def test_overlap_summary_zero_and_tiny_values_render_sensibly():
    result = mk_result(
        sssi=mk_sssi(has_overlap=True, pct=0.04),
        phi=mk_phi(has=False),
        aw=mk_aw(has=False),
        fz=mk_fz(has=True, pct=84.35),
    )
    bars = {bar.theme_key: bar for bar in build_overlap_summary(result).bars}
    assert bars["sssi"].pct_label == "<0.1%" and bars["sssi"].fill_fraction > 0
    assert bars["priority_habitats"].pct_label == "0%"
    assert bars["priority_habitats"].fill_fraction == 0.0
    assert bars["flood_zones"].fill_fraction == pytest.approx(0.8435, abs=1e-4)


def test_overlap_summary_has_non_additivity_note_and_no_total():
    summary = build_overlap_summary(mk_result(sssi=mk_sssi(has_overlap=True)))
    assert "should not be added together" in summary.note
    text = " ".join(
        [summary.note, summary.irz_label] + [b.pct_label for b in summary.bars]
    )
    for word in ("total", "combined", "overall", "score", "rank", "pass", "fail"):
        assert word not in text.lower()
    assert not _BANNED.search(text)


# --------------------------------------------------------------------------- #
# Friendlier validation-message presentation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "fixture, needle, detail_kept",
    [
        ("malformed.geojson", "valid GeoJSON", True),
        ("non_polygon.geojson", "Polygon or MultiPolygon", True),
        ("empty_geometry.geojson", "no usable polygon geometry", False),
        ("multiple_features.geojson", "one site feature at a time", False),
    ],
)
def test_friendly_site_error_from_real_fixtures(fixture, needle, detail_kept):
    try:
        validate_site(read_geojson_site(_fixture(fixture)))
    except (TypeError, ValueError) as exc:
        headline, detail = friendly_site_error(str(exc))
    else:  # pragma: no cover - fixture is meant to fail
        pytest.fail(f"{fixture} unexpectedly validated")

    assert needle.lower() in headline.lower()
    assert not _BANNED.search(headline)
    assert "Traceback" not in headline
    assert (detail is not None) is detail_kept


def test_friendly_multiple_features_message_reports_the_count():
    try:
        validate_site(read_geojson_site(_fixture("multiple_features.geojson")))
    except ValueError as exc:
        headline, _ = friendly_site_error(str(exc))
    assert "2 features" in headline


def test_friendly_repair_notice_reframes_the_make_valid_warning():
    raw_warning = "site geometry is invalid; attempting repair with shapely.make_valid()"
    notice = friendly_repair_notice([raw_warning])
    assert notice is not None
    assert "repaired for screening" in notice
    assert "make_valid" not in notice  # implementation detail stays out of the headline
    assert friendly_repair_notice([]) is None


def test_friendly_site_error_falls_back_without_crashing():
    headline, detail = friendly_site_error("some message we have never seen before")
    assert headline and not _BANNED.search(headline)
    assert detail == "some message we have never seen before"


# --------------------------------------------------------------------------- #
# Video-prep UI pass: CARTO basemap key, header wording, footer, compact cards
# --------------------------------------------------------------------------- #


def test_carto_tile_layer_uses_the_key_only_in_the_url():
    keyed = carto_tile_layer("FAKE_CARTO_KEY_abc123")
    assert "key=FAKE_CARTO_KEY_abc123" in keyed["tiles"]
    assert "cartocdn.com" in keyed["tiles"]
    # the key must not leak into anything else the component renders
    assert "FAKE_CARTO_KEY_abc123" not in keyed["attr"]
    assert "FAKE_CARTO_KEY_abc123" not in keyed["name"]
    # attribution is always present
    assert "OpenStreetMap" in keyed["attr"] and "CARTO" in keyed["attr"]


@pytest.mark.parametrize("missing", [None, "", "   "])
def test_carto_tile_layer_falls_back_to_osm_without_a_key(missing):
    fallback = carto_tile_layer(missing)
    assert "openstreetmap.org" in fallback["tiles"].lower()
    assert "key=" not in fallback["tiles"]
    assert "OpenStreetMap" in fallback["attr"]
    assert "carto" not in fallback["tiles"].lower()


def test_carto_key_helper_reads_env_and_trims(monkeypatch):
    app = _import_app()
    monkeypatch.delenv("CARTO_BASEMAP_API_KEY", raising=False)
    # st.secrets has no such key in the test environment
    assert app._carto_api_key() is None

    monkeypatch.setenv("CARTO_BASEMAP_API_KEY", "  env-key-xyz  ")
    assert app._carto_api_key() == "env-key-xyz"

    monkeypatch.setenv("CARTO_BASEMAP_API_KEY", "   ")
    assert app._carto_api_key() is None


@pytestmark_apptest
def test_header_uses_proof_of_concept_wording_and_no_stale_disclaimer():
    at = _app_test()
    at.run(timeout=120)
    header = " ".join(m.value for m in at.markdown if "ess-subline" in m.value)
    assert "Proof-of-concept" in header
    assert "not an environmental assessment or a planning decision" not in header
    # must not imply future regulatory status
    assert "not officially usable" not in header.lower()


@pytestmark_apptest
def test_footer_has_contact_links():
    at = _app_test()
    at.run(timeout=120)
    footer = " ".join(
        m.value for m in at.markdown if "ess-footer-links" in m.value and "<a href" in m.value
    )
    assert "https://ariyoamy.github.io/" in footer
    assert "https://github.com/ariyoamy" in footer
    assert "mailto:ariyoamy@gmail.com" in footer
    assert 'target="_blank"' in footer  # external links open in a new tab


@pytestmark_apptest
def test_compact_result_cards_keep_theme_state_and_metric():
    at = _app_test()
    _inject_demo_result(at, mk_result(sssi=mk_sssi(has_overlap=True)))
    at.run(timeout=120)

    cards = [m.value for m in at.markdown if _CARD_MARK in m.value]
    assert len(cards) == 5
    blob = " ".join(cards)
    for theme in ("SSSI", "Priority Habitats", "Ancient Woodland", "Flood Zones"):
        assert theme in blob
    assert "Mapped overlap" in blob  # result state still shown
    assert "%" in blob  # headline percentage still shown
    assert "of site" in blob  # secondary metric still shown
    assert not _BANNED.search(blob)
