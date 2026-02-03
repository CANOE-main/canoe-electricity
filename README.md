# CANOE Electricity Sector Aggregation

This script aggregates the modular electricity sector model for CANOE. It pulls data primarily from CODERS but also from the NREL ATB (optionally) and some other sources like the IESO public database.

Aggregation can be configured through files in `input_files/` (see Configuration) to include/exclude technologies, provinces, types of data/model structures.

It will download a large number of files on the first run (as of now, 141 MB) but will cache these files locally and use the local cache in subsequent runs. Parameters can be set to force downloading to get latest data (see Configuration).

## Usage

### 1. Create the conda environment

1.  Install miniconda.
2.  Open a miniconda prompt.
3.  Install the conda environment:
    *   Set current directory to the repository folder:
        ```bash
        cd C:/.../canoe-electricity/
        ```
    *   Create the environment:
        ```bash
        conda env create
        ```

### 2. Add your CODERS API key

1.  Acquire a CODERS API key at [CodeRS](https://cme-emh.ca/en/coders/).
2.  Create a new text file in `input_files/` called `coders_api_key.txt` and save your API key there.

### 3. Run the aggregation

1.  Set current directory to the parent of the repository:
    ```bash
    cd C:/.../parent_folder/
    ```
2.  Activate the environment:
    ```bash
    conda activate canoe-backend
    ```
3.  Run the scripts:
    ```bash
    python canoe-electricity/
    ```
    *(Note: Replace `canoe-electricity` with the actual folder name if different)*

## Annual Update Checklist

1.  Make a copy of the data cache and remove all its contents.
2.  Update any links in the `params.yaml` file for updated data sources.
3.  Fix any bugs that emerge.

## Components

### Directories

*   `data_cache/`: Where downloaded data is locally cached and pulled from on subsequent runs, unless `force_download` param is set to True.
*   `input_files/`:
    *   Configuration files
    *   CANOE database schema (`canoe_dataset_schema.sql`)
    *   CANOE excel spreadsheet template
    *   `params.yml` (see Configuration)
    *   `coders_api_key.txt` (NOTE: this file is ignored by git and must be created manually)

### Scripts

*   `__main__.py`: For running from command line like `python canoe-electricity/`.
*   `electricity_sector.py`: Handles execution order of other scripts.
*   `currency_conversion.py`: Converts data currencies to a unified final currency.
*   `coders_api.py`: Handles fetching of data from CODERS and local caching.
*   `setup.py`: Builds the config object which contains aggregation configuration and some common data.
*   `utils.py`: Repository of frequently used utility scripts. Includes `get_data()` method which robustly fetches and locally caches data from online sources.
*   `testing_dummy.py`: A blank script for prototyping code snippets.
*   `others...`: Aggregation scripts for particular data types.

## Configuration

Configuration is performed by editing the files in `input_files/`.

### `params.yml`

Various other aggregation parameters. Some cannot be changed but others can. Generally free to play with booleans under "## Aggregation switches".

### `atb_master_tables.csv`

This simply references where to find tables (so far only technology-specific variables) in the calculation workbook of the NREL ATB. It may need to be updated with new versions of the ATB.

**Columns:**

*   `atb_master_sheet`: The name of the excel worksheet to be extracted from (referenced by `[storage/generator]_technologies.csv`) - table. Label of which table is being specific. So far only tsv for technology-specific variables.
*   `first_row`: Excel-indexed row number of the first table row (first of multiple header rows for tsv).
*   `last_row`: Excel-indexed row number of the bottom row of the table.
*   `columns`: Excel-indexed column letters spanning the table.

### `generator_technologies.csv`

Configures the aggregation of generators.

**Columns:**

*   `code`: DO NOT CHANGE. This is the immutable reference code for generator types and is hard-linked into scripts.
*   `base_tech`: The in-database base name for a technology. Base tech name will be appended with variants such as -EXS for existing capacity, -NEW for new capacity, -NEW-1 for batched new capacity if configured in `batched_new_capacity.xlsx`.
*   `description`: The in-database description of this technology.
*   `include_new`: Whether to include new capacity of this technology in the model.
*   `coders_existing`: Which CODERS technology types to aggregate as existing capacity for this technology. If blank, this technology will have no existing capacity. Multiple CODERS gen types (from the generators API table) can be added with a + as `tech_one+tech_two`.
*   `coders_equiv`: Which CODERS technology to use for generic data from generation_generic API table.
*   `atb_display_name`: Which ATB technology to use for generic ATB data. If this is set, it will PRIORITISE ATB DATA but pull from CODERS if unavailable. Some data will be pulled from CODERS either way.
*   `atb_master_sheet`: In which worksheet of the ATB calculation workbook is the technology-specific variables table for this technology. Does not need to be set.
*   `atb_tsv_row`: Which row of the technology-specific variables table corresponds to this technology. Must be set if `atb_master_sheet` is used.
*   `atb_scenario`: Which ATB scenario to use for ATB generic data for this technology. Must be set if pulling data from the ATB. 'Conservative', 'Moderate' (recommended), or 'Advanced'.
*   `in_comm` / `out_comm`: Immutable commodity code that this technology will use as an input/output. The name of that commodity can be configured in `commodities.csv`.
*   `new_cap_batches`: How many batches/bins of new capacity should this technology have in the model. Will create this many new capacity variant technologies, e.g. if set to 3: E_TECH-NEW-1, E_TECH-NEW-2, E_TECH-NEW-3.
*   `flag`: Technology flag for the technologies database table.
*   `tech_sets`: Which database sets to add this technology to. Multiple can be added with a +.
*   `include_fuel_cost`: Whether to attach variable fuel costs from ATB/CODERS to this technology. Set FALSE if adding costs on fuel import.
*   `no_retirement`: Whether this technology ever retires. Should be TRUE for hydroelectric techs. Aggregates existing capacity to last period before first model period and sets lifetime to 100.
