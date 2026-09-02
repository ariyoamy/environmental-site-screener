"""Pure input helpers for the Streamlit app.

Nothing here imports Streamlit or PyDeck, so it stays unit-testable on its own.
It covers a few small jobs:

* turning uploaded GeoJSON bytes into one candidate :class:`geopandas.GeoDataFrame`
  (left unvalidated - :func:`environmental_site_screener.site.validate_site` is
  still the single validation entry point);
* a small gallery of deterministic built-in demo sites so the app runs, and
  shows meaningfully different results, without an upload;
* building a one-rectangle candidate site from typed bounding coordinates (the
  "Define area" convenience input);
* turning raw validation errors into plain-language messages for the UI;
* choosing the basemap tile layer for the "Define area" drawing map;
* resolving and checking the local raw-data source paths the screening backend
  needs.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import MultiPolygon, box, shape

# --------------------------------------------------------------------------- #
# Demo site
# --------------------------------------------------------------------------- #

DEMO_SITE_LABEL = "Demo site - not a real proposed development"

# A 200 m square in eastern England (Suffolk), matching the candidate site in
# ``scripts/check_full_screening.py`` so the demo exercises several themes at
# once. EPSG:27700, so it passes straight through ``validate_site`` unchanged.
DEMO_SITE_BOUNDS = (565_147.0, 195_157.0, 565_347.0, 195_357.0)


def demo_site() -> gpd.GeoDataFrame:
    """Return the original built-in demo candidate site (one polygon, EPSG:27700).

    This is the first entry of :func:`demo_gallery`, kept as a standalone helper
    because tests and fixtures depend on its exact bounds.
    """
    minx, miny, maxx, maxy = DEMO_SITE_BOUNDS
    return gpd.GeoDataFrame(
        {"site_name": [DEMO_SITE_LABEL]},
        geometry=[box(minx, miny, maxx, maxy)],
        crs="EPSG:27700",
    )


# --------------------------------------------------------------------------- #
# Demo gallery
# --------------------------------------------------------------------------- #

_DEMO_MARKER = "fictional demo screening boundary, not a real proposed development"


@dataclass(frozen=True)
class DemoSite:
    """One deterministic example site for the app's demo gallery.

    ``geometry`` is a Shapely geometry in ``crs``; :meth:`geodataframe` wraps it
    the way an upload would arrive, so it flows through ``validate_site`` and the
    England eligibility check unchanged. All demo sites are within England and are
    clearly labelled as fictional.
    """

    key: str
    label: str
    blurb: str
    geometry: object
    crs: str = "EPSG:4326"

    def geodataframe(self) -> gpd.GeoDataFrame:
        return gpd.GeoDataFrame(
            {"site_name": [f"{self.label} ({_DEMO_MARKER})"]},
            geometry=[self.geometry],
            crs=self.crs,
        )


def _multipolygon(*boxes: tuple[float, float, float, float]) -> MultiPolygon:
    return MultiPolygon([box(*b) for b in boxes])


# Five deterministic example sites, chosen (and checked against the real
# datasets) to span clearly different screening outcomes rather than five
# lookalike rectangles. Order is fixed; the first is the original demo site.
DEMO_SITES: tuple[DemoSite, ...] = (
    DemoSite(
        key="suffolk_mixed",
        label="Mixed constraints - Suffolk",
        blurb="Priority habitat, ancient woodland and flood zone all present; nearest SSSI reported.",
        geometry=box(*DEMO_SITE_BOUNDS),
        crs="EPSG:27700",
    ),
    DemoSite(
        key="cambridge_urban",
        label="Urban mixed constraints - Cambridge",
        blurb="Edge-of-city rectangle overlapping priority habitat and a flood zone; nearest SSSI reported.",
        geometry=box(0.10000, 52.20000, 0.10900, 52.20600),
    ),
    DemoSite(
        key="newbury_multipart",
        label="Multi-part site - Newbury",
        blurb="Two separate parcels forming one candidate site; overlaps an SSSI and a flood zone.",
        geometry=_multipolygon(
            (-1.312, 51.400, -1.310, 51.402),
            (-1.308, 51.401, -1.306, 51.403),
        ),
    ),
    DemoSite(
        key="lincs_low",
        label="Low constraint - Lincolnshire Wolds",
        blurb="Arable farmland where several themes return no mapped overlap.",
        geometry=box(-0.202, 53.350, -0.198, 53.352),
    ),
    DemoSite(
        key="london_large",
        label="Large-area screening - London",
        blurb=(
            "A deliberately large demonstration extent (~22,600 ha) - every theme "
            "appears. It is not a real proposal and is far larger than a normal "
            "development site; screening it takes noticeably longer."
        ),
        geometry=box(-0.23600, 51.44000, -0.01900, 51.57500),
    ),
)


def demo_gallery() -> tuple[DemoSite, ...]:
    """Return the fixed tuple of demo sites for the gallery selector."""
    return DEMO_SITES


def demo_site_by_key(key: str) -> DemoSite:
    """Look up one demo site by its stable key."""
    for site in DEMO_SITES:
        if site.key == key:
            return site
    raise KeyError(f"unknown demo site key: {key!r}")


# --------------------------------------------------------------------------- #
# "Define area" convenience input
# --------------------------------------------------------------------------- #


def rectangle_site(
    west: float, south: float, east: float, north: float, *, crs: str = "EPSG:4326"
) -> gpd.GeoDataFrame:
    """Build a one-rectangle candidate site from bounding coordinates.

    The app's "Define area" option. The result is deliberately left unvalidated -
    it still goes through :func:`environmental_site_screener.site.validate_site`
    and the England eligibility check like any other candidate site.

    Raises
    ------
    ValueError
        If ``west >= east`` or ``south >= north`` (the message names the pair),
        or if any bound is not finite.
    """
    bounds = {"west": west, "south": south, "east": east, "north": north}
    for name, value in bounds.items():
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} coordinate is not a number: {value!r}") from exc
        if numeric != numeric or numeric in (float("inf"), float("-inf")):
            raise ValueError(f"{name} coordinate must be a finite number")
    if float(west) >= float(east):
        raise ValueError(
            f"west ({west}) must be less than east ({east}) - check the coordinate order"
        )
    if float(south) >= float(north):
        raise ValueError(
            f"south ({south}) must be less than north ({north}) - check the coordinate order"
        )
    return gpd.GeoDataFrame(
        {"site_name": ["Defined area"]},
        geometry=[box(float(west), float(south), float(east), float(north))],
        crs=crs,
    )


def rect_bounds_from_drawing(feature) -> tuple[float, float, float, float] | None:
    """``(west, south, east, north)`` from a Leaflet/GeoJSON draw payload.

    Accepts a GeoJSON ``Feature`` or a bare geometry ``dict`` (the shape
    ``streamlit-folium`` returns for a drawn rectangle). Returns ``None`` - never
    raises - for anything that is not a usable polygon ring: wrong type, missing
    or short coordinates, non-finite numbers, or a degenerate (zero-width/height)
    box. A usable result is still passed through :func:`rectangle_site` and the
    normal validation path by the caller.
    """
    if isinstance(feature, Mapping) and isinstance(feature.get("geometry"), Mapping):
        geom = feature["geometry"]
    elif isinstance(feature, Mapping):
        geom = feature
    else:
        return None

    if geom.get("type") != "Polygon":
        return None
    rings = geom.get("coordinates") or []
    if not rings or not rings[0]:
        return None

    xs: list[float] = []
    ys: list[float] = []
    for point in rings[0]:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            return None
        try:
            x = float(point[0])
            y = float(point[1])
        except (TypeError, ValueError):
            return None
        if x != x or y != y or x in (float("inf"), float("-inf")) or y in (
            float("inf"),
            float("-inf"),
        ):
            return None
        xs.append(x)
        ys.append(y)

    if len(xs) < 4:  # a rectangle ring is 5 points (closed); < 4 is not an area
        return None
    west, east = min(xs), max(xs)
    south, north = min(ys), max(ys)
    if west == east or south == north:
        return None
    return (west, south, east, north)


# --------------------------------------------------------------------------- #
# Basemap for the "Define area" drawing map
# --------------------------------------------------------------------------- #

# CARTO Voyager raster tiles. The `{s}` subdomain and `{z}/{x}/{y}` placeholders
# are filled in by Leaflet at request time. A CARTO Basemaps API key is appended
# as a query parameter when one is configured; without a key CARTO shows an
# "API key required" watermark, so the app falls back to OpenStreetMap tiles.
_CARTO_RASTER_URL = (
    "https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png"
)
_CARTO_ATTRIBUTION = (
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> '
    'contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
)
_OSM_TILES_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
_OSM_ATTRIBUTION = (
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> '
    "contributors"
)


def carto_tile_layer(api_key: str | None) -> dict:
    """Tile-layer settings for the Define-area drawing map.

    With a CARTO Basemaps API key, use CARTO Voyager raster tiles and append the
    key as a query parameter. Without one, fall back to key-free OpenStreetMap
    tiles. Attribution is always included; the key, when present, is only ever in
    the ``tiles`` URL.

    Returns a dict with ``tiles``, ``attr`` and ``name``, ready to hand to
    ``folium.TileLayer(**...)`` or ``folium.Map(tiles=..., attr=...)``.
    """
    key = (api_key or "").strip()
    if key:
        return {
            "tiles": f"{_CARTO_RASTER_URL}?key={key}",
            "attr": _CARTO_ATTRIBUTION,
            "name": "CARTO Voyager",
        }
    return {
        "tiles": _OSM_TILES_URL,
        "attr": _OSM_ATTRIBUTION,
        "name": "OpenStreetMap",
    }


# --------------------------------------------------------------------------- #
# Plain-language validation messages
# --------------------------------------------------------------------------- #

_FEATURE_ROWS_RE = re.compile(r"has (\d+) rows")

_REPAIR_NOTICE = (
    "The uploaded boundary was invalid and has been repaired for screening. "
    "Review the displayed boundary before continuing."
)


def friendly_site_error(message: str) -> tuple[str, str | None]:
    """Translate a raw ``read_geojson_site`` / ``validate_site`` error for the UI.

    Returns ``(headline, detail)``: ``headline`` is a plain-language sentence;
    ``detail`` is the original technical message to show in smaller text / an
    expander, or ``None`` when the headline already says everything. The raw
    ``validate_site`` messages themselves are left untouched.
    """
    text = str(message).strip()
    low = text.lower()

    if (
        "could not be parsed as json" in low
        or "not utf-8" in low
        or "root must be a json object" in low
    ):
        return (
            "We couldn't read this file as valid GeoJSON. "
            "Check the file format and try again.",
            text,
        )
    if "unsupported geojson type" in low:
        return (
            "This file isn't a GeoJSON Feature, FeatureCollection or geometry.",
            text,
        )
    if "no features" in low:
        return ("This GeoJSON contains no site features.", None)
    if "has no geometry" in low or "feature geometry could not be read" in low:
        return ("A feature in this file has no usable geometry.", text)
    match = _FEATURE_ROWS_RE.search(text)
    if match:
        return (
            f"Upload one site feature at a time. This file contains {match.group(1)} features.",
            None,
        )
    if "exactly one site feature" in low:
        return ("Upload one site feature at a time.", None)
    if "polygon or multipolygon" in low:
        return ("The candidate site must be a Polygon or MultiPolygon.", text)
    if "missing or empty" in low:
        return ("The uploaded feature has no usable polygon geometry.", None)
    if "could not be repaired" in low:
        return (
            "This boundary is invalid and couldn't be repaired for screening.",
            text,
        )
    if "non-positive area" in low:
        return (
            "The uploaded boundary has no area once projected to British National Grid.",
            text,
        )
    if "no crs" in low:
        return (
            "This GeoJSON has no coordinate reference system, so it can't be projected.",
            text,
        )
    return ("This site couldn't be validated.", text)


def friendly_repair_notice(messages) -> str | None:
    """Return one user-facing line if ``validate_site`` reported a geometry repair.

    The underlying technical warning is kept available separately (the app shows
    it in smaller text); this only reframes the headline copy.
    """
    for message in messages:
        if "invalid" in str(message).lower():
            return _REPAIR_NOTICE
    return None


# --------------------------------------------------------------------------- #
# GeoJSON upload
# --------------------------------------------------------------------------- #

_GEOMETRY_TYPES = {
    "Point",
    "MultiPoint",
    "LineString",
    "MultiLineString",
    "Polygon",
    "MultiPolygon",
    "GeometryCollection",
}

_EPSG_IN_NAME = re.compile(r"EPSG:{1,2}(\d+)", re.IGNORECASE)


def _crs_from_geojson(obj: dict) -> str | None:
    """Best-effort EPSG string from a (deprecated) GeoJSON ``crs`` member."""
    crs = obj.get("crs")
    if not isinstance(crs, dict):
        return None
    name = (crs.get("properties") or {}).get("name")
    if not isinstance(name, str):
        return None
    match = _EPSG_IN_NAME.search(name)
    return f"EPSG:{match.group(1)}" if match else None


def read_geojson_site(data: bytes | str) -> gpd.GeoDataFrame:
    """Parse uploaded GeoJSON into a candidate GeoDataFrame (not yet validated).

    Accepts a ``FeatureCollection``, a single ``Feature`` or a bare geometry.
    Multiple features are returned as multiple rows on purpose, so that
    :func:`environmental_site_screener.site.validate_site` can reject them with
    its own "exactly one site feature" message rather than this helper hiding the
    problem.

    Parameters
    ----------
    data:
        Raw GeoJSON, as bytes (UTF-8) or text.

    Returns
    -------
    geopandas.GeoDataFrame
        One row per input feature, geometry column set, CRS taken from a named
        ``crs`` member if present otherwise EPSG:4326 (the GeoJSON default).

    Raises
    ------
    ValueError
        If the bytes are not UTF-8, the text is not JSON, the structure is not
        recognisable GeoJSON, there are no features, or a geometry cannot be
        read. The message keeps the underlying parser detail.
    """
    if isinstance(data, bytes):
        try:
            data = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(
                "The file is not UTF-8 text; a GeoJSON file is expected."
            ) from exc

    try:
        obj = json.loads(data)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"The file could not be parsed as JSON: {exc}") from exc

    if not isinstance(obj, dict):
        raise ValueError("The GeoJSON root must be a JSON object.")

    geojson_type = obj.get("type")
    if geojson_type == "FeatureCollection":
        features = obj.get("features") or []
    elif geojson_type == "Feature":
        features = [obj]
    elif geojson_type in _GEOMETRY_TYPES:
        features = [{"type": "Feature", "properties": {}, "geometry": obj}]
    else:
        raise ValueError(
            f"Unsupported GeoJSON type: {geojson_type!r}. "
            "Expected FeatureCollection, Feature or a geometry."
        )

    if len(features) == 0:
        raise ValueError("The GeoJSON contains no features.")

    geometries = []
    properties: list[dict] = []
    for feature in features:
        raw_geom = feature.get("geometry") if isinstance(feature, dict) else None
        if raw_geom is None:
            raise ValueError("A feature in the GeoJSON has no geometry.")
        try:
            geometries.append(shape(raw_geom))
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            raise ValueError(f"A feature geometry could not be read: {exc}") from exc
        props = feature.get("properties")
        properties.append(props if isinstance(props, dict) else {})

    crs = _crs_from_geojson(obj) or "EPSG:4326"
    return gpd.GeoDataFrame(pd.DataFrame(properties), geometry=geometries, crs=crs)


# --------------------------------------------------------------------------- #
# Local source data
# --------------------------------------------------------------------------- #

# Same local files as scripts/check_full_screening.py, relative to the repo root.
_RELATIVE_SOURCES = {
    "sssi_path": ("sssi", "Sites_of_Special_Scientific_Interest_England.gpkg"),
    "sssi_irz_path": ("sssi_irz", "SSSI_Impact_Risk_Zones_England.gpkg"),
    "priority_habitats_path": (
        "priority_habitats",
        "Priority_Habitats_Inventory_England.gpkg",
    ),
    "ancient_woodland_revised_path": (
        "ancient_woodland",
        "revised",
        "Ancient_Woodland_Revised_England_Completed_Counties.gpkg",
    ),
    "ancient_woodland_legacy_path": (
        "ancient_woodland",
        "legacy",
        "Ancient_Woodland_England.gpkg",
    ),
    "revised_coverage_path": (
        "ancient_woodland",
        "coverage",
        "Boundary-line-ceremonial-counties_region.shp",
    ),
    "flood_zones_path": ("flood_zones", "Flood_Map_for_Planning_Flood_Zones.gpkg"),
}


def default_data_sources(repo_root: str | Path) -> dict[str, Path]:
    """Return the ``load_screening_datasets`` keyword paths under ``data/raw``."""
    raw = Path(repo_root) / "data" / "raw"
    return {key: raw.joinpath(*parts) for key, parts in _RELATIVE_SOURCES.items()}


def missing_sources(sources: Mapping[str, str | Path]) -> list[Path]:
    """Return the source paths that do not exist, in declared order."""
    return [Path(path) for path in sources.values() if not Path(path).exists()]
