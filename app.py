"""Environmental Site Screener - local Streamlit workspace.

Run with::

    streamlit run app.py

This is a thin presentation layer over ``screen_site`` (the single full-screening
backend entry point). It adds no spatial logic. The reusable national datasets
are loaded once per process with ``st.cache_resource``; Flood Zones stays on its
site-bbox loader inside ``screen_site``. Map-layer visibility is a display-only
control - it re-uses the stored result and never re-runs any analysis.
"""

from __future__ import annotations

import html
import sys
import time
import warnings
from pathlib import Path

import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parent
_SRC = REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from environmental_site_screener.app_data import (  # noqa: E402
    default_data_sources,
    demo_gallery,
    friendly_repair_notice,
    friendly_site_error,
    missing_sources,
    read_geojson_site,
    rect_bounds_from_drawing,
    rectangle_site,
)
from environmental_site_screener.app_format import (  # noqa: E402
    THEME_DISPLAY,
    THEME_KEYS,
    THEME_MARKER_RGB,
    THEME_TAB_LABELS,
    ThemeCard,
    ThemeDetail,
    build_overlap_summary,
    build_theme_cards,
    build_theme_detail,
    theme_help,
)
from environmental_site_screener.app_map import (  # noqa: E402
    available_layer_control_keys,
    available_layer_controls,
    build_deck,
    legend_entries,
)
from environmental_site_screener.england import (  # noqa: E402
    CROSSES,
    ELIGIBLE,
    OUTSIDE,
    classify_site_england_eligibility,
    load_england_boundary,
)
from environmental_site_screener.screening import (  # noqa: E402
    load_screening_datasets,
    screen_site,
)
from environmental_site_screener.site import validate_site  # noqa: E402

try:  # optional: only the "Define area -> Draw on map" input needs these
    import folium  # noqa: E402
    from folium.plugins import Draw  # noqa: E402
    from streamlit_folium import st_folium  # noqa: E402

    _DRAW_MAP_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without the extra deps
    _DRAW_MAP_AVAILABLE = False

MAP_HEIGHT = 690
DRAW_MAP_HEIGHT = 330
_LAYER_KEY_PREFIX = "lyr_"

# Purely advisory: above this the app tells the user screening will take longer.
# It never blocks screening and never resizes anything - it is not a
# methodological or arbitrary site-size cap (uploads and demos are not capped
# either). The value sits above every normal development site and above the
# built-in demos except the deliberately large "Large-area screening - London"
# one; ~22,600 ha there screens in ~12 s.
LARGE_AREA_WARN_HA = 15_000.0
_LARGE_AREA_MESSAGE = (
    "This is a very large screening area and may take longer to process."
)

# Default "Define area" rectangle - a small site on the edge of Cambridge, the
# same extent as the "Urban mixed constraints - Cambridge" demo.
_DRAW_DEFAULT_BOUNDS = (0.10000, 52.20000, 0.10900, 52.20600)  # west, south, east, north
_DRAW_KEYS = ("draw_w", "draw_s", "draw_e", "draw_n")

_ENGLAND_ONLY_MESSAGE = "This tool currently supports candidate sites in England only."
_CROSSES_MESSAGE = (
    "The submitted boundary extends outside the supported England coverage."
)

# --------------------------------------------------------------------------- #
# Visual system
# --------------------------------------------------------------------------- #

# One coherent token set (colour, radius, spacing, shadow) exposed as CSS
# variables; everything below is declarative. A handful of Streamlit containers
# are targeted by stable data-testid / attribute selectors, all purely
# cosmetic - no functional control is hidden. Fonts are a web-safe system stack.
CSS = """
<style>
:root {
  /* surfaces - a whisper of sage-grey, reads neutral / geospatial */
  --ess-bg:          #f1f4f1;
  --ess-surface:     #ffffff;
  --ess-surface-2:   #f4f6f3;
  /* text - rich dark blue-green */
  --ess-ink:         #17302e;
  --ess-ink-soft:    #3d534f;
  --ess-muted:       #64756f;
  /* lines */
  --ess-border:      #e0e5df;
  --ess-border-2:    #cdd4cd;
  /* brand - stronger forest/teal, plus a lime used very sparingly */
  --ess-primary:     #1f6f5c;
  --ess-primary-dk:  #1a5f4f;
  --ess-primary-soft:#e6f0ec;
  --ess-accent:      #b6d63f;
  --ess-context:     #7a76a8;   /* slate-violet, matches the IRZ map layer */
  /* geometry */
  --ess-radius:      12px;
  --ess-radius-lg:   16px;
  --ess-shadow:      0 1px 2px rgba(20,48,44,.05), 0 12px 32px rgba(20,48,44,.07);
}

.stApp {
  background: var(--ess-bg);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
    "Helvetica Neue", Arial, "Noto Sans", system-ui, sans-serif;
}
.stApp, .stMarkdown, .stText, [data-testid="stCaptionContainer"] { color: var(--ess-ink); }
h1, h2, h3, h4, h5 { color: var(--ess-ink); letter-spacing: -0.01em; }

/* give the title room to clear Streamlit's top chrome */
[data-testid="stMainBlockContainer"], .block-container {
  padding-top: 3.2rem; padding-bottom: 3.5rem; max-width: 1620px;
}

/* ---- header ------------------------------------------------------------- */
.ess-topbar {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: 22px; flex-wrap: wrap;
}
.ess-brand { display: flex; gap: 15px; align-items: flex-start; }
/* simplified plot-boundary mark with a survey point - pure CSS, no image */
.ess-mark {
  width: 34px; height: 34px; flex: none; margin-top: 5px; position: relative;
  background: var(--ess-primary);
  clip-path: polygon(14% 6%, 92% 22%, 80% 92%, 30% 82%, 5% 44%);
  filter: drop-shadow(0 4px 10px rgba(20,48,44,.18));
}
.ess-mark::after {
  content: ""; position: absolute; left: 43%; top: 38%;
  width: 8px; height: 8px; border-radius: 999px; background: var(--ess-accent);
}
.ess-title { font-size: 1.95rem; font-weight: 700; line-height: 1.12; letter-spacing: -0.02em; }
.ess-proposition {
  font-size: 1.16rem; font-weight: 400; color: var(--ess-ink-soft); margin-top: 5px;
  max-width: 44ch;
}
.ess-subline { font-size: 0.88rem; color: var(--ess-muted); margin-top: 12px; }
.ess-pill {
  font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.11em;
  white-space: nowrap; color: var(--ess-primary); background: var(--ess-primary-soft);
  border: 1px solid #c9e2d9; padding: 6px 12px; border-radius: 999px; margin-top: 7px;
}
.ess-rule { height: 1px; background: var(--ess-border); margin: 22px 0 26px; }

/* ---- section headings (real headings, not tiny labels) ------------------- */
.ess-h { font-size: 1.16rem; font-weight: 700; color: var(--ess-ink); letter-spacing: -0.01em; }
.ess-h-sub { font-size: 0.88rem; color: var(--ess-muted); margin: 3px 0 14px; line-height: 1.5; }

/* ---- left panel: numbered progression ----------------------------------- */
.ess-step { display: flex; align-items: center; gap: 9px; margin: 18px 0 9px; }
.ess-step:first-of-type { margin-top: 6px; }
.ess-step-n {
  width: 21px; height: 21px; border-radius: 999px; flex: none;
  background: var(--ess-primary-soft); color: var(--ess-primary);
  font-size: 0.8rem; font-weight: 700; display: grid; place-items: center;
}
.ess-step-label {
  font-size: 0.8rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.08em; color: var(--ess-ink-soft);
}
.ess-facts { font-size: 0.9rem; color: var(--ess-ink-soft); line-height: 1.75; }
.ess-facts b { color: var(--ess-ink); font-weight: 600; }

/* ---- result cards ----------------------------------------------------------- */
.ess-card {
  background: var(--ess-surface); border: 1px solid var(--ess-border);
  border-left: 4px solid var(--ess-border-2); border-radius: var(--ess-radius);
  padding: 13px 15px 13px; margin-bottom: 11px; min-height: 134px;
}
.ess-card-head { display: flex; align-items: center; gap: 8px; }
.ess-card-dot {
  width: 10px; height: 10px; border-radius: 3px; flex: none;
  box-shadow: inset 0 0 0 1px rgba(0,0,0,.14);
}
.ess-card-theme { font-size: 0.94rem; font-weight: 700; color: var(--ess-ink); }
.ess-card-state { font-size: 0.86rem; font-weight: 650; margin-top: 6px; color: var(--ess-ink-soft); }
.ess-card.is-overlap .ess-card-state { color: var(--ess-primary); }
.ess-card.is-context .ess-card-state { color: #6a66a0; }
.ess-card-primary {
  font-size: 1.62rem; font-weight: 700; letter-spacing: -0.02em;
  color: var(--ess-ink); margin-top: 4px; line-height: 1.05;
}
.ess-card-secondary { font-size: 0.88rem; color: var(--ess-ink-soft); margin-top: 2px; }
.ess-card-context { font-size: 0.82rem; color: var(--ess-muted); margin-top: 7px; }

/* ---- "Mapped overlap by theme" bars ------------------------------------- */
.ess-bars { margin: 2px 0 20px; }
.ess-bars-title { font-size: 0.96rem; font-weight: 700; color: var(--ess-ink); margin-bottom: 11px; }
.ess-bar-row {
  display: grid; grid-template-columns: 138px 1fr 50px; align-items: center;
  gap: 11px; margin: 7px 0;
}
.ess-bar-label { font-size: 0.86rem; color: var(--ess-ink-soft); }
.ess-bar-track {
  height: 9px; border-radius: 999px; background: var(--ess-surface-2);
  border: 1px solid var(--ess-border); overflow: hidden;
}
.ess-bar-fill { display: block; height: 100%; border-radius: 999px; }
.ess-bar-val { font-size: 0.86rem; font-weight: 650; color: var(--ess-ink); text-align: right; }
.ess-bars-irz { font-size: 0.86rem; color: var(--ess-ink-soft); margin: 12px 0 4px; }
.ess-bars-irz i {
  width: 10px; height: 10px; border-radius: 3px; display: inline-block;
  margin-right: 7px; vertical-align: middle; box-shadow: inset 0 0 0 1px rgba(0,0,0,.14);
}
.ess-bars-note { font-size: 0.82rem; color: var(--ess-muted); margin-top: 7px; line-height: 1.5; }

/* ---- map frame + legend -------------------------------------------------- */
[data-testid="stDeckGlJsonChart"], [data-testid="stDeckGlChart"], .stDeckGlJsonChart {
  border: 1px solid var(--ess-border-2); border-radius: var(--ess-radius-lg);
  overflow: hidden; box-shadow: var(--ess-shadow);
}
.ess-legend {
  display: flex; flex-wrap: wrap; gap: 7px 18px;
  margin-top: 12px; font-size: 0.85rem; color: var(--ess-ink-soft);
}
.ess-legend span { display: inline-flex; align-items: center; gap: 7px; }
.ess-legend i {
  width: 11px; height: 11px; border-radius: 3px; display: inline-block;
  box-shadow: inset 0 0 0 1px rgba(0,0,0,.08);
}

/* ---- "Explore results" panels ---------------------------------------------- */
.ess-detail-headline { font-size: 1.05rem; font-weight: 650; color: var(--ess-ink); margin: 2px 0 9px; }
.ess-metric-lead { font-size: 1.06rem; font-weight: 600; color: var(--ess-ink); margin: 1px 0; }
.ess-metric { font-size: 0.92rem; color: var(--ess-ink-soft); margin: 1px 0; }
.ess-means {
  background: var(--ess-primary-soft); border: 1px solid #d3e6df;
  border-radius: 10px; padding: 11px 13px; margin: 12px 0 14px;
  font-size: 0.92rem; color: var(--ess-ink-soft); line-height: 1.5;
}
.ess-means b {
  display: block; font-size: 0.7rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.1em; color: var(--ess-primary); margin-bottom: 4px;
}

/* ---- containment: the two side columns read as raised panels ------------- */
[data-testid="stVerticalBlockBorderWrapper"] {
  border-color: var(--ess-border); border-radius: var(--ess-radius-lg);
  background: var(--ess-surface); box-shadow: var(--ess-shadow);
}

/* ---- controls -------------------------------------------------------------- */
.stButton > button[kind="primary"] {
  background: var(--ess-primary); border: 1px solid var(--ess-primary);
  border-radius: 10px; font-weight: 650; box-shadow: var(--ess-shadow);
}
.stButton > button[kind="primary"]:hover {
  background: var(--ess-primary-dk); border-color: var(--ess-primary-dk);
}
.stButton > button[kind="primary"]:focus { box-shadow: 0 0 0 3px var(--ess-primary-soft); }
.stTabs [data-baseweb="tab-list"] { gap: 3px; border-bottom: 1px solid var(--ess-border); }
.stTabs [data-baseweb="tab"] { font-size: 0.9rem; font-weight: 600; color: var(--ess-muted); }
.stTabs [aria-selected="true"] { color: var(--ess-ink) !important; }
.stTabs [data-baseweb="tab-highlight"] { background: var(--ess-accent) !important; height: 3px; }

/* helper / caption text - keep it a clear step below body, still legible */
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {
  font-size: 0.84rem; color: var(--ess-muted); line-height: 1.5;
}
/* provenance / limitations body - one comfortable step below body copy */
[data-testid="stExpanderDetails"] .stMarkdown p,
[data-testid="stExpanderDetails"] .stMarkdown li { font-size: 0.9rem; line-height: 1.6; }
</style>
"""

PROVENANCE_MD = """
**Sources.** Natural England - Sites of Special Scientific Interest, SSSI Impact
Risk Zones, Priority Habitats Inventory, Ancient Woodland (revised and legacy).
Environment Agency - Flood Map for Planning, Flood Zones 2 and 3 (rivers and
sea). Ordnance Survey - Boundary-Line ceremonial counties, used for the
project-inferred revised Ancient Woodland coverage and for the England-only
product boundary that limits which candidate sites can be screened.

**Method.** All overlap, area and distance work is done in EPSG:27700 (British
National Grid). Areas are hectares (m² / 10,000); percentages are of the
submitted site area; nearest distance is edge to edge.

**This is preliminary desktop screening.** It identifies *mapped* environmental
constraints and sensitivities that may warrant further investigation. It is not
an environmental assessment, ecological survey, planning judgement or
Biodiversity Net Gain calculation, and it produces no overall score or
pass/fail.

**Dataset limitations.**
- Coverage is England only. A candidate site must lie fully within England to be
  screened; sites outside or straddling the border are shown on the map but not
  screened, because the datasets above stop at the border.
- SSSI Impact Risk Zones are contextual - an intersection is not an adverse
  result; relevance depends on the proposed development.
- Priority Habitats: not every inventory polygon is priority habitat; context
  classes are reported separately.
- Ancient Woodland: revised-inventory coverage uses a documented,
  project-inferred completed-county list, not a Natural England coverage layer.
- Flood Zones cover river and sea flooding only. They ignore the benefit of
  flood defences and do not represent surface water, groundwater or drainage
  flooding. Flood Zone 1 is not mapped. Some areas retain earlier data pending
  revision.
- Mapped datasets may have omissions and are revised over time.
"""


# --------------------------------------------------------------------------- #
# Cached dataset loading
# --------------------------------------------------------------------------- #


@st.cache_resource(show_spinner=False)
def get_datasets():
    """Load the reusable national layers once per Streamlit process."""
    sources = default_data_sources(REPO_ROOT)
    return load_screening_datasets(**{key: str(path) for key, path in sources.items()})


@st.cache_resource(show_spinner=False)
def get_england_boundary():
    """Load the England product boundary once (cheap - one shapefile, no gpkgs)."""
    sources = default_data_sources(REPO_ROOT)
    return load_england_boundary(sources["revised_coverage_path"])


# --------------------------------------------------------------------------- #
# Rendering helpers
# --------------------------------------------------------------------------- #


def render_header() -> None:
    st.markdown(
        '<div class="ess-topbar">'
        '<div class="ess-brand">'
        '<div class="ess-mark"></div>'
        "<div>"
        '<div class="ess-title">Environmental Site Screener</div>'
        '<div class="ess-proposition">Understand the mapped environmental '
        "constraints around a proposed site in England.</div>"
        "</div></div>"
        '<span class="ess-pill">Desktop screening &middot; England</span>'
        "</div>"
        '<div class="ess-subline">Preliminary desktop screening against Natural '
        "England and Environment Agency datasets &mdash; not an environmental "
        "assessment or a planning decision.</div>"
        '<div class="ess-rule"></div>',
        unsafe_allow_html=True,
    )


def render_section(title: str, sub: str) -> None:
    st.markdown(
        f'<div class="ess-h">{html.escape(title)}</div>'
        f'<div class="ess-h-sub">{html.escape(sub)}</div>',
        unsafe_allow_html=True,
    )


def render_step(number: int, label: str) -> None:
    st.markdown(
        f'<div class="ess-step"><span class="ess-step-n">{number}</span>'
        f'<span class="ess-step-label">{html.escape(label)}</span></div>',
        unsafe_allow_html=True,
    )


def render_card(card: ThemeCard) -> None:
    tone_class = {"overlap": "is-overlap", "context": "is-context", "none": "is-none"}[
        card.tone
    ]
    r, g, b = card.marker_rgb
    parts = [
        f'<div class="ess-card {tone_class}" style="border-left-color: rgb({r},{g},{b})">',
        '<div class="ess-card-head">',
        f'<span class="ess-card-dot" style="background: rgb({r},{g},{b})"></span>',
        f'<span class="ess-card-theme">{html.escape(card.theme)}</span>',
        "</div>",
        f'<div class="ess-card-state">{html.escape(card.state_label)}</div>',
    ]
    if card.primary_metric:
        parts.append(f'<div class="ess-card-primary">{html.escape(card.primary_metric)}</div>')
    if card.secondary_metric:
        parts.append(
            f'<div class="ess-card-secondary">{html.escape(card.secondary_metric)}</div>'
        )
    if card.context_line:
        parts.append(f'<div class="ess-card-context">{html.escape(card.context_line)}</div>')
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def render_legend(entries) -> None:
    if not entries:
        return
    chips = "".join(
        f'<span><i style="background: rgb({r}, {g}, {b})"></i>{html.escape(label)}</span>'
        for label, (r, g, b) in entries
    )
    st.markdown(f'<div class="ess-legend">{chips}</div>', unsafe_allow_html=True)


def render_overlap_summary(summary) -> None:
    """Four independent per-theme overlap bars plus the IRZ context line.

    Not a pie/donut: the themes can spatially overlap each other, so the bars are
    independent percentages of the candidate site and are never summed.
    """
    parts = [
        '<div class="ess-bars">',
        '<div class="ess-bars-title">Mapped overlap by theme</div>',
    ]
    for bar in summary.bars:
        r, g, b = bar.marker_rgb
        width = max(0.0, min(100.0, bar.fill_fraction * 100.0))
        parts.append(
            '<div class="ess-bar-row">'
            f'<span class="ess-bar-label">{html.escape(bar.theme)}</span>'
            '<span class="ess-bar-track">'
            f'<span class="ess-bar-fill" style="width: {width:.2f}%; '
            f'background: rgb({r},{g},{b})"></span></span>'
            f'<span class="ess-bar-val">{html.escape(bar.pct_label)}</span>'
            "</div>"
        )
    ri, gi, bi = THEME_MARKER_RGB["irz"]
    parts.append(
        f'<div class="ess-bars-irz"><i style="background: rgb({ri},{gi},{bi})"></i>'
        f"SSSI Impact Risk Zone &middot; {html.escape(summary.irz_label)}</div>"
    )
    parts.append(f'<div class="ess-bars-note">{html.escape(summary.note)}</div>')
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def render_detail(detail: ThemeDetail) -> None:
    st.markdown(
        f'<div class="ess-detail-headline">{html.escape(detail.headline)}</div>',
        unsafe_allow_html=True,
    )
    for index, metric in enumerate(detail.metrics):
        css = "ess-metric-lead" if index == 0 else "ess-metric"
        st.markdown(f'<div class="{css}">{html.escape(metric)}</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="ess-means"><b>What this means</b>{html.escape(detail.what_it_means)}</div>',
        unsafe_allow_html=True,
    )
    for table in detail.tables:
        if table.rows:
            st.markdown(f"**{table.title}**")
            st.dataframe(pd.DataFrame(list(table.rows)), width="stretch", hide_index=True)
    if detail.links:
        st.markdown("**Advice links**")
        for url in detail.links:
            st.markdown(f"- [{url}]({url})")
    if detail.note:
        st.caption(detail.note)


def render_site_facts(raw, validated, repair_messages) -> None:
    area_m2 = float(validated.geometry.iloc[0].area)
    area_ha = area_m2 / 10_000
    in_epsg = raw.crs.to_epsg() if raw.crs is not None else None
    lines = [
        "<b>Boundary</b> &nbsp;valid single polygon",
        f"<b>Area</b> &nbsp;{area_ha:,.2f} ha &nbsp;({area_m2:,.0f} m&sup2;)",
        "<b>Analysis grid</b> &nbsp;British National Grid (EPSG:27700)",
    ]
    if in_epsg is not None and in_epsg != 27700:
        lines.append(f"<b>Reprojected from</b> &nbsp;EPSG:{in_epsg}")
    st.markdown(
        '<div class="ess-facts">' + "<br/>".join(lines) + "</div>",
        unsafe_allow_html=True,
    )
    notice = friendly_repair_notice(repair_messages)
    if notice:
        st.warning(notice)
        with st.expander("Technical detail"):
            for message in repair_messages:
                st.caption(message)


# --------------------------------------------------------------------------- #
# Left panel: candidate site
# --------------------------------------------------------------------------- #


def _ensure_draw_defaults() -> None:
    """Seed the shared West/South/East/North state used by both Define-area modes."""
    for key, value in zip(_DRAW_KEYS, _DRAW_DEFAULT_BOUNDS):
        st.session_state.setdefault(key, float(value))


def _current_draw_bounds() -> tuple[float, float, float, float]:
    """The current ``(west, south, east, north)`` from session state."""
    return tuple(float(st.session_state[key]) for key in _DRAW_KEYS)


def _apply_draw_bounds(bounds) -> bool:
    """Write ``(w, s, e, n)`` into session state; return ``True`` if anything moved.

    Values are rounded to the 5 dp the coordinate inputs display, so re-reading
    the same drawn rectangle on the next run is a no-op (no rerun loop).
    """
    changed = False
    for key, value in zip(_DRAW_KEYS, bounds):
        rounded = round(float(value), 5)
        if abs(rounded - round(float(st.session_state.get(key, 0.0)), 5)) > 1e-9:
            st.session_state[key] = rounded
            changed = True
    return changed


def _coordinate_inputs() -> None:
    col_w, col_e = st.columns(2)
    col_w.number_input("West longitude", format="%.5f", step=0.001, key="draw_w")
    col_e.number_input("East longitude", format="%.5f", step=0.001, key="draw_e")
    col_s, col_n = st.columns(2)
    col_s.number_input("South latitude", format="%.5f", step=0.001, key="draw_s")
    col_n.number_input("North latitude", format="%.5f", step=0.001, key="draw_n")


def _draw_map() -> None:
    """Small Leaflet drawing surface: draw / drag / resize one rectangle.

    Any new rectangle is folded back into the shared coordinate state and the
    script reruns so the rest of the panel and the PyDeck result map pick it up.
    Screening still happens only when the user clicks *Screen site*.
    """
    west, south, east, north = _current_draw_bounds()
    generation = st.session_state.setdefault("draw_map_gen", 0)

    fmap = folium.Map(
        location=[(south + north) / 2.0, (west + east) / 2.0],
        zoom_start=12,
        tiles="CartoDB positron",
        control_scale=True,
    )
    folium.Rectangle(
        bounds=[[south, west], [north, east]],
        color="#1f6f5c",
        weight=2,
        fill=True,
        fill_opacity=0.12,
    ).add_to(fmap)
    Draw(
        draw_options={
            "polyline": False,
            "polygon": False,
            "circle": False,
            "circlemarker": False,
            "marker": False,
            "rectangle": {"shapeOptions": {"color": "#1f6f5c"}},
        },
        edit_options={"edit": True, "remove": True},
    ).add_to(fmap)

    out = st_folium(
        fmap,
        key=f"draw_map_{generation}",
        height=DRAW_MAP_HEIGHT,
        use_container_width=True,
        returned_objects=["all_drawings"],
    )
    st.caption(
        "Draw a rectangle, then drag or resize it with the edit tool. Only one "
        "rectangle is used - the most recent. Fine-tune the exact numbers below."
    )

    drawings = (out or {}).get("all_drawings") or []
    if drawings:
        bounds = rect_bounds_from_drawing(drawings[-1])
        if bounds is not None and _apply_draw_bounds(bounds):
            # Bump the widget key so Leaflet's own drawn layer is cleared and only
            # the authoritative folium.Rectangle remains on the next run.
            st.session_state["draw_map_gen"] = generation + 1
            st.rerun()


def _site_source_input(source):
    """Return ``(raw_gdf, error_str)`` for the chosen candidate-site source."""
    if source == "Demo site":
        gallery = demo_gallery()
        labels = [site.label for site in gallery]
        chosen = st.selectbox("Example site", labels, key="demo_choice")
        site = next(s for s in gallery if s.label == chosen)
        st.caption(f"{site.blurb} Fictional demo boundary - not a real proposed development.")
        return site.geodataframe(), None

    if source == "Define area":
        _ensure_draw_defaults()
        if _DRAW_MAP_AVAILABLE:
            mode = st.radio(
                "Define area mode",
                ["Draw on map", "Enter coordinates"],
                horizontal=True,
                label_visibility="collapsed",
                key="draw_mode",
            )
        else:
            mode = "Enter coordinates"

        if mode == "Draw on map":
            _draw_map()
            with st.expander("Fine-tune coordinates (WGS84 decimal degrees)"):
                _coordinate_inputs()
        else:
            st.caption(
                "One rectangle in decimal degrees (WGS84), e.g. from a web map. "
                "West/South is the bottom-left corner, East/North the top-right."
            )
            _coordinate_inputs()

        west, south, east, north = _current_draw_bounds()
        try:
            return rectangle_site(west, south, east, north), None
        except ValueError as exc:
            return None, str(exc)

    upload = st.file_uploader(
        "GeoJSON site boundary", type=["geojson", "json"], accept_multiple_files=False
    )
    if upload is not None:
        try:
            return read_geojson_site(upload.getvalue()), None
        except ValueError as exc:
            return None, str(exc)
    st.caption("Upload a single-polygon GeoJSON boundary.")
    return None, None


def _report_site_error(message: str) -> None:
    headline, detail = friendly_site_error(message)
    st.error(headline)
    if detail and detail != headline:
        with st.expander("Technical detail"):
            st.caption(detail)


def site_panel(england_boundary):
    """Render the site controls.

    Returns ``(raw_gdf, validated_gdf, display_gdf, error_str)``:

    * ``validated_gdf`` - a screenable site in EPSG:27700, or ``None`` if the
      boundary failed validation, is outside England, or crosses the England
      boundary. A very large area is still screenable (advisory note only).
    * ``display_gdf`` - a boundary to keep on the map even though it cannot be
      screened (an outside/crossing site), or ``None``.
    """
    render_section(
        "Candidate site",
        "Choose a demo, upload a GeoJSON boundary, or define a rectangle to screen.",
    )

    render_step(1, "Choose a site")
    source = st.radio(
        "Site source",
        ["Demo site", "Upload GeoJSON", "Define area"],
        horizontal=True,
        label_visibility="collapsed",
    )
    raw, error = _site_source_input(source)

    render_step(2, "Check boundary")
    validated = None
    display_site = None
    repair_messages: list[str] = []
    if raw is not None and error is None:
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                validated = validate_site(raw)
            repair_messages = [
                str(w.message) for w in caught if issubclass(w.category, UserWarning)
            ]
        except (TypeError, ValueError) as exc:
            error = str(exc)

    eligibility = None
    large_area_ha = None
    if validated is not None:
        eligibility = classify_site_england_eligibility(validated, england_boundary)
        area_ha = float(validated.geometry.iloc[0].area) / 10_000
        if area_ha > LARGE_AREA_WARN_HA:
            large_area_ha = area_ha
        if eligibility != ELIGIBLE:
            display_site = validated  # keep it on the map, but not screenable
            validated = None

    if error:
        _report_site_error(error)
    elif eligibility == OUTSIDE:
        st.error(f"{_ENGLAND_ONLY_MESSAGE} This boundary is entirely outside England.")
        st.caption("The boundary is still shown on the map, but it cannot be screened.")
    elif eligibility == CROSSES:
        st.error(f"{_CROSSES_MESSAGE} Part of it lies outside England.")
        st.caption(
            "The boundary is still shown on the map. Screening needs a site fully "
            "within England - it is not clipped to the English part."
        )
    elif validated is not None:
        render_site_facts(raw, validated, repair_messages)
        if large_area_ha is not None:
            st.info(f"{_LARGE_AREA_MESSAGE} (about {large_area_ha:,.0f} ha)")
    else:
        st.caption("Waiting for a site boundary.")

    render_step(3, "Run screening")
    return raw, validated, display_site, error


def run_screening(validated) -> None:
    """Load datasets (first run only), screen the site, stash the result, rerun."""
    try:
        with st.spinner("Preparing environmental datasets - first run only (~40 s)…"):
            datasets = get_datasets()
    except Exception as exc:  # surface the real failure, do not hide it
        st.session_state.pop("result", None)
        st.error(f"Could not load the environmental datasets: {exc}")
        return

    with st.spinner("Screening candidate site…"):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            started = time.perf_counter()
            result = screen_site(validated, datasets)
            elapsed = time.perf_counter() - started

    new_bounds = _bounds_key(validated)
    # A screening for a *different* boundary starts from a clean map: otherwise a
    # layer the user hid for the previous site would silently hide it here too.
    # (Re-screening the same site keeps the user's layer choices.)
    if new_bounds != st.session_state.get("result_site_bounds"):
        _clear_layer_visibility(st.session_state, available_layer_control_keys(result))

    st.session_state["result"] = result
    st.session_state["elapsed"] = elapsed
    st.session_state["result_site_bounds"] = new_bounds
    st.session_state["screen_warnings"] = [
        str(w.message) for w in caught if issubclass(w.category, UserWarning)
    ]
    st.rerun()


def _bounds_key(validated):
    """A stable fingerprint of the validated site, to detect a changed site."""
    return tuple(round(float(v), 3) for v in validated.total_bounds)


def _clear_layer_visibility(session_state, control_keys) -> None:
    """Forget stored layer-toggle state so the next result starts fully visible.

    Takes the state mapping explicitly (``st.session_state`` in the app) so it is
    testable without a Streamlit context. Only ``lyr_<control key>`` entries are
    removed; the stored result and other state are left untouched.
    """
    for control_key in control_keys:
        session_state.pop(f"{_LAYER_KEY_PREFIX}{control_key}", None)


# --------------------------------------------------------------------------- #
# Centre: map + layer visibility
# --------------------------------------------------------------------------- #


def _ensure_layer_defaults(result) -> list[str]:
    """Seed every available layer toggle to visible on first sight; return keys."""
    control_keys = available_layer_control_keys(result)
    for key in control_keys:
        st.session_state.setdefault(f"{_LAYER_KEY_PREFIX}{key}", True)
    return control_keys


def _visible_layer_keys(control_keys) -> set[str]:
    """The currently-checked layer control keys, from session state."""
    return {
        key for key in control_keys if st.session_state.get(f"{_LAYER_KEY_PREFIX}{key}")
    }


def layer_controls(result, control_keys) -> None:
    """The 'Map layers' popover: show all / site only, plus one toggle per layer."""
    with st.popover("Map layers", width="content"):
        st.caption("Display only - the candidate site is always shown.")
        if st.button("Show all layers", width="stretch", key="lyr_show_all"):
            for key in control_keys:
                st.session_state[f"{_LAYER_KEY_PREFIX}{key}"] = True
            st.rerun()
        if st.button("Site only", width="stretch", key="lyr_site_only"):
            for key in control_keys:
                st.session_state[f"{_LAYER_KEY_PREFIX}{key}"] = False
            st.rerun()
        for key, label, _rgb in available_layer_controls(result):
            st.checkbox(label, key=f"{_LAYER_KEY_PREFIX}{key}")


def render_map(result, validated, display_site, stale) -> None:
    render_section(
        "Site map",
        "Explore mapped environmental results around the candidate boundary.",
    )
    if result is not None:
        control_keys = _ensure_layer_defaults(result)
        layer_controls(result, control_keys)
        visible = _visible_layer_keys(control_keys)
        st.pydeck_chart(build_deck(result, height=MAP_HEIGHT, visible=visible))
        render_legend(legend_entries(result, visible=visible))
    elif validated is not None:
        st.pydeck_chart(build_deck(site=validated, height=MAP_HEIGHT))
        render_legend(legend_entries(site=validated))
        if stale:
            st.info("Candidate site changed - screen the site again to update results.")
    elif display_site is not None:
        # An outside-England / boundary-crossing / oversized site: shown for
        # orientation, but screening is blocked (see the Candidate site panel).
        st.pydeck_chart(build_deck(site=display_site, height=MAP_HEIGHT))
        render_legend(legend_entries(site=display_site))
        st.info("This boundary can't be screened - see the Candidate site panel.")
    else:
        if stale:
            st.info("No candidate site selected - the previous screening no longer applies.")
        else:
            st.info("Choose a demo site, upload a boundary, or define an area, then screen it.")


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #


def main() -> None:
    st.set_page_config(
        page_title="Environmental Site Screener",
        page_icon="🛰️",
        layout="wide",
    )
    st.markdown(CSS, unsafe_allow_html=True)
    render_header()

    sources = default_data_sources(REPO_ROOT)
    absent = missing_sources(sources)
    if absent:
        st.error(
            "Local environmental source data is missing. These files are expected "
            "under `data/raw/`:\n\n"
            + "\n".join(f"- `{path.relative_to(REPO_ROOT)}`" for path in absent)
            + "\n\nAdd the raw datasets and reload."
        )
        st.stop()

    england_boundary = get_england_boundary()

    left, centre, right = st.columns([18, 62, 20], gap="large")

    with left:
        with st.container(border=True):
            _, validated, display_site, _ = site_panel(england_boundary)
            run_clicked = st.button(
                "Screen site",
                type="primary",
                width="stretch",
                disabled=validated is None,
            )

    result = st.session_state.get("result")
    # The stored result only describes the site it was screened for. Drop it from
    # the view if the current candidate boundary is different, or if there is no
    # valid candidate boundary right now (e.g. switched to Upload with no file) -
    # otherwise the old result reads as though it applies to the new selection.
    stale = result is not None and (
        validated is None
        or _bounds_key(validated) != st.session_state.get("result_site_bounds")
    )
    if stale:
        result = None

    with centre:
        render_map(result, validated, display_site, stale)

    with right:
        with st.container(border=True):
            render_section(
                "Screening results", "Five environmental themes checked for this site."
            )
            with st.popover("About the five themes", width="stretch"):
                for key in THEME_KEYS:
                    st.markdown(f"**{THEME_DISPLAY[key]}** — {theme_help(key)}")
            if result is not None:
                for card in build_theme_cards(result):
                    render_card(card)
                warned = len(st.session_state.get("screen_warnings", []))
                elapsed = st.session_state.get("elapsed")
                if elapsed is not None:
                    note = f"Screened in {elapsed:.1f} s"
                    if warned:
                        note += f" · {warned} source geometry warning(s)"
                    st.caption(note)
            else:
                st.markdown(
                    '<div class="ess-facts">Screen the site to see the mapped '
                    "environmental constraints for the candidate boundary.</div>",
                    unsafe_allow_html=True,
                )

    if run_clicked and validated is not None:
        run_screening(validated)

    if result is not None:
        render_section(
            "Explore results",
            "Detailed results, mapped evidence and source information for each "
            "environmental theme.",
        )
        render_overlap_summary(build_overlap_summary(result))
        for tab, key in zip(st.tabs(list(THEME_TAB_LABELS)), THEME_KEYS):
            with tab:
                render_detail(build_theme_detail(result, key))

    st.markdown('<div class="ess-rule" style="margin-top: 28px"></div>', unsafe_allow_html=True)
    with st.expander("Data sources and limitations"):
        st.markdown(PROVENANCE_MD)


if __name__ == "__main__":
    main()
