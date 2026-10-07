# Data provenance for the published dashboard

The dashboard reference bundle combines the exported site, hazard, hospital, demand, and deterministic data with completed Paper LP and SAA profile exports. `examples/reference_results/scenario_manifest.json` records the bundle generation time and file inventory. It contains derived tables and model outputs, not the original source workbooks or raster files.

The study combines these source families:

- USGS earthquake event/catalog data for the 2023 Kahramanmaraş sequence.
- OpenStreetMap candidate facilities and road/access information. OpenStreetMap data is © OpenStreetMap contributors and is available under the Open Database License (ODbL); provide attribution and review ODbL obligations when redistributing substantial derived databases.
- Copernicus Emergency Management Service EMSR648 damage mapping.
- SRTM elevation and USGS Vs30 ground-condition data.
- Turkish Ministry of Health hospital information, curated with source and confidence notes in the research workflow.
- PAGER/HAZUS casualty projections and aggregate demographic inputs.

The result bundle includes facility locations, site hazard values, modeled demand totals, and aggregate facility allocations. It does not contain individual patient records. Its provenance does not automatically grant redistribution rights for every upstream source; maintain the attribution above and verify provider terms before expanding the published bundle.

The Pages exporter adds presentation fields to the browser JSON without changing the source CSVs: named OSM sites retain their names, unnamed sites receive a readable facility-type label anchored to the nearest named demand point, and the source site ID is retained in parentheses for traceability. Curated hospital names remain the display source for hospitals; facility types are humanized for display. These generated labels are not new OSM name tags or independently verified place names.

The separate `examples/model_inputs/` fixture is synthetic: its demand points, facility IDs, capacities, and distances are illustrative and do not represent real communities or facilities.


Current profile coverage: Paper LP has all-candidates and TOPSIS top-120 exports. SAA has a completed all-candidates export, including one detailed policy and validation draw; the TOPSIS-screened SAA checkpoint is incomplete and is not presented as a completed result. See [current pipeline](CURRENT_PIPELINE.md) for run metadata and availability.
