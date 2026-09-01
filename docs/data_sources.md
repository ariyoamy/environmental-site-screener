# Data sources

The national datasets the screening runs against, the exact file each loader
expects, and where it belongs under `data/raw/`. These files are large (more than
10 GB in total) and are not committed to Git.

For the source inspection, fields used, revision information and known
limitations, see [data_audit.md](data_audit.md). For how each dataset is used in
the analysis, see [methodology.md](methodology.md).

## Expected files under `data/raw/`

`environmental_site_screener.app_data.default_data_sources()` resolves these
paths, and the Streamlit app lists any that are missing on start-up.

| Theme | Publisher | Path under `data/raw/` | Format |
| --- | --- | --- | --- |
| SSSI | Natural England | `sssi/Sites_of_Special_Scientific_Interest_England.gpkg` | GeoPackage |
| SSSI Impact Risk Zones | Natural England | `sssi_irz/SSSI_Impact_Risk_Zones_England.gpkg` | GeoPackage |
| Priority Habitats Inventory | Natural England | `priority_habitats/Priority_Habitats_Inventory_England.gpkg` | GeoPackage |
| Ancient Woodland, revised | Natural England | `ancient_woodland/revised/Ancient_Woodland_Revised_England_Completed_Counties.gpkg` | GeoPackage |
| Ancient Woodland, legacy | Natural England | `ancient_woodland/legacy/Ancient_Woodland_England.gpkg` | GeoPackage |
| Flood Map for Planning, Flood Zones | Environment Agency | `flood_zones/Flood_Map_for_Planning_Flood_Zones.gpkg` | GeoPackage, layer `Flood_Zones_2_3_Rivers_and_Sea` |
| Boundary-Line ceremonial counties | Ordnance Survey | `ancient_woodland/coverage/Boundary-line-ceremonial-counties_region.shp` (`.dbf`, `.prj`, `.shx` alongside) | Shapefile |

All seven sources are expected in `EPSG:27700` (British National Grid). The
loaders do not reproject a source dataset. The Boundary-Line file is used both
for the revised Ancient Woodland coverage inference and for the England product
scope check.

## Publishers

- Natural England: SSSI, SSSI Impact Risk Zones, Priority Habitats Inventory,
  Ancient Woodland (revised and legacy). Published through the Natural England
  open data portal on data.gov.uk.
- Environment Agency: Flood Map for Planning, Flood Zones. Published through the
  Environment Agency Digital Services / DEFRA data services platform.
- Ordnance Survey: Boundary-Line, from OS OpenData.

These are open datasets. Search for each dataset by name on the publisher's site
to reach the current download page. Check each publisher's licence terms before
reusing the data. The download pages and licence text are not mirrored in this
repository.

## Revision information

Recorded during the source inspection on 31 August 2026 (see
[data_audit.md](data_audit.md) for the full detail):

| Dataset | Recorded version / date | Notes |
| --- | --- | --- |
| SSSI Impact Risk Zones | User Guidance v5.4, 2 April 2025 | 4 invalid geometries in the source, left unchanged |
| Priority Habitats Inventory | publication version `Sep_25` | 1 invalid geometry in the source, left unchanged |
| Ancient Woodland, revised | inspected 31 August 2026 | 69 invalid geometries (ring self-intersections), left unchanged |
| Ancient Woodland, legacy | inspected 31 August 2026 | no invalid geometries |
| Flood Map for Planning | Product Description 30 June 2026 | about 813,627 features, GeoPackage about 5.9 GB |
| Boundary-Line ceremonial counties | inspected 31 August 2026 | 91 rows covering Great Britain; one invalid geometry (`Shetland`), outside England and not used |

Revision dates move when the publishers refresh a dataset. Re-check them against
the download page when refreshing the local copy, and review the revised Ancient
Woodland coverage allow-list at the same time (see
[methodology.md](methodology.md)).
