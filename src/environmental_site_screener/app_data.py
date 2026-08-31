"""Pure input helpers for the Streamlit app.

Nothing here imports Streamlit or PyDeck, so it stays unit-testable on its own.
It covers three small jobs:

* turning uploaded GeoJSON bytes into one candidate :class:`geopandas.GeoDataFrame`
  (left unvalidated - :func:`environmental_site_screener.site.validate_site` is
  still the single validation entry point);
* a deterministic built-in demo site so the app runs without an upload;
* resolving and checking the local raw-data source paths the screening backend
  needs.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import box, shape

# --------------------------------------------------------------------------- #
# Demo site
# --------------------------------------------------------------------------- #

DEMO_SITE_LABEL = "Demo site - not a real proposed development"

# A 200 m square in eastern England (Suffolk), matching the candidate site in
# ``scripts/check_full_screening.py`` so the demo exercises several themes at
# once. EPSG:27700, so it passes straight through ``validate_site`` unchanged.
DEMO_SITE_BOUNDS = (565_147.0, 195_157.0, 565_347.0, 195_357.0)


def demo_site() -> gpd.GeoDataFrame:
    """Return the built-in demo candidate site (one polygon, EPSG:27700)."""
    minx, miny, maxx, maxy = DEMO_SITE_BOUNDS
    return gpd.GeoDataFrame(
        {"site_name": [DEMO_SITE_LABEL]},
        geometry=[box(minx, miny, maxx, maxy)],
        crs="EPSG:27700",
    )


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
