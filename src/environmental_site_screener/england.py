"""England product-geography boundary and site eligibility.

The screening datasets are England-only (Natural England, Environment Agency), so
a candidate site outside England would screen "clear" against every theme and
report a misleading nearest-English-SSSI distance. This module builds an explicit
England product boundary and classifies whether a candidate site may be screened.

The boundary is built from the local Ordnance Survey Boundary-Line **ceremonial
counties** source already bundled for the Ancient Woodland revised-coverage
inference (``data/raw/ancient_woodland/coverage/``). That file is GB-wide, so the
English extent is taken from an explicit, reviewed allow-list of the 48 English
ceremonial-county names in its ``NAME`` field - England is never inferred from
"not obviously Scottish/Welsh", nor from environmental-data extent.

Nothing here imports Streamlit or PyDeck; it is plain GeoPandas/Shapely and stays
unit-testable. Geometry work is in EPSG:27700, matching the analytical CRS.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd

ANALYTICAL_CRS = "EPSG:27700"

# The 48 ceremonial counties of England, exactly as they appear in the OS
# Boundary-Line ``NAME`` field. Reviewed against the full 91-row GB file: the
# remaining 43 names are the 35 Scottish councils/lieutenancy areas and the 8
# Welsh preserved counties (Clwyd, Dyfed, Gwent, Gwynedd, Powys, and the three
# Glamorgans). 91 - 43 = 48, which matches the known count of English ceremonial
# counties - the cross-check the loader asserts.
ENGLAND_CEREMONIAL_COUNTIES: frozenset[str] = frozenset(
    {
        "Bedfordshire",
        "Berkshire",
        "Bristol",
        "Buckinghamshire",
        "Cambridgeshire",
        "Cheshire",
        "City and County of the City of London",
        "Cornwall",
        "Cumbria",
        "Derbyshire",
        "Devon",
        "Dorset",
        "Durham",
        "East Riding of Yorkshire",
        "East Sussex",
        "Essex",
        "Gloucestershire",
        "Greater London",
        "Greater Manchester",
        "Hampshire",
        "Herefordshire",
        "Hertfordshire",
        "Isle of Wight",
        "Kent",
        "Lancashire",
        "Leicestershire",
        "Lincolnshire",
        "Merseyside",
        "Norfolk",
        "North Yorkshire",
        "Northamptonshire",
        "Northumberland",
        "Nottinghamshire",
        "Oxfordshire",
        "Rutland",
        "Shropshire",
        "Somerset",
        "South Yorkshire",
        "Staffordshire",
        "Suffolk",
        "Surrey",
        "Tyne & Wear",
        "Warwickshire",
        "West Midlands",
        "West Sussex",
        "West Yorkshire",
        "Wiltshire",
        "Worcestershire",
    }
)

# Eligibility outcomes for classify_site_england_eligibility().
ELIGIBLE = "eligible"
OUTSIDE = "outside"
CROSSES = "crosses"

# A candidate site may sit a whisker outside the generalised county boundary at
# the coast or an exact shared border purely from vertex precision. Anything up
# to this many square metres outside England is treated as fully within - a
# numerical tolerance, not a spatial buffer (it never grows England).
BOUNDARY_TOLERANCE_M2 = 1.0


def load_england_boundary(path: str | Path) -> gpd.GeoDataFrame:
    """Build the England product boundary from the OS Boundary-Line source.

    Parameters
    ----------
    path:
        The ``Boundary-line-ceremonial-counties_region.shp`` shapefile (the same
        file used for Ancient Woodland revised coverage).

    Returns
    -------
    geopandas.GeoDataFrame
        One row, ``name="England"``, geometry the union of the 48 English
        ceremonial counties, in EPSG:27700.

    Raises
    ------
    FileNotFoundError
        If ``path`` does not exist.
    ValueError
        If the source is missing the expected columns, is not in EPSG:27700, is
        missing any expected English county, or the resulting union is empty or
        invalid.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Boundary-Line source not found: {path}")

    counties = gpd.read_file(path)
    missing_columns = {"NAME", "geometry"} - set(counties.columns)
    if missing_columns:
        raise ValueError(
            f"Boundary-Line source is missing column(s): {sorted(missing_columns)}"
        )
    if counties.crs is None or counties.crs.to_epsg() != 27700:
        raise ValueError(
            f"Boundary-Line source must be EPSG:27700, got {counties.crs}"
        )

    english = counties[counties["NAME"].isin(ENGLAND_CEREMONIAL_COUNTIES)]
    found = set(english["NAME"])
    missing_counties = ENGLAND_CEREMONIAL_COUNTIES - found
    if missing_counties:
        raise ValueError(
            "Boundary-Line source is missing expected English "
            f"county/counties: {sorted(missing_counties)}"
        )

    if english.geometry.isna().any() or english.geometry.is_empty.any():
        raise ValueError("Boundary-Line source has a missing/empty English geometry")
    # The one invalid geometry in this file (Shetland, a self-intersection) is
    # Scottish and excluded here, so no repair of the authoritative data is
    # needed; guard the assumption rather than silently trusting it.
    if not english.geometry.is_valid.all():
        raise ValueError(
            "Unexpected invalid geometry among the English counties; refusing to "
            "silently repair authoritative Boundary-Line data"
        )

    union = english.geometry.union_all()
    if union.is_empty or not union.is_valid:
        raise ValueError("England boundary union is empty or invalid")

    return gpd.GeoDataFrame({"name": ["England"]}, geometry=[union], crs=ANALYTICAL_CRS)


def classify_site_england_eligibility(
    site: gpd.GeoDataFrame, england_boundary: gpd.GeoDataFrame
) -> str:
    """Classify a validated candidate site against the England product boundary.

    Both inputs must be in EPSG:27700 (``site`` is the output of
    :func:`environmental_site_screener.site.validate_site`).

    Returns
    -------
    str
        - :data:`ELIGIBLE` - the site is fully within England (within
          :data:`BOUNDARY_TOLERANCE_M2` at the edge);
        - :data:`CROSSES` - the site is partly inside and partly outside;
        - :data:`OUTSIDE` - the site does not touch England at all.

    The site is never clipped and the English portion is never screened on its
    own; a non-eligible site must not be passed to ``screen_site``.
    """
    if site.crs is None or site.crs.to_epsg() != 27700:
        raise ValueError("site must be in EPSG:27700 before eligibility classification")

    site_geom = site.geometry.union_all()
    england_geom = england_boundary.geometry.union_all()

    if not site_geom.intersects(england_geom):
        return OUTSIDE
    if site_geom.difference(england_geom).area <= BOUNDARY_TOLERANCE_M2:
        return ELIGIBLE
    return CROSSES
