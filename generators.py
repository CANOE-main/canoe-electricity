"""
Aggregates data for generators
Written by Ian David Elder for the CANOE model
"""

import sqlite3
from setup import config
import coders_api
import utils
import pandas as pd
import os
import traceback
import capacity_credits
import capacity_factors

df_generic: pd.DataFrame
df_cost: pd.DataFrame

conn: sqlite3.Connection
curs: sqlite3.Cursor



def aggregate():

    print("Aggregating generator data...")

    initialise_data()

    # Aggregate new generation
    aggregate_new_generators()
    if config.params['include_storage']: aggregate_new_storage()

    # Aggregate existing generation
    df_rtv = None
    if config.params['include_existing_capacity']:
        df_rtv = aggregate_existing_generators()
        if config.params['include_storage']: aggregate_existing_storage()

    # Aggregate CCS retrofits
    if config.params['include_ccs_retrofits']: aggregate_ccs_retrofits(df_rtv)

    print(f"Generator data aggregated into {os.path.basename(config.database_file)}\n")



def initialise_data():

    global df_generic, df_cost

    # CODERS capital cost evolution
    _cost_json, df_cost, date_accessed = coders_api.get_data(end_point='generation_cost_evolution')
    config.references['generation_cost_evolution'] = config.params['coders']['reference'].replace("<date>", date_accessed).replace("<table>","generation_cost_evolution")
    df_cost['gen_type'] = df_cost['gen_type'].str.lower()
    df_cost.set_index('gen_type', inplace=True)

    # CODERS generic generator data
    _generic_json, df_generic, date_accessed = coders_api.get_data(end_point='generation_generic')
    config.references['generation_generic'] = config.params['coders']['reference'].replace("<date>", date_accessed).replace("<table>","generation_generic")
    df_generic['gen_type'] = df_generic['gen_type'].str.lower()
    df_generic.set_index('gen_type', inplace=True)



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

    for tech_code, tech_config in config.gen_techs.iterrows():

        if not tech_config['include_new']: continue

        # Number of specified new capacity batches. Default 1 if not specified
        n_batches = int(tech_config['new_cap_batches']) if not pd.isna(tech_config['new_cap_batches']) else 1

        # Generates batched tech names like E_TECH-NEW-1, E_TECH-NEW-2...
        base_tech = tech_config['base_tech']
        if n_batches > 1: new_techs = [f"{base_tech}-NEW-{n}" for n in range(1,n_batches+1)] # batches are specified
        else: new_techs = [f"{base_tech}-NEW"] # batches not specified

        for tech in new_techs:

            ## Technologies
            curs.execute(f"""REPLACE INTO
                        technologies(tech, flag, sector, tech_desc)
                        VALUES("{tech}", "{tech_config['flag']}", "electricity", "new {tech_config['description']}")""")
            
            for region in config.model_regions:
                for period in config.model_periods:
                    rtv.append({'region': region, 'tech_code': tech_code, 'tech': tech, 'vint': period})

    conn.commit()
    conn.close()

    df_rtv = pd.DataFrame(data=rtv)

    # Add life because capacity credits need it as a check
    df_rtv['life'] = [df_generic.loc[config.gen_techs.loc[tc, 'coders_equiv'], 'service_life'] for tc in df_rtv['tech_code']]

    ## CapacityCredit
    if config.params['include_reserve_margin']: capacity_credits.aggregate_new(df_rtv)

    ## CapacityFactorTech
    capacity_factors.aggregate_new(df_rtv)

    # Aggregate remaining technoeconomic data
    aggregate_generators_generic(df_rtv)



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

    for code, storage_config in config.storage_techs.iterrows():

        if not storage_config['include_new']: continue

        # Commodity data
        input_comm = config.commodities.loc[storage_config['in_comm']]
        output_comm = config.commodities.loc[storage_config['out_comm']]
        eff_units = f"({input_comm['units']}/{output_comm['units']})"

        tech = f"{storage_config['base_tech']}-NEW"

        ## Technologies
        curs.execute(f"""REPLACE INTO
                    technologies(tech, flag, sector, tech_desc)
                    VALUES("{tech}", "ps", "electricity", "new {storage_config['description']}")""")
        
        for region in config.model_regions:

            ## StorageDuration
            curs.execute(f"""REPLACE INTO
                        StorageDuration(regions, tech, duration, duration_notes)
                        VALUES("{region}", "{tech}", "{storage_config['duration']}", "(hours of storage)")""")
        
            for vint in config.model_periods:
                rtv.append({'region': region, 'tech_code': code, 'tech': tech, 'vint': vint})

                ## Efficiency
                curs.execute(f"""REPLACE INTO
                            Efficiency(regions, input_comm, tech, vintage, output_comm, efficiency, eff_notes, reference, dq_est)
                            VALUES("{region}", "{input_comm['commodity']}", "{tech}", {vint}, "{output_comm['commodity']}", {storage_config['efficiency']},
                            "{eff_units} Following assumptions in NREL ATB", "{config.params['atb']['reference'].replace('<scenario>', storage_config['atb_scenario'])}", 1)""")

    conn.commit()
    conn.close()

    df_rtv = pd.DataFrame(data=rtv)

    # Add life because capacity credits need it as a check
    df_rtv['life'] = [df_generic.loc[config.storage_techs.loc[tc, 'coders_equiv'], 'service_life'] for tc in df_rtv['tech_code']]

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

    _exs, df_existing, date_accessed = coders_api.get_data(end_point='generators')
    config.references['generators'] = config.params['coders']['reference'].replace("<date>", date_accessed).replace("<table>","generators")

    # Maps all coders existing storage types to canoe techs
    existing_map = dict()
    for tech_code, row in config.gen_techs.iterrows():
        if pd.isna(row['coders_existing']): continue
        for coders_equiv in row['coders_existing'].split("+"):
            existing_map[coders_equiv] = tech_code

    # Get CANOE technologies
    df_existing['gen_type'] = df_existing['gen_type'].str.lower()
    df_existing['tech_code'] = df_existing['gen_type'].map(existing_map)

    # Remove any that have not been set as an equivalent in the config csv
    for idx, row in df_existing.iterrows():
        if pd.isna(row['tech_code']):
            print(f"Existing generation technology {row['gen_type']} has not been assigned to a CANOE tech and will be skipped!")
    df_existing = df_existing.loc[~pd.isna(df_existing['tech_code'])]

    # Get CANOE regions and skip capacity in exogenous provinces
    df_existing['region'] = df_existing['operating_region'].str.lower().map(config.region_map)
    df_existing = df_existing.loc[df_existing['region'].isin(config.model_regions)]

    # Remove zero-capacity projects
    df_existing = df_existing.loc[df_existing['facility_installed_capacity'].astype(float) > 0]
    df_existing['capacity'] = df_existing['facility_installed_capacity'].astype(float) * float(config.units.loc['capacity', 'coders_conv_fact'])

    if len(df_existing) == 0:
        print("No valid existing generation capacity found.")
        return

    # Delimiter for concatenating project names together for a description
    df_existing['description'] = df_existing['generation_facility_name'] + ' - '

    # Vintage is last renewal year if available otherwise start year
    df_existing['vint'] = df_existing[['start_year','previous_renewal_year']].max(axis=1)

    # Remove any existing capacity after first model period
    df_existing = df_existing.loc[df_existing['vint'] < config.model_periods[0]]

    # Round vintages to period step but before first model period
    step = config.params['period_step']
    df_existing['vint'] = [min(config.model_periods[0] - 1, step * round(vint/step)) for vint in df_existing['vint']]

    # If no retirement then override vintage to one year before first model period
    df_existing['vint'] = df_existing['vint'].mask([config.gen_techs.loc[tc, 'no_retirement'] for tc in df_existing['tech_code']], config.model_periods[0] - 1)
    
    # Aggregate existing capacities and projects by region, tech, vintage
    df_rtv = df_existing.groupby(['region','tech_code','vint']).sum(numeric_only=False).reset_index()
    df_rtv['description'] = df_rtv['description'].str.removesuffix(' - ') # one excess delimiter after concatenating

    # Add -EXS tag
    df_rtv['tech'] = [f"{config.gen_techs.loc[tc, 'base_tech']}-EXS" for tc in df_rtv['tech_code']]

    # Add life because capacity credits need it as a check
    df_rtv['life'] = [df_generic.loc[config.gen_techs.loc[tc, 'coders_equiv'], 'service_life'] for tc in df_rtv['tech_code']]

    # Remove any existing capacity that wouldn't reach the first model period
    df_rtv = df_rtv.loc[df_rtv['vint'] + df_rtv['life'] > config.model_periods[0]]

    ## CapacityFactorTech
    capacity_factors.aggregate_existing(df_rtv)

    ## CapacityCredit
    if config.params['include_reserve_margin']: capacity_credits.aggregate_existing(df_rtv)

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()

    # Add technologies
    for _idx, row in df_rtv[['tech_code','tech','description']].drop_duplicates().iterrows():
    
        tech_config = config.gen_techs.loc[row['tech_code']]

        ## Technologies
        curs.execute(f"""REPLACE INTO
                    technologies(tech, flag, sector, tech_desc)
                    VALUES("{row['tech']}", "{tech_config['flag']}", "electricity", "existing {tech_config['description']} - {row['description']}")""")

    # Iterate over aggregated existing capacity
    for _idx, row in df_rtv.iterrows():

        tech_config = config.gen_techs.loc[row['tech_code']]

        ## ExistingCapacity
        if tech_config['no_retirement']: note = f"no retirement so aggregated to last existing vintage - {utils.string_cleaner(row['description'])}"
        else: note = f"aggregated to {step}-yearly vintages - {utils.string_cleaner(row['description'])}"
        
        curs.execute(f"""REPLACE INTO
                    ExistingCapacity(regions, tech, vintage, exist_cap, exist_cap_units, exist_cap_notes, reference, data_flags, dq_est)
                    VALUES("{row['region']}", "{row['tech']}", "{row['vint']}", "{row['capacity']}", "({config.units.loc['capacity', 'units']})",
                    "{note}", "{config.references['generators']}", "coders", 1)""")
    

    ## time_periods
    for vint in df_rtv['vint'].unique():
        curs.execute(f"""REPLACE INTO
                    time_periods(t_periods, flag)
                    VALUES({vint}, 'e')""")
        
    conn.commit()
    conn.close()
    
    # Aggregate remaining technoeconomic data
    aggregate_generators_generic(df_rtv[['region','tech_code','tech','vint']].copy())

    return df_rtv



def aggregate_existing_storage():

    print("Aggregating existing storage capacity data...")

    """
    ##############################################################
        Existing storage
    ##############################################################
    """

    _storage_exs, df_existing, date_accessed = coders_api.get_data(end_point='storage')
    config.references['storage'] = config.params['coders']['reference'].replace("<date>", date_accessed).replace("<table>","storage")

    # Maps all coders existing storage types to canoe techs
    existing_map = dict()
    for tech_code, row in config.storage_techs.iterrows():
        if pd.isna(row['coders_existing']): continue
        for coders_equiv in row['coders_existing'].split("+"):
            existing_map[(coders_equiv, row['duration'])] = tech_code

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

    # Delimiter for concatenating project names together for a description
    df_existing['description'] = df_existing['storage_facility_name'] + ' - '

    # Vintage is last renewal year if available otherwise start year
    df_existing['vint'] = df_existing[['start_year','previous_renewal_year']].max(axis=1)

    # Remove any existing capacity after first model period
    df_existing = df_existing.loc[df_existing['vint'] < config.model_periods[0]]

    # Round vintages to period step but before first model period
    step = config.params['period_step']
    df_existing['vint'] = [min(config.model_periods[0] - 1, step * round(vint/step)) for vint in df_existing['vint']]

    # If no retirement then override vintage to last before first model period
    df_existing['vint'] = df_existing['vint'].mask([config.storage_techs.loc[tc, 'no_retirement'] for tc in df_existing['tech_code']], config.model_periods[0] - 1)
    
    # Aggregate existing capacities and projects by region, tech, vintage
    df_rtdv = df_existing.groupby(['region','tech_code','storage_duration','vint']).sum(numeric_only=False).reset_index()
    df_rtdv['description'] = df_rtdv['description'].str.removesuffix(' - ') # one excess delimiter after concatenating

    # Add life because capacity credits need it as a check
    df_rtdv['life'] = [df_generic.loc[config.storage_techs.loc[tc, 'coders_equiv'], 'service_life'] for tc in df_rtdv['tech_code']]

    # Remove any existing capacity that wouldn't reach the first model period
    df_rtdv = df_rtdv.loc[df_rtdv['vint'] + df_rtdv['life'] > config.model_periods[0]]

    # Add -EXS tag
    df_rtdv['tech'] = [f"{config.storage_techs.loc[tc, 'base_tech']}-EXS" for tc in df_rtdv['tech_code']]

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()

    # Iterate over aggregated existing capacity
    for _idx, row in df_rtdv.iterrows():

        # Tech configuration data
        storage_config = config.storage_techs.loc[row['tech_code']]

        # Commodity data
        input_comm = config.commodities.loc[storage_config['in_comm']]
        output_comm = config.commodities.loc[storage_config['out_comm']]
        eff_units = f"({input_comm['units']}/{output_comm['units']})"


        ## Technologies
        curs.execute(f"""REPLACE INTO
                    technologies(tech, flag, sector, tech_desc)
                    VALUES("{row['tech']}", "ps", "electricity", "existing {storage_config['description']} - {row['description']}")""")
        

        ## Efficiency
        curs.execute(f"""REPLACE INTO
                    Efficiency(regions, input_comm, tech, vintage, output_comm, efficiency, eff_notes, reference, dq_est)
                    VALUES("{row['region']}", "{input_comm['commodity']}", "{row['tech']}", {row['vint']}, "{output_comm['commodity']}", {storage_config['efficiency']},
                    "{eff_units} Following assumptions in NREL ATB", "{config.params['atb']['reference'].replace('<scenario>', storage_config['atb_scenario'])}", 1)""")


        ## ExistingCapacity
        if storage_config['no_retirement']: note = f"no retirement so aggregated to last existing vintage - {utils.string_cleaner(row['description'])}"
        else: note = f"aggregated to {step}-yearly vintages - {utils.string_cleaner(row['description'])}"

        curs.execute(f"""REPLACE INTO
                    ExistingCapacity(regions, tech, vintage, exist_cap, exist_cap_units, exist_cap_notes, reference, data_flags, dq_est)
                    VALUES("{row['region']}", "{row['tech']}", "{row['vint']}", "{row['storage_capacity']}", "({config.units.loc['capacity', 'units']})",
                    "{note}", "{config.references['storage']}", "coders", 1)""")


        ## StorageDuration
        curs.execute(f"""REPLACE INTO
                    StorageDuration(regions, tech, duration, duration_notes, reference, data_flags, dq_est)
                    VALUES("{row['region']}", "{row['tech']}", "{row['storage_duration']}", "(hours of storage)", "{config.references['storage']}", "coders", 1)""")
    
    
    ## time_periods
    for vint in df_rtdv['vint'].unique():
        curs.execute(f"""REPLACE INTO
                    time_periods(t_periods, flag)
                    VALUES({vint}, 'e')""")
        

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

        tech_config = config.gen_techs.loc[row['tech_code']].copy()

        aggregate_rt_all(row['region'], row['tech'], tech_config)

        # Take from ATB if an ATB equivalent is defined, otherwise CODERS
        if pd.isna(tech_config['atb_display_name']): aggregate_rt_coders(row['region'], row['tech'], tech_config)
        else: aggregate_rt_atb(row['region'], row['tech'], tech_config)
    
    # Also need vintage index for this data
    for _idx, row in df_rtv.iterrows():

        tech_config = config.gen_techs.loc[row['tech_code']].copy()

        # Take from ATB if an ATB equivalent is defined, otherwise CODERS
        if pd.isna(tech_config['atb_display_name']): aggregate_rtv_coders(row['region'], row['tech'], row['vint'], tech_config)
        else: aggregate_rtv_atb(row['region'], row['tech'], row['vint'], tech_config)

    conn.commit()
    conn.close()
    


def aggregate_storage_generic(df_rtv: pd.DataFrame):

    global conn, curs

    ## CapacityCredit
    if config.params['include_reserve_margin']: capacity_credits.aggregate_storage(df_rtv)

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()

    # Just need region and tech indices for this data
    for _idx, row in df_rtv[['region','tech_code','tech']].drop_duplicates().iterrows():

        storage_config = config.storage_techs.loc[row['tech_code']].copy()

        aggregate_rt_all(row['region'], row['tech'], storage_config)

        # Take from ATB if an ATB equivalent is defined, otherwise CODERS
        if pd.isna(storage_config['atb_display_name']): aggregate_rt_coders(row['region'], row['tech'], storage_config)
        else: aggregate_rt_atb(row['region'], row['tech'], storage_config)
    
    # Also need vintage index for this data
    for _idx, row in df_rtv.iterrows():

        storage_config = config.storage_techs.loc[row['tech_code']].copy()

        # Take from ATB if an ATB equivalent is defined, otherwise CODERS
        if pd.isna(storage_config['atb_display_name']): aggregate_rtv_coders(row['region'], row['tech'], row['vint'], storage_config)
        else: aggregate_rtv_atb(row['region'], row['tech'], row['vint'], storage_config)

    conn.commit()
    conn.close()



## Aggregates some common data where indexed by region, tech
def aggregate_rt_all(region, tech, tech_config):

    # Using some generic CODERS data
    coders_gen = df_generic.loc[tech_config['coders_equiv']]

    # Add to specified sets
    if not pd.isna(tech_config['tech_sets']):
        for tech_set in tech_config['tech_sets'].split('+'):
            curs.execute(f"""REPLACE INTO {tech_set}(tech) VALUES('{tech}')""")


    ## LifetimeTech
    if tech_config['no_retirement']:
        curs.execute(f"""REPLACE INTO
                    LifetimeTech(regions, tech, life, life_notes)
                    VALUES("{region}", "{tech}", 100, "(y) no retirement")""")
    else:
        curs.execute(f"""REPLACE INTO
                    LifetimeTech(regions, tech, life, life_notes, reference, data_flags, dq_est)
                    VALUES("{region}", "{tech}", "{coders_gen['service_life']}", "(y) {tech_config['coders_equiv']} service life years",
                    "{config.references['generation_generic']}", "coders", 1)""")


    ## CapacityToActivity
    curs.execute(f"""REPLACE INTO
                CapacityToActivity(regions, tech, c2a, c2a_notes)
                VALUES("{region}", "{tech}", "{config.params['c2a']}", "({config.params['c2a_unit']})")""")
    


def aggregate_rt_atb(region, tech, tech_config):

    """
    ##############################################################
        Generic data from NREL ATB, indexed by region, tech
    ##############################################################
    """

    # CODERS data as a backup where not available in ATB
    tsv = atb_tsv(tech_config['atb_master_sheet'], tech_config['atb_tsv_row'])
    tsv_note = f"{tech_config['atb_master_sheet']} - {tech_config['atb_tsv_row']}"
    
    
    ## RampUp and RampDown
    # Take from ATB tsv table if available, otherwise use CODERS
    if tsv is None: aggregate_ramp_rt_coders(region, tech, tech_config)
    else:
        ramp_rate = tsv['ramp_rate_%_min']

        if pd.isna(ramp_rate): aggregate_ramp_rt_coders(region, tech, tech_config)
        else:
            ramp_rate = config.units.loc['ramp_rate', 'atb_conv_fact'] * float(ramp_rate)

            if 0.0 < ramp_rate < 1.0:

                note = f"({config.units.loc['ramp_rate', 'units']}) {tsv_note} ramp_rate_%_min times {config.units.loc['ramp_rate', 'coders_conv_fact']}"

                curs.execute(f"""REPLACE INTO
                            RampUp(regions, tech, ramp_up, reference, dq_est, additional_notes)
                            VALUES("{region}", "{tech}", "{ramp_rate}", "{config.references[tsv_note]}", 1, "{note}")""")
                curs.execute(f"""REPLACE INTO
                            RampDown(regions, tech, ramp_down, reference, dq_est, additional_notes)
                            VALUES("{region}", "{tech}", "{ramp_rate}", "{config.references[tsv_note]}", 1, "{note}")""")
                
                curs.execute(f"""REPLACE INTO tech_ramping(tech) VALUES("{tech}")""")
    

    ## CostInvest
    if not utils.is_exs(tech):
        for vint in config.model_periods:

            metric = config.params['atb']['cost_invest_metric']
            cost_invest, note = utils.atb_data(tech_config, core_metric_parameter=metric, core_metric_variable=max(2021,vint))
            cost_invest = config.units.loc['cost_invest', 'atb_conv_fact'] * float(cost_invest.iloc[0])
            
            if cost_invest != 0:
                curs.execute(f"""REPLACE INTO
                            CostInvest(regions, tech, vintage, cost_invest_notes, data_cost_invest, data_cost_year, data_curr, reference, dq_est)
                            VALUES("{region}", "{tech}", {vint}, "{note}", {cost_invest}, {config.params['atb']['currency_year']},
                            "{config.params['atb']['currency']}", "{config.references['atb']}", 1)""")



## Aggregates data from NREL ATB where indexed by region, tech, vintage
def aggregate_rtv_atb(region, tech, vint, tech_config):

    """
    ##############################################################
        Generic data from NREL ATB, indexed by region, tech, vint
    ##############################################################
    """

    # CODERS data as a backup where not available in ATB
    coders_gen = df_generic.loc[tech_config['coders_equiv']]
    tsv = atb_tsv(tech_config['atb_master_sheet'], tech_config['atb_tsv_row'])
    tsv_note = f"{tech_config['atb_master_sheet']} - {tech_config['atb_tsv_row']}"
    
    # Commodity data
    input_comm = config.commodities.loc[tech_config['in_comm']]
    output_comm = config.commodities.loc[tech_config['out_comm']]
    eff_units = f"({input_comm['units']}/{output_comm['units']})"

    # If configured for ccs retrofits change output commodity to an intermediary
    if tech_config.name in config.ccs_techs['generator'].values and config.params['include_ccs_retrofits']:
        output_comm = output_comm.copy()
        output_comm['commodity'] += f"_{tech_config.name}"


    ## Efficiency    
    # Efficiency is arbitrary for ethos (e.g. renewables)
    if "ethos" in input_comm['commodity']:
        
        curs.execute(f"""REPLACE INTO
                    Efficiency(regions, input_comm, tech, vintage, output_comm, efficiency, eff_notes)
                    VALUES("{region}", "{input_comm['commodity']}", "{tech}", {vint}, "{output_comm['commodity']}", 1, "{eff_units} dummy input so arbitrary")""")
    
    else:
        eff, note = utils.atb_data(tech_config, core_metric_parameter='Heat Rate', core_metric_variable=max(2021,vint))

        # If eff is None should be a storage tech and efficiency is already added so skip
        if eff is not None: 

            # Heat rate to % efficiency
            eff = 1 / (config.units.loc['heat_rate', 'atb_conv_fact'] * float(eff.iloc[0]))
            
            curs.execute(f"""REPLACE INTO
                    Efficiency(regions, input_comm, tech, vintage, output_comm, efficiency, eff_notes, reference, dq_est)
                    VALUES("{region}", "{input_comm['commodity']}", "{tech}", {vint}, "{output_comm['commodity']}", {eff}, "{eff_units} {note}",
                    "{config.references['atb']}", 1)""")


    ## EmissionActivity
    if config.params['include_emissions']:

        if tsv is None: # no ATB emissions data so use CODERS
            aggregate_emissions_rtv_coders(region, tech, vint, input_comm, output_comm, coders_gen, tech_config)
        
        else: # use ATB emissions data
            for emis in ['co2','so2','nox','hg']:

                emis_act = config.units.loc[f"{emis}_emissions", 'atb_conv_fact'] * float(tsv[f"emissions_{emis}_lbs_MMBtu"])
                emis_comm = config.commodities.loc[emis]
                emis_units = f"({emis_comm['units']}/{output_comm['units']})"

                if emis_act != 0:
                    curs.execute(f"""REPLACE INTO
                                EmissionActivity(regions, emis_comm, input_comm, tech, vintage, output_comm, emis_act, emis_act_units, emis_act_notes, reference, dq_est)
                                VALUES("{region}", "{emis_comm['commodity']}", "{input_comm['commodity']}", "{tech}", {vint}, "{output_comm['commodity']}",
                                {emis_act}, "{emis_units}", "{tsv_note} - emissions_{emis}_lbs_MMBtu", "{config.references[tsv_note]}", 1)""")


    # Indexed by period and vintage
    for period in config.model_periods:
        
        if vint > period or vint + coders_gen['service_life'] <= period: continue
        

        ## CostFixed
        cost_fixed, note = utils.atb_data(tech_config, core_metric_parameter='Fixed O&M', core_metric_variable=max(2021,vint))
        cost_fixed = config.units.loc['cost_fixed', 'atb_conv_fact'] * float(cost_fixed.iloc[0])

        if cost_fixed != 0:
            curs.execute(f"""REPLACE INTO
                        CostFixed(regions, periods, tech, vintage, cost_fixed_notes, data_cost_fixed, data_cost_year, data_curr, reference, dq_est)
                        VALUES("{region}", {period}, "{tech}", {vint}, "{note}", {cost_fixed}, {config.params['atb']['currency_year']},
                        "{config.params['atb']['currency']}", "{config.references['atb']}", 1)""")


        ## CostVariable
        cost_variable, var_note = utils.atb_data(tech_config, core_metric_parameter='Variable O&M', core_metric_variable=max(2021,vint))
        cost_fuel, fuel_note = utils.atb_data(tech_config, core_metric_parameter='Fuel', core_metric_variable=period)

        # If asking for fuel costs and ATB doesn't have it, use CODERS for all variable cost (can't mix currencies)
        if config.params['include_tech_fuel_cost'] and tech_config['include_fuel_cost'] and cost_fuel is None:
            aggregate_cost_var_rtvp_coders(region, tech, vint, period, coders_gen, tech_config)
        
        # Otherwise take Variable O&M from the ATB if it has it
        elif cost_variable is not None:

            cost_variable = config.units.loc['cost_variable', 'atb_conv_fact'] * float(cost_variable.iloc[0])
            
            if config.params['include_tech_fuel_cost'] and tech_config['include_fuel_cost']:
                cost_variable += config.units.loc['cost_fuel', 'atb_conv_fact'] * float(cost_fuel.iloc[0])
                note = f"variable o&m plus fuel cost - {var_note} - {fuel_note}"
            else: note = var_note

            if cost_variable != 0:
                curs.execute(f"""REPLACE INTO
                            CostVariable(regions, periods, tech, vintage, cost_variable_notes, data_cost_variable, data_cost_year, data_curr, reference, dq_est)
                            VALUES("{region}", {period}, "{tech}", {vint}, "{note}", {cost_variable}, {config.params['atb']['currency_year']},
                            "{config.params['atb']['currency']}", "{config.references['atb']}", 1)""")



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
    cost_invest = df_cost.loc[tech_config['coders_equiv']]
    if not utils.is_exs(tech):
        for vint in config.model_periods:

            cost = config.units.loc['cost_invest', 'coders_conv_fact'] * float(cost_invest[f"{vint}_CAD_per_kW"])
            # 'cost_invest_notes, data_cost_invest, data_cost_year, data_curr,' -> 'cost_invest_notes, data_cost_invest, data_cost_year, data_curr,'
            curs.execute(f"""REPLACE INTO
                        CostInvest(regions, tech, vintage, cost_invest_notes, data_cost_invest, data_cost_year, data_curr, reference, data_flags, dq_est)
                        VALUES("{region}", "{tech}", {vint}, "{tech_config['coders_equiv']} CAD_per_kW by vintage", {cost}, {config.params['coders']['currency_year']},
                        "{config.params['coders']['currency']}", "{config.references['generation_cost_evolution']}", "coders", 1)""")



def aggregate_ramp_rt_coders(region, tech, tech_config):

    coders_gen = df_generic.loc[tech_config['coders_equiv']]
    ramp_rate = coders_gen['ramp_rate_percent_per_min']

    if not pd.isna(ramp_rate):

        ramp_rate = config.units.loc['ramp_rate', 'coders_conv_fact'] * float(ramp_rate)

        if 0.0 < ramp_rate < 1.0:

            note = f"({config.units.loc['ramp_rate', 'units']}) {tech_config['coders_equiv']} ramp_rate_percent_per_min times {config.units.loc['ramp_rate', 'coders_conv_fact']}"

            curs.execute(f"""REPLACE INTO
                        RampUp(regions, tech, ramp_up, reference, data_flags, dq_est, additional_notes)
                        VALUES("{region}", "{tech}", "{ramp_rate}", "{config.references['generation_generic']}",
                        "coders", 1, "{note}")""")
            curs.execute(f"""REPLACE INTO
                        RampDown(regions, tech, ramp_down, reference, data_flags, dq_est, additional_notes)
                        VALUES("{region}", "{tech}", "{ramp_rate}", "{config.references['generation_generic']}",
                        "coders", 1, "{note}")""")
            
            curs.execute(f"""REPLACE INTO tech_ramping(tech) VALUES("{tech}")""")



## Aggregates data from CODERS where indexed by region, tech, vintage
def aggregate_rtv_coders(region, tech, vint, tech_config):

    """
    ##############################################################
        Generic data from CODERS, indexed by region, tech, vint
    ##############################################################
    """

    # Use coders equivalent for generic data
    coders_gen = df_generic.loc[tech_config['coders_equiv']]

    # Commodity data
    input_comm = config.commodities.loc[tech_config['in_comm']]
    output_comm = config.commodities.loc[tech_config['out_comm']]
    eff_units = f"({input_comm['units']}/{output_comm['units']})"

    # If configured for ccs retrofits change output commodity to an intermediary
    if tech_config.name in config.ccs_techs['generator'].values and config.params['include_ccs_retrofits']:
        output_comm = output_comm.copy()
        output_comm['commodity'] += f"_{tech_config.name}"


    ## Efficiency
    # Efficiency is arbitrary for ethos (e.g. renewables)
    if "ethos" in input_comm['commodity']:

        curs.execute(f"""REPLACE INTO
                    Efficiency(regions, input_comm, tech, vintage, output_comm, efficiency, eff_notes)
                    VALUES("{region}", "{input_comm['commodity']}", "{tech}", {vint}, "{output_comm['commodity']}", 1, "{eff_units} dummy input so arbitrary")""")
    
    # CODERS database provides an efficiency
    elif coders_gen['efficiency'] is not None:

        curs.execute(f"""REPLACE INTO
                    Efficiency(regions, input_comm, tech, vintage, output_comm, efficiency, eff_notes, reference, data_flags, dq_est)
                    VALUES("{region}", "{input_comm['commodity']}", "{tech}", {vint}, "{output_comm['commodity']}", "{coders_gen['efficiency']}",
                    "{eff_units} {tech_config['coders_equiv']} efficiency", "{config.references['generation_generic']}", "coders", 1)""")
    

    ## EmissionActivity
    if config.params['include_emissions']:
        aggregate_emissions_rtv_coders(region, tech, vint, input_comm, output_comm, coders_gen, tech_config)


    # Indexed by period and vintage
    for period in config.model_periods:
        
        if vint > period or vint + coders_gen['service_life'] <= period: continue

        
        ## CostFixed
        cost_fixed = config.units.loc['cost_fixed', 'coders_conv_fact'] * coders_gen['fixed_om_cost_CAD_per_MWyear']

        if cost_fixed != 0:
            curs.execute(f"""REPLACE INTO
                        CostFixed(regions, periods, tech, vintage, cost_fixed_notes, data_cost_fixed, data_cost_year, data_curr, reference, data_flags, dq_est)
                        VALUES("{region}", {period}, "{tech}", {vint}, "{tech_config['coders_equiv']} fixed_om_cost_CAD_per_MWyear", {cost_fixed}, {config.params['coders']['currency_year']},
                        "{config.params['coders']['currency']}", "{config.references['generation_cost_evolution']}", "coders", 1)""")
        
        ## CostVariable
        aggregate_cost_var_rtvp_coders(region, tech, vint, period, coders_gen, tech_config)



def aggregate_emissions_rtv_coders(region, tech, vint, input_comm, output_comm, coders_gen, tech_config):

    emis_act = config.units.loc['co2_emissions', 'coders_conv_fact'] * float(coders_gen['carbon_emissions'])
    emis_comm = config.commodities.loc['co2e']
    emis_units = f"({emis_comm['units']}/{output_comm['units']})"

    if emis_act != 0:
        curs.execute(f"""REPLACE INTO
                    EmissionActivity(regions, emis_comm, input_comm, tech, vintage, output_comm, emis_act, emis_act_units, emis_act_notes, reference, data_flags, dq_est)
                    VALUES("{region}", "{emis_comm['commodity']}", "{input_comm['commodity']}", "{tech}", {vint}, "{output_comm['commodity']}",
                    {emis_act}, "{emis_units}", "{tech_config['coders_equiv']} carbon_emissions", "{config.references['generation_generic']}", "coders", 1)""")



def aggregate_cost_var_rtvp_coders(region, tech, vint, period, coders_gen, tech_config):

    cost_variable = config.units.loc['cost_variable', 'coders_conv_fact'] * float(coders_gen['variable_om_cost_CAD_per_MWh'])
    description = f"{tech_config['coders_equiv']} variable_om_cost_CAD_per_MWh"

    if config.params['include_tech_fuel_cost'] and tech_config['include_fuel_cost']:

        fuel_price = coders_gen['average_fuel_price_CAD_per_GJ']

        if not pd.isna(fuel_price) and coders_gen['efficiency'] is not None:
            cost_variable += config.units.loc['cost_fuel', 'coders_conv_fact'] * float(fuel_price) / float(coders_gen['efficiency'])
            description += " plus average_fuel_price_CAD_per_GJ divided by efficiency"

    if cost_variable != 0:
        curs.execute(f"""REPLACE INTO
                    CostVariable(regions, periods, tech, vintage, cost_variable_notes, data_cost_variable, data_cost_year, data_curr, reference, data_flags, dq_est)
                    VALUES("{region}", {period}, "{tech}", {vint}, "{description}", {cost_variable}, {config.params['coders']['currency_year']},
                    "{config.params['coders']['currency']}", "{config.references['generation_generic']}", "coders", 1)""")



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

    if not config.params['include_emissions']:
        print("Can't include CCS retrofits without including emissions, too! Skipped CCS retrofits.")
        return
    
    print("Aggregating CCS retrofits data...")

    # Get region-tech-vint sets for techs with CCS retrofits
    if df_rtv_all is None: df_rtv_all = pd.DataFrame(columns=['region','tech_code','vint'])
    df_rtv_ccs = df_rtv_all.loc[df_rtv_all['tech_code'].isin(config.ccs_techs['generator'])]

    for ccs_code, ccs_config in config.ccs_techs.iterrows():
        
        # Get the retrofitted generator config and its coders generic data
        gen_config: pd.Series = config.gen_techs.loc[ccs_config['generator']]
        coders_gen: pd.Series = df_generic.loc[gen_config['coders_equiv']]

        # Existing capacity for this retrofittable generator
        df_rtv_gen = df_rtv_ccs.loc[df_rtv_ccs['tech_code'] == gen_config.name]

        # If including new capacity, add rtv sets for all future periods, regions
        if gen_config['include_new']:
            df_new = pd.DataFrame([{'region':r, 'tech_code':gen_config.name, 'vint':v}
                                for r in config.model_regions
                                for v in config.model_periods])
            df_rtv_gen = pd.concat([df_rtv_gen, df_new])

        # Make sure there can be a generator of this type to retrofit in any region otherwise add nothing
        if len(df_rtv_gen) == 0: continue

        try:
            tsv = atb_tsv(gen_config['atb_master_sheet'], gen_config['atb_tsv_row'])
            gen_emis = config.units.loc[f"co2_emissions", 'atb_conv_fact'] * float(tsv[f"emissions_co2_lbs_MMBtu"])
        except Exception as e:
            gen_emis = config.units.loc['co2_emissions', 'coders_conv_fact'] * float(coders_gen['carbon_emissions'])
            print(traceback.format_exc())
            print(f"\nTrying to aggregate {ccs_code} but could not get CO2 emissions of retrofitted generator {gen_config.name} from ATB workbook."
                  f"\nWill use CODERS emissions data for now but this will be capturing CO2-equivalent emissions!")
            continue

        if gen_emis <= 0:
            print(f"Tried to aggregate {ccs_code} but retrofitted generator {gen_config.name} had {gen_emis} CO2 emissions!")
            continue
        
        # Commodities data
        output_comm = config.commodities.loc[gen_config['out_comm']]
        emis_comm = config.commodities.loc['co2']
        emis_units = f"({emis_comm['units']}/{output_comm['units']})"

        # Create new intermediate commodity between generator and retrofit
        input_comm = output_comm.copy()
        input_comm['commodity'] += f"_{gen_config.name}"
        input_comm['description'] += f" from {gen_config['description']}"


        ## Commodities
        curs.execute(f"""REPLACE INTO
                    commodities(comm_name, flag, comm_desc)
                    VALUES('{input_comm['commodity']}', 'p',
                    '({input_comm['units']}) intermediate commodity going either to {ccs_config['tech']} or straight to {output_comm['commodity']}')""")


        ## Technologies
        # Bypass tech
        curs.execute(f"""REPLACE INTO
                    technologies(tech, flag, sector, tech_desc)
                    VALUES("{gen_config['base_tech']}_RFIT_BYPASS", "p", "electricity", "dummy bypass for ccs retrofit")""")
        
        # Retrofit tech
        curs.execute(f"""REPLACE INTO
                    technologies(tech, flag, sector, tech_desc)
                    VALUES("{ccs_config['tech']}", "p", "electricity", "{ccs_config['description']}")""")


        for region in config.model_regions:
                
                # Get the existing vintages for this region and generator tech
                exs_vints = df_rtv_gen.loc[df_rtv_gen['region']==region]['vint']
                if len(exs_vints) == 0: continue
                

                ## LifetimeTech
                life = round(coders_gen['service_life'] / 2) # retrofit so average half the life of the existing generator

                curs.execute(f"""REPLACE INTO
                            LifetimeTech(regions, tech, life, life_notes, reference, data_flags, dq_est)
                            VALUES("{region}", "{ccs_config['tech']}", "{life}",
                            "(y) retrofit so assumed half the life of the retrofitted generator on average - {gen_config['coders_equiv']} service life years",
                            "{config.references['generation_generic']}", "coders", 1)""")
                
                
                # This is the vintage of the CCS retrofit, not the attached generator
                for vint in config.model_periods:
                    
                    # Make sure that there can be a generator to retrofit for this region and vintage. If so, add remaining data
                    if len(exs_vints.loc[(exs_vints < vint) & (exs_vints + life > vint)]) == 0: continue


                    ## Efficiency
                    penalty, note = utils.atb_data(ccs_config, core_metric_parameter='Net Output Penalty', core_metric_variable=max(2021,vint))

                    # Efficiency penalty to efficiency
                    eff = 1 + float(penalty.iloc[0])
                    eff_units = f"({output_comm['units']}/{output_comm['units']})"

                    # CCS retrofit
                    curs.execute(f"""REPLACE INTO
                                Efficiency(regions, input_comm, tech, vintage, output_comm, efficiency, eff_notes, reference, dq_est)
                                VALUES("{region}", "{input_comm['commodity']}", "{ccs_config['tech']}", {vint}, "{output_comm['commodity']}",
                                "{eff}", "{eff_units} {note}", "{config.references['atb']}", 1)""")
                    

                    ## EmissionActivity
                    emis_act = -1.0 * ccs_config['capture_rate'] / eff * gen_emis # have to adjust for efficiency as units are co2 emitted per output energy

                    curs.execute(f"""REPLACE INTO
                                EmissionActivity(regions, emis_comm, input_comm, tech, vintage, output_comm, emis_act, emis_act_units, emis_act_notes, reference, dq_est)
                                VALUES("{region}", "{emis_comm['commodity']}", "{input_comm['commodity']}", "{ccs_config['tech']}", {vint}, "{output_comm['commodity']}",
                                {emis_act}, "{emis_units}", "Minus capture rate times {gen_config.name} co2 emissions divided by {ccs_code} efficiency",
                                "{config.references['atb']}", 1)""")
                    

                    ## CostInvest
                    metric = config.params['atb']['ccs_retrofit_cost_invest_metric']
                    cost_invest, note = utils.atb_data(ccs_config, core_metric_parameter=metric, core_metric_variable=max(2021,vint))
                    cost_invest = config.units.loc['cost_invest', 'atb_conv_fact'] * float(cost_invest.iloc[0])

                    if cost_invest != 0:
                        curs.execute(f"""REPLACE INTO
                                    CostInvest(regions, tech, vintage, cost_invest_notes, data_cost_invest, data_cost_year, data_curr, reference, dq_est)
                                    VALUES("{region}", "{ccs_config['tech']}", {vint}, "{note}", {cost_invest}, {config.params['atb']['currency_year']},
                                    "{config.params['atb']['currency']}", "{config.references['atb']}", 1)""")
                    

                    # Add  CCS retrofit options for all future model periods
                    for period in config.model_periods:
                        
                        if vint > period or vint + life <= period: continue


                        ## Efficiency
                        # Dummy retrofit bypass
                        curs.execute(f"""REPLACE INTO
                                    Efficiency(regions, input_comm, tech, vintage, output_comm, efficiency, eff_notes)
                                    VALUES("{region}", "{input_comm['commodity']}", "{gen_config['base_tech']}_RFIT_BYPASS", {period}, "{output_comm['commodity']}", 1, "{eff_units} dummy bypass")""")


                        ## CostFixed
                        cost_fixed, note = utils.atb_data(ccs_config, core_metric_parameter='Fixed O&M', core_metric_variable=max(2021,vint))
                        cost_fixed = config.units.loc['cost_fixed', 'atb_conv_fact'] * float(cost_fixed.iloc[0])

                        if cost_fixed != 0:
                            curs.execute(f"""REPLACE INTO
                                        CostFixed(regions, periods, tech, vintage, cost_fixed_notes, data_cost_fixed, data_cost_year, data_curr, reference, dq_est)
                                        VALUES("{region}", {period}, "{ccs_config['tech']}", {vint}, "{note}", {cost_fixed}, {config.params['atb']['currency_year']},
                                        "{config.params['atb']['currency']}", "{config.references['atb']}", 1)""")


                        ## CostVariable
                        cost_variable, note = utils.atb_data(ccs_config, core_metric_parameter='Variable O&M', core_metric_variable=max(2021,vint))
                        cost_variable = config.units.loc['cost_variable', 'atb_conv_fact'] * float(cost_variable.iloc[0])

                        if cost_variable != 0:
                            curs.execute(f"""REPLACE INTO
                                        CostVariable(regions, periods, tech, vintage, cost_variable_notes, data_cost_variable, data_cost_year, data_curr, reference, dq_est)
                                        VALUES("{region}", {period}, "{ccs_config['tech']}", {vint}, "{note}", {cost_variable}, {config.params['atb']['currency_year']},
                                        "{config.params['atb']['currency']}", "{config.references['atb']}", 1)""")

    conn.commit()
    conn.close()



"""
##############################################################
    Technology specific variables data
    Misc. data like emissions from ATB underlying workbook
##############################################################
"""

tsv_tables = dict() # store after loading as each takes ~0.3s - saves lots of time
# Gets a technology specific variables table from ATB master workbook
def atb_tsv(sheet, row) -> pd.DataFrame:

    if pd.isna(sheet): return # not specified

    cache_file = config.cache_dir + f"atb_technology_specific_variables_{sheet}.csv"

    config.references[f"{sheet} - {row}"] = config.params['atb']['master_reference'].replace('<sheet>', sheet)

    # If TSV already loaded, return it
    if sheet in tsv_tables.keys(): return tsv_tables[sheet].loc[row]

    # Otherwise, if TSV has been cached as a csv, load it and return it
    if os.path.isfile(cache_file) and not config.params['force_download']:
        df = pd.read_csv(cache_file, index_col=0)
        tsv_tables[sheet] = df # store loaded tsv
        return df.loc[row]

    table = config.atb_master_tables.loc[config.atb_master_tables['table']=='tsv'].loc[sheet]

    df = pd.read_excel(config.atb_master_file, dtype='unicode', sheet_name=sheet, usecols=table['columns'],
                       skiprows=int(table['first_row'])-1, nrows=int(table['last_row'])-int(table['first_row']), index_col=0)
    
    # Just to concatenate annoyingly split-up headers
    none_if_unnamed = lambda string: string.replace(' ','') if 'Unnamed' not in string else ''
    none_if_na = lambda val: str(val).replace(' ','') if not pd.isna(val) else ''
    df.columns = [none_if_unnamed(df.columns[i]) + none_if_na(df.iloc[0,i]) + none_if_na(df.iloc[1,i]) for i in range(len(df.columns))]

    # Translate concatenated ATB headers into useful headers
    df = df[[col for col in config.params['atb']['tsv_headers'].keys() if col in df.columns]] # remove irrelevant columns
    df.columns = [config.params['atb']['tsv_headers'][col] for col in df.columns] # translate headers

    # Add NaN columns for data we wanted but wasnt there so we can do if pd.isna(datum)
    for col in config.params['atb']['tsv_headers'].values():
        if col not in df.columns: df[col] = pd.NA

    # Drop leading two useless rows
    df = df.iloc[2:]

    # Cache tsv locally to speed things up next time
    df.to_csv(cache_file)
    tsv_tables[sheet] = df # store tsv

    return df.loc[row]



if __name__ == "__main__":

    aggregate()