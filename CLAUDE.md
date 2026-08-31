# Claude Code Project Instructions

## Project purpose

This repository contains a portfolio-scale geospatial environmental screening tool for proposed development and infrastructure sites in England.

The core question is:

"What mapped environmental constraints or sensitivities should a user know about before taking a candidate site further?"

The intended user is a GIS or environmental analyst carrying out preliminary desktop screening.

This is an initial screening tool. It is not a statutory assessment or a substitute for professional environmental judgement.

Before making substantial changes, read:

- `README.md`
- `docs/project_scope.md`
- `docs/data_sources.md`
- `docs/methodology.md`

Treat those files as the project's source of truth unless the user explicitly instructs otherwise.

## Current MVP

The MVP analyses one candidate site polygon at a time.

The five user-facing environmental themes are:

1. Sites of Special Scientific Interest (SSSI)
2. SSSI Impact Risk Zones (IRZ)
3. Priority Habitats
4. Ancient Woodland
5. Flood Zones

Ancient Woodland is internally sourced from two datasets:

- Ancient Woodland - Revised (England) - Completed Counties
- Ancient Woodland (England), used only where revised coverage does not supersede it

Local Nature Reserves are not part of the MVP.

Flood Zones plus Climate Change are not part of the initial MVP.

## Analytical principles

Prefer transparent spatial operations over opaque scoring or unnecessary machine learning.

Typical operations include:

- geometry validation
- CRS validation and reprojection
- polygon intersection
- intersection area
- percentage overlap
- nearest-feature distance
- extraction of relevant source attributes

Do not introduce an overall environmental suitability score unless the user explicitly approves a defensible methodology.

Do not silently convert different environmental constraints into arbitrary numeric weights.

## Coordinate reference systems

EPSG:27700 (OSGB36 / British National Grid) is the default analytical CRS.

All distance and area calculations must be performed in an appropriate projected CRS, normally EPSG:27700 for this England-wide MVP.

Do not calculate areas or distances directly in EPSG:4326.

For web-map display, geometries may later be transformed to EPSG:4326.

Area outputs should normally be expressed in hectares:

area_ha = area_m2 / 10000

Distance outputs should normally be expressed in metres, or kilometres where clearly more readable.

## Dataset-specific interpretation rules

### SSSI

Suitable for:

- intersection
- intersection area
- percentage site overlap
- nearest distance when no overlap
- reporting site name/reference where available

Do not infer that proximity or overlap automatically makes development impermissible.

### SSSI Impact Risk Zones

An IRZ intersection is not automatically an adverse environmental verdict.

The relevance of an IRZ depends on the type and scale of proposed development.

The current public spatial layer may primarily provide an advice URL.

Do not invent development-category attributes that are not present in the source data.

Where available, preserve and expose the official IRZ advice link.

### Priority Habitats Inventory

Do not treat every polygon in the dataset as automatically being a priority habitat.

Use the actual habitat classification fields, particularly `MainHabs`, and preserve useful provenance fields where available.

When calculating overall affected area across multiple intersecting polygons, avoid double counting overlapping geometry.

### Ancient Woodland

Where revised Ancient Woodland coverage exists, the revised dataset takes precedence.

Do not naively union revised and legacy Ancient Woodland datasets across the same coverage because this may duplicate or conflict with features.

The legacy Ancient Woodland dataset is the fallback outside revised coverage.

### Flood Zones

The MVP uses Environment Agency Flood Map for Planning - Flood Zones.

Do not describe this as comprehensive flood-risk mapping.

Flood Zone 1 is not represented as polygons in the source dataset.

Do not fabricate a Flood Zone 1 layer unless a deliberate and documented derivation method is approved.

Preserve relevant attributes such as flood zone, flood source and origin where available.

## Claims the application must not make

Do not state or imply that the tool determines:

- whether planning permission will be granted
- whether development is legally permitted
- whether a site passes or fails Biodiversity Net Gain requirements
- whether development will cause ecological harm
- whether a site is environmentally "good" or "bad"
- whether a site is legally safe to develop

Use language such as:

- preliminary screening
- mapped environmental constraint
- mapped sensitivity
- may warrant further investigation
- source dataset indicates
- initial desktop assessment

## Code organisation

Application and analytical code belongs under:

`src/environmental_site_screener/`

Tests belong under:

`tests/`

Large source datasets belong under:

`data/raw/`

and should not be committed to Git.

Processed/cache data should also remain outside Git unless a small reproducible fixture is intentionally included.

Do not place important analytical logic only inside notebooks.

Prefer small, testable Python functions.

## Coding behaviour

When given a bounded implementation task:

1. inspect the relevant existing files first
2. make the smallest change required
3. do not rewrite unrelated working code
4. do not rename files or functions unnecessarily
5. do not add dependencies without explaining why
6. do not change methodological assumptions silently
7. flag uncertainty instead of guessing
8. keep functions readable enough for the project owner to explain in an interview

When a task specifies which files may be edited, do not edit other files unless necessary. If another file genuinely must change, explain why first.

## Testing expectations

New analytical functionality should normally include tests.

Important cases include:

- valid polygon
- empty geometry
- invalid geometry
- missing CRS
- reprojection
- complete overlap
- partial overlap
- no overlap
- multiple intersecting polygons
- overlapping source polygons where double counting could occur
- nearest-feature distance
- empty constraint layer

Where practical, create small synthetic geometries with known expected answers rather than relying entirely on large external datasets.

Do not weaken or remove tests simply to make a failing implementation pass.

## Validation expectations

Passing software tests is not enough.

Spatial results should also be checked for analytical plausibility.

For important calculations:

- verify units
- verify CRS
- inspect geometries
- compare at least some results to manually understandable test cases

If an output seems surprising, investigate it rather than assuming it is meaningful.

## AI-assisted development

Claude Code is an implementation and review assistant, not the methodological decision-maker.

The project owner remains responsible for:

- problem definition
- dataset choice
- methodological decisions
- validation
- interpretation
- limitations
- final conclusions

Do not make claims about productivity gains or development speed unless measured.

## Git behaviour

Do not commit or push changes unless the user explicitly asks you to.

Do not rewrite Git history.

Do not delete or overwrite working changes without explicit approval.

The user will normally review diffs, run tests, and commit changes manually.

## Scope control

This is intended to be a polished portfolio MVP, not enterprise software.

Do not introduce unnecessary:

- authentication
- cloud infrastructure
- databases
- machine learning
- LLM features
- complex frontend frameworks
- microservices
- containerisation

unless a concrete project requirement later justifies them.

Prefer a small, understandable and well-tested implementation.
