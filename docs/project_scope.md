``` markdown
# Project Overview — Environmental Site Screening Tool

## 1. Project Idea

This project is a **geospatial environmental screening tool for proposed development and infrastructure sites in England**.

A user provides the boundary of a candidate site, and the application automatically checks that location against a selection of authoritative environmental spatial datasets.

The aim is to turn multiple GIS datasets and spatial checks into a clear answer to one simple question:

> **What environmental constraints or sensitivities should I know about before taking this site further?**

The tool should help someone identify potential issues early, before committing significant time or money to more detailed investigation.

It is an **initial screening tool**, not a substitute for professional environmental assessment, ecological survey, planning advice or statutory calculations.

---

## 2. Intended User

The main user is a:

**GIS or environmental analyst carrying out an initial desktop assessment of a proposed development or infrastructure site.**

They may be working within an environmental consultancy, infrastructure company, renewable-energy developer, property/development organisation, utility, transport organisation or planning/environment team.

Their goal is not necessarily to make the final development decision themselves. Instead, the tool helps them quickly identify and communicate issues that may require further investigation.

For example:

> “This candidate site overlaps mapped priority habitat and lies close to ancient woodland. It also falls within an SSSI Impact Risk Zone. These issues should be investigated further.”

---

## 3. Core Workflow

The application should follow a simple workflow:

**Candidate site boundary**  
↓  
**Automated spatial checks against environmental datasets**  
↓  
**Environmental constraints and sensitivities identified**  
↓  
**Interactive map + quantitative results + supporting information**  
↓  
**Clear indication of what may require further investigation**

The user should be able to understand both **what was found** and **where the result came from**.

---

## 4. MVP Scope

### Geography

The intended product scope is **England**.

The underlying environmental datasets are generally national, meaning the application should ideally accept a candidate polygon anywhere in England.

Demonstration sites can be limited to a smaller number of example locations if required for performance or presentation.

### Input

The MVP analyses **one candidate site polygon at a time**.

Possible input methods:

- a supplied demonstration site; and/or
- an uploaded GeoJSON site boundary.

### Environmental Layers

The initial version should focus on a small number of useful, defensible datasets rather than including layers simply because they are available.

The current core candidates are:

1. Sites of Special Scientific Interest (SSSI)
2. SSSI Impact Risk Zones
3. Priority Habitats Inventory
4. Ancient Woodland
5. Flood-related constraint data

A Local Nature Reserve layer may be added if it contributes meaningfully without unnecessarily expanding the MVP.

---

## 5. Analysis Performed

The application is based mainly on transparent GIS operations rather than machine learning or an arbitrary environmental scoring system.

For each relevant environmental layer, the tool may calculate:

### Intersection

Does the proposed development site overlap the mapped environmental feature?

### Intersection Area

How much of the site overlaps the feature, expressed in hectares?

### Percentage Overlap

What proportion of the candidate site is affected?

### Proximity

If there is no direct overlap, how far away is the nearest mapped feature?

### Context

Where appropriate, what additional spatial context applies to the site, such as whether it lies within an SSSI Impact Risk Zone?

These calculations should remain understandable and traceable so that every result produced by the application can be explained.

---

## 6. Output

The main output should combine an **interactive map** with a concise environmental screening summary.

A result might communicate information such as:

**Priority Habitat — overlap detected**

3.8 ha of the candidate site intersects mapped Priority Habitat, representing 8.9% of the submitted site boundary.

**SSSI — no direct overlap**

The nearest mapped SSSI boundary is approximately 740 metres from the candidate site.

**SSSI Impact Risk Zone — identified**

The submitted site intersects a mapped Natural England SSSI Impact Risk Zone. The underlying information should be reviewed to determine its relevance to the proposed development.

Users should also be able to view information such as:

- dataset/source;
- type of analysis performed;
- overlap area;
- percentage overlap;
- nearest-feature distance;
- dataset revision or provenance where useful;
- important dataset limitations.

The application should make the evidence behind a result visible rather than presenting unexplained conclusions.

---

## 7. What the Project Is NOT

Maintaining this boundary is important.

The application should **not** claim to determine:

- whether planning permission will be granted;
- whether development is legally permitted;
- whether a site is environmentally “good” or “bad”;
- whether a project passes or fails Biodiversity Net Gain requirements;
- whether development will cause ecological harm;
- whether a site is legally safe to develop.

It should also avoid creating an arbitrary overall score such as:

**“Environmental suitability: 72/100.”**

Unless a defensible methodology exists for weighting completely different environmental constraints, presenting the individual evidence is more credible than combining everything into a single number.

The tool supports investigation and decision-making; it does not make the decision itself.

---

## 8. Design Principles

Throughout development, the project should stay guided by a few principles:

**Keep the question simple.**

The product should always answer: *What environmental issues should I know about at this proposed site?*

**Make the analysis transparent.**

Users should be able to understand how each result was calculated.

**Use authoritative spatial data.**

Each dataset should have a documented source, licence, revision and known limitations.

**Do not overstate what the data means.**

A mapped constraint may indicate something requiring investigation; it does not automatically mean development is prohibited.

**Prefer useful evidence over unnecessary complexity.**

A smaller number of well-implemented datasets and spatial analyses is better than a large collection of poorly explained layers.

**Keep the MVP focused.**

Additional functionality should only be added when it strengthens the central site-screening use case.

---

## 9. Possible Future Direction

The first version should screen **one site well**.

A natural extension would be the ability to compare several candidate locations side-by-side, for example:

- habitat overlap;
- flood overlap;
- distance to SSSI;
- distance to ancient woodland;
- other selected constraints.

This could develop into a wider tool for screening a portfolio of candidate development sites and identifying which locations warrant further investigation.

However, **multi-site comparison is an extension, not the core MVP**.

---

## Project North Star

If the project starts becoming complicated, return to this:

> **Build a clear, credible geospatial tool that takes a proposed development site in England, checks it against authoritative environmental spatial data, and shows the user which mapped environmental issues may need further investigation.**

Everything in the GitHub repository should ultimately support that objective.
```
