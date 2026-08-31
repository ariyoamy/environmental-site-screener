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
from shapely.geometry import Polygon

from environmental_site_screener import screening
from environmental_site_screener.ancient_woodland import AncientWoodlandOverlapResult
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
    build_theme_cards,
    build_theme_detail,
    format_area_ha,
    format_distance,
    format_pct,
    theme_help,
)
from environmental_site_screener.app_map import (
    build_deck,
    build_map_layers,
    legend_entries,
    view_state_for_bounds,
)
from environmental_site_screener.distance import NearestSssiResult
from environmental_site_screener.flood_zones import FloodZoneOverlapResult
from environmental_site_screener.priority_habitats import PriorityHabitatOverlapResult
from environmental_site_screener.screening import ScreeningResult, load_screening_datasets
from environmental_site_screener.site import validate_site
from environmental_site_screener.sssi_irz import SssiIrzContextResult
from environmental_site_screener.overlap import SssiOverlapResult

CRS = "EPSG:27700"

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


def _rect(xmin, ymin, xmax, ymax):
    return Polygon(
        [(xmin, ymin), (xmin, ymax), (xmax, ymax), (xmax, ymin), (xmin, ymin)]
    )


def _empty_gdf(columns):
    return gpd.GeoDataFrame(
        {c: [] for c in columns if c != "geometry"}, geometry=[], crs=CRS
    )


# --------------------------------------------------------------------------- #
# synthetic backend result objects
# --------------------------------------------------------------------------- #


def mk_sssi(*, has_overlap=True, area_ha=0.3838, pct=48.34, feature_count=1):
    cols = [
        "ref_code",
        "name",
        "measure",
        "intersection_area_m2",
        "intersection_area_ha",
        "geometry",
    ]
    if has_overlap:
        feats = gpd.GeoDataFrame(
            {
                "ref_code": ["S1"],
                "name": ["Test SSSI"],
                "measure": ["Lowland fen"],
                "intersection_area_m2": [area_ha * 10_000],
                "intersection_area_ha": [area_ha],
            },
            geometry=[_rect(0, 0, 62, 62)],
            crs=CRS,
        )
    else:
        feats = _empty_gdf(cols)
    return SssiOverlapResult(
        has_overlap=has_overlap,
        feature_count=feature_count if has_overlap else 0,
        features=feats,
        site_area_m2=10_000.0,
        affected_area_m2=area_ha * 10_000 if has_overlap else 0.0,
        affected_area_ha=area_ha if has_overlap else 0.0,
        affected_pct=pct if has_overlap else 0.0,
    )


def mk_nearest(*, distance_m=2659.06):
    feats = gpd.GeoDataFrame(
        {"ref_code": ["S9"], "name": ["Far SSSI"], "measure": ["Broadleaved woodland"]},
        geometry=[_rect(5_000, 5_000, 5_100, 5_100)],
        crs=CRS,
    )
    return NearestSssiResult(
        distance_m=distance_m,
        distance_km=distance_m / 1_000,
        feature_count=1,
        features=feats,
    )


def mk_irz(*, zone_count=2):
    cols = ["irzurl", "irz_code", "geometry"]
    if zone_count:
        urls = [f"https://example.test/?irzcode={i:013d}" for i in range(zone_count)]
        zones = gpd.GeoDataFrame(
            {"irzurl": urls, "irz_code": [f"{i:013d}" for i in range(zone_count)]},
            geometry=[_rect(0, 0, 80, 80) for _ in range(zone_count)],
            crs=CRS,
        )
        advice = tuple(sorted(set(urls)))
    else:
        zones = _empty_gdf(cols)
        advice = ()
    return SssiIrzContextResult(
        has_irz_context=bool(zone_count),
        zone_count=zone_count,
        zones=zones,
        advice_urls=advice,
    )


def mk_phi(*, has=True, area_ha=2.5688, pct=64.22, habitat_count=2, with_context=False):
    hcols = [
        "habitat_code",
        "habitat_name",
        "intersection_area_m2",
        "intersection_area_ha",
        "geometry",
    ]
    ccols = ["uid", "context_codes", "context_habitats", "primsource", "geometry"]
    if has:
        habitats = gpd.GeoDataFrame(
            {
                "habitat_code": ["DWOOD", "LMEAD"][:habitat_count],
                "habitat_name": ["Deciduous woodland", "Lowland meadow"][:habitat_count],
                "intersection_area_m2": [area_ha * 10_000, 1_000.0][:habitat_count],
                "intersection_area_ha": [area_ha, 0.1][:habitat_count],
            },
            geometry=[_rect(0, 0, 50, 50), _rect(10, 10, 20, 20)][:habitat_count],
            crs=CRS,
        )
    else:
        habitats = _empty_gdf(hcols)
    if with_context:
        context = gpd.GeoDataFrame(
            {
                "uid": ["PHI9"],
                "context_codes": ["GMOOR"],
                "context_habitats": ["Grass moorland"],
                "primsource": ["test survey"],
            },
            geometry=[_rect(0, 0, 30, 30)],
            crs=CRS,
        )
    else:
        context = _empty_gdf(ccols)
    return PriorityHabitatOverlapResult(
        has_priority_overlap=has,
        habitat_count=habitat_count if has else 0,
        habitats=habitats,
        context=context,
        site_area_m2=10_000.0,
        affected_area_m2=area_ha * 10_000 if has else 0.0,
        affected_area_ha=area_ha if has else 0.0,
        affected_pct=pct if has else 0.0,
    )


def mk_aw(*, has=True, area_ha=1.0961, pct=27.40, feature_count=1):
    cols = [
        "inventory",
        "category_code",
        "category_name",
        "intersection_area_m2",
        "intersection_area_ha",
        "geometry",
    ]
    if has:
        feats = gpd.GeoDataFrame(
            {
                "inventory": ["revised"],
                "category_code": ["ASNW"],
                "category_name": ["Ancient & Semi-Natural Woodland"],
                "intersection_area_m2": [area_ha * 10_000],
                "intersection_area_ha": [area_ha],
            },
            geometry=[_rect(0, 0, 40, 40)],
            crs=CRS,
        )
    else:
        feats = _empty_gdf(cols)
    return AncientWoodlandOverlapResult(
        has_overlap=has,
        feature_count=feature_count if has else 0,
        features=feats,
        site_area_m2=10_000.0,
        revised_coverage_area_m2=10_000.0,
        fallback_area_m2=0.0,
        affected_area_m2=area_ha * 10_000 if has else 0.0,
        affected_area_ha=area_ha if has else 0.0,
        affected_pct=pct if has else 0.0,
    )


def mk_fz(*, has=True, area_ha=3.3739, pct=84.35, zones_present=("FZ2", "FZ3")):
    cols = [
        "flood_zone",
        "intersection_area_m2",
        "intersection_area_ha",
        "site_pct",
        "flood_sources",
        "origins",
        "geometry",
    ]
    if has:
        n = len(zones_present)
        zones = gpd.GeoDataFrame(
            {
                "flood_zone": list(zones_present),
                "intersection_area_m2": [area_ha * 10_000 / n] * n,
                "intersection_area_ha": [area_ha / n] * n,
                "site_pct": [pct / n] * n,
                "flood_sources": ["river"] * n,
                "origins": ["modelled"] * n,
            },
            geometry=[_rect(0, 0, 50, 50) for _ in range(n)],
            crs=CRS,
        )
        sources, origins = ("river",), ("modelled",)
    else:
        zones = _empty_gdf(cols)
        sources, origins = (), ()
    return FloodZoneOverlapResult(
        has_flood_zone_overlap=has,
        zone_count=len(zones_present) if has else 0,
        zones=zones,
        site_area_m2=10_000.0,
        affected_area_m2=area_ha * 10_000 if has else 0.0,
        affected_area_ha=area_ha if has else 0.0,
        affected_pct=pct if has else 0.0,
        flood_sources=sources,
        origins=origins,
    )


def mk_result(*, sssi=None, nearest=..., irz=None, phi=None, aw=None, fz=None):
    sssi = sssi if sssi is not None else mk_sssi(has_overlap=False)
    if nearest is ...:
        nearest = None if sssi.has_overlap else mk_nearest()
    irz = irz if irz is not None else mk_irz(zone_count=2)
    phi = phi if phi is not None else mk_phi(has=True)
    aw = aw if aw is not None else mk_aw(has=True)
    fz = fz if fz is not None else mk_fz(has=True)
    summary = screening._build_summary(sssi, nearest, irz, phi, aw, fz)
    return ScreeningResult(
        site=demo_site(),
        sssi=sssi,
        nearest_sssi=nearest,
        sssi_irz=irz,
        priority_habitats=phi,
        ancient_woodland=aw,
        flood_zones=fz,
        summary=summary,
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
