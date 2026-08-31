# Methodology

This file explains the methods I have implemented so far.

At the moment, the code covers seven parts of the screening workflow:

- checking that a candidate site boundary is usable
- calculating overlap between a candidate site and SSSI polygons
- finding the nearest SSSI to a candidate site
- checking whether a candidate site falls within a mapped SSSI Impact Risk Zone
- calculating overlap between a candidate site and mapped priority habitat
- calculating overlap between a candidate site and ancient woodland, revised or legacy
- calculating overlap between a candidate site and mapped Flood Zone 2 or 3

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

## Ancient Woodland

### What this step does

There are two Natural England ancient woodland inventories: a **revised** one (`Ancient Woodland - Revised (England) - Completed Counties`) being rebuilt county by county, and the older **legacy** one (`Ancient Woodland (England)`) that still covers the rest of the country. Natural England's rule is that where a county has been done in the revised inventory, the revised data takes precedence there and the legacy data is the fallback everywhere else. The two must not simply be merged: they overlap heavily inside the revised counties, so a union would double-count.

`load_ancient_woodland_revised()` and `load_ancient_woodland_legacy()` read the two sources. `load_revised_coverage()` builds the polygon that says where "revised" applies. `calculate_ancient_woodland_overlap()` splits the candidate site along that coverage boundary, runs the revised inventory on the inside part and the legacy inventory on the outside part, and reports how much ancient woodland the site overlaps.

### The revised coverage allow-list

Natural England does not publish a completed-county list or a coverage layer, and the revised GeoPackage has no county field. So the coverage is a **project inference**, not Natural England metadata. It is a fixed allow-list of 29 ceremonial counties held in the code as `REVISED_COVERAGE_COUNTIES`, worked out from the current revised snapshot plus a county-by-county diagnostic (assigning every revised and legacy polygon to a ceremonial county by an interior point, then checking nearest-neighbour distance and grid coverage). **This list must be reviewed whenever the revised source is refreshed.**

`load_revised_coverage()` reads the OS Boundary-Line ceremonial counties layer and filters it to that allow-list. The source must be `EPSG:27700` and must have a `NAME` field. Every allow-list county must be present exactly once; a missing or duplicated allow-list county raises. Null, empty, non-polygon or invalid geometry among the **selected** counties raises rather than being repaired. Invalid geometry outside the selected counties (the Boundary-Line `Shetland` polygon is a self-intersection, for example) is never looked at and does not matter. The result has `county_name` and `geometry`, sorted by name, in `EPSG:27700`.

Two named exclusions:

- **Somerset** is left out because the revised inventory only covers part of ceremonial Somerset (the former-Avon north and east); the west of the county is still legacy-only, so treating the whole county as revised would be wrong.
- **City and County of the City of London** is excluded separately; it carries no ancient woodland and is not a delivery area.

**Hampshire** is included, with a caveat: the revised inventory looks complete across the county apart from a small cluster of legacy woods near the south-east edge (around the West Sussex border). It is close enough to whole-county to treat as revised.

### Loading the two inventories

Both loaders return the same normalised columns: `aw_name`, `category_code`, `category_name`, `theme_id`, `inventory` and `geometry`. `inventory` is the literal `"revised"` or `"legacy"`.

The category codes are kept per source and are **not** normalised across inventories:

- revised: `ASNW`, `ARW`, `AWPP`, `IAWPP`
- legacy: `ASNW`, `PAWS`, `AWP`

Revised `ARW` (Ancient Replanted Woodland) and legacy `PAWS` (Plantations on Ancient Woodland Sites) are the same idea under different codes, and revised `AWPP` and legacy `AWP` are both wood pasture, but the code and name are left exactly as the source gives them so it is always clear which inventory a result row came from.

Both sources must already be in `EPSG:27700`; neither loader reprojects. Null, empty and non-polygon geometry is rejected. Invalid geometry is left unchanged, with one warning giving the count: the current revised source has 69 invalid geometries (ring self-intersections), so that warning fires on the real file; the current legacy source has none. The source `area` and `perimeter` fields are not read and take no part in any calculation. Blank woodland names are allowed and `theme_id` is not required to be unique (a multi-part wood shares one ID). The legacy `themid` is a number in the source and is cleaned to a string with no trailing `.0`. Each `category_code` to `category_name` pairing is checked against the mapping in the delivered GeoPackages (not the supporting PDFs, which disagree with the data on the replanted-woodland code); an unexpected code, or a code/name pair that does not match, raises.

### How overlap is measured

`calculate_ancient_woodland_overlap()` takes the validated site, the revised inventory, the legacy inventory and the revised coverage. It checks that all four are `GeoDataFrames`, all have a CRS and are in `EPSG:27700`, the site has one row, the revised and legacy layers have the normalised columns, and the coverage is non-empty and polygonal. It does not reproject or repair anything.

The site is partitioned by the coverage:

```text
revised_part  = site ∩ revised coverage
fallback_part = site − revised coverage
```

The revised inventory is used only against `revised_part`, and the legacy inventory only against `fallback_part`. That is the precedence rule: revised where revised coverage applies, legacy elsewhere. The two parts do not overlap, so ground near the coverage boundary is not counted twice.

Spatial indexes are used twice: once to find which coverage counties the site touches (only those are unioned, not all 29), and once per side to find candidate woodland polygons. For each candidate the real intersection with the relevant site part is taken, and only positive-area intersections are kept. A site that only touches a woodland or coverage boundary line or corner does not count.

### Per-category results

`features` has one row per `(inventory, category_code)` pair the site overlaps, with `inventory`, `category_code`, `category_name`, `intersection_area_m2`, `intersection_area_ha` and the clipped `geometry`. For each pair the clipped pieces are combined into one geometry before the area is measured, so overlapping source polygons of the same category are not double-counted. Rows are sorted by area, largest first, then by `inventory`, then by `category_code`.

### Overall affected area

The overall affected area is not the sum of the per-category areas. Every kept clipped piece, from both site parts, is combined into one geometry and the area of that is measured, so ground under more than one woodland polygon or more than one category is counted once.

Hectares are square metres divided by 10,000. The affected percentage is the affected ancient-woodland area divided by the site area, times 100. Values are returned as calculated, without rounding. The result also records `revised_coverage_area_m2` (how much of the site fell inside revised coverage) and `fallback_area_m2` (how much fell outside); these add up to the site area.

### Missing sources

If the site has a part inside revised coverage but the revised layer is empty, the function raises rather than reporting zero, because a zero there would really mean "the required source was missing". The same applies if the site has a fallback part but the legacy layer is empty. A non-empty source that genuinely has no woodland near the site gives an honest zero result.

### What this step does not do

- no severity score or ranking of woodland categories
- no planning, legal, ecological-harm or suitability conclusion
- no distance to the nearest ancient woodland when nothing overlaps
- source `area` and `perimeter` are not used

### Checking this

`tests/test_ancient_woodland.py` covers the loaders, the coverage loader and the overlap function with small synthetic GeoPackages and geometries: both loaders' exact schemas, missing file, missing required column, wrong or missing CRS, null/empty/non-polygon geometry, invalid revised and legacy geometry warning and staying unchanged, all allowed codes and an unknown code that raises, a code/name mismatch that raises, blank names allowed, duplicate `theme_id` allowed, numeric `themid` cleaned to a string; the coverage loader selecting exactly the 29-county allow-list, a missing or duplicated allow-list county raising, invalid selected coverage geometry raising, invalid non-selected geometry ignored, missing `NAME`, wrong CRS, non-polygon selected geometry; a site fully inside coverage ignoring a co-located legacy polygon, a site fully outside using legacy only, a site crossing the boundary using revised on one side and legacy on the other, a site outside all coverage, a site intersecting one coverage polygon of several, a site straddling two adjacent coverage polygons, revised polygons outside coverage ignored, legacy polygons inside coverage ignored, overlapping same-category polygons unioned rather than summed, per-category areas summing to more than the headline, a boundary touch excluded, a no-overlap zero result, a required-side-empty inventory raising, the exact result schema and CRS, the hectare and percentage arithmetic, and the frozen dataclass. `scripts/check_ancient_woodland_overlap.py` runs the whole pipeline against the real revised, legacy and OS Boundary-Line sources; after the spatial-index prefiltering the site analysis itself takes about 0.1 s (the time is dominated by reading the two large GeoPackages).

## Flood Map for Planning – Flood Zones

### What this step does

`load_flood_zones()` reads the Environment Agency Flood Map for Planning – Flood Zones GeoPackage (layer `Flood_Zones_2_3_Rivers_and_Sea`). `calculate_flood_zone_overlap()` then reports how much of a candidate site overlaps mapped Flood Zone 2 or Flood Zone 3.

This is river and sea flood risk for planning. It is not a property-level flood check, not a flood-risk score, and not a safe/unsafe or planning-permission conclusion.

### Loading the source

The source must already be in `EPSG:27700`; the loader does not reproject. It requires the fields `origin`, `flood_zone` and `flood_source`, and reads only those plus geometry. `flood_zone` must be non-null, non-empty and one of `FZ2` or `FZ3`; anything else raises. Null, empty and non-polygon geometry is rejected. Invalid geometry is left unchanged, with one warning giving the count (the current real source is clean, so no warning fires on it). `flood_source` and `origin` may be null and are preserved as `None`; they are kept verbatim and are not checked against a fixed list of allowed values. The source `fid` is not retained.

`load_flood_zones(path, bbox=None)` takes an optional bounding box:

- `bbox=None` reads the whole national source. This is for audits and manual validation. An actually empty national source raises.
- `bbox=(minx, miny, maxx, maxy)` in `EPSG:27700` first does lightweight metadata checks with `pyogrio.read_info` (source readable, CRS, required fields), then uses the GeoPackage spatial index to read only the features whose bounding box intersects the box. A valid box with no matching features returns an empty layer with the normal columns and CRS, not an error, because that is a real spatial subset rather than a missing source.

The bounding-box read exists because the national GeoPackage has 813,627 features and is about 5.9 GB, while a candidate site only needs the flood polygons near it. In the real smoke check, loading the flood zones for a site dropped from about 224.9 s for the full source to about 0.05 s for the 8 features in the site's bounding box, with the analysis itself about 0.01 s. The intended app call is `load_flood_zones(path, bbox=tuple(site.total_bounds))`.

### How overlap is measured

`calculate_flood_zone_overlap()` takes the validated site and the Flood Zones layer (usually the bounding-box subset). Both must be `GeoDataFrames` in `EPSG:27700`, the site must have one row, and the flood-zones layer must have `flood_zone`, `flood_source` and `origin`. Inputs are not reprojected or repaired.

A bounding-box subset can contain polygons whose boxes overlap the site but whose actual geometry does not, so the analysis still takes the real intersection of each candidate with the site and keeps only positive-area results. A site that only touches a flood-zone boundary line or corner is not an overlap.

### Per-zone results

`zones` has one row per overlapping `flood_zone`, with `flood_zone`, `intersection_area_m2`, `intersection_area_ha`, `site_pct`, `flood_sources`, `origins` and the clipped `geometry`. For each zone the clipped pieces are combined into one geometry before the area is measured. `flood_sources` and `origins` are comma-joined sorted lists of the distinct non-null `flood_source` and `origin` values on that zone's intersecting polygons; a combined value such as `river and sea` is kept whole, not split. Rows are sorted by area, largest first, then by zone.

### Overall affected area

The overall affected area is the area of the union of every kept clipped Flood Zone 2 and Flood Zone 3 piece. It is never the sum of the per-zone areas. In the current delivered data FZ2 and FZ3 do not overlap, so the sum and the union usually match, but the code unions defensively so it stays correct if that changes or if floating-point slivers appear.

Hectares are square metres divided by 10,000. Percentages are against the site area. Values are returned as calculated, without rounding.

An empty but valid local subset (a bounding box with no flood polygons in it) gives a genuine zero result: `has_flood_zone_overlap` is `False`, `zone_count` is `0`, `zones` is empty with the right columns and CRS, the areas and percentage are `0`, and the provenance tuples are empty.

### Flood Zone meanings

The source zone codes `FZ2` and `FZ3` are preserved as-is.

- **Flood Zone 2** is the lower-probability outer band: 0.1%–1% annual probability from rivers, 0.1%–0.5% from the sea, plus accepted recorded flood outlines.
- **Flood Zone 3** is the higher-probability mapped area: 1% or greater from rivers, 0.5% or greater from the sea. Flood Zone 3b (the functional floodplain) is included within Flood Zone 3 and not mapped separately.

In the delivered dataset the FZ2 and FZ3 polygons behave as mutually exclusive bands rather than FZ3 sitting nested inside FZ2. The two zones together make up the full area at 0.1% or greater annual probability.

Flood Zone 1 (less than 0.1% annual probability) is not supplied as geometry. The tool never creates a Flood Zone 1 geometry, result row or flag. When a site has no FZ2 or FZ3 overlap, presentation may say "No mapped Flood Zone 2 or 3 overlap in this dataset". It must not say the site is free from flood risk.

### What this step does not do

- no flood-risk score
- no safe/unsafe conclusion
- no planning-permission conclusion
- no climate-change layer (the Flood Zones plus climate change dataset is separate and not used in this MVP)
- no other flood sources such as surface water, groundwater or drainage
- Flood Zones also ignore the benefit of flood defences (an Environment Agency property of the data)

### Checking this

`tests/test_flood_zones.py` covers the loader and the overlap function with small synthetic GeoPackages and geometries: valid load and exact schema/CRS/index, missing file, missing required column, wrong or missing CRS, null/empty/non-polygon geometry, an empty source, invalid geometry that warns but is left unchanged, allowed `FZ2`/`FZ3`, an unknown or null or empty `flood_zone` that raises, null `flood_source` and null `origin` allowed, `river and sea` preserved verbatim; a `bbox=None` full read, a bounding box selecting only nearby polygons, a bounding box with nothing nearby returning an empty normalised layer, analysis of that empty subset giving a genuine zero result, a bounding-box false positive that only touches the site boundary being dropped by the exact intersection, a bounding-box subset giving the same arithmetic as the full read, and missing source / wrong CRS / missing column still raising on the bounding-box path; a site inside FZ3, a site spanning disjoint FZ2 and FZ3, a constructed overlapping FZ2/FZ3 case where the headline union is less than the sum of the per-zone areas, overlapping same-zone polygons unioned rather than summed, a boundary touch excluded, a no-overlap zero result with exact schema and CRS, null flood sources excluded from the provenance, multi-source provenance retained, the hectare and percentage arithmetic, the result sorting, the exact result schema and CRS, the frozen dataclass, and the type, CRS, row and column guards. `scripts/check_flood_zones_overlap.py` runs the intended app workflow against the real GeoPackage: it reads the national feature count from metadata, reads one feature to pick a deterministic site, then loads only that site's bounding box and runs the overlap.

## Full site screening

`load_screening_datasets()` and `screen_site()` in `screening.py` run all five themes for one candidate site in a single call. This layer adds no new spatial logic; it wires the existing per-theme loaders and analysis functions together.

### Loading the datasets

`load_screening_datasets()` reads the reusable source layers once and returns them in a frozen `ScreeningDatasets` dataclass:

- SSSI (`load_sssi`)
- SSSI IRZ (`load_sssi_irz`)
- Priority Habitats (`load_priority_habitats`)
- Ancient Woodland revised (`load_ancient_woodland_revised`)
- Ancient Woodland legacy (`load_ancient_woodland_legacy`)
- revised Ancient Woodland coverage (`load_revised_coverage`)
- the Flood Zones source path

The first six are held as loaded `GeoDataFrame`s because they are reused between site runs. Flood Zones is different: its production loader is bounding-box based, so `ScreeningDatasets` keeps only the file path and the bounding-box read happens per site.

### screen_site()

`screen_site(site, datasets)`:

- validates the candidate site with `validate_site()`
- runs SSSI overlap
- calculates the nearest SSSI only when there is no SSSI overlap
- checks SSSI IRZ context
- calculates Priority Habitat overlap
- calculates Ancient Woodland overlap using revised/legacy precedence
- loads only the candidate site's Flood Zones bounding box, `load_flood_zones(path, bbox=tuple(site.total_bounds))`
- calculates Flood Zone overlap
- builds the five-row summary

Loader and validation errors are not caught. A broken required dataset fails visibly rather than turning into a false "no constraint" result. Input `GeoDataFrame`s are not mutated.

### ScreeningResult

`screen_site()` returns a frozen `ScreeningResult` holding:

- the validated site
- the SSSI overlap result
- the nearest-SSSI result, or `None` when the site overlaps an SSSI
- the SSSI IRZ context result
- the Priority Habitats result
- the Ancient Woodland result
- the Flood Zones result
- the `summary` DataFrame

The individual result objects are kept as they are, not flattened, so a caller can drill into any of them.

### The summary table

`summary` is a plain pandas DataFrame with one row per theme, in the order SSSI, SSSI Impact Risk Zone, Priority Habitats, Ancient Woodland, Flood Zones. Columns:

- `theme` — the theme name
- `has_result` — whether that theme found something for this site (positive-area SSSI overlap; positive-area IRZ context; priority-habitat overlap; ancient-woodland overlap; mapped FZ2 or FZ3 overlap)
- `result_type` — either `overlap` or `context`, nothing else; only IRZ is `context`
- `feature_count` — that theme's own count
- `affected_area_ha` — hectares of the site affected, from that theme's overall union result
- `affected_pct` — that area as a percentage of the site
- `nearest_distance_m` — nearest SSSI distance in metres, populated only when there was no SSSI overlap

Interpretation notes:

- IRZ `affected_area_ha` and `affected_pct` are null. IRZ is contextual and an overlap area is not a meaningful metric for it.
- A zero rather than a null in an area or percentage column means the metric applies to that theme and the measured value is genuinely zero, for example an ancient-woodland check that ran and found no overlap.
- `feature_count` does not mean the same thing across themes: SSSI features, IRZ intersecting zones, Priority Habitat classes, Ancient Woodland (inventory, category) output rows, Flood Zone rows. It is for compact display, not cross-theme comparison.

### What the orchestration does not calculate

There is no total constraint count, no cross-theme affected area, no cross-theme percentage, no environmental score, no severity weighting, no red/amber/green, no pass/fail. Different themes can overlap spatially and represent different environmental concepts, so their areas are never summed.

### Checking this

`tests/test_screening.py` covers the integration behaviour with synthetic layers: all five themes running, the exact summary schema and row order, a site given in `EPSG:4326` being validated and reprojected once, nearest SSSI being skipped when there is overlap and run when there is not, the IRZ area and percentage staying null, a genuine zero for a theme that ran and found nothing, revised/legacy precedence surviving the orchestration, the Flood Zones loader receiving the validated site's bounding box, inputs not being mutated, and a broken required dataset raising rather than returning a false result.

`scripts/check_full_screening.py` runs the whole thing once against the real local sources. The current run produced overlap, context and nearest-distance results together in one screen. Loading the reusable national layers took about 41.6 s once (dominated by the Priority Habitats GeoPackage); the single `screen_site()` call took about 1.3 s. The datasets are therefore meant to be loaded once and reused across site runs.
