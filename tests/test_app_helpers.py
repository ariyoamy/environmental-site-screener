"""Tests for the Streamlit app's pure helper logic.

Streamlit rendering is not tested. These cover: GeoJSON upload parsing, the demo
site, the source-path helpers, the PyDeck layer/legend builders, the theme-card
and theme-detail view-models, and number formatting. Backend spatial behaviour
is covered by the dataset test modules and is not repeated here.
"""

import inspect
import json
import re

import geopandas as gpd
import pydeck as pdk
import pytest

from environmental_site_screener import app_map
from environmental_site_screener.app_data import (
    DEMO_SITE_LABEL,
    default_data_sources,
    demo_site,
    missing_sources,
    read_geojson_site,
)
from environmental_site_screener.app_format import (
    THEME_DISPLAY,
    THEME_KEYS,
    THEME_MARKER_RGB,
    build_theme_cards,
    build_theme_detail,
    format_area_ha,
    format_distance,
    format_pct,
    theme_help,
)
from environmental_site_screener.app_map import (
    available_layer_control_keys,
    available_layer_controls,
    build_deck,
    build_map_layers,
    legend_entries,
    view_state_for_bounds,
)
from environmental_site_screener.screening import load_screening_datasets
from environmental_site_screener.site import validate_site
from synthetic_results import (
    mk_aw,
    mk_fz,
    mk_irz,
    mk_nearest,
    mk_phi,
    mk_result,
    mk_sssi,
    rect as _rect,
)

# Language that would imply a regulatory verdict or a screening score. This is
# deliberately about verdict phrasing ("risk score", "low risk", "pass/fail",
# "safe") - not the bare word "risk", which is unavoidable in the proper noun
# "SSSI Impact Risk Zone".
_BANNED = re.compile(
    r"(risk\s+(score|level|rating|category|band)|(low|high|moderate)\s+risk|"
    r"traffic[\s-]*light|pass/fail|\bpass\b|\bfail\b|\bsafe\b|\bunsafe\b|"
    r"\bscore\b|\brating\b|suitab\w*|\bgrade\b)",
    re.IGNORECASE,
)



def _all_card_text(cards):
    out = []
    for card in cards:
        out += [
            card.theme,
            card.state_label,
            card.primary_metric or "",
            card.secondary_metric or "",
            card.context_line or "",
        ]
    return out


def _all_detail_text(result):
    out = []
    for key in THEME_KEYS:
        detail = build_theme_detail(result, key)
        out.append(detail.headline)
        out += list(detail.metrics)
        out.append(detail.what_it_means)
        out.append(detail.note or "")
        for table in detail.tables:
            out.append(table.title)
            for row in table.rows:
                out += [str(v) for v in row.values()]
    return out


# --------------------------------------------------------------------------- #
# GeoJSON upload
# --------------------------------------------------------------------------- #


def _fc(*polygons, crs_name=None):
    doc = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {}, "geometry": p.__geo_interface__}
            for p in polygons
        ],
    }
    if crs_name is not None:
        doc["crs"] = {"type": "name", "properties": {"name": crs_name}}
    return json.dumps(doc).encode("utf-8")


def test_read_geojson_single_feature_is_one_row_wgs84():
    gdf = read_geojson_site(_fc(_rect(-0.1, 52.0, -0.09, 52.01)))

    assert isinstance(gdf, gpd.GeoDataFrame)
    assert len(gdf) == 1
    assert gdf.crs.to_epsg() == 4326


def test_read_geojson_multi_feature_passes_through_to_validation():
    gdf = read_geojson_site(
        _fc(_rect(-0.1, 52.0, -0.09, 52.01), _rect(0.2, 53.0, 0.21, 53.01))
    )
    assert len(gdf) == 2  # helper does not silently collapse or drop features

    with pytest.raises(ValueError, match="exactly one site feature"):
        validate_site(gdf)


def test_read_geojson_honours_named_epsg_27700_crs():
    gdf = read_geojson_site(
        _fc(_rect(565_100, 195_100, 565_400, 195_400),
            crs_name="urn:ogc:def:crs:EPSG::27700")
    )
    assert gdf.crs.to_epsg() == 27700


def test_read_geojson_empty_featurecollection_raises():
    with pytest.raises(ValueError, match="no features"):
        read_geojson_site(b'{"type": "FeatureCollection", "features": []}')


def test_read_geojson_not_json_raises():
    with pytest.raises(ValueError, match="could not be parsed as JSON"):
        read_geojson_site(b"this is not json")


def test_read_geojson_feature_without_geometry_raises():
    doc = b'{"type": "Feature", "properties": {}}'
    with pytest.raises(ValueError, match="no geometry"):
        read_geojson_site(doc)


# --------------------------------------------------------------------------- #
# demo site and source paths
# --------------------------------------------------------------------------- #


def test_demo_site_validates_to_four_hectares():
    raw = demo_site()
    assert len(raw) == 1
    assert raw.crs.to_epsg() == 27700
    assert "not a real" in DEMO_SITE_LABEL

    validated = validate_site(raw)
    assert validated.crs.to_epsg() == 27700
    assert float(validated.geometry.iloc[0].area) == pytest.approx(40_000.0)


def test_default_data_sources_keys_match_loader_signature(tmp_path):
    keys = set(default_data_sources(tmp_path))
    params = set(inspect.signature(load_screening_datasets).parameters)
    assert keys == params


def test_missing_sources_reports_absent_paths(tmp_path):
    present = tmp_path / "here.gpkg"
    present.write_bytes(b"x")
    absent = tmp_path / "gone.gpkg"

    reported = missing_sources({"a": present, "b": absent})
    assert reported == [absent]


# --------------------------------------------------------------------------- #
# map layers / legend
# --------------------------------------------------------------------------- #


def test_map_layers_overlap_case_has_site_on_top_and_theme_layers():
    result = mk_result(sssi=mk_sssi(has_overlap=True))
    layers = build_map_layers(result)

    assert all(isinstance(layer, pdk.Layer) for layer in layers)
    assert layers[-1].id == "site"  # candidate site drawn last / on top

    ids = {layer.id for layer in layers}
    assert "sssi" in ids
    assert {"phi", "aw", "fz-fz2", "fz-fz3"} <= ids

    sssi_layer = next(layer for layer in layers if layer.id == "sssi")
    feature = sssi_layer.data["features"][0]
    assert feature["properties"]["layer_label"] == "SSSI (overlap)"
    assert isinstance(feature["properties"]["tooltip"], str)
    assert feature["properties"]["tooltip"]


def test_site_map_layer_is_not_pickable_but_result_layers_are():
    layers = build_map_layers(mk_result(sssi=mk_sssi(has_overlap=True)))
    by_id = {layer.id: layer for layer in layers}

    assert by_id["site"].pickable is False
    for layer_id in ("sssi", "irz", "phi", "aw", "fz-fz2", "fz-fz3"):
        assert by_id[layer_id].pickable is True, f"{layer_id} should be pickable"


def test_nearest_sssi_layer_is_pickable():
    layers = build_map_layers(mk_result(sssi=mk_sssi(has_overlap=False), nearest=mk_nearest()))
    by_id = {layer.id: layer for layer in layers}
    assert by_id["sssi-nearest"].pickable is True
    assert by_id["site"].pickable is False


def test_map_layers_no_overlap_uses_nearest_sssi_layer():
    result = mk_result(sssi=mk_sssi(has_overlap=False), nearest=mk_nearest())
    ids = {layer.id for layer in build_map_layers(result)}

    assert "sssi-nearest" in ids
    assert "sssi" not in ids


def test_map_layers_empty_context_result_adds_no_layer():
    result = mk_result(irz=mk_irz(zone_count=0))
    ids = {layer.id for layer in build_map_layers(result)}

    assert "irz" not in ids


def test_map_layers_site_only_before_first_run():
    layers = build_map_layers(site=demo_site())
    assert [layer.id for layer in layers] == ["site"]


def test_legend_entries_lead_with_candidate_site():
    entries = legend_entries(mk_result(sssi=mk_sssi(has_overlap=True)))
    labels = [label for label, _ in entries]

    assert labels[0] == "Candidate site"
    assert "SSSI (overlap)" in labels
    assert "Flood Zone 3" in labels
    for _label, rgb in entries:
        assert len(rgb) == 3


def test_build_deck_serialises_without_error():
    deck = build_deck(mk_result(sssi=mk_sssi(has_overlap=True)))
    assert isinstance(deck, pdk.Deck)
    assert isinstance(deck.to_json(), str)


def test_view_state_zoom_is_clamped_and_centred():
    view = view_state_for_bounds((-0.1, 52.0, -0.09, 52.01))
    assert 4.0 <= view.zoom <= 16.5
    assert -0.1 < view.longitude < -0.09
    assert 52.0 < view.latitude < 52.01


# --------------------------------------------------------------------------- #
# layer visibility control
# --------------------------------------------------------------------------- #


def _ids(layers):
    return {layer.id for layer in layers}


def test_visible_none_shows_every_present_layer():
    result = mk_result(sssi=mk_sssi(has_overlap=True))
    all_ids = _ids(build_map_layers(result))
    keys = set(available_layer_control_keys(result))

    assert _ids(build_map_layers(result, visible=keys)) == all_ids


def test_visible_subset_shows_only_selected_env_layers_plus_site():
    result = mk_result(sssi=mk_sssi(has_overlap=True))

    assert _ids(build_map_layers(result, visible={"priority_habitats"})) == {"phi", "site"}
    assert _ids(build_map_layers(result, visible={"irz", "ancient_woodland"})) == {
        "irz",
        "aw",
        "site",
    }


def test_site_only_when_visible_is_empty():
    result = mk_result(sssi=mk_sssi(has_overlap=True))
    layers = build_map_layers(result, visible=set())

    assert [layer.id for layer in layers] == ["site"]
    assert layers[0].pickable is False


def test_show_all_restores_every_available_result_layer():
    result = mk_result(sssi=mk_sssi(has_overlap=True))
    every = set(available_layer_control_keys(result))

    assert _ids(build_map_layers(result, visible=every)) == _ids(build_map_layers(result))


def test_flood_zone_2_and_3_are_independent_controls():
    result = mk_result(fz=mk_fz(has=True, zones_present=("FZ2", "FZ3")))

    assert _ids(build_map_layers(result, visible={"flood_zone_3"})) == {"fz-fz3", "site"}
    assert _ids(build_map_layers(result, visible={"flood_zone_2"})) == {"fz-fz2", "site"}


def test_sssi_control_covers_both_overlap_and_nearest_style_keys():
    nearest_result = mk_result(sssi=mk_sssi(has_overlap=False), nearest=mk_nearest())
    assert _ids(build_map_layers(nearest_result, visible={"sssi"})) == {
        "sssi-nearest",
        "site",
    }
    overlap_result = mk_result(sssi=mk_sssi(has_overlap=True))
    assert "sssi" in _ids(build_map_layers(overlap_result, visible={"sssi"}))


def test_layer_visibility_does_not_alter_the_result_object():
    result = mk_result(sssi=mk_sssi(has_overlap=True))
    before = (
        result.priority_habitats.affected_area_ha,
        result.flood_zones.affected_pct,
        result.sssi.feature_count,
        result.ancient_woodland.has_overlap,
    )

    build_map_layers(result, visible={"priority_habitats"})
    build_map_layers(result, visible=set())
    build_map_layers(result, visible=None)

    after = (
        result.priority_habitats.affected_area_ha,
        result.flood_zones.affected_pct,
        result.sssi.feature_count,
        result.ancient_woodland.has_overlap,
    )
    assert before == after


def test_available_layer_controls_lists_only_present_layers_with_colour():
    result = mk_result(sssi=mk_sssi(has_overlap=True), aw=mk_aw(has=False))
    controls = available_layer_controls(result)
    keys = [key for key, _, _ in controls]

    assert "ancient_woodland" not in keys
    assert {"sssi", "irz", "priority_habitats", "flood_zone_2", "flood_zone_3"} <= set(keys)
    for key, label, rgb in controls:
        assert isinstance(label, str) and label
        assert len(rgb) == 3 and all(isinstance(component, int) for component in rgb)


def test_legend_reflects_the_visible_layer_selection():
    result = mk_result(sssi=mk_sssi(has_overlap=True))
    labels = [label for label, _ in legend_entries(result, visible={"priority_habitats"})]

    assert labels[0] == "Candidate site"  # site always in the legend
    assert "Priority habitat" in labels
    assert "SSSI (overlap)" not in labels


# --------------------------------------------------------------------------- #
# hover highlight + tooltips
# --------------------------------------------------------------------------- #


def test_environmental_layers_have_hover_highlight_and_site_does_not():
    layers = {layer.id: layer for layer in build_map_layers(mk_result(sssi=mk_sssi(has_overlap=True)))}

    for layer_id in ("sssi", "irz", "phi", "aw", "fz-fz2", "fz-fz3"):
        assert getattr(layers[layer_id], "auto_highlight", False) is True
        assert layers[layer_id].pickable is True
    assert getattr(layers["site"], "auto_highlight", True) is False
    assert layers["site"].pickable is False


def test_tooltips_are_concise_title_plus_short_body():
    layers = {layer.id: layer for layer in build_map_layers(mk_result(sssi=mk_sssi(has_overlap=True)))}

    phi = layers["phi"].data["features"][0]["properties"]
    assert phi["tt_title"] == "Priority Habitat"
    assert "Deciduous woodland" in phi["tooltip"]
    assert "ha overlap" in phi["tooltip"]
    assert phi["tooltip"].count("<br/>") <= 1  # title line + at most two body lines

    fz = layers["fz-fz3"].data["features"][0]["properties"]
    assert fz["tt_title"] == "Flood Zone 3"
    assert "% of site" in fz["tooltip"]


def test_tooltip_template_and_style_are_width_capped():
    tooltip = app_map.TOOLTIP
    assert tooltip["html"] == "<b>{tt_title}</b><br/>{tooltip}"
    assert tooltip["style"]["whiteSpace"] == "normal"
    assert "maxWidth" in tooltip["style"]


# --------------------------------------------------------------------------- #
# card / legend / map colour consistency
# --------------------------------------------------------------------------- #


def test_theme_marker_rgb_matches_map_layer_styles():
    style_for_theme = {
        "sssi": "sssi",
        "irz": "irz",
        "priority_habitats": "priority_habitats",
        "ancient_woodland": "ancient_woodland",
        "flood_zones": "flood_zone_3",
    }
    assert set(THEME_MARKER_RGB) == set(THEME_KEYS)
    for theme_key, style_key in style_for_theme.items():
        expected = tuple(int(c) for c in app_map.LAYER_STYLES[style_key]["fill"][:3])
        assert THEME_MARKER_RGB[theme_key] == expected


def test_cards_carry_marker_rgb_matching_the_theme_colour():
    cards = build_theme_cards(mk_result(sssi=mk_sssi(has_overlap=True)))
    by_theme = {card.theme: card for card in cards}

    assert by_theme["Priority Habitats"].marker_rgb == THEME_MARKER_RGB["priority_habitats"]
    assert by_theme["Flood Zones"].marker_rgb == THEME_MARKER_RGB["flood_zones"]
    for card in cards:
        assert len(card.marker_rgb) == 3
        assert all(isinstance(component, int) for component in card.marker_rgb)


# --------------------------------------------------------------------------- #
# theme cards
# --------------------------------------------------------------------------- #


def test_cards_are_five_in_fixed_theme_order():
    cards = build_theme_cards(mk_result())
    assert [c.theme for c in cards] == [
        "SSSI",
        "SSSI Impact Risk Zone",
        "Priority Habitats",
        "Ancient Woodland",
        "Flood Zones",
    ]


def test_sssi_overlap_card_leads_with_percentage_then_area():
    sssi = build_theme_cards(mk_result(sssi=mk_sssi(has_overlap=True)))[0]

    assert sssi.tone == "overlap"
    assert sssi.state_label == "Mapped overlap"
    assert sssi.primary_metric.endswith("%")
    assert "ha of site" in sssi.secondary_metric
    assert "intersecting SSSI" in sssi.context_line


def test_overlap_cards_all_lead_with_a_percentage():
    result = mk_result(
        sssi=mk_sssi(has_overlap=True),
        phi=mk_phi(has=True),
        aw=mk_aw(has=True),
        fz=mk_fz(has=True),
    )
    cards = {c.theme: c for c in build_theme_cards(result)}
    for theme in ("SSSI", "Priority Habitats", "Ancient Woodland", "Flood Zones"):
        assert cards[theme].primary_metric.endswith("%"), theme
        assert "ha of site" in cards[theme].secondary_metric, theme


def test_sssi_no_overlap_card_reports_nearest_distance():
    sssi = build_theme_cards(
        mk_result(sssi=mk_sssi(has_overlap=False), nearest=mk_nearest(distance_m=2659.06))
    )[0]

    assert sssi.tone == "none"
    assert sssi.state_label == "No mapped overlap"
    assert sssi.primary_metric is None
    assert sssi.secondary_metric.startswith("Nearest:")
    assert "km" in sssi.secondary_metric or " m" in sssi.secondary_metric


def test_irz_card_is_context_with_no_numeric_metric():
    irz = build_theme_cards(mk_result(irz=mk_irz(zone_count=3)))[1]

    assert irz.tone == "context"
    assert irz.state_label == "Context identified"
    assert irz.primary_metric is None
    assert irz.secondary_metric is None
    assert "zone" in irz.context_line.lower()


def test_irz_card_no_context_state():
    irz = build_theme_cards(mk_result(irz=mk_irz(zone_count=0)))[1]
    assert irz.state_label == "No IRZ context"
    assert irz.context_line is None


def test_genuine_zero_overlap_card_says_no_mapped_overlap():
    phi = build_theme_cards(mk_result(phi=mk_phi(has=False)))[2]

    assert phi.tone == "none"
    assert phi.state_label == "No mapped overlap"
    assert phi.primary_metric is None


def test_flood_zone_no_overlap_card_uses_dataset_phrasing():
    fz = build_theme_cards(mk_result(fz=mk_fz(has=False)))[4]
    assert fz.state_label == "No mapped overlap"
    assert "Flood Zone 2 or 3" in fz.context_line


# --------------------------------------------------------------------------- #
# plain-English theme help
# --------------------------------------------------------------------------- #


def test_every_theme_has_a_non_empty_plain_english_explanation():
    for key in THEME_KEYS:
        text = theme_help(key)
        assert isinstance(text, str)
        assert len(text.split()) >= 10, f"{key} help is too short"
        assert not _BANNED.search(text), f"{key} help uses judgement language"
    # the "About the themes" popover needs a display name for every key
    assert set(THEME_DISPLAY) == set(THEME_KEYS)


def test_theme_help_rejects_unknown_key():
    with pytest.raises(KeyError):
        theme_help("not_a_theme")


# --------------------------------------------------------------------------- #
# theme detail
# --------------------------------------------------------------------------- #


def test_detail_every_theme_has_headline_and_what_it_means():
    result = mk_result()
    for key in THEME_KEYS:
        detail = build_theme_detail(result, key)
        assert detail.headline.strip()
        assert len(detail.what_it_means.split()) >= 12
        # the plain-English explanation is folded into "What this means"
        assert theme_help(key).split(".")[0] in detail.what_it_means


def test_detail_sssi_overlap_lists_intersecting_features():
    detail = build_theme_detail(mk_result(sssi=mk_sssi(has_overlap=True)), "sssi")

    assert detail.headline == "Mapped SSSI overlaps this candidate site."
    assert detail.metrics and "of the site" in detail.metrics[0]
    assert detail.tables[0].title == "Intersecting SSSIs"
    assert detail.tables[0].rows[0]["Reference"] == "S1"


def test_detail_sssi_no_overlap_shows_nearest_name_and_table():
    detail = build_theme_detail(
        mk_result(sssi=mk_sssi(has_overlap=False), nearest=mk_nearest()), "sssi"
    )
    assert detail.headline.startswith("No mapped SSSI")
    assert detail.metrics and "Far SSSI" in detail.metrics[0]
    assert "edge to edge" in detail.what_it_means
    assert any("Nearest SSSI" in t.title for t in detail.tables)


def test_detail_irz_flags_contextual_nature_and_links():
    detail = build_theme_detail(mk_result(irz=mk_irz(zone_count=2)), "irz")

    assert "not a finding" in detail.what_it_means.lower()
    assert detail.note is not None and "advice link" in detail.note.lower()
    assert len(detail.links) == 2


def test_detail_priority_habitat_context_is_separate_from_priority():
    detail = build_theme_detail(
        mk_result(phi=mk_phi(has=False, with_context=True)), "priority_habitats"
    )
    titles = [t.title for t in detail.tables]
    assert any("context" in t.lower() for t in titles)
    assert detail.note is not None


def test_detail_flood_zone_explains_defences_and_other_sources():
    detail = build_theme_detail(mk_result(fz=mk_fz(has=True)), "flood_zones")

    assert detail.headline.endswith("mapped Flood Zone 2 or 3.")
    means = detail.what_it_means.lower()
    assert "defences" in means
    assert "surface water" in means


def test_detail_ancient_woodland_reports_coverage_split():
    detail = build_theme_detail(mk_result(aw=mk_aw(has=True)), "ancient_woodland")
    joined = " ".join(detail.metrics).lower()
    assert "revised-inventory coverage" in joined and "legacy fallback" in joined


def test_unknown_theme_key_raises():
    with pytest.raises(KeyError):
        build_theme_detail(mk_result(), "not_a_theme")


# --------------------------------------------------------------------------- #
# formatting
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "value, expected",
    [
        (0.0, "0 ha"),
        (0.0005, "<0.01 ha"),
        (0.3838, "0.38 ha"),
        (12.5, "12.50 ha"),
        (2568.8, "2,569 ha"),
    ],
)
def test_format_area_ha(value, expected):
    assert format_area_ha(value) == expected


@pytest.mark.parametrize(
    "value, expected",
    [(0.0, "0%"), (0.02, "<0.1%"), (48.34, "48.3%"), (99.99, "100%")],
)
def test_format_pct(value, expected):
    assert format_pct(value) == expected


@pytest.mark.parametrize(
    "value, expected",
    [(0.0, "0 m"), (740.2, "740 m"), (999.4, "999 m"), (2659.06, "2.66 km")],
)
def test_format_distance(value, expected):
    assert format_distance(value) == expected


# --------------------------------------------------------------------------- #
# no score / rating language anywhere in the helper output
# --------------------------------------------------------------------------- #


def test_helpers_produce_no_score_or_rating_language():
    # a result that exercises every branch: overlap SSSI is swapped for the
    # no-overlap + nearest default, plus context habitat present
    result = mk_result(
        sssi=mk_sssi(has_overlap=False),
        nearest=mk_nearest(),
        phi=mk_phi(has=True, with_context=True),
    )
    texts = _all_card_text(build_theme_cards(result)) + _all_detail_text(result)

    offenders = sorted({m.group(0).lower() for t in texts for m in [_BANNED.search(t)] if m})
    assert not offenders, f"judgement/score language leaked into helper output: {offenders}"


def test_helpers_produce_no_score_language_for_overlap_result():
    result = mk_result(sssi=mk_sssi(has_overlap=True))
    texts = _all_card_text(build_theme_cards(result)) + _all_detail_text(result)
    assert not any(_BANNED.search(t) for t in texts)
