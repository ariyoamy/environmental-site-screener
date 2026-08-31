"""Tests for :mod:`environmental_site_screener.flood_zones`.

Loader tests write tiny synthetic GeoPackages via ``tmp_path``. Analysis tests
build small in-memory GeoDataFrames shaped like the loader output. The candidate
site is a 1,000 m square at the origin in EPSG:27700 and flood-zone polygons are
simple rectangles, so every expected area is easy to check by hand.
"""

import warnings
from dataclasses import FrozenInstanceError

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import MultiPolygon, Point, Polygon

from environmental_site_screener.flood_zones import (
    FLOOD_ZONE_OUTPUT_COLUMNS,
    ZONE_COLUMNS,
    FloodZoneOverlapResult,
    calculate_flood_zone_overlap,
    load_flood_zones,
)

CRS = "EPSG:27700"
_MISSING = object()


def _rect(xmin, ymin, xmax, ymax):
    return Polygon(
        [(xmin, ymin), (xmin, ymax), (xmax, ymax), (xmax, ymin), (xmin, ymin)]
    )


_BOWTIE = Polygon([(0, 0), (0, 100), (100, 0), (100, 100), (0, 0)])


def _write(tmp_path, gdf, name):
    path = tmp_path / name
    gdf.to_file(path, driver="GPKG")
    return path


def _write_or_skip(tmp_path, gdf, name):
    path = tmp_path / name
    try:
        gdf.to_file(path, driver="GPKG")
    except Exception as exc:  # pragma: no cover - depends on GDAL build
        pytest.skip(f"GPKG writer could not represent this source: {exc!r}")
    return path


def _rows_to_records(rows, cols_order):
    recs, geoms = [], []
    for row in rows:
        src = row.get("source", _MISSING)
        if src is _MISSING:
            src = "river"
        org = row.get("origin", _MISSING)
        if org is _MISSING:
            org = "modelled"
        rec = {"flood_zone": row["zone"], "flood_source": src, "origin": org}
        recs.append({k: rec[k] for k in cols_order})
        geoms.append(row["geom"])
    return recs, geoms


def _fz_source(rows):
    """GeoDataFrame shaped like the raw Flood Zones source (origin, flood_zone, flood_source)."""
    cols = ["origin", "flood_zone", "flood_source"]
    if not rows:
        return gpd.GeoDataFrame(
            {c: pd.Series(dtype="object") for c in cols},
            geometry=gpd.GeoSeries([], crs=CRS),
            crs=CRS,
        )
    recs, geoms = _rows_to_records(rows, cols)
    return gpd.GeoDataFrame(recs, geometry=gpd.GeoSeries(geoms, crs=CRS), crs=CRS)


def _fz(rows):
    """GeoDataFrame shaped like load_flood_zones output."""
    cols = ["flood_zone", "flood_source", "origin"]
    if not rows:
        return gpd.GeoDataFrame(
            {c: pd.Series(dtype="object") for c in cols},
            geometry=gpd.GeoSeries([], crs=CRS),
            crs=CRS,
        )
    recs, geoms = _rows_to_records(rows, cols)
    return gpd.GeoDataFrame(recs, geometry=gpd.GeoSeries(geoms, crs=CRS), crs=CRS)


def _site(geom=None):
    return gpd.GeoDataFrame(
        geometry=[geom if geom is not None else _rect(0, 0, 1_000, 1_000)], crs=CRS
    )


# --------------------------------------------------------------------------- #
# loader
# --------------------------------------------------------------------------- #


def test_load_valid_source(tmp_path):
    src = _fz_source(
        [
            {"geom": MultiPolygon([_rect(0, 0, 100, 100)]), "zone": "FZ2", "source": "river"},
            {"geom": MultiPolygon([_rect(200, 0, 300, 100)]), "zone": "FZ3", "source": "sea"},
        ]
    )

    out = load_flood_zones(_write(tmp_path, src, "fz.gpkg"))

    assert list(out.columns) == FLOOD_ZONE_OUTPUT_COLUMNS
    assert list(out.index) == [0, 1]
    assert out.crs.to_epsg() == 27700
    assert list(out["flood_zone"]) == ["FZ2", "FZ3"]
    assert list(out["flood_source"]) == ["river", "sea"]


def test_load_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_flood_zones(tmp_path / "nope.gpkg")


@pytest.mark.parametrize("col", ["origin", "flood_zone", "flood_source"])
def test_load_missing_required_column(tmp_path, col):
    src = _fz_source([{"geom": _rect(0, 0, 100, 100), "zone": "FZ2"}]).drop(columns=[col])
    with pytest.raises(ValueError, match=col):
        load_flood_zones(_write(tmp_path, src, "fz.gpkg"))


def test_load_wrong_crs(tmp_path):
    src = _fz_source([{"geom": _rect(0, 0, 100, 100), "zone": "FZ2"}]).to_crs("EPSG:4326")
    with pytest.raises(ValueError, match="27700"):
        load_flood_zones(_write(tmp_path, src, "fz.gpkg"))


def test_load_missing_crs(tmp_path):
    src = _fz_source([{"geom": _rect(0, 0, 100, 100), "zone": "FZ2"}]).set_crs(
        None, allow_override=True
    )
    path = tmp_path / "fz_nocrs.gpkg"
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message="'crs' was not provided", category=UserWarning
        )
        src.to_file(path, driver="GPKG")
    if gpd.read_file(path).crs is not None:
        pytest.skip("GPKG round-trip did not preserve an undefined CRS on this stack")

    with pytest.raises(ValueError, match="CRS"):
        load_flood_zones(path)


def test_load_non_polygon_geometry(tmp_path):
    gdf = gpd.GeoDataFrame(
        {
            "origin": ["modelled", "modelled"],
            "flood_zone": ["FZ2", "FZ3"],
            "flood_source": ["river", "river"],
        },
        geometry=[Point(0, 0), Point(10, 10)],
        crs=CRS,
    )
    with pytest.raises(ValueError, match="non-polygon"):
        load_flood_zones(_write(tmp_path, gdf, "fz_pts.gpkg"))


def test_load_null_geometry(tmp_path):
    src = _fz_source(
        [
            {"geom": _rect(0, 0, 100, 100), "zone": "FZ2"},
            {"geom": None, "zone": "FZ3"},
        ]
    )
    path = _write_or_skip(tmp_path, src, "fz_null.gpkg")
    if not gpd.read_file(path).geometry.isna().any():
        pytest.skip("GPKG round-trip did not preserve a null geometry on this stack")
    with pytest.raises(ValueError, match="null geometr"):
        load_flood_zones(path)


def test_load_empty_geometry(tmp_path):
    src = _fz_source(
        [
            {"geom": _rect(0, 0, 100, 100), "zone": "FZ2"},
            {"geom": Polygon(), "zone": "FZ3"},
        ]
    )
    path = _write_or_skip(tmp_path, src, "fz_empty.gpkg")
    back = gpd.read_file(path).geometry
    if not (back.isna().any() or back.is_empty.any()):
        pytest.skip("GPKG round-trip did not preserve an empty geometry on this stack")
    with pytest.raises(ValueError):
        load_flood_zones(path)


def test_load_empty_source(tmp_path):
    path = _write_or_skip(tmp_path, _fz_source([]), "fz_empty_src.gpkg")
    if len(gpd.read_file(path)) != 0:
        pytest.skip("GPKG writer will not create a zero-feature layer on this stack")
    with pytest.raises(ValueError, match="no features"):
        load_flood_zones(path)


def test_load_invalid_geometry_warns_and_keeps_unchanged(tmp_path):
    assert not _BOWTIE.is_valid
    src = _fz_source(
        [
            {"geom": _rect(200, 0, 300, 100), "zone": "FZ2"},
            {"geom": _BOWTIE, "zone": "FZ3"},
        ]
    )
    path = _write_or_skip(tmp_path, src, "fz_invalid.gpkg")
    if gpd.read_file(path).geometry.is_valid.all():
        pytest.skip("GPKG round-trip repaired the invalid geometry on this stack")

    with pytest.warns(UserWarning, match="invalid geometr"):
        out = load_flood_zones(path)

    assert len(out) == 2
    assert int((~out.geometry.is_valid).sum()) == 1  # left unchanged, not repaired


@pytest.mark.parametrize("zone", ["FZ2", "FZ3"])
def test_load_allowed_flood_zone_values(tmp_path, zone):
    src = _fz_source([{"geom": _rect(0, 0, 100, 100), "zone": zone}])
    out = load_flood_zones(_write(tmp_path, src, "fz.gpkg"))
    assert out["flood_zone"].iloc[0] == zone


def test_load_unknown_flood_zone_raises(tmp_path):
    src = _fz_source(
        [
            {"geom": _rect(0, 0, 100, 100), "zone": "FZ2"},
            {"geom": _rect(200, 0, 300, 100), "zone": "FZ1"},
        ]
    )
    with pytest.raises(ValueError, match="FZ1"):
        load_flood_zones(_write(tmp_path, src, "fz.gpkg"))


def test_load_null_flood_zone_raises(tmp_path):
    src = _fz_source(
        [
            {"geom": _rect(0, 0, 100, 100), "zone": "FZ2"},
            {"geom": _rect(200, 0, 300, 100), "zone": None},
        ]
    )
    path = _write_or_skip(tmp_path, src, "fz.gpkg")
    if gpd.read_file(path)["flood_zone"].notna().all():
        pytest.skip("GPKG round-trip did not preserve a null flood_zone on this stack")
    with pytest.raises(ValueError, match="flood_zone"):
        load_flood_zones(path)


def test_load_empty_flood_zone_raises(tmp_path):
    src = _fz_source(
        [
            {"geom": _rect(0, 0, 100, 100), "zone": "FZ2"},
            {"geom": _rect(200, 0, 300, 100), "zone": ""},
        ]
    )
    with pytest.raises(ValueError, match="flood_zone"):
        load_flood_zones(_write(tmp_path, src, "fz.gpkg"))


def test_load_null_flood_source_allowed(tmp_path):
    src = _fz_source([{"geom": _rect(0, 0, 100, 100), "zone": "FZ2", "source": None}])
    out = load_flood_zones(_write(tmp_path, src, "fz.gpkg"))
    assert len(out) == 1
    assert pd.isna(out["flood_source"].iloc[0])


def test_load_null_origin_allowed(tmp_path):
    src = _fz_source([{"geom": _rect(0, 0, 100, 100), "zone": "FZ2", "origin": None}])
    out = load_flood_zones(_write(tmp_path, src, "fz.gpkg"))
    assert len(out) == 1
    assert pd.isna(out["origin"].iloc[0])


def test_load_river_and_sea_preserved_verbatim(tmp_path):
    src = _fz_source(
        [{"geom": _rect(0, 0, 100, 100), "zone": "FZ3", "source": "river and sea"}]
    )
    out = load_flood_zones(_write(tmp_path, src, "fz.gpkg"))
    assert out["flood_source"].iloc[0] == "river and sea"


# --------------------------------------------------------------------------- #
# loader - bbox / spatially filtered read
# --------------------------------------------------------------------------- #

_TWO_APART = [
    {"geom": _rect(0, 0, 100, 100), "zone": "FZ2"},
    {"geom": _rect(5_000, 5_000, 5_100, 5_100), "zone": "FZ3"},
]


def test_load_bbox_none_reads_full_source(tmp_path):
    path = _write(tmp_path, _fz_source(_TWO_APART), "fz.gpkg")

    out = load_flood_zones(path, bbox=None)

    assert len(out) == 2
    assert list(out.columns) == FLOOD_ZONE_OUTPUT_COLUMNS
    assert out.crs.to_epsg() == 27700


def test_load_bbox_selects_only_nearby_polygons(tmp_path):
    path = _write(tmp_path, _fz_source(_TWO_APART), "fz.gpkg")

    out = load_flood_zones(path, bbox=(-10, -10, 200, 200))

    assert len(out) == 1
    assert out["flood_zone"].iloc[0] == "FZ2"
    assert out.crs.to_epsg() == 27700
    assert list(out.columns) == FLOOD_ZONE_OUTPUT_COLUMNS


def test_load_bbox_no_nearby_polygons_returns_empty_normalised(tmp_path):
    path = _write(tmp_path, _fz_source(_TWO_APART), "fz.gpkg")

    out = load_flood_zones(path, bbox=(20_000, 20_000, 20_100, 20_100))

    assert len(out) == 0
    assert list(out.columns) == FLOOD_ZONE_OUTPUT_COLUMNS
    assert out.crs.to_epsg() == 27700
    assert list(out.index) == []


def test_analysis_of_empty_bbox_subset_is_zero_result(tmp_path):
    path = _write(tmp_path, _fz_source([{"geom": _rect(0, 0, 100, 100), "zone": "FZ2"}]), "fz.gpkg")
    fz = load_flood_zones(path, bbox=(20_000, 20_000, 20_100, 20_100))

    result = calculate_flood_zone_overlap(_site(), fz)

    assert result.has_flood_zone_overlap is False
    assert result.zone_count == 0
    assert list(result.zones.columns) == ZONE_COLUMNS
    assert result.zones.crs.to_epsg() == 27700
    assert result.affected_area_m2 == 0.0
    assert result.flood_sources == ()


def test_bbox_false_positive_boundary_touch_excluded_by_analysis(tmp_path):
    # polygon east of the site sharing only the x = 1000 edge; its bbox overlaps
    # the site bbox so a bbox read keeps it, but exact analysis drops it.
    path = _write(tmp_path, _fz_source([{"geom": _rect(1_000, 0, 2_000, 1_000), "zone": "FZ3"}]), "fz.gpkg")
    fz = load_flood_zones(path, bbox=(0.0, 0.0, 1_000.0, 1_000.0))

    assert len(fz) == 1  # bbox kept the edge-touching polygon

    result = calculate_flood_zone_overlap(_site(), fz)

    assert result.has_flood_zone_overlap is False
    assert result.zone_count == 0
    assert result.affected_area_m2 == 0.0


def test_bbox_does_not_change_overlap_arithmetic(tmp_path):
    rows = [
        {"geom": _rect(-500, -500, 600, 1_500), "zone": "FZ2"},   # site x 0..600
        {"geom": _rect(600, -500, 1_500, 1_500), "zone": "FZ3"},  # site x 600..1000
        {"geom": _rect(50_000, 50_000, 50_100, 50_100), "zone": "FZ3"},  # far away
    ]
    path = _write(tmp_path, _fz_source(rows), "fz.gpkg")

    full = calculate_flood_zone_overlap(_site(), load_flood_zones(path))
    scoped = calculate_flood_zone_overlap(
        _site(), load_flood_zones(path, bbox=tuple(_site().total_bounds))
    )

    assert scoped.affected_area_m2 == pytest.approx(full.affected_area_m2)
    assert scoped.affected_area_m2 == pytest.approx(1_000_000)
    assert dict(zip(scoped.zones["flood_zone"], scoped.zones["intersection_area_m2"])) == pytest.approx(
        dict(zip(full.zones["flood_zone"], full.zones["intersection_area_m2"]))
    )


def test_bbox_missing_source_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_flood_zones(tmp_path / "nope.gpkg", bbox=(0, 0, 10, 10))


def test_bbox_wrong_crs_raises_before_empty(tmp_path):
    src = _fz_source([{"geom": _rect(0, 0, 100, 100), "zone": "FZ2"}]).to_crs("EPSG:4326")
    with pytest.raises(ValueError, match="27700"):
        load_flood_zones(_write(tmp_path, src, "fz.gpkg"), bbox=(-1, -1, 1, 1))


def test_bbox_missing_column_raises_before_empty(tmp_path):
    src = _fz_source([{"geom": _rect(0, 0, 100, 100), "zone": "FZ2"}]).drop(columns=["flood_source"])
    with pytest.raises(ValueError, match="flood_source"):
        load_flood_zones(_write(tmp_path, src, "fz.gpkg"), bbox=(0, 0, 200, 200))


# --------------------------------------------------------------------------- #
# analysis
# --------------------------------------------------------------------------- #


def test_site_entirely_inside_fz3():
    fz = _fz([{"geom": _rect(-500, -500, 2_000, 2_000), "zone": "FZ3", "source": "river"}])

    result = calculate_flood_zone_overlap(_site(), fz)

    assert result.has_flood_zone_overlap is True
    assert result.zone_count == 1
    row = result.zones.iloc[0]
    assert row["flood_zone"] == "FZ3"
    assert row["intersection_area_m2"] == pytest.approx(1_000_000)
    assert row["intersection_area_ha"] == pytest.approx(100)
    assert row["site_pct"] == pytest.approx(100)
    assert result.affected_area_m2 == pytest.approx(1_000_000)
    assert result.affected_area_ha == pytest.approx(100)
    assert result.affected_pct == pytest.approx(100)
    assert result.flood_sources == ("river",)


def test_site_spanning_disjoint_fz2_and_fz3():
    fz = _fz(
        [
            {"geom": _rect(-500, -500, 600, 1_500), "zone": "FZ2"},   # site x 0..600
            {"geom": _rect(600, -500, 1_500, 1_500), "zone": "FZ3"},  # site x 600..1000
        ]
    )

    result = calculate_flood_zone_overlap(_site(), fz)

    assert result.zone_count == 2
    by_zone = dict(
        zip(result.zones["flood_zone"], result.zones["intersection_area_m2"])
    )
    assert by_zone["FZ2"] == pytest.approx(600_000)
    assert by_zone["FZ3"] == pytest.approx(400_000)
    assert result.affected_area_m2 == pytest.approx(1_000_000)
    assert result.affected_area_m2 == pytest.approx(by_zone["FZ2"] + by_zone["FZ3"])
    assert list(result.zones["flood_zone"]) == ["FZ2", "FZ3"]  # sorted by area desc


def test_constructed_overlapping_fz2_fz3_headline_below_sum():
    fz = _fz(
        [
            {"geom": _rect(-100, -100, 800, 1_100), "zone": "FZ2"},   # site x 0..800
            {"geom": _rect(400, -100, 1_100, 1_100), "zone": "FZ3"},  # site x 400..1000
        ]
    )

    result = calculate_flood_zone_overlap(_site(), fz)

    by_zone = dict(
        zip(result.zones["flood_zone"], result.zones["intersection_area_m2"])
    )
    assert by_zone["FZ2"] == pytest.approx(800_000)
    assert by_zone["FZ3"] == pytest.approx(600_000)
    per_zone_sum = by_zone["FZ2"] + by_zone["FZ3"]
    assert result.affected_area_m2 == pytest.approx(1_000_000)  # union of the two
    assert result.affected_area_m2 < per_zone_sum


def test_same_zone_overlapping_polygons_are_unioned():
    fz = _fz(
        [
            {"geom": _rect(-100, -100, 600, 1_100), "zone": "FZ3"},   # site x 0..600
            {"geom": _rect(400, -100, 1_100, 1_100), "zone": "FZ3"},  # site x 400..1000
        ]
    )

    result = calculate_flood_zone_overlap(_site(), fz)

    assert result.zone_count == 1
    assert result.zones["intersection_area_m2"].iloc[0] == pytest.approx(1_000_000)
    assert result.affected_area_m2 == pytest.approx(1_000_000)  # not 1,200,000


def test_boundary_touch_only_does_not_count():
    fz = _fz([{"geom": _rect(1_000, 0, 2_000, 1_000), "zone": "FZ3"}])

    result = calculate_flood_zone_overlap(_site(), fz)

    assert result.has_flood_zone_overlap is False
    assert result.zone_count == 0
    assert result.affected_area_m2 == 0.0


def test_no_overlap_zero_result_schema():
    fz = _fz([{"geom": _rect(5_000, 5_000, 6_000, 6_000), "zone": "FZ3"}])

    result = calculate_flood_zone_overlap(_site(), fz)

    assert result.has_flood_zone_overlap is False
    assert result.zone_count == 0
    assert list(result.zones.columns) == ZONE_COLUMNS
    assert result.zones.crs.to_epsg() == 27700
    assert result.affected_area_m2 == 0.0
    assert result.affected_pct == 0.0
    assert result.flood_sources == ()
    assert result.origins == ()
    assert result.site_area_m2 == pytest.approx(1_000_000)


def test_empty_analysis_source_returns_zero_result():
    # a valid, correctly shaped, empty EPSG:27700 layer (e.g. a bbox subset with
    # nothing in it) is a genuine no-overlap, not a missing source
    result = calculate_flood_zone_overlap(_site(), _fz([]))

    assert result.has_flood_zone_overlap is False
    assert result.zone_count == 0
    assert list(result.zones.columns) == ZONE_COLUMNS
    assert result.zones.crs.to_epsg() == 27700
    assert result.affected_area_m2 == 0.0
    assert result.affected_pct == 0.0
    assert result.flood_sources == ()
    assert result.origins == ()


def test_null_flood_source_excluded_from_provenance():
    fz = _fz(
        [
            {"geom": _rect(-100, -100, 1_100, 1_100), "zone": "FZ3", "source": None},
            {"geom": _rect(-100, -100, 1_100, 1_100), "zone": "FZ3", "source": "river"},
        ]
    )

    result = calculate_flood_zone_overlap(_site(), fz)

    assert result.flood_sources == ("river",)
    assert result.zones["flood_sources"].iloc[0] == "river"


def test_all_null_source_gives_empty_provenance():
    fz = _fz([{"geom": _rect(-100, -100, 1_100, 1_100), "zone": "FZ3", "source": None}])

    result = calculate_flood_zone_overlap(_site(), fz)

    assert result.flood_sources == ()
    assert result.zones["flood_sources"].iloc[0] == ""
    assert result.zones["origins"].iloc[0] == "modelled"


def test_multi_source_provenance_retained():
    fz = _fz(
        [{"geom": _rect(-100, -100, 1_100, 1_100), "zone": "FZ3", "source": "river and sea"}]
    )

    result = calculate_flood_zone_overlap(_site(), fz)

    assert result.flood_sources == ("river and sea",)
    assert result.zones["flood_sources"].iloc[0] == "river and sea"


def test_distinct_origins_joined_sorted():
    fz = _fz(
        [
            {"geom": _rect(-100, -100, 600, 1_100), "zone": "FZ3", "origin": "recorded"},
            {"geom": _rect(400, -100, 1_100, 1_100), "zone": "FZ3", "origin": "modelled"},
        ]
    )

    result = calculate_flood_zone_overlap(_site(), fz)

    assert result.origins == ("modelled", "recorded")
    assert result.zones["origins"].iloc[0] == "modelled,recorded"


def test_hectare_and_percentage_arithmetic():
    fz = _fz([{"geom": _rect(0, 0, 250, 1_000), "zone": "FZ3"}])  # 250,000 m^2

    result = calculate_flood_zone_overlap(_site(), fz)

    assert result.affected_area_ha == pytest.approx(result.affected_area_m2 / 10_000)
    assert result.affected_area_ha == pytest.approx(25)
    assert result.affected_pct == pytest.approx(
        100 * result.affected_area_m2 / result.site_area_m2
    )
    assert result.affected_pct == pytest.approx(25)
    row = result.zones.iloc[0]
    assert row["site_pct"] == pytest.approx(25)
    assert row["intersection_area_ha"] == pytest.approx(row["intersection_area_m2"] / 10_000)


def test_zones_sorted_by_area_then_flood_zone():
    fz = _fz(
        [
            {"geom": _rect(0, 0, 100, 1_000), "zone": "FZ2"},    # 100,000
            {"geom": _rect(100, 0, 1_000, 1_000), "zone": "FZ3"},  # 900,000
        ]
    )

    result = calculate_flood_zone_overlap(_site(), fz)

    assert list(result.zones["flood_zone"]) == ["FZ3", "FZ2"]


def test_result_schema_and_crs_are_exact():
    fz = _fz([{"geom": _rect(-500, -500, 2_000, 2_000), "zone": "FZ3"}])

    result = calculate_flood_zone_overlap(_site(), fz)

    assert list(result.zones.columns) == ZONE_COLUMNS
    assert result.zones.geometry.name == "geometry"
    assert result.zones.crs.to_epsg() == 27700


def test_result_is_frozen_dataclass():
    result = calculate_flood_zone_overlap(
        _site(), _fz([{"geom": _rect(-500, -500, 2_000, 2_000), "zone": "FZ3"}])
    )
    assert isinstance(result, FloodZoneOverlapResult)
    with pytest.raises(FrozenInstanceError):
        result.has_flood_zone_overlap = False


@pytest.mark.parametrize("bad", ["site", "flood_zones"])
def test_analysis_non_geodataframe_raises_type_error(bad):
    site = _site()
    fz = _fz([{"geom": _rect(0, 0, 100, 100), "zone": "FZ3"}])
    if bad == "site":
        site = [(0, 0), (1, 1)]
    else:
        fz = [(0, 0), (1, 1)]
    with pytest.raises(TypeError, match=f"{bad} must be a geopandas.GeoDataFrame"):
        calculate_flood_zone_overlap(site, fz)


@pytest.mark.parametrize("bad", ["site", "flood_zones"])
def test_analysis_wrong_crs_raises(bad):
    site = _site()
    fz = _fz([{"geom": _rect(0, 0, 100, 100), "zone": "FZ3"}])
    if bad == "site":
        site = site.to_crs("EPSG:4326")
    else:
        fz = fz.to_crs("EPSG:4326")
    with pytest.raises(ValueError, match="27700"):
        calculate_flood_zone_overlap(site, fz)


@pytest.mark.parametrize("bad", ["site", "flood_zones"])
def test_analysis_missing_crs_raises(bad):
    site = _site()
    fz = _fz([{"geom": _rect(0, 0, 100, 100), "zone": "FZ3"}])
    if bad == "site":
        site = site.set_crs(None, allow_override=True)
    else:
        fz = fz.set_crs(None, allow_override=True)
    with pytest.raises(ValueError, match="CRS"):
        calculate_flood_zone_overlap(site, fz)


def test_analysis_site_multiple_rows_raises():
    site = gpd.GeoDataFrame(
        geometry=[_rect(0, 0, 1_000, 1_000), _rect(2_000, 2_000, 3_000, 3_000)], crs=CRS
    )
    with pytest.raises(ValueError, match="exactly one row"):
        calculate_flood_zone_overlap(
            site, _fz([{"geom": _rect(0, 0, 100, 100), "zone": "FZ3"}])
        )


@pytest.mark.parametrize("col", ["flood_zone", "flood_source", "origin"])
def test_analysis_missing_required_column_raises(col):
    fz = _fz([{"geom": _rect(-500, -500, 2_000, 2_000), "zone": "FZ3"}]).drop(columns=[col])
    with pytest.raises(ValueError, match=col):
        calculate_flood_zone_overlap(_site(), fz)
