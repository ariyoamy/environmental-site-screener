"""Tests for :func:`environmental_site_screener.site.validate_site`.

All geometries here are small synthetic shapes with known expected answers.
"""

import geopandas as gpd
import pytest
from shapely.geometry import LineString, MultiPolygon, Point, Polygon

from environmental_site_screener.site import ANALYTICAL_CRS, validate_site


def _square(origin=(0.0, 0.0), size=100.0):
    """Axis-aligned square polygon, used as a well-behaved site boundary."""
    x, y = origin
    return Polygon(
        [(x, y), (x, y + size), (x + size, y + size), (x + size, y), (x, y)]
    )


def test_accepts_valid_bng_polygon():
    poly = _square()
    gdf = gpd.GeoDataFrame({"site_id": ["A"]}, geometry=[poly], crs="EPSG:27700")

    result = validate_site(gdf)

    assert isinstance(result, gpd.GeoDataFrame)
    assert len(result) == 1
    assert result.crs.to_epsg() == 27700
    assert result.geometry.iloc[0].equals(poly)


def test_reprojects_wgs84_to_bng():
    # A small polygon near Newbury, England, defined in lon/lat.
    poly = Polygon(
        [(-1.32, 51.40), (-1.32, 51.41), (-1.31, 51.41), (-1.31, 51.40)]
    )
    gdf = gpd.GeoDataFrame(geometry=[poly], crs="EPSG:4326")

    result = validate_site(gdf)

    assert result.crs.to_epsg() == 27700
    # Coordinates are now projected metres (British National Grid), not degrees.
    minx, miny, maxx, maxy = result.total_bounds
    assert 400_000 < minx < 500_000
    assert 150_000 < miny < 200_000


def test_area_approximately_preserved_through_wgs84_round_trip():
    # 1 km square defined directly in British National Grid: area is 1,000,000 m^2.
    square_bng = _square(origin=(400_000.0, 300_000.0), size=1_000.0)
    bng = gpd.GeoDataFrame(geometry=[square_bng], crs="EPSG:27700")
    wgs84_input = bng.to_crs("EPSG:4326")

    result = validate_site(wgs84_input)

    assert result.geometry.iloc[0].area == pytest.approx(1_000_000, rel=0.01)


def test_rejects_non_geodataframe():
    with pytest.raises(TypeError):
        validate_site(_square())


def test_rejects_missing_crs():
    gdf = gpd.GeoDataFrame(geometry=[_square()])

    with pytest.raises(ValueError, match="CRS"):
        validate_site(gdf)


def test_rejects_empty_geodataframe():
    gdf = gpd.GeoDataFrame(geometry=[], crs="EPSG:27700")

    with pytest.raises(ValueError):
        validate_site(gdf)


def test_rejects_multiple_rows():
    gdf = gpd.GeoDataFrame(
        geometry=[_square(), _square(origin=(500.0, 500.0))],
        crs="EPSG:27700",
    )

    with pytest.raises(ValueError):
        validate_site(gdf)


def test_rejects_null_geometry():
    gdf = gpd.GeoDataFrame(geometry=[None], crs="EPSG:27700")

    with pytest.raises(ValueError):
        validate_site(gdf)


def test_rejects_empty_geometry():
    gdf = gpd.GeoDataFrame(geometry=[Polygon()], crs="EPSG:27700")

    with pytest.raises(ValueError):
        validate_site(gdf)


@pytest.mark.parametrize("geom", [Point(0, 0), LineString([(0, 0), (1, 1)])])
def test_rejects_non_polygon_geometry(geom):
    gdf = gpd.GeoDataFrame(geometry=[geom], crs="EPSG:27700")

    with pytest.raises(ValueError):
        validate_site(gdf)


def test_repairs_invalid_polygon_and_warns():
    # Classic self-intersecting "bowtie": invalid, but repairable.
    bowtie = Polygon([(0, 0), (0, 2), (2, 0), (2, 2), (0, 0)])
    assert not bowtie.is_valid
    gdf = gpd.GeoDataFrame(geometry=[bowtie], crs="EPSG:27700")

    with pytest.warns(UserWarning):
        result = validate_site(gdf)

    geom = result.geometry.iloc[0]
    assert geom.is_valid
    assert not geom.is_empty
    assert geom.geom_type in ("Polygon", "MultiPolygon")
    assert geom.area > 0


def test_preserves_input_attributes():
    # Realistic England lon/lat polygon so the reprojection step is well defined.
    poly = Polygon(
        [(-1.32, 51.40), (-1.32, 51.41), (-1.31, 51.41), (-1.31, 51.40)]
    )
    gdf = gpd.GeoDataFrame(
        {"site_id": ["site-42"], "note": ["candidate"]},
        geometry=[poly],
        crs="EPSG:4326",
    )

    result = validate_site(gdf)

    assert list(result["site_id"]) == ["site-42"]
    assert list(result["note"]) == ["candidate"]


def test_accepts_valid_multipolygon():
    multi = MultiPolygon([_square(), _square(origin=(500.0, 500.0))])
    assert multi.is_valid
    gdf = gpd.GeoDataFrame(geometry=[multi], crs="EPSG:27700")

    result = validate_site(gdf)

    geom = result.geometry.iloc[0]
    assert geom.geom_type == "MultiPolygon"
    assert geom.is_valid
    assert not geom.is_empty
    assert result.crs.to_epsg() == 27700


def test_does_not_mutate_input():
    poly = Polygon(
        [(-1.32, 51.40), (-1.32, 51.41), (-1.31, 51.41), (-1.31, 51.40)]
    )
    original = gpd.GeoDataFrame(geometry=[poly], crs="EPSG:4326")
    original_wkt = original.geometry.iloc[0].wkt

    result = validate_site(original)

    assert result.crs.to_epsg() == 27700
    assert original.crs.to_epsg() == 4326
    assert original.geometry.iloc[0].wkt == original_wkt
    assert original.geometry.iloc[0].equals(poly)
