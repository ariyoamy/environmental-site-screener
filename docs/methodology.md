# Methodology

This document describes the analytical methods currently implemented in the
codebase. It is updated as functionality is added. At present it covers only
candidate-site validation.

## Candidate-site validation

### Purpose

`validate_site()` (in `src/environmental_site_screener/site.py`) is the single
entry point for turning a caller-supplied site boundary into a clean,
predictable input for the screening operations that follow.

It checks that the input is structurally usable, attempts to repair invalid geometry where a valid polygonal result can be produced, and returns the site in a single known coordinate reference
system so that later intersection, area and distance calculations do not each
have to re-check these conditions.

It does not perform any environmental analysis and makes no judgement about the
site.

### Accepted input

The function accepts one `geopandas.GeoDataFrame` containing exactly one row.
The geometry of that row must be a `Polygon` or a `MultiPolygon`.

The following inputs are rejected with a clear error:

- anything that is not a `GeoDataFrame` (raises `TypeError`);
- a `GeoDataFrame` with no rows, or with more than one row (raises `ValueError`);
- a row whose geometry is missing (`None`) or empty (raises `ValueError`);
- a geometry that is not a `Polygon` or `MultiPolygon`, for example a `Point`
  or `LineString` (raises `ValueError`).

A `MultiPolygon` is accepted as-is. The function does not split it into parts or
merge multiple rows into one feature.

### Coordinate reference system

The input `GeoDataFrame` must have an explicitly defined CRS. If `crs` is not
set, the function raises `ValueError` and stops.

The code does not guess a missing CRS. A GeoDataFrame with no CRS gives no
reliable indication of what its coordinates mean, and assuming a common default
such as EPSG:4326 would silently produce wrong reprojections, wrong overlap
areas and wrong distances with no warning to the user. Requiring the CRS to be
stated makes the caller responsible for that decision.

The analytical CRS is EPSG:27700 (OSGB36 / British National Grid), held as the
module constant `ANALYTICAL_CRS`. If the input is in a different CRS it is
reprojected to EPSG:27700. If it is already in EPSG:27700 it is left as-is.

Area and, later, distance calculations are performed in this projected CRS
rather than in EPSG:4326. EPSG:4326 coordinates are in degrees of latitude and
longitude, so areas and lengths computed directly from them are not in usable
ground units and are distorted by latitude. EPSG:27700 is a metre-based
projected system covering Great Britain, so areas come out in square metres
(convertible to hectares) and distances in metres. After reprojection the
function checks that the site geometry has a positive area and raises
`ValueError` if it does not.

### Invalid-geometry handling

If the input geometry is not valid (for example a self-intersecting polygon),
the function:

1. emits a `UserWarning` stating that the geometry is invalid and that repair
   is being attempted;
2. calls `shapely.make_valid()` on the geometry;
3. accepts the repaired result only if it is a non-empty, valid `Polygon` or
   `MultiPolygon`.

If `make_valid()` cannot produce a valid `Polygon` or `MultiPolygon` (for
example if it returns an empty geometry, a line, or a geometry collection), the
function raises `ValueError` rather than continuing with an unusable geometry.

Repair can change the geometry type: a repaired self-intersecting polygon may
come back as a `MultiPolygon`.

### Attributes and input handling

Non-geometry columns on the input row are preserved. The function operates on a
copy of the input, so any attribute columns present on the supplied
`GeoDataFrame` appear unchanged on the returned `GeoDataFrame`.

The original input `GeoDataFrame` is not modified. Callers keep their object
with its original CRS and geometry; the validated, reprojected site is returned
as a new object.

### Current exclusions

The following are deliberately not implemented at this stage:

- **No England-boundary or location check.** The function does not verify that
  the site falls within England or Great Britain. A site outside the expected
  area will still validate.
- **No Z-coordinate handling.** Any Z values on the input geometry are left
  untouched. There is no flattening to 2D.
- **No multi-feature dissolve.** A `GeoDataFrame` with more than one row is
  rejected, not merged into a single site.

## Validation and testing

The behaviour above is exercised by synthetic tests in `tests/test_site.py`.
The geometries are small, hand-constructed shapes with known expected results
rather than extracts from real datasets. The current tests cover:

- a valid EPSG:27700 `Polygon` is accepted and returned unchanged;
- a valid EPSG:27700 `MultiPolygon` is accepted and returned as a valid
  `MultiPolygon`;
- an EPSG:4326 `Polygon` is reprojected to EPSG:27700, with the output
  coordinates in the expected British National Grid range;
- a 1 km square defined in EPSG:27700, converted to EPSG:4326 and passed back
  in, returns an area of approximately 1,000,000 m² (within 1%), confirming the
  units and CRS of the area calculation;
- a `GeoDataFrame` with no CRS is rejected;
- an empty `GeoDataFrame` is rejected;
- a `GeoDataFrame` with more than one row is rejected;
- a row with `None` geometry, and a row with an empty `Polygon`, are rejected;
- non-polygon geometries (`Point`, `LineString`) are rejected;
- a self-intersecting "bowtie" polygon is repaired to a valid geometry and a
  `UserWarning` is emitted during repair;
- non-geometry attribute columns are preserved on the output;
- the original input `GeoDataFrame` is not mutated: after the call it is still
  in EPSG:4326 with its original geometry, while the returned object is in
  EPSG:27700.
