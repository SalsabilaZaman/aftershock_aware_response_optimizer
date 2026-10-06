# Full pipeline inputs

The pipeline source is included, but the full Kahramanmaraş analysis is not an out-of-the-box run from this public repository. Raw and author-provided inputs are intentionally excluded.

The extraction configuration expects source material such as:

- USGS catalog/PAGER records and OpenStreetMap site/hospital/road data.
- SRTM elevation tiles and a Vs30 grid.
- Copernicus EMSR648 damage-product shapefiles.
- Curated hospital capacity data and prepared casualty/subdistrict inputs.

Expected paths and extraction settings are listed in `pipelines/extraction/config.yaml`; schemas and derivation notes belong with the source-data documentation. Some products are large, require external download/API access, or have distinct redistribution terms. Acquire them from their providers, check usage terms, and keep credentials in environment variables such as `OPENTOPO_API_KEY`, never in committed configuration.

The included synthetic example exercises only the deterministic facility-location solver. It does not validate the complete extraction, hazard, or stochastic pipeline against the real study inputs.
