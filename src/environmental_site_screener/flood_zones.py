"""Loader and overlap analysis for the Environment Agency Flood Map for Planning
- Flood Zones (rivers and sea).

The source layer ``Flood_Zones_2_3_Rivers_and_Sea`` maps two zones:

* ``FZ2`` - land between the 0.1% and 1% (rivers) / 0.1% and 0.5% (sea) annual
  probability of flooding, plus accepted recorded flood outlines;
* ``FZ3`` - land at 1% (rivers) / 0.5% (sea) or greater annual probability
  (Flood Zone 3b, the functional floodplain, is included within FZ3 and not
  mapped separately).

In the delivered dataset the ``FZ2`` and ``FZ3`` polygons are mutually exclusive
bands, but the analysis unions all kept clipped geometry for the headline figure
rather than adding the per-zone areas, so it stays correct if that ever changes
or if floating-point slivers appear.

Flood Zone 1 (less than 0.1% annual probability) is *not* in this dataset; it is
land outside mapped FZ2/FZ3. This module never manufactures a Flood Zone 1
geometry, row or flag - a site with no positive-area FZ2/FZ3 overlap simply
returns an empty result.

The national source is ~5.9 GB / 800k+ features. :func:`load_flood_zones`
therefore takes an optional ``bbox`` for a native GeoPackage spatial-index read
of just the polygons near a site; ``bbox=None`` keeps the full-source read for
audits. Source metadata is checked with ``pyogrio.read_info`` so a missing or
broken source is distinguished from a valid but locally empty spatial subset.

The Environment Agency's Flood Zones ignore the benefit of flood defences, do
not represent other flood sources (surface water, groundwater, drainage), and
are a planning tool rather than a property-level or yes/no flood statement.
Nothing here derives a flood-risk score or any safe/unsafe, permitted/refused
conclusion, and the climate-change dataset is out of scope for this MVP.
"""

from __future__ import annotations

import pathlib
import warnings
from dataclasses import dataclass

import geopandas as gpd
import pandas as pd
import pyogrio
from shapely import union_all

EXPECTED_EPSG = 27700

_ALLOWED_GEOM_TYPES = frozenset({"Polygon", "MultiPolygon"})
_ALLOWED_FLOOD_ZONES = frozenset({"FZ2", "FZ3"})

_SOURCE_COLUMNS = ("origin", "flood_zone", "flood_source")

FLOOD_ZONE_OUTPUT_COLUMNS = ["flood_zone", "flood_source", "origin", "geometry"]

ZONE_COLUMNS = [
    "flood_zone",
    "intersection_area_m2",
    "intersection_area_ha",
    "site_pct",
    "flood_sources",
    "origins",
    "geometry",
]

_REQUIRED_ANALYSIS_COLUMNS = ("flood_zone", "flood_source", "origin")


def _none_normalised(series: pd.Series):
    """Object array carrying a real ``None`` wherever the source value is missing."""
    return series.astype(object).where(series.notna(), None).to_numpy()


def _distinct_non_null(values) -> list[str]:
    """Sorted distinct non-null string values, ``river and sea`` kept as one token."""
    seen: set[str] = set()
    for value in values:
        if value is None or pd.isna(value):
            continue
        text = str(value)
        if text:
            seen.add(text)
    return sorted(seen)


def _epsg_from_info(crs_value) -> int | None:
    """Best-effort EPSG code from a ``pyogrio.read_info`` ``crs`` value."""
    if not crs_value:
        return None
    text = str(crs_value).strip().upper().replace(" ", "")
    if text.startswith("EPSG:"):
        try:
            return int(text.split(":", 1)[1])
        except ValueError:
            return None
    return None


def _empty_flood_zones(crs) -> gpd.GeoDataFrame:
    """Empty loader-shaped GeoDataFrame (exact schema, given CRS, clean index)."""
    attr = pd.DataFrame(
        {
            "flood_zone": pd.Series(dtype="object"),
            "flood_source": pd.Series(dtype="object"),
            "origin": pd.Series(dtype="object"),
        }
    )
    empty = gpd.GeoDataFrame(attr, geometry=gpd.GeoSeries([], crs=crs))
    return empty.loc[:, FLOOD_ZONE_OUTPUT_COLUMNS].reset_index(drop=True)


def load_flood_zones(
    path: str | pathlib.Path,
    bbox: tuple[float, float, float, float] | None = None,
) -> gpd.GeoDataFrame:
    """Load and validate the EA Flood Map for Planning - Flood Zones source.

    Parameters
    ----------
    path:
        Path to the Flood Zones GeoPackage
        (``Flood_Map_for_Planning_Flood_Zones.gpkg``, layer
        ``Flood_Zones_2_3_Rivers_and_Sea``).
    bbox:
        Optional ``(minx, miny, maxx, maxy)`` in EPSG:27700. ``None`` reads the
        whole national source (for audits / manual validation). A bounding box
        performs a native GeoPackage spatial-index read of only the features
        whose bounding box intersects it - the intended site-screening path is
        ``bbox=tuple(site.total_bounds)``. Exact positive-area intersection in
        :func:`calculate_flood_zone_overlap` still removes bbox false positives,
        so no bbox buffer is added or needed.

    Returns
    -------
    geopandas.GeoDataFrame
        Columns ``flood_zone``, ``flood_source``, ``origin`` and ``geometry``
        (in that order), in EPSG:27700, with a clean ``RangeIndex``.
        ``flood_source`` and ``origin`` carry ``None`` where the source value is
        missing. With a ``bbox`` and no features inside it, an empty GeoDataFrame
        with this exact schema and CRS is returned - a legitimate spatial
        subset, not a missing source.

    Raises
    ------
    FileNotFoundError
        If ``path`` does not exist.
    ValueError
        If source metadata cannot confirm a readable layer, an EPSG:27700 CRS
        and the required ``origin`` / ``flood_zone`` / ``flood_source`` fields;
        if ``bbox`` is ``None`` and the source has no features; or if the rows
        actually read have no active geometry column, null, empty or
        non-polygonal geometry, or a ``flood_zone`` value that is null, empty or
        not ``FZ2``/``FZ3``.

    Warns
    -----
    UserWarning
        Once, with a count, if the rows read contain invalid geometry. The
        geometry is left unchanged; this loader does not repair authoritative
        source data.

    Notes
    -----
    Source metadata is inspected with ``pyogrio.read_info`` before the feature
    read, so a broken or missing national source is distinguished from a valid
    source with nothing near the site without loading the national geometry.
    Only ``origin``, ``flood_zone`` and ``flood_source`` plus geometry are read.
    The source is not reprojected. ``flood_source`` and ``origin`` are preserved
    verbatim and are not checked against a fixed vocabulary; the source ``fid``
    is not retained.
    """
    source = pathlib.Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Flood Zones source file not found: {source}")

    # Lightweight metadata inspection - tells a broken/missing national source
    # apart from a valid source with nothing near the site, without reading the
    # national geometry.
    info = pyogrio.read_info(source)

    if not info.get("crs"):
        raise ValueError("Flood Zones source has no CRS defined; expected EPSG:27700")
    meta_epsg = _epsg_from_info(info.get("crs"))
    if meta_epsg is not None and meta_epsg != EXPECTED_EPSG:
        raise ValueError(
            f"Flood Zones source CRS is EPSG:{meta_epsg}; expected EPSG:27700. "
            "This loader does not reproject the authoritative Flood Zones source."
        )

    meta_fields = {
        str(f) for f in (info.get("fields") if info.get("fields") is not None else [])
    }
    meta_missing = [c for c in _SOURCE_COLUMNS if c not in meta_fields]
    if meta_missing:
        raise ValueError(
            f"Flood Zones source is missing required column(s): {meta_missing}"
        )

    if bbox is None and int(info.get("features") or 0) == 0:
        raise ValueError("Flood Zones source contains no features")

    read_kwargs = {"columns": list(_SOURCE_COLUMNS)}
    if bbox is not None:
        read_kwargs["bbox"] = tuple(bbox)
    gdf = gpd.read_file(source, **read_kwargs)

    try:
        gdf.geometry.name
    except AttributeError as exc:
        raise ValueError("Flood Zones source has no active geometry column") from exc

    if len(gdf) == 0:
        if bbox is None:
            raise ValueError("Flood Zones source contains no features")
        return _empty_flood_zones(gdf.crs or f"EPSG:{EXPECTED_EPSG}")

    missing = [c for c in _SOURCE_COLUMNS if c not in gdf.columns]
    if missing:
        raise ValueError(f"Flood Zones source is missing required column(s): {missing}")

    if gdf.crs is None:
        raise ValueError("Flood Zones source has no CRS defined; expected EPSG:27700")
    epsg = gdf.crs.to_epsg()
    if epsg != EXPECTED_EPSG:
        raise ValueError(
            f"Flood Zones source CRS is {gdf.crs.name!r} (EPSG:{epsg}); expected EPSG:27700. "
            "This loader does not reproject the authoritative Flood Zones source."
        )

    geometry = gdf.geometry
    null_geom = int(geometry.isna().sum())
    if null_geom:
        raise ValueError(f"Flood Zones source contains {null_geom} null geometries")
    empty_geom = int(geometry.is_empty.sum())
    if empty_geom:
        raise ValueError(f"Flood Zones source contains {empty_geom} empty geometries")
    bad_types = sorted(set(geometry.geom_type) - _ALLOWED_GEOM_TYPES)
    if bad_types:
        raise ValueError(
            f"Flood Zones source contains non-polygonal geometry (types found: {bad_types})"
        )
    invalid_count = int((~geometry.is_valid).sum())
    if invalid_count:
        warnings.warn(
            f"Flood Zones source contains {invalid_count} invalid geometries; they are "
            "left unchanged (this loader does not repair authoritative source data)",
            UserWarning,
            stacklevel=2,
        )

    flood_zone = gdf["flood_zone"]
    if flood_zone.isna().any():
        raise ValueError(
            f"Flood Zones source has {int(flood_zone.isna().sum())} null flood_zone values"
        )
    fz_text = flood_zone.astype("string")
    if (fz_text.str.len() == 0).any():
        raise ValueError("Flood Zones source has empty flood_zone values")
    unknown = sorted(set(fz_text) - _ALLOWED_FLOOD_ZONES)
    if unknown:
        raise ValueError(
            f"Flood Zones source has unexpected flood_zone value(s): {unknown}. "
            "Only 'FZ2' and 'FZ3' are expected."
        )

    result = gpd.GeoDataFrame(
        {
            "flood_zone": fz_text.astype(object).to_numpy(),
            "flood_source": _none_normalised(gdf["flood_source"]),
            "origin": _none_normalised(gdf["origin"]),
        },
        geometry=geometry.to_numpy(),
        crs=gdf.crs,
    )
    result = result.loc[:, FLOOD_ZONE_OUTPUT_COLUMNS]
    return result.reset_index(drop=True)


@dataclass(frozen=True)
class FloodZoneOverlapResult:
    """Result of a candidate-site / Flood Zones overlap analysis.

    Attributes
    ----------
    has_flood_zone_overlap:
        ``True`` when the site overlaps mapped Flood Zone 2 or 3 with positive
        area. It is not a statement that the site will or will not flood, or that
        development is or is not permitted.
    zone_count:
        Number of rows in ``zones`` (0, 1 or 2).
    zones:
        One row per overlapping ``flood_zone``, columns ``flood_zone``,
        ``intersection_area_m2``, ``intersection_area_ha``, ``site_pct``,
        ``flood_sources``, ``origins`` and ``geometry`` (the unioned clipped
        overlap for that zone), EPSG:27700, sorted by descending
        ``intersection_area_m2`` then ``flood_zone``. Empty with this exact
        schema when there is no overlap.
    site_area_m2:
        Area of the candidate site polygon, square metres.
    affected_area_m2:
        Area of the site covered by any mapped Flood Zone 2 or 3, square metres,
        computed as the area of the union of every kept clipped polygon - never
        the sum of the per-zone areas.
    affected_area_ha:
        ``affected_area_m2 / 10_000``.
    affected_pct:
        ``100 * affected_area_m2 / site_area_m2``.
    flood_sources:
        Sorted tuple of the distinct non-null ``flood_source`` values across all
        kept intersecting polygons (``river and sea`` is one value, not split).
    origins:
        Sorted tuple of the distinct non-null ``origin`` values across all kept
        intersecting polygons.
    """

    has_flood_zone_overlap: bool
    zone_count: int
    zones: gpd.GeoDataFrame
    site_area_m2: float
    affected_area_m2: float
    affected_area_ha: float
    affected_pct: float
    flood_sources: tuple[str, ...]
    origins: tuple[str, ...]


def _empty_zones(crs) -> gpd.GeoDataFrame:
    attr = pd.DataFrame(
        {
            "flood_zone": pd.Series(dtype="object"),
            "intersection_area_m2": pd.Series(dtype="float64"),
            "intersection_area_ha": pd.Series(dtype="float64"),
            "site_pct": pd.Series(dtype="float64"),
            "flood_sources": pd.Series(dtype="object"),
            "origins": pd.Series(dtype="object"),
        }
    )
    return gpd.GeoDataFrame(attr, geometry=gpd.GeoSeries([], crs=crs))[ZONE_COLUMNS]


def calculate_flood_zone_overlap(
    site: gpd.GeoDataFrame, flood_zones: gpd.GeoDataFrame
) -> FloodZoneOverlapResult:
    """Calculate positive-area overlap between a candidate site and Flood Zones.

    Parameters
    ----------
    site:
        Single-row GeoDataFrame from ``validate_site`` (EPSG:27700).
    flood_zones:
        Flood Zones layer from :func:`load_flood_zones` (EPSG:27700), with
        columns ``flood_zone``, ``flood_source`` and ``origin``.

    Returns
    -------
    FloodZoneOverlapResult

    Raises
    ------
    TypeError
        If either input is not a GeoDataFrame.
    ValueError
        If either input has no CRS or does not resolve to EPSG:27700, if
        ``site`` does not contain exactly one row, or if ``flood_zones`` is
        missing a required column.

    Notes
    -----
    An empty but correctly shaped ``flood_zones`` layer (for example a bbox
    subset with nothing in it) yields a genuine zero result, not an error - the
    missing-source distinction is made in :func:`load_flood_zones`.
    Inputs are not reprojected and geometry is not repaired. Candidate polygons
    are found with the spatial index, clipped to the site, and only positive-area
    intersections are kept; a site that merely touches a boundary line or corner
    has no overlap. Per-zone geometry is unioned before its area is measured, and
    the headline ``affected_area_m2`` is the area of the union of every kept
    clipped polygon. Values are returned unrounded.
    """
    if not isinstance(site, gpd.GeoDataFrame):
        raise TypeError(
            f"site must be a geopandas.GeoDataFrame, got {type(site).__name__}"
        )
    if not isinstance(flood_zones, gpd.GeoDataFrame):
        raise TypeError(
            f"flood_zones must be a geopandas.GeoDataFrame, got {type(flood_zones).__name__}"
        )

    if site.crs is None:
        raise ValueError("site has no CRS defined; EPSG:27700 is required")
    if flood_zones.crs is None:
        raise ValueError("flood_zones has no CRS defined; EPSG:27700 is required")
    if site.crs.to_epsg() != EXPECTED_EPSG:
        raise ValueError(f"site CRS must be EPSG:27700; got EPSG:{site.crs.to_epsg()}")
    if flood_zones.crs.to_epsg() != EXPECTED_EPSG:
        raise ValueError(
            f"flood_zones CRS must be EPSG:27700; got EPSG:{flood_zones.crs.to_epsg()}"
        )

    if len(site) != 1:
        raise ValueError(f"site must contain exactly one row; got {len(site)}")

    missing = [c for c in _REQUIRED_ANALYSIS_COLUMNS if c not in flood_zones.columns]
    if missing:
        raise ValueError(f"flood_zones is missing required column(s): {missing}")

    site_geom = site.geometry.iloc[0]
    site_area_m2 = float(site_geom.area)

    if len(flood_zones):
        candidate_idx = flood_zones.sindex.query(site_geom, predicate="intersects")
        candidates = flood_zones.iloc[candidate_idx]
    else:
        candidates = flood_zones

    per_zone: dict[str, dict] = {}
    all_clipped: list = []
    all_sources: list = []
    all_origins: list = []
    for zone, source, origin, geom in zip(
        candidates["flood_zone"],
        candidates["flood_source"],
        candidates["origin"],
        candidates.geometry,
    ):
        clipped = geom.intersection(site_geom)
        if clipped.area <= 0:
            continue
        bucket = per_zone.setdefault(
            str(zone), {"geoms": [], "sources": [], "origins": []}
        )
        bucket["geoms"].append(clipped)
        bucket["sources"].append(source)
        bucket["origins"].append(origin)
        all_clipped.append(clipped)
        all_sources.append(source)
        all_origins.append(origin)

    if per_zone:
        records = []
        geoms = []
        for zone, bucket in per_zone.items():
            merged = union_all(bucket["geoms"])
            area_m2 = float(merged.area)
            records.append(
                {
                    "flood_zone": zone,
                    "intersection_area_m2": area_m2,
                    "intersection_area_ha": area_m2 / 10_000,
                    "site_pct": 100.0 * area_m2 / site_area_m2,
                    "flood_sources": ",".join(_distinct_non_null(bucket["sources"])),
                    "origins": ",".join(_distinct_non_null(bucket["origins"])),
                }
            )
            geoms.append(merged)
        attrs = pd.DataFrame.from_records(
            records, columns=[c for c in ZONE_COLUMNS if c != "geometry"]
        ).astype(
            {
                "intersection_area_m2": "float64",
                "intersection_area_ha": "float64",
                "site_pct": "float64",
            }
        )
        zones = gpd.GeoDataFrame(
            attrs, geometry=gpd.GeoSeries(geoms, index=attrs.index, crs=site.crs)
        )
        zones = (
            zones.sort_values(
                ["intersection_area_m2", "flood_zone"],
                ascending=[False, True],
                kind="stable",
            )
            .reset_index(drop=True)
            .loc[:, ZONE_COLUMNS]
        )
        affected_area_m2 = float(union_all(all_clipped).area)
    else:
        zones = _empty_zones(site.crs)
        affected_area_m2 = 0.0

    zone_count = len(zones)
    return FloodZoneOverlapResult(
        has_flood_zone_overlap=zone_count > 0,
        zone_count=zone_count,
        zones=zones,
        site_area_m2=site_area_m2,
        affected_area_m2=affected_area_m2,
        affected_area_ha=affected_area_m2 / 10_000,
        affected_pct=100.0 * affected_area_m2 / site_area_m2,
        flood_sources=tuple(_distinct_non_null(all_sources)),
        origins=tuple(_distinct_non_null(all_origins)),
    )
