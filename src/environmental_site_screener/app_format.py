"""Plain-language presentation helpers for the screening result.

Pure functions only - no Streamlit, no PyDeck, no map/geometry work. Everything
here turns the backend result dataclasses into small view-models the app renders:
the compact per-theme cards, a one-line plain-English explanation of each theme,
and the per-theme "Explore results" panels shown under the workspace.

The wording is deliberately neutral. These helpers never produce a score, a
rating, a pass/fail, a "risk" level or a "safe"/"unsafe" statement; they report
what the mapped datasets show for the candidate site and the documented way to
read that, and nothing more.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Theme keys in the fixed user-facing order, with their tab labels and the
# short name used in prose / the "About the themes" panel.
THEME_KEYS = (
    "sssi",
    "irz",
    "priority_habitats",
    "ancient_woodland",
    "flood_zones",
)
THEME_TAB_LABELS = (
    "SSSI",
    "SSSI IRZ",
    "Priority Habitats",
    "Ancient Woodland",
    "Flood Zones",
)
THEME_DISPLAY = {
    "sssi": "SSSI",
    "irz": "SSSI Impact Risk Zone",
    "priority_habitats": "Priority Habitats",
    "ancient_woodland": "Ancient Woodland",
    "flood_zones": "Flood Zones",
}

# One concise, cautious explanation per theme, consistent with the methodology.
THEME_HELP = {
    "sssi": (
        "Sites of Special Scientific Interest are nationally designated sites "
        "protected for important wildlife or geological features."
    ),
    "irz": (
        "SSSI Impact Risk Zones are a Natural England screening context used to "
        "flag developments that may need further consideration near an SSSI. An "
        "intersection is not itself an adverse result."
    ),
    "priority_habitats": (
        "Priority Habitats are habitats identified as conservation priorities in "
        "England. Not every polygon in the inventory is priority habitat - the "
        "context classes are reported separately."
    ),
    "ancient_woodland": (
        "Ancient Woodland is long-established woodland, mapped here using Natural "
        "England's revised inventory where available and the legacy inventory "
        "elsewhere."
    ),
    "flood_zones": (
        "Flood Zones are Environment Agency planning zones showing mapped river "
        "and sea flood probability. They do not cover surface water, groundwater "
        "or drainage flooding, and Flood Zone 1 is not mapped."
    ),
}

# Card "tone" drives visual emphasis only - not a judgement.
TONE_OVERLAP = "overlap"
TONE_CONTEXT = "context"
TONE_NONE = "none"

_GRID = "British National Grid (EPSG:27700)"


def theme_help(theme_key: str) -> str:
    """Return the one-line plain-English explanation for a theme key."""
    if theme_key not in THEME_HELP:
        raise KeyError(f"unknown theme key: {theme_key!r}")
    return THEME_HELP[theme_key]


# --------------------------------------------------------------------------- #
# Number formatting
# --------------------------------------------------------------------------- #


def format_area_ha(area_ha: float) -> str:
    """Format an area in hectares for display."""
    if area_ha is None or (isinstance(area_ha, float) and math.isnan(area_ha)):
        return "-"
    if area_ha <= 0:
        return "0 ha"
    if area_ha < 0.01:
        return "<0.01 ha"
    if area_ha < 100:
        return f"{area_ha:.2f} ha"
    return f"{area_ha:,.0f} ha"


def format_pct(pct: float) -> str:
    """Format a percentage of the candidate site for display."""
    if pct is None or (isinstance(pct, float) and math.isnan(pct)):
        return "-"
    if pct <= 0:
        return "0%"
    if pct < 0.1:
        return "<0.1%"
    if pct >= 99.95:
        return "100%"
    return f"{pct:.1f}%"


def format_distance(distance_m: float) -> str:
    """Format an edge-to-edge distance: metres under 1 km, kilometres above."""
    if distance_m is None or (isinstance(distance_m, float) and math.isnan(distance_m)):
        return "-"
    if distance_m <= 0:
        return "0 m"
    if distance_m < 1_000:
        return f"{distance_m:,.0f} m"
    return f"{distance_m / 1_000:.2f} km"


def _count(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _clean(value) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value)


def _first_value(gdf, column, default=""):
    """First non-empty value in ``column`` of ``gdf``, or ``default``."""
    for value in gdf[column]:
        text = _clean(value).strip()
        if text:
            return text
    return default


# --------------------------------------------------------------------------- #
# Theme cards
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ThemeCard:
    """A compact per-theme result card.

    ``tone`` (``"overlap"`` / ``"context"`` / ``"none"``) controls visual
    emphasis only. ``primary_metric`` is the single number the card leads with
    for an overlap theme (the percentage of the site affected) and is ``None``
    when there is nothing to lead with. ``secondary_metric`` and ``context_line``
    carry the supporting figures.
    """

    theme: str
    tone: str
    state_label: str
    primary_metric: str | None
    secondary_metric: str | None
    context_line: str | None


def build_theme_cards(result) -> list[ThemeCard]:
    """Build the five environmental-screening cards in fixed theme order."""
    return [
        _sssi_card(result),
        _irz_card(result),
        _priority_habitats_card(result),
        _ancient_woodland_card(result),
        _flood_zones_card(result),
    ]


def _overlap_card(theme, area_ha, pct, context_line) -> ThemeCard:
    return ThemeCard(
        theme,
        TONE_OVERLAP,
        "Mapped overlap",
        format_pct(pct),
        f"{format_area_ha(area_ha)} of site",
        context_line,
    )


def _sssi_card(result) -> ThemeCard:
    sssi = result.sssi
    if sssi.has_overlap:
        return _overlap_card(
            "SSSI",
            sssi.affected_area_ha,
            sssi.affected_pct,
            _count(sssi.feature_count, "intersecting SSSI", "intersecting SSSIs"),
        )
    nearest = result.nearest_sssi
    secondary = (
        f"Nearest: {format_distance(nearest.distance_m)}"
        if nearest is not None
        else None
    )
    return ThemeCard("SSSI", TONE_NONE, "No mapped overlap", None, secondary, None)


def _irz_card(result) -> ThemeCard:
    irz = result.sssi_irz
    if irz.has_irz_context:
        return ThemeCard(
            "SSSI Impact Risk Zone",
            TONE_CONTEXT,
            "Context identified",
            None,
            None,
            _count(irz.zone_count, "intersecting zone", "intersecting zones"),
        )
    return ThemeCard(
        "SSSI Impact Risk Zone", TONE_CONTEXT, "No IRZ context", None, None, None
    )


def _priority_habitats_card(result) -> ThemeCard:
    phi = result.priority_habitats
    if phi.has_priority_overlap:
        return _overlap_card(
            "Priority Habitats",
            phi.affected_area_ha,
            phi.affected_pct,
            _count(phi.habitat_count, "habitat class", "habitat classes"),
        )
    context_line = (
        "Context habitat mapped (not priority)" if len(phi.context) > 0 else None
    )
    return ThemeCard(
        "Priority Habitats", TONE_NONE, "No mapped overlap", None, None, context_line
    )


def _ancient_woodland_card(result) -> ThemeCard:
    woodland = result.ancient_woodland
    if woodland.has_overlap:
        inventories = sorted({str(v) for v in woodland.features["inventory"]})
        context_line = _count(
            woodland.feature_count, "woodland category", "woodland categories"
        )
        if inventories:
            context_line += " · " + " + ".join(inventories)
        return _overlap_card(
            "Ancient Woodland",
            woodland.affected_area_ha,
            woodland.affected_pct,
            context_line,
        )
    return ThemeCard(
        "Ancient Woodland", TONE_NONE, "No mapped overlap", None, None, None
    )


def _flood_zones_card(result) -> ThemeCard:
    flood = result.flood_zones
    if flood.has_flood_zone_overlap:
        zones = " + ".join(sorted({str(z) for z in flood.zones["flood_zone"]}))
        return _overlap_card(
            "Flood Zones", flood.affected_area_ha, flood.affected_pct, zones or None
        )
    return ThemeCard(
        "Flood Zones",
        TONE_NONE,
        "No mapped overlap",
        None,
        None,
        "No mapped Flood Zone 2 or 3",
    )


# --------------------------------------------------------------------------- #
# Theme detail ("Explore results")
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DetailTable:
    """A titled table for a theme-detail panel; ``rows`` is display-ready."""

    title: str
    rows: tuple[dict, ...]


@dataclass(frozen=True)
class ThemeDetail:
    """View-model for one theme's "Explore results" panel.

    ``headline`` is a plain-language result statement; ``metrics`` are the key
    figures (first one shown most prominently); ``what_it_means`` is a short,
    non-technical explanation of how to read the result; ``tables`` are the
    mapped/source detail; ``note`` is a dataset-specific caution.
    """

    headline: str
    metrics: tuple[str, ...]
    what_it_means: str
    tables: tuple[DetailTable, ...]
    links: tuple[str, ...]
    note: str | None


def _table(
    gdf, columns: list[tuple[str, str]], *, round_map: dict[str, int] | None = None
) -> tuple[dict, ...]:
    """Rows for a :class:`DetailTable` from ``gdf`` using ``(label, col)`` pairs."""
    round_map = round_map or {}
    rows: list[dict] = []
    for _, record in gdf.iterrows():
        row: dict = {}
        for label, col in columns:
            value = record[col]
            if label in round_map and isinstance(value, (int, float)) and not (
                isinstance(value, float) and math.isnan(value)
            ):
                value = round(float(value), round_map[label])
            elif not isinstance(value, (int, float)):
                value = _clean(value)
            row[label] = value
        rows.append(row)
    return tuple(rows)


def build_theme_detail(result, theme_key: str) -> ThemeDetail:
    """Build the "Explore results" view-model for one theme (see THEME_KEYS)."""
    builders = {
        "sssi": _sssi_detail,
        "irz": _irz_detail,
        "priority_habitats": _priority_habitats_detail,
        "ancient_woodland": _ancient_woodland_detail,
        "flood_zones": _flood_zones_detail,
    }
    if theme_key not in builders:
        raise KeyError(f"unknown theme key: {theme_key!r}")
    return builders[theme_key](result)


def _sssi_detail(result) -> ThemeDetail:
    sssi = result.sssi
    if sssi.has_overlap:
        headline = "Mapped SSSI overlaps this candidate site."
        metrics = (
            f"{format_pct(sssi.affected_pct)} of the site "
            f"({format_area_ha(sssi.affected_area_ha)})",
            _count(sssi.feature_count, "intersecting SSSI", "intersecting SSSIs"),
        )
        what = (
            f"{THEME_HELP['sssi']} The figures are the mapped overlap between the "
            f"site boundary and SSSI polygons, measured in {_GRID}."
        )
        tables = (
            DetailTable(
                "Intersecting SSSIs",
                _table(
                    sssi.features,
                    [
                        ("Reference", "ref_code"),
                        ("Name", "name"),
                        ("Notified feature", "measure"),
                        ("Overlap (ha)", "intersection_area_ha"),
                    ],
                    round_map={"Overlap (ha)": 4},
                ),
            ),
        )
        note = (
            "A mapped overlap flags a designated site to investigate. It is not a "
            "finding that development is prohibited or that harm will occur."
        )
        return ThemeDetail(headline, metrics, what, tables, (), note)

    nearest = result.nearest_sssi
    headline = "No mapped SSSI overlaps this candidate site."
    metrics: tuple[str, ...] = ()
    tables: tuple[DetailTable, ...] = ()
    if nearest is not None:
        name = _first_value(nearest.features, "name", "the nearest SSSI")
        metrics = (
            f"Nearest designated site: {name} ({format_distance(nearest.distance_m)})",
        )
        tables = (
            DetailTable(
                "Nearest SSSI",
                _table(
                    nearest.features,
                    [
                        ("Reference", "ref_code"),
                        ("Name", "name"),
                        ("Notified feature", "measure"),
                    ],
                ),
            ),
        )
    what = (
        f"{THEME_HELP['sssi']} The distance is edge to edge between the site "
        f"boundary and the nearest SSSI, measured in {_GRID} - not a straight "
        "line between centres."
    )
    note = "A nearby SSSI is context to be aware of, not a constraint on the site itself."
    return ThemeDetail(headline, metrics, what, tables, (), note)


def _irz_detail(result) -> ThemeDetail:
    irz = result.sssi_irz
    if irz.has_irz_context:
        noun = "Zone" if irz.zone_count == 1 else "Zones"
        headline = (
            f"The candidate site intersects {irz.zone_count} mapped SSSI Impact "
            f"Risk {noun}."
        )
        metrics = (
            _count(irz.zone_count, "intersecting zone", "intersecting zones"),
        )
        tables = (
            DetailTable(
                "Intersecting zones",
                _table(
                    irz.zones,
                    [("IRZ code", "irz_code"), ("Advice URL", "irzurl")],
                ),
            ),
        )
    else:
        headline = "The candidate site does not intersect a mapped SSSI Impact Risk Zone."
        metrics = ()
        tables = ()
    what = (
        f"{THEME_HELP['irz']} This step only reports the intersection - it does "
        "not measure how much of the site is covered, and it is not a finding "
        "that development will affect an SSSI."
    )
    note = (
        "Whether Natural England advice applies depends on the type and scale of "
        "the proposed development. Follow the advice link for each zone."
    )
    return ThemeDetail(headline, metrics, what, tables, tuple(irz.advice_urls), note)


def _priority_habitats_detail(result) -> ThemeDetail:
    phi = result.priority_habitats
    if phi.has_priority_overlap:
        headline = "Mapped priority habitat overlaps this candidate site."
        metrics = (
            f"{format_pct(phi.affected_pct)} of the site "
            f"({format_area_ha(phi.affected_area_ha)})",
            _count(phi.habitat_count, "priority habitat class", "priority habitat classes"),
        )
    else:
        headline = "No mapped priority habitat overlaps this candidate site."
        metrics = ()

    tables: list[DetailTable] = []
    habitat_rows = _table(
        phi.habitats,
        [
            ("Code", "habitat_code"),
            ("Habitat", "habitat_name"),
            ("Overlap (ha)", "intersection_area_ha"),
        ],
        round_map={"Overlap (ha)": 4},
    )
    if habitat_rows:
        tables.append(DetailTable("Priority habitat classes", habitat_rows))

    note = None
    if len(phi.context) > 0:
        context_rows = _table(
            phi.context,
            [
                ("UID", "uid"),
                ("Codes", "context_codes"),
                ("Habitat", "context_habitats"),
                ("Source", "primsource"),
            ],
        )
        if context_rows:
            tables.append(
                DetailTable("Other mapped habitat (context, not priority)", context_rows)
            )
        note = (
            "Context classes - fragmented heath, grass moorland, good quality "
            "semi-improved grassland, no main habitat - are recorded in the "
            "inventory but are not priority habitat, so they are shown separately "
            "and excluded from the figures above."
        )
    what = (
        f"{THEME_HELP['priority_habitats']} The figures are the mapped overlap "
        f"between the site boundary and priority-habitat polygons, in {_GRID}."
    )
    return ThemeDetail(headline, tuple(metrics), what, tuple(tables), (), note)


def _ancient_woodland_detail(result) -> ThemeDetail:
    woodland = result.ancient_woodland
    if woodland.has_overlap:
        headline = "Mapped ancient woodland overlaps this candidate site."
        metrics = [
            f"{format_pct(woodland.affected_pct)} of the site "
            f"({format_area_ha(woodland.affected_area_ha)})",
        ]
    else:
        headline = "No mapped ancient woodland overlaps this candidate site."
        metrics = []
    metrics.append(
        f"{format_area_ha(woodland.revised_coverage_area_m2 / 10_000)} of the site "
        "sits within revised-inventory coverage; "
        f"{format_area_ha(woodland.fallback_area_m2 / 10_000)} on the legacy fallback."
    )
    tables = (
        DetailTable(
            "Woodland categories",
            _table(
                woodland.features,
                [
                    ("Inventory", "inventory"),
                    ("Code", "category_code"),
                    ("Category", "category_name"),
                    ("Overlap (ha)", "intersection_area_ha"),
                ],
                round_map={"Overlap (ha)": 4},
            ),
        ),
    )
    what = (
        f"{THEME_HELP['ancient_woodland']} Where the revised inventory covers a "
        "county it takes precedence; the legacy inventory is the fallback "
        "elsewhere. Coverage uses a documented, project-inferred completed-county "
        "list rather than a Natural England coverage layer."
    )
    note = "Revised and legacy categories are reported separately and are not merged."
    return ThemeDetail(headline, tuple(metrics), what, tables, (), note)


def _flood_zones_detail(result) -> ThemeDetail:
    flood = result.flood_zones
    if flood.has_flood_zone_overlap:
        headline = (
            f"{format_pct(flood.affected_pct)} of the candidate site intersects "
            "mapped Flood Zone 2 or 3."
        )
        metrics = [f"{format_area_ha(flood.affected_area_ha)} affected"]
        metrics.append(
            "Flood sources: "
            + (", ".join(flood.flood_sources) if flood.flood_sources else "not recorded")
        )
        metrics.append(
            "Origin: "
            + (", ".join(flood.origins) if flood.origins else "not recorded")
        )
    else:
        headline = "No mapped Flood Zone 2 or 3 overlaps this candidate site."
        metrics = []
    tables = (
        DetailTable(
            "Flood zones",
            _table(
                flood.zones,
                [
                    ("Zone", "flood_zone"),
                    ("Overlap (ha)", "intersection_area_ha"),
                    ("Site %", "site_pct"),
                    ("Flood source", "flood_sources"),
                    ("Origin", "origins"),
                ],
                round_map={"Overlap (ha)": 4, "Site %": 2},
            ),
        ),
    )
    what = (
        f"{THEME_HELP['flood_zones']} These are planning flood zones for river "
        "and sea flooding; they ignore the benefit of flood defences and this is "
        "not a property-level flood check."
    )
    note = (
        "Flood Zone 2 and 3 are shown as mapped. Flood Zone 3b (functional "
        "floodplain) is included within Flood Zone 3 and not shown separately."
    )
    return ThemeDetail(headline, tuple(metrics), what, tables, (), note)
