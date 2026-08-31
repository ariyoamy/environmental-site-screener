"""Tests for :func:`environmental_site_screener.distance.calculate_nearest_sssi`.

The candidate site is a 1,000 m x 1,000 m square at the origin in EPSG:27700.
SSSI features are simple metre-based polygons, so every expected distance is
easy to verify by hand.
"""

from dataclasses import FrozenInstanceError

import geopandas as gpd
import pytest
from shapely.geometry import MultiPolygon, Polygon

from environmental_site_screener.distance import (
    FEATURE_COLUMNS,
    NearestSssiResult,
    calculate_nearest_sssi,
)

CRS = "EPSG:27700"


def _rect(xmin, ymin, xmax, ymax):
    return Polygon(
        [(xmin, ymin), (xmin, ymax), (xmax, ymax), (xmax, ymin), (xmin, ymin)]
    )


def _site():
    return gpd.GeoDataFrame(geometry=[_rect(0, 0, 1_000, 1_000)], crs=CRS)


def _sssi(geometries, *, ref_codes=None, names=None, measures=None, crs=CRS):
    n = len(geometries)
    if ref_codes is None:
        ref_codes = [f"S{i + 1}" for i in range(n)]
    if names is None:
        names = [f"Name {i + 1}" for i in range(n)]
    if measures is None:
        measures = [float((i + 1) * 10) for i in range(n)]
    return gpd.GeoDataFrame(
        {"ref_code": ref_codes, "name": names, "measure": measures},
        geometry=gpd.GeoSeries(list(geometries), crs=crs),
        crs=crs,
    )


def test_single_sssi_100m_away():
    sssi = _sssi([_rect(1_100, 0, 1_600, 1_000)])  # gap x=1000..1100

    result = calculate_nearest_sssi(_site(), sssi)

    assert isinstance(result, NearestSssiResult)
    assert result.distance_m == pytest.approx(100.0)
    assert result.distance_km == pytest.approx(0.1)
    assert result.feature_count == 1
    assert list(result.features["ref_code"]) == ["S1"]
    assert result.features.crs.to_epsg() == 27700


def test_selects_nearest_of_several():
    sssi = _sssi(
        [
            _rect(1_100, 0, 1_200, 1_000),  # 100 m
            _rect(1_300, 0, 1_400, 1_000),  # 300 m
            _rect(1_800, 0, 1_900, 1_000),  # 800 m
        ],
        ref_codes=["near", "mid", "far"],
    )

    result = calculate_nearest_sssi(_site(), sssi)

    assert result.distance_m == pytest.approx(100.0)
    assert result.feature_count == 1
    assert list(result.features["ref_code"]) == ["near"]


def test_corner_to_corner_euclidean_distance():
    sssi = _sssi([_rect(1_300, 1_300, 2_000, 2_000)])
    # nearest points: site corner (1000, 1000) to SSSI corner (1300, 1300)
    expected = (300.0**2 + 300.0**2) ** 0.5

    result = calculate_nearest_sssi(_site(), sssi)

    assert result.distance_m == pytest.approx(expected)
    assert result.distance_m == pytest.approx(424.264, abs=1e-3)


def test_boundary_touch_returns_zero():
    sssi = _sssi([_rect(1_000, 0, 2_000, 1_000)])  # shares the x=1000 edge

    result = calculate_nearest_sssi(_site(), sssi)

    assert result.distance_m == 0.0
    assert result.distance_km == 0.0
    assert result.feature_count == 1


def test_positive_area_overlap_returns_zero():
    sssi = _sssi([_rect(500, 0, 1_500, 1_000)])  # overlaps the right half

    result = calculate_nearest_sssi(_site(), sssi)

    assert result.distance_m == 0.0
    assert result.feature_count == 1


def test_two_equidistant_sssis_are_both_returned():
    sssi = _sssi(
        [
            _rect(1_100, 0, 1_600, 1_000),  # 100 m east
            _rect(-600, 0, -100, 1_000),  # 100 m west
        ],
        ref_codes=["S_east", "S_west"],
    )

    result = calculate_nearest_sssi(_site(), sssi)

    assert result.distance_m == pytest.approx(100.0)
    assert result.feature_count == 2
    assert list(result.features["ref_code"]) == ["S_east", "S_west"]


def test_tied_features_sorted_by_ref_code():
    sssi = _sssi(
        [
            _rect(1_100, 0, 1_600, 1_000),  # 100 m east
            _rect(-600, 0, -100, 1_000),  # 100 m west
            _rect(0, 1_100, 1_000, 1_600),  # 100 m north
        ],
        ref_codes=["zzz", "aaa", "mmm"],
    )

    result = calculate_nearest_sssi(_site(), sssi)

    assert result.feature_count == 3
    assert list(result.features["ref_code"]) == ["aaa", "mmm", "zzz"]


def test_empty_sssi_layer_raises():
    with pytest.raises(ValueError, match="no features"):
        calculate_nearest_sssi(_site(), _sssi([]))


@pytest.mark.parametrize("bad", ["site", "sssi"])
def test_wrong_crs_raises(bad):
    site = _site()
    sssi = _sssi([_rect(1_100, 0, 1_600, 1_000)])
    if bad == "site":
        site = site.to_crs("EPSG:4326")
    else:
        sssi = sssi.to_crs("EPSG:4326")

    with pytest.raises(ValueError, match="27700"):
        calculate_nearest_sssi(site, sssi)


@pytest.mark.parametrize("bad", ["site", "sssi"])
def test_missing_crs_raises(bad):
    site = _site()
    sssi = _sssi([_rect(1_100, 0, 1_600, 1_000)])
    if bad == "site":
        site = site.set_crs(None, allow_override=True)
    else:
        sssi = sssi.set_crs(None, allow_override=True)

    with pytest.raises(ValueError, match="CRS"):
        calculate_nearest_sssi(site, sssi)


@pytest.mark.parametrize("bad", ["site", "sssi"])
def test_non_geodataframe_input_raises_type_error(bad):
    site = _site()
    sssi = _sssi([_rect(1_100, 0, 1_600, 1_000)])
    not_a_gdf = [(0, 0), (0, 1), (1, 1)]
    if bad == "site":
        site = not_a_gdf
    else:
        sssi = not_a_gdf

    with pytest.raises(TypeError, match=f"{bad} must be a geopandas.GeoDataFrame"):
        calculate_nearest_sssi(site, sssi)


@pytest.mark.parametrize("missing_col", ["ref_code", "name", "measure"])
def test_missing_required_sssi_column_raises(missing_col):
    sssi = _sssi([_rect(1_100, 0, 1_600, 1_000)]).drop(columns=[missing_col])

    with pytest.raises(ValueError, match=missing_col):
        calculate_nearest_sssi(_site(), sssi)


def test_site_with_multiple_rows_raises():
    site = gpd.GeoDataFrame(
        geometry=[_rect(0, 0, 1_000, 1_000), _rect(2_000, 2_000, 3_000, 3_000)],
        crs=CRS,
    )
    sssi = _sssi([_rect(1_100, 0, 1_600, 1_000)])

    with pytest.raises(ValueError, match="exactly one row"):
        calculate_nearest_sssi(site, sssi)


def test_multipolygon_nearest_component_determines_distance():
    near_part = _rect(1_100, 0, 1_200, 1_000)  # 100 m from the site
    far_part = _rect(5_000, 5_000, 6_000, 6_000)
    sssi = _sssi([MultiPolygon([near_part, far_part])], ref_codes=["M1"])

    result = calculate_nearest_sssi(_site(), sssi)

    assert result.distance_m == pytest.approx(100.0)
    assert result.feature_count == 1
    assert list(result.features["ref_code"]) == ["M1"]
    assert result.features.geometry.iloc[0].geom_type == "MultiPolygon"


def test_returns_original_unclipped_geometry():
    rect = _rect(1_100, 0, 1_600, 1_000)
    sssi = _sssi([rect])

    result = calculate_nearest_sssi(_site(), sssi)

    assert result.features.geometry.iloc[0].equals(rect)


def test_null_measure_passes_through():
    sssi = _sssi([_rect(1_100, 0, 1_600, 1_000)], measures=[None])

    result = calculate_nearest_sssi(_site(), sssi)

    assert result.feature_count == 1
    assert result.features["measure"].isna().all()


def test_metre_to_kilometre_conversion():
    sssi = _sssi([_rect(3_000, 0, 4_000, 1_000)])  # 2,000 m from the site

    result = calculate_nearest_sssi(_site(), sssi)

    assert result.distance_m == pytest.approx(2_000.0)
    assert result.distance_km == pytest.approx(2.0)
    assert result.distance_km == result.distance_m / 1000


def test_feature_output_columns_and_crs_are_exact():
    sssi = _sssi([_rect(1_100, 0, 1_600, 1_000)])
    sssi["hyperlink"] = ["1005624"]  # must not leak into the result
    sssi["shape_area"] = [123.0]

    result = calculate_nearest_sssi(_site(), sssi)

    assert list(result.features.columns) == ["ref_code", "name", "measure", "geometry"]
    assert list(result.features.columns) == FEATURE_COLUMNS
    assert result.features.geometry.name == "geometry"
    assert result.features.crs.to_epsg() == 27700


def test_result_is_frozen_dataclass():
    result = calculate_nearest_sssi(_site(), _sssi([_rect(1_100, 0, 1_600, 1_000)]))

    assert isinstance(result, NearestSssiResult)
    with pytest.raises(FrozenInstanceError):
        result.distance_m = 0.0
