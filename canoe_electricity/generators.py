"""
Aggregates data for generators
Written by Ian David Elder for the CANOE model
"""

import sqlite3
from canoe_electricity.setup import config
import canoe_electricity.coders_api as coders_api
import canoe_electricity.atb_api as atb_api
import canoe_electricity.utils as utils
import pandas as pd
import os
import traceback
import canoe_electricity.capacity_credits as capacity_credits
import canoe_electricity.capacity_factors as capacity_factors
import canoe_electricity.new_wind_solar as new_wind_solar
import canoe_electricity.constraints as constraints
from canoe_electricity.currency_conversion import conv_curr
from canoe_schema.v4_0.models import (
    Technology, Efficiency, LifetimeTech, ExistingCapacity, TimePeriod,
    StorageDuration, CapacityToActivity, CostInvest, EmissionActivity,
    CostFixed, CostVariable, LifetimeProcess, LimitActivity, Commodity,
    RampUpHourly, RampDownHourly,
)

df_generic: pd.DataFrame
df_cost: pd.DataFrame

conn: sqlite3.Connection
curs: sqlite3.Cursor



def aggregate():

    print("Aggregating generator data...")

    initialise_data()

    # Aggregate existing generation
    # Do this before new so we have existing CFs to calculate capacity credits
    df_rtv = None
    if config.include_existing_capacity:
        df_rtv = aggregate_existing_generators()
        if config.include_storage: aggregate_existing_storage()

    # Aggregate new generation
    aggregate_new_generators()
    if config.include_storage: aggregate_new_storage()

    # Aggregate CCS retrofits
    if config.include_ccs_retrofits: aggregate_ccs_retrofits(df_rtv)

    print(f"Generator data aggregated into {os.path.basename(config.database_file)}\n")



def initialise_data():

    global df_generic, df_cost

    _coders_kwargs = dict(
        cache_dir=config.cache_dir,
        force_download=config.force_download,
        api_key_file=config.input_files + config.coders_api_key_file,
        debug=config.debug,
    )

    # CODERS capital cost evolution
    df_cost, date_accessed = coders_api.get_data(end_point='generation_cost_evolution', **_coders_kwargs)
    config.refs.add('generation_cost_evolution', config.coders.reference.replace("<date>", date_accessed).replace("<table>","generation_cost_evolution"))
    df_cost['gen_type'] = df_cost['gen_type'].str.lower()
    df_cost = df_cost.set_index('gen_type')

    # CODERS generic generator data
    df_generic, date_accessed = coders_api.get_data(end_point='generation_generic', **_coders_kwargs)
    config.refs.add('generation_generic', config.coders.reference.replace("<date>", date_accessed).replace("<table>","generation_generic"))
    df_generic['gen_type'] = df_generic['gen_type'].str.lower()
    df_generic = df_generic.set_index('gen_type')



def aggregate_new_generators():

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()

    print("Aggregating new generators data...")

    """
    ##############################################################
        New generators
    ##############################################################
    """

    rtv = list()

    for tech in config.gen_techs:
        tech_code = tech.code

        if not tech.include_new: continue

        # Number of specified new capacity batches. Default 1 if not specified
        n_batches = tech.new_cap_batches if tech.new_cap_batches is not None else 1

        # Generates batched tech names like E_TECH-NEW-1, E_TECH-NEW-2...
        base_tech = tech.base_tech
        if n_batches > 1: new_techs = [f"{base_tech}-NEW-{n}" for n in range(1,n_batches+1)] # batches are specified
        else: new_techs = [f"{base_tech}-NEW"] # batches not specified

        for n in range(len(new_techs)):

            ## Technologies
            curs.executemany(*Technology.bulk_insert_or_ignore_sql([Technology(
                tech=new_techs[n], flag=tech.flag, sector='electricity',
                description=f"{tech.description} - new", data_id=utils.data_id(),
            )]))
            
            for region in config.model_regions:
                for period in config.model_periods:
                    rtv.append({'region': region, 'tech_code': tech_code, 'tech': new_techs[n], 'vint': period, 'bin': n})

    conn.commit()
    conn.close()

    df_rtv = pd.DataFrame(data=rtv)

    # Add life because capacity credits need it as a check
    df_rtv['life'] = [df_generic.loc[config.gen_techs_by_code[tc].coders_equiv, 'service_life'] for tc in df_rtv['tech_code']]

    # New wind and solar only need a small subset of generic data, then passed to provincial aggregation
    aggregate_new_wind_solar(df_rtv.loc[df_rtv['tech_code'].isin(['wind_onshore','solar'])])
    df_rtv = df_rtv.loc[~df_rtv['tech_code'].isin(['wind_onshore','solar'])] # continue with other generators

    ## CapacityCredit
    if config.include_reserve_margin: capacity_credits.aggregate_new(df_rtv)

    ## CapacityFactorTech
    capacity_factors.aggregate_new(df_rtv)

    ## Other constraints
    constraints.aggregate(df_rtv)

    # Aggregate remaining technoeconomic data
    aggregate_generators_generic(df_rtv)

    # Add reservoir storage for monthly hydro
    setup_monthly_hydro(df_rtv.loc[df_rtv['tech_code'] == 'hydro_monthly'])



def aggregate_new_storage():

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()

    print("Aggregating new storage data...")

    """
    ##############################################################
        New storage
    ##############################################################
    """

    rtv = list()

    for storage_tech in config.storage_techs:
        code = storage_tech.code

        if not storage_tech.include_new: continue

        citation = config.atb.reference.replace('<scenario>', storage_tech.atb_scenario)
        ref = config.refs.add(f"atb_storage_{storage_tech.atb_scenario}", citation)

        # Commodity data
        input_comm = config.commodities.loc[storage_tech.in_comm]
        output_comm = config.commodities.loc[storage_tech.out_comm]
        eff_units = f"({input_comm['units']}/{output_comm['units']})"

        tech = f"{storage_tech.base_tech}-NEW"

        ## Technologies
        curs.executemany(*Technology.bulk_insert_or_ignore_sql([Technology(
            tech=tech, flag='ps', sector='electricity',
            description=f"{storage_tech.description} - new", data_id=utils.data_id(),
        )]))

        for region in config.model_regions:

            ## StorageDuration
            curs.executemany(*StorageDuration.bulk_insert_or_ignore_sql([StorageDuration(
                region=region, tech=tech, duration=storage_tech.duration,
                notes="(hours of storage)", data_id=utils.data_id(region),
            )]))

            eff_rows = []
            for vint in config.model_periods:
                rtv.append({'region': region, 'tech_code': code, 'tech': tech, 'vint': vint})
                eff_rows.append(Efficiency(
                    region=region, input_comm=input_comm['commodity'],
                    tech=tech, vintage=vint, output_comm=output_comm['commodity'],
                    efficiency=storage_tech.efficiency,
                    notes=f"{eff_units} Following assumptions in NREL ATB",
                    data_source=ref.id, dq_cred=1, data_id=utils.data_id(region),
                ))
            curs.executemany(*Efficiency.bulk_insert_or_ignore_sql(eff_rows, include_nulls=True))

    conn.commit()
    conn.close()

    df_rtv = pd.DataFrame(data=rtv)

    # Add life because capacity credits need it as a check
    df_rtv['life'] = [df_generic.loc[config.storage_techs_by_code[tc].coders_equiv, 'service_life'] for tc in df_rtv['tech_code']]

    # Aggregate remaining technoeconomic data
    aggregate_storage_generic(df_rtv)
    
    return None



def aggregate_existing_generators() -> pd.DataFrame:

    print("Aggregating existing generation capacity data...")

    """
    ##############################################################
        Existing generators
    ##############################################################
    """

    df_existing, date_accessed = coders_api.get_data(
        end_point='generators',
        cache_dir=config.cache_dir,
        force_download=config.force_download,
        api_key_file=config.input_files + config.coders_api_key_file,
        debug=config.debug,
    )
    config.refs.add('generators', config.coders.reference.replace("<date>", date_accessed).replace("<table>","generators"))

    # Get CANOE technologies
    df_existing['gen_type'] = df_existing['gen_type'].str.lower()
    df_existing['tech_code'] = df_existing['gen_type'].map(config.existing_map)

    # Remove any that have not been set as an equivalent in the config csv
    for idx, row in df_existing.iterrows():
        if pd.isna(row['tech_code']):
            print(f"Existing generation technology {row['gen_type']} has not been assigned to a CANOE tech and will be skipped!")
    df_existing = df_existing.loc[~pd.isna(df_existing['tech_code'])]

    # Get CANOE regions and skip capacity in exogenous provinces
    df_existing['region'] = df_existing['operating_region'].str.lower().map(config.region_map)
    df_existing = df_existing.loc[df_existing['region'].isin(config.model_regions)]

    # Remove zero-capacity projects
    df_existing = df_existing.loc[df_existing['unit_installed_capacity'].astype(float) > 0]
    df_existing['capacity'] = df_existing['unit_installed_capacity'].astype(float) * float(config.units.loc['capacity', 'coders_conv_fact'])

    if len(df_existing) == 0:
        print("No valid existing generation capacity found.")
        return

    # Delimiter for concatenating project names together for a description
    df_existing['facilities'] = df_existing['generation_facility_code'] + ',' + df_existing['capacity'].astype(str) + ';' # for calculating CFs
    df_existing['description'] = df_existing['generation_facility_name'] + ' - '

    # Vintage is last renewal year if available otherwise start year
    df_existing['vint'] = df_existing[['start_year','previous_renewal_year']].max(axis=1)

    # Remove any existing capacity after first model period
    df_existing = df_existing.loc[df_existing['vint'] < config.model_periods[0]]

    # Round vintages to period step but before first model period
    step = config.period_step
    df_existing['vint'] = [min(config.model_periods[0] - 1, step * round(vint/step)) for vint in df_existing['vint']]

    # If no retirement then override vintage to one year before first model period
    df_existing['vint'] = df_existing['vint'].mask([config.gen_techs_by_code[tc].no_retirement for tc in df_existing['tech_code']], config.model_periods[0] - 1)

    # Aggregate existing capacities and projects by region, tech, vintage
    df_rtv = df_existing.groupby(['region','tech_code','vint']).sum(numeric_only=False).reset_index()
    df_rtv['description'] = df_rtv['description'].str.removesuffix(' - ') # one excess delimiter after concatenating

    # Add -EXS tag
    df_rtv['tech'] = [f"{config.gen_techs_by_code[tc].base_tech}-EXS" for tc in df_rtv['tech_code']]

    # Add life because capacity credits need it as a check
    df_rtv['life'] = [df_generic.loc[config.gen_techs_by_code[tc].coders_equiv, 'service_life'] for tc in df_rtv['tech_code']]

    # Remove any existing capacity that's below threshold or wouldn't reach the first model period
    df_rtv = df_rtv.loc[df_rtv['vint'] + df_rtv['life'] > config.model_periods[0]]
    df_rtv = df_rtv.loc[df_rtv['capacity'] > config.existing_capacity_threshold]

    ## CapacityFactorTech
    capacity_factors.aggregate_existing(df_rtv)

    ## CapacityCredit
    if config.include_reserve_margin: capacity_credits.aggregate_existing(df_rtv)

    ## Other constraints
    constraints.aggregate(df_rtv)

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()

    # Add technologies
    tech_rows = []
    for _idx, row in df_rtv[['tech_code','tech','description']].drop_duplicates().iterrows():
        tech_config = config.gen_techs_by_code[row['tech_code']]
        tech_rows.append(Technology(
            tech=row['tech'], flag=tech_config.flag, sector='electricity',
            description=f"{tech_config.description} - {row['description']} - existing",
            data_id=utils.data_id(),
        ))
    if tech_rows:
        curs.executemany(*Technology.bulk_insert_or_ignore_sql(tech_rows, include_nulls=True))

    # Iterate over aggregated existing capacity
    ec_rows = []
    for _idx, row in df_rtv.iterrows():
        tech_config = config.gen_techs_by_code[row['tech_code']]
        if tech_config.no_retirement: note = f"no retirement so aggregated to last existing vintage - {utils.string_cleaner(row['description'])}"
        else: note = f"aggregated to {step}-yearly vintages - {utils.string_cleaner(row['description'])}"
        ec_rows.append(ExistingCapacity(
            region=row['region'], tech=row['tech'], vintage=row['vint'],
            capacity=row['capacity'], units=f"({config.units.loc['capacity', 'units']})",
            notes=note, data_source=config.refs.get('generators').id, dq_cred=2,
            data_id=utils.data_id(row['region']),
        ))
    if ec_rows:
        curs.executemany(*ExistingCapacity.bulk_insert_or_ignore_sql(ec_rows, include_nulls=True))

    ## time_periods
    tp_rows = [TimePeriod(period=int(vint), flag='e') for vint in df_rtv['vint'].unique()]
    if tp_rows:
        curs.executemany(*TimePeriod.bulk_insert_or_ignore_sql(tp_rows, include_nulls=True))
        
    conn.commit()
    conn.close()
    
    # Aggregate remaining technoeconomic data
    aggregate_generators_generic(df_rtv[['region','tech_code','tech','vint']].copy())

    # Add reservoir storage for monthly hydro
    setup_monthly_hydro(df_rtv.loc[df_rtv['tech_code'] == 'hydro_monthly'])

    return df_rtv



def aggregate_existing_storage():

    print("Aggregating existing storage capacity data...")
    
    """
    ##############################################################
        Existing storage
    ##############################################################
    """

    df_existing, date_accessed = coders_api.get_data(
        end_point='storage',
        cache_dir=config.cache_dir,
        force_download=config.force_download,
        api_key_file=config.input_files + config.coders_api_key_file,
        debug=config.debug,
    )
    citation = config.coders.reference.replace("<date>", date_accessed).replace("<table>","storage")
    config.refs.add('storage', citation)

    # Maps all coders existing storage types to canoe techs (same as config.storage_map)
    existing_map = dict()
    for st in config.storage_techs:
        if st.coders_existing is None: continue
        for coders_equiv in st.coders_existing.split("+"):
            existing_map[(coders_equiv, st.duration)] = st.code

    # Get CANOE technologies
    df_existing['storage_type'] = df_existing['storage_type'].str.lower()
    df_existing['storage_duration'] = round(df_existing['storage_duration'].astype(float)).astype(int)
    df_existing['tech_code'] = pd.MultiIndex.from_frame(df_existing[['storage_type','storage_duration']]).map(existing_map)

    # Remove any that have not been set as an equivalent in the config csv
    for idx, row in df_existing.iterrows():
        if pd.isna(row['tech_code']):
            print(f"Existing storage technology {row['storage_type']} {row['storage_duration']}-hour has no equivalent defined in config tables and will be skipped!")
    df_existing = df_existing.loc[~pd.isna(df_existing['tech_code'])]

    # Get CANOE regions and skip capacity in exogenous provinces
    df_existing['region'] = df_existing['operating_region'].str.lower().map(config.region_map)
    df_existing = df_existing.loc[df_existing['region'].isin(config.model_regions)]

    # Remove zero-capacity projects
    df_existing = df_existing.loc[df_existing['storage_capacity'] > 0]

    if len(df_existing) == 0:
        print("No valid existing storage capacity found.")
        return
    
    # Existing capacity converted 
    df_existing['capacity'] = df_existing['storage_capacity'].astype(float) * float(config.units.loc['capacity', 'coders_conv_fact'])

    # Delimiter for concatenating project names together for a description
    df_existing['description'] = df_existing['storage_facility_name'] + ' - '

    # Vintage is last renewal year if available otherwise start year
    df_existing['vint'] = df_existing[['start_year','previous_renewal_year']].max(axis=1)

    # Remove any existing capacity after first model period
    df_existing = df_existing.loc[df_existing['vint'] < config.model_periods[0]]

    # Round vintages to period step but before first model period
    step = config.period_step
    df_existing['vint'] = [min(config.model_periods[0] - 1, step * round(vint/step)) for vint in df_existing['vint']]

    # If no retirement then override vintage to last before first model period
    df_existing['vint'] = df_existing['vint'].mask([config.storage_techs_by_code[tc].no_retirement for tc in df_existing['tech_code']], config.model_periods[0] - 1)

    # Aggregate existing capacities and projects by region, tech, vintage
    df_rtdv = df_existing.groupby(['region','tech_code','storage_duration','vint']).sum(numeric_only=False).reset_index()
    df_rtdv['description'] = df_rtdv['description'].str.removesuffix(' - ') # one excess delimiter after concatenating

    # Add life because capacity credits need it as a check
    df_rtdv['life'] = [df_generic.loc[config.storage_techs_by_code[tc].coders_equiv, 'service_life'] for tc in df_rtdv['tech_code']]

    # Remove any existing capacity that's below threshold or wouldn't reach the first model period
    df_rtdv = df_rtdv.loc[df_rtdv['vint'] + df_rtdv['life'] > config.model_periods[0]]
    df_rtdv = df_rtdv.loc[df_rtdv['capacity'] > config.existing_capacity_threshold]

    # Add -EXS tag
    df_rtdv['tech'] = [f"{config.storage_techs_by_code[tc].base_tech}-EXS" for tc in df_rtdv['tech_code']]

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()

    # Iterate over aggregated existing capacity
    tech_rows = []
    eff_rows = []
    ec_rows = []
    sd_rows = []
    for _idx, row in df_rtdv.iterrows():

        # Tech configuration data
        storage_config = config.storage_techs_by_code[row['tech_code']]
        ref = config.refs.add(f"atb_storage_{storage_config.atb_scenario}", config.atb.reference.replace('<scenario>', storage_config.atb_scenario))

        # Commodity data
        input_comm = config.commodities.loc[storage_config.in_comm]
        output_comm = config.commodities.loc[storage_config.out_comm]
        eff_units = f"({input_comm['units']}/{output_comm['units']})"

        if storage_config.no_retirement: note = f"no retirement so aggregated to last existing vintage - {utils.string_cleaner(row['description'])}"
        else: note = f"aggregated to {step}-yearly vintages - {utils.string_cleaner(row['description'])}"

        tech_rows.append(Technology(
            tech=row['tech'], flag='ps', sector='electricity',
            description=f"{storage_config.description} - {row['description']} - existing",
            data_id=utils.data_id(),
        ))
        eff_rows.append(Efficiency(
            region=row['region'], input_comm=input_comm['commodity'],
            tech=row['tech'], vintage=row['vint'], output_comm=output_comm['commodity'],
            efficiency=storage_config.efficiency,
            notes=f"{eff_units} Following assumptions in NREL ATB",
            data_source=ref.id, dq_cred=1, data_id=utils.data_id(row['region']),
        ))
        ec_rows.append(ExistingCapacity(
            region=row['region'], tech=row['tech'], vintage=row['vint'],
            capacity=row['capacity'], units=f"({config.units.loc['capacity', 'units']})",
            notes=note, data_source=config.refs.get('storage').id, dq_cred=2,
            data_id=utils.data_id(row['region']),
        ))
        sd_rows.append(StorageDuration(
            region=row['region'], tech=row['tech'], duration=row['storage_duration'],
            notes="(hours of storage)", data_source=config.refs.get('storage').id,
            data_id=utils.data_id(row['region']),
        ))

    if tech_rows: curs.executemany(*Technology.bulk_insert_or_ignore_sql(tech_rows, include_nulls=True))
    if eff_rows: curs.executemany(*Efficiency.bulk_insert_or_ignore_sql(eff_rows, include_nulls=True))
    if ec_rows: curs.executemany(*ExistingCapacity.bulk_insert_or_ignore_sql(ec_rows, include_nulls=True))
    if sd_rows: curs.executemany(*StorageDuration.bulk_insert_or_ignore_sql(sd_rows, include_nulls=True))

    ## time_periods
    tp_rows = [TimePeriod(period=int(vint), flag='e') for vint in df_rtdv['vint'].unique()]
    if tp_rows:
        curs.executemany(*TimePeriod.bulk_insert_or_ignore_sql(tp_rows, include_nulls=True))
        

    conn.commit()
    conn.close()

    # Aggregate remaining technoeconomic data
    aggregate_storage_generic(df_rtdv)



def aggregate_generators_generic(df_rtv: pd.DataFrame):

    global conn, curs

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()

    # Just need region and tech indices for this data
    for _idx, row in df_rtv[['region','tech_code','tech']].drop_duplicates().iterrows():

        tech_config = config.gen_techs_by_code[row['tech_code']]

        aggregate_rt_all(row['region'], row['tech'], tech_config)

        # Take from ATB if an ATB equivalent is defined, otherwise CODERS
        if tech_config.atb_display_name is None: aggregate_rt_coders(row['region'], row['tech'], tech_config)
        else: aggregate_rt_atb(row['region'], row['tech'], tech_config)

    # Also need vintage index for this data
    for _idx, row in df_rtv.iterrows():

        tech_config = config.gen_techs_by_code[row['tech_code']]

        # Take from ATB if an ATB equivalent is defined, otherwise CODERS
        if tech_config.atb_display_name is None: aggregate_rtv_coders(row['region'], row['tech'], row['vint'], tech_config)
        else: aggregate_rtv_atb(row['region'], row['tech'], row['vint'], tech_config)

    conn.commit()
    conn.close()
    


def aggregate_storage_generic(df_rtv: pd.DataFrame):

    global conn, curs

    ## CapacityCredit
    # Note: no longer used after dynamic reserve margin rework
    # if config.params['include_reserve_margin']: capacity_credits.aggregate_storage(df_rtv)

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()

    # Just need region and tech indices for this data
    for _idx, row in df_rtv[['region','tech_code','tech']].drop_duplicates().iterrows():

        storage_config = config.storage_techs_by_code[row['tech_code']]

        aggregate_rt_all(row['region'], row['tech'], storage_config)

        # Take from ATB if an ATB equivalent is defined, otherwise CODERS
        if storage_config.atb_display_name is None: aggregate_rt_coders(row['region'], row['tech'], storage_config)
        else: aggregate_rt_atb(row['region'], row['tech'], storage_config)

    # Also need vintage index for this data
    for _idx, row in df_rtv.iterrows():

        storage_config = config.storage_techs_by_code[row['tech_code']]

        # Take from ATB if an ATB equivalent is defined, otherwise CODERS
        if storage_config.atb_display_name is None: aggregate_rtv_coders(row['region'], row['tech'], row['vint'], storage_config)
        else: aggregate_rtv_atb(row['region'], row['tech'], row['vint'], storage_config)

    conn.commit()
    conn.close()



# New wind and solar only need a subset of the generic data, rest is provincial
def aggregate_new_wind_solar(df_rtv: pd.DataFrame):

    global conn, curs

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()

    # Just need region and tech indices for this data
    for _idx, row in df_rtv[['region','tech_code','tech']].drop_duplicates().iterrows():

        tech_config = config.gen_techs_by_code[row['tech_code']]

        aggregate_rt_all(row['region'], row['tech'], tech_config)

    conn.commit()
    conn.close()

    new_wind_solar.aggregate(df_rtv)



## Aggregates some common data where indexed by region, tech
def aggregate_rt_all(region, tech, tech_config):

    # Using some generic CODERS data
    coders_gen = df_generic.loc[tech_config.coders_equiv]

    # Add to specified sets
    if tech_config.tech_sets is not None:
        for tech_set in tech_config.tech_sets.split(','):
            curs.execute(f"""UPDATE technology SET {tech_set}=1 WHERE tech == '{tech}'""")


    ## LifetimeTech
    if tech_config.no_retirement:
        lt_row = LifetimeTech(region=region, tech=tech, lifetime=100, notes="(y) no retirement", data_id=utils.data_id(region))
    else:
        lt_row = LifetimeTech(
            region=region, tech=tech, lifetime=coders_gen['service_life'],
            notes=f"(y) {tech_config.coders_equiv} service life years",
            data_source=config.refs.get('generation_generic').id, dq_cred=2,
            data_id=utils.data_id(region),
        )
    curs.executemany(*LifetimeTech.bulk_insert_or_ignore_sql([lt_row], include_nulls=True))

    ## CapacityToActivity
    curs.executemany(*CapacityToActivity.bulk_insert_or_ignore_sql([CapacityToActivity(
        region=region, tech=tech, c2a=config.c2a,
        notes=f"({config.c2a_unit})", data_id=utils.data_id(region),
    )]))
    


def aggregate_rt_atb(region, tech, tech_config):

    """
    ##############################################################
        Generic data from NREL ATB, indexed by region, tech
    ##############################################################
    """

    # CODERS data as a backup where not available in ATB
    tsv, tsv_note = atb_api.load_tsv(
        sheet=tech_config.atb_master_sheet,
        row=tech_config.atb_tsv_row,
        master_file=config.atb_master_file,
        master_tables=config.atb_master_tables,
        cache_dir=config.cache_dir,
        headers_map=config.atb.tsv_headers,
        force_download=config.force_download,
    )
    if tsv is not None:
        config.refs.add(tsv_note, config.atb.master_reference.replace('<sheet>', tsv_note))


    ## RampUp and RampDown
    # TODO need some actual hourly values for this
    # Take from ATB tsv table if available, otherwise use CODERS
    if tsv is None: aggregate_ramp_rt_coders(region, tech, tech_config)
    else:
        ramp_rate = tsv['ramp_rate_%_min']

        if pd.isna(ramp_rate): aggregate_ramp_rt_coders(region, tech, tech_config)
        else:
            ramp_rate = config.units.loc['ramp_rate', 'atb_conv_fact'] * float(ramp_rate)

            if 0.0 < ramp_rate < 1.0:

                note = f"({config.units.loc['ramp_rate', 'units']}) {tsv_note} ramp_rate_%_min times {config.units.loc['ramp_rate', 'coders_conv_fact']}"

                _kwargs = dict(region=region, tech=tech, rate=ramp_rate, notes=note, data_source=config.refs.get(tsv_note).id, dq_cred=1, data_id=utils.data_id(region))
                curs.executemany(*RampUpHourly.bulk_insert_or_ignore_sql([RampUpHourly(**_kwargs)], include_nulls=True))
                curs.executemany(*RampDownHourly.bulk_insert_or_ignore_sql([RampDownHourly(**_kwargs)], include_nulls=True))


    ## CostInvest
    if not utils.is_exs(tech):
        for vint in config.model_periods:

            metric = config.atb.cost_invest_metric
            cost_invest, note = utils.atb_data(
                tech_config,
                core_metric_parameter=metric,
                core_metric_variable=int(max(
                    tech_config.atb_min_year,
                    utils.data_year(vint)
                ))
            )
            cost_invest = conv_curr(float(cost_invest.iloc[0]), config.atb.currency_year, config.atb.currency)
            
            if cost_invest != 0 and not pd.isna(cost_invest):
                curs.executemany(*CostInvest.bulk_insert_or_ignore_sql([CostInvest(
                    region=region, tech=tech, vintage=vint, cost=cost_invest,
                    units=f"({config.units.loc['cost_invest', 'units']})",
                    notes=note, data_source=config.refs.get('atb').id, dq_cred=1,
                    data_id=utils.data_id(region),
                )]))



## Aggregates data from NREL ATB where indexed by region, tech, vintage
def aggregate_rtv_atb(region, tech, vint, tech_config):

    """
    ##############################################################
        Generic data from NREL ATB, indexed by region, tech, vint
    ##############################################################
    """
    # TODO output captured co2?

    # CODERS data as a backup where not available in ATB
    coders_gen = df_generic.loc[tech_config.coders_equiv]
    tsv, tsv_note = atb_api.load_tsv(
        sheet=tech_config.atb_master_sheet,
        row=tech_config.atb_tsv_row,
        master_file=config.atb_master_file,
        master_tables=config.atb_master_tables,
        cache_dir=config.cache_dir,
        headers_map=config.atb.tsv_headers,
        force_download=config.force_download,
    )
    if tsv is not None:
        config.refs.add(tsv_note, config.atb.master_reference.replace('<sheet>', tsv_note))

    # Commodity data
    input_comm = config.commodities.loc[tech_config.in_comm]
    output_comm = config.commodities.loc[tech_config.out_comm]
    eff_units = f"({input_comm['units']}/{output_comm['units']})"

    # If configured for ccs retrofits change output commodity to an intermediary
    data_id = utils.data_id(region)
    if tech_config.code in config.ccs_techs['generator'].values and config.include_ccs_retrofits:
        output_comm = output_comm.copy()
        output_comm['commodity'] += f"_{tech_config.code}"


    ## Efficiency
    # Efficiency is arbitrary for ethos (e.g. renewables)
    if "ethos" in input_comm['commodity']:

        eff = 1

        curs.executemany(*Efficiency.bulk_insert_or_ignore_sql([Efficiency(
            region=region, input_comm=input_comm['commodity'],
            tech=tech, vintage=vint, output_comm=output_comm['commodity'],
            efficiency=1, notes=f"{eff_units} dummy input so arbitrary",
            data_id=data_id,
        )]))

    else:
        eff, note = utils.atb_data(tech_config, core_metric_parameter='Heat Rate', core_metric_variable=int(max(tech_config.atb_min_year,utils.data_year(vint))))

        # If eff is None should be a storage tech and efficiency is already added so skip
        if eff is not None:

            # Heat rate to % efficiency
            eff = 1 / (config.units.loc['heat_rate', 'atb_conv_fact'] * float(eff.iloc[0]))

            curs.executemany(*Efficiency.bulk_insert_or_ignore_sql([Efficiency(
                region=region, input_comm=input_comm['commodity'],
                tech=tech, vintage=vint, output_comm=output_comm['commodity'],
                efficiency=eff, notes=f"{eff_units} {note}",
                data_source=config.refs.get('atb').id, dq_cred=1,
                data_id=data_id,
            )]))


    ## EmissionActivity
    if (tech_config.ccs or config.include_emissions) and eff is not None:

        if tsv is None: # no ATB emissions data so use CODERS
            aggregate_emissions_rtv_coders(region, tech, vint, input_comm, output_comm, coders_gen, tech_config)
        
        else: # use ATB emissions data
            for emis in ['co2','so2','nox','hg']:

                emis_act = config.units.loc[f"{emis}_emissions", 'atb_conv_fact'] * float(tsv[f"emissions_{emis}_lbs_MMBtu"]) / eff
                emis_comm = config.commodities.loc[emis]
                emis_units = f"({emis_comm['units']}/{output_comm['units']})"

                # Emissions are accounted upstream so negative emissions here to offset
                if not config.include_emissions:
                    if emis != 'co2': continue
                    emis_act = -emis_act * (tech_config.ccs) / (1 - tech_config.ccs)

                if emis_act != 0 and not pd.isna(emis_act):
                    curs.executemany(*EmissionActivity.bulk_insert_or_ignore_sql([EmissionActivity(
                        region=region, emis_comm=emis_comm['commodity'], input_comm=input_comm['commodity'],
                        tech=tech, vintage=vint, output_comm=output_comm['commodity'],
                        activity=emis_act, units=emis_units,
                        notes=f"{tsv_note} - emissions_{emis}_lbs_MMBtu",
                        data_source=config.refs.get(tsv_note).id, dq_cred=1, data_id=data_id,
                    )]))
                    # Duplicate co2 for co2e
                    if emis == 'co2':
                        emis_comm = config.commodities.loc['co2e']
                        emis_units = f"({emis_comm['units']}/{output_comm['units']})"
                        curs.executemany(*EmissionActivity.bulk_insert_or_ignore_sql([EmissionActivity(
                            region=region, emis_comm=emis_comm['commodity'], input_comm=input_comm['commodity'],
                            tech=tech, vintage=vint, output_comm=output_comm['commodity'],
                            activity=emis_act, units=emis_units,
                            notes=f"{tsv_note} - emissions_{emis}_lbs_MMBtu",
                            data_source=config.refs.get(tsv_note).id, dq_cred=1, data_id=data_id,
                        )]))


    # Indexed by period and vintage
    for period in config.model_periods:
        
        if vint > period or vint + coders_gen['service_life'] <= period: continue
        

        ## CostFixed
        cost_fixed, note = utils.atb_data(tech_config, core_metric_parameter='Fixed O&M', core_metric_variable=int(max(tech_config.atb_min_year,utils.data_year(vint))))
        cost_fixed = config.units.loc['cost_fixed', 'atb_conv_fact'] * float(cost_fixed.iloc[0])
        cost_fixed = conv_curr(cost_fixed, config.atb.currency_year, config.atb.currency)

        if cost_fixed != 0 and not pd.isna(cost_fixed):
            curs.executemany(*CostFixed.bulk_insert_or_ignore_sql([CostFixed(
                region=region, period=period, tech=tech, vintage=vint,
                cost=cost_fixed, units=f"({config.units.loc['cost_fixed', 'units']})",
                notes=note, data_source=config.refs.get('atb').id, dq_cred=1,
                data_id=utils.data_id(region),
            )]))


        ## CostVariable
        cost_variable, var_note = utils.atb_data(tech_config, core_metric_parameter='Variable O&M', core_metric_variable=int(max(tech_config.atb_min_year,utils.data_year(vint))))
        cost_fuel, fuel_note = utils.atb_data(tech_config, core_metric_parameter='Fuel', core_metric_variable=utils.data_year(period))

        # If asking for fuel costs and ATB doesn't have it, use CODERS for all variable cost (can't mix currencies)
        if config.include_tech_fuel_cost and tech_config.include_fuel_cost and cost_fuel is None:
            aggregate_cost_var_rtvp_coders(region, tech, vint, period, coders_gen, tech_config)

        # Otherwise take Variable O&M from the ATB if it has it
        elif cost_variable is not None:

            cost_variable = config.units.loc['cost_variable', 'atb_conv_fact'] * float(cost_variable.iloc[0])

            if config.include_tech_fuel_cost and tech_config.include_fuel_cost:
                cost_variable += config.units.loc['cost_fuel', 'atb_conv_fact'] * float(cost_fuel.iloc[0])
                note = f"variable o&m plus fuel cost - {var_note} - {fuel_note}"
            else: note = var_note

            cost_variable = conv_curr(cost_variable, config.atb.currency_year, config.atb.currency)

            if cost_variable != 0 and not pd.isna(cost_variable):
                curs.executemany(*CostVariable.bulk_insert_or_ignore_sql([CostVariable(
                    region=region, period=period, tech=tech, vintage=vint,
                    cost=cost_variable, units=f"({config.units.loc['cost_variable', 'units']})",
                    notes=note, data_source=config.refs.get('atb').id, dq_cred=1,
                    data_id=utils.data_id(region),
                )]))



## Aggregates data from CODERS where indexed by region, tech
def aggregate_rt_coders(region, tech, tech_config):

    """
    ##############################################################
        Generic data from CODERS, indexed by region, tech
    ##############################################################
    """
    

    ## RampUp and RampDown
    aggregate_ramp_rt_coders(region, tech, tech_config)


    ## CostInvest
    cost_invest = df_cost.loc[tech_config.coders_equiv]
    if not utils.is_exs(tech):
        for vint in config.model_periods:

            cost = config.units.loc['cost_invest', 'coders_conv_fact'] * float(cost_invest[f"{utils.data_year(vint)}_CAD_per_kW"])
            cost = conv_curr(cost, config.coders.currency_year, config.coders.currency)
            # 'cost_invest_notes, data_cost_invest, data_cost_year, data_curr,' -> 'cost_invest_notes, data_cost_invest, data_cost_year, data_curr,'
            curs.executemany(*CostInvest.bulk_insert_or_ignore_sql([CostInvest(
                region=region, tech=tech, vintage=vint, cost=cost,
                units=f"({config.units.loc['cost_invest', 'units']})",
                notes=f"{tech_config['coders_equiv']} CAD_per_kW by vintage",
                data_source=config.refs.get('generation_cost_evolution').id, dq_cred=2,
                data_id=utils.data_id(region),
            )]))



def aggregate_ramp_rt_coders(region, tech, tech_config):

    coders_gen = df_generic.loc[tech_config.coders_equiv]
    ramp_rate = coders_gen['ramp_rate_percent_per_min']

    if not pd.isna(ramp_rate):

        ramp_rate = config.units.loc['ramp_rate', 'coders_conv_fact'] * float(ramp_rate)

        if 0.0 < ramp_rate < 1.0:

            note = f"({config.units.loc['ramp_rate', 'units']}) {tech_config.coders_equiv} ramp_rate_percent_per_min times {config.units.loc['ramp_rate', 'coders_conv_fact']}"

            _kwargs = dict(region=region, tech=tech, rate=ramp_rate, notes=note, data_source=config.refs.get('generation_generic').id, dq_cred=2, data_id=utils.data_id(region))
            curs.executemany(*RampUpHourly.bulk_insert_or_ignore_sql([RampUpHourly(**_kwargs)], include_nulls=True))
            curs.executemany(*RampDownHourly.bulk_insert_or_ignore_sql([RampDownHourly(**_kwargs)], include_nulls=True))



## Aggregates data from CODERS where indexed by region, tech, vintage
def aggregate_rtv_coders(region, tech, vint, tech_config):

    """
    ##############################################################
        Generic data from CODERS, indexed by region, tech, vint
    ##############################################################
    """

    # Use coders equivalent for generic data
    coders_gen = df_generic.loc[tech_config.coders_equiv]

    # Commodity data
    input_comm = config.commodities.loc[tech_config.in_comm]
    output_comm = config.commodities.loc[tech_config.out_comm]
    eff_units = f"({input_comm['units']}/{output_comm['units']})"

    # If configured for ccs retrofits change output commodity to an intermediary
    data_id = utils.data_id(region)
    if tech_config.code in config.ccs_techs['generator'].values and config.include_ccs_retrofits:
        output_comm = output_comm.copy()
        output_comm['commodity'] += f"_{tech_config.code}"


    ## Efficiency
    # Efficiency is arbitrary for ethos (e.g. renewables)
    if "ethos" in input_comm['commodity']:

        curs.executemany(*Efficiency.bulk_insert_or_ignore_sql([Efficiency(
            region=region, input_comm=input_comm['commodity'],
            tech=tech, vintage=vint, output_comm=output_comm['commodity'],
            efficiency=1, notes=f"{eff_units} dummy input so arbitrary",
            data_id=data_id,
        )]))

    # CODERS database provides an efficiency
    elif not pd.isna(coders_gen['efficiency']):

        curs.executemany(*Efficiency.bulk_insert_or_ignore_sql([Efficiency(
            region=region, input_comm=input_comm['commodity'],
            tech=tech, vintage=vint, output_comm=output_comm['commodity'],
            efficiency=coders_gen['efficiency'],
            notes=f"{eff_units} {tech_config.coders_equiv} efficiency",
            data_source=config.refs.get('generation_generic').id, dq_cred=2,
            data_id=data_id,
        )]))


    ## EmissionActivity
    if tech_config.ccs or config.include_emissions:
        aggregate_emissions_rtv_coders(region, tech, vint, input_comm, output_comm, coders_gen, tech_config)


    # Indexed by period and vintage
    for period in config.model_periods:

        if vint > period or vint + coders_gen['service_life'] <= period: continue


        ## CostFixed
        cost_fixed = config.units.loc['cost_fixed', 'coders_conv_fact'] * coders_gen['fixed_om_costs']
        cost_fixed = conv_curr(cost_fixed, config.coders.currency_year, config.coders.currency)

        if cost_fixed != 0 and not pd.isna(cost_fixed):
            curs.executemany(*CostFixed.bulk_insert_or_ignore_sql([CostFixed(
                region=region, period=period, tech=tech, vintage=vint,
                cost=cost_fixed, units=f"({config.units.loc['cost_fixed', 'units']})",
                notes=f"{tech_config.coders_equiv} fixed_om_costs",
                data_source=config.refs.get('generation_cost_evolution').id, dq_cred=2,
                data_id=utils.data_id(region),
            )]))
        
        ## CostVariable
        aggregate_cost_var_rtvp_coders(region, tech, vint, period, coders_gen, tech_config)



def aggregate_emissions_rtv_coders(region, tech, vint, input_comm, output_comm, coders_gen, tech_config):

    emis_act = config.units.loc['co2_emissions', 'coders_conv_fact'] * float(coders_gen['carbon_emissions'])
    emis_comm = config.commodities.loc['co2e']
    emis_units = f"({emis_comm['units']}/{output_comm['units']})"

    # Emissions are accounted upstream so negative emissions here to offset
    if not config.include_emissions:
        emis_act = -emis_act * (tech_config.ccs) / (1 - tech_config.ccs)

    if emis_act != 0 and not pd.isna(emis_act):
        curs.executemany(*EmissionActivity.bulk_insert_or_ignore_sql([EmissionActivity(
            region=region, emis_comm=emis_comm['commodity'], input_comm=input_comm['commodity'],
            tech=tech, vintage=vint, output_comm=output_comm['commodity'],
            activity=emis_act, units=emis_units,
            notes=f"{tech_config.coders_equiv} carbon_emissions",
            data_source=config.refs.get('generation_generic').id, dq_cred=2,
            data_id=utils.data_id(region),
        )]))



def aggregate_cost_var_rtvp_coders(region, tech, vint, period, coders_gen, tech_config):

    cost_variable = config.units.loc['cost_variable', 'coders_conv_fact'] * float(coders_gen['variable_om_costs'])
    description = f"{tech_config.coders_equiv} variable_om_costs"

    if config.include_tech_fuel_cost and tech_config.include_fuel_cost:

        fuel_price = coders_gen['average_fuel_price_CAD_per_MMBtu']

        if not pd.isna(fuel_price) and coders_gen['efficiency'] is not None:
            cost_variable += config.units.loc['cost_fuel', 'coders_conv_fact'] * float(fuel_price) / float(coders_gen['efficiency'])
            description += " plus average_fuel_price_CAD_per_MMBtu to M$/PJ and divided by efficiency"

    if cost_variable != 0 and not pd.isna(cost_variable):

        cost_variable = conv_curr(cost_variable, config.coders.currency_year, config.coders.currency)

        curs.executemany(*CostVariable.bulk_insert_or_ignore_sql([CostVariable(
            region=region, period=period, tech=tech, vintage=vint,
            cost=cost_variable, units=f"({config.units.loc['cost_variable', 'units']})",
            notes=description, data_source=config.refs.get('generation_generic').id,
            dq_cred=2, data_id=utils.data_id(region),
        )]))



"""
##############################################################
    CCS retrofits
##############################################################
"""

## Generic data for the retrofit tech
# This gets a little messy because we need to check that there is capacity available to retrofit in each region and period
def aggregate_ccs_retrofits(df_rtv_all: pd.DataFrame):

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()
    
    print("Aggregating CCS retrofits data...")

    if not config.include_emissions:
        print("Including ccs retrofits but not other emissions. Assuming emissions are accounted upstream.")

    # Get region-tech-vint sets for techs with CCS retrofits
    if df_rtv_all is None: df_rtv_all = pd.DataFrame(columns=['region','tech_code','vint'])
    df_rtv_ccs = df_rtv_all.loc[df_rtv_all['tech_code'].isin(config.ccs_techs['generator'])]

    for ccs_code, ccs_config in config.ccs_techs.iterrows():
        
        # Get the retrofitted generator config and its coders generic data
        gen_config = config.gen_techs_by_code[ccs_config['generator']]
        coders_gen: pd.Series = df_generic.loc[gen_config.coders_equiv]

        # Existing capacity for this retrofittable generator
        df_rtv_gen = df_rtv_ccs.loc[df_rtv_ccs['tech_code'] == gen_config.code]

        # If including new capacity, add rtv sets for all future periods, regions
        if gen_config.include_new:
            df_new = pd.DataFrame([{'region':r, 'tech_code':gen_config.code, 'vint':v}
                                for r in config.model_regions
                                for v in config.model_periods])
            df_rtv_gen = pd.concat([df_rtv_gen, df_new])

        # Make sure there can be a generator of this type to retrofit in any region otherwise add nothing
        if len(df_rtv_gen) == 0: continue

        try:
            tsv, tsv_note = atb_api.load_tsv(
                sheet=gen_config.atb_master_sheet,
                row=gen_config.atb_tsv_row,
                master_file=config.atb_master_file,
                master_tables=config.atb_master_tables,
                cache_dir=config.cache_dir,
                headers_map=config.atb.tsv_headers,
                force_download=config.force_download,
            )
            if tsv is not None:
                config.refs.add(tsv_note, config.atb.master_reference.replace('<sheet>', tsv_note))
            gen_emis = config.units.loc[f"co2_emissions", 'atb_conv_fact'] * float(tsv["emissions_co2_lbs_MMBtu"]) \
                * float(tsv["heat_rate_MMBtu_MWh"]) * config.units.loc[f"heat_rate", 'atb_conv_fact']
        except Exception as e:
            gen_emis = config.units.loc['co2_emissions', 'coders_conv_fact'] * float(coders_gen['carbon_emissions']) \
                / float(coders_gen['efficiency'])
            print(traceback.format_exc())
            print(f"\nTrying to aggregate {ccs_code} but could not get CO2 emissions of retrofitted generator {gen_config.code} from ATB workbook."
                  f"\nWill use CODERS emissions data for now but this will be capturing CO2-equivalent emissions!")

        if gen_emis <= 0:
            print(f"Tried to aggregate {ccs_code} but retrofitted generator {gen_config.code} had {gen_emis} CO2 emissions!")
            continue
        
        # Commodities data
        output_comm = config.commodities.loc[gen_config.out_comm]
        eff_units = f"({output_comm['units']}/{output_comm['units']})"

        # Create new intermediate commodity between generator and retrofit
        input_comm = output_comm.copy()
        input_comm['commodity'] += f"_{gen_config.code}"
        input_comm['description'] += f" from {gen_config.description}"

        # Name of CCS retrofit bypass tech
        bypass_tech = f"{gen_config.base_tech}_RFIT_BYPASS"

        ## Commodities
        curs.executemany(*Commodity.bulk_insert_or_ignore_sql([Commodity(
            name=input_comm['commodity'], flag='p',
            description=f"({input_comm['units']}) intermediate commodity going either to {ccs_config['tech']} or straight to {output_comm['commodity']}",
            data_id=utils.data_id(),
        )]))


        ## Technologies
        # Bypass tech
        curs.executemany(*Technology.bulk_insert_or_ignore_sql([Technology(
            tech=bypass_tech, flag='p', sector='electricity', unlim_cap=1,
            description="dummy bypass for ccs retrofit", data_id=utils.data_id(),
        )]))

        # Retrofit tech
        curs.executemany(*Technology.bulk_insert_or_ignore_sql([Technology(
            tech=ccs_config['tech'], flag='p', sector='electricity',
            description=ccs_config['description'], data_id=utils.data_id(),
        )]))


        for region in config.model_regions:
                
                # Get the existing vintages for this region and generator tech
                exs_vints = df_rtv_gen.loc[df_rtv_gen['region']==region]['vint']
                if len(exs_vints) == 0: continue


                ## CapacityToActivity
                curs.executemany(*CapacityToActivity.bulk_insert_or_ignore_sql([
                    CapacityToActivity(region=region, tech=bypass_tech, c2a=config.c2a, notes=f"({config.c2a_unit})", data_id=utils.data_id(region)),
                    CapacityToActivity(region=region, tech=ccs_config['tech'], c2a=config.c2a, notes=f"({config.c2a_unit})", data_id=utils.data_id(region)),
                ]))
                
            
                # Efficiency dummy retrofit bypass
                curs.executemany(*Efficiency.bulk_insert_or_ignore_sql([Efficiency(
                    region=region, input_comm=input_comm['commodity'],
                    tech=bypass_tech, vintage=config.model_periods[0],
                    output_comm=output_comm['commodity'], efficiency=1,
                    notes=f"{eff_units} dummy bypass", data_id=utils.data_id(region),
                )]))
                
                # Dummy processes have to retire when their generators reach end of life or they'll be orphaned
                life = max(exs_vints + coders_gen['service_life']) - config.model_periods[0]
                curs.executemany(*LifetimeTech.bulk_insert_or_ignore_sql([LifetimeTech(
                    region=region, tech=bypass_tech, lifetime=life,
                    notes="(y) matched to end of life of retrofittable generators",
                    data_id=utils.data_id(region),
                )]))
                
                
                # This is the vintage of the CCS retrofit, not the attached generator
                for vint in config.model_periods:
                    
                    # Make sure that there can be a generator to retrofit for this region and vintage. If so, add remaining data
                    if len(exs_vints.loc[(exs_vints <= vint) & (exs_vints + coders_gen['service_life'] > vint)]) == 0: continue


                    ## LifetimeTech
                    # To avoid network orphans, the CCS retrofits must die when their upstream generators do
                    life = min(coders_gen['service_life'], max(exs_vints + coders_gen['service_life']) - vint)
                    curs.executemany(*LifetimeProcess.bulk_insert_or_ignore_sql([LifetimeProcess(
                        region=region, tech=ccs_config['tech'], vintage=vint, lifetime=life,
                        notes=f"(y) {gen_config.coders_equiv} service life years - capped at end of life of retrofittable generators",
                        data_source=config.refs.get('generation_generic').id, dq_cred=2,
                        data_id=utils.data_id(region),
                    )]))


                    ## Efficiency
                    penalty, note = utils.atb_data(ccs_config, core_metric_parameter='Net Output Penalty', core_metric_variable=int(max(ccs_config['atb_min_year'],utils.data_year(vint))))

                    # Penalty to efficiency
                    eff = 1 + float(penalty.iloc[0])
                    curs.executemany(*Efficiency.bulk_insert_or_ignore_sql([Efficiency(
                        region=region, input_comm=input_comm['commodity'],
                        tech=ccs_config['tech'], vintage=vint,
                        output_comm=output_comm['commodity'], efficiency=eff,
                        notes=f"{eff_units} {note}",
                        data_source=config.refs.get('atb').id, dq_cred=1,
                        data_id=utils.data_id(region),
                    )]))
                    

                    ## EmissionActivity
                    emis_act = -1.0 * ccs_config['capture_rate'] / eff * gen_emis # have to adjust for efficiency as units are co2 emitted per output energy

                    # Add as both negative CO2 and negative that same number CO2e (1:1)
                    # CANOE currently tracks both separate GHGs and an aggregate CO2e (double counting)
                    for e in ('co2', 'co2e'):
                        emis_comm = config.commodities.loc[e]
                        units = f"({emis_comm['units']}/{output_comm['units']})"
                        curs.executemany(*EmissionActivity.bulk_insert_or_ignore_sql([EmissionActivity(
                            region=region, emis_comm=emis_comm['commodity'],
                            input_comm=input_comm['commodity'],
                            tech=ccs_config['tech'], vintage=vint,
                            output_comm=output_comm['commodity'],
                            activity=emis_act, units=units,
                            notes=f"Minus capture rate times {gen_config.code} co2 emissions divided by {ccs_code} efficiency",
                            data_source=config.refs.get('atb').id, dq_cred=1,
                            data_id=utils.data_id(region),
                        )]))
                    

                    ## CostInvest
                    metric = config.atb.ccs_retrofit_cost_invest_metric
                    cost_invest, note = utils.atb_data(ccs_config, core_metric_parameter=metric, core_metric_variable=int(max(ccs_config['atb_min_year'],utils.data_year(vint))))
                    cost_invest = config.units.loc['cost_invest', 'atb_conv_fact'] * float(cost_invest.iloc[0])
                    cost_invest = conv_curr(cost_invest, config.atb.currency_year, config.atb.currency)

                    if cost_invest != 0 and not pd.isna(cost_invest):
                        curs.executemany(*CostInvest.bulk_insert_or_ignore_sql([CostInvest(
                            region=region, tech=ccs_config['tech'], vintage=vint,
                            cost=cost_invest, units=f"({config.units.loc['cost_invest', 'units']})",
                            notes=note, data_source=config.refs.get('atb').id, dq_cred=1,
                            data_id=utils.data_id(region),
                        )]))
                    

                    # Add CCS retrofit options for all future model periods
                    for period in config.model_periods:
                        
                        if vint > period or vint + life <= period: continue


                        ## MaxActivity
                        # This period is beyond end-of-life of all retrofittable generators
                        if period >= max(exs_vints + coders_gen['service_life']):
                            _la_note = "beyond end-of-life of all retrofittable generators"
                            _la_units = f"({output_comm['units']})"
                            curs.executemany(*LimitActivity.bulk_insert_or_ignore_sql([
                                LimitActivity(region=region, period=period, tech_or_group=ccs_config['tech'], operator='le', activity=0, units=_la_units, notes=_la_note, data_id=utils.data_id(region)),
                                LimitActivity(region=region, period=period, tech_or_group=bypass_tech, operator='le', activity=0, units=_la_units, notes=_la_note, data_id=utils.data_id(region)),
                            ]))


                        ## CostFixed
                        cost_fixed, note = utils.atb_data(ccs_config, core_metric_parameter='Fixed O&M', core_metric_variable=int(max(ccs_config['atb_min_year'],utils.data_year(vint))))
                        cost_fixed = config.units.loc['cost_fixed', 'atb_conv_fact'] * float(cost_fixed.iloc[0])
                        cost_fixed = conv_curr(cost_fixed, config.atb.currency_year, config.atb.currency)

                        if cost_fixed != 0 and not pd.isna(cost_fixed):
                            curs.executemany(*CostFixed.bulk_insert_or_ignore_sql([CostFixed(
                                region=region, period=period, tech=ccs_config['tech'], vintage=vint,
                                cost=cost_fixed, units=f"({config.units.loc['cost_fixed', 'units']})",
                                notes=note, data_source=config.refs.get('atb').id, dq_cred=1,
                                data_id=utils.data_id(region),
                            )]))


                        ## CostVariable
                        cost_variable, note = utils.atb_data(ccs_config, core_metric_parameter='Variable O&M', core_metric_variable=int(max(ccs_config['atb_min_year'],utils.data_year(vint))))
                        cost_variable = config.units.loc['cost_variable', 'atb_conv_fact'] * float(cost_variable.iloc[0])
                        cost_variable = conv_curr(cost_variable, config.atb.currency_year, config.atb.currency)

                        if cost_variable != 0 and not pd.isna(cost_variable):
                            curs.executemany(*CostVariable.bulk_insert_or_ignore_sql([CostVariable(
                                region=region, period=period, tech=ccs_config['tech'], vintage=vint,
                                cost=cost_variable, units=f"({config.units.loc['cost_variable', 'units']})",
                                notes=note, data_source=config.refs.get('atb').id, dq_cred=1,
                                data_id=utils.data_id(region),
                            )]))

    conn.commit()
    conn.close()



"""
##############################################################
    Monthly hydro
##############################################################
"""

def setup_monthly_hydro(df_rtv: pd.DataFrame):
    """
    We need to add an intermediate commodity and technology to act as the reservoir storage.
    To keep things simple, keep the existing MLY-EXS and duplicate some data, 
    creating MLY-EXS-IN, which fills the reservoir. Changes to make:
    1. Duplicate ExistingCapacity so both have this existing capacity
    2. Duplicate and rename Efficiency so it is ethos --IN-> storage --EXS-> electricity
    3. Duplicate Technology for IN, make it baseload 'pb'
    4. Make EXS a seasonal storage tech ('ps' tag and seas_stor = 1 in the Technology table)
    5. Give EXS a StorageDuration of 730 hours (one month... it'll do for now)
    6. Rename LimitSeasonalCapacityFactor to IN
    7. Duplicate CapacityToActivity for IN
    """

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()

    for base_tech in df_rtv['tech'].unique():

        tech_config = config.gen_techs_by_code['hydro_monthly']

        in_tech = f'{base_tech}-IN'

        storage_comm = config.commodities.loc['hyd_mly']
        out_comm = config.commodities.loc[tech_config.out_comm]
        
        ## ExistingCapacity
        curs.execute(
            "REPLACE INTO "
            "existing_capacity(region, tech, vintage, capacity, units, notes, data_source, dq_cred, data_id) "
            f"SELECT region, '{in_tech}' as tech, vintage, capacity, units, notes, data_source, dq_cred, data_id "
            "FROM existing_capacity "
            f"WHERE tech == '{base_tech}' "
        )

        ## Efficiency
        note = f"({out_comm['units']}/{storage_comm['units']}) storage units are available generation"
        curs.execute(
            "REPLACE INTO "
            "efficiency(region, input_comm, tech, vintage, output_comm, efficiency, notes, data_source, dq_cred, data_id) "
            f"SELECT region, input_comm, '{in_tech}' as tech, vintage, '{storage_comm['commodity']}' as output_comm, efficiency, '{note}' as notes, data_source, dq_cred, data_id "
            "FROM efficiency "
            f"WHERE tech == '{base_tech}' "
        )
        curs.execute(
            "UPDATE efficiency "
            f"SET input_comm = '{storage_comm['commodity']}', "
            f"notes = '{note}' "
            f"WHERE tech == '{base_tech}'"
        )

        ## Technology
        desc = 'inflow to reservoir for monthly hydroelectric generation'
        curs.execute(
            "REPLACE INTO "
            "technology(tech, flag, sector, description, data_id) "
            f"SELECT '{in_tech}' as tech, 'pb' as flag, sector, '{desc}' as description, data_id "
            "FROM technology "
            f"WHERE tech == '{base_tech}' "
        )
        curs.execute(
            "UPDATE technology "
            f"SET "
            "flag = 'ps', "
            "seas_stor = 1 "
            f"WHERE tech == '{base_tech}'"
        )

        ## CapacityToActivity
        curs.execute(
            "REPLACE INTO "
            "capacity_to_activity(region, tech, c2a, notes, data_id) "
            f"SELECT region, '{in_tech}' as tech, c2a, notes, data_id "
            "FROM capacity_to_activity "
            f"WHERE tech == '{base_tech}' "
        )

        ## LimitSeasonalCapacityFactor
        curs.execute(f"UPDATE limit_seasonal_capacity_factor SET tech_or_group = '{in_tech}' WHERE tech_or_group == '{base_tech}'")
        
        ## StorageDuration
        sd_rows = [
            StorageDuration(
                region=region, tech=base_tech, duration=730,
                notes="(hours of storage) one month", data_id=utils.data_id(region),
            )
            for region in df_rtv.loc[df_rtv['tech'] == base_tech]['region'].unique()
        ]
        if sd_rows:
            curs.executemany(*StorageDuration.bulk_insert_or_ignore_sql(sd_rows, include_nulls=True))

    conn.commit()
    conn.close()






if __name__ == "__main__":

    aggregate()