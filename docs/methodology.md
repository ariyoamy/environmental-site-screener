# Methodology

This file explains the methods I have implemented so far.

At the moment, the code covers three parts of the screening workflow:

- checking that a candidate site boundary is usable
- calculating overlap between a candidate site and SSSI polygons
- finding the nearest SSSI to a candidate site

I am keeping this file close to the code. Planned ideas can go in the README, project scope or issues. This document is for methods that are already implemented and tested.

Spatial calculations use `EPSG:27700` / OSGB36 British National Grid unless stated otherwise. This keeps area and distance work in metre-based units.

## Candidate-site validation

### What this step does

`validate_site()` prepares a candidate site boundary for the rest of the tool.

It checks that the input is one polygonal site, makes sure the CRS is known, repairs invalid geometry where that can be done safely, and returns a copy in `EPSG:27700`.

It does not run any environmental checks. It just makes sure the site geometry is in a usable state before later functions try to intersect it with environmental datasets.

### Accepted input

The function expects one `geopandas.GeoDataFrame` with exactly one row.

The geometry must be either:

- `Polygon`
- `MultiPolygon`

The function rejects:

- inputs that are not a `GeoDataFrame`
- empty `GeoDataFrame` objects
- inputs with more than one row
- missing or empty geometry
- non-polygon geometry, such as `Point` or `LineString`

A `MultiPolygon` is accepted as one site. The function does not split it into separate parts.

### CRS handling

The input must have a defined CRS.

The function does not guess one. If the CRS is missing, it raises an error.

I chose this because guessing a CRS can make the rest of the analysis look fine while quietly producing wrong areas and distances. For example, assuming `EPSG:4326` when the coordinates are actually in another CRS would give bad reprojection results with no obvious warning.

The project CRS is:

```text
EPSG:27700 — OSGB36 / British National Grid
```

If the site is already in `EPSG:27700` it is left as is. If it is in another CRS it is reprojected to `EPSG:27700`. The target CRS is held in the module as `ANALYTICAL_CRS`.

Area and distance work is done in this projected CRS, not in `EPSG:4326`. Degrees of latitude and longitude are not ground units, and the distortion changes with latitude, so areas and lengths taken straight from them are wrong. `EPSG:27700` is metre based, so areas come out in square metres, and hectares, and distances in metres.

After reprojection the function checks that the site has a positive area. If it does not, it raises an error.

### Invalid geometry

If the site geometry is not valid, for example a self-intersecting polygon, the function:

- emits a `UserWarning` to say the geometry is invalid and repair is being attempted
- runs `shapely.make_valid()` on it
- keeps the result only if it is a non-empty valid `Polygon` or `MultiPolygon`, and otherwise raises an error

Repair can change the geometry type. A repaired `Polygon` can come back as a `MultiPolygon`.

### Attributes and the input object

Non-geometry columns on the input row are kept on the returned site.

The function works on a copy. The caller's original `GeoDataFrame` is not changed. The validated, reprojected site is returned as a new object.

### What this step does not do

- no check that the site is inside England or Great Britain
- no Z-coordinate handling; any Z values are left alone
- no dissolving of several rows into one site; more than one row is rejected

### Checking this

`tests/test_site.py` covers this with small synthetic geometries: a valid polygon and multipolygon, reprojection from `EPSG:4326`, missing CRS, empty and multi-row inputs, null and empty geometry, non-polygon geometry, and a self-intersecting polygon that is repaired with a warning. It also checks that attributes are kept and the input object is not mutated.

## SSSI data

`load_sssi()` reads the Natural England SSSI GeoPackage and returns it as a `GeoDataFrame` for the overlap and distance steps to use.

It keeps four fields: `ref_code`, `name`, `measure` and `geometry`. The other source fields are dropped.

The layer must already be in `EPSG:27700`. It is not reprojected.

Geometry is not repaired. Null, empty, non-polygonal or invalid geometry is rejected, because this is an authoritative source and a problem here should be looked at rather than patched over.

`ref_code` must be present and unique, and `name` must be present. `measure` is kept but may be empty.

The overlap and distance functions assume their SSSI input is the output of `load_sssi()`, so they do not repeat these checks.

## SSSI overlap

### What this step does

`calculate_sssi_overlap()` reports where a candidate site overlaps SSSI polygons: whether there is any positive-area overlap, which SSSIs are involved, how much of each falls inside the site, and how much of the site is affected overall.

### Inputs and guards

It takes the validated site from `validate_site()` and the SSSI layer from `load_sssi()`.

It checks that both are `GeoDataFrames`, both have a CRS, both are in `EPSG:27700`, the site has exactly one row, and the SSSI layer has `ref_code`, `name` and `measure`. It does not reproject, does not repair geometry, and does not repeat the full checks from the earlier steps.

### How overlap is measured

It takes the single site geometry and finds the SSSI rows whose geometry intersects it. For each of those it clips the SSSI to the site and measures the area of the clipped piece, in square metres and in hectares.

Only positive-area overlap counts. If two polygons only share an edge or a point, the clipped area is zero and that SSSI is dropped from the result.

### Per-feature results

The result has one row per overlapping SSSI, with `ref_code`, `name`, `measure`, `intersection_area_m2`, `intersection_area_ha` and the clipped `geometry`. Rows are sorted by intersection area, largest first. `ref_code` is unique in the source, so there is no need to merge rows.

### Overall affected area

The overall affected area is not the sum of the per-feature areas. If two SSSIs cover the same part of the site, that ground would be counted twice.

Instead the clipped pieces are combined into one geometry and the area of that is measured. Ground covered by more than one SSSI is then counted once.

For example, two SSSIs might each cover 600,000 m² of the site, which is 1,200,000 m² added up, but if their clipped pieces together cover the whole site the affected area is 1,000,000 m², or 100% of the site, not 120%.

The affected percentage is the affected area divided by the site area, times 100.

### No overlap and empty layers

If nothing overlaps, or the SSSI layer has no rows, the function still returns a result: no overlap, an empty feature table with the right columns and CRS, and zero for the areas and percentage.

### What this step does not do

- it does not measure distance to SSSIs that do not overlap; that is the next step
- values are returned as calculated, without rounding

### Checking this

`tests/test_overlap.py` uses a 1,000 m square site and simple rectangles: no overlap, complete overlap, partial overlap, several disjoint SSSIs, two overlapping SSSIs where the per-feature areas add up to more than the site but the affected area does not, boundary touch, empty layer, wrong or missing CRS, a MultiPolygon SSSI, and the exact output columns. `scripts/check_sssi_overlap.py` runs the same function against the real SSSI GeoPackage.

## Nearest-SSSI distance

### What this step does

`calculate_nearest_sssi()` finds the smallest distance between a candidate site and the SSSI polygons, and returns the nearest SSSI feature or features.

It is mainly for the case where `calculate_sssi_overlap()` found no positive-area overlap.

### Inputs and guards

It takes the validated site from `validate_site()` and the SSSI layer from `load_sssi()`.

The guards are the same as the overlap step: both `GeoDataFrames`, both with a CRS, both in `EPSG:27700`, the site with one row, and `ref_code`, `name` and `measure` present. In addition the SSSI layer must have at least one feature. An empty layer raises an error, because nearest distance is undefined with nothing to measure to.

It does not reproject or repair the inputs.

### How distance is measured

The calculation uses the site and SSSI geometries directly. It calls `.distance()` from each SSSI polygon to the site polygon, not a centroid distance.

The distance is the minimum edge-to-edge separation, in metres. Kilometres are just metres divided by 1000.

### Zero distance

A zero distance can mean the polygons touch or that they overlap. This function does not tell those cases apart. `calculate_sssi_overlap()` is what decides whether there is positive-area overlap.

### Ties

If several SSSIs have exactly the same calculated minimum distance, all of them are returned. Tied features are sorted by `ref_code` so the order is stable. Only exactly equal distances are treated as ties; there is no tolerance for near-ties.

### What this step does not do

- the returned geometries are the original SSSI polygons, not clipped or simplified
- no shortest-line geometry between the site and the nearest SSSI is produced yet
- no spatial-index optimisation has been added yet; every SSSI distance is calculated
- values are returned as calculated, without rounding

### Checking this

`tests/test_distance.py` uses a 1,000 m square site and simple polygons: a known 100 m gap, the nearest of several features, a diagonal corner-to-corner distance with a known Euclidean value, a boundary touch and a positive-area overlap both giving 0.0, two exactly equidistant SSSIs both returned and sorted by `ref_code`, a MultiPolygon where the nearest part sets the distance, and the CRS and input guards. `scripts/check_sssi_distance.py` runs the function against the real SSSI GeoPackage and checks the result is sane.
