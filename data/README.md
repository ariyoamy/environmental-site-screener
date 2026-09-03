# data/

## `data/raw/`

The national source datasets go here. They are large (more than 10 GB in total)
and are not committed to Git. `data/raw/`, `data/processed/` and `data/cache/`
are all in `.gitignore`.

The analytical test suite (`python -m pytest -q`) does not need any of this data.
It uses small synthetic geometries. You only need the raw datasets to run the
full Streamlit application and the `scripts/check_*` real-data checks.

### Expected layout

```text
data/raw/
├── sssi/
│   └── Sites_of_Special_Scientific_Interest_England.gpkg
├── sssi_irz/
│   └── SSSI_Impact_Risk_Zones_England.gpkg
├── priority_habitats/
│   └── Priority_Habitats_Inventory_England.gpkg
├── ancient_woodland/
│   ├── revised/
│   │   └── Ancient_Woodland_Revised_England_Completed_Counties.gpkg
│   ├── legacy/
│   │   └── Ancient_Woodland_England.gpkg
│   └── coverage/
│       └── Boundary-line-ceremonial-counties_region.shp   (+ .dbf, .prj, .shx)
└── flood_zones/
    └── Flood_Map_for_Planning_Flood_Zones.gpkg
```

The file names above are the ones the loaders expect. If a file is missing, the
Streamlit app starts and lists exactly which paths it could not find.

See [../docs/data_sources.md](../docs/data_sources.md) for the publishers,
formats, source fields, revision information and known limitations, and
[../docs/methodology.md](../docs/methodology.md) for how each dataset is used.

## `data/processed/` and `data/cache/`

Not used at the moment. Reserved for any processed or cached derivatives, which
would also stay out of Git.
