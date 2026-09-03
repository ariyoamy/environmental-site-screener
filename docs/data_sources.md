# Data sources

This file records the national datasets the screening runs against: what each
one is, the file the app expects, the source fields I use, and the limitations I
know about. I inspected these sources on 31 August 2026. Where a dataset has a
recorded version or product date I note it below, but publishers refresh these
datasets and move those dates, so re-check them when you download a fresh copy.

For how each dataset is actually used in the analysis, see
[methodology.md](methodology.md).

## Source files

These files are large (more than 10 GB in total) and are not committed to Git.
`environmental_site_screener.app_data.default_data_sources()` resolves the paths,
and the Streamlit app lists any that are missing on start-up. All seven sources
are expected in `EPSG:27700` (British National Grid); the loaders do not
reproject a source dataset.

| Theme | Publisher | Dataset | Path under `data/raw/` | Format |
| --- | --- | --- | --- | --- |
| SSSI | Natural England | Sites of Special Scientific Interest (England) | `sssi/Sites_of_Special_Scientific_Interest_England.gpkg` | GeoPackage |
| SSSI Impact Risk Zones | Natural England | SSSI Impact Risk Zones (England) | `sssi_irz/SSSI_Impact_Risk_Zones_England.gpkg` | GeoPackage |
| Priority Habitats | Natural England | Priority Habitats Inventory (England) | `priority_habitats/Priority_Habitats_Inventory_England.gpkg` | GeoPackage |
| Ancient Woodland, revised | Natural England | Ancient Woodland - Revised (England) - Completed Counties | `ancient_woodland/revised/Ancient_Woodland_Revised_England_Completed_Counties.gpkg` | GeoPackage |
| Ancient Woodland, legacy | Natural England | Ancient Woodland (England) | `ancient_woodland/legacy/Ancient_Woodland_England.gpkg` | GeoPackage |
| Flood Zones | Environment Agency | Flood Map for Planning - Flood Zones | `flood_zones/Flood_Map_for_Planning_Flood_Zones.gpkg` | GeoPackage, layer `Flood_Zones_2_3_Rivers_and_Sea` |
| Boundary-Line ceremonial counties | Ordnance Survey | Boundary-Line (OS OpenData) | `ancient_woodland/coverage/Boundary-line-ceremonial-counties_region.shp` (`.dbf`, `.prj`, `.shx` alongside) | Shapefile |

Natural England and the Environment Agency publish through data.gov.uk and the
DEFRA data services platform; Ordnance Survey Boundary-Line is from OS OpenData.
These are open datasets. Search for each one by name on the publisher's site to
reach the current download page, and check the licence terms before reusing the
data. The Boundary-Line file is used twice: for the revised Ancient Woodland
coverage inference and for the England product-scope check.

## Source notes

### SSSI

- Natural England, Sites of Special Scientific Interest (England).
- I keep `ref_code`, `name` and `measure`. `ref_code` is the unique site
  reference and `name` is the SSSI name; `measure` is a citation text field and
  can be empty.
- The download does not carry condition or designation-detail attributes, so the
  app reports overlap and nearest distance only, not site condition.

### SSSI Impact Risk Zones

- Natural England, SSSI Impact Risk Zones (England). 208,538 features, all
  `MultiPolygon`. 4 invalid geometries in the inspected source.
- Supplied User Guidance version 5.4, issue date 2 April 2025. The guidance
  describes the IRZs as a tool for a rapid initial assessment of whether a
  development proposal might affect a terrestrial SSSI, and says the outcome
  depends on the location and the type of development.
- The only published attribute I use is `irzurl`, the hyperlink to Natural
  England's online IRZ advice. I keep it verbatim and parse the 13-digit
  `irzcode` from it as an opaque string.
- The guidance documents 13 development categories, but the download does not
  publish a machine-readable mapping from the `irzcode` digits to those
  categories, so the app does not attempt to interpret them. The download also
  contains no SSSI names or references.
- This is why an IRZ intersection is treated as context, not as an adverse
  result.

### Priority Habitats

- Natural England, Priority Habitats Inventory (England). Publication version
  recorded in the source as `Sep_25`. 799,637 features, all `MultiPolygon`. 1
  invalid geometry in the inspected source. `uid` is unique and non-null.
- The inventory is not a single "priority habitat" layer. I work from an
  explicit set of 27 priority habitat codes and 4 context (non-priority) codes:
  Fragmented heath (`FHEAT`), Grass moorland (`GMOOR`), Good quality
  semi-improved grassland (`GQSIG`) and No main habitat (`NMHAB`).
- I use `mainhabs` and `habcodes` (comma-separated, can list more than one
  habitat per polygon, paired positionally), `is_priority` (derived), `featdesc`
  and `primsource` for provenance, and `uid`. 10,821 rows carry more than one
  main habitat. Seven real polygons mix `GQSIG` with the priority habitat
  `TORCH` (Traditional orchard), so a polygon can feed both the priority metric
  and context.
- `addhabs` (additional habitats present) is kept as provenance only. It never
  contributes to the headline priority-habitat metric.
- Source field `areaha` is not read; the app measures clipped geometry itself.

### Ancient Woodland

There are two Natural England inventories and one coverage source.

- **Revised:** Ancient Woodland - Revised (England) - Completed Counties. 45,406
  features, all `MultiPolygon`. 69 invalid geometries (ring self-intersections).
  Categories `ASNW`, `ARW`, `AWPP`, `IAWPP`. Smaller parcels than the legacy
  inventory (a 0.25 ha threshold nationally) and much fuller wood-pasture
  representation.
- **Legacy:** Ancient Woodland (England). 53,638 features, all `MultiPolygon`.
  No invalid geometries. Categories `ASNW`, `PAWS`, `AWP`.
- Neither inventory has a county or completed-county field. The revised
  `themeid` prefixes are a mix of county and records-centre codes and many rows
  have none, so they cannot reconstruct coverage. From each source I keep the
  woodland name, the source category code and name, a theme id and an `inventory`
  tag. Source `area` and `perimeter` are not used.
- Revised `ARW` and legacy `PAWS` are the same idea under different codes, as are
  revised `AWPP` and legacy `AWP`. I keep the source code and name exactly as
  delivered and never map them onto each other. Where the supporting PDFs
  disagree with the delivered revised GeoPackage on the replanted-woodland
  abbreviation, I treat the delivered data (`ARW`) as the authority.
- Natural England's rule is that where a county has been redone in the revised
  inventory the revised data takes precedence there, and the legacy inventory is
  the fallback everywhere else. The two must not simply be unioned: sampling
  found roughly three-quarters of the revised-county woodland area is also
  covered by legacy polygons.
- **Coverage:** there is no published completed-county list or coverage layer, so
  the app decides where "revised" applies from a fixed allow-list of 29
  ceremonial counties, filtered out of the OS Boundary-Line layer. This is a
  dated project inference, not Natural England metadata, and it must be reviewed
  whenever the revised source is refreshed. Somerset is excluded because only the
  north and east of the ceremonial county is revised; counties with only a
  handful of revised polygons (for example North Yorkshire, Cornwall,
  Herefordshire) are treated as cross-border spill and excluded.
- **Boundary-Line:** 91 rows covering Great Britain, county name field `NAME`.
  One invalid geometry (`Shetland`), which is Scottish and never used. All
  English ceremonial counties are present.

### Flood Zones

- Environment Agency, Flood Map for Planning - Flood Zones. Supporting Product
  Description published 30 June 2026. 813,627 features; the GeoPackage is about
  5.9 GB. One layer, `Flood_Zones_2_3_Rivers_and_Sea`. No null, empty or invalid
  geometry found in the inspected source.
- `flood_zone` is `FZ2` (540,282 features) or `FZ3` (273,345). I keep
  `flood_zone`, `flood_source` and `origin`. `flood_source` holds `river`, `sea`,
  `river and sea` or undefined-type values, with about 4,808 nulls; a single
  polygon can carry a combined source such as `river and sea`, which I keep
  whole. `origin` records provenance such as `modelled`, `recorded` and
  `direct rainfall model`. No stable source identifier is retained.
- This is river and sea flood risk for planning, not comprehensive flood-risk
  mapping. Surface water, groundwater, drainage and infrastructure-failure
  flooding are not represented, not all rivers are mapped, and the zones ignore
  the benefit of flood defences. Some locations still carry the previous
  November 2023 data pending improvements.
- Flood Zone 1 (less than 0.1% annual probability) is not supplied as geometry.
  The app never manufactures a Flood Zone 1 layer, row or flag. Flood Zone 3b
  (functional floodplain) is not separately represented and sits inside
  Flood Zone 3.
- In the inspected data `FZ2` and `FZ3` behave as mutually exclusive bands
  rather than `FZ3` nested inside `FZ2`.
- Climate-change flood data is a separate dataset and is not used in this MVP.

## Data handling

- The analytical CRS is `EPSG:27700` (OSGB36 / British National Grid). All area
  and distance work is done in this projected CRS.
- The raw datasets are excluded from Git. They are large, licensed by their
  publishers and change over time.
- Source geometry is not silently repaired. Where an authoritative source
  contains invalid polygons, the loader emits one warning with the count and
  leaves the geometry unchanged, so the problem stays visible. Invalid geometry
  in a user-supplied boundary is a different case and may be repaired with a
  warning.
- Publishers revise these datasets. Feature counts, versions and invalid-geometry
  counts above are from the 31 August 2026 inspection and will drift.

## Refreshing the data

Download a fresh copy from the publisher, replace the file at the same path under
`data/raw/`, keeping the filename the loader expects, and re-run the
`scripts/check_*` real-data checks. When you refresh the revised Ancient Woodland
source, review the 29-county coverage allow-list in the code at the same time
(see [methodology.md](methodology.md)). Note any new recorded version or product
date and any change in the invalid-geometry warnings.
