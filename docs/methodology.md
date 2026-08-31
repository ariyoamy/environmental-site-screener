# Methodology

This file explains the methods I have implemented so far.

At the moment, the code covers two parts of the screening workflow:

- checking that a candidate site boundary is usable
- calculating overlap between a candidate site and SSSI polygons

I am keeping this file close to the code. Planned ideas can go in the README, project scope or issues. This document is for methods that are already implemented and tested.

Spatial calculations use `EPSG:27700` / OSGB36 British National Grid unless stated otherwise. This keeps area and distance work in metre-based units.

## Candidate-site validation

### What this step does

`validate_site()` prepares a candidate site boundary for the rest of the tool.

It checks that the input is one polygonal site, makes sure the CRS is known, repairs invalid geometry where that can be done safely, and returns a copy in `EPSG:27700`.

It does not run any environmental checks. It just makes sure the site geometry is in a usable state before later functions try to intersect it with environmental datasets.

### Accepted input

The function expects one `geopandas.GeoDataFrame` with exactly one row.

The geometry must be either:

- `Polygon`
- `MultiPolygon`

The function rejects:

- inputs that are not a `GeoDataFrame`
- empty `GeoDataFrame` objects
- inputs with more than one row
- missing or empty geometry
- non-polygon geometry, such as `Point` or `LineString`

A `MultiPolygon` is accepted as one site. The function does not split it into separate parts.

### CRS handling

The input must have a defined CRS.

The function does not guess one. If the CRS is missing, it raises an error.

I chose this because guessing a CRS can make the rest of the analysis look fine while quietly producing wrong areas and distances. For example, assuming `EPSG:4326` when the coordinates are actually in another CRS would give bad reprojection results with no obvious warning.

The project CRS is:

```text
EPSG:27700 — OSGB36 / British National Grid