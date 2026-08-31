"""Tests for :func:`environmental_site_screener.sssi.load_sssi`.

Each test builds a tiny synthetic source, writes it to a temporary GeoPackage via
``tmp_path``, and calls ``load_sssi`` on that file. Geometries are small
hand-constructed shapes with known expected answers.

Some malformed sources (null / empty / invalid geometry, zero-feature layers,
undefined CRS) depend on the GeoPackage writer/reader preserving the anomaly
through a round-trip. Where a round-trip normalises it away on this stack, the
affected test skips with an explanation rather than asserting a fake result.
"""

import warnings

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import MultiPolygon, Point, Polygon

from environmental_site_screener.sssi import load_sssi


def _square(x=0.0, y=0.0, size=1_000.0):
    return Polygon(
        [(x, y), (x, y + size), (x + size, y + size), (x + size, y), (x, y)]
    )


def _multi(x=0.0, y=0.0):
    return MultiPolygon([_square(x, y)])


def _multis(n):
    return [_multi(i * 5_000.0) for i in range(n)]


def _polys(n):
    return [_square(i * 5_000.0) for i in range(n)]


def _sssi_gdf(geometries, *, ref_codes=None, names=None, measures=None,
              crs="EPSG:27700"):
    n = len(geometries)
    if ref_codes is None:
        ref_codes = [f"S{i + 1}" for i in range(n)]
    if names is None:
        names = [f"Site {i + 1}" for i in range(n)]
    if measures is None:
        measures = [float((i + 1) * 10) for i in range(n)]
    return gpd.GeoDataFrame(
        {"ref_code": ref_codes, "name": names, "measure": measures},
        geometry=list(geometries),
        crs=crs,
    )


def _write(tmp_path, gdf, name="sssi.gpkg"):
    path = tmp_path / name
    gdf.to_file(path, driver="GPKG")
    return path


def _write_or_skip(tmp_path, gdf, name="sssi.gpkg"):
    path = tmp_path / name
    try:
        gdf.to_file(path, driver="GPKG")
    except Exception as exc:  # pragma: no cover - depends on GDAL build
        pytest.skip(f"GPKG writer could not represent this source: {exc!r}")
    return path


def test_loads_valid_multipolygon_source(tmp_path):
    path = _write(tmp_path, _sssi_gdf(_multis(3)))

    result = load_sssi(path)

    assert isinstance(result, gpd.GeoDataFrame)
    assert len(result) == 3
    assert result.crs.to_epsg() == 27700
    assert set(result.geometry.geom_type) == {"MultiPolygon"}


def test_loads_valid_polygon_source(tmp_path):
    path = _write(tmp_path, _sssi_gdf(_polys(3)))

    result = load_sssi(path)

    assert len(result) == 3
    assert set(result.geometry.geom_type) <= {"Polygon", "MultiPolygon"}


def test_output_columns_and_clean_index(tmp_path):
    gdf = _sssi_gdf(_multis(3))
    gdf["hyperlink"] = ["1005624", "1005625", "1005626"]
    gdf["contact_no"] = ["a", "b", "c"]
    gdf["label"] = ["x", "y", "z"]
    gdf["shape_length"] = [1.0, 2.0, 3.0]
    gdf["shape_area"] = [1.0, 2.0, 3.0]
    path = _write(tmp_path, gdf)

    result = load_sssi(path)

    assert list(result.columns) == ["ref_code", "name", "measure", "geometry"]
    assert result.index.equals(pd.RangeIndex(len(result)))


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_sssi(tmp_path / "does_not_exist.gpkg")


@pytest.mark.parametrize("drop_col", ["ref_code", "name", "measure"])
def test_missing_required_column_raises(tmp_path, drop_col):
    gdf = _sssi_gdf(_multis(3)).drop(columns=[drop_col])
    path = _write(tmp_path, gdf)

    with pytest.raises(ValueError, match=drop_col):
        load_sssi(path)


def test_wrong_crs_raises(tmp_path):
    gdf = _sssi_gdf(_multis(3)).to_crs("EPSG:4326")
    path = _write(tmp_path, gdf)

    with pytest.raises(ValueError, match="27700"):
        load_sssi(path)


def test_missing_crs_raises(tmp_path):
    gdf = _sssi_gdf(_multis(3)).set_crs(None, allow_override=True)
    # Writing a CRS-less GeoPackage is intentional here; pyogrio's matching
    # "'crs' was not provided" warning is expected for this fixture only.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="'crs' was not provided",
            category=UserWarning,
        )
        path = _write_or_skip(tmp_path, gdf, name="no_crs.gpkg")
    if gpd.read_file(path).crs is not None:
        pytest.skip("GPKG round-trip does not preserve an undefined CRS on this stack")

    with pytest.raises(ValueError, match="CRS"):
        load_sssi(path)


def test_invalid_geometry_raises(tmp_path):
    bowtie = Polygon([(0, 0), (0, 100), (100, 0), (100, 100), (0, 0)])
    assert not bowtie.is_valid
    gdf = _sssi_gdf([bowtie, _square(5_000.0)])
    path = _write_or_skip(tmp_path, gdf, name="invalid.gpkg")
    if gpd.read_file(path).geometry.is_valid.all():
        pytest.skip("GPKG round-trip repaired the invalid geometry on this stack")

    with pytest.raises(ValueError, match="invalid"):
        load_sssi(path)


def test_non_polygon_geometry_raises(tmp_path):
    gdf = _sssi_gdf([Point(0, 0), Point(1_000, 1_000)])
    path = _write(tmp_path, gdf, name="points.gpkg")

    with pytest.raises(ValueError, match="non-polygonal"):
        load_sssi(path)


def test_null_geometry_raises(tmp_path):
    gdf = _sssi_gdf([None, _square(5_000.0)])
    path = _write_or_skip(tmp_path, gdf, name="null_geom.gpkg")
    if not gpd.read_file(path).geometry.isna().any():
        pytest.skip("GPKG round-trip did not preserve a null geometry on this stack")

    with pytest.raises(ValueError, match="null"):
        load_sssi(path)


def test_empty_geometry_raises(tmp_path):
    gdf = _sssi_gdf([Polygon(), _square(5_000.0)])
    path = _write_or_skip(tmp_path, gdf, name="empty_geom.gpkg")
    first = gpd.read_file(path).geometry.iloc[0]
    if first is not None and not first.is_empty:
        pytest.skip("GPKG round-trip did not preserve an empty geometry on this stack")

    # An empty geometry may round-trip as null; the loader rejects either way.
    with pytest.raises(ValueError):
        load_sssi(path)


def test_duplicate_ref_code_raises(tmp_path):
    gdf = _sssi_gdf(_multis(3), ref_codes=["S1", "S2", "S1"])
    path = _write(tmp_path, gdf)

    with pytest.raises(ValueError, match="duplicate ref_code"):
        load_sssi(path)


def test_null_ref_code_raises(tmp_path):
    gdf = _sssi_gdf(_multis(3), ref_codes=["S1", None, "S3"])
    path = _write(tmp_path, gdf)

    with pytest.raises(ValueError, match="null ref_code"):
        load_sssi(path)


def test_null_name_raises(tmp_path):
    gdf = _sssi_gdf(_multis(3), names=["Alpha", None, "Gamma"])
    path = _write(tmp_path, gdf)

    with pytest.raises(ValueError, match="null name"):
        load_sssi(path)


def test_null_measure_is_accepted(tmp_path):
    gdf = _sssi_gdf(_multis(3), measures=[10.0, None, 30.0])
    path = _write(tmp_path, gdf)

    result = load_sssi(path)

    assert len(result) == 3
    assert int(result["measure"].isna().sum()) == 1


def test_empty_source_raises(tmp_path):
    gdf = _sssi_gdf([], ref_codes=[], names=[], measures=[])
    path = _write_or_skip(tmp_path, gdf, name="empty.gpkg")
    if not path.exists() or len(gpd.read_file(path)) != 0:
        pytest.skip("GPKG writer will not create a zero-feature layer on this stack")

    with pytest.raises(ValueError, match="no features"):
        load_sssi(path)
