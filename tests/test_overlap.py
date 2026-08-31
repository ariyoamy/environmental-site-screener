"""Tests for :func:`environmental_site_screener.overlap.calculate_sssi_overlap`.

The candidate site is a 1,000 m x 1,000 m square at the origin in EPSG:27700
(1,000,000 m^2 = 100 ha). SSSI features are axis-aligned rectangles with integer
coordinates, so every expected area is exact.
"""

from dataclasses import FrozenInstanceError

import geopandas as gpd
import pytest
from shapely.geometry import MultiPolygon, Polygon

from environmental_site_screener.overlap import (
    FEATURE_COLUMNS,
    SssiOverlapResult,
    calculate_sssi_overlap,
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


def test_no_overlap_returns_zero_result():
    result = calculate_sssi_overlap(_site(), _sssi([_rect(5_000, 5_000, 6_000, 6_000)]))

    assert result.has_overlap is False
    assert result.feature_count == 0
    assert list(result.features.columns) == FEATURE_COLUMNS
    assert len(result.features) == 0
    assert result.features.crs.to_epsg() == 27700
    assert result.site_area_m2 == pytest.approx(1_000_000)
    assert result.affected_area_m2 == 0.0
    assert result.affected_area_ha == 0.0
    assert result.affected_pct == 0.0


def test_complete_overlap():
    sssi = _sssi([_rect(-100, -100, 1_100, 1_100)])  # fully covers the site

    result = calculate_sssi_overlap(_site(), sssi)

    assert result.has_overlap is True
    assert result.feature_count == 1
    row = result.features.iloc[0]
    assert row["intersection_area_m2"] == pytest.approx(1_000_000)
    assert row["intersection_area_ha"] == pytest.approx(100)
    assert row.geometry.equals(_rect(0, 0, 1_000, 1_000))
    assert result.affected_area_m2 == pytest.approx(1_000_000)
    assert result.affected_area_ha == pytest.approx(100)
    assert result.affected_pct == pytest.approx(100)


def test_partial_overlap_50_percent():
    sssi = _sssi([_rect(500, 0, 1_500, 1_000)])  # right half -> 500,000 m^2

    result = calculate_sssi_overlap(_site(), sssi)

    assert result.feature_count == 1
    row = result.features.iloc[0]
    assert row["intersection_area_m2"] == pytest.approx(500_000)
    assert row.geometry.equals(_rect(500, 0, 1_000, 1_000))
    assert result.affected_area_m2 == pytest.approx(500_000)
    assert result.affected_area_ha == pytest.approx(50)
    assert result.affected_pct == pytest.approx(50)


def test_two_disjoint_sssis():
    sssi = _sssi(
        [
            _rect(0, 0, 250, 1_000),  # 250,000 m^2
            _rect(750, 0, 1_000, 1_000),  # 250,000 m^2
        ]
    )

    result = calculate_sssi_overlap(_site(), sssi)

    assert result.feature_count == 2
    assert sorted(result.features["intersection_area_m2"]) == pytest.approx(
        [250_000, 250_000]
    )
    assert result.affected_area_m2 == pytest.approx(500_000)
    assert result.affected_pct == pytest.approx(50)


def test_two_overlapping_sssis_not_double_counted():
    sssi = _sssi(
        [
            _rect(0, 0, 600, 1_000),  # 600,000 m^2 within the site
            _rect(400, 0, 1_000, 1_000),  # 600,000 m^2 within the site
        ]
    )

    result = calculate_sssi_overlap(_site(), sssi)

    assert result.feature_count == 2
    per_feature = list(result.features["intersection_area_m2"])
    assert sum(per_feature) == pytest.approx(1_200_000)

    assert result.affected_area_m2 == pytest.approx(1_000_000)
    assert result.affected_area_m2 != pytest.approx(1_200_000)
    assert result.affected_pct == pytest.approx(100)
    assert result.affected_pct != pytest.approx(120)


def test_boundary_touch_only_is_not_overlap():
    sssi = _sssi([_rect(1_000, 0, 2_000, 1_000)])  # shares the x=1000 edge only

    result = calculate_sssi_overlap(_site(), sssi)

    assert result.has_overlap is False
    assert result.feature_count == 0
    assert len(result.features) == 0
    assert result.affected_area_m2 == 0.0
    assert result.affected_pct == 0.0


def test_empty_sssi_layer_returns_zero_result():
    sssi = _sssi([])

    result = calculate_sssi_overlap(_site(), sssi)

    assert result.has_overlap is False
    assert result.feature_count == 0
    assert list(result.features.columns) == FEATURE_COLUMNS
    assert result.features.crs.to_epsg() == 27700
    assert result.site_area_m2 == pytest.approx(1_000_000)
    assert result.affected_area_m2 == 0.0
    assert result.affected_pct == 0.0


@pytest.mark.parametrize("bad", ["site", "sssi"])
def test_wrong_crs_raises(bad):
    site = _site()
    sssi = _sssi([_rect(0, 0, 500, 1_000)])
    if bad == "site":
        site = site.to_crs("EPSG:4326")
    else:
        sssi = sssi.to_crs("EPSG:4326")

    with pytest.raises(ValueError, match="27700"):
        calculate_sssi_overlap(site, sssi)


@pytest.mark.parametrize("bad", ["site", "sssi"])
def test_missing_crs_raises(bad):
    site = _site()
    sssi = _sssi([_rect(0, 0, 500, 1_000)])
    if bad == "site":
        site = site.set_crs(None, allow_override=True)
    else:
        sssi = sssi.set_crs(None, allow_override=True)

    with pytest.raises(ValueError, match="CRS"):
        calculate_sssi_overlap(site, sssi)


def test_multipolygon_sssi_feature():
    part_inside = _rect(0, 0, 300, 1_000)  # 300,000 m^2 within the site
    part_outside = _rect(5_000, 5_000, 6_000, 6_000)
    sssi = _sssi([MultiPolygon([part_inside, part_outside])])

    result = calculate_sssi_overlap(_site(), sssi)

    assert result.feature_count == 1
    row = result.features.iloc[0]
    assert row["ref_code"] == "S1"
    assert row["intersection_area_m2"] == pytest.approx(300_000)
    assert result.affected_area_m2 == pytest.approx(300_000)
    assert result.affected_pct == pytest.approx(30)


def test_site_with_multiple_rows_raises():
    site = gpd.GeoDataFrame(
        geometry=[_rect(0, 0, 1_000, 1_000), _rect(2_000, 2_000, 3_000, 3_000)],
        crs=CRS,
    )
    sssi = _sssi([_rect(0, 0, 500, 1_000)])

    with pytest.raises(ValueError, match="exactly one row"):
        calculate_sssi_overlap(site, sssi)


def test_feature_output_columns_are_exact():
    sssi = _sssi([_rect(0, 0, 500, 1_000)])
    sssi["hyperlink"] = ["1005624"]  # must not leak into the result
    sssi["shape_area"] = [123.0]

    result = calculate_sssi_overlap(_site(), sssi)

    assert list(result.features.columns) == [
        "ref_code",
        "name",
        "measure",
        "intersection_area_m2",
        "intersection_area_ha",
        "geometry",
    ]
    assert result.features.geometry.name == "geometry"


def test_features_sorted_by_descending_area():
    sssi = _sssi(
        [
            _rect(0, 0, 100, 1_000),  # 100,000 m^2
            _rect(0, 0, 900, 1_000),  # 900,000 m^2
            _rect(0, 0, 400, 1_000),  # 400,000 m^2
        ],
        ref_codes=["small", "large", "mid"],
    )

    result = calculate_sssi_overlap(_site(), sssi)

    assert list(result.features["ref_code"]) == ["large", "mid", "small"]
    assert list(result.features["intersection_area_m2"]) == pytest.approx(
        [900_000, 400_000, 100_000]
    )


def test_hectare_and_percentage_calculations():
    sssi = _sssi([_rect(0, 0, 250, 1_000)])  # 250,000 m^2 = 25 ha = 25% of site

    result = calculate_sssi_overlap(_site(), sssi)

    assert result.affected_area_ha == pytest.approx(result.affected_area_m2 / 10_000)
    assert result.affected_area_ha == pytest.approx(25)
    assert result.affected_pct == pytest.approx(
        100 * result.affected_area_m2 / result.site_area_m2
    )
    assert result.affected_pct == pytest.approx(25)

    row = result.features.iloc[0]
    assert row["intersection_area_ha"] == pytest.approx(
        row["intersection_area_m2"] / 10_000
    )


@pytest.mark.parametrize("bad", ["site", "sssi"])
def test_non_geodataframe_input_raises_type_error(bad):
    site = _site()
    sssi = _sssi([_rect(0, 0, 500, 1_000)])
    not_a_gdf = [(0, 0), (0, 1), (1, 1)]
    if bad == "site":
        site = not_a_gdf
    else:
        sssi = not_a_gdf

    with pytest.raises(TypeError, match=f"{bad} must be a geopandas.GeoDataFrame"):
        calculate_sssi_overlap(site, sssi)


@pytest.mark.parametrize("missing_col", ["ref_code", "name", "measure"])
def test_missing_required_sssi_column_raises_value_error(missing_col):
    sssi = _sssi([_rect(0, 0, 500, 1_000)]).drop(columns=[missing_col])

    with pytest.raises(ValueError, match=missing_col):
        calculate_sssi_overlap(_site(), sssi)


def test_result_is_frozen_dataclass():
    result = calculate_sssi_overlap(_site(), _sssi([_rect(0, 0, 100, 100)]))

    assert isinstance(result, SssiOverlapResult)
    with pytest.raises(FrozenInstanceError):
        result.has_overlap = False
