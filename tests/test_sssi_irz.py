"""Tests for :mod:`environmental_site_screener.sssi_irz`.

Loader tests write tiny synthetic GeoPackages via ``tmp_path``. Context tests
build small in-memory GeoDataFrames. The candidate site is a 1,000 m square at
the origin in EPSG:27700 and IRZ polygons are simple rectangles, so every
expected result is easy to check by hand.
"""

import warnings
from dataclasses import FrozenInstanceError

import geopandas as gpd
import pytest
from shapely.geometry import MultiPolygon, Point, Polygon

from environmental_site_screener.sssi_irz import (
    SssiIrzContextResult,
    calculate_sssi_irz_context,
    load_sssi_irz,
)

CRS = "EPSG:27700"


def _url(code="0300000630000", notes=""):
    return (
        f"https://irz.geodata.org.uk/IRZ/step2.html?irzcode={code}"
        f"&notes={notes}&location=77215,11523 %20(IRZ%20polygon%20centre)"
    )


def _rect(xmin, ymin, xmax, ymax):
    return Polygon(
        [(xmin, ymin), (xmin, ymax), (xmax, ymax), (xmax, ymin), (xmin, ymin)]
    )


def _irz_source(geometries, urls=None, crs=CRS):
    """Build a GeoDataFrame shaped like the raw IRZ source (irzurl + geometry)."""
    n = len(geometries)
    if urls is None:
        urls = [_url() for _ in range(n)]
    return gpd.GeoDataFrame(
        {"irzurl": urls},
        geometry=gpd.GeoSeries(list(geometries), crs=crs),
        crs=crs,
    )


def _write(tmp_path, gdf, name="irz.gpkg"):
    path = tmp_path / name
    gdf.to_file(path, driver="GPKG")
    return path


def _write_or_skip(tmp_path, gdf, name="irz.gpkg"):
    path = tmp_path / name
    try:
        gdf.to_file(path, driver="GPKG")
    except Exception as exc:  # pragma: no cover - depends on GDAL build
        pytest.skip(f"GPKG writer could not represent this source: {exc!r}")
    return path


def _site(geom=None):
    return gpd.GeoDataFrame(
        geometry=[geom if geom is not None else _rect(0, 0, 1_000, 1_000)], crs=CRS
    )


def _irz(geometries, urls=None, codes=None, crs=CRS):
    """Build a GeoDataFrame shaped like load_sssi_irz output (irzurl + irz_code)."""
    n = len(geometries)
    if codes is None:
        codes = [f"{i:013d}" for i in range(n)]
    if urls is None:
        urls = [_url(c) for c in codes]
    return gpd.GeoDataFrame(
        {"irzurl": urls, "irz_code": codes},
        geometry=gpd.GeoSeries(list(geometries), crs=crs),
        crs=crs,
    )


# --------------------------------------------------------------------------- #
# loader
# --------------------------------------------------------------------------- #


def test_load_valid_source(tmp_path):
    gdf = _irz_source(
        [MultiPolygon([_rect(0, 0, 100, 100)]), MultiPolygon([_rect(200, 0, 300, 100)])],
        urls=[_url("0300000630000"), _url("0101254211121")],
    )

    out = load_sssi_irz(_write(tmp_path, gdf))

    assert isinstance(out, gpd.GeoDataFrame)
    assert list(out.columns) == ["irzurl", "irz_code", "geometry"]
    assert list(out.index) == [0, 1]
    assert out.crs.to_epsg() == 27700
    assert list(out["irz_code"]) == ["0300000630000", "0101254211121"]
    assert out["irzurl"].iloc[0] == _url("0300000630000")


def test_load_output_schema_drops_extra_columns(tmp_path):
    gdf = _irz_source([_rect(0, 0, 100, 100)])
    gdf["objectid"] = [7]
    gdf["extra"] = ["keep me out"]

    out = load_sssi_irz(_write(tmp_path, gdf))

    assert list(out.columns) == ["irzurl", "irz_code", "geometry"]
    assert out.geometry.name == "geometry"


def test_load_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_sssi_irz(tmp_path / "does_not_exist.gpkg")


def test_load_wrong_crs(tmp_path):
    gdf = _irz_source([_rect(0, 0, 100, 100)]).to_crs("EPSG:4326")

    with pytest.raises(ValueError, match="27700"):
        load_sssi_irz(_write(tmp_path, gdf))


def test_load_missing_crs(tmp_path):
    gdf = _irz_source([_rect(0, 0, 100, 100)]).set_crs(None, allow_override=True)
    path = tmp_path / "no_crs.gpkg"
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message="'crs' was not provided", category=UserWarning
        )
        gdf.to_file(path, driver="GPKG")
    if gpd.read_file(path).crs is not None:
        pytest.skip("GPKG round-trip did not preserve an undefined CRS on this stack")

    with pytest.raises(ValueError, match="CRS"):
        load_sssi_irz(path)


def test_load_missing_irzurl_column(tmp_path):
    gdf = _irz_source([_rect(0, 0, 100, 100)]).drop(columns=["irzurl"])

    with pytest.raises(ValueError, match="irzurl"):
        load_sssi_irz(_write(tmp_path, gdf))


def test_load_null_irzurl(tmp_path):
    gdf = _irz_source(
        [_rect(0, 0, 100, 100), _rect(200, 0, 300, 100)], urls=[_url(), None]
    )

    with pytest.raises(ValueError, match="null irzurl"):
        load_sssi_irz(_write(tmp_path, gdf))


def test_load_empty_irzurl(tmp_path):
    gdf = _irz_source(
        [_rect(0, 0, 100, 100), _rect(200, 0, 300, 100)], urls=[_url(), ""]
    )

    # Depending on the GPKG stack, "" may round-trip as "" or as NULL; both are
    # rejected by the loader.
    with pytest.raises(ValueError, match="irzurl"):
        load_sssi_irz(_write(tmp_path, gdf))


def test_load_non_polygon_geometry(tmp_path):
    gdf = gpd.GeoDataFrame(
        {"irzurl": [_url(), _url()]},
        geometry=[Point(0, 0), Point(1_000, 1_000)],
        crs=CRS,
    )

    with pytest.raises(ValueError, match="non-polygonal"):
        load_sssi_irz(_write(tmp_path, gdf, name="points.gpkg"))


def test_load_null_geometry(tmp_path):
    gdf = _irz_source([_rect(0, 0, 100, 100), None])
    path = _write_or_skip(tmp_path, gdf, name="null_geom.gpkg")
    if not gpd.read_file(path).geometry.isna().any():
        pytest.skip("GPKG round-trip did not preserve a null geometry on this stack")

    with pytest.raises(ValueError, match="null geometr"):
        load_sssi_irz(path)


def test_load_empty_geometry(tmp_path):
    gdf = _irz_source([_rect(0, 0, 100, 100), Polygon()])
    path = _write_or_skip(tmp_path, gdf, name="empty_geom.gpkg")
    back = gpd.read_file(path).geometry
    if not (back.isna().any() or back.is_empty.any()):
        pytest.skip("GPKG round-trip did not preserve an empty geometry on this stack")

    with pytest.raises(ValueError):
        load_sssi_irz(path)


def test_load_empty_source(tmp_path):
    gdf = _irz_source([])
    path = _write_or_skip(tmp_path, gdf, name="empty.gpkg")
    if len(gpd.read_file(path)) != 0:
        pytest.skip("GPKG writer will not create a zero-feature layer on this stack")

    with pytest.raises(ValueError, match="no features"):
        load_sssi_irz(path)


def test_load_invalid_geometry_warns_and_keeps_unchanged(tmp_path):
    bowtie = Polygon([(0, 0), (0, 100), (100, 0), (100, 100), (0, 0)])
    assert not bowtie.is_valid
    gdf = _irz_source([_rect(200, 0, 300, 100), bowtie])
    path = _write_or_skip(tmp_path, gdf, name="invalid.gpkg")
    if gpd.read_file(path).geometry.is_valid.all():
        pytest.skip("GPKG round-trip repaired the invalid geometry on this stack")

    with pytest.warns(UserWarning, match="invalid geometr"):
        out = load_sssi_irz(path)

    assert len(out) == 2
    assert int((~out.geometry.is_valid).sum()) == 1  # left unchanged, not repaired


def test_load_parses_13_digit_irz_code(tmp_path):
    gdf = _irz_source([_rect(0, 0, 100, 100)], urls=[_url("1234567890123")])

    out = load_sssi_irz(_write(tmp_path, gdf))

    assert out["irz_code"].iloc[0] == "1234567890123"


def test_load_unparseable_irz_code_warns_and_leaves_missing(tmp_path):
    no_code = "https://irz.geodata.org.uk/IRZ/step2.html?irzcode=&notes=&location=1,2"
    short_code = "https://irz.geodata.org.uk/IRZ/step2.html?irzcode=123&notes=&location=1,2"
    gdf = _irz_source(
        [_rect(0, 0, 100, 100), _rect(200, 0, 300, 100)], urls=[no_code, short_code]
    )

    with pytest.warns(UserWarning, match="parseable 13-digit irzcode"):
        out = load_sssi_irz(_write(tmp_path, gdf))

    assert out["irz_code"].isna().all()
    assert list(out["irzurl"]) == [no_code, short_code]  # preserved verbatim


# --------------------------------------------------------------------------- #
# context analysis
# --------------------------------------------------------------------------- #


def test_context_site_inside_one_zone():
    irz = _irz([_rect(-500, -500, 2_000, 2_000)], codes=["0300000630000"])

    result = calculate_sssi_irz_context(_site(), irz)

    assert result.has_irz_context is True
    assert result.zone_count == 1
    assert list(result.zones.columns) == ["irzurl", "irz_code", "geometry"]
    assert result.zones.crs.to_epsg() == 27700
    assert result.zones["irz_code"].iloc[0] == "0300000630000"
    assert result.advice_urls == (_url("0300000630000"),)
    # original IRZ geometry, not clipped to the site
    assert result.zones.geometry.iloc[0].equals(_rect(-500, -500, 2_000, 2_000))


def test_context_site_spans_two_adjacent_zones():
    irz = _irz(
        [_rect(-500, 0, 500, 1_000), _rect(500, 0, 1_500, 1_000)],
        codes=["0000000000001", "0000000000002"],
    )

    result = calculate_sssi_irz_context(_site(), irz)

    assert result.zone_count == 2
    assert list(result.zones["irz_code"]) == ["0000000000001", "0000000000002"]
    assert result.advice_urls == (_url("0000000000001"), _url("0000000000002"))


def test_context_no_intersection():
    irz = _irz([_rect(5_000, 5_000, 6_000, 6_000)])

    result = calculate_sssi_irz_context(_site(), irz)

    assert result.has_irz_context is False
    assert result.zone_count == 0
    assert list(result.zones.columns) == ["irzurl", "irz_code", "geometry"]
    assert result.zones.crs.to_epsg() == 27700
    assert len(result.zones) == 0
    assert result.advice_urls == ()


def test_context_boundary_touch_only_does_not_count():
    irz = _irz([_rect(1_000, 0, 2_000, 1_000)])  # shares the x=1000 edge only

    result = calculate_sssi_irz_context(_site(), irz)

    assert result.has_irz_context is False
    assert result.zone_count == 0
    assert result.advice_urls == ()


def test_context_two_rows_one_url():
    shared = _url("0300000630000")
    irz = _irz(
        [_rect(-100, 0, 500, 1_000), _rect(500, 0, 1_100, 1_000)],
        urls=[shared, shared],
        codes=["0300000630000", "0300000630000"],
    )

    result = calculate_sssi_irz_context(_site(), irz)

    assert result.zone_count == 2
    assert result.advice_urls == (shared,)


def test_context_empty_irz_layer_returns_zero_result():
    result = calculate_sssi_irz_context(_site(), _irz([]))

    assert result.has_irz_context is False
    assert result.zone_count == 0
    assert list(result.zones.columns) == ["irzurl", "irz_code", "geometry"]
    assert result.zones.crs.to_epsg() == 27700
    assert result.advice_urls == ()


@pytest.mark.parametrize("bad", ["site", "irz"])
def test_context_non_geodataframe_raises_type_error(bad):
    site, irz = _site(), _irz([_rect(0, 0, 100, 100)])
    not_a_gdf = [(0, 0), (0, 1), (1, 1)]
    if bad == "site":
        site = not_a_gdf
    else:
        irz = not_a_gdf

    with pytest.raises(TypeError, match=f"{bad} must be a geopandas.GeoDataFrame"):
        calculate_sssi_irz_context(site, irz)


@pytest.mark.parametrize("bad", ["site", "irz"])
def test_context_wrong_crs_raises(bad):
    site, irz = _site(), _irz([_rect(0, 0, 100, 100)])
    if bad == "site":
        site = site.to_crs("EPSG:4326")
    else:
        irz = irz.to_crs("EPSG:4326")

    with pytest.raises(ValueError, match="27700"):
        calculate_sssi_irz_context(site, irz)


@pytest.mark.parametrize("bad", ["site", "irz"])
def test_context_missing_crs_raises(bad):
    site, irz = _site(), _irz([_rect(0, 0, 100, 100)])
    if bad == "site":
        site = site.set_crs(None, allow_override=True)
    else:
        irz = irz.set_crs(None, allow_override=True)

    with pytest.raises(ValueError, match="CRS"):
        calculate_sssi_irz_context(site, irz)


def test_context_site_multiple_rows_raises():
    site = gpd.GeoDataFrame(
        geometry=[_rect(0, 0, 100, 100), _rect(200, 0, 300, 100)], crs=CRS
    )

    with pytest.raises(ValueError, match="exactly one row"):
        calculate_sssi_irz_context(site, _irz([_rect(0, 0, 100, 100)]))


@pytest.mark.parametrize("missing_col", ["irzurl", "irz_code"])
def test_context_missing_irz_column_raises(missing_col):
    irz = _irz([_rect(-500, -500, 2_000, 2_000)]).drop(columns=[missing_col])

    with pytest.raises(ValueError, match=missing_col):
        calculate_sssi_irz_context(_site(), irz)


def test_context_zone_schema_and_crs_are_exact():
    irz = _irz([_rect(-500, -500, 2_000, 2_000)])
    irz["objectid"] = [99]  # must not leak into zones

    result = calculate_sssi_irz_context(_site(), irz)

    assert list(result.zones.columns) == ["irzurl", "irz_code", "geometry"]
    assert result.zones.geometry.name == "geometry"
    assert result.zones.crs.to_epsg() == 27700


def test_result_is_frozen_dataclass():
    result = calculate_sssi_irz_context(
        _site(), _irz([_rect(-500, -500, 2_000, 2_000)])
    )

    assert isinstance(result, SssiIrzContextResult)
    with pytest.raises(FrozenInstanceError):
        result.has_irz_context = False
