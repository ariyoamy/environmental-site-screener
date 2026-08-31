# Environmental Dataset Audit

**Audit date:** 31 August 2026

This document records the environmental datasets selected for the MVP and the main implementation decisions arising from the Phase 0 data review.

## MVP screening themes

The application will initially screen five environmental themes using six source datasets:

1. Sites of Special Scientific Interest (SSSI)
2. SSSI Impact Risk Zones
3. Priority Habitats
4. Ancient Woodland
   - Ancient Woodland - Revised (England) - Completed Counties
   - Ancient Woodland (England), as fallback outside revised coverage
5. Flood Zones
   - Environment Agency Flood Map for Planning - Flood Zones

## Deferred datasets

- Local Nature Reserves: excluded from the MVP because the national dataset is described as indicative rather than definitive.
- Flood Zones plus Climate Change: deferred as a separate possible enhancement rather than mixing present-day and future flood extents in the initial result.

## Analytical CRS

The default analytical coordinate reference system is:

`EPSG:27700 — OSGB36 / British National Grid`

Area and distance calculations will be performed in this projected CRS.

## Key implementation rules

- SSSI IRZ intersection is contextual and should not be presented as an automatic adverse-risk finding.
- Priority Habitats must be interpreted using habitat classifications rather than treating every mapped polygon as a priority habitat.
- Revised Ancient Woodland data takes precedence where available; the legacy dataset acts as fallback elsewhere.
- Flood Zones should not be described as comprehensive flood-risk mapping.
- Spatial overlap calculations must avoid double-counting overlapping source polygons.

Detailed source URLs, licence terms, fields, revision dates and limitations will be maintained below as implementation progresses.

## SSSI Impact Risk Zones — source findings

The following come from inspecting the local source and reading the supplied documentation. They are facts about the data, not interpretation.

- Publisher: Natural England.
- Dataset: SSSI Impact Risk Zones (England).
- Analytical CRS: `EPSG:27700`.
- Local source inspected on 31 August 2026.
- 208,538 features, all `MultiPolygon`.
- Published source attribute: `irzurl`. The supplied attribute metadata describes it as the SSSI Impact Risk Zone advice hyperlink.
- Supplied User Guidance: version 5.4, issue date 2 April 2025.
- The guidance describes the IRZs as a tool for a rapid initial assessment of the potential risks to terrestrial SSSIs from development proposals.
- The guidance says the outcome for a location depends on that location and on the type of development.
- The guidance documents 13 development categories, but the downloaded dataset does not publish a machine-readable mapping from the 13 `irzcode` digits to those categories.
- The external download does not contain SSSI names or references.
- The current source contains 4 invalid geometries.

Implementation decisions from these findings:

- An IRZ intersection is treated as contextual only.
- `irzurl` is preserved verbatim; the 13-digit `irzcode` is kept as an opaque string and its digits are not interpreted.
- No risk score, consultation verdict or suitability judgement is derived from an IRZ intersection.
- Invalid source geometry is not repaired; the loader emits one warning and leaves it unchanged.

## Priority Habitats — source findings

These come from inspecting the local source and reading the supplied metadata. They are facts about the data, not interpretation.

- Publisher: Natural England.
- Dataset: Priority Habitats Inventory (England).
- Analytical CRS: `EPSG:27700`.
- Local source inspected on 31 August 2026.
- Publication version recorded in the source: `Sep_25`.
- 799,637 features, all `MultiPolygon`.
- The current source contains one invalid geometry.
- `uid` is unique and non-null.
- Key fields and their meaning:
  - `mainhabs`: list of main habitats present in the polygon
  - `habcodes`: habitat codes, corresponding to `mainhabs`
  - `featdesc`: additional habitat feature / sub-class description
  - `featcodes`: codes corresponding to the feature descriptions
  - `otherclass`: other survey classification
  - `addhabs`: additional habitats present
  - `primsource`: primary data source
  - `areaha`: source polygon area
  - `version`: publication version
  - `uid`: unique polygon identifier
- 83 distinct `mainhabs` combinations.
- 10,821 rows carry more than one main habitat, with up to three main habitats in a single polygon.
- Four context / non-priority classes:
  - Fragmented heath (`FHEAT`)
  - Grass moorland (`GMOOR`)
  - Good quality semi-improved grassland (`GQSIG`)
  - No main habitat (`NMHAB`)
- Seven real polygons mix `GQSIG` with the priority habitat `TORCH` (Traditional orchard).
- `addhabs` is additional habitat information; it is not promoted into the main priority metric.
- The current release is effectively non-overlapping geometrically, but the implementation still uses union-based de-duplication and does not rely on that staying true.
- The inventory is built from multiple contributing surveys and inventories; `primsource` is retained for provenance.

Implementation decisions from these findings:

- The four context classes are excluded from the priority affected-area metric and surfaced separately, with no area or percentage.
- The loader works from an explicit list of 27 priority codes and 4 context codes; an unknown `habcodes` token raises rather than being guessed.
- `mainhabs` and `habcodes` are split and paired positionally; mismatched token counts raise.
- Only the retained attributes plus geometry are read from the GeoPackage; `areaha` is not used for overlap calculations.
- Invalid source geometry is not repaired; the loader emits one warning and leaves it unchanged.

## Ancient Woodland — source findings

These come from inspecting the local sources and reading the supplied metadata. They are facts about the data, not interpretation.

### Revised inventory

- Publisher: Natural England.
- Dataset: Ancient Woodland - Revised (England) - Completed Counties.
- Analytical CRS: `EPSG:27700`.
- Local source inspected on 31 August 2026.
- 45,406 features, all `MultiPolygon`.
- Categories observed (`status` / `themename`): `ASNW` (Ancient & Semi-Natural Woodland), `ARW` (Ancient Replanted Woodland), `AWPP` (Ancient Wood Pasture), `IAWPP` (Infilled Ancient Wood Pasture).
- 69 invalid geometries (ring self-intersections).
- Attribute columns: `name`, `theme`, `themename`, `status`, `x_coord`, `y_coord`, `themeid`, `area`, `perimeter`.
- No county or local-authority field.
- No separate coverage layer (the GeoPackage has a single layer).
- No reliable completed-county field: `themeid` carries an informal prefix (for example `ESS-` for Essex) but the prefixes are a mix of county and records-centre codes and many rows have none, so it cannot be used to reconstruct coverage.
- `themeid` is not unique (a multi-part wood shares one ID); `name` is blank for many rows.
- `area` is in hectares and `perimeter` in kilometres, but the readme warns digital and previously recorded areas can differ.

### Legacy inventory

- Publisher: Natural England.
- Dataset: Ancient Woodland (England).
- Analytical CRS: `EPSG:27700`.
- Local source inspected on 31 August 2026.
- 53,638 features, all `MultiPolygon`.
- Categories observed (`status` / `themname`): `ASNW` (Ancient & Semi-Natural Woodland), `PAWS` (Plantations on Ancient Woodland Sites), `AWP` (Ancient Wood Pasture).
- No invalid geometries in the inspected source.
- Attribute columns: `name`, `theme`, `themname`, `themid`, `status`, `perimeter`, `area`, `x_coord`, `y_coord`.
- No county or local-authority field; `themid` is a plain number and is not unique.
- `area` is in hectares, `perimeter` in metres.

### Source interpretation

- The supplied metadata states that where a county has been updated and is included in the revised dataset, the revised data takes precedence; where a county has not been updated, the legacy inventory remains the primary reference.
- The two datasets must not simply be unioned: sampling found roughly three-quarters of the revised-county woodland area is also covered by legacy polygons, so a union would double-count.
- The revised inventory includes smaller woodland parcels (a 0.25 ha threshold nationally, against 2 ha outside the older south-east pilot) and much fuller wood-pasture representation (`AWPP` plus `IAWPP`, about 5,300 features) than the legacy inventory (`AWP`, 64 features).
- Revised `ARW` and legacy `PAWS` are related concepts, as are revised `AWPP` and legacy `AWP`, but the source codes and names are preserved separately and are never mapped onto each other.
- The supporting PDFs disagree with the delivered revised GeoPackage on the replanted-woodland abbreviation; the delivered data (`ARW`) is treated as the authority.

### Coverage source

- Dataset: OS Boundary-Line ceremonial counties (`Boundary-line-ceremonial-counties_region.shp`).
- CRS: `EPSG:27700`.
- 91 rows covering Great Britain (English, Welsh and Scottish ceremonial counties); county name field is `NAME`.
- One invalid geometry, `Shetland`, which is outside England and not used.
- All expected English ceremonial counties are present, plus `City and County of the City of London` as a separate polygon.
- Diagnostic: assigning every revised and legacy polygon to a ceremonial county by an interior representative point matched all 45,406 revised and all 53,638 legacy points to exactly one county, with no unmatched or multiply matched points.
- The current project allow-list is 29 ceremonial counties judged to be whole-county revised replacements.
- Somerset was found to be only partially revised (the west of the ceremonial county is still legacy-only) and is excluded.
- Counties with only a handful of revised polygons — for example North Yorkshire, Cornwall and Herefordshire — were treated as cross-border spill, not county completion, and are excluded.
- This coverage set is a dated project inference, not an official Natural England coverage product.

Implementation decisions from these findings:

- `load_revised_coverage()` filters the OS Boundary-Line layer to a fixed 29-county allow-list held in the code; the allow-list must be reviewed when the revised source is refreshed.
- The candidate site is split into a revised part (inside coverage) and a fallback part (outside coverage); the revised inventory is used only for the first and the legacy inventory only for the second, which applies the precedence rule without double-counting.
- Source-specific category codes are preserved; `ARW`/`PAWS` and `AWPP`/`AWP` are not normalised across inventories.
- Both inventories must already be in `EPSG:27700` and are not reprojected; the `area` and `perimeter` fields are not used for overlap calculations.
- Invalid revised geometry is not repaired; the loader emits one warning with the count (69 on the current source) and leaves it unchanged. Invalid coverage geometry among the selected counties raises; invalid geometry outside them is ignored.
- If the site needs one inventory side but that source is empty, the analysis raises rather than reporting a false zero.
