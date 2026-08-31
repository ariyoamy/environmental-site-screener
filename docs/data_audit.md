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
