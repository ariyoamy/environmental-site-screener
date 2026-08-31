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
