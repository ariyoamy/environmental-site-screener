# Methodology

These are my notes on how the screening works, written so another technical
person can follow the analytical choices and challenge them. They cover what is
implemented and tested. Where a detail is really about a function guard or a
test case I have left it in the code and tests rather than repeating it here.

For the datasets themselves, their fields and their limitations, see
[data_sources.md](data_sources.md).

## Common spatial rules

The same handful of rules apply to every theme.

- **CRS.** All area and distance work is done in `EPSG:27700` (OSGB36 / British
  National Grid), a metre-based projected system. I do not calculate areas or
  distances in latitude/longitude, because degrees are not ground units and the
  distortion changes with latitude, so the numbers would be wrong with no
  obvious warning. The candidate site is reprojected once during validation.
  Every source dataset is expected already in `EPSG:27700` and is not
  reprojected.
- **Positive-area overlap only.** An intersection counts only if the clipped
  geometry has area greater than zero. A site that shares only an edge or a
  corner with a feature is not overlapping it, because a boundary touch is a
  coincidence of mapping, not a spatial constraint on the site.
- **Union before the headline area.** When several source polygons overlap the
  site, I combine the clipped pieces into one geometry and measure that, rather
  than adding per-feature areas. Two polygons that each cover 60% of a site
  cannot produce a 120% result. Per-feature and per-class tables are still
  reported, but the headline affected area and percentage come from the union.
- **Areas from geometry, not attributes.** Affected area is measured from the
  clipped geometry. I do not trust an `area` or `areaha` field in the source
  data. Hectares are square metres divided by 10,000, percentages are against
  the validated site area, and values are returned unrounded.
- **Source geometry is not silently repaired.** If an authoritative source
  contains invalid polygons, the loader emits one warning with the count and
  leaves them unchanged, so a data problem stays visible. User-supplied geometry
  is the one exception (see below).

## Candidate site validation and England scope

`validate_site()` accepts one `Polygon` or `MultiPolygon` in a
`GeoDataFrame` with exactly one row and a known CRS. It repairs invalid user
geometry with `shapely.make_valid()` where that produces a non-empty polygonal
result, emitting a `UserWarning` so the user inspects it, then reprojects the
site to `EPSG:27700` and checks it has positive area. Missing CRS, empty
geometry, non-polygon input and multiple features are rejected. A `MultiPolygon`
is kept as a single site and is not split. The function does no environmental
checks and does not look at where the site is.

I let user geometry be repaired but not source geometry, because a user boundary
is an input I am helping someone prepare, while an authoritative dataset is
something I should report faithfully.

The England check is separate, in `england.py`, run after validation and before
screening. `load_england_boundary()` builds one England polygon from the OS
Boundary-Line ceremonial counties layer using an explicit allow-list of 48
English ceremonial-county names, so England is not inferred from the extent of
the environmental data. `classify_site_england_eligibility()` returns `eligible`
(fully inside, allowing up to 1.0 m² outside as a vertex-precision tolerance,
not a buffer), `crosses` or `outside`. Only an `eligible` site is screened. The
site is never clipped to England and a partly-English site is never screened on
its own, because the five datasets stop at the border and the English part of a
cross-border site would screen as falsely clear.

## SSSI

`load_sssi()` reads the Natural England SSSI GeoPackage and keeps `ref_code`,
`name` and `measure`. Two functions run against it.

`calculate_sssi_overlap()` finds SSSI polygons that intersect the site, clips
each to the site, and measures the clipped area per SSSI and overall (unioned).
It reports one row per overlapping SSSI with `ref_code`, `name`, `measure` and
the intersection area, sorted largest first, plus the overall affected area and
percentage. `ref_code` is unique in the source, so rows are not merged. If
nothing overlaps, or the layer is empty, it still returns a well-formed zero
result.

`calculate_nearest_sssi()` is used only when there is no positive-area SSSI
overlap. It measures edge-to-edge distance with `.distance()` from each SSSI
polygon to the site polygon, not centroid to centroid, and returns the nearest
SSSI and the distance in metres. If several SSSIs are exactly equidistant, all
are returned, sorted by `ref_code`. A zero distance from this function can mean a
touch or an overlap, so the overlap function is what decides whether there is
real overlap. An empty SSSI layer is a valid "no overlap" result for the overlap
function but an error for the nearest function, because nearest distance is
undefined with nothing to measure to.

## SSSI Impact Risk Zones

`load_sssi_irz()` reads the Natural England IRZ GeoPackage. The only published
attribute I use is `irzurl`, the link to Natural England's online IRZ advice,
kept verbatim. I also parse `irz_code`, the 13-digit `irzcode` from the URL, and
keep it as an opaque string. I do not interpret its digits, because the download
does not publish a machine-readable mapping from those digits to Natural
England's development categories.

`calculate_sssi_irz_context()` uses the layer's spatial index to find candidate
polygons, then keeps those with positive-area intersection with the site. It
reports whether the site has any IRZ context, the intersecting zones with their
original geometries and advice URLs, and the distinct advice URLs. It does not
calculate overlap area, percentage or nearest distance.

The important interpretation decision: `has_irz_context = True` means only that
part of the site falls inside one or more mapped IRZ advice areas. It is not a
severity score and not a finding that development will harm an SSSI or that
consultation is required. The relevant advice depends on the type and scale of
the proposal and has to be read from the Natural England URL. That is why I
report IRZ as context, separate from the overlap themes. At the moment the IRZ
polygons behave as an effectively non-overlapping coverage, but the code does not
rely on that and just returns every zone the site intersects with positive area.

## Priority Habitats

`load_priority_habitats()` reads the Natural England Priority Habitats Inventory.
The inventory is not a single "priority habitat" layer, so I work from an
explicit set of 27 priority habitat codes and 4 context (non-priority) codes:
`FHEAT`, `GMOOR`, `GQSIG` and `NMHAB`. `mainhabs` (names) and `habcodes` (codes)
are comma-separated, can list more than one habitat per polygon, and are split
and paired positionally. `is_priority` is true when at least one code on the row
is a priority code. `addhabs` is kept as provenance and never enters the metric.

`calculate_priority_habitat_overlap()` uses the spatial index to find candidate
polygons, keeps positive-area intersections, and classifies per main-habitat
code rather than per polygon. Each priority code on an intersecting polygon
attributes that polygon's clipped geometry to that priority class, and each
context code adds the polygon to a separate context result. A polygon coded
`GQSIG,TORCH` feeds Traditional orchard into the priority metric and `GQSIG`
into context at the same time.

The overall affected area is the union of every clipped piece belonging to at
least one priority class. Because a multi-habitat polygon is attributed to
several classes, the per-class areas can legitimately sum to more than the
headline. The four context classes are reported separately with no area or
percentage, because they are information rather than a constraint measure.

## Ancient Woodland

There are two Natural England inventories: a **revised** one being rebuilt county
by county, and the older **legacy** one covering the rest of the country.
Natural England's rule is that where a county has been redone, the revised data
takes precedence there and the legacy data is the fallback elsewhere. The two
must not simply be unioned, because they overlap heavily inside the revised
counties and a union would double-count.

`load_ancient_woodland_revised()` and `load_ancient_woodland_legacy()` return the
same normalised columns, but the source category codes are kept per source and
never mapped onto each other: revised `ASNW`/`ARW`/`AWPP`/`IAWPP`, legacy
`ASNW`/`PAWS`/`AWP`. Revised `ARW` and legacy `PAWS` mean much the same thing,
as do revised `AWPP` and legacy `AWP`, but I keep the source code and name so a
result row always shows which inventory it came from.

`load_revised_coverage()` builds the polygon that says where "revised" applies.
Natural England does not publish a completed-county list or a coverage layer, and
the revised GeoPackage has no county field, so this is a **project inference**: a
fixed allow-list of 29 ceremonial counties, held in the code as
`REVISED_COVERAGE_COUNTIES` and filtered out of the OS Boundary-Line layer,
worked out from the current revised snapshot plus a county-by-county diagnostic.
This list must be reviewed whenever the revised source is refreshed. Somerset is
excluded because only its north and east is revised, and counties with only a few
revised polygons are treated as cross-border spill and excluded.

`calculate_ancient_woodland_overlap()` partitions the site by the coverage:

```text
revised_part  = site ∩ revised coverage
fallback_part = site − revised coverage
```

The revised inventory runs only against `revised_part` and the legacy inventory
only against `fallback_part`. The two parts do not overlap, so ground near the
coverage boundary is not counted twice. Per-category rows and the headline area
follow the common union rule. The result also records how much of the site fell
inside and outside revised coverage. If the site has a part on one side but that
inventory is empty, the function raises rather than reporting a false zero,
because a zero there would really mean the source was missing.

## Flood Zones

`load_flood_zones()` reads the Environment Agency Flood Map for Planning Flood
Zones GeoPackage, layer `Flood_Zones_2_3_Rivers_and_Sea`. I keep `flood_zone`
(`FZ2` or `FZ3` only), `flood_source` and `origin`, all preserved verbatim with
nulls allowed. A combined value such as `river and sea` is kept whole, not
split.

The national GeoPackage is about 5.9 GB with 813,627 features, and a site only
needs the flood polygons near it, so the production loader takes a bounding box:
`load_flood_zones(path, bbox=tuple(site.total_bounds))`. It does lightweight
metadata checks, then uses the GeoPackage spatial index to read only features
whose bounding box intersects the site box, which takes the load from a few
minutes to a fraction of a second. A valid box with nothing in it returns an
empty layer, not an error, because that is a real spatial subset.

`calculate_flood_zone_overlap()` still takes the exact intersection of each
candidate polygon with the site, because a bounding-box subset can include
polygons whose boxes overlap the site but whose geometry does not. It reports
per-zone area and percentage and an overall affected area that is the union of
every clipped `FZ2` and `FZ3` piece, never `FZ2 + FZ3`. In the current data the
two zones do not overlap, but the code unions defensively.

Flood Zone 1 (less than 0.1% annual probability) is not supplied as geometry.
The tool never creates a Flood Zone 1 geometry, row or flag. When a site has no
`FZ2` or `FZ3` overlap, the result says there is no mapped Flood Zone 2 or 3
overlap in this dataset. It must not say the site is free from flood risk.

## Full site screening

`load_screening_datasets()` and `screen_site()` in `screening.py` run all five
themes for one candidate site in one call. This layer adds no new spatial logic,
it wires the per-theme loaders and functions together. The six reusable source
layers are loaded once and reused between site runs. For Flood Zones only the
file path is held, and the bounding-box read happens per site.

`screen_site(site, datasets)` validates the site, runs SSSI overlap, runs the
nearest-SSSI calculation only when there is no SSSI overlap, checks IRZ context,
runs Priority Habitat and Ancient Woodland overlap, loads the site's Flood Zones
bounding box and runs Flood Zone overlap, then builds a five-row summary. Loader
and validation errors are not caught, so a broken required dataset fails visibly
rather than turning into a false "no constraint" result. Input `GeoDataFrame`s
are not mutated.

The `summary` DataFrame has one row per theme with a result flag, a
`result_type` of `overlap` or `context` (only IRZ is `context`), a feature
count, affected area in hectares, affected percentage and the nearest-SSSI
distance where it applies. IRZ area and percentage are null on purpose. A zero
rather than a null means the metric applies and the measured value is genuinely
zero. `feature_count` means something different per theme and is for compact
display, not cross-theme comparison.

There is no total constraint count, no cross-theme area or percentage, and no
overall environmental score, severity weighting or pass/fail. The themes
represent different environmental concepts, can overlap the same ground, and
have no defensible common weighting, so showing the individual evidence is more
useful and more honest than combining it.

## Testing and validation

The suite uses small synthetic geometries with known answers wherever possible,
rather than the national source files. Across the themes it covers valid and
invalid geometry, missing CRS, reprojection, complete / partial / zero overlap,
boundary-only touches, disjoint and overlapping source polygons, the
double-counting case where naive summation would exceed the site area,
nearest-feature distance and ties, empty constraint layers, and the England
scope classification including a cross-border rectangle. Each theme also has a
`scripts/check_*` script that runs the real function against the real source.

Passing tests is not the whole check. For the important calculations I have also
verified units and CRS, inspected geometries, and compared results to cases I
can reason about by hand, for example a 1,000 m square site with a rectangle
overlapping a known fraction of it.

## Current limitations

- The five datasets are England-only, which is why the app blocks sites outside
  England rather than screening them.
- The revised Ancient Woodland coverage allow-list is my inference, not a
  Natural England product, and can go out of date when the revised inventory is
  extended.
- Flood Zones cover river and sea flooding for planning. They ignore the benefit
  of flood defences and do not represent surface water, groundwater or drainage
  flooding, and Flood Zone 1 is not mapped.
- An IRZ intersection is contextual and its relevance depends on the proposed
  development.
- The screening is a preliminary desktop check against mapped data. It is not an
  ecological survey, a flood-risk assessment or a planning judgement, and mapped
  datasets contain omissions and are revised over time.
