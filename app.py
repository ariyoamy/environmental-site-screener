"""Environmental Site Screener - local Streamlit workspace.

Run with::

    streamlit run app.py

This is a thin presentation layer over ``screen_site`` (the single full-screening
backend entry point). It adds no spatial logic. The reusable national datasets
are loaded once per process with ``st.cache_resource``; Flood Zones stays on its
site-bbox loader inside ``screen_site``.
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
    DEMO_SITE_LABEL,
    default_data_sources,
    demo_site,
    missing_sources,
    read_geojson_site,
)
from environmental_site_screener.app_format import (  # noqa: E402
    THEME_DISPLAY,
    THEME_KEYS,
    THEME_TAB_LABELS,
    ThemeCard,
    ThemeDetail,
    build_theme_cards,
    build_theme_detail,
    theme_help,
)
from environmental_site_screener.app_map import build_deck, legend_entries  # noqa: E402
from environmental_site_screener.screening import (  # noqa: E402
    load_screening_datasets,
    screen_site,
)
from environmental_site_screener.site import validate_site  # noqa: E402

MAP_HEIGHT = 640

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
  /* surfaces - warm, not cold grey */
  --ess-bg:          #fbfaf5;
  --ess-surface:     #ffffff;
  --ess-surface-2:   #f5f3ea;
  /* text - rich dark blue-green */
  --ess-ink:         #17302e;
  --ess-ink-soft:    #3d534f;
  --ess-muted:       #6b7c77;
  /* lines */
  --ess-border:      #e6e2d6;
  --ess-border-2:    #d9d3c4;
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
  padding-top: 3.2rem; padding-bottom: 3.5rem; max-width: 1600px;
}

/* ---- header ------------------------------------------------------------- */
.ess-topbar {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: 22px; flex-wrap: wrap;
}
.ess-brand { display: flex; gap: 15px; align-items: flex-start; }
.ess-mark {
  width: 40px; height: 40px; border-radius: 11px; flex: none; margin-top: 4px;
  background: linear-gradient(140deg, var(--ess-primary) 0%, #2f8f6f 58%,
    var(--ess-accent) 150%);
  box-shadow: var(--ess-shadow);
}
.ess-title { font-size: 1.95rem; font-weight: 700; line-height: 1.12; letter-spacing: -0.02em; }
.ess-proposition {
  font-size: 1.16rem; font-weight: 400; color: var(--ess-ink-soft); margin-top: 5px;
  max-width: 44ch;
}
.ess-subline { font-size: 0.82rem; color: var(--ess-muted); margin-top: 12px; }
.ess-pill {
  font-size: 0.66rem; text-transform: uppercase; letter-spacing: 0.12em;
  white-space: nowrap; color: var(--ess-primary); background: var(--ess-primary-soft);
  border: 1px solid #c9e2d9; padding: 6px 12px; border-radius: 999px; margin-top: 7px;
}
.ess-rule { height: 1px; background: var(--ess-border); margin: 20px 0 24px; }

/* ---- section labels -------------------------------------------------------- */
.ess-eyebrow {
  font-size: 0.7rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.12em; color: var(--ess-muted); margin: 0 0 12px;
}

/* ---- left panel: numbered progression ------------------------------------- */
.ess-step { display: flex; align-items: center; gap: 9px; margin: 20px 0 9px; }
.ess-step:first-of-type { margin-top: 4px; }
.ess-step-n {
  width: 20px; height: 20px; border-radius: 999px; flex: none;
  background: var(--ess-primary-soft); color: var(--ess-primary);
  font-size: 0.72rem; font-weight: 700; display: grid; place-items: center;
}
.ess-step-label {
  font-size: 0.72rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.09em; color: var(--ess-muted);
}
.ess-facts { font-size: 0.83rem; color: var(--ess-muted); line-height: 1.7; }
.ess-facts b { color: var(--ess-ink); font-weight: 600; }

/* ---- result cards ------------------------------------------------------- */
.ess-card {
  background: var(--ess-surface); border: 1px solid var(--ess-border);
  border-left: 3px solid var(--ess-border-2); border-radius: var(--ess-radius);
  padding: 14px 15px 13px; margin-bottom: 11px; min-height: 132px;
}
.ess-card.is-overlap { border-left-color: var(--ess-primary); }
.ess-card.is-context { border-left-color: var(--ess-context); }
.ess-card-theme {
  font-size: 0.65rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.11em; color: var(--ess-muted);
}
.ess-card-state { font-size: 0.92rem; font-weight: 650; margin-top: 5px; color: var(--ess-ink); }
.ess-card.is-overlap .ess-card-state { color: var(--ess-primary); }
.ess-card.is-context .ess-card-state { color: #6a66a0; }
.ess-card-primary {
  font-size: 1.6rem; font-weight: 700; letter-spacing: -0.02em;
  color: var(--ess-ink); margin-top: 5px; line-height: 1.05;
}
.ess-card-secondary { font-size: 0.82rem; color: var(--ess-ink-soft); margin-top: 2px; }
.ess-card-context { font-size: 0.75rem; color: var(--ess-muted); margin-top: 7px; }

/* ---- map frame ---------------------------------------------------------- */
[data-testid="stDeckGlJsonChart"], [data-testid="stDeckGlChart"], .stDeckGlJsonChart {
  border: 1px solid var(--ess-border-2); border-radius: var(--ess-radius-lg);
  overflow: hidden; box-shadow: var(--ess-shadow);
}
.ess-legend {
  display: flex; flex-wrap: wrap; gap: 7px 18px;
  margin-top: 13px; font-size: 0.78rem; color: var(--ess-muted);
}
.ess-legend span { display: inline-flex; align-items: center; gap: 7px; }
.ess-legend i {
  width: 11px; height: 11px; border-radius: 3px; display: inline-block;
  box-shadow: inset 0 0 0 1px rgba(0,0,0,.08);
}

/* ---- "Explore results" panels ---------------------------------------------- */
.ess-detail-headline { font-size: 1.03rem; font-weight: 650; color: var(--ess-ink); margin: 2px 0 9px; }
.ess-metric-lead { font-size: 1.05rem; font-weight: 600; color: var(--ess-ink); margin: 1px 0; }
.ess-metric { font-size: 0.86rem; color: var(--ess-muted); margin: 1px 0; }
.ess-means {
  background: var(--ess-primary-soft); border: 1px solid #d3e6df;
  border-radius: 10px; padding: 11px 13px; margin: 12px 0 14px;
  font-size: 0.86rem; color: var(--ess-ink-soft); line-height: 1.5;
}
.ess-means b {
  display: block; font-size: 0.62rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.11em; color: var(--ess-primary); margin-bottom: 4px;
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
.stTabs [data-baseweb="tab"] { font-size: 0.85rem; font-weight: 600; color: var(--ess-muted); }
.stTabs [aria-selected="true"] { color: var(--ess-ink) !important; }
.stTabs [data-baseweb="tab-highlight"] { background: var(--ess-accent) !important; height: 3px; }
</style>
"""

PROVENANCE_MD = """
**Sources.** Natural England - Sites of Special Scientific Interest, SSSI Impact
Risk Zones, Priority Habitats Inventory, Ancient Woodland (revised and legacy).
Environment Agency - Flood Map for Planning, Flood Zones 2 and 3 (rivers and
sea). Ordnance Survey - Boundary-Line ceremonial counties, used only for the
project-inferred revised Ancient Woodland coverage.

**Method.** All overlap, area and distance work is done in EPSG:27700 (British
National Grid). Areas are hectares (m² / 10,000); percentages are of the
submitted site area; nearest distance is edge to edge.

**This is preliminary desktop screening.** It identifies *mapped* environmental
constraints and sensitivities that may warrant further investigation. It is not
an environmental assessment, ecological survey, planning judgement or
Biodiversity Net Gain calculation, and it produces no overall score or
pass/fail.

**Dataset limitations.**
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
    parts = [
        f'<div class="ess-card {tone_class}">',
        f'<div class="ess-card-theme">{html.escape(card.theme)}</div>',
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
    for message in repair_messages:
        st.warning(message)


# --------------------------------------------------------------------------- #
# Left panel: candidate site
# --------------------------------------------------------------------------- #


def site_panel():
    """Render the site controls; return ``(raw_gdf, validated_gdf, error_str)``."""
    st.markdown('<div class="ess-eyebrow">Candidate site</div>', unsafe_allow_html=True)

    render_step(1, "Choose a site")
    source = st.radio(
        "Site source",
        ["Demo site", "Upload GeoJSON"],
        horizontal=True,
        label_visibility="collapsed",
    )

    raw = None
    error = None

    if source == "Demo site":
        raw = demo_site()
        st.caption(f"{DEMO_SITE_LABEL}. Already selected - no upload needed.")
    else:
        upload = st.file_uploader(
            "GeoJSON site boundary", type=["geojson", "json"], accept_multiple_files=False
        )
        if upload is not None:
            try:
                raw = read_geojson_site(upload.getvalue())
            except ValueError as exc:
                error = str(exc)
        else:
            st.caption("Upload a single-polygon GeoJSON boundary.")

    render_step(2, "Check boundary")
    validated = None
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

    if error:
        st.error(f"This site could not be validated: {error}")
    elif validated is not None:
        render_site_facts(raw, validated, repair_messages)
    else:
        st.caption("Waiting for a site boundary.")

    render_step(3, "Run screening")
    return raw, validated, error


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

    st.session_state["result"] = result
    st.session_state["elapsed"] = elapsed
    st.session_state["result_site_bounds"] = _bounds_key(validated)
    st.session_state["screen_warnings"] = [
        str(w.message) for w in caught if issubclass(w.category, UserWarning)
    ]
    st.rerun()


def _bounds_key(validated):
    """A stable fingerprint of the validated site, to detect a changed site."""
    return tuple(round(float(v), 3) for v in validated.total_bounds)


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

    left, centre, right = st.columns([20, 58, 22], gap="large")

    with left:
        _, validated, _ = site_panel()
        run_clicked = st.button(
            "Screen site",
            type="primary",
            width="stretch",
            disabled=validated is None,
        )

    result = st.session_state.get("result")
    # If the user has since loaded a different valid site, the stored result no
    # longer describes it - fall back to the site-only map until they re-run.
    stale = (
        result is not None
        and validated is not None
        and _bounds_key(validated) != st.session_state.get("result_site_bounds")
    )
    if stale:
        result = None

    with centre:
        st.markdown('<div class="ess-eyebrow">Map</div>', unsafe_allow_html=True)
        if result is not None:
            st.pydeck_chart(build_deck(result, height=MAP_HEIGHT))
            render_legend(legend_entries(result))
        elif validated is not None:
            st.pydeck_chart(build_deck(site=validated, height=MAP_HEIGHT))
            render_legend(legend_entries(site=validated))
            if stale:
                st.info("Candidate site changed - screen the site again to update results.")
        else:
            st.info("Add a candidate site to begin.")

    with right:
        st.markdown(
            '<div class="ess-eyebrow">Environmental screening</div>',
            unsafe_allow_html=True,
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
        st.markdown(
            '<div class="ess-eyebrow" style="margin-top: 28px">Explore results</div>',
            unsafe_allow_html=True,
        )
        for tab, key in zip(st.tabs(list(THEME_TAB_LABELS)), THEME_KEYS):
            with tab:
                render_detail(build_theme_detail(result, key))

    st.markdown('<div class="ess-rule" style="margin-top: 28px"></div>', unsafe_allow_html=True)
    with st.expander("Data sources and limitations"):
        st.markdown(PROVENANCE_MD)


if __name__ == "__main__":
    main()
