"""Tests for :mod:`environmental_site_screener.priority_habitats`.

Loader tests write tiny synthetic GeoPackages via ``tmp_path``. Analysis tests
build small in-memory GeoDataFrames shaped like the loader output. The candidate
site is a 1,000 m square at the origin in EPSG:27700 and PHI polygons are simple
rectangles, so every expected area is easy to check by hand.
"""

import warnings
from dataclasses import FrozenInstanceError

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import MultiPolygon, Point, Polygon

from environmental_site_screener.priority_habitats import (
    CONTEXT_HABITAT_CODES,
    PRIORITY_HABITAT_CODES,
    PriorityHabitatOverlapResult,
    calculate_priority_habitat_overlap,
    load_priority_habitats,
)

CRS = "EPSG:27700"

_NAMES = {
    "DWOOD": "Deciduous woodland",
    "RBEDS": "Reedbeds",
    "SALTM": "Coastal saltmarsh",
    "TORCH": "Traditional orchard",
    "LHEAT": "Lowland heathland",
    "BLBOG": "Blanket bog",
    "PONDS": "Ponds",
    "LAKES": "Lakes",
    "MHWSC": "Mountain heaths and willow scrub",
    "GQSIG": "Good quality semi improved grassland",
    "GMOOR": "Grass moorland",
    "FHEAT": "Fragmented heath",
    "NMHAB": "No main habitat but additional habitats present",
}

_MISSING = object()


def _name(code):
    return _NAMES.get(code, f"{code} habitat")


def _rect(xmin, ymin, xmax, ymax):
    return Polygon(
        [(xmin, ymin), (xmin, ymax), (xmax, ymax), (xmax, ymin), (xmin, ymin)]
    )


def _default_main(codes):
    if not codes:
        return ""
    return ",".join(_name(c.strip()) for c in codes.split(","))


def _phi_source(rows):
    """GeoDataFrame shaped like the raw PHI source (6 string fields + geometry)."""
    string_cols = ["uid", "mainhabs", "habcodes", "featdesc", "addhabs", "primsource"]
    if not rows:
        gdf = gpd.GeoDataFrame(
            {c: pd.Series(dtype="object") for c in string_cols},
            geometry=gpd.GeoSeries([], crs=CRS),
            crs=CRS,
        )
        return gdf
    recs = []
    geoms = []
    for i, row in enumerate(rows):
        codes = row["habcodes"]
        main = row.get("mainhabs", _MISSING)
        if main is _MISSING:
            main = _default_main(codes)
        recs.append(
            {
                "uid": row.get("uid", f"PHID{i:08d}_{i:09d}"),
                "mainhabs": main,
                "habcodes": codes,
                "featdesc": row.get("featdesc", ""),
                "addhabs": row.get("addhabs", ""),
                "primsource": row.get("primsource", f"Test source {i} (X)"),
            }
        )
        geoms.append(row["geom"])
    return gpd.GeoDataFrame(recs, geometry=gpd.GeoSeries(geoms, crs=CRS), crs=CRS)


def _phi(rows):
    """GeoDataFrame shaped like load_priority_habitats output (adds is_priority)."""
    recs = []
    geoms = []
    for i, row in enumerate(rows):
        codes = row["habcodes"]
        code_tokens = [c.strip() for c in codes.split(",")]
        main = row.get("mainhabs", _MISSING)
        if main is _MISSING:
            main = _default_main(codes)
        recs.append(
            {
                "uid": row.get("uid", f"PHID{i:08d}_{i:09d}"),
                "mainhabs": main,
                "habcodes": codes,
                "is_priority": any(c in PRIORITY_HABITAT_CODES for c in code_tokens),
                "featdesc": row.get("featdesc", ""),
                "addhabs": row.get("addhabs", ""),
                "primsource": row.get("primsource", f"src{i}"),
            }
        )
        geoms.append(row["geom"])
    if not recs:
        return gpd.GeoDataFrame(
            {
                c: pd.Series(dtype="object")
                for c in ["uid", "mainhabs", "habcodes", "is_priority", "featdesc", "addhabs", "primsource"]
            },
            geometry=gpd.GeoSeries([], crs=CRS),
            crs=CRS,
        )
    return gpd.GeoDataFrame(recs, geometry=gpd.GeoSeries(geoms, crs=CRS), crs=CRS)


def _site(geom=None):
    return gpd.GeoDataFrame(
        geometry=[geom if geom is not None else _rect(0, 0, 1_000, 1_000)], crs=CRS
    )


def _write(tmp_path, gdf, name="phi.gpkg"):
    path = tmp_path / name
    gdf.to_file(path, driver="GPKG")
    return path


def _write_or_skip(tmp_path, gdf, name="phi.gpkg"):
    path = tmp_path / name
    try:
        gdf.to_file(path, driver="GPKG")
    except Exception as exc:  # pragma: no cover - depends on GDAL build
        pytest.skip(f"GPKG writer could not represent this source: {exc!r}")
    return path


# --------------------------------------------------------------------------- #
# loader
# --------------------------------------------------------------------------- #


def test_load_valid_source(tmp_path):
    src = _phi_source(
        [
            {"geom": MultiPolygon([_rect(0, 0, 100, 100)]), "habcodes": "DWOOD"},
            {"geom": MultiPolygon([_rect(200, 0, 300, 100)]), "habcodes": "GQSIG"},
            {
                "geom": MultiPolygon([_rect(400, 0, 500, 100)]),
                "habcodes": "RBEDS,SALTM",
                "mainhabs": "Reedbeds,Coastal saltmarsh",
            },
        ]
    )

    out = load_priority_habitats(_write(tmp_path, src))

    assert list(out.columns) == [
        "uid", "mainhabs", "habcodes", "is_priority", "featdesc", "addhabs", "primsource", "geometry",
    ]
    assert list(out.index) == [0, 1, 2]
    assert out.crs.to_epsg() == 27700
    assert list(out["is_priority"]) == [True, False, True]


def test_load_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_priority_habitats(tmp_path / "does_not_exist.gpkg")


def test_load_wrong_crs(tmp_path):
    src = _phi_source([{"geom": _rect(0, 0, 100, 100), "habcodes": "DWOOD"}]).to_crs("EPSG:4326")

    with pytest.raises(ValueError, match="27700"):
        load_priority_habitats(_write(tmp_path, src))


def test_load_missing_crs(tmp_path):
    src = _phi_source([{"geom": _rect(0, 0, 100, 100), "habcodes": "DWOOD"}]).set_crs(
        None, allow_override=True
    )
    path = tmp_path / "no_crs.gpkg"
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message="'crs' was not provided", category=UserWarning
        )
        src.to_file(path, driver="GPKG")
    if gpd.read_file(path).crs is not None:
        pytest.skip("GPKG round-trip did not preserve an undefined CRS on this stack")

    with pytest.raises(ValueError, match="CRS"):
        load_priority_habitats(path)


@pytest.mark.parametrize(
    "col", ["uid", "mainhabs", "habcodes", "featdesc", "addhabs", "primsource"]
)
def test_load_missing_required_column(tmp_path, col):
    src = _phi_source([{"geom": _rect(0, 0, 100, 100), "habcodes": "DWOOD"}]).drop(columns=[col])

    with pytest.raises(ValueError, match=col):
        load_priority_habitats(_write(tmp_path, src))


def test_load_non_polygon_geometry(tmp_path):
    gdf = gpd.GeoDataFrame(
        {
            "uid": ["u1", "u2"],
            "mainhabs": ["Reedbeds", "Reedbeds"],
            "habcodes": ["RBEDS", "RBEDS"],
            "featdesc": ["", ""],
            "addhabs": ["", ""],
            "primsource": ["s", "s"],
        },
        geometry=[Point(0, 0), Point(1_000, 1_000)],
        crs=CRS,
    )

    with pytest.raises(ValueError, match="non-polygonal"):
        load_priority_habitats(_write(tmp_path, gdf, "points.gpkg"))


def test_load_null_geometry(tmp_path):
    src = _phi_source(
        [
            {"geom": _rect(0, 0, 100, 100), "habcodes": "DWOOD"},
            {"geom": None, "habcodes": "RBEDS"},
        ]
    )
    path = _write_or_skip(tmp_path, src, "null_geom.gpkg")
    if not gpd.read_file(path).geometry.isna().any():
        pytest.skip("GPKG round-trip did not preserve a null geometry on this stack")

    with pytest.raises(ValueError, match="null geometr"):
        load_priority_habitats(path)


def test_load_empty_geometry(tmp_path):
    src = _phi_source(
        [
            {"geom": _rect(0, 0, 100, 100), "habcodes": "DWOOD"},
            {"geom": Polygon(), "habcodes": "RBEDS"},
        ]
    )
    path = _write_or_skip(tmp_path, src, "empty_geom.gpkg")
    back = gpd.read_file(path).geometry
    if not (back.isna().any() or back.is_empty.any()):
        pytest.skip("GPKG round-trip did not preserve an empty geometry on this stack")

    with pytest.raises(ValueError):
        load_priority_habitats(path)


def test_load_empty_source(tmp_path):
    src = _phi_source([])
    path = _write_or_skip(tmp_path, src, "empty.gpkg")
    if len(gpd.read_file(path)) != 0:
        pytest.skip("GPKG writer will not create a zero-feature layer on this stack")

    with pytest.raises(ValueError, match="no features"):
        load_priority_habitats(path)


def test_load_invalid_geometry_warns_and_keeps_unchanged(tmp_path):
    bowtie = Polygon([(0, 0), (0, 100), (100, 0), (100, 100), (0, 0)])
    assert not bowtie.is_valid
    src = _phi_source(
        [
            {"geom": _rect(200, 0, 300, 100), "habcodes": "DWOOD"},
            {"geom": bowtie, "habcodes": "RBEDS"},
        ]
    )
    path = _write_or_skip(tmp_path, src, "invalid.gpkg")
    if gpd.read_file(path).geometry.is_valid.all():
        pytest.skip("GPKG round-trip repaired the invalid geometry on this stack")

    with pytest.warns(UserWarning, match="invalid geometr"):
        out = load_priority_habitats(path)

    assert len(out) == 2
    assert int((~out.geometry.is_valid).sum()) == 1  # left unchanged, not repaired


@pytest.mark.parametrize("code", ["FHEAT", "GMOOR", "GQSIG", "NMHAB"])
def test_load_context_codes_are_not_priority(tmp_path, code):
    src = _phi_source([{"geom": _rect(0, 0, 100, 100), "habcodes": code}])

    out = load_priority_habitats(_write(tmp_path, src))

    assert bool(out["is_priority"].iloc[0]) is False


@pytest.mark.parametrize("code", ["DWOOD", "RBEDS", "TORCH", "BLBOG", "PONDS", "LAKES", "MHWSC"])
def test_load_priority_codes_derive_true(tmp_path, code):
    src = _phi_source([{"geom": _rect(0, 0, 100, 100), "habcodes": code}])

    out = load_priority_habitats(_write(tmp_path, src))

    assert bool(out["is_priority"].iloc[0]) is True


@pytest.mark.parametrize(
    "codes,main",
    [
        ("RBEDS,SALTM", "Reedbeds,Coastal saltmarsh"),
        ("GQSIG,TORCH", "Good quality semi improved grassland,Traditional orchard"),
    ],
)
def test_load_multitoken_with_priority_is_priority(tmp_path, codes, main):
    src = _phi_source([{"geom": _rect(0, 0, 100, 100), "habcodes": codes, "mainhabs": main}])

    out = load_priority_habitats(_write(tmp_path, src))

    assert bool(out["is_priority"].iloc[0]) is True


def test_load_unknown_habitat_code_raises(tmp_path):
    src = _phi_source(
        [
            {"geom": _rect(0, 0, 100, 100), "habcodes": "DWOOD"},
            {"geom": _rect(200, 0, 300, 100), "habcodes": "ZZZZZ", "mainhabs": "Mystery habitat"},
        ]
    )

    with pytest.raises(ValueError, match="ZZZZZ"):
        load_priority_habitats(_write(tmp_path, src))


def test_load_token_count_mismatch_raises(tmp_path):
    src = _phi_source(
        [{"geom": _rect(0, 0, 100, 100), "habcodes": "RBEDS,SALTM", "mainhabs": "Reedbeds"}]
    )

    with pytest.raises(ValueError, match="token count"):
        load_priority_habitats(_write(tmp_path, src))


def test_load_null_uid_raises(tmp_path):
    src = _phi_source(
        [
            {"geom": _rect(0, 0, 100, 100), "habcodes": "DWOOD", "uid": "u1"},
            {"geom": _rect(200, 0, 300, 100), "habcodes": "RBEDS", "uid": None},
        ]
    )

    with pytest.raises(ValueError, match="uid"):
        load_priority_habitats(_write(tmp_path, src))


def test_load_duplicate_uid_raises(tmp_path):
    src = _phi_source(
        [
            {"geom": _rect(0, 0, 100, 100), "habcodes": "DWOOD", "uid": "dup"},
            {"geom": _rect(200, 0, 300, 100), "habcodes": "RBEDS", "uid": "dup"},
        ]
    )

    with pytest.raises(ValueError, match="duplicate uid"):
        load_priority_habitats(_write(tmp_path, src))


@pytest.mark.parametrize("col", ["mainhabs", "habcodes"])
def test_load_null_classification_raises(tmp_path, col):
    rows = [
        {"geom": _rect(0, 0, 100, 100), "habcodes": "DWOOD"},
        {"geom": _rect(200, 0, 300, 100), "habcodes": "RBEDS", "mainhabs": "Reedbeds"},
    ]
    rows[1][col] = None
    src = _phi_source(rows)

    with pytest.raises(ValueError, match=col):
        load_priority_habitats(_write(tmp_path, src))


def test_load_ignores_extra_source_columns(tmp_path):
    src = _phi_source([{"geom": _rect(0, 0, 100, 100), "habcodes": "DWOOD"}])
    src["areaha"] = [0.01]
    src["version"] = ["Sep_25"]
    src["shape_area"] = [1.0]

    out = load_priority_habitats(_write(tmp_path, src))

    assert list(out.columns) == [
        "uid", "mainhabs", "habcodes", "is_priority", "featdesc", "addhabs", "primsource", "geometry",
    ]


# --------------------------------------------------------------------------- #
# analysis
# --------------------------------------------------------------------------- #


def test_context_site_inside_one_priority_habitat():
    phi = _phi([{"geom": _rect(-500, -500, 2_000, 2_000), "habcodes": "DWOOD"}])

    result = calculate_priority_habitat_overlap(_site(), phi)

    assert result.has_priority_overlap is True
    assert result.habitat_count == 1
    row = result.habitats.iloc[0]
    assert row["habitat_code"] == "DWOOD"
    assert row["habitat_name"] == "Deciduous woodland"
    assert row["intersection_area_m2"] == pytest.approx(1_000_000)
    assert row["intersection_area_ha"] == pytest.approx(100)
    assert result.affected_area_m2 == pytest.approx(1_000_000)
    assert result.affected_area_ha == pytest.approx(100)
    assert result.affected_pct == pytest.approx(100)
    assert len(result.context) == 0


def test_site_spanning_two_priority_classes():
    phi = _phi(
        [
            {"geom": _rect(-500, 0, 500, 1_000), "habcodes": "RBEDS"},
            {"geom": _rect(500, 0, 1_500, 1_000), "habcodes": "SALTM"},
        ]
    )

    result = calculate_priority_habitat_overlap(_site(), phi)

    assert result.habitat_count == 2
    assert sorted(result.habitats["intersection_area_m2"]) == pytest.approx([500_000, 500_000])
    assert result.affected_area_m2 == pytest.approx(1_000_000)
    assert result.affected_pct == pytest.approx(100)


def test_multi_priority_polygon_contributes_to_each_class():
    phi = _phi(
        [
            {
                "geom": _rect(-500, -500, 2_000, 2_000),
                "habcodes": "RBEDS,SALTM",
                "mainhabs": "Reedbeds,Coastal saltmarsh",
            }
        ]
    )

    result = calculate_priority_habitat_overlap(_site(), phi)

    assert set(result.habitats["habitat_code"]) == {"RBEDS", "SALTM"}
    per_class = list(result.habitats["intersection_area_m2"])
    assert sum(per_class) == pytest.approx(2_000_000)  # each class gets the full clip
    assert result.affected_area_m2 == pytest.approx(1_000_000)  # unioned once
    assert result.affected_area_m2 < sum(per_class)
    assert result.affected_pct == pytest.approx(100)


def test_gqsig_torch_polygon_splits_priority_and_context():
    phi = _phi(
        [
            {
                "geom": _rect(-500, -500, 2_000, 2_000),
                "habcodes": "GQSIG,TORCH",
                "mainhabs": "Good quality semi improved grassland,Traditional orchard",
                "uid": "u_mix",
            }
        ]
    )

    result = calculate_priority_habitat_overlap(_site(), phi)

    assert list(result.habitats["habitat_code"]) == ["TORCH"]
    assert result.affected_area_m2 == pytest.approx(1_000_000)
    assert len(result.context) == 1
    ctx = result.context.iloc[0]
    assert ctx["uid"] == "u_mix"
    assert ctx["context_codes"] == "GQSIG"
    assert ctx["context_habitats"] == "Good quality semi improved grassland"
    assert ctx.geometry.equals(_rect(-500, -500, 2_000, 2_000))  # original, unclipped


def test_nmhab_with_priority_addhabs_stays_context_only():
    phi = _phi(
        [
            {
                "geom": _rect(-500, -500, 2_000, 2_000),
                "habcodes": "NMHAB",
                "addhabs": "DWOOD",
                "uid": "u_nm",
            }
        ]
    )

    result = calculate_priority_habitat_overlap(_site(), phi)

    assert result.has_priority_overlap is False
    assert result.habitat_count == 0
    assert len(result.habitats) == 0
    assert result.affected_area_m2 == 0.0
    assert len(result.context) == 1
    assert result.context["context_codes"].iloc[0] == "NMHAB"


def test_overlapping_priority_polygons_same_class_are_unioned():
    phi = _phi(
        [
            {"geom": _rect(-500, 0, 600, 1_000), "habcodes": "DWOOD"},  # x 0..600 in site
            {"geom": _rect(400, 0, 1_500, 1_000), "habcodes": "DWOOD"},  # x 400..1000 in site
        ]
    )

    result = calculate_priority_habitat_overlap(_site(), phi)

    assert result.habitat_count == 1
    assert result.habitats["intersection_area_m2"].iloc[0] == pytest.approx(1_000_000)
    assert result.affected_area_m2 == pytest.approx(1_000_000)  # not 1,200,000


def test_boundary_touch_only_does_not_count():
    phi = _phi([{"geom": _rect(1_000, 0, 2_000, 1_000), "habcodes": "DWOOD"}])

    result = calculate_priority_habitat_overlap(_site(), phi)

    assert result.has_priority_overlap is False
    assert result.habitat_count == 0
    assert result.affected_area_m2 == 0.0
    assert len(result.context) == 0


def test_context_only_site_has_zero_priority_area_but_context():
    phi = _phi([{"geom": _rect(-500, -500, 2_000, 2_000), "habcodes": "GMOOR", "uid": "u_ctx"}])

    result = calculate_priority_habitat_overlap(_site(), phi)

    assert result.has_priority_overlap is False
    assert result.habitat_count == 0
    assert result.affected_area_m2 == 0.0
    assert result.site_area_m2 == pytest.approx(1_000_000)
    assert len(result.context) == 1
    assert result.context["context_codes"].iloc[0] == "GMOOR"


def test_no_intersection_returns_zero_result():
    phi = _phi([{"geom": _rect(5_000, 5_000, 6_000, 6_000), "habcodes": "DWOOD"}])

    result = calculate_priority_habitat_overlap(_site(), phi)

    assert result.has_priority_overlap is False
    assert result.habitat_count == 0
    assert list(result.habitats.columns) == [
        "habitat_code", "habitat_name", "intersection_area_m2", "intersection_area_ha", "geometry",
    ]
    assert result.habitats.crs.to_epsg() == 27700
    assert len(result.context) == 0
    assert result.affected_area_m2 == 0.0
    assert result.affected_pct == 0.0


def test_empty_phi_layer_returns_zero_result():
    result = calculate_priority_habitat_overlap(_site(), _phi([]))

    assert result.has_priority_overlap is False
    assert result.habitat_count == 0
    assert list(result.habitats.columns) == [
        "habitat_code", "habitat_name", "intersection_area_m2", "intersection_area_ha", "geometry",
    ]
    assert result.habitats.crs.to_epsg() == 27700
    assert list(result.context.columns) == [
        "uid", "context_codes", "context_habitats", "primsource", "geometry",
    ]
    assert result.context.crs.to_epsg() == 27700
    assert result.affected_area_m2 == 0.0


def test_class_area_sum_can_exceed_overall_affected_area():
    # one polygon coded with three priority habitats, covering the whole site
    phi = _phi(
        [
            {
                "geom": _rect(-100, -100, 1_100, 1_100),
                "habcodes": "RBEDS,SALTM,DWOOD",
                "mainhabs": "Reedbeds,Coastal saltmarsh,Deciduous woodland",
            }
        ]
    )

    result = calculate_priority_habitat_overlap(_site(), phi)

    assert result.habitat_count == 3
    assert sum(result.habitats["intersection_area_m2"]) == pytest.approx(3_000_000)
    assert result.affected_area_m2 == pytest.approx(1_000_000)


def test_habitats_sorted_by_area_then_code():
    phi = _phi(
        [
            {"geom": _rect(0, 0, 100, 1_000), "habcodes": "LHEAT"},  # 100,000
            {"geom": _rect(0, 0, 900, 1_000), "habcodes": "DWOOD"},  # 900,000
            {"geom": _rect(0, 0, 400, 1_000), "habcodes": "RBEDS"},  # 400,000
            {"geom": _rect(0, 0, 100, 1_000), "habcodes": "BLBOG"},  # 100,000 (ties LHEAT)
        ]
    )

    result = calculate_priority_habitat_overlap(_site(), phi)

    # descending area, then habitat_code ascending as the tie-break
    assert list(result.habitats["habitat_code"]) == ["DWOOD", "RBEDS", "BLBOG", "LHEAT"]


def test_hectare_and_percentage_calculations():
    phi = _phi([{"geom": _rect(0, 0, 250, 1_000), "habcodes": "DWOOD"}])  # 250,000 m^2

    result = calculate_priority_habitat_overlap(_site(), phi)

    assert result.affected_area_ha == pytest.approx(result.affected_area_m2 / 10_000)
    assert result.affected_area_ha == pytest.approx(25)
    assert result.affected_pct == pytest.approx(
        100 * result.affected_area_m2 / result.site_area_m2
    )
    assert result.affected_pct == pytest.approx(25)


def test_result_schema_and_crs_are_exact():
    phi = _phi([{"geom": _rect(-500, -500, 2_000, 2_000), "habcodes": "DWOOD,GQSIG",
                 "mainhabs": "Deciduous woodland,Good quality semi improved grassland"}])

    result = calculate_priority_habitat_overlap(_site(), phi)

    assert list(result.habitats.columns) == [
        "habitat_code", "habitat_name", "intersection_area_m2", "intersection_area_ha", "geometry",
    ]
    assert result.habitats.geometry.name == "geometry"
    assert result.habitats.crs.to_epsg() == 27700
    assert list(result.context.columns) == [
        "uid", "context_codes", "context_habitats", "primsource", "geometry",
    ]
    assert result.context.geometry.name == "geometry"
    assert result.context.crs.to_epsg() == 27700


@pytest.mark.parametrize("bad", ["site", "phi"])
def test_analysis_non_geodataframe_raises_type_error(bad):
    site, phi = _site(), _phi([{"geom": _rect(0, 0, 100, 100), "habcodes": "DWOOD"}])
    not_a_gdf = [(0, 0), (0, 1), (1, 1)]
    if bad == "site":
        site = not_a_gdf
    else:
        phi = not_a_gdf

    with pytest.raises(TypeError, match=f"{bad} must be a geopandas.GeoDataFrame"):
        calculate_priority_habitat_overlap(site, phi)


@pytest.mark.parametrize("bad", ["site", "phi"])
def test_analysis_wrong_crs_raises(bad):
    site, phi = _site(), _phi([{"geom": _rect(0, 0, 100, 100), "habcodes": "DWOOD"}])
    if bad == "site":
        site = site.to_crs("EPSG:4326")
    else:
        phi = phi.to_crs("EPSG:4326")

    with pytest.raises(ValueError, match="27700"):
        calculate_priority_habitat_overlap(site, phi)


@pytest.mark.parametrize("bad", ["site", "phi"])
def test_analysis_missing_crs_raises(bad):
    site, phi = _site(), _phi([{"geom": _rect(0, 0, 100, 100), "habcodes": "DWOOD"}])
    if bad == "site":
        site = site.set_crs(None, allow_override=True)
    else:
        phi = phi.set_crs(None, allow_override=True)

    with pytest.raises(ValueError, match="CRS"):
        calculate_priority_habitat_overlap(site, phi)


def test_analysis_site_multiple_rows_raises():
    site = gpd.GeoDataFrame(
        geometry=[_rect(0, 0, 1_000, 1_000), _rect(2_000, 2_000, 3_000, 3_000)], crs=CRS
    )

    with pytest.raises(ValueError, match="exactly one row"):
        calculate_priority_habitat_overlap(
            site, _phi([{"geom": _rect(0, 0, 100, 100), "habcodes": "DWOOD"}])
        )


@pytest.mark.parametrize("col", ["uid", "mainhabs", "habcodes", "primsource"])
def test_analysis_missing_phi_column_raises(col):
    phi = _phi([{"geom": _rect(-500, -500, 2_000, 2_000), "habcodes": "DWOOD"}]).drop(columns=[col])

    with pytest.raises(ValueError, match=col):
        calculate_priority_habitat_overlap(_site(), phi)


def test_result_is_frozen_dataclass():
    result = calculate_priority_habitat_overlap(
        _site(), _phi([{"geom": _rect(-500, -500, 2_000, 2_000), "habcodes": "DWOOD"}])
    )

    assert isinstance(result, PriorityHabitatOverlapResult)
    with pytest.raises(FrozenInstanceError):
        result.has_priority_overlap = False


def test_context_multiple_codes_reported_together():
    phi = _phi(
        [
            {
                "geom": _rect(-500, -500, 2_000, 2_000),
                "habcodes": "GQSIG,GMOOR",
                "mainhabs": "Good quality semi improved grassland,Grass moorland",
                "uid": "u_ctx2",
            }
        ]
    )

    result = calculate_priority_habitat_overlap(_site(), phi)

    assert result.has_priority_overlap is False
    assert len(result.context) == 1
    assert result.context["context_codes"].iloc[0] == "GMOOR,GQSIG"  # sorted
