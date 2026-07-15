"""Pydantic configuration models for the electricity module."""
from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------------------------------------------------------------------------
# Reference management
# ---------------------------------------------------------------------------

class reference:
    """Stores a single data reference (source_id + citation string)."""

    def __init__(self, id: str, citation: str) -> None:
        self.id = id
        self.citation = citation


class bibliography:
    """Accumulates references and assigns sequential unique IDs."""

    def __init__(self) -> None:
        self._refs: dict[str, reference] = {}

    def __iter__(self):
        yield from self._refs.values()

    def add(self, name: str, citation: str) -> reference:
        if name in self._refs:
            return self._refs[name]
        num = len(self._refs) + 1
        ref = reference(id=f"E{num:02d}", citation=citation)
        self._refs[name] = ref
        return ref

    def get(self, name: str) -> reference | None:
        if name not in self._refs:
            print(f"Tried to get a reference that had not been added yet: {name}")
            return None
        return self._refs[name]


# ---------------------------------------------------------------------------
# Sub-models for structured config sections
# ---------------------------------------------------------------------------

class CODERSConfig(BaseModel):
    reference: str
    currency_year: int
    currency: str


class ATBConfig(BaseModel):
    url: str
    reference: str
    master_url: str
    master_reference: str
    year: int
    core_metric_case: str
    currency_year: int
    currency: str
    tsv_headers: dict[str, str]
    cost_invest_metric: str
    ccs_retrofit_cost_invest_metric: str


class SolarDegradationConfig(BaseModel):
    rate: float
    reference: str


class CapacityCreditsConfig(BaseModel):
    reference: str
    year: int


class SutubraVREConfig(BaseModel):
    reference: str
    year: int
    sort_solar_by: str
    sort_wind_by: str


class RenewablesNinjaConfig(BaseModel):
    reference: str


# ---------------------------------------------------------------------------
# Technology row models (replace gen_techs.csv / storage_techs.csv DataFrames)
# ---------------------------------------------------------------------------

class CANOEGenTech(BaseModel):
    code: str
    base_tech: str
    description: str
    include_new: bool
    coders_existing: str | None = None
    coders_equiv: str
    atb_display_name: str | None = None
    atb_master_sheet: str | None = None
    atb_tsv_row: str | None = None
    atb_scenario: str | None = None
    atb_min_year: int | None = None
    in_comm: str
    out_comm: str
    new_cap_batches: int | None = None
    flag: str
    tech_sets: str | None = None
    include_fuel_cost: bool = False
    no_retirement: bool = False
    ccs: float = 0


class CANOEStorageTech(BaseModel):
    code: str
    base_tech: str
    description: str
    duration: int
    include_new: bool
    coders_existing: str | None = None
    coders_equiv: str
    atb_display_name: str | None = None
    atb_master_sheet: str | None = None
    atb_tsv_row: str | None = None
    atb_scenario: str | None = None
    atb_min_year: int | None = None
    efficiency: float
    in_comm: str
    out_comm: str
    tech_sets: str | None = None
    no_retirement: bool = False
    ccs: float = 0
    include_fuel_cost: bool = False


# ---------------------------------------------------------------------------
# Top-level config model
# ---------------------------------------------------------------------------

class CANOEElectricityConfig(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # --- File paths ---
    input_files: str = 'input_files/'
    cache_dir: str = 'data_cache/'

    # --- Scalar params (from TOML) ---
    coders_api_key_file: str
    period_step: int
    model_periods: list[int]
    base_year: int
    weather_year: int
    timezone: str
    data_id_prefix: str
    data_version: str
    final_currency: str
    final_currency_year: int
    inflation_index: str
    global_discount_rate: float
    dsd_tolerance: float
    cf_tolerance: float
    sqlite_database: str = 'electricity.sqlite'
    excel_template: str = ''
    excel_output: str = 'electricity.xlsx'
    validation_behavior: str = 'error'
    existing_periods: list[int] = Field(default_factory=list)

    # --- Feature flags ---
    debug: bool = False
    force_download: bool = False
    force_wipe_database: bool = False
    full_dataset: bool = True
    include_boundary_interfaces: bool = True
    include_endogenous_interfaces: bool = True
    include_imports: bool = False
    include_emissions: bool = False
    include_existing_capacity: bool = True
    include_reserve_margin: bool = True
    include_capacity_limits: bool = False
    include_storage: bool = True
    include_provincial_demand: bool = True
    include_ccs_retrofits: bool = True
    include_tech_fuel_cost: bool = False
    include_new_wind_solar: bool = True
    clone_to_excel: bool = False
    simplify_model: bool = False
    show_plots: bool = True

    # --- Parameter groups ---
    included_emissions: dict[str, bool] = Field(default_factory=dict)
    c2a_unit: str = 'PJ/GWy'
    c2a: float = 31.536
    existing_capacity_threshold: float = 0.001
    solar_degradation: SolarDegradationConfig | None = None
    intertie_fixed_flow_note: str = ''
    capacity_factor_note: str = ''
    hydro_daily_note: str = ''
    coders: CODERSConfig
    atb: ATBConfig
    capacity_credits: CapacityCreditsConfig
    sutubra_vre: SutubraVREConfig
    renewables_ninja: RenewablesNinjaConfig
    ieso_reference: str = ''
    ieso_rel_yyyy_mmm: str = ''
    ieso_rel_peak_type: str = 'Firm'
    new_wind_techs: dict[str, str] = Field(default_factory=dict)

    # --- Typed technology lists (replace CSV DataFrames) ---
    gen_techs: list[CANOEGenTech] = Field(default_factory=list)
    storage_techs: list[CANOEStorageTech] = Field(default_factory=list)

    # --- CSV-backed DataFrames (not moved to TOML yet) ---
    commodities: pd.DataFrame = Field(default_factory=pd.DataFrame)
    regions: pd.DataFrame = Field(default_factory=pd.DataFrame)
    time: pd.DataFrame = Field(default_factory=pd.DataFrame)
    units: pd.DataFrame = Field(default_factory=pd.DataFrame)
    trans_techs: pd.DataFrame = Field(default_factory=pd.DataFrame)
    import_techs: pd.DataFrame = Field(default_factory=pd.DataFrame)
    ccs_techs: pd.DataFrame = Field(default_factory=pd.DataFrame)
    atb_master_tables: pd.DataFrame = Field(default_factory=pd.DataFrame)
    cap_limits: dict = Field(default_factory=dict)

    # --- Mutable runtime state (not serialised) ---
    refs: Any = None              # bibliography instance
    data_ids: set = Field(default_factory=set)
    provincial_demand: dict = Field(default_factory=dict)
    exs_vre_gen: dict = Field(default_factory=dict)
    atb_master_file: str = ''

    # --- Derived lookups (computed by model_validator) ---
    model_regions: list[str] = Field(default_factory=list)
    gen_techs_by_code: dict[str, CANOEGenTech] = Field(default_factory=dict)
    storage_techs_by_code: dict[str, CANOEStorageTech] = Field(default_factory=dict)
    gen_map: dict[str, str] = Field(default_factory=dict)
    storage_map: dict = Field(default_factory=dict)
    region_map: dict[str, str] = Field(default_factory=dict)
    existing_map: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode='after')
    def _compute_derived(self) -> 'CANOEElectricityConfig':
        self.gen_techs_by_code = {t.code: t for t in self.gen_techs}
        self.gen_map = {t.coders_equiv: t.code for t in self.gen_techs}
        self.storage_techs_by_code = {t.code: t for t in self.storage_techs}
        self.storage_map = {(t.coders_equiv, t.duration): t.code for t in self.storage_techs}

        if not self.regions.empty:
            self.regions['endogenous'] = self.regions['endogenous'].astype('boolean').fillna(False)
            self.model_regions = sorted(
                self.regions.loc[self.regions['endogenous']].index.unique().tolist()
            )
            for region, row in self.regions.iterrows():
                for coders_equiv in row['coders_equivs'].split('+'):
                    self.region_map[coders_equiv] = region

        for t in self.gen_techs:
            if t.coders_existing is None:
                continue
            for coders_equiv in t.coders_existing.split('+'):
                self.existing_map[coders_equiv] = t.code

        return self

    # --- Backward-compat properties ---

    @property
    def database_file(self) -> str:
        return self.sqlite_database

    @property
    def schema_file(self) -> str:
        return self.input_files + self.sqlite_schema

    @property
    def excel_template_file(self) -> str:
        return self.input_files + self.excel_template

    @property
    def excel_target_file(self) -> str:
        return self.excel_output

    # --- Factory ---

    @classmethod
    def load(cls, toml_path: str | Path = 'input_files/params.toml') -> 'CANOEElectricityConfig':
        """Load config from TOML + CSV files."""
        with open(toml_path, 'rb') as f:
            data = tomllib.load(f)

        input_files = data.pop('input_files', 'input_files/')
        cache_dir = data.pop('cache_dir', 'data_cache/')

        # Load gen_techs from CSV into Pydantic models
        gen_techs_df = pd.read_csv(input_files + 'generator_technologies.csv', index_col=0)
        gen_techs = []
        for code, row in gen_techs_df.iterrows():
            row_dict = {k: (None if pd.isna(v) else v) for k, v in row.items()}
            gen_techs.append(CANOEGenTech(code=str(code), **row_dict))

        # Load storage_techs from CSV into Pydantic models
        storage_techs_df = pd.read_csv(input_files + 'storage_technologies.csv', index_col=0)
        storage_techs = []
        for code, row in storage_techs_df.iterrows():
            row_dict = {k: (None if pd.isna(v) else v) for k, v in row.items()}
            storage_techs.append(CANOEStorageTech(code=str(code), **row_dict))

        # CCS techs (still a DataFrame — not typed yet)
        ccs_techs_df = pd.read_csv(input_files + 'ccs_retrofit_technologies.csv', index_col=0)
        ccs_techs_df = ccs_techs_df.loc[ccs_techs_df['include']]

        instance = cls(
            input_files=input_files,
            cache_dir=cache_dir,
            gen_techs=gen_techs,
            storage_techs=storage_techs,
            commodities=pd.read_csv(input_files + 'commodities.csv', index_col=0),
            regions=pd.read_csv(input_files + 'regions.csv', index_col=0),
            time=pd.read_csv(input_files + 'time.csv', index_col=0),
            units=pd.read_csv(input_files + 'units.csv', index_col=0),
            trans_techs=pd.read_csv(input_files + 'transmission_technologies.csv', index_col=0),
            import_techs=pd.read_csv(input_files + 'import_technologies.csv', index_col=0),
            ccs_techs=ccs_techs_df,
            atb_master_tables=pd.read_csv(input_files + 'atb_master_tables.csv', index_col=0),
            refs=bibliography(),
            **data,
        )

        if not os.path.exists(instance.cache_dir):
            os.mkdir(instance.cache_dir)

        for region in instance.model_regions:
            instance.exs_vre_gen[region] = np.zeros(8760)

        return instance
