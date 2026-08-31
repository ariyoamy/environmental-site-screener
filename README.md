# Environmental Site Screening Tool

Early-stage geospatial project for screening proposed development or infrastructure sites in England against selected environmental spatial datasets.

The idea is simple: provide a candidate site boundary, run a set of transparent GIS checks, and return a clear summary of mapped environmental constraints or sensitivities that may need further investigation.

I am building this as a practical portfolio project using Python and open spatial data. It is not intended to replace ecological survey, environmental assessment, planning advice or statutory Biodiversity Net Gain calculations.

## Current status

The first SSSI screening pieces are now implemented.

So far, the code can:

- validate a candidate site boundary;
- load and validate the Natural England SSSI source data;
- calculate positive-area overlap between a candidate site and SSSI polygons;
- return overlap area in square metres and hectares;
- calculate the percentage of the candidate site affected by SSSI overlap;
- avoid double-counting overlapping SSSI geometry when calculating the total affected area;
- ignore boundary-touch cases where there is no real area of overlap.

The SSSI overlap code has been tested with synthetic geometries and against the real Natural England dataset. The current test suite has 55 passing tests.

Nearest-SSSI distance is the next SSSI calculation to add. It is not implemented yet.

The other environmental themes and the interactive application are still to be built.

## What the tool will check

The MVP will focus on a small number of environmental layers rather than trying to include everything at once.

Initial candidate datasets:

- Sites of Special Scientific Interest (SSSI)
- SSSI Impact Risk Zones
- Priority Habitats Inventory
- Ancient Woodland
- Flood-related constraint data

The final dataset list may change as I review data access, licensing, attributes and suitability for automated spatial analysis.

## Planned workflow

The first version will analyse one site polygon at a time.

Planned steps:

1. Load or upload a candidate site boundary.
2. Check it against selected environmental datasets.
3. Calculate overlaps, overlap areas and nearest-feature distances where relevant.
4. Display the results on an interactive map.
5. Show the source dataset behind each result.

The aim is to make each result traceable, rather than giving the site a single unexplained score.

## Example outputs

The tool is intended to return results such as:

- Whether the site intersects mapped priority habitat.
- How much of the site overlaps a protected or sensitive layer.
- The distance to the nearest mapped SSSI if there is no direct overlap.
- Whether the site falls within an SSSI Impact Risk Zone.
- Which dataset and spatial operation produced each result.

## What this project is not

This tool will not decide whether a site is environmentally suitable or whether development should go ahead.

It will not determine:

- Whether planning permission will be granted.
- Whether development is legally permitted.
- Whether a site passes Biodiversity Net Gain requirements.
- Whether ecological harm will occur.
- Whether a site is "good" or "bad" overall.

The purpose is early screening: identifying mapped issues that may need a closer look.

