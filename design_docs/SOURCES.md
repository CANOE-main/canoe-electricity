# canoe-electricity — External Data Sources

For human reference only. Not consumed by any tooling.

| Source | What it provides | Accessed by | Cache file(s) |
|---|---|---|---|
| **CODERS API** (`https://api.sesit.ca/`) | Existing generators fleet (`generators`) | `coders_api.get_data('generators')` | `data_cache/generators.csv` |
| | Existing storage fleet (`storage`) | `coders_api.get_data('storage')` | `data_cache/storage.csv` |
| | Capital-cost evolution by tech (`generation_cost_evolution`) | `coders_api.get_data('generation_cost_evolution')` | `data_cache/generation_cost_evolution.csv` |
| | Generic technoeconomic params by tech (`generation_generic`) | `coders_api.get_data('generation_generic')` | `data_cache/generation_generic.csv` |
| | Provincial reserve margins, line losses (`CA_system_parameters`) | `coders_api.get_data('CA_system_parameters')` | `data_cache/CA_system_parameters.csv` |
| | Interprovincial interface transfer capacities (`interface_capacities`) | `coders_api.get_data('interface_capacities')` | `data_cache/interface_capacities.csv` |
| | Hourly provincial electricity demand (`provincial_demand`) | `coders_api.get_data('provincial_demand', year=..., province=...)` | `data_cache/provincial_demand_year=..._province=....csv` |
| | Forecasted annual electricity demand (`forecasted_annual_demand`) | `coders_api.get_data('forecasted_annual_demand')` | `data_cache/forecasted_annual_demand.csv` |
| | Hourly interprovincial transfers (`interprovincial_transfers`) | `coders_api.get_data('interprovincial_transfers', ...)` | `data_cache/interprovincial_transfers....csv` |
| | Hourly international transfers (`international_transfers`) | `coders_api.get_data('international_transfers', ...)` | `data_cache/international_transfers....csv` |
| **NREL ATB** (Annual Technology Baseline) | Capital costs, O&M, heat rates by tech/scenario — summary CSV | `utils.atb_data()` (TODO: migrate to `atb_api` in Step 4) | `data_cache/<atb_summary>.csv` |
| | Technology-specific variables (heat rates, emissions, ramp rates) — from master workbook | `atb_api.load_tsv(sheet, row, ...)` | `data_cache/<master_workbook>.xlsb` + `data_cache/atb_technology_specific_variables_<sheet>.csv` |

## API key

CODERS requires an API key, stored in the file path configured under `params.yaml → coders_api_key_file`
(relative to `input_files/`). If the file is absent, `coders_api.get_data()` will print a helpful error
and fall back to any locally cached CSV.

## Notes

- Both CODERS and ATB data are cached locally on first download. Re-download is controlled by
  `params.yaml → force_download`.
- CODERS and ATB are the only two external network sources. All other input data (technology
  parameters, commodity definitions, unit conversions) are local CSV files under `input_files/`.
- `utils.atb_data()` reads the ATB summary CSV and is shared with `new_wind_solar.py`. It will
  be migrated to `atb_api.py` as part of Step 4 (Pydantic SQL / generators refactor).
