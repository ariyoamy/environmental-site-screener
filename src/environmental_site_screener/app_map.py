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
hues, not a rainbow. The same table drives both the map and the legend so they
stay in step.

The candidate-site outline is drawn last (on top) but is **not pickable**, so
hovering the map surfaces the environmental layer underneath rather than always
reporting "Candidate site".
"""

from __future__ import annotations

import math

import geopandas as gpd
import pydeck as pdk
from shapely.geometry import mapping

WGS84 = "EPSG:4326"

# style key -> {label, fill [r,g,b,a], line [r,g,b], line_px}
LAYER_STYLES: dict[str, dict] = {
    "site": {
        "label": "Candidate site",
        "fill": [20, 52, 58, 20],
        "line": [17, 48, 46],
        "line_px": 2.6,
    },
    "sssi": {
        "label": "SSSI (overlap)",
        "fill": [39, 118, 92, 120],
        "line": [24, 88, 66],
        "line_px": 1.5,
    },
    "sssi_nearest": {
        "label": "Nearest SSSI",
        "fill": [141, 173, 160, 70],
        "line": [96, 130, 118],
        "line_px": 1.2,
    },
    "irz": {
        "label": "SSSI IRZ (context)",
        "fill": [123, 118, 168, 60],
        "line": [92, 86, 140],
        "line_px": 1.0,
    },
    "priority_habitats": {
        "label": "Priority habitat",
        "fill": [124, 160, 74, 120],
        "line": [88, 118, 46],
        "line_px": 1.3,
    },
    "ancient_woodland": {
        "label": "Ancient woodland",
        "fill": [178, 138, 68, 135],
        "line": [132, 96, 40],
        "line_px": 1.3,
    },
    "flood_zone_2": {
        "label": "Flood Zone 2",
        "fill": [124, 176, 214, 110],
        "line": [82, 132, 172],
        "line_px": 1.1,
    },
    "flood_zone_3": {
        "label": "Flood Zone 3",
        "fill": [50, 120, 178, 140],
        "line": [30, 88, 138],
        "line_px": 1.1,
    },
}


# --------------------------------------------------------------------------- #
# Tooltip text - built from real result attributes only
# --------------------------------------------------------------------------- #


def _tt_site(_row) -> str:
    return "Candidate site boundary"


def _tt_sssi(row) -> str:
    return f"{row['name']} ({row['ref_code']}) · {row['intersection_area_ha']:.2f} ha in site"


def _tt_sssi_nearest(row) -> str:
    return f"{row['name']} ({row['ref_code']}) · nearest SSSI"


def _tt_irz(row) -> str:
    return f"SSSI Impact Risk Zone {row['irz_code']}"


def _tt_phi(row) -> str:
    return f"{row['habitat_name']} ({row['habitat_code']}) · {row['intersection_area_ha']:.2f} ha"


def _tt_aw(row) -> str:
    return f"{row['category_name']} · {row['inventory']} · {row['intersection_area_ha']:.2f} ha"


def _tt_fz(row) -> str:
    return f"{row['flood_zone']} · {row['intersection_area_ha']:.2f} ha · {row['site_pct']:.1f}% of site"


# --------------------------------------------------------------------------- #
# Layer building
# --------------------------------------------------------------------------- #


def _feature_collection(gdf: gpd.GeoDataFrame, label: str, tooltip_fn) -> dict:
    """WGS84 GeoJSON FeatureCollection with just ``layer_label`` and ``tooltip``."""
    features = []
    for _, row in gdf.to_crs(WGS84).iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": mapping(geom),
                "properties": {"layer_label": label, "tooltip": tooltip_fn(row)},
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
    collection = _feature_collection(gdf, style["label"], tooltip_fn)
    if not collection["features"]:
        return None
    return pdk.Layer(
        "GeoJsonLayer",
        data=collection,
        id=layer_id,
        stroked=True,
        filled=True,
        pickable=pickable,
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


def build_map_layers(result=None, *, site=None) -> list[pdk.Layer]:
    """Build the ordered PyDeck layers for a screening result.

    ``result`` is a :class:`~environmental_site_screener.screening.ScreeningResult`
    (or ``None`` to draw only the site). ``site`` overrides the site geometry and
    is what the app passes before the first screening run. The candidate-site
    layer is always appended last so it draws on top.
    """
    site_gdf = _site_gdf(result, site)
    layers: list = []

    if result is not None:
        sssi = result.sssi
        if sssi.has_overlap and len(sssi.features):
            layers.append(_layer("sssi", sssi.features, _tt_sssi, "sssi"))
        elif result.nearest_sssi is not None and len(result.nearest_sssi.features):
            layers.append(
                _layer(
                    "sssi_nearest",
                    result.nearest_sssi.features,
                    _tt_sssi_nearest,
                    "sssi-nearest",
                )
            )

        irz = result.sssi_irz
        if irz.zone_count and len(irz.zones):
            layers.append(_layer("irz", irz.zones, _tt_irz, "irz"))

        phi = result.priority_habitats
        if phi.has_priority_overlap and len(phi.habitats):
            layers.append(_layer("priority_habitats", phi.habitats, _tt_phi, "phi"))

        woodland = result.ancient_woodland
        if woodland.has_overlap and len(woodland.features):
            layers.append(_layer("ancient_woodland", woodland.features, _tt_aw, "aw"))

        flood = result.flood_zones
        if flood.has_flood_zone_overlap and len(flood.zones):
            for code, style_key in (("FZ2", "flood_zone_2"), ("FZ3", "flood_zone_3")):
                subset = flood.zones[flood.zones["flood_zone"] == code]
                if len(subset):
                    layers.append(
                        _layer(style_key, subset, _tt_fz, f"fz-{code.lower()}")
                    )

    # Site outline on top, but not pickable: hovering the map should surface the
    # environmental layer underneath, not the site boundary every time.
    layers.append(_layer("site", site_gdf, _tt_site, "site", pickable=False))
    return [layer for layer in layers if layer is not None]


def legend_entries(result=None, *, site=None) -> list[tuple[str, tuple[int, int, int]]]:
    """``(label, rgb)`` for every layer the map will actually show, site first."""
    keys = ["site"]
    if result is not None:
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
    return [(LAYER_STYLES[k]["label"], tuple(LAYER_STYLES[k]["fill"][:3])) for k in keys]


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


TOOLTIP = {
    "html": "<b>{layer_label}</b><br/>{tooltip}",
    "style": {
        "backgroundColor": "#17302e",
        "color": "#f4f1e6",
        "fontSize": "12px",
        "padding": "7px 10px",
        "borderRadius": "8px",
        "boxShadow": "0 6px 18px rgba(20,48,44,.25)",
    },
}


def build_deck(result=None, *, site=None, height: int = 640) -> pdk.Deck:
    """Assemble the PyDeck ``Deck`` for the workspace map."""
    site_gdf = _site_gdf(result, site)
    return pdk.Deck(
        layers=build_map_layers(result, site=site_gdf),
        initial_view_state=view_state_for_bounds(_bounds_wgs84(site_gdf)),
        map_provider="carto",
        map_style="light",
        height=height,
        tooltip=TOOLTIP,
    )
