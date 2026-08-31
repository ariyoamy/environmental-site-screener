"""Loader and context check for Natural England SSSI Impact Risk Zones (IRZ).

The documented attribute on the SSSI IRZ source is ``irzurl``: a hyperlink to
Natural England's online IRZ advice. Each URL contains a 13-digit ``irzcode``
value. This project preserves that code as an opaque string (``irz_code``) and
does not interpret its individual digits. The actual advice (which development
types and scales matter, and any statutory advice) is obtained from Natural
England through the ``irzurl``.

Inspection of the 31 August 2026 source used for this project found the IRZ
polygons behave as an effectively non-overlapping coverage: they share
boundaries and produce only negligible floating-point sliver overlaps. The
analysis here does not rely on this remaining true in future releases -
:func:`calculate_sssi_irz_context` simply returns every IRZ polygon the site
intersects with positive area.

This module:

- :func:`load_sssi_irz` reads and checks the source, keeps ``irzurl``, parses the
  13-digit ``irzcode`` into ``irz_code`` as an opaque string, and returns those
  two fields plus geometry in EPSG:27700;
- :func:`calculate_sssi_irz_context` reports whether part of a candidate site
  falls inside one or more IRZ polygons, and hands back those polygons and their
  advice URLs.

Nothing here interprets the code digits, ranks zones, measures how much of the
site is covered, measures distance, or draws any planning, legal or impact
conclusion. Natural England's User Guidance lists the development categories the
IRZ tool considers; whether any apply to a given site depends on the proposed
development and must be checked through the ``irzurl``.
"""

from __future__ import annotations

import pathlib
import re
import warnings
from dataclasses import dataclass

import geopandas as gpd

EXPECTED_EPSG = 27700

IRZ_OUTPUT_COLUMNS = ["irzurl", "irz_code", "geometry"]
ZONE_COLUMNS = ["irzurl", "irz_code", "geometry"]

_ALLOWED_GEOM_TYPES = ("Polygon", "MultiPolygon")

# The advice URL contains "irzcode=<13 digits>". The per-digit meaning is
# resolved by Natural England's online tool and is deliberately not interpreted
# here; the code is kept only as an opaque string.
_IRZ_CODE_RE = re.compile(r"[?&]irzcode=(\d+)")
_IRZ_CODE_LENGTH = 13


def _parse_irz_code(url: str) -> str | None:
    """Return the 13-digit ``irzcode`` from an IRZ advice URL, or ``None``."""
    match = _IRZ_CODE_RE.search(str(url))
    if match is None:
        return None
    digits = match.group(1)
    if len(digits) != _IRZ_CODE_LENGTH:
        return None
    return digits


def load_sssi_irz(path: str | pathlib.Path) -> gpd.GeoDataFrame:
    """Load and validate the Natural England SSSI Impact Risk Zones source file.

    Parameters
    ----------
    path:
        Path to the SSSI IRZ spatial file (the official GeoPackage).

    Returns
    -------
    geopandas.GeoDataFrame
        Columns ``irzurl``, ``irz_code`` and ``geometry`` (in that order), in
        EPSG:27700, with a clean ``RangeIndex``. ``irzurl`` is preserved
        verbatim. ``irz_code`` is the 13-digit ``irzcode`` parsed from the URL,
        or missing where no 13-digit code could be parsed.

    Raises
    ------
    FileNotFoundError
        If ``path`` does not exist.
    ValueError
        If the source has no features, no active geometry column, no ``irzurl``
        column, any null or empty ``irzurl``, no CRS, a CRS that is not
        EPSG:27700, or any null, empty or non-polygonal geometry.

    Warns
    -----
    UserWarning
        Once, with a count, if the source contains invalid geometry (left
        unchanged, not repaired). Once, with a count, if any ``irzurl`` has no
        parseable 13-digit ``irzcode`` (``irz_code`` left missing for those
        rows).

    Notes
    -----
    Read errors for an existing but unreadable source propagate from
    GeoPandas/pyogrio unchanged. The source is not reprojected and its geometry
    is not repaired. ``irzurl`` is not required to be unique and rows are not
    de-duplicated. The URL's ``notes=`` and ``location=`` parameters are ignored.
    """
    source = pathlib.Path(path)
    if not source.exists():
        raise FileNotFoundError(f"SSSI IRZ source file not found: {source}")

    gdf = gpd.read_file(source)

    try:
        geom_col = gdf.geometry.name
    except AttributeError as exc:
        raise ValueError("SSSI IRZ source has no active geometry column") from exc

    if len(gdf) == 0:
        raise ValueError("SSSI IRZ source contains no features")

    if "irzurl" not in gdf.columns:
        raise ValueError("SSSI IRZ source is missing required column: 'irzurl'")

    if gdf.crs is None:
        raise ValueError("SSSI IRZ source has no CRS defined; expected EPSG:27700")

    epsg = gdf.crs.to_epsg()
    if epsg != EXPECTED_EPSG:
        raise ValueError(
            f"SSSI IRZ source CRS is {gdf.crs.name!r} (EPSG:{epsg}); expected EPSG:27700. "
            "This loader does not reproject the authoritative SSSI IRZ source."
        )

    irzurl = gdf["irzurl"]
    null_url = int(irzurl.isna().sum())
    if null_url:
        raise ValueError(f"SSSI IRZ source has {null_url} null irzurl values")
    empty_url = int((irzurl.astype("string").str.len() == 0).sum())
    if empty_url:
        raise ValueError(f"SSSI IRZ source has {empty_url} empty irzurl values")

    geometry = gdf.geometry
    null_geom = int(geometry.isna().sum())
    if null_geom:
        raise ValueError(f"SSSI IRZ source contains {null_geom} null geometries")
    empty_geom = int(geometry.is_empty.sum())
    if empty_geom:
        raise ValueError(f"SSSI IRZ source contains {empty_geom} empty geometries")
    bad_types = sorted(set(geometry.geom_type) - set(_ALLOWED_GEOM_TYPES))
    if bad_types:
        raise ValueError(
            f"SSSI IRZ source contains non-polygonal geometry (types found: {bad_types})"
        )

    invalid_count = int((~geometry.is_valid).sum())
    if invalid_count:
        warnings.warn(
            f"SSSI IRZ source contains {invalid_count} invalid geometries; they are "
            "left unchanged (this loader does not repair authoritative source data)",
            UserWarning,
            stacklevel=2,
        )

    irz_code = irzurl.map(_parse_irz_code)
    unparseable = int(irz_code.isna().sum())
    if unparseable:
        warnings.warn(
            f"SSSI IRZ source has {unparseable} irzurl value(s) with no parseable "
            "13-digit irzcode; irz_code is left missing for those rows",
            UserWarning,
            stacklevel=2,
        )

    result = gdf.loc[:, ["irzurl", geom_col]].copy()
    result["irz_code"] = irz_code.to_numpy()
    if geom_col != "geometry":
        result = result.rename_geometry("geometry")
    result = result.loc[:, IRZ_OUTPUT_COLUMNS]
    return result.reset_index(drop=True)


@dataclass(frozen=True)
class SssiIrzContextResult:
    """Result of an SSSI IRZ context check for one candidate site.

    Attributes
    ----------
    has_irz_context:
        ``True`` only means that part of the candidate site falls within one or
        more mapped SSSI Impact Risk Zone advice areas. It does **not** mean that
        development will harm an SSSI, that Natural England consultation is
        automatically required, that development is unsuitable, or that any
        planning or legal conclusion has been reached. The actual advice depends
        on the type and scale of the proposed development and must be checked
        through the Natural England ``irzurl``.
    zone_count:
        Number of IRZ polygons the site intersects with positive area.
    zones:
        Those IRZ polygons, columns ``irzurl``, ``irz_code`` and ``geometry``
        (the original, unclipped IRZ geometry), EPSG:27700, sorted by ``irzurl``.
        Empty with this schema when there is no context.
    advice_urls:
        Sorted tuple of the distinct non-empty ``irzurl`` values in ``zones``.
    """

    has_irz_context: bool
    zone_count: int
    zones: gpd.GeoDataFrame
    advice_urls: tuple[str, ...]


def calculate_sssi_irz_context(
    site: gpd.GeoDataFrame, irz: gpd.GeoDataFrame
) -> SssiIrzContextResult:
    """Report whether a candidate site falls within mapped SSSI IRZ advice areas.

    Parameters
    ----------
    site:
        Single-row GeoDataFrame from ``validate_site`` (EPSG:27700).
    irz:
        SSSI IRZ layer from ``load_sssi_irz`` (EPSG:27700), with columns
        ``irzurl`` and ``irz_code``.

    Returns
    -------
    SssiIrzContextResult

    Raises
    ------
    TypeError
        If either input is not a GeoDataFrame.
    ValueError
        If either input has no CRS, if either input does not resolve to
        EPSG:27700, if ``site`` does not contain exactly one row, or if ``irz``
        is missing ``irzurl`` or ``irz_code``.

    Notes
    -----
    This is a context/intersection check only. It does not reproject or repair
    geometry, and it does not calculate overlap area, overlap percentage,
    nearest-IRZ distance, a risk score, a consultation outcome or a development
    suitability judgement. Only positive-area intersection counts: a site that
    merely touches an IRZ boundary line or corner has no IRZ context. The
    temporary site/IRZ intersection geometry used for that test is discarded;
    ``zones`` holds the original IRZ polygons.
    """
    if not isinstance(site, gpd.GeoDataFrame):
        raise TypeError(
            f"site must be a geopandas.GeoDataFrame, got {type(site).__name__}"
        )
    if not isinstance(irz, gpd.GeoDataFrame):
        raise TypeError(
            f"irz must be a geopandas.GeoDataFrame, got {type(irz).__name__}"
        )

    if site.crs is None:
        raise ValueError("site has no CRS defined; EPSG:27700 is required")
    if irz.crs is None:
        raise ValueError("irz has no CRS defined; EPSG:27700 is required")

    if site.crs.to_epsg() != EXPECTED_EPSG:
        raise ValueError(
            f"site CRS must be EPSG:27700; got EPSG:{site.crs.to_epsg()}"
        )
    if irz.crs.to_epsg() != EXPECTED_EPSG:
        raise ValueError(
            f"irz CRS must be EPSG:27700; got EPSG:{irz.crs.to_epsg()}"
        )

    if len(site) != 1:
        raise ValueError(f"site must contain exactly one row; got {len(site)}")

    missing = [c for c in ("irzurl", "irz_code") if c not in irz.columns]
    if missing:
        raise ValueError(f"irz is missing required column(s): {missing}")

    site_geom = site.geometry.iloc[0]
    # Narrow to bounding-box candidates via the spatial index (~208k polygons in
    # the real source), then confirm true intersection below. The query result
    # order is not guaranteed, but ``zones`` is sorted by ``irzurl`` at the end.
    candidate_idx = irz.sindex.query(site_geom, predicate="intersects")
    candidates = irz.iloc[candidate_idx]

    positive_area = candidates.geometry.intersection(site_geom).area > 0
    zones = candidates.loc[positive_area, ZONE_COLUMNS].copy()
    zones = zones.sort_values("irzurl", kind="stable").reset_index(drop=True)

    advice_urls = tuple(
        sorted({u for u in zones["irzurl"].tolist() if isinstance(u, str) and u})
    )

    return SssiIrzContextResult(
        has_irz_context=len(zones) > 0,
        zone_count=len(zones),
        zones=zones,
        advice_urls=advice_urls,
    )
