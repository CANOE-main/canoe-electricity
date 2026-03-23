# CANOE Electricity Sector — Data Processing Documentation

*Comprehensive documentation of the data pipeline that converts upstream data sources into a Temoa-ready SQLite database for the Canadian Open-source National Optimised Electricity (CANOE) model.*

---

## Table of Contents

- [Overview](#1-overview)

- [Pipeline Architecture](#2-pipeline-architecture)

- [Configuration and Setup](#3-configuration-and-setup)

- [Pre-Processing](#4-pre-processing)

- [Provincial Grid Infrastructure](#5-provincial-grid-infrastructure)

- [Generator Aggregation](#6-generator-aggregation)

- [Capacity Factors](#7-capacity-factors)

- [Capacity Credits and Reserve Margin](#8-capacity-credits-and-reserve-margin)

- [New Wind and Solar Characterisation](#9-new-wind-and-solar-characterisation)

- [Energy Storage](#10-energy-storage)

- [CCS Retrofits](#11-ccs-retrofits)

- [Interfaces and Interties](#12-interfaces-and-interties)

- [Constraints](#13-constraints)

- [Currency Conversion](#14-currency-conversion)

- [Post-Processing](#15-post-processing)

- [Unit Conventions](#16-unit-conventions)

- [Known Assumptions and Limitations](#17-known-assumptions-and-limitations)

---

## 1. Overview

### Purpose

The CANOE electricity sector aggregation tool automatically constructs a Temoa-compatible SQLite database representing the Canadian electricity system. It downloads data from several upstream databases — primarily the Canadian Open-Source Database for Energy Research and Systems-Modelling (CODERS) and the U.S. National Renewable Energy Laboratory (NREL) Annual Technology Baseline (ATB) — processes and harmonises that data, and writes it into a structured SQLite database suitable for long-term capacity expansion modelling.

### What the Tool Produces

- A **Temoa-schema SQLite database** containing all technology, cost, capacity, demand, emissions, and time-series data required to run an electricity sector capacity expansion model.

- Optionally, an **Excel workbook** clone of the database for inspection and review.

- **Diagnostic plots** (PDF) showing demand profiles, capacity factors, capacity credits, and intertie flows for visual verification.

### Scope

The model covers:

- **Regions**: Canadian provinces (configurable; defaults to all ten provinces).

- **Technologies**: Existing and new generators (thermal, nuclear, hydro, wind, solar), energy storage (batteries, pumped hydro), CCS retrofits, and transmission/distribution dummy technologies.

- **Time resolution**: Hourly (8,760 time-slices per year), with representative-day or full-year options.

- **Planning horizon**: Configurable five-year periods (default: 2025–2045).

---

## 2. Pipeline Architecture

The aggregation runs in a fixed order, orchestrated by `electricity_sector.py`:

1. setup.py            → Load configuration, download ATB workbook, build mappings
2. instantiate_database → Create or wipe SQLite database from schema
3. pre_processing.py   → Write time periods, regions, seasons, times-of-day
4. provincial_grids.py → Reserve margin, demand, transmission/distribution
5. generators.py       → Existing & new generators, storage, CCS retrofits
6. interfaces.py       → Interprovincial and international interties
7. post_processing.py  → Imports, commodity table, unused tech cleanup, references

Each step opens its own SQLite connection, writes data, commits, and closes. The database grows incrementally as each module runs.

### Data Flow Diagram

                    ┌──────────────┐
                    │  CODERS API  │
                    └──────┬───────┘
                           │
     ┌─────────────────────┼──────────────────────┐
     │                     │                      │
     ▼                     ▼                      ▼
┌─────────┐        ┌──────────────┐       ┌──────────────┐
│Generators│        │ Provincial   │       │  Interface   │
│ Table    │        │ Demand (hrly)│       │  Flows (hrly)│
└────┬─────┘        └──────┬───────┘       └──────┬───────┘
     │                     │                      │
     ▼                     ▼                      ▼
┌─────────────────────────────────────────────────────────┐
│                 generators.py                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │ Existing │  │   New    │  │   CCS    │              │
│  │Generators│  │Generators│  │Retrofits │              │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘              │
│       │              │              │                    │
│       ▼              ▼              ▼                    │
│  ┌──────────────────────────────────────┐               │
│  │ Generic Data (costs, efficiency,     │               │
│  │ emissions, lifetime, ramp rates)     │               │
│  │ Source: ATB preferred, CODERS backup │               │
│  └──────────────────────────────────────┘               │
└──────────────────────────┬──────────────────────────────┘
                           │
     ┌─────────────────────┼──────────────────────┐
     │                     │                      │
     ▼                     ▼                      ▼
┌──────────┐       ┌──────────────┐       ┌──────────────┐
│ NREL ATB │       │ IESO Public  │       │ Renewables   │
│ CSV + WB │       │ Data (ON)    │       │ Ninja API    │
└────┬─────┘       └──────┬───────┘       └──────┬───────┘
     │                    │                      │
     ▼                    ▼                      ▼
┌─────────────────────────────────────────────────────────┐
│   Capacity Factors, Capacity Credits, Costs             │
│   → Written to Temoa SQLite database tables             │
└─────────────────────────────────────────────────────────┘

---

## 3. Configuration and Setup

### 3.1 Configuration File (`params.yaml`)

The primary configuration file controls all aspects of aggregation. Key parameters include:

| Parameter | Default | Description |
|---|---|---|
| `period_step` | 5 | Years between model periods |
| `model_periods` | [2025, 2030, 2035, 2040, 2045] | Planning horizon periods |
| `base_year` | 2020 | Default year for pulling non-timeseries data |
| `weather_year` | 2018 | Year for all 8,760-hour time-series data |
| `timezone` | EST | Final model timezone; time-series data is realigned to this |
| `final_currency` | CAD | Currency for all cost data in the database |
| `final_currency_year` | 2020 | Currency year for all cost data |
| `global_discount_rate` | 0.03 | For internal LCOE calculations (e.g., VRE bin sorting) |
| `c2a` | 31.536 | Capacity-to-activity ratio (PJ/GW·yr) |
| `existing_capacity_threshold` | 0.001 GW | Minimum capacity to include |

#### Aggregation Switches

Boolean switches enable/disable major pipeline components:

| Switch | Default | Effect |
|---|---|---|
| `force_download` | false | Re-download all data instead of using cache |
| `force_wipe_database` | true | Wipe database before aggregation |
| `full_dataset` | true | Produce complete dataset for later filtering |
| `include_boundary_interfaces` | true | Interties crossing model boundary |
| `include_endogenous_interfaces` | true | Interties between modelled regions |
| `include_existing_capacity` | true | Existing generator fleet |
| `include_reserve_margin` | true | Planning reserve margin and capacity credits |
| `include_storage` | true | Battery and pumped-hydro storage |
| `include_provincial_demand` | true | Electricity demand by province |
| `include_ccs_retrofits` | true | CCS retrofit options for fossil generators |
| `include_tech_fuel_cost` | false | Include fuel costs in technology variable cost |
| `include_new_wind_solar` | true | New wind/solar characterisation (time-consuming) |
| `include_emissions` | false | Direct emissions accounting (vs. upstream) |
| `show_plots` | true | Generate diagnostic plots |

### 3.2 Technology Configuration CSVs

Technologies are defined through several CSV files in `input_files/`:

- **`generator_technologies.csv`**: Maps generator types to CODERS/ATB equivalents, technology flags, I/O commodities, number of new-capacity bins, and whether to use ATB or CODERS data.

- **`storage_technologies.csv`**: Similar configuration for storage technologies (batteries, pumped hydro).

- **`transmission_technologies.csv`**: Defines dummy technologies for transmission (TX→DX), distribution (DX→DEM), demand, and interties.

- **`ccs_retrofit_technologies.csv`**: Defines CCS retrofit options with capture rates and ATB mappings.

- **`import_technologies.csv`**: Defines fuel import dummy technologies.

- **`commodities.csv`**: Maps commodity codes to names, flags (source/physical/demand/emissions), units, and descriptions.

- **`regions.csv`**: Defines provinces, their CODERS equivalents, and whether they are endogenous to the model.

- **`time.csv`**: Maps 8,760 hours to seasons (days) and times-of-day, defining the temporal resolution.

- **`units.csv`**: Conversion factors for all unit transformations (e.g., MW→GW, $/kW→M$/GW).

### 3.3 The `config` Singleton

On import, `setup.py` instantiates a singleton `config` object that:

- Loads `params.yaml` and all CSV configuration files.

- Builds mapping dictionaries:

- `gen_map`: CODERS generator type → CANOE tech code

- `storage_map`: (CODERS storage type, duration) → CANOE tech code

- `region_map`: CODERS province name → CANOE region code

- `existing_map`: CODERS generator type → CANOE existing-tech code

- Downloads the NREL ATB master Excel workbook if not already cached.

- Initialises per-region VRE generation arrays for capacity credit calculations.

### 3.4 Data Caching

All downloaded data is cached locally in `data_cache/`. The caching system:

- Checks if a local file exists before downloading.

- Stores CODERS API responses as CSV files with cleaned endpoint names.

- Tracks download dates in `dates.csv` for reference provenance.

- Converts XML and Excel downloads to CSV or pickle for faster subsequent loads.

- Can be forced to re-download with `force_download: true`.

### 3.5 Bibliography and Data IDs

The tool maintains a **bibliography** of all data sources, assigning each a unique ID (E01, E02, ...) which is stored in the `DataSource` table. Every data row in the database carries a `data_id` formed as `{prefix}{region}{version}` for traceability, and a `data_source` foreign key referencing the bibliography.

---

## 4. Pre-Processing

**Module**: `pre_processing.py`

Pre-processing populates the foundational Temoa tables that other modules depend on:

### 4.1 Time Periods

Future model periods from `params.yaml` are written to `TimePeriod` with flag `"f"` (future). An additional period is appended beyond the last model period (at `last_period + period_step`) to define the model horizon endpoint. Existing-capacity vintage periods are added later by `generators.py` with flag `"e"`.

### 4.2 Regions

All endogenous model regions from `regions.csv` are written to the `Region` table with their descriptions.

### 4.3 Temporal Structure

The `time.csv` file defines the mapping of 8,760 hours to:

- **Seasons** (`SeasonLabel`): Each row defines a season label corresponding to a representative day or day-of-year.

- **Times of day** (`TimeOfDay`): 24 hourly labels (H01–H24) within each season.

These labels form the (season, tod) index used throughout all time-series data in the database.

**Assumption**: The temporal resolution is fixed at the hourly level within a 365-day year. Leap-year data (if present) is truncated to 8,760 hours.

---

## 5. Provincial Grid Infrastructure

**Module**: `provincial_grids.py`

This module handles three main tasks: demand, transmission structure, and planning reserve margin.

### 5.1 Electricity Demand

#### Annual Demand Projections

Annual provincial electricity demand forecasts are pulled from the CODERS `forecasted_annual_demand` API endpoint. For each province and period:

- The demand value for the year corresponding to each period is extracted (using `data_year()`, which returns `period + period_step` for future periods).

- Values are converted from the CODERS native unit (GWh) to the model unit (PJ) via the conversion factor in `units.csv`.

- Written to the `Demand` table.

#### Hourly Demand Profiles (DemandSpecificDistribution)

For each province with available data for the weather year:

- Hourly demand data (8,760 values in MWh) is downloaded from CODERS `provincial_demand` endpoint.

- A **tolerance filter** is applied: any hour with demand below `dsd_tolerance × mean_demand` is set to zero. This is done for computational efficiency in the optimisation solver.

- The profile is **normalised** by dividing each hour by the total annual sum, creating a distribution that sums to 1.0 over the year.

- The normalised profile is written to `DemandSpecificDistribution` for every model period (the shape is assumed constant across periods; only annual demand changes).

**Assumption**: The hourly demand shape from the weather year is used identically for all future periods. Only the total annual demand scales with projections. This means structural changes in demand patterns (e.g., electrification shifting load shapes) are not captured.

**Assumption**: The hourly demand data is stored for use in capacity credit calculations later, linking demand-side data to supply-side reliability metrics.

### 5.2 Transmission and Distribution

Two dummy technologies represent in-province grid infrastructure:

| Technology | Purpose | Key Parameter |
|---|---|---|
| `E_ELC_TX_to_DX` | Transmission to distribution | Efficiency = 1 − line loss (from CODERS `ca_system_parameters`) |
| `E_ELC_DX_to_DEM` | Distribution to demand | Efficiency = 1.0 (dummy) |

- Both are given unlimited capacity (`unlim_cap = 1`) since transmission expansion is not modelled within provinces.

- **Variable costs** for both transmission and distribution are pulled from the U.S. EIA Annual Energy Outlook (AEO) levelised cost tables. Costs are converted from US cents/kWh (USD 2024) to M$/PJ (CAD 2020) using currency conversion factors.

- **Line losses** are province-specific, taken from the CODERS `ca_system_parameters` table (`system_line_losses_percent`).

**Assumption**: In-province transmission is not capacity-constrained. The model can move unlimited electricity within a province at the associated variable cost and line loss.

**Assumption**: Transmission and distribution variable costs are uniform across provinces and taken from U.S. data (EIA AEO), which may not perfectly reflect Canadian cost structures.

### 5.3 Planning Reserve Margin

Provincial planning reserve margins are taken from CODERS `ca_system_parameters` (`reserve_requirements_percent`). These are written directly to the `PlanningReserveMargin` table for each region.

**Assumption**: Reserve margins are province-specific but constant over the entire planning horizon.

---

## 6. Generator Aggregation

**Module**: `generators.py`

This is the most complex module. It aggregates both existing and new generators, filling the bulk of the database tables.

### 6.1 Existing Generators

#### Data Source

The CODERS `generators` API endpoint provides a facility-level database of all Canadian electricity generators, including:
- Facility name and code, province, installed capacity, start year, renewal year
- Generator type (e.g., "Natural Gas - Combined Cycle"), latitude/longitude
- Average annual energy output, capacity factor

#### Processing Steps

**Technology mapping**: Each CODERS generator type is mapped to a CANOE technology code via `config.existing_map` (built from `generator_technologies.csv`'s `coders_existing` column). Generators without a mapping are skipped with a warning.

**Region mapping**: CODERS province names are mapped to CANOE region codes. Only generators in endogenous model regions are included.

**Capacity filtering**: Zero-capacity entries are removed.

**Vintage determination**: The vintage is set to `max(start_year, previous_renewal_year)`. This captures major refurbishments.

**Vintage rounding**: Vintages are rounded to the `period_step` interval and capped at `first_model_period - 1`. This reduces the number of unique vintages in the database:

Example: with period_step=5 and first period 2025, a generator started in 2007 gets vintage 2005, one from 2013 gets vintage 2015, and one from 2023 gets vintage 2024 (capped at 2024).

**No-retirement handling**: Technologies flagged `no_retirement = true` (e.g., hydroelectric) have their vintage overridden to `first_model_period - 1` and lifetime set to 100 years. This ensures they persist throughout the planning horizon.

**Aggregation**: Capacities are summed by (region, tech_code, vintage). Facility descriptions are concatenated.

**Filtering**:

- Generators whose vintage + lifetime does not reach the first model period are excluded.

Generators below the `existing_capacity_threshold` (0.001 GW) after aggregation are excluded.

**Database writing**: For each aggregated (region, tech, vintage) combination:

- `Technology` table entry with flag, sector, description

- `ExistingCapacity` table entry with converted capacity (MW → GW)

`TimePeriod` entries for existing vintages (flag `"e"`)

**Downstream processing**: The aggregated dataframe is passed to capacity factor, capacity credit, constraint, and generic-data modules.

### 6.2 New Generators

For each technology in `generator_technologies.csv` with `include_new = true`:

**Batching**: If `new_cap_batches > 1`, multiple technology variants are created (e.g., `E_WND_ON-NEW-1` through `E_WND_ON-NEW-13`). Each batch represents a bin of new capacity, typically used for variable renewables with different resource qualities.

**Technology entries**: Written to the `Technology` table.

**Region-vintage combinations**: A full cross-product of (model_regions × model_periods) is generated as the set of region-tech-vintage entries.

**Wind and solar** are separated from other generators and passed to `new_wind_solar.py` for specialised provincial resource characterisation. The remaining generators continue through the generic data pipeline.

### 6.3 Generic Techno-Economic Data

Two parallel paths handle generic data depending on whether an ATB equivalent is defined:

#### ATB Path (preferred when `atb_display_name` is set)

Data from the NREL ATB is used for:

- **Efficiency**: Derived from ATB Heat Rate (`1 / (heat_rate × conversion_factor)`). For renewable technologies with dummy inputs (ethos), efficiency is set to 1.

- **Investment cost** (`CostInvest`): ATB's OCC (Overnight Capital Cost) metric, converted from USD/kW to M$/GW and then to the final currency (CAD 2020). Projected values are taken for each vintage year.

- **Fixed O&M** (`CostFixed`): From ATB Fixed O&M, indexed by vintage year. Converted to model units and currency.

- **Variable O&M** (`CostVariable`): From ATB Variable O&M. If `include_tech_fuel_cost` is enabled and the technology has `include_fuel_cost = true`, fuel costs from ATB are added to the variable cost.

- **Ramp rates**: From ATB technology-specific variables (TSV) workbook tables if available, otherwise from CODERS.

- **Emissions** (`EmissionActivity`): From ATB TSV tables for CO2, SO2, NOx, and Hg, scaled by efficiency. CO2 values are duplicated as CO2-equivalent entries.

#### CODERS Path (fallback when no ATB equivalent)

Uses CODERS `generation_generic` and `generation_cost_evolution` tables for:

- Efficiency, investment cost, fixed O&M, variable O&M, ramp rates, and CO2 emissions.

- All values are converted from CODERS native units (typically CAD/kW, % per minute, etc.) via `units.csv` conversion factors.

#### Lifetime

Service lifetime is always taken from the CODERS `generation_generic` table (`service_life` column), regardless of ATB/CODERS path, except for no-retirement technologies which get 100 years.

#### Capacity-to-Activity

A uniform `c2a` ratio of 31.536 PJ/GW·yr is written for every technology, representing the conversion from nameplate capacity to maximum annual energy output.

#### Emissions Accounting

Two emissions modes are available:

- **`include_emissions = false`** (default): Emissions are assumed to be accounted for upstream (in fuel supply sectors). For technologies with CCS, *negative* emissions entries are written to offset the captured portion, calculated as `-emissions × capture_rate / (1 - capture_rate)`.

- **`include_emissions = true`**: Direct emissions are written as positive values.

**Assumption**: When emissions are off, the model assumes a complementary fuel-supply sector handles emissions correctly. CCS technologies then only need to represent the *incremental* capture benefit.

### 6.4 Technology-Specific Variables (TSV)

The ATB master Excel workbook contains detailed technical parameters in technology-specific variable tables. These are parsed by:

- Reading the relevant worksheet (e.g., "Natural Gas_FE", "Nuclear") using row/column ranges from `atb_master_tables.csv`.

- Concatenating multi-row headers into single-row headers.

- Translating column names using the `tsv_headers` mapping in `params.yaml`.

- Caching the parsed table locally as a CSV for faster subsequent loads.

---

## 7. Capacity Factors

**Module**: `capacity_factors.py` (dispatcher), with implementations in `provincial_data/`

Capacity factors are critical for representing the output variability of generators. The approach varies by technology type and data availability.

### 7.1 Existing VRE (Wind and Solar) — Ontario

**Module**: `provincial_data/on/existing_vre_capacity_factors.py`

For Ontario, real operational data is available from the IESO:

- **Hourly generation by fuel** is downloaded from IESO's `GenOutputbyFuelHourly` XML endpoint for the weather year.

- The XML data is parsed to extract hourly MWh generation for WIND and SOLAR fuel types.

- **Average annual capacity factors** for each technology are computed as capacity-weighted averages from CODERS facility data (facilities ≥20 MW, matching IESO's reporting threshold).

- **Hourly capacity factors** are computed by normalising the hourly generation profile to the average annual capacity factor: `cf(h) = hourly(h) / mean(hourly) × cf_annual`.

- Values are clipped to [0, 1] and values below `cf_tolerance` (0.01) are set to zero.

- Written to `CapacityFactorTech` for all valid (region, period, season, tod) combinations.

**Assumption**: Ontario's aggregate VRE generation profile from IESO is representative of the true hourly resource availability of its existing fleet.

### 7.2 Existing VRE — Other Provinces

**Module**: `provincial_data/default/existing_vre_capacity_factors.py`

For provinces without real operational data, capacity factors are *synthesised* using the Renewables Ninja API:

- For each existing VRE facility in CODERS, its latitude and longitude are sent to the Renewables Ninja API to obtain simulated hourly generation for the weather year.

- Results are based on MERRA-2 reanalysis weather data.

- Facility-specific hourly profiles are aggregated using capacity-weighted averaging.

- The total annual energy is adjusted to match the CODERS-reported `unit_average_annual_energy`.

- Aggregate capacity factors are computed as `cf(h) = energy_adjusted_gen(h) / total_capacity`.

**Assumption**: The Renewables Ninja API provides representative profiles using the MERRA-2 weather dataset, a standard reference turbine (Vestas V112 3000 for onshore wind at 110m, Vestas V164 9500 for offshore at 150m), and a 45° tilt for solar PV.

**Limitation**: API rate limits (50 requests/hour) mean that initial data collection for all facilities can take several hours. Results are cached locally.

### 7.3 Existing Hydroelectric — Ontario

**Module**: `provincial_data/on/existing_hydro_capacity_factors.py`

Ontario hydroelectric capacity factors use IESO's `GenOutputCapabilityMonth` data:

- For data before 2019: A single Excel workbook per year provides hourly output and available capacity by generator.

- For data from 2020 onward: Monthly CSV files provide the same data.

- Generators are classified as **daily storage** (`hydro_daily`) or **run-of-river** (`hydro_run`) via a manually curated mapping file (`hydro_types.csv`).

- Hourly capacity factors are computed as `output_MW / capability_MW` for each type.

- **Run-of-river** gets hourly `CapacityFactorTech` entries.

- **Daily storage** gets daily-averaged `LimitSeasonalCapacityFactor` entries (one per season/day).

**Assumption**: Ontario has no monthly-storage hydroelectric capacity in the IESO dataset. Monthly hydro is handled separately.

### 7.4 Existing Hydroelectric — Other Provinces

**Module**: `provincial_data/default/existing_hydro_capacity_factors.py`

For other provinces, hydroelectric capacity factors are synthesised from Statistics Canada monthly generation data:

- StatCan table 25-10-0015-01 provides monthly hydraulic turbine generation by province in MWh.

- Monthly totals are spread uniformly across days within each month.

- The total provincial hydro generation is apportioned among hydro types (run-of-river, daily storage, monthly storage) based on each type's `unit_average_annual_energy` from CODERS.

- Hourly capacity factors are computed from the resulting daily generation divided by aggregated capacity.

**Run-of-river** hydro is assumed to have constant output within each month (flat hourly profile per month). **Daily and monthly storage** hydro are given seasonal capacity factor limits (`LimitSeasonalCapacityFactor`) rather than hourly factors, allowing the optimiser to dispatch them within those bounds.

**Assumption**: Monthly hydro generation data can be evenly spread over the days of that month. The breakdown between hydro types is based on average annual energy proportions from CODERS.

**Limitation**: This is a coarse approximation. Real hydro dispatch is driven by water inflows, reservoir levels, and operational decisions — none of which are captured here.

### 7.5 New Generators

For new non-renewable, non-VRE generators, no capacity factors are set (the optimiser freely dispatches within their other constraints).

For new hydro (daily, run-of-river), Ontario existing hydro capacity factors are currently used as a proxy for all regions. This is a known limitation flagged with a TODO.

---

## 8. Capacity Credits and Reserve Margin

**Module**: `capacity_credits.py`, `provincial_data/on/existing_capacity_credits.py`

Capacity credits express how much firm capacity each technology contributes toward meeting the planning reserve margin.

### 8.1 Non-VRE Generators

Capacity credits for thermal, nuclear, and hydro generators are derived from Ontario's IESO Reliability Outlook:

- The Reliability Outlook Table 4.1 provides **forecast capability at summer peak** and **total installed capacity** by fuel type.

- The ratio gives a capacity credit: `cc = capability / installed_capacity`.

- IESO fuel types are mapped to CANOE generator codes via `fuel_types.csv`.

- These credits are written to both `CapacityCredit` (for static reserve margin) and `ReserveCapacityDerate` (for dynamic/seasonal reserve margin) tables.

**Assumption**: Ontario's IESO reliability data is used for all provinces. This is a significant simplification — provinces with different generator fleets may have different de-rating factors.

### 8.2 VRE Capacity Credits (New Wind and Solar)

VRE capacity credits are calculated using the **NREL ReEDS top-100-hours method**:

- Start with the provincial **hourly load** (demand profile).

- Subtract hourly generation from all **existing VRE** to get an initial net load.

For each new VRE capacity bin (ordered by ascending LCOE):
   a. Calculate the **marginal net load** by subtracting the bin's projected hourly generation (capacity factor × nameplate capacity) from the current net load.
   b. Compute the **load duration curve (LDC)** and the **net load duration curve (NLDC)** (both sorted descending).
   c. The **capacity credit** is the mean reduction in NLDC over the top 100 hours, divided by nameplate capacity.
   d. Update net load for the next iteration.
- This produces **declining marginal capacity credits**: the first bins of VRE added have higher capacity value; later bins have diminishing value as their output becomes increasingly correlated with existing VRE.

**Assumption**: VRE capacity bins are assumed to be built sequentially in order of ascending LCOE, and only one type of renewable is evaluated at a time (cross-technology interactions are not captured).

### 8.3 Storage Capacity Credits

Storage is currently assigned a flat capacity credit of 0.9 for all regions and periods. This is a placeholder pending a more sophisticated method.

---

## 9. New Wind and Solar Characterisation

**Module**: `new_wind_solar.py`

New wind and solar use spatially explicit resource characterisation data. This is the most data-intensive part of the pipeline.

### 9.1 New Wind

#### Resource Data

Wind resource data comes from characterisation work by Sutubra, providing:

- **Cluster Composition**: For each geographic cluster, the fraction of three turbine technology classes (T1, T2, T3 corresponding to ATB wind classes 7, 8, 9) and maximum capacity.

- **Cluster Capacity Factors**: Hourly (8,760) capacity factor profiles per cluster.

- **Cluster Spur Costs**: Estimated cost to connect each cluster to the existing transmission grid.

#### Processing Steps

- **ATB cost projections** are loaded for each wind class (T1–T3): investment cost (OCC), fixed O&M, and capacity factor projections over time.

- **Weighted cluster costs** are computed by weighting ATB data by the capacity fraction of each turbine class in the cluster, then adding spur line costs.

- **LCOE ranking**: Clusters are sorted by estimated LCOE using a simple annualised cost / annual energy calculation with the global discount rate.

- **Bin assignment**: The top N clusters (N = number of capacity bins from `generator_technologies.csv`) are assigned to new capacity bins 1–N.

- **Capacity factor indexing**: Hourly CFs are scaled by ATB's projected CF improvement relative to a 2030 base year for each vintage.

- **Capacity credits** are calculated using the VRE top-100-hours method.

- **Database entries**: For each (region, cluster, vintage):

- `LimitCapacity`: Maximum capacity per bin (from cluster data, MW → GW)

- `Efficiency`: 1.0 (dummy ethos input)

- `CostInvest`: Weighted ATB + spur costs, currency-converted

- `CapacityFactorProcess`: Hourly CFs for each vintage (indexed to ATB projections)

- `CostFixed`: Weighted ATB fixed O&M

**Assumption**: Currently, only Ontario wind resource data is used for all provinces. This is flagged as a TODO for future improvement.

**Assumption**: Wind turbine classes 7/8/9 from ATB represent the range of resources available. Cost and performance improvements follow ATB projections.

### 9.2 New Solar

Similar to wind, but simpler (no turbine class weighting):

- Solar resource data provides per-grid-cell capacity factors, maximum capacity, interconnection costs, and LCOE.

- Grid cells are sorted by LCOE (or capacity factor, configurable).

- The top N cells are assigned to capacity bins.

- ATB solar PV cost and performance projections are applied, indexed to a 2022 base year.

- **Solar degradation**: A per-year degradation rate (default 0.85%/year) is applied to capacity factors, reducing output linearly with age.

- Capacity credits and database entries are computed as for wind.

**Assumption**: Solar degradation follows a flat 0.85%/year rate based on Jordan et al. (2016).

**Assumption**: As with wind, only Ontario solar resource data is currently used for all provinces.

---

## 10. Energy Storage

### 10.1 Existing Storage

From the CODERS `storage` API endpoint:

- Each storage facility is mapped to a CANOE technology based on (storage_type, duration).

- Duration is rounded to the nearest integer hour.

- Capacities are aggregated by (region, tech, vintage) following the same vintage-rounding and filtering logic as generators.

- Efficiency is taken from `storage_technologies.csv` (fixed, ATB-aligned).

- `StorageDuration` is set from the facility's reported duration.

- Technology flag is `"ps"` (physical storage).

### 10.2 New Storage

For new storage technologies (with `include_new = true`):

- A single technology variant is created per storage type (e.g., `E_BAT_2H-NEW`, `E_BAT_4H-NEW`).

- Efficiency and storage duration come from `storage_technologies.csv`.

- Cost data follows the ATB or CODERS path as for generators.

### 10.3 Monthly Hydroelectric Storage

Monthly hydro is given special treatment to model reservoir storage:

- An **intermediate commodity** (`E_hyd_mly_stor`) is created to represent stored water energy.

- An **inflow technology** (`E_HYD_MLY-EXS-IN`) fills the reservoir — it takes weather-dependent hydro inflow and produces the storage commodity.

- The **existing hydro tech** (`E_HYD_MLY-EXS`) is converted to a seasonal storage technology that takes from the reservoir and produces electricity.

- `StorageDuration` is set to 730 hours (approximately one month).

- The `LimitSeasonalCapacityFactor` from hydro CF calculations is assigned to the inflow technology rather than the dispatch technology, constraining how much energy enters the reservoir each season while allowing flexible dispatch.

**Assumption**: 730 hours of storage capacity represents monthly-scale reservoir flexibility. Real reservoirs may have multi-month or multi-year storage.

---

## 11. CCS Retrofits

**Module**: Part of `generators.py`

CCS retrofits are modelled as **add-on technologies** that sit between an existing fossil generator and the transmission grid:

### Architecture

Generator → [Intermediate Commodity] → CCS Retrofit → Transmission
                                    ↘ Bypass Tech  ↗

- A new **intermediate commodity** (e.g., `E_elc_tx_ng_cc`) is created between the generator output and the transmission grid.

- A **bypass technology** allows unabated electricity to pass through at efficiency 1.0.

- A **retrofit technology** (e.g., `E_NG_CCS_RFIT_95`) captures CO2 at a specified capture rate (e.g., 90% or 95%) with an energy penalty.

### Data Processing

- **Efficiency**: From ATB "Net Output Penalty" metric: `efficiency = 1 + penalty` (penalty is negative, so efficiency < 1).

- **Emissions**: Negative emission entries: `-capture_rate × generator_co2_emissions / efficiency`.

- **Costs**: Investment, fixed O&M, and variable O&M from ATB CCS retrofit data.

- **Lifetime**: CCS retrofit lifetime is capped to not exceed the remaining life of the retrofittable generators.

- **Activity limits**: Retrofit and bypass activities are capped to zero when no generators remain alive.

**Assumption**: The ATB provides representative costs for CCS retrofits on natural gas combined cycle and coal plants. Costs are not region-specific.

**Assumption**: CCS retrofits are vintage-dependent — costs decrease over time following ATB projections.

---

## 12. Interfaces and Interties

**Module**: `interfaces.py`

Interties (electricity interconnections) between provinces and to the U.S. are aggregated in two categories:

### 12.1 Boundary Interfaces

These cross the model boundary (one region inside the model, one outside). They are represented as:

- **Outgoing demand**: A demand commodity and demand technology force the model to export the historically observed flow pattern.

- **Incoming VRE generator**: A variable generator with curtailment ability represents imports, with capacity factors derived from historical hourly flows.

#### Processing Steps

- All interprovincial and international interties are loaded from CODERS.

- For each intertie crossing the model boundary, hourly flow data is retrieved for the weather year.

- **Flow direction**: In CODERS, negative flows represent forward transfers and positive flows represent backward transfers.

- Flows are aggregated by regional pair.

- **Export (outgoing)**:

- Annual demand = sum of outgoing hourly flows (MWh → PJ).

- Demand profile (DSD) = hourly flow / annual total.

- Transmission efficiency = 1 − province line loss.

- Variable cost from AEO transmission costs.

- **Import (incoming)**:

- Existing capacity = peak hourly import flow (MWh/h → GW).

- Capacity factor = hourly flow / peak flow.

- Marked as curtailable.

**Assumption**: Historical boundary flows are projected forward as fixed demand/supply patterns for all future periods. This freezes international trade at weather-year levels.

### 12.2 Endogenous Interfaces

These connect two modelled regions and are represented as **exchange technologies** in Temoa:

- A single `E_INT` technology is used.

- **Capacity**: Set to the maximum of seasonal transfer capabilities (summer/winter) in either direction, from CODERS `interface_capacities`.

- **Seasonal capacity factors**: If transfer capabilities differ by season or direction, capacity factors constrain flows below the physical limit.

- **Efficiency**: 1 − line loss of the sending province.

- **Variable cost**: AEO transmission costs apply.

**Assumption**: Endogenous interface capacity is fixed at existing levels; no transmission expansion is modelled between provinces.

---

## 13. Constraints

**Module**: `constraints.py` dispatching to `provincial_data/default/`

### 13.1 Ramp Rates

**Source**: `ramp_rates.csv`, based on Dolter & Rivers (2018).

Hourly ramp-up and ramp-down rates are applied to technologies based on their CANOE tech code. Values are expressed as a fraction of capacity per hour.

Not all technologies have ramp constraints — only those listed in the CSV file.

### 13.2 Cogeneration Constraints

Existing cogeneration technologies (natural gas CHP, biomass CHP) are activity-constrained:

- **Maximum activity** = `unit_average_annual_energy` from CODERS (converted to PJ).

- **Minimum activity** = 95% of maximum (computational slack).

This ensures cogeneration output matches historical levels, since the model does not endogenously represent the heat demand served by CHP.

**Assumption**: Cogeneration heat demand is exogenous and constant. The 5% slack prevents infeasibility.

---

## 14. Currency Conversion

**Module**: `currency_conversion.py`

All costs in the database are converted to a single target currency and year (default: CAD 2020).

### Methodology

The conversion uses two tables from `input_files/`:

- **`currency_exchange.csv`**: Exchange rates for multiple currencies (USD, EUR, GBP, AUD, CAD) by year.

- **`cad_inflation.csv`**: Inflation indices (GDP deflator, CPI variants, construction indices) by year.

The conversion formula is:

converted_cost = original_cost × exchange_rate(orig_year, orig_currency) × inflation_index(orig_year) / base_factor

where `base_factor = exchange_rate(base_year, base_currency) × inflation_index(base_year)`.

The GDP deflator index is used by default. Conversion happens **inline** during data aggregation — each cost value is converted before being written to the database.

---

## 15. Post-Processing

**Module**: `post_processing.py`

After all data has been aggregated:

### 15.1 Import Dummy Technologies

If `include_imports` is enabled, dummy import technologies are created for each fuel commodity used in the model:

- For every commodity that appears as an input in the `Efficiency` table, an import technology is created.

- Import techs have efficiency 1.0, a single vintage at the first period, and retire when no longer needed.

- This bridges the gap between fuel supply sectors and the electricity sector.

### 15.2 Commodity Table

Commodities are added to the `Commodity` table based on actual usage:

- Only commodities appearing in `Efficiency` (as inputs or outputs) or `EmissionActivity` (as emission commodities) are added.

- This prevents orphaned commodities in the database.

### 15.3 Unused Technology Removal

Technologies that appear in the `Technology` table but never in the `Efficiency` table are removed from all database tables. This cleans up technologies that were configured but never had valid data (e.g., a province might not have solar generators to aggregate).

### 15.4 References and Data IDs

- All bibliography entries are written to the `DataSource` table.

- All unique data IDs are written to the `DataSet` table.

- A consistency check warns about any database rows with NULL `data_id` values.

---

## 16. Unit Conventions

All unit conversions are centralised in `input_files/units.csv`. Key conversions include:

| Quantity | Input Units | Model Units | Conversion |
|---|---|---|---|
| Capacity | MW | GW | ÷ 1000 |
| Activity/Energy | MWh | PJ | × 3.6×10⁻⁶ |
| Investment cost | $/kW | M$/GW | × 1 (equivalent) |
| Fixed O&M | $/kW-yr | M$/GW-yr | × 1 |
| Variable O&M | $/MWh | M$/PJ | × 1/3.6 |
| Heat rate | MMBtu/MWh | PJ/PJ | Specific factor |
| Emissions | lbs/MMBtu | kt/PJ | Specific factor |
| Ramp rate | %/min | fraction/hour | × 0.6 |
| C2A | PJ/GW·yr | — | 31.536 |

The `units.csv` file contains separate columns for CODERS and ATB conversion factors, since the two data sources use different native units.

---

## 17. Known Assumptions and Limitations

### Spatial

- **Ontario data as default**: Several province-specific calculations (hydro CFs, VRE resource characterisation, capacity credits) currently use Ontario data for all provinces. This is flagged in the code with TODO comments.

- **Province-level granularity**: Generators, demand, and transmission are modelled at the provincial level. Sub-provincial variation is not captured.

- **U.S. trade frozen**: Boundary interties with the U.S. use weather-year historical flows for all future periods.

### Temporal

- **Weather year**: All hourly profiles (demand, generation, interties) come from a single weather year (2018 by default). Climate variability is not represented.

- **Static demand shape**: The hourly demand profile is assumed constant across all future periods.

### Technical

- **No transmission expansion**: In-province transmission and interprovincial capacities are fixed.

- **Hydro approximation**: Monthly hydro uses 730-hour storage duration; real reservoir operations are more complex.

- **Cogeneration heat demand**: Treated as exogenous and constant.

- **Storage capacity credits**: Flat 0.9 for all storage, pending improved methodology.

### Economic

- **U.S. cost data**: Transmission/distribution costs come from EIA AEO, not Canadian sources.

- **ATB prevalence**: Technology costs primarily follow U.S. ATB projections, which may not reflect Canadian market conditions.

- **Currency conversion**: Uses GDP deflator for inflation adjustment; other indices are available but not default.

### Data Quality

- **CODERS data completeness**: Some generators may lack renewal dates, capacity factors, or average annual energy data, leading to potential inaccuracies in vintage assignment or CF calculations.

- **Renewables Ninja synthesis**: Non-Ontario VRE CFs are simulated rather than observed, introducing weather model uncertainty.

---

*This documentation describes the CANOE electricity sector aggregation tool as of 2025. The tool is under active development and some features (marked with TODO) are planned for future improvement.*

# CANOE Electricity Sector — Data Sources Catalog

*A comprehensive catalog of all upstream data sources used by the CANOE electricity sector aggregation tool, their update schedules, and procedures for incorporating updated data.*

---

## Table of Contents

- [Data Source Summary](#1-data-source-summary)

- [CODERS — Canadian Open-Source Database for Energy Research](#2-coders)

- [NREL Annual Technology Baseline (ATB)](#3-nrel-annual-technology-baseline-atb)

- [IESO Public Data (Ontario)](#4-ieso-public-data-ontario)

- [Statistics Canada](#5-statistics-canada)

- [Renewables Ninja API](#6-renewables-ninja-api)

- [U.S. EIA Annual Energy Outlook (AEO)](#7-us-eia-annual-energy-outlook-aeo)

- [Sutubra VRE Resource Characterisation](#8-sutubra-vre-resource-characterisation)

- [Academic and Reference Data](#9-academic-and-reference-data)

- [Update Procedures](#10-update-procedures)

---

## 1. Data Source Summary

| # | Source | Type | Frequency | Used For | Critical? |
|---|---|---|---|---|---|
| 1 | CODERS API | REST API / CSV cache | Annual | Generators, demand, interties, system parameters | **Yes** |
| 2 | NREL ATB CSV | CSV download | Annual (July) | Technology costs, heat rates, efficiency, emissions | **Yes** |
| 3 | NREL ATB Workbook | Excel download | Annual (July) | TSV: emissions factors, ramp rates, outage rates | **Yes** |
| 4 | IESO Public Data | XML/CSV/Excel download | Ongoing/Monthly | Ontario VRE CFs, hydro CFs, capacity credits | **Yes** (Ontario) |
| 5 | Statistics Canada | ZIP/CSV download | Monthly | Hydroelectric monthly generation by province | Moderate |
| 6 | Renewables Ninja | REST API | On-demand | Non-Ontario VRE hourly capacity factor synthesis | Moderate |
| 7 | EIA AEO | Manual/CSV | Annual (March) | Transmission and distribution variable costs | Low |
| 8 | Sutubra Resource Data | Local CSV files | Periodic | New wind/solar cluster data (CFs, costs, spur lines) | **Yes** |
| 9 | Currency/Inflation tables | Local CSV files | Annual | Currency exchange rates and inflation adjustments | Low |
| 10 | Dolter & Rivers (2018) | Local CSV | Static | Ramp rate constraints | Low |
| 11 | Jordan et al. (2016) | Parameter in config | Static | Solar degradation rate | Low |

---

## 2. CODERS

### Description

The **Canadian Open-Source Database for Energy Research and Systems-Modelling (CODERS)** is the primary data source providing the Canadian energy system inventory. It is maintained by the Centre for Applied Energy Research at the University of Victoria and accessible via REST API.

**Website**: [https://cme-emh.ca/en/coders/](https://cme-emh.ca/en/coders/)

**API base URL**: `https://api.sesit.ca/`

### API Key Requirement

An API key must be obtained from the CODERS website and stored in `input_files/coders_api_key.txt`. This file is git-ignored and must be created manually.

### Endpoints Used

| Endpoint | Cache File | Used In | Purpose |
|---|---|---|---|
| `generators` | `generators.csv` | `generators.py` | Existing generator fleet: facility name, type, capacity, vintage, location, annual energy |
| `storage` | `storage.csv` | `generators.py` | Existing storage facilities: type, capacity, duration, location |
| `generation_generic` | `generationgeneric.csv` | `generators.py` | Generic technology parameters: efficiency, service life, emissions, fuel prices, O&M costs |
| `generation_cost_evolution` | `generationcostevolution.csv` | `generators.py` | Investment cost projections by technology and year |
| `CA_system_parameters` | `CAsystemparameters.csv` | `provincial_grids.py`, `interfaces.py` | Provincial system parameters: line losses, reserve requirements |
| `forecasted_annual_demand` | `forecastedannualdemand.csv` | `provincial_grids.py` | Provincial annual demand projections by year |
| `provincial_demand` | `provincialdemandyear{Y}province{P}.csv` | `provincial_grids.py` | Hourly provincial demand for specific year and province |
| `interface_capacities` | `interfacecapacities.csv` | `interfaces.py` | Transfer capabilities between provinces/states (summer/winter) |
| `interprovincial_transfers` | `interprovincialtransfers*.csv` | `interfaces.py` | Hourly interprovincial flow data and available interties |
| `international_transfers` | `internationaltransfers*.csv` | `interfaces.py` | Hourly Canada–U.S. flow data and available interties |

### Update Schedule

CODERS is updated **annually**, typically in the first half of the calendar year. Individual tables may be updated independently. Key data points that change annually:

- Existing generator fleet additions and retirements

- Annual demand forecasts (extended horizon)

- Technology cost projections

- Provincial system parameters

### Citation Format

Hendriks, R.M., Monroe, J., Cusi, T., Aldana, D., Griffiths, K., Dorman, T., Chhina, A., 
McPherson, M. (2023). Canadian Open-Source Database for Energy Research and Systems-Modelling 
(CODERS). Available at www.cme-emh/coders. {table} table. Accessed {date}

---

## 3. NREL Annual Technology Baseline (ATB)

### Description

The **NREL Annual Technology Baseline** provides projected technology cost and performance data for electricity generation and storage technologies. Two files are used:

- **ATB CSV** (`ATBe.csv`): The main data table with cost metrics, capacity factors, heat rates, and more, indexed by technology, scenario, year, and metric.

- **ATB Master Workbook** (`.xlsx`): The full Excel calculation workbook containing technology-specific variable (TSV) tables with detailed technical parameters (emissions factors, ramp rates, outage rates).

**Website**: [https://atb.nrel.gov/](https://atb.nrel.gov/)

### URLs (from params.yaml, 2024 v3 edition)

| File | URL |
|---|---|
| ATB CSV | `https://oedi-data-lake.s3.amazonaws.com/ATB/electricity/csv/2024/v3.0.0/ATBe.csv` |
| ATB Workbook | `https://data.openei.org/files/6006/2024_v3_Workbook.xlsx` |

### Data Parameters Extracted

| Parameter | Source | ATB Metric | Notes |
|---|---|---|---|
| Investment cost | ATB CSV | OCC (Overnight Capital Cost) | Per-vintage projections |
| Fixed O&M | ATB CSV | Fixed O&M | Per-vintage projections |
| Variable O&M | ATB CSV | Variable O&M | Per-period projections |
| Fuel cost | ATB CSV | Fuel | Per-period projections |
| Heat rate (efficiency) | ATB CSV | Heat Rate | Converted to fractional efficiency |
| Capacity factor | ATB CSV | CF | Used for VRE indexing |
| CO2 emissions | ATB Workbook TSV | emissions_co2_lbs_MMBtu | Per-technology |
| SO2 emissions | ATB Workbook TSV | emissions_so2_lbs_MMBtu | Per-technology |
| NOx emissions | ATB Workbook TSV | emissions_nox_lbs_MMBtu | Per-technology |
| Hg emissions | ATB Workbook TSV | emissions_hg_lbs_MMBtu | Per-technology |
| Ramp rate | ATB Workbook TSV | ramp_rate_%_min | Per-technology |
| CCS Net Output Penalty | ATB CSV | Net Output Penalty | For CCS retrofits |
| CCS Additional OCC | ATB CSV | Additional OCC | For CCS retrofits |

### Configuration

- **Scenario**: Configurable in `generator_technologies.csv` per technology (`Conservative`, `Moderate`, or `Advanced`). Recommended: `Moderate`.

- **Core metric case**: `Market` (from params.yaml).

- **CRP years**: Fixed at 20 (arbitrary unless using LCOE).

- **Currency**: USD, year configurable (currently 2021).

### Update Schedule

The ATB is released **annually in July**. The release consists of new CSV data files and an updated Excel workbook. Version numbering follows `YYYY/vX.Y.Z`.

### How to Update

- Go to [https://atb.nrel.gov/electricity/data](https://atb.nrel.gov/electricity/data) and find the latest CSV and Workbook links.

- In `params.yaml`, update:

- `atb.url` → new CSV URL

- `atb.master_url` → new Workbook URL

- `atb.year` → new publication year

- `atb.currency_year` → verify the new ATB's cost year

- Check `atb.tsv_headers` — column names in the workbook may change between versions.

- Update `input_files/atb_master_tables.csv` if worksheet names, row ranges, or column ranges have changed. This is verified by manually opening the workbook and comparing.

- Update `generator_technologies.csv` column `atb_display_name` if technology display names have changed.

- Delete cached ATB files in `data_cache/` (`ATBe.csv`, `2024_v3_Workbook.xlsx`, `atb_technology_specific_variables_*.csv`).

- Re-run the aggregation.

---

## 4. IESO Public Data (Ontario)

### Description

The **Independent Electricity System Operator (IESO)** publishes detailed operational data for Ontario's electricity grid. Three data products are used:

### 4.1 Generator Output by Fuel (Hourly)

| Attribute | Value |
|---|---|
| URL pattern | `http://reports.ieso.ca/public/GenOutputbyFuelHourly/PUB_GenOutputbyFuelHourly_{YYYY}.xml` |
| Format | XML |
| Frequency | Annual compilation |
| Used in | `provincial_data/on/existing_vre_capacity_factors.py` |
| Purpose | Aggregate Ontario hourly wind and solar generation for capacity factor calculation |

### 4.2 Generator Output and Capability (Monthly)

| Attribute | Value |
|---|---|
| URL pattern (before 2019) | `https://www.ieso.ca/-/media/Files/IESO/Power-Data/data-directory/GOC-{YYYY}.xlsx` |
| URL pattern (2020+) | `http://reports.ieso.ca/public/GenOutputCapabilityMonth/PUB_GenOutputCapabilityMonth_{YYYY}{MM}.csv` |
| Format | Excel (pre-2019) or CSV (2020+) |
| Frequency | Monthly |
| Used in | `provincial_data/on/existing_hydro_capacity_factors.py` |
| Purpose | Ontario hydroelectric hourly output and available capacity by generator |

### 4.3 Reliability Outlook

| Attribute | Value |
|---|---|
| URL pattern | `https://www.ieso.ca/-/media/Files/IESO/Document-Library/planning-forecasts/reliability-outlook/ReliabilityOutlookTables_{YYYY}{Mon}.xlsx` |
| Format | Excel |
| Frequency | ~Semi-annual |
| Used in | `provincial_data/on/existing_capacity_credits.py` |
| Purpose | Capacity credits from forecast capability vs. installed capacity |
| Table used | Table 4.1: Forecast capability at summer peak |

### Update Schedule

- Hourly generation data: Updated annually with each calendar year's data.

- Monthly capability data: Monthly releases.

- Reliability Outlook: Updated approximately twice per year (e.g., June and December).

### How to Update

- **Weather year change** (if updating the weather year):

- Update `params.yaml`: `weather_year` to the new year.

- Delete provincial demand and intertie flow cache files for the old year.

Delete Ontario-specific output data in `provincial_data/on/output_data/`.

**Reliability Outlook update**:

- In `params.yaml`, update `ieso_rel_yyyy_mmm` (e.g., `"2026_Jun"`).

- Verify `ieso_rel_peak_type` is still valid (`"Firm"` or `"Planned"` — IESO may change terminology).

Delete the cached reliability outlook file in `data_cache/`.

**Hydro types**: If IESO changes generator naming, update `provincial_data/on/hydro_types.csv`.

- **Fuel types**: If IESO changes fuel type naming in reliability outlook, update `provincial_data/on/fuel_types.csv`.

### Citation Format

IESO. ({year}). IESO public data. http://reports.ieso.ca/public/
IESO. ({year}, {month}). Reliability Outlook. https://www.ieso.ca/en/Sector-Participants/Planning-and-Forecasting/Reliability-Outlook

---

## 5. Statistics Canada

### Description

Statistics Canada table **25-10-0015-01** provides monthly electricity generation by type of turbine and province. This is used to synthesise hydroelectric capacity factors for provinces other than Ontario.

| Attribute | Value |
|---|---|
| Table | 25-10-0015-01 |
| URL | `https://www150.statcan.gc.ca/t1/wds/rest/getFullTableDownloadCSV/25100015/en` |
| Format | CSV inside ZIP |
| Used in | `provincial_data/default/existing_hydro_capacity_factors.py` |
| Purpose | Monthly hydraulic turbine generation by province and year |

### Update Schedule

Updated **monthly** by Statistics Canada, typically with a 2–3 month lag.

### How to Update

The data is downloaded automatically when the weather year changes or cache is cleared. No code changes are needed unless StatCan changes the table format or number.

- Delete `data_cache/monthly_hydro_gen.csv` to force re-download.

- If the table ID changes, update the `25100015` references in `provincial_data/default/existing_hydro_capacity_factors.py`.

### Citation

Government of Canada, Statistics Canada. Electric power generation, monthly generation by type of 
electricity. Table 25-10-0015-01. https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=2510001501

---

## 6. Renewables Ninja API

### Description

**Renewables Ninja** provides simulated hourly electricity output for wind and solar PV installations at any location worldwide, using MERRA-2 reanalysis weather data. It is used to synthesise capacity factor profiles for existing VRE facilities outside Ontario.

**Website**: [https://www.renewables.ninja/](https://www.renewables.ninja/)

**API base URL**: `https://www.renewables.ninja/api/`

### API Key Requirement

A token must be obtained from the Renewables Ninja website and stored in either `input_files/rninja_api_token.txt` or `provincial_data/default/rninja_api_token.txt`.

### Parameters Used

| Technology | Parameters |
|---|---|
| Solar PV | lat/lon per facility, tilt=45°, system_loss=10%, tracking=0, dataset=MERRA-2 |
| Onshore Wind | lat/lon per facility, height=110m, turbine=Vestas V112 3000 |
| Offshore Wind | lat/lon per facility, height=150m, turbine=Vestas V164 9500 |

### Rate Limits and Caching

- **50 requests per hour**.

- Results are cached per-facility in `provincial_data/default/output_data/cf_solar.csv`, `cf_wind_on.csv`, `cf_wind_off.csv`.

- Initial data collection for ~200+ facilities can take several hours.

- Subsequent runs use cached data unless facilities are added.

### Update Schedule

The API is available on-demand. Weather data (MERRA-2) is updated periodically by NASA. The API should only need to be re-queried when:

- The weather year changes.

- New VRE facilities are added to CODERS.

### How to Update

- Delete `provincial_data/default/output_data/cf_*.csv` to force re-collection.

- Ensure API token is valid.

- Re-run aggregation — the tool will prompt for confirmation before initiating API collection.

### Citation

Pfenninger, S., & Staffell, I. (2016). Long-term patterns of European PV output using 30 years 
of validated hourly reanalysis and satellite data. Energy, 114, 1251–1265. 
https://doi.org/10.1016/j.energy.2016.08.060

---

## 7. U.S. EIA Annual Energy Outlook (AEO)

### Description

The **Annual Energy Outlook** from the U.S. Energy Information Administration provides projected levelised costs for electricity transmission and distribution.

**Website**: [https://www.eia.gov/outlooks/aeo/](https://www.eia.gov/outlooks/aeo/)

### Data Used

| Table | Data | Cache File |
|---|---|---|
| Table 8 (AEO 2025) | Levelised cost of transmission (cents/kWh) | `provincial_data/default/cost_tx_dx.csv` |
| Table 8 (AEO 2025) | Levelised cost of distribution (cents/kWh) | `provincial_data/default/cost_tx_dx.csv` |

Costs are converted from USD 2024 cents/kWh to M$/PJ in CAD 2020.

### Update Schedule

AEO is released **annually in March**.

### How to Update

- Visit the AEO data browser and extract Table 8 transmission and distribution costs.

- Update `provincial_data/default/cost_tx_dx.csv` with new projections.

- Update the currency year in `provincial_data/default/cost_tx_dx.py` if the AEO changes its cost year.

- Update the reference URL in `cost_tx_dx.py`.

### Citation

U.S. Energy Information Administration. Annual Energy Outlook {year}. 
https://www.eia.gov/outlooks/aeo/data/browser/

---

## 8. Sutubra VRE Resource Characterisation

### Description

Resource characterisation data for new wind and solar capacity comes from work by **Sutubra** (a research group or tool; citation placeholder in current code). This data provides spatially resolved renewable energy resource assessments for Ontario.

### Data Files

Located in `provincial_data/on/new_wind/` and `provincial_data/on/new_solar/`:

#### Wind Data

| File | Content |
|---|---|
| `Cluster Composition.csv` | Fraction of turbine classes (T1/T2/T3) per cluster, maximum capacity |
| `Cluster Capacity Factors.csv` | 8,760 hourly capacity factor profiles per cluster |
| `Cluster Spur Costs.csv` | Estimated transmission interconnection cost per cluster (USD/kW) |
| `Cluster Costs.csv` | Additional cost data per cluster |
| `Cluster Mappings.csv` | Geographic mapping of clusters |
| `Resource Summary.csv` | Summary resource statistics |

#### Solar Data

| File | Content |
|---|---|
| `Hourly PV Capacity Factors.csv` | 8,760 hourly capacity factor profiles per grid cell |
| `Solar Resource Summary.csv` | Per-cell capacity factor, max capacity, LCOE, interconnection cost, coordinates |

### Update Schedule

Updated **periodically** as new resource assessment studies are completed. Not on a fixed schedule.

### How to Update

- Replace the CSV files in `provincial_data/on/new_wind/` and/or `provincial_data/on/new_solar/` with updated data files from the latest resource assessment.

- Ensure column names match expectations in the code (check `new_wind_solar.py`).

- If expanding to other provinces:

- Create `provincial_data/{province_code}/new_wind/` and `new_solar/` directories with equivalent files.

- Update `new_wind_solar.py` to load province-specific data instead of hardcoded Ontario paths.

- Update the reference in `params.yaml` under `sutubra_vre.reference` and `sutubra_vre.year`.

---

## 9. Academic and Reference Data

### 9.1 Ramp Rate Constraints

| Attribute | Value |
|---|---|
| Source | Dolter & Rivers (2018) |
| File | `provincial_data/default/ramp_rates.csv` |
| Type | Static lookup table |
| Update | Only if better data becomes available |

**Citation**:

Dolter, B., & Rivers, N. (2018). The cost of decarbonizing the Canadian electricity system. 
Energy Policy, 113, 135–148. https://doi.org/10.1016/j.enpol.2017.10.040

### 9.2 Solar Degradation Rate

| Attribute | Value |
|---|---|
| Rate | 0.85% per year |
| Source | Jordan et al. (2016) |
| Used in | `new_wind_solar.py` (`aggregate_solar`) |

**Citation**:

Jordan, D. C., Kurtz, S. R., VanSant, K., & Newmiller, J. (2016). Compendium of photovoltaic 
degradation rates. Progress in Photovoltaics, 24(7), 978–989. https://doi.org/10.1002/pip.2744

### 9.3 Capacity Credit Methodology

| Attribute | Value |
|---|---|
| Method | NREL ReEDS 8760-based top-100-hour net load method |
| Source | Frew et al. (2017) |
| Used in | `capacity_credits.py` |

**Citation**:

Frew, B., Cole, W., Sun, Y., Richards, J., & Mai, T. (2017). 8760-Based Method for Representing 
Variable Generation Capacity Value in Capacity Expansion Models. NREL. 
https://www.nrel.gov/docs/fy17osti/68869.pdf

### 9.4 Currency Conversion Tables

| File | Content | Update Frequency |
|---|---|---|
| `input_files/currency_exchange.csv` | Annual exchange rates (USD, EUR, GBP, AUD, CAD) | Annual |
| `input_files/cad_inflation.csv` | Inflation indices (GDP deflator, CPI, etc.) | Annual |

These tables must be manually extended with new year rows as data becomes available from Statistics Canada and the Bank of Canada.

---

## 10. Update Procedures

### 10.1 Annual Update Checklist

This checklist should be followed when performing a regular annual or biannual CANOE update:

#### Phase 1: Prepare Environment

- [ ] **Back up the data cache**: Copy `data_cache/` to a safe location.

- [ ] **Clear the data cache**: Delete all files in `data_cache/` to ensure fresh downloads.

- [ ] **Delete generated output data**:

- `provincial_data/on/output_data/*.csv`

- `provincial_data/default/output_data/*.csv`

- [ ] **Verify API keys**: Ensure CODERS (`input_files/coders_api_key.txt`) and Renewables Ninja (`input_files/rninja_api_token.txt`) tokens are valid.

#### Phase 2: Update Data Sources

- [ ] **NREL ATB** (if new version available, typically July):

- Update URLs in `params.yaml` (`atb.url`, `atb.master_url`).

- Check and update `atb.currency_year`, `atb.tsv_headers`, `atb.cost_invest_metric` if needed.

- Update `input_files/atb_master_tables.csv` row/column ranges.

Verify `generator_technologies.csv` `atb_display_name` values still match.

[ ] **IESO Reliability Outlook** (if new version available):

- Update `params.yaml`: `ieso_rel_yyyy_mmm`.

Verify `ieso_rel_peak_type` is still valid.

[ ] **EIA AEO** (if new version available, typically March):

- Update `provincial_data/default/cost_tx_dx.csv` with new projections.

Update currency year and reference in `cost_tx_dx.py`.

[ ] **Currency tables**:

- Extend `input_files/currency_exchange.csv` with the new year's exchange rates.

Extend `input_files/cad_inflation.csv` with the new year's inflation indices.

[ ] **Model periods** (if extending horizon):

- Add new periods to `params.yaml` `model_periods` list.

#### Phase 3: Run and Validate

- [ ] **Run the aggregation**: `python canoe-electricity/`

- [ ] **Review diagnostic plots** in `output_plots/` for anomalies.

- [ ] **Check console warnings** for skipped generators, missing data, or mapping failures.

- [ ] **Spot-check database**: Open the SQLite database and verify key tables have reasonable values.

#### Phase 4: Handle Issues

Common issues after data updates:

| Issue | Likely Cause | Resolution |
|---|---|---|
| ATB column not found | Header names changed between ATB versions | Update `atb.tsv_headers` in `params.yaml` |
| ATB technology not found | Display names changed | Update `atb_display_name` in `generator_technologies.csv` |
| CODERS endpoint returns None | API key expired or table renamed | Renew API key; check CODERS documentation |
| Missing generator facilities | New facilities in CODERS not mapped | Update `coders_existing` column in `generator_technologies.csv` |
| Reliability Outlook parse error | Table format changed | Open workbook manually and update `existing_capacity_credits.py` parsing |
| Negative efficiency or cost | Unit change in source data | Verify and update conversion factors in `units.csv` |

### 10.2 Weather Year Change

Changing the weather year affects all time-series data:

- Update `params.yaml`: `weather_year`.

- Clear all cached time-series data:

- `data_cache/provincialdemandyear*.csv`

- `data_cache/interprovincialtransfersyear*.csv`

- `data_cache/internationaltransfersyear*.csv`

- `data_cache/PUB_GenOutputbyFuelHourly_*.pkl`

- `data_cache/on_gen_output_*.csv` and `on_gen_capacity_*.csv`

- Clear synthesised capacity factors:

- `provincial_data/default/output_data/cf_*.csv`

- `provincial_data/on/output_data/*.csv`

- Re-run aggregation. Note: Renewables Ninja API collection may take several hours.

### 10.3 Adding a New Province

To bring a new province from exogenous to endogenous:

- In `input_files/regions.csv`, set `endogenous = TRUE` for the province.

- Ensure the province has CODERS equivalents mapped in the `coders_equivs` column.

- Optionally create a `provincial_data/{code}/` directory with province-specific data scripts.

- Verify that CODERS has hourly demand data for this province for the weather year.

### 10.4 Adding a New Technology

- Add a row to the appropriate technology CSV (`generator_technologies.csv`, `storage_technologies.csv`, or `ccs_retrofit_technologies.csv`).

- Map it to CODERS and/or ATB equivalents.

- Define its input/output commodities in `commodities.csv` if new commodities are needed.

- Re-run the aggregation.

---

*Last updated: 2025. This catalog should be reviewed and updated with each major CANOE update cycle.*