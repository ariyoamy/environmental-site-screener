# Methodology

This file explains the methods I have implemented so far.

At the moment, the code covers five parts of the screening workflow:

- checking that a candidate site boundary is usable
- calculating overlap between a candidate site and SSSI polygons
- finding the nearest SSSI to a candidate site
- checking whether a candidate site falls within a mapped SSSI Impact Risk Zone
- calculating overlap between a candidate site and mapped priority habitat

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

## SSSI Impact Risk Zones

### What this step does

`load_sssi_irz()` reads the Natural England SSSI Impact Risk Zones (IRZ) GeoPackage. `calculate_sssi_irz_context()` then reports whether part of a candidate site falls inside one or more IRZ polygons.

An IRZ polygon is a mapped area around SSSIs where some types or scales of development could have potential adverse impacts and Natural England's advice should be checked. This step only provides that context.

### Loading the source

The source must already be in `EPSG:27700`. It is not reprojected.

The published attribute the loader needs is `irzurl`, the hyperlink to Natural England's online IRZ advice. It is kept verbatim.

From each `irzurl` the loader parses `irz_code`: the 13-digit `irzcode` value in the URL, kept as an opaque string. Its individual digits are not interpreted. The `notes=` and `location=` parameters in the URL are ignored. `load_sssi_irz()` returns `irzurl`, `irz_code` and `geometry`.

Null, empty and non-polygon geometry is rejected. Invalid geometry is not repaired: this is an authoritative source, so the loader leaves any invalid polygons unchanged and emits one warning with the count. The 31 August 2026 source has 4 invalid geometries, so the warning fires on the real file.

### How the context check works

`calculate_sssi_irz_context()` takes the validated site from `validate_site()` and the IRZ layer from `load_sssi_irz()`. It checks that both are `GeoDataFrames`, both have a CRS, both are in `EPSG:27700`, the site has one row, and the IRZ layer has `irzurl` and `irz_code`. It does not reproject or repair geometry.

It uses the IRZ layer's spatial index to find candidate polygons, then checks the real site/IRZ intersection. Only positive-area intersection counts. A site that only touches an IRZ boundary line or a corner has no IRZ context.

The result reports:

- `has_irz_context`: whether any IRZ polygon is intersected with positive area
- `zones`: the qualifying IRZ polygons, with their original (unclipped) geometries, `irzurl` and `irz_code`, sorted by `irzurl`
- `advice_urls`: the distinct advice URLs from those zones

It does not report overlap area, overlap percentage or nearest-IRZ distance. If there is no context, or the IRZ layer has no rows, it returns an empty result with the same columns and CRS.

### What has_irz_context = True means

It means only that part of the candidate site falls within one or more mapped IRZ advice areas.

It is not a finding that development will harm an SSSI, that Natural England consultation is required, that the site is unsuitable, or that any planning or legal conclusion has been reached. The actual advice depends on the type and scale of the proposed development and must be checked through the Natural England advice URL.

### A note on the source shape

Inspection of the 31 August 2026 source found the IRZ polygons behave as an effectively non-overlapping coverage: they share boundaries and produce only negligible floating-point sliver overlaps. The analysis does not rely on this always being true. If a future release has genuinely overlapping polygons, `calculate_sssi_irz_context()` still just returns every polygon the site intersects with positive area.

### Checking this

`tests/test_sssi_irz.py` covers the loader and the context check with small synthetic GeoPackages and geometries: valid load and exact output columns, missing file, wrong or missing CRS, missing/null/empty `irzurl`, null/empty/non-polygon geometry, an empty source, invalid geometry that warns but is left unchanged, 13-digit code parsing, an unparseable code that leaves `irz_code` missing with a warning, a site inside one zone, a site spanning two zones, no context, boundary touch only, two zone rows sharing one URL, an empty IRZ layer, and the CRS, type, column and row guards. `scripts/check_sssi_irz_context.py` runs the loader and context check against the real IRZ GeoPackage.

## Priority Habitats

### What this step does

`load_priority_habitats()` reads the Natural England Priority Habitats Inventory (PHI) GeoPackage. `calculate_priority_habitat_overlap()` then reports where a candidate site overlaps mapped priority habitat: whether there is any positive-area overlap, which habitat classes are involved, how much of each falls inside the site, and how much of the site is affected overall.

The PHI is not a single "priority habitat" layer. Natural England's catalogue for this release lists 27 priority habitat classes plus four classes that are not priority habitat. This step keeps those apart rather than treating every PHI polygon as priority habitat.

### Loading the source

The source must already be in `EPSG:27700`. It is not reprojected.

The loader keeps `uid`, `mainhabs`, `habcodes`, `is_priority`, `featdesc`, `addhabs`, `primsource` and `geometry`. Only those required attributes plus geometry are read from the GeoPackage; other source fields such as `areaha` are not read at all, so the source polygon area plays no part in any calculation here.

The project works from an explicit set of 27 priority habitat codes and four context codes. The context (non-priority) codes are:

- `FHEAT` — Fragmented heath
- `GMOOR` — Grass moorland
- `GQSIG` — Good quality semi-improved grassland
- `NMHAB` — No main habitat

`mainhabs` (names) and `habcodes` (codes) are comma-separated and can list more than one habitat for a polygon. They are split, whitespace-stripped, and paired positionally. If a row's `mainhabs` and `habcodes` token counts do not match, the loader raises an error rather than guessing the pairing. If a `habcodes` token is not one of the 27 priority or 4 context codes, the loader raises an error naming the unexpected codes rather than guessing what it means.

`is_priority` is `True` when at least one `habcodes` token is a priority code.

`addhabs` (additional habitats present) is kept as provenance only. It never contributes to the priority-habitat overlap metric.

Geometry is not repaired. Null, empty and non-polygon geometry is rejected. Invalid geometry is left unchanged: this is an authoritative source, so the loader emits one warning with the count and does not alter the polygons. The 31 August 2026 source has one invalid geometry, so the warning fires on the real file.

### How overlap is measured

`calculate_priority_habitat_overlap()` takes the validated site from `validate_site()` and the PHI layer from `load_priority_habitats()`. It checks that both are `GeoDataFrames`, both have a CRS, both are in `EPSG:27700`, the site has one row, and the PHI layer has `uid`, `mainhabs`, `habcodes` and `primsource`. It does not reproject or repair geometry.

It uses the PHI spatial index to find candidate polygons, then checks the real site/polygon intersection. Only positive-area intersection counts. A site that only touches a polygon boundary line or a corner is not an overlap.

Classification is per main-habitat code token, not simply per polygon. For each positive-area intersection the `mainhabs` and `habcodes` tokens are paired; each priority token attributes that polygon's clipped geometry to that priority class, and each context token adds the polygon to the context result. A polygon coded `GQSIG,TORCH` therefore contributes Traditional orchard to the priority metric and `GQSIG` to context at the same time.

### Per-class results

`habitats` has one row per priority habitat class the site overlaps, with `habitat_code`, `habitat_name`, `intersection_area_m2`, `intersection_area_ha` and the clipped `geometry`. For each class its clipped pieces are combined into one geometry before the area is measured, so overlapping source polygons of the same class are not double-counted. Rows are sorted by area, largest first, then by code.

### Overall affected area

The overall affected area is not the sum of the per-class areas. All the clipped pieces that belong to at least one priority class are combined into one geometry and the area of that is measured, so ground under more than one priority habitat is counted once.

A polygon with several priority main habitats contributes its clipped geometry to each of those classes. Because of that, the sum of the per-class areas can legitimately exceed the overall affected area: the same ground is attributed to more than one habitat class, while the headline affected area counts that ground once.

Hectares are square metres divided by 10,000. The affected percentage is the priority-habitat affected area divided by the site area, times 100. Values are returned as calculated, without rounding.

### Context classes

The four context classes are returned separately in `context`, with `uid`, `context_codes`, `context_habitats`, `primsource` and the original unclipped polygon geometry. A polygon carrying more than one context code reports those codes together, and rows are sorted by `uid`. No area or percentage is calculated for context; it is there as information, not as a constraint measure.

### What this step does not do

- no ecological quality score, habitat severity ranking or condition assessment
- no planning, legal or ecological-harm conclusion
- no distance to the nearest priority habitat when nothing overlaps
- source `areaha` is not used

### Checking this

`tests/test_priority_habitats.py` covers the loader and the overlap function with small synthetic GeoPackages and geometries: valid load and exact output columns, missing file, missing required column, wrong or missing CRS, null/empty/non-polygon geometry, null/empty/duplicate `uid`, null/empty `mainhabs` or `habcodes`, a `mainhabs`/`habcodes` token-count mismatch that raises, an unknown habitat code that raises, invalid geometry that warns but is left unchanged, the four context codes giving `is_priority` false, representative priority codes giving `is_priority` true, a `GQSIG,TORCH` polygon feeding both the priority metric and context, `addhabs` not affecting the priority metric, overlapping same-class polygons unioned rather than summed, a boundary touch excluded, a context-only site, the per-class areas summing to more than the overall affected area, the exact result schemas and CRS, the frozen dataclass, and the CRS, type, column and row guards. `scripts/check_priority_habitats_overlap.py` runs the loader and overlap function against the real PHI GeoPackage.
