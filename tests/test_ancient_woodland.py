"""Tests for :mod:`environmental_site_screener.ancient_woodland`.

Loader tests write tiny synthetic GeoPackages via ``tmp_path``. Analysis tests
build small in-memory GeoDataFrames shaped like the loader output. The candidate
site is a 1,000 m square at the origin in EPSG:27700 and woodland/coverage
polygons are simple rectangles, so every expected area is easy to check by hand.
"""

import warnings
from dataclasses import FrozenInstanceError

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import MultiPolygon, Point, Polygon

from environmental_site_screener.ancient_woodland import (
    AW_OUTPUT_COLUMNS,
    FEATURE_COLUMNS,
    LEGACY_CATEGORIES,
    REVISED_CATEGORIES,
    REVISED_COVERAGE_COUNTIES,
    AncientWoodlandOverlapResult,
    calculate_ancient_woodland_overlap,
    load_ancient_woodland_legacy,
    load_ancient_woodland_revised,
    load_revised_coverage,
)

CRS = "EPSG:27700"


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


# --------------------------------------------------------------------------- #
# source-shaped builders (raw GeoPackage schema)
# --------------------------------------------------------------------------- #

_MISSING = object()


def _revised_source(rows):
    cols = ["name", "status", "themename", "themeid"]
    if not rows:
        return gpd.GeoDataFrame(
            {c: pd.Series(dtype="object") for c in cols},
            geometry=gpd.GeoSeries([], crs=CRS),
            crs=CRS,
        )
    recs, geoms = [], []
    for i, row in enumerate(rows):
        code = row["code"]
        themename = row.get("themename", _MISSING)
        if themename is _MISSING:
            themename = REVISED_CATEGORIES.get(code, f"{code} name")
        recs.append(
            {
                "name": row.get("name", f"Wood {i}"),
                "status": code,
                "themename": themename,
                "themeid": row.get("themeid", f"TST-{1000 + i}"),
            }
        )
        geoms.append(row["geom"])
    return gpd.GeoDataFrame(recs, geometry=gpd.GeoSeries(geoms, crs=CRS), crs=CRS)


def _legacy_source(rows):
    cols = ["name", "status", "themname", "themid"]
    if not rows:
        return gpd.GeoDataFrame(
            {c: pd.Series(dtype="object") for c in cols},
            geometry=gpd.GeoSeries([], crs=CRS),
            crs=CRS,
        )
    recs, geoms = [], []
    for i, row in enumerate(rows):
        code = row["code"]
        themname = row.get("themname", _MISSING)
        if themname is _MISSING:
            themname = LEGACY_CATEGORIES.get(code, f"{code} name")
        recs.append(
            {
                "name": row.get("name", f"Wood {i}"),
                "status": code,
                "themname": themname,
                "themid": row.get("themid", float(1_400_000 + i)),
            }
        )
        geoms.append(row["geom"])
    return gpd.GeoDataFrame(recs, geometry=gpd.GeoSeries(geoms, crs=CRS), crs=CRS)


# --------------------------------------------------------------------------- #
# output-shaped builders (loader output schema)
# --------------------------------------------------------------------------- #


def _norm(rows, inventory, categories):
    if not rows:
        return gpd.GeoDataFrame(
            {c: pd.Series(dtype="object") for c in AW_OUTPUT_COLUMNS if c != "geometry"},
            geometry=gpd.GeoSeries([], crs=CRS),
            crs=CRS,
        )
    recs, geoms = [], []
    for i, row in enumerate(rows):
        code = row["code"]
        recs.append(
            {
                "aw_name": row.get("name", f"Wood {i}"),
                "category_code": code,
                "category_name": row.get("category_name", categories[code]),
                "theme_id": row.get("theme_id", f"TID{i}"),
                "inventory": inventory,
            }
        )
        geoms.append(row["geom"])
    return gpd.GeoDataFrame(recs, geometry=gpd.GeoSeries(geoms, crs=CRS), crs=CRS)


def _revised(rows):
    return _norm(rows, "revised", REVISED_CATEGORIES)


def _legacy(rows):
    return _norm(rows, "legacy", LEGACY_CATEGORIES)


def _site(geom=None):
    return gpd.GeoDataFrame(
        geometry=[geom if geom is not None else _rect(0, 0, 1_000, 1_000)], crs=CRS
    )


def _cov(geom, name="Testshire"):
    """Coverage input shaped like load_revised_coverage output."""
    if isinstance(geom, (list, tuple)):
        geoms = list(geom)
        names = [f"{name}{i}" for i in range(len(geoms))]
    else:
        geoms, names = [geom], [name]
    return gpd.GeoDataFrame(
        {"county_name": names}, geometry=gpd.GeoSeries(geoms, crs=CRS), crs=CRS
    )


# --------------------------------------------------------------------------- #
# coverage-source builder + loader tests
# --------------------------------------------------------------------------- #


def _coverage_source(pairs):
    """pairs: list of (NAME, geometry)."""
    return gpd.GeoDataFrame(
        {
            "NAME": [n for n, _ in pairs],
            "DESCRIPTIO": ["Ceremonial County"] * len(pairs),
        },
        geometry=gpd.GeoSeries([g for _, g in pairs], crs=CRS),
        crs=CRS,
    )


def _allowlist_pairs(offset=0):
    pairs = []
    for i, county in enumerate(REVISED_COVERAGE_COUNTIES):
        x = (i + offset) * 10
        pairs.append((county, _rect(x, 0, x + 5, 5)))
    return pairs


def test_coverage_loader_selects_exactly_the_allow_list(tmp_path):
    pairs = _allowlist_pairs()
    pairs.append(("Somerset", _rect(10_000, 0, 10_005, 5)))
    pairs.append(("Shetland", _BOWTIE))  # invalid, not selected -> ignored
    path = _write_or_skip(tmp_path, _coverage_source(pairs), "cov.gpkg")

    out = load_revised_coverage(path)

    assert list(out.columns) == ["county_name", "geometry"]
    assert list(out["county_name"]) == sorted(REVISED_COVERAGE_COUNTIES)
    assert len(out) == len(REVISED_COVERAGE_COUNTIES)
    assert "Somerset" not in set(out["county_name"])
    assert out.crs.to_epsg() == 27700
    assert list(out.index) == list(range(len(out)))


def test_coverage_loader_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_revised_coverage(tmp_path / "nope.gpkg")


def test_coverage_loader_missing_name_column(tmp_path):
    src = _coverage_source(_allowlist_pairs()).rename(columns={"NAME": "county"})
    with pytest.raises(ValueError, match="NAME"):
        load_revised_coverage(_write(tmp_path, src, "cov.gpkg"))


def test_coverage_loader_wrong_crs(tmp_path):
    src = _coverage_source(_allowlist_pairs()).to_crs("EPSG:4326")
    with pytest.raises(ValueError, match="27700"):
        load_revised_coverage(_write(tmp_path, src, "cov.gpkg"))


def test_coverage_loader_missing_allow_list_county_raises(tmp_path):
    pairs = [p for p in _allowlist_pairs() if p[0] != "Dorset"]
    with pytest.raises(ValueError, match="Dorset"):
        load_revised_coverage(_write(tmp_path, _coverage_source(pairs), "cov.gpkg"))


def test_coverage_loader_duplicate_allow_list_county_raises(tmp_path):
    pairs = _allowlist_pairs()
    pairs.append(("Dorset", _rect(20_000, 0, 20_005, 5)))
    with pytest.raises(ValueError, match="[Dd]uplicate"):
        load_revised_coverage(_write(tmp_path, _coverage_source(pairs), "cov.gpkg"))


def test_coverage_loader_invalid_selected_geometry_raises(tmp_path):
    pairs = _allowlist_pairs()
    pairs = [(n, _BOWTIE if n == "Dorset" else g) for n, g in pairs]
    path = _write_or_skip(tmp_path, _coverage_source(pairs), "cov.gpkg")
    if gpd.read_file(path).geometry.is_valid.all():
        pytest.skip("GPKG round-trip repaired the invalid selected geometry")
    with pytest.raises(ValueError, match="invalid"):
        load_revised_coverage(path)


def test_coverage_loader_non_polygon_selected_geometry_raises(tmp_path):
    pairs = _allowlist_pairs()
    pairs = [(n, Point(1, 1) if n == "Dorset" else g) for n, g in pairs]
    path = _write_or_skip(tmp_path, _coverage_source(pairs), "cov.gpkg")
    with pytest.raises(ValueError, match="non-polygonal"):
        load_revised_coverage(path)


def test_coverage_loader_non_selected_invalid_geometry_is_ignored(tmp_path):
    pairs = _allowlist_pairs()
    pairs.append(("Shetland", _BOWTIE))
    path = _write_or_skip(tmp_path, _coverage_source(pairs), "cov.gpkg")

    out = load_revised_coverage(path)  # must not raise

    assert set(out["county_name"]) == set(REVISED_COVERAGE_COUNTIES)


# --------------------------------------------------------------------------- #
# revised + legacy loaders
# --------------------------------------------------------------------------- #


def test_load_revised_valid_schema(tmp_path):
    src = _revised_source(
        [
            {"geom": MultiPolygon([_rect(0, 0, 100, 100)]), "code": "ASNW"},
            {"geom": MultiPolygon([_rect(200, 0, 300, 100)]), "code": "ARW"},
            {"geom": MultiPolygon([_rect(400, 0, 500, 100)]), "code": "AWPP"},
            {"geom": MultiPolygon([_rect(600, 0, 700, 100)]), "code": "IAWPP"},
        ]
    )

    out = load_ancient_woodland_revised(_write(tmp_path, src, "rev.gpkg"))

    assert list(out.columns) == AW_OUTPUT_COLUMNS
    assert list(out.index) == [0, 1, 2, 3]
    assert out.crs.to_epsg() == 27700
    assert set(out["inventory"]) == {"revised"}
    assert list(out["category_code"]) == ["ASNW", "ARW", "AWPP", "IAWPP"]
    assert list(out["category_name"]) == [REVISED_CATEGORIES[c] for c in out["category_code"]]


def test_load_legacy_valid_schema(tmp_path):
    src = _legacy_source(
        [
            {"geom": _rect(0, 0, 100, 100), "code": "ASNW"},
            {"geom": _rect(200, 0, 300, 100), "code": "PAWS"},
            {"geom": _rect(400, 0, 500, 100), "code": "AWP"},
        ]
    )

    out = load_ancient_woodland_legacy(_write(tmp_path, src, "leg.gpkg"))

    assert list(out.columns) == AW_OUTPUT_COLUMNS
    assert out.crs.to_epsg() == 27700
    assert set(out["inventory"]) == {"legacy"}
    assert list(out["category_code"]) == ["ASNW", "PAWS", "AWP"]
    # legacy codes preserved, not normalised onto revised ARW/AWPP
    assert "ARW" not in set(out["category_code"])
    assert list(out["category_name"]) == [LEGACY_CATEGORIES[c] for c in out["category_code"]]


@pytest.mark.parametrize(
    "loader,name", [(load_ancient_woodland_revised, "rev"), (load_ancient_woodland_legacy, "leg")]
)
def test_load_missing_file(tmp_path, loader, name):
    with pytest.raises(FileNotFoundError):
        loader(tmp_path / f"missing_{name}.gpkg")


def test_load_revised_wrong_crs(tmp_path):
    src = _revised_source([{"geom": _rect(0, 0, 100, 100), "code": "ASNW"}]).to_crs("EPSG:4326")
    with pytest.raises(ValueError, match="27700"):
        load_ancient_woodland_revised(_write(tmp_path, src, "rev.gpkg"))


def test_load_legacy_missing_crs(tmp_path):
    src = _legacy_source([{"geom": _rect(0, 0, 100, 100), "code": "ASNW"}]).set_crs(
        None, allow_override=True
    )
    path = tmp_path / "leg_nocrs.gpkg"
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message="'crs' was not provided", category=UserWarning
        )
        src.to_file(path, driver="GPKG")
    if gpd.read_file(path).crs is not None:
        pytest.skip("GPKG round-trip did not preserve an undefined CRS on this stack")

    with pytest.raises(ValueError, match="CRS"):
        load_ancient_woodland_legacy(path)


@pytest.mark.parametrize("col", ["name", "status", "themename", "themeid"])
def test_load_revised_missing_required_column(tmp_path, col):
    src = _revised_source([{"geom": _rect(0, 0, 100, 100), "code": "ASNW"}]).drop(columns=[col])
    with pytest.raises(ValueError, match=col):
        load_ancient_woodland_revised(_write(tmp_path, src, "rev.gpkg"))


@pytest.mark.parametrize("col", ["name", "status", "themname", "themid"])
def test_load_legacy_missing_required_column(tmp_path, col):
    src = _legacy_source([{"geom": _rect(0, 0, 100, 100), "code": "ASNW"}]).drop(columns=[col])
    with pytest.raises(ValueError, match=col):
        load_ancient_woodland_legacy(_write(tmp_path, src, "leg.gpkg"))


def test_load_revised_non_polygon_geometry(tmp_path):
    gdf = gpd.GeoDataFrame(
        {
            "name": ["a", "b"],
            "status": ["ASNW", "ASNW"],
            "themename": [REVISED_CATEGORIES["ASNW"]] * 2,
            "themeid": ["X1", "X2"],
        },
        geometry=[Point(0, 0), Point(10, 10)],
        crs=CRS,
    )
    with pytest.raises(ValueError, match="non-polygonal"):
        load_ancient_woodland_revised(_write(tmp_path, gdf, "rev_pts.gpkg"))


def test_load_revised_null_geometry(tmp_path):
    src = _revised_source(
        [
            {"geom": _rect(0, 0, 100, 100), "code": "ASNW"},
            {"geom": None, "code": "ARW"},
        ]
    )
    path = _write_or_skip(tmp_path, src, "rev_null.gpkg")
    if not gpd.read_file(path).geometry.isna().any():
        pytest.skip("GPKG round-trip did not preserve a null geometry on this stack")
    with pytest.raises(ValueError, match="null geometr"):
        load_ancient_woodland_revised(path)


def test_load_revised_empty_geometry(tmp_path):
    src = _revised_source(
        [
            {"geom": _rect(0, 0, 100, 100), "code": "ASNW"},
            {"geom": Polygon(), "code": "ARW"},
        ]
    )
    path = _write_or_skip(tmp_path, src, "rev_empty.gpkg")
    back = gpd.read_file(path).geometry
    if not (back.isna().any() or back.is_empty.any()):
        pytest.skip("GPKG round-trip did not preserve an empty geometry on this stack")
    with pytest.raises(ValueError):
        load_ancient_woodland_revised(path)


def test_load_revised_empty_source(tmp_path):
    path = _write_or_skip(tmp_path, _revised_source([]), "rev_empty_src.gpkg")
    if len(gpd.read_file(path)) != 0:
        pytest.skip("GPKG writer will not create a zero-feature layer on this stack")
    with pytest.raises(ValueError, match="no features"):
        load_ancient_woodland_revised(path)


def test_load_revised_invalid_geometry_warns_and_keeps_unchanged(tmp_path):
    assert not _BOWTIE.is_valid
    src = _revised_source(
        [
            {"geom": _rect(200, 0, 300, 100), "code": "ASNW"},
            {"geom": _BOWTIE, "code": "ARW"},
        ]
    )
    path = _write_or_skip(tmp_path, src, "rev_invalid.gpkg")
    if gpd.read_file(path).geometry.is_valid.all():
        pytest.skip("GPKG round-trip repaired the invalid geometry on this stack")

    with pytest.warns(UserWarning, match="invalid geometr"):
        out = load_ancient_woodland_revised(path)

    assert len(out) == 2
    assert int((~out.geometry.is_valid).sum()) == 1  # left unchanged, not repaired


def test_load_legacy_invalid_geometry_warns(tmp_path):
    src = _legacy_source(
        [
            {"geom": _rect(200, 0, 300, 100), "code": "ASNW"},
            {"geom": _BOWTIE, "code": "PAWS"},
        ]
    )
    path = _write_or_skip(tmp_path, src, "leg_invalid.gpkg")
    if gpd.read_file(path).geometry.is_valid.all():
        pytest.skip("GPKG round-trip repaired the invalid geometry on this stack")

    with pytest.warns(UserWarning, match="invalid geometr"):
        load_ancient_woodland_legacy(path)


@pytest.mark.parametrize("code", ["ASNW", "ARW", "AWPP", "IAWPP"])
def test_load_revised_allowed_codes(tmp_path, code):
    src = _revised_source([{"geom": _rect(0, 0, 100, 100), "code": code}])
    out = load_ancient_woodland_revised(_write(tmp_path, src, "rev.gpkg"))
    assert out["category_code"].iloc[0] == code


@pytest.mark.parametrize("code", ["ASNW", "PAWS", "AWP"])
def test_load_legacy_allowed_codes(tmp_path, code):
    src = _legacy_source([{"geom": _rect(0, 0, 100, 100), "code": code}])
    out = load_ancient_woodland_legacy(_write(tmp_path, src, "leg.gpkg"))
    assert out["category_code"].iloc[0] == code


def test_load_revised_unknown_code_raises(tmp_path):
    src = _revised_source(
        [
            {"geom": _rect(0, 0, 100, 100), "code": "ASNW"},
            {"geom": _rect(200, 0, 300, 100), "code": "PAWS", "themename": "Mystery"},
        ]
    )
    with pytest.raises(ValueError, match="PAWS"):
        load_ancient_woodland_revised(_write(tmp_path, src, "rev.gpkg"))


def test_load_legacy_unknown_code_raises(tmp_path):
    src = _legacy_source(
        [
            {"geom": _rect(0, 0, 100, 100), "code": "ASNW"},
            {"geom": _rect(200, 0, 300, 100), "code": "IAWPP", "themname": "Mystery"},
        ]
    )
    with pytest.raises(ValueError, match="IAWPP"):
        load_ancient_woodland_legacy(_write(tmp_path, src, "leg.gpkg"))


def test_load_revised_code_name_mismatch_raises(tmp_path):
    src = _revised_source(
        [{"geom": _rect(0, 0, 100, 100), "code": "ASNW", "themename": "Ancient Replanted Woodland"}]
    )
    with pytest.raises(ValueError, match="disagree"):
        load_ancient_woodland_revised(_write(tmp_path, src, "rev.gpkg"))


def test_load_revised_blank_name_allowed(tmp_path):
    src = _revised_source([{"geom": _rect(0, 0, 100, 100), "code": "ASNW", "name": ""}])
    out = load_ancient_woodland_revised(_write(tmp_path, src, "rev.gpkg"))
    assert out["aw_name"].iloc[0] == ""


def test_load_revised_duplicate_theme_id_allowed(tmp_path):
    src = _revised_source(
        [
            {"geom": _rect(0, 0, 100, 100), "code": "ASNW", "themeid": "DUP-1"},
            {"geom": _rect(200, 0, 300, 100), "code": "ARW", "themeid": "DUP-1"},
        ]
    )
    out = load_ancient_woodland_revised(_write(tmp_path, src, "rev.gpkg"))
    assert list(out["theme_id"]) == ["DUP-1", "DUP-1"]


def test_load_legacy_numeric_theme_id_conversion(tmp_path):
    src = _legacy_source([{"geom": _rect(0, 0, 100, 100), "code": "ASNW", "themid": 1_481_207.0}])
    out = load_ancient_woodland_legacy(_write(tmp_path, src, "leg.gpkg"))
    assert out["theme_id"].iloc[0] == "1481207"


def test_load_revised_string_theme_id_passthrough(tmp_path):
    src = _revised_source([{"geom": _rect(0, 0, 100, 100), "code": "ASNW", "themeid": "ESS-2501"}])
    out = load_ancient_woodland_revised(_write(tmp_path, src, "rev.gpkg"))
    assert out["theme_id"].iloc[0] == "ESS-2501"


# --------------------------------------------------------------------------- #
# analysis
# --------------------------------------------------------------------------- #

_INSIDE_COV = _cov(_rect(-5_000, -5_000, 5_000, 5_000))
_OUTSIDE_COV = _cov(_rect(5_000, 5_000, 9_000, 9_000))
_WEST_HALF_COV = _cov(_rect(-5_000, -5_000, 500, 5_000))  # covers site x 0..500


def test_site_inside_coverage_ignores_colocated_legacy():
    revised = _revised([{"geom": _rect(-500, -500, 2_000, 2_000), "code": "ASNW"}])
    legacy = _legacy([{"geom": _rect(-500, -500, 2_000, 2_000), "code": "PAWS"}])

    result = calculate_ancient_woodland_overlap(_site(), revised, legacy, _INSIDE_COV)

    assert result.has_overlap is True
    assert result.feature_count == 1
    row = result.features.iloc[0]
    assert row["inventory"] == "revised"
    assert row["category_code"] == "ASNW"
    assert row["intersection_area_m2"] == pytest.approx(1_000_000)
    assert result.affected_area_m2 == pytest.approx(1_000_000)
    assert result.affected_pct == pytest.approx(100)
    assert result.revised_coverage_area_m2 == pytest.approx(1_000_000)
    assert result.fallback_area_m2 == pytest.approx(0.0)


def test_site_outside_coverage_uses_legacy_only():
    revised = _revised([{"geom": _rect(-500, -500, 2_000, 2_000), "code": "ASNW"}])
    legacy = _legacy([{"geom": _rect(-500, -500, 2_000, 2_000), "code": "PAWS"}])

    result = calculate_ancient_woodland_overlap(_site(), revised, legacy, _OUTSIDE_COV)

    assert result.feature_count == 1
    row = result.features.iloc[0]
    assert row["inventory"] == "legacy"
    assert row["category_code"] == "PAWS"
    assert result.affected_area_m2 == pytest.approx(1_000_000)
    assert result.revised_coverage_area_m2 == pytest.approx(0.0)
    assert result.fallback_area_m2 == pytest.approx(1_000_000)


def test_site_crossing_boundary_uses_revised_and_legacy_on_each_side():
    revised = _revised([{"geom": _rect(-500, -500, 2_000, 2_000), "code": "ASNW"}])
    legacy = _legacy([{"geom": _rect(-500, -500, 2_000, 2_000), "code": "PAWS"}])

    result = calculate_ancient_woodland_overlap(_site(), revised, legacy, _WEST_HALF_COV)

    assert result.feature_count == 2
    by_inv = dict(zip(result.features["inventory"], result.features["intersection_area_m2"]))
    assert by_inv["revised"] == pytest.approx(500_000)
    assert by_inv["legacy"] == pytest.approx(500_000)
    assert result.affected_area_m2 == pytest.approx(1_000_000)  # disjoint parts, no double count
    assert result.affected_pct == pytest.approx(100)
    assert result.revised_coverage_area_m2 == pytest.approx(500_000)
    assert result.fallback_area_m2 == pytest.approx(500_000)


def test_site_outside_all_coverage_uses_whole_site_as_fallback():
    # coverage polygons exist but none is anywhere near the site (empty sindex hit)
    cov = _cov([_rect(5_000, 5_000, 6_000, 6_000), _rect(7_000, 7_000, 8_000, 8_000)])
    revised = _revised([{"geom": _rect(-500, -500, 2_000, 2_000), "code": "ASNW"}])
    legacy = _legacy([{"geom": _rect(-500, -500, 2_000, 2_000), "code": "PAWS"}])

    result = calculate_ancient_woodland_overlap(_site(), revised, legacy, cov)

    assert result.revised_coverage_area_m2 == pytest.approx(0.0)
    assert result.fallback_area_m2 == pytest.approx(1_000_000)
    assert set(result.features["inventory"]) == {"legacy"}
    assert result.affected_area_m2 == pytest.approx(1_000_000)


def test_site_intersects_one_coverage_polygon_of_several():
    # three disjoint coverage polygons; only the middle one contains the site
    cov = _cov(
        [
            _rect(-9_000, -9_000, -8_000, -8_000),
            _rect(-5_000, -5_000, 5_000, 5_000),
            _rect(8_000, 8_000, 9_000, 9_000),
        ]
    )
    revised = _revised([{"geom": _rect(-500, -500, 2_000, 2_000), "code": "ASNW"}])
    legacy = _legacy([{"geom": _rect(-500, -500, 2_000, 2_000), "code": "PAWS"}])

    result = calculate_ancient_woodland_overlap(_site(), revised, legacy, cov)

    assert set(result.features["inventory"]) == {"revised"}
    assert result.revised_coverage_area_m2 == pytest.approx(1_000_000)
    assert result.fallback_area_m2 == pytest.approx(0.0)


def test_site_intersects_two_adjacent_coverage_polygons():
    # two counties meeting at x = 500; the site (x 0..1000) straddles the join
    cov = _cov([_rect(-5_000, -5_000, 500, 5_000), _rect(500, -5_000, 5_000, 5_000)])
    revised = _revised([{"geom": _rect(-500, -500, 2_000, 2_000), "code": "ASNW"}])
    legacy = _legacy([{"geom": _rect(-500, -500, 2_000, 2_000), "code": "PAWS"}])

    result = calculate_ancient_woodland_overlap(_site(), revised, legacy, cov)

    assert set(result.features["inventory"]) == {"revised"}
    assert result.revised_coverage_area_m2 == pytest.approx(1_000_000)
    assert result.fallback_area_m2 == pytest.approx(0.0)
    assert result.affected_area_m2 == pytest.approx(1_000_000)


def test_revised_features_outside_coverage_are_ignored():
    # revised woodland only in the eastern (non-covered) half of the site
    revised = _revised([{"geom": _rect(600, 0, 1_000, 1_000), "code": "ASNW"}])
    legacy = _legacy([{"geom": _rect(600, 0, 1_000, 1_000), "code": "PAWS"}])

    result = calculate_ancient_woodland_overlap(_site(), revised, legacy, _WEST_HALF_COV)

    # revised polygon sits outside coverage -> ignored; legacy picks it up in fallback
    assert set(result.features["inventory"]) == {"legacy"}
    assert result.affected_area_m2 == pytest.approx(400_000)


def test_legacy_features_inside_coverage_are_ignored():
    revised = _revised([{"geom": _rect(9_000, 9_000, 9_500, 9_500), "code": "ASNW"}])  # far away
    legacy = _legacy([{"geom": _rect(-500, -500, 2_000, 2_000), "code": "PAWS"}])

    result = calculate_ancient_woodland_overlap(_site(), revised, legacy, _INSIDE_COV)

    assert result.has_overlap is False
    assert result.feature_count == 0
    assert result.affected_area_m2 == 0.0
    assert result.fallback_area_m2 == pytest.approx(0.0)


def test_overlapping_same_category_polygons_are_unioned():
    revised = _revised(
        [
            {"geom": _rect(-500, 0, 600, 1_000), "code": "ASNW"},
            {"geom": _rect(400, 0, 1_500, 1_000), "code": "ASNW"},
        ]
    )
    legacy = _legacy([{"geom": _rect(9_000, 9_000, 9_500, 9_500), "code": "PAWS"}])

    result = calculate_ancient_woodland_overlap(_site(), revised, legacy, _INSIDE_COV)

    assert result.feature_count == 1
    assert result.features["intersection_area_m2"].iloc[0] == pytest.approx(1_000_000)
    assert result.affected_area_m2 == pytest.approx(1_000_000)  # not 1,200,000


def test_per_category_areas_can_exceed_headline():
    revised = _revised(
        [
            {"geom": _rect(-100, -100, 1_100, 1_100), "code": "ASNW"},
            {"geom": _rect(-100, -100, 1_100, 1_100), "code": "ARW"},
        ]
    )
    legacy = _legacy([{"geom": _rect(9_000, 9_000, 9_500, 9_500), "code": "PAWS"}])

    result = calculate_ancient_woodland_overlap(_site(), revised, legacy, _INSIDE_COV)

    assert result.feature_count == 2
    assert sum(result.features["intersection_area_m2"]) == pytest.approx(2_000_000)
    assert result.affected_area_m2 == pytest.approx(1_000_000)


def test_boundary_touch_only_does_not_count():
    revised = _revised([{"geom": _rect(1_000, 0, 2_000, 1_000), "code": "ASNW"}])
    legacy = _legacy([{"geom": _rect(9_000, 9_000, 9_500, 9_500), "code": "PAWS"}])

    result = calculate_ancient_woodland_overlap(_site(), revised, legacy, _INSIDE_COV)

    assert result.has_overlap is False
    assert result.feature_count == 0
    assert result.affected_area_m2 == 0.0


def test_no_overlap_zero_result_schema():
    revised = _revised([{"geom": _rect(9_000, 9_000, 9_500, 9_500), "code": "ASNW"}])
    legacy = _legacy([{"geom": _rect(8_000, 8_000, 8_500, 8_500), "code": "PAWS"}])

    result = calculate_ancient_woodland_overlap(_site(), revised, legacy, _INSIDE_COV)

    assert result.has_overlap is False
    assert result.feature_count == 0
    assert list(result.features.columns) == FEATURE_COLUMNS
    assert result.features.crs.to_epsg() == 27700
    assert result.affected_area_m2 == 0.0
    assert result.affected_pct == 0.0
    assert result.site_area_m2 == pytest.approx(1_000_000)
    assert result.revised_coverage_area_m2 == pytest.approx(1_000_000)


def test_required_revised_side_empty_raises():
    legacy = _legacy([{"geom": _rect(-500, -500, 2_000, 2_000), "code": "PAWS"}])
    with pytest.raises(ValueError, match="revised"):
        calculate_ancient_woodland_overlap(_site(), _revised([]), legacy, _INSIDE_COV)


def test_required_fallback_side_empty_raises():
    revised = _revised([{"geom": _rect(-500, -500, 2_000, 2_000), "code": "ASNW"}])
    with pytest.raises(ValueError, match="legacy"):
        calculate_ancient_woodland_overlap(_site(), revised, _legacy([]), _OUTSIDE_COV)


def test_non_required_side_empty_is_fine():
    # site fully inside coverage: legacy is not needed and may be empty
    revised = _revised([{"geom": _rect(-500, -500, 2_000, 2_000), "code": "ASNW"}])

    result = calculate_ancient_woodland_overlap(_site(), revised, _legacy([]), _INSIDE_COV)

    assert result.has_overlap is True
    assert set(result.features["inventory"]) == {"revised"}


def test_hectare_and_percentage_arithmetic():
    revised = _revised([{"geom": _rect(0, 0, 250, 1_000), "code": "ASNW"}])  # 250,000 m^2
    legacy = _legacy([{"geom": _rect(9_000, 9_000, 9_500, 9_500), "code": "PAWS"}])

    result = calculate_ancient_woodland_overlap(_site(), revised, legacy, _INSIDE_COV)

    assert result.affected_area_ha == pytest.approx(result.affected_area_m2 / 10_000)
    assert result.affected_area_ha == pytest.approx(25)
    assert result.affected_pct == pytest.approx(
        100 * result.affected_area_m2 / result.site_area_m2
    )
    assert result.affected_pct == pytest.approx(25)
    row = result.features.iloc[0]
    assert row["intersection_area_ha"] == pytest.approx(row["intersection_area_m2"] / 10_000)


def test_features_sorted_by_area_then_inventory_then_code():
    revised = _revised(
        [
            {"geom": _rect(0, 0, 100, 1_000), "code": "ARW"},   # 100,000
            {"geom": _rect(0, 0, 900, 1_000), "code": "ASNW"},  # 900,000
        ]
    )
    legacy = _legacy([{"geom": _rect(9_000, 9_000, 9_500, 9_500), "code": "PAWS"}])

    result = calculate_ancient_woodland_overlap(_site(), revised, legacy, _INSIDE_COV)

    assert list(result.features["category_code"]) == ["ASNW", "ARW"]


def test_result_schema_and_crs_are_exact():
    revised = _revised([{"geom": _rect(-500, -500, 2_000, 2_000), "code": "ASNW"}])
    legacy = _legacy([{"geom": _rect(9_000, 9_000, 9_500, 9_500), "code": "PAWS"}])

    result = calculate_ancient_woodland_overlap(_site(), revised, legacy, _INSIDE_COV)

    assert list(result.features.columns) == FEATURE_COLUMNS
    assert result.features.geometry.name == "geometry"
    assert result.features.crs.to_epsg() == 27700


@pytest.mark.parametrize("bad", ["site", "revised", "legacy", "revised_coverage"])
def test_analysis_non_geodataframe_raises_type_error(bad):
    args = {
        "site": _site(),
        "revised": _revised([{"geom": _rect(0, 0, 100, 100), "code": "ASNW"}]),
        "legacy": _legacy([{"geom": _rect(0, 0, 100, 100), "code": "PAWS"}]),
        "revised_coverage": _INSIDE_COV,
    }
    args[bad] = [(0, 0), (1, 1)]
    with pytest.raises(TypeError, match=f"{bad} must be a geopandas.GeoDataFrame"):
        calculate_ancient_woodland_overlap(**args)


@pytest.mark.parametrize("bad", ["site", "revised", "legacy", "revised_coverage"])
def test_analysis_wrong_crs_raises(bad):
    args = {
        "site": _site(),
        "revised": _revised([{"geom": _rect(0, 0, 100, 100), "code": "ASNW"}]),
        "legacy": _legacy([{"geom": _rect(0, 0, 100, 100), "code": "PAWS"}]),
        "revised_coverage": _cov(_rect(-5_000, -5_000, 5_000, 5_000)),
    }
    args[bad] = args[bad].to_crs("EPSG:4326")
    with pytest.raises(ValueError, match="27700"):
        calculate_ancient_woodland_overlap(**args)


@pytest.mark.parametrize("bad", ["site", "revised", "legacy", "revised_coverage"])
def test_analysis_missing_crs_raises(bad):
    args = {
        "site": _site(),
        "revised": _revised([{"geom": _rect(0, 0, 100, 100), "code": "ASNW"}]),
        "legacy": _legacy([{"geom": _rect(0, 0, 100, 100), "code": "PAWS"}]),
        "revised_coverage": _cov(_rect(-5_000, -5_000, 5_000, 5_000)),
    }
    args[bad] = args[bad].set_crs(None, allow_override=True)
    with pytest.raises(ValueError, match="CRS"):
        calculate_ancient_woodland_overlap(**args)


def test_analysis_site_multiple_rows_raises():
    site = gpd.GeoDataFrame(
        geometry=[_rect(0, 0, 1_000, 1_000), _rect(2_000, 2_000, 3_000, 3_000)], crs=CRS
    )
    with pytest.raises(ValueError, match="exactly one row"):
        calculate_ancient_woodland_overlap(
            site,
            _revised([{"geom": _rect(0, 0, 100, 100), "code": "ASNW"}]),
            _legacy([{"geom": _rect(0, 0, 100, 100), "code": "PAWS"}]),
            _INSIDE_COV,
        )


@pytest.mark.parametrize("col", ["aw_name", "category_code", "category_name", "theme_id", "inventory"])
def test_analysis_missing_normalised_column_raises(col):
    revised = _revised([{"geom": _rect(-500, -500, 2_000, 2_000), "code": "ASNW"}]).drop(columns=[col])
    legacy = _legacy([{"geom": _rect(9_000, 9_000, 9_500, 9_500), "code": "PAWS"}])
    with pytest.raises(ValueError, match=col):
        calculate_ancient_woodland_overlap(_site(), revised, legacy, _INSIDE_COV)


def test_analysis_empty_coverage_raises():
    empty_cov = gpd.GeoDataFrame({"county_name": pd.Series(dtype="object")},
                                 geometry=gpd.GeoSeries([], crs=CRS), crs=CRS)
    with pytest.raises(ValueError, match="empty"):
        calculate_ancient_woodland_overlap(
            _site(),
            _revised([{"geom": _rect(0, 0, 100, 100), "code": "ASNW"}]),
            _legacy([{"geom": _rect(0, 0, 100, 100), "code": "PAWS"}]),
            empty_cov,
        )


def test_analysis_non_polygon_coverage_raises():
    bad_cov = gpd.GeoDataFrame(
        {"county_name": ["x"]}, geometry=[Point(0, 0)], crs=CRS
    )
    with pytest.raises(ValueError, match="polygonal"):
        calculate_ancient_woodland_overlap(
            _site(),
            _revised([{"geom": _rect(0, 0, 100, 100), "code": "ASNW"}]),
            _legacy([{"geom": _rect(0, 0, 100, 100), "code": "PAWS"}]),
            bad_cov,
        )


def test_result_is_frozen_dataclass():
    result = calculate_ancient_woodland_overlap(
        _site(),
        _revised([{"geom": _rect(-500, -500, 2_000, 2_000), "code": "ASNW"}]),
        _legacy([{"geom": _rect(9_000, 9_000, 9_500, 9_500), "code": "PAWS"}]),
        _INSIDE_COV,
    )
    assert isinstance(result, AncientWoodlandOverlapResult)
    with pytest.raises(FrozenInstanceError):
        result.has_overlap = False
