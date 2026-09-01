"""PyDeck map construction for the screening workspace.

This module builds the interactive map from a screening result: one prominent
candidate-site outline plus only the geometry that is actually relevant to that
site (intersecting SSSI / Priority Habitat / Ancient Woodland / Flood Zone
pieces, contextual IRZ polygons, or the nearest SSSI when nothing overlaps).
National source layers are never drawn.

It imports PyDeck and GeoPandas but not Streamlit, so the layer builders can be
tested directly. Colours are a small, meaningful set - greens for SSSI and
priority habitat (a deeper forest green vs a lighter leaf green), ochre for
ancient woodland, two blues for the flood zones, slate-violet for the contextual
IRZ, and a deep blue-green for the candidate-site outline. Value shifts of a few
hues, not a rainbow. The same table drives the map, the legend and the result
cards so they stay in step.

The candidate-site outline is drawn last (on top) but is **not pickable** and has
no hover highlight, so hovering the map surfaces the environmental layer
underneath rather than always reporting "Candidate site". Environmental layers
are pickable and use PyDeck's built-in ``auto_highlight`` so the hovered polygon
is obvious.

Layer visibility is a display concern only. ``build_map_layers`` /
``build_deck`` accept a ``visible`` set of user-facing control keys; passing a
different set never touches the screening result or re-runs any spatial work.
"""

from __future__ import annotations

import math

import geopandas as gpd
import pydeck as pdk
from shapely.geometry import mapping

WGS84 = "EPSG:4326"

# A subtle translucent-white wash that stays legible over every fill in the
# palette (greens, blues, ochre, slate-violet).
HIGHLIGHT_COLOR = [255, 255, 255, 110]

# style key -> {label, tt_title, fill [r,g,b,a], line [r,g,b], line_px}
#   label     - legend text
#   tt_title  - bold first line of the hover tooltip
LAYER_STYLES: dict[str, dict] = {
    "site": {
        "label": "Candidate site",
        "tt_title": "Candidate site",
        "fill": [20, 52, 58, 20],
        "line": [17, 48, 46],
        "line_px": 2.6,
    },
    "sssi": {
        "label": "SSSI (overlap)",
        "tt_title": "SSSI",
        "fill": [39, 118, 92, 120],
        "line": [24, 88, 66],
        "line_px": 1.5,
    },
    "sssi_nearest": {
        "label": "Nearest SSSI",
        "tt_title": "Nearest SSSI",
        "fill": [141, 173, 160, 70],
        "line": [96, 130, 118],
        "line_px": 1.2,
    },
    "irz": {
        "label": "SSSI IRZ (context)",
        "tt_title": "SSSI Impact Risk Zone",
        "fill": [123, 118, 168, 60],
        "line": [92, 86, 140],
        "line_px": 1.0,
    },
    "priority_habitats": {
        "label": "Priority habitat",
        "tt_title": "Priority Habitat",
        "fill": [124, 160, 74, 120],
        "line": [88, 118, 46],
        "line_px": 1.3,
    },
    "ancient_woodland": {
        "label": "Ancient woodland",
        "tt_title": "Ancient Woodland",
        "fill": [178, 138, 68, 135],
        "line": [132, 96, 40],
        "line_px": 1.3,
    },
    "flood_zone_2": {
        "label": "Flood Zone 2",
        "tt_title": "Flood Zone 2",
        "fill": [124, 176, 214, 110],
        "line": [82, 132, 172],
        "line_px": 1.1,
    },
    "flood_zone_3": {
        "label": "Flood Zone 3",
        "tt_title": "Flood Zone 3",
        "fill": [50, 120, 178, 140],
        "line": [30, 88, 138],
        "line_px": 1.1,
    },
}

# User-facing visibility controls: ordered (control key, label, style keys it
# toggles). The candidate site is deliberately absent - it is always shown.
_LAYER_CONTROLS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("sssi", "SSSI / nearest SSSI", ("sssi", "sssi_nearest")),
    ("irz", "SSSI Impact Risk Zone", ("irz",)),
    ("priority_habitats", "Priority Habitats", ("priority_habitats",)),
    ("ancient_woodland", "Ancient Woodland", ("ancient_woodland",)),
    ("flood_zone_2", "Flood Zone 2", ("flood_zone_2",)),
    ("flood_zone_3", "Flood Zone 3", ("flood_zone_3",)),
)
_STYLE_TO_CONTROL = {sk: ck for ck, _, sks in _LAYER_CONTROLS for sk in sks}


# --------------------------------------------------------------------------- #
# Tooltip text - concise, built from real result attributes only
# --------------------------------------------------------------------------- #


def _tt_site(_row) -> str:
    return "boundary"


def _tt_sssi(row) -> str:
    return f"{row['name']}<br/>{row['intersection_area_ha']:.2f} ha overlap"


def _tt_sssi_nearest(row) -> str:
    return f"{row['name']}<br/>nearest designated site"


def _tt_irz(row) -> str:
    return f"Advice zone {row['irz_code']}"


def _tt_phi(row) -> str:
    return f"{row['habitat_name']}<br/>{row['intersection_area_ha']:.2f} ha overlap"


def _tt_aw(row) -> str:
    return (
        f"{row['category_name']} ({row['inventory']})"
        f"<br/>{row['intersection_area_ha']:.2f} ha overlap"
    )


def _tt_fz(row) -> str:
    return f"{row['intersection_area_ha']:.2f} ha overlap<br/>{row['site_pct']:.1f}% of site"


# --------------------------------------------------------------------------- #
# Layer building
# --------------------------------------------------------------------------- #


def _feature_collection(gdf: gpd.GeoDataFrame, style: dict, tooltip_fn) -> dict:
    """WGS84 GeoJSON FeatureCollection carrying only the display properties."""
    features = []
    for _, row in gdf.to_crs(WGS84).iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": mapping(geom),
                "properties": {
                    "layer_label": style["label"],
                    "tt_title": style["tt_title"],
                    "tooltip": tooltip_fn(row),
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def _layer(
    style_key: str,
    gdf: gpd.GeoDataFrame,
    tooltip_fn,
    layer_id: str,
    *,
    pickable: bool = True,
):
    """Return a PyDeck ``GeoJsonLayer`` for ``gdf``, or ``None`` if it is empty."""
    if gdf is None or len(gdf) == 0:
        return None
    style = LAYER_STYLES[style_key]
    collection = _feature_collection(gdf, style, tooltip_fn)
    if not collection["features"]:
        return None
    return pdk.Layer(
        "GeoJsonLayer",
        data=collection,
        id=layer_id,
        stroked=True,
        filled=True,
        pickable=pickable,
        auto_highlight=pickable,
        highlight_color=HIGHLIGHT_COLOR,
        get_fill_color=style["fill"],
        get_line_color=style["line"],
        line_width_min_pixels=style["line_px"],
    )


def _site_gdf(result, site):
    if site is not None:
        return site
    if result is not None:
        return result.site
    raise ValueError("a candidate site is required to build the map")


def _present_style_keys(result) -> list[str]:
    """Ordered style keys whose geometry this result would actually draw."""
    keys: list[str] = []
    sssi = result.sssi
    if sssi.has_overlap and len(sssi.features):
        keys.append("sssi")
    elif result.nearest_sssi is not None and len(result.nearest_sssi.features):
        keys.append("sssi_nearest")
    if result.sssi_irz.zone_count and len(result.sssi_irz.zones):
        keys.append("irz")
    phi = result.priority_habitats
    if phi.has_priority_overlap and len(phi.habitats):
        keys.append("priority_habitats")
    woodland = result.ancient_woodland
    if woodland.has_overlap and len(woodland.features):
        keys.append("ancient_woodland")
    flood = result.flood_zones
    if flood.has_flood_zone_overlap and len(flood.zones):
        present = {str(z) for z in flood.zones["flood_zone"]}
        if "FZ2" in present:
            keys.append("flood_zone_2")
        if "FZ3" in present:
            keys.append("flood_zone_3")
    return keys


def _is_visible(style_key: str, visible) -> bool:
    return visible is None or _STYLE_TO_CONTROL[style_key] in visible


def build_map_layers(result=None, *, site=None, visible=None) -> list[pdk.Layer]:
    """Build the ordered PyDeck layers for a screening result.

    ``result`` is a :class:`~environmental_site_screener.screening.ScreeningResult`
    (or ``None`` to draw only the site). ``site`` overrides the site geometry and
    is what the app passes before the first screening run.

    ``visible`` is a set of user-facing control keys (see
    :func:`available_layer_controls`). ``None`` shows every present layer; an
    empty set shows the candidate site only. The candidate-site layer is always
    included and is always drawn last (on top) and non-pickable.
    """
    site_gdf = _site_gdf(result, site)
    layers: list = []

    if result is not None:
        sssi = result.sssi
        if sssi.has_overlap and len(sssi.features) and _is_visible("sssi", visible):
            layers.append(_layer("sssi", sssi.features, _tt_sssi, "sssi"))
        elif (
            result.nearest_sssi is not None
            and len(result.nearest_sssi.features)
            and _is_visible("sssi_nearest", visible)
        ):
            layers.append(
                _layer(
                    "sssi_nearest",
                    result.nearest_sssi.features,
                    _tt_sssi_nearest,
                    "sssi-nearest",
                )
            )

        irz = result.sssi_irz
        if irz.zone_count and len(irz.zones) and _is_visible("irz", visible):
            layers.append(_layer("irz", irz.zones, _tt_irz, "irz"))

        phi = result.priority_habitats
        if (
            phi.has_priority_overlap
            and len(phi.habitats)
            and _is_visible("priority_habitats", visible)
        ):
            layers.append(_layer("priority_habitats", phi.habitats, _tt_phi, "phi"))

        woodland = result.ancient_woodland
        if (
            woodland.has_overlap
            and len(woodland.features)
            and _is_visible("ancient_woodland", visible)
        ):
            layers.append(_layer("ancient_woodland", woodland.features, _tt_aw, "aw"))

        flood = result.flood_zones
        if flood.has_flood_zone_overlap and len(flood.zones):
            for code, style_key in (("FZ2", "flood_zone_2"), ("FZ3", "flood_zone_3")):
                if not _is_visible(style_key, visible):
                    continue
                subset = flood.zones[flood.zones["flood_zone"] == code]
                if len(subset):
                    layers.append(
                        _layer(style_key, subset, _tt_fz, f"fz-{code.lower()}")
                    )

    # Site outline on top, not pickable and not highlighted: hovering the map
    # should surface the environmental layer underneath, not the site boundary.
    layers.append(_layer("site", site_gdf, _tt_site, "site", pickable=False))
    return [layer for layer in layers if layer is not None]


def available_layer_controls(result) -> list[tuple[str, str, tuple[int, int, int]]]:
    """``(control_key, label, rgb)`` for every layer this result actually draws.

    Ordered as :data:`_LAYER_CONTROLS`. ``rgb`` is the representative legend/map
    colour for that control, so the app can show a matching chip.
    """
    present = set(_present_style_keys(result))
    out: list[tuple[str, str, tuple[int, int, int]]] = []
    for control_key, label, style_keys in _LAYER_CONTROLS:
        active = [sk for sk in style_keys if sk in present]
        if active:
            rgb = tuple(int(c) for c in LAYER_STYLES[active[0]]["fill"][:3])
            out.append((control_key, label, rgb))
    return out


def available_layer_control_keys(result) -> list[str]:
    """Just the control keys from :func:`available_layer_controls`, in order."""
    return [key for key, _, _ in available_layer_controls(result)]


def legend_entries(
    result=None, *, site=None, visible=None
) -> list[tuple[str, tuple[int, int, int]]]:
    """``(label, rgb)`` for the layers the map is actually showing, site first."""
    keys = ["site"]
    if result is not None:
        for style_key in _present_style_keys(result):
            if _is_visible(style_key, visible):
                keys.append(style_key)
    return [
        (LAYER_STYLES[k]["label"], tuple(int(c) for c in LAYER_STYLES[k]["fill"][:3]))
        for k in keys
    ]


# --------------------------------------------------------------------------- #
# View state and deck
# --------------------------------------------------------------------------- #


def _bounds_wgs84(gdf: gpd.GeoDataFrame) -> tuple[float, float, float, float]:
    return tuple(gdf.to_crs(WGS84).total_bounds)


def view_state_for_bounds(
    bounds: tuple[float, float, float, float],
    *,
    pad: float = 2.6,
    min_zoom: float = 4.0,
    max_zoom: float = 16.5,
) -> pdk.ViewState:
    """A centred, zoomed-out-a-little view fitting ``bounds`` (WGS84 degrees)."""
    minx, miny, maxx, maxy = bounds
    centre_lon = (minx + maxx) / 2.0
    centre_lat = (miny + maxy) / 2.0
    span_x = max(maxx - minx, 1e-6) * pad
    span_y = max(maxy - miny, 1e-6) * pad
    zoom = min(math.log2(360.0 / span_x), math.log2(180.0 / span_y))
    zoom = max(min_zoom, min(max_zoom, zoom))
    return pdk.ViewState(
        latitude=centre_lat, longitude=centre_lon, zoom=zoom, bearing=0, pitch=0
    )


# Tooltip: a bold title line then <=2 concise body lines. A capped width with
# normal wrapping keeps it from becoming a wide bar; PyDeck still positions it at
# the pointer, so a tooltip very near the right/bottom edge can be clipped by the
# map frame - a PyDeck limitation with no non-JS fix.
TOOLTIP = {
    "html": "<b>{tt_title}</b><br/>{tooltip}",
    "style": {
        "backgroundColor": "#17302e",
        "color": "#f4f1e6",
        "fontSize": "12px",
        "lineHeight": "1.4",
        "padding": "8px 11px",
        "maxWidth": "230px",
        "whiteSpace": "normal",
        "wordBreak": "break-word",
        "borderRadius": "8px",
        "boxShadow": "0 6px 18px rgba(20,48,44,.25)",
    },
}


def build_deck(result=None, *, site=None, height: int = 640, visible=None) -> pdk.Deck:
    """Assemble the PyDeck ``Deck`` for the workspace map."""
    site_gdf = _site_gdf(result, site)
    return pdk.Deck(
        layers=build_map_layers(result, site=site_gdf, visible=visible),
        initial_view_state=view_state_for_bounds(_bounds_wgs84(site_gdf)),
        map_provider="carto",
        map_style="light",
        height=height,
        tooltip=TOOLTIP,
    )
