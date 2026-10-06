# Data provenance for the published dashboard

The dashboard snapshot is a copy of the pipeline's exported `dashboard_data/` bundle, frozen from the reference run recorded in `examples/reference_results/scenario_manifest.json`. It contains derived tables and model outputs, not the original source workbooks or raster files.

The study combines these source families:

- USGS earthquake event/catalog data for the 2023 Kahramanmaraş sequence.
- OpenStreetMap candidate facilities and road/access information. OpenStreetMap data is © OpenStreetMap contributors and is available under the Open Database License (ODbL); provide attribution and review ODbL obligations when redistributing substantial derived databases.
- Copernicus Emergency Management Service EMSR648 damage mapping.
- SRTM elevation and USGS Vs30 ground-condition data.
- Turkish Ministry of Health hospital information, curated with source and confidence notes in the research workflow.
- PAGER/HAZUS casualty projections and aggregate demographic inputs.

The result bundle includes facility locations, site hazard values, modeled demand totals, and aggregate facility allocations. It does not contain individual patient records. Its provenance does not automatically grant redistribution rights for every upstream source; maintain the attribution above and verify provider terms before expanding the published bundle.

The separate `examples/model_inputs/` fixture is synthetic: its demand points, facility IDs, capacities, and distances are illustrative and do not represent real communities or facilities.
