"""Tests for :mod:`environmental_site_screener.screening`.

These exercise the orchestration behaviour only - the per-theme spatial logic is
covered by the dataset test modules. Datasets are tiny synthetic GeoDataFrames
in EPSG:27700; the Flood Zones source is a small GeoPackage written to
``tmp_path`` because ``screen_site`` calls ``load_flood_zones(path, bbox=...)``.
"""

from dataclasses import FrozenInstanceError

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon

from environmental_site_screener import screening
from environmental_site_screener.screening import (
    SUMMARY_COLUMNS,
    SUMMARY_THEMES,
    ScreeningDatasets,
    ScreeningResult,
    screen_site,
)

CRS = "EPSG:27700"


def _rect(xmin, ymin, xmax, ymax):
    return Polygon(
        [(xmin, ymin), (xmin, ymax), (xmax, ymax), (xmax, ymin), (xmin, ymin)]
    )


_COVERS = _rect(-500, -500, 2_000, 2_000)  # covers the default 1,000 m site
_FAR = _rect(50_000, 50_000, 51_000, 51_000)  # nowhere near the site


def _site(geom=None, crs=CRS):
    return gpd.GeoDataFrame(
        geometry=[geom if geom is not None else _rect(0, 0, 1_000, 1_000)], crs=crs
    )


def _sssi(geoms):
    return gpd.GeoDataFrame(
        {
            "ref_code": [f"S{i}" for i in range(len(geoms))],
            "name": [f"SSSI {i}" for i in range(len(geoms))],
            "measure": [None] * len(geoms),
        },
        geometry=list(geoms),
        crs=CRS,
    )


def _irz(geoms):
    return gpd.GeoDataFrame(
        {
            "irzurl": [f"https://example.test/?irzcode={i:013d}" for i in range(len(geoms))],
            "irz_code": [f"{i:013d}" for i in range(len(geoms))],
        },
        geometry=list(geoms),
        crs=CRS,
    )


def _phi(rows):
    """rows: list of (habcode, geometry)."""
    return gpd.GeoDataFrame(
        {
            "uid": [f"PHI{i}" for i in range(len(rows))],
            "mainhabs": [f"{c} name" for c, _ in rows],
            "habcodes": [c for c, _ in rows],
            "primsource": ["test"] * len(rows),
        },
        geometry=[g for _, g in rows],
        crs=CRS,
    )


def _aw(rows, inventory, categories):
    """rows: list of (code, geometry)."""
    return gpd.GeoDataFrame(
        {
            "aw_name": [f"Wood {i}" for i in range(len(rows))],
            "category_code": [c for c, _ in rows],
            "category_name": [categories[c] for c, _ in rows],
            "theme_id": [f"T{i}" for i in range(len(rows))],
            "inventory": [inventory] * len(rows),
        },
        geometry=[g for _, g in rows],
        crs=CRS,
    )


_REV_CATS = {"ASNW": "Ancient & Semi-Natural Woodland", "ARW": "Ancient Replanted Woodland"}
_LEG_CATS = {"ASNW": "Ancient & Semi-Natural Woodland", "PAWS": "Ancient Replanted Woodland"}


def _coverage(geom):
    return gpd.GeoDataFrame({"county_name": ["Testshire"]}, geometry=[geom], crs=CRS)


def _write_fz(tmp_path, rows, name="fz.gpkg"):
    """rows: list of (flood_zone, geometry); writes a synthetic Flood Zones GPKG."""
    gdf = gpd.GeoDataFrame(
        {
            "origin": ["modelled"] * len(rows),
            "flood_zone": [z for z, _ in rows],
            "flood_source": ["river"] * len(rows),
        },
        geometry=[g for _, g in rows],
        crs=CRS,
    )
    path = tmp_path / name
    gdf.to_file(path, driver="GPKG")
    return path


def _datasets(
    tmp_path,
    *,
    sssi_geoms=(_COVERS,),
    irz_geoms=(_COVERS,),
    phi_rows=(("DWOOD", _COVERS),),
    revised_rows=(("ASNW", _COVERS),),
    legacy_rows=(("PAWS", _COVERS),),
    coverage_geom=_COVERS,
    fz_rows=(("FZ3", _COVERS),),
):
    return ScreeningDatasets(
        sssi=_sssi(sssi_geoms),
        sssi_irz=_irz(irz_geoms),
        priority_habitats=_phi(phi_rows),
        ancient_woodland_revised=_aw(revised_rows, "revised", _REV_CATS),
        ancient_woodland_legacy=_aw(legacy_rows, "legacy", _LEG_CATS),
        ancient_woodland_revised_coverage=_coverage(coverage_geom),
        flood_zones_path=_write_fz(tmp_path, fz_rows),
    )


# --------------------------------------------------------------------------- #
# integration
# --------------------------------------------------------------------------- #


def test_all_five_themes_run_and_summary_shape(tmp_path):
    result = screen_site(_site(), _datasets(tmp_path))

    assert isinstance(result, ScreeningResult)
    assert isinstance(result.summary, pd.DataFrame)
    assert not isinstance(result.summary, gpd.GeoDataFrame)
    assert list(result.summary.columns) == SUMMARY_COLUMNS
    assert tuple(result.summary["theme"]) == SUMMARY_THEMES
    assert len(result.summary) == 5
    # every theme genuinely produced its result object
    assert result.sssi.has_overlap is True
    assert result.sssi_irz.has_irz_context is True
    assert result.priority_habitats.has_priority_overlap is True
    assert result.ancient_woodland.has_overlap is True
    assert result.flood_zones.has_flood_zone_overlap is True


def test_summary_schema_dtypes_and_result_type_vocab(tmp_path):
    summary = screen_site(_site(), _datasets(tmp_path)).summary

    assert summary["has_result"].dtype == bool
    assert summary["feature_count"].dtype == "int64"
    for col in ("affected_area_ha", "affected_pct", "nearest_distance_m"):
        assert summary[col].dtype == "float64"
    assert set(summary["result_type"]) <= {"overlap", "context"}
    assert summary.loc[summary["theme"] == "SSSI Impact Risk Zone", "result_type"].iloc[0] == "context"
    assert summary.loc[summary["theme"] == "SSSI", "result_type"].iloc[0] == "overlap"


def test_site_in_epsg_4326_is_reprojected_once_and_downstream_is_27700(tmp_path):
    site_4326 = _site().to_crs("EPSG:4326")

    result = screen_site(site_4326, _datasets(tmp_path))

    assert result.site.crs.to_epsg() == 27700
    assert result.sssi.has_overlap is True
    assert result.sssi.features.crs.to_epsg() == 27700
    assert result.flood_zones.zones.crs.to_epsg() == 27700
    assert result.ancient_woodland.features.crs.to_epsg() == 27700


def test_sssi_overlap_means_nearest_is_none(tmp_path):
    result = screen_site(_site(), _datasets(tmp_path, sssi_geoms=(_COVERS,)))

    assert result.sssi.has_overlap is True
    assert result.nearest_sssi is None
    row = result.summary.loc[result.summary["theme"] == "SSSI"].iloc[0]
    assert pd.isna(row["nearest_distance_m"])
    assert row["affected_area_ha"] == pytest.approx(result.sssi.affected_area_ha)


def test_no_sssi_overlap_calculates_nearest(tmp_path):
    # SSSI 2,000 m east of the 1,000 m site -> no overlap, nearest gap 1,000 m
    far_sssi = _rect(2_000, 0, 3_000, 1_000)
    result = screen_site(_site(), _datasets(tmp_path, sssi_geoms=(far_sssi,)))

    assert result.sssi.has_overlap is False
    assert result.nearest_sssi is not None
    assert result.nearest_sssi.distance_m == pytest.approx(1_000)
    row = result.summary.loc[result.summary["theme"] == "SSSI"].iloc[0]
    assert row["nearest_distance_m"] == pytest.approx(1_000)
    assert row["affected_area_ha"] == 0.0  # applicable metric, genuinely zero
    assert row["affected_pct"] == 0.0
    assert bool(row["has_result"]) is False


def test_irz_row_has_null_area_and_percentage_not_zero(tmp_path):
    summary = screen_site(_site(), _datasets(tmp_path)).summary
    row = summary.loc[summary["theme"] == "SSSI Impact Risk Zone"].iloc[0]

    assert row["result_type"] == "context"
    assert pd.isna(row["affected_area_ha"])
    assert pd.isna(row["affected_pct"])
    assert pd.isna(row["nearest_distance_m"])
    assert int(row["feature_count"]) == 1
    assert bool(row["has_result"]) is True


def test_no_priority_habitat_overlap_is_real_zero(tmp_path):
    result = screen_site(
        _site(), _datasets(tmp_path, phi_rows=(("DWOOD", _FAR),))
    )
    row = result.summary.loc[result.summary["theme"] == "Priority Habitats"].iloc[0]

    assert result.priority_habitats.has_priority_overlap is False
    assert bool(row["has_result"]) is False
    assert row["affected_area_ha"] == 0.0
    assert row["affected_pct"] == 0.0
    assert not pd.isna(row["affected_area_ha"])


def test_context_only_priority_habitat_is_not_a_priority_overlap(tmp_path):
    # GMOOR is a PHI context code, not a priority habitat
    result = screen_site(
        _site(), _datasets(tmp_path, phi_rows=(("GMOOR", _COVERS),))
    )
    row = result.summary.loc[result.summary["theme"] == "Priority Habitats"].iloc[0]

    assert result.priority_habitats.has_priority_overlap is False
    assert bool(row["has_result"]) is False
    assert row["affected_area_ha"] == 0.0


def test_ancient_woodland_precedence_survives_orchestration(tmp_path):
    # site inside coverage: the co-located legacy polygon must be ignored
    result = screen_site(
        _site(),
        _datasets(
            tmp_path,
            coverage_geom=_COVERS,
            revised_rows=(("ASNW", _COVERS),),
            legacy_rows=(("PAWS", _COVERS),),
        ),
    )

    assert result.ancient_woodland.has_overlap is True
    assert set(result.ancient_woodland.features["inventory"]) == {"revised"}
    row = result.summary.loc[result.summary["theme"] == "Ancient Woodland"].iloc[0]
    assert bool(row["has_result"]) is True
    assert row["affected_area_ha"] == pytest.approx(result.ancient_woodland.affected_area_ha)


def test_flood_zone_loader_receives_validated_site_bounds(tmp_path, monkeypatch):
    captured = {}
    real_loader = screening.load_flood_zones

    def spy(path, bbox=None):
        captured["path"] = path
        captured["bbox"] = bbox
        return real_loader(path, bbox=bbox)

    monkeypatch.setattr(screening, "load_flood_zones", spy)

    site_4326 = _site().to_crs("EPSG:4326")
    datasets = _datasets(tmp_path)
    result = screen_site(site_4326, datasets)

    assert captured["path"] == datasets.flood_zones_path
    assert captured["bbox"] == pytest.approx(tuple(result.site.total_bounds))
    # bounds handed to the loader are the EPSG:27700 validated bounds
    assert result.site.crs.to_epsg() == 27700


def test_empty_flood_zone_bbox_subset_gives_zero_row(tmp_path):
    result = screen_site(
        _site(), _datasets(tmp_path, fz_rows=(("FZ3", _FAR),))
    )
    row = result.summary.loc[result.summary["theme"] == "Flood Zones"].iloc[0]

    assert result.flood_zones.has_flood_zone_overlap is False
    assert result.flood_zones.zone_count == 0
    assert bool(row["has_result"]) is False
    assert row["affected_area_ha"] == 0.0  # applicable metric, genuinely zero
    assert row["affected_pct"] == 0.0
    assert int(row["feature_count"]) == 0


def test_no_cross_theme_totals_or_score(tmp_path):
    result = screen_site(_site(), _datasets(tmp_path))

    # the result object exposes only the per-theme objects plus site + summary
    assert set(vars(result)) == {
        "site",
        "sssi",
        "nearest_sssi",
        "sssi_irz",
        "priority_habitats",
        "ancient_woodland",
        "flood_zones",
        "summary",
    }
    # the summary has no aggregate row or column
    assert set(result.summary.columns) == set(SUMMARY_COLUMNS)
    assert tuple(result.summary["theme"]) == SUMMARY_THEMES  # exactly the 5 themes
    for banned in ("total", "score", "rating", "risk", "combined", "overall"):
        assert not any(banned in c.lower() for c in result.summary.columns)


def test_inputs_are_not_mutated(tmp_path):
    site = _site()
    site_snapshot = site.copy()
    datasets = _datasets(tmp_path)
    snapshots = {
        "sssi": datasets.sssi.copy(),
        "sssi_irz": datasets.sssi_irz.copy(),
        "priority_habitats": datasets.priority_habitats.copy(),
        "ancient_woodland_revised": datasets.ancient_woodland_revised.copy(),
        "ancient_woodland_legacy": datasets.ancient_woodland_legacy.copy(),
        "ancient_woodland_revised_coverage": datasets.ancient_woodland_revised_coverage.copy(),
    }

    screen_site(site, datasets)

    assert site.equals(site_snapshot)
    assert site.crs == site_snapshot.crs
    for name, snap in snapshots.items():
        assert getattr(datasets, name).equals(snap), f"{name} was mutated"


def test_result_and_datasets_are_frozen(tmp_path):
    datasets = _datasets(tmp_path)
    result = screen_site(_site(), datasets)

    with pytest.raises(FrozenInstanceError):
        result.summary = None
    with pytest.raises(FrozenInstanceError):
        datasets.sssi = None


def test_broken_required_dataset_error_propagates(tmp_path):
    datasets = _datasets(tmp_path)
    broken = ScreeningDatasets(
        sssi=datasets.sssi.drop(columns=["measure"]),  # SSSI overlap requires it
        sssi_irz=datasets.sssi_irz,
        priority_habitats=datasets.priority_habitats,
        ancient_woodland_revised=datasets.ancient_woodland_revised,
        ancient_woodland_legacy=datasets.ancient_woodland_legacy,
        ancient_woodland_revised_coverage=datasets.ancient_woodland_revised_coverage,
        flood_zones_path=datasets.flood_zones_path,
    )

    with pytest.raises(ValueError, match="measure"):
        screen_site(_site(), broken)


def test_missing_flood_zone_source_error_propagates(tmp_path):
    datasets = _datasets(tmp_path)
    missing = ScreeningDatasets(
        sssi=datasets.sssi,
        sssi_irz=datasets.sssi_irz,
        priority_habitats=datasets.priority_habitats,
        ancient_woodland_revised=datasets.ancient_woodland_revised,
        ancient_woodland_legacy=datasets.ancient_woodland_legacy,
        ancient_woodland_revised_coverage=datasets.ancient_woodland_revised_coverage,
        flood_zones_path=tmp_path / "does_not_exist.gpkg",
    )

    with pytest.raises(FileNotFoundError):
        screen_site(_site(), missing)


def test_screen_site_rejects_non_datasets_container(tmp_path):
    with pytest.raises(TypeError, match="ScreeningDatasets"):
        screen_site(_site(), {"sssi": None})
