# Environmental Site Screener

Before taking a proposed development or infrastructure site further, an analyst usually has to make the same first set of GIS checks. Does the site overlap a protected site, priority habitat or ancient woodland? Is any of it within a mapped flood zone? Each check means working with a different national dataset, clipping or comparing it to the site, and recording what was found.

I built this small Python application to bring those first checks into one repeatable workflow. You give it a candidate site boundary in England and it answers a single question:

> What mapped environmental constraints or sensitivities should I know about before taking this site further?

It screens one candidate site at a time, against five environmental themes, and shows the map, the numbers and the source behind every result. It is a preliminary desktop screen. It is not a planning decision, an ecological survey or a Biodiversity Net Gain calculation.

This is a portfolio project. I wanted to build something close to the kind of GIS and environmental analysis work I would like to do professionally, using real national data and decisions I can defend.

![Environmental Site Screener showing a screened candidate site: candidate panel on the left, an interactive result map in the centre, and five environmental result cards on the right.](screenshots/app-overview.png)

## What it does

You give the app a candidate site in one of three ways:

- pick one of five built-in demo sites,
- upload a GeoJSON file containing a single `Polygon` or `MultiPolygon` feature,
- define a rectangle, either by drawing and resizing it on a small map or by typing west, east, south and north coordinates.

The app then:

1. validates the geometry (one polygonal feature, a known CRS, positive area), repairing an invalid boundary with a visible warning if it can,
2. reprojects it to British National Grid (`EPSG:27700`) if it arrived in another CRS, for example WGS84 lat/long,
3. checks the site is fully inside England, because the datasets stop at the border and a site outside England would screen as falsely clear,
4. runs the five environmental checks when you press **Screen site**,
5. shows the results on an interactive map with per-theme layer toggles, a set of result cards, a compact "mapped overlap by theme" bar summary, and a detail tab per theme with the source table and how to read it.

A drawn or typed rectangle goes through the same validation, England check and screening as an uploaded file.

## Environmental checks

| Theme | What the app checks | Main output |
| --- | --- | --- |
| Sites of Special Scientific Interest | Positive-area intersection between the site and SSSI polygons. Nearest SSSI edge distance when nothing overlaps. | Overlap area and percentage of the site, intersecting SSSI names, or the distance and name of the nearest SSSI. |
| SSSI Impact Risk Zones | Whether the site falls inside one or more mapped IRZ advice areas. | Count of intersecting zones and the Natural England advice link for each. No percentage or severity, because an IRZ intersection is context, not an adverse result. |
| Priority Habitats | Positive-area overlap with mapped priority habitat, classified per habitat code rather than per polygon. | Affected area and percentage, the habitat classes involved. The four non-priority context classes are reported separately and excluded from the figure. |
| Ancient Woodland | Overlap with the revised inventory where the project-derived revised county coverage applies, and the legacy inventory everywhere else. | Affected area and percentage, and the woodland categories, kept per inventory. See [docs/methodology.md](docs/methodology.md) for the precedence method. |
| Flood Zones | Overlap with Environment Agency Flood Zone 2 and Flood Zone 3 (rivers and sea). | Affected area and percentage per zone, plus the flood source and data origin. |

Flood Zone 1 is not supplied as polygons in the source dataset, so the app does not create one. When there is no FZ2 or FZ3 overlap it says so, it does not say the site is free of flood risk.

## How the analysis works

- All area and distance work is done in `EPSG:27700`, a metre-based projected CRS. Nothing is measured in degrees.
- Overlaps use the real geometry intersection and keep only positive-area results. A site that just touches a boundary line or a corner is not counted as an overlap.
- Areas are measured from the clipped geometry, not read from any area field in the source data.
- Where overlapping source polygons could double-count the same ground, the clipped pieces are unioned before the headline affected area is calculated. Two SSSIs that each cover 60% of a site do not produce 120%.
- Exactly one validated candidate site is analysed per run.
- The Flood Zones source is about 5.9 GB, so the app reads only the polygons in the site's bounding box through the GeoPackage spatial index rather than loading the national file.
- The other national datasets are loaded once and cached in the app, so screening a second site is fast.

For the dataset-specific details and edge cases, see [docs/methodology.md](docs/methodology.md).

## A few decisions that mattered

**No overall score.** I keep the themes separate rather than combining them into one environmental number. SSSI, habitat, woodland and flood zones mean different things, they can overlap the same piece of ground, and there is no obvious defensible way to weight them against each other. Showing the individual evidence is more useful and more honest than a single figure.

**IRZ stays contextual.** Being inside an SSSI Impact Risk Zone is not treated as an adverse result. The zone is a prompt to check Natural England's advice for the specific type and scale of development. The app reports the intersection and the advice link and nothing more.

**Ancient Woodland precedence.** The revised and legacy inventories cannot simply be merged. Inside a revised county the two overlap heavily, so a union would double count. Natural England has no published completed-county list, so the project works from a documented, dated allow-list of 29 ceremonial counties and splits the site along that boundary: revised inventory inside, legacy outside.

**Authoritative source geometry is not silently repaired.** If a user uploads an invalid boundary, the app repairs it with `shapely.make_valid()` and shows a warning so the person can check the result. If an invalid geometry is found in a national source dataset, the loader leaves it untouched and reports the count, because a problem in authoritative data is something to investigate, not something to quietly patch.

## Data

The screening runs against public national datasets. They are large and are not included in this repository.

| Theme | Publisher | Dataset |
| --- | --- | --- |
| SSSI | Natural England | Sites of Special Scientific Interest (England) |
| SSSI Impact Risk Zones | Natural England | SSSI Impact Risk Zones (England) |
| Priority Habitats | Natural England | Priority Habitats Inventory (England) |
| Ancient Woodland, revised | Natural England | Ancient Woodland Revised (England), Completed Counties |
| Ancient Woodland, legacy | Natural England | Ancient Woodland (England) |
| Flood Zones | Environment Agency | Flood Map for Planning, Flood Zones 2 and 3 |
| Revised AW coverage boundary | Ordnance Survey | Boundary-Line ceremonial counties |

These are open datasets published by Natural England, the Environment Agency and Ordnance Survey. Check each publisher's current licence terms before reusing the data.

[docs/data_sources.md](docs/data_sources.md) lists the exact file each loader expects and where it belongs under `data/raw/`. [docs/data_audit.md](docs/data_audit.md) records the source inspection, the fields used, revision information and known limitations. The raw national datasets are intentionally excluded from Git, see [data/README.md](data/README.md).

## Demonstration sites

The five demo sites are fictional screening boundaries, not real development proposals. They are chosen to show different result profiles rather than five similar rectangles.

- **Mixed constraints, Suffolk.** Priority habitat, ancient woodland and a flood zone, with the nearest SSSI reported because there is no SSSI overlap.
- **Urban mixed constraints, Cambridge.** Priority habitat and flood zone overlap on the edge of the city, no ancient woodland.
- **Multi-part site, Newbury.** One candidate site made of two separate parcels, to show that a `MultiPolygon` is handled as a single site.
- **Low constraint, Lincolnshire Wolds.** Arable farmland where most themes return no mapped overlap.
- **Large-area screening, London.** A deliberately large area, roughly 22,600 ha, far bigger than a normal development site. Every theme returns something and it takes about 12 seconds to screen, so it shows how the interface behaves across a broad extent. There is no artificial site size cap, but the app does show a "this may take longer" note.

## Testing

The suite is 485 tests and currently passes. The analytical tests lean on small synthetic geometries with hand-calculable answers rather than only checking against the large national files.

They cover, among other things:

- candidate site validation: Polygon and MultiPolygon, reprojection from WGS84, missing CRS, empty and multi-row inputs, non-polygon geometry, a self-intersecting polygon repaired with a warning,
- each loader: schema, required fields, CRS, and refusing to reproject or silently repair authoritative data,
- overlap behaviour: complete, partial and no overlap, a boundary touch that should not count, several disjoint features, and overlapping features where a naive sum would exceed the site area,
- nearest-feature distance with a known gap and known ties,
- the England product scope check: England sites eligible, Wales and outside Great Britain rejected, a boundary that crosses the border rejected,
- the app helpers and state: GeoJSON input, malformed, multiple and non-polygon uploads, layer visibility, the demo profiles, the mapped overlap bars,
- a real-data scenario script (`scripts/check_app_scenarios.py`) that screens the demos and fixtures end to end.

Run them with:

```bash
python -m pytest -q
```

The analytical tests do not need the national datasets. The real-data scenario script and a few application integration tests do.

## What this tool does not tell you

The aim is not to answer "can this site be developed". The aim is to answer "what mapped issues should someone look at more carefully".

It does not decide:

- whether planning permission will be granted,
- whether development is legally permitted,
- whether ecological harm will occur,
- whether a site passes or fails Biodiversity Net Gain,
- whether a site is environmentally good or bad,
- whether a site is safe to develop.

A few things worth keeping in mind about the data:

- Mapped datasets can have omissions, and the publishers revise them over time.
- Flood Zones cover river and sea flooding only. They ignore the benefit of flood defences and do not represent surface water, groundwater or drainage flooding.
- An IRZ intersection is context. Whether Natural England advice applies depends on the proposed development.
- A desktop screen is not an ecological survey.

There is no overall environmental score because the themes are not comparable on one scale and can overlap the same ground. Presenting the separate evidence is more defensible than inventing a weighting.

## Running it locally

```bash
git clone https://github.com/ariyoamy/environmental-site-screener.git
cd environmental-site-screener
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

To run the test suite:

```bash
python -m pytest -q
```

The analytical tests run without any external data.

To run the full application you also need the national source datasets, which are not in this repository. They total more than 10 GB. Download each one from its publisher and place it under `data/raw/` using the exact names in [docs/data_sources.md](docs/data_sources.md), then:

```bash
streamlit run app.py
```

If the raw data is missing, the app starts and tells you which files it expected and where. [data/README.md](data/README.md) has the directory layout.

## Repository structure

```text
environmental-site-screener/
├── app.py                          Streamlit application
├── src/environmental_site_screener/
│   ├── site.py                     candidate site validation and reprojection
│   ├── england.py                  England product scope boundary and eligibility
│   ├── sssi.py, overlap.py, distance.py
│   ├── sssi_irz.py
│   ├── priority_habitats.py
│   ├── ancient_woodland.py         revised / legacy loaders and precedence
│   ├── flood_zones.py              bounding box source read
│   ├── screening.py                runs all five themes for one site
│   ├── app_data.py                 demo sites, GeoJSON and rectangle input, messages
│   ├── app_map.py                  PyDeck result map and layers
│   └── app_format.py               result cards, overlap bars, theme detail
├── tests/                          pytest suite and small GeoJSON fixtures
├── scripts/                        one-off checks against the real datasets
├── docs/                           project scope, methodology, data audit, data sources
├── data/                           data/raw/ is where the national datasets go (git-ignored)
└── screenshots/                    images used in this README
```

## Development note

I used AI-assisted coding tools while building this, mainly for drafting, debugging, refactoring and generating test cases. I treated generated code as something to review rather than something to trust. The source interpretation, the methodology decisions, the checks against the real data and the final review were mine to verify against the underlying datasets and documentation.

## What I would add next

This is a finished MVP. Things I would look at next, roughly in order of usefulness:

- small UX and accessibility tweaks from real use,
- Flood Zones plus climate change as separate future flood context,
- one or two more carefully chosen environmental layers, if they add something the current five do not,
- a way to deliver or host the data so the app is runnable without a manual multi-gigabyte download,
- a simple exported screening summary, if it proves useful rather than just being a feature.

Multi-site comparison, screening several candidate boundaries and comparing their constraints side by side, is a natural next direction. It is a future extension, not part of the current MVP scope.
