"""
This script pulls data from the CODERS database and fills a TEMOA schema 
Written by Ian David Elder for the TEMOA Canada / CANOE model
"""

import sqlite3
import shutil
import os
import intertie_transfers
from utils import string_cleaner
import coders_api
from setup import config

# Frequently used config variables
translator = config.translator
params = config.params
all_regions = config.all_regions
model_periods = config.model_periods
generic_techs = config.generic_techs


# Get various files
this_dir = os.path.realpath(os.path.dirname(__file__)) + "/"
input_files = this_dir + "input_files/"
schema_file = this_dir + "coders_schema.sqlite"
database_file = this_dir + "coders_db.sqlite"

# If db does not exist make a copy of the schema
if not os.path.exists(database_file):
    shutil.copy(schema_file, database_file)



# Connect to the new database file
conn = sqlite3.connect(database_file)
curs = conn.cursor() # Cursor object interacts with the sqlite db

# Whether to use CODERS data from local cache instead of downloading new
from_cache = params['pull_from_cache'] == 'true'

# Collect existing generator data
existing_gen = coders_api.get_json(end_point='generators',from_cache=from_cache)

# Collect evolving cost data
cost_json = coders_api.get_json(end_point='generation_cost_evolution',from_cache=from_cache)
evolving_cost = dict({translator['generator_types'][tech['gen_type'].upper()]['CANOE_tech']: tech for tech in cost_json})



"""
##############################################################
    Fill basic tables
##############################################################
"""

# Add default global discount rate
curs.execute("DELETE FROM GlobalDiscountRate")
curs.execute(f"INSERT INTO GlobalDiscountRate(rate) VALUES({params['global_discount_rate']})")

# Add future model periods
for period in [*model_periods, 2*model_periods[-1] - model_periods[-2]]: 
    curs.execute(f"""REPLACE INTO
                time_periods(t_periods, flag)
                VALUES({period}, "f")""")

# Add regions
for region in all_regions:
    description = "outside model" if region == "EX" else translator['regions'][region]['description']
    curs.execute(f"""REPLACE INTO
                    regions(regions, region_note)
                    VALUES("{region}", "{description}")""")
    
# Add seasons and times of day
for h in range(0,24*365,24):
    seas = config.seas_8760[h]
    curs.execute(f"""INSERT OR IGNORE INTO
                time_season(t_season)
                VALUES("{seas}")""")
# Add seasons and times of day
for h in range(24):
    tofd = config.tofd_8760[h]
    curs.execute(f"""INSERT OR IGNORE INTO
                time_of_day(t_day)
                VALUES("{tofd}")""")

# Add emission commodity
curs.execute(f"""INSERT OR IGNORE INTO
             commodities(comm_name, flag)
             VALUES('{translator['units']['emission_commodity']['CANOE_unit']}', 'e')""")
    


# To determine whether a tech is existing or new
is_exs = lambda tech: '-EXS' in tech
is_new = lambda tech: '-NEW' in tech



"""
##############################################################
    Existing storage capacity
##############################################################
"""

# Replacing these base tech names with updated variants
old_techs = set()

# Add storage technology data
storage_exs = coders_api.get_json(end_point='storage',from_cache=from_cache)

for storage in storage_exs:

    region = translator['regions'][storage['operating_region'].upper()]['CANOE_region']
    if region == 'EX': continue

    if storage['closure_year'] <= model_periods[0]:
        print(f"Existing storage {storage['project_name']} would retire before first model period and so was excluded.")

    # Get the storage tech name e.g. E_BAT_4H
    CODERS_gen_type = storage['generation_type'].upper()
    duration = int(round(storage['duration']))
    base_tech = translator['generator_types'][CODERS_gen_type]['CANOE_tech']

    if base_tech not in generic_techs.keys():
        print(f"""Existing storage technology {CODERS_gen_type} has no generic data and was ignored!
              Site: {storage['project_name']} ({storage['owner']})
              Region: {region}
              Capacity: {storage['storage_capacity_in_mw']} MW""")
        continue

    tech = f"{base_tech}-{duration}H"

    # Some nomenclature differences between merged tables
    storage['install_capacity_in_mw'] = storage['storage_capacity_in_mw']

    # Updated duration-tagged tech
    storage['gen_type'] = tech

    # Have to add updated duration-tagged tech to translator
    translator['generator_types'][tech] = dict()
    translator['generator_types'][tech]['CANOE_tech'] = tech

    # Update dicts with new storage tech name, new and existing
    generic_techs[tech] = generic_techs[base_tech]
    evolving_cost[tech] = evolving_cost[base_tech]
    existing_gen.append(storage.copy())

    # Slate old tech name for removal
    old_techs.add(base_tech)

    notes = "1 hour storage" if duration == 1 else str(duration) + " hours storage"

    # Can use insert or ignore here as the tech name is now tied to the duration
    curs.execute(f"""REPLACE INTO
                StorageDuration(regions, tech, duration, duration_notes)
                VALUES("{region}", "{tech}-NEW", "{duration}", "{notes}")""")
    curs.execute(f"""REPLACE INTO
                StorageDuration(regions, tech, duration, duration_notes)
                VALUES("{region}", "{tech}-EXS", "{duration}", "{notes}")""")
    

# Remove outdated base storage techs
for old_tech in old_techs:
    generic_techs.pop(old_tech)
    evolving_cost.pop(old_tech)
old_techs.clear() # Otherwise it'll throw an error popping again below



"""
##############################################################
    Setup existing/new capacity batches (tech variants)
##############################################################
"""

# Handle batches of new techs
tech_variants = dict() # tech_variants[region][tech][tech-EXS, tech-NEW-1, ...]
for region in config.batched_cap.keys():
    if region == 'EX': continue

    tech_variants[region] = list()

    # For techs with specified batch sizes get from csv
    for base_tech in list(generic_techs.keys()):
        
        n_batches = int(translator['generator_types'][generic_techs[base_tech]['generation_type'].upper()]['new_cap_steps'])

        if n_batches == 0: variants = [f"{base_tech}-EXS"] # No new capacity allowed
        elif n_batches > 1: variants = [f"{base_tech}-EXS", *[f"{base_tech}-NEW-{n}" for n in range(1,n_batches+1)]] # Specified batches
        else: variants = [f"{base_tech}-EXS", f"{base_tech}-NEW"] # Not specified or 1 so allow new and existing

        tech_variants[region].extend(variants)

        # Add these additional techs to the generic techs dict
        old_techs.add(base_tech)
        for variant in variants:
            generic_techs[variant] = generic_techs[base_tech]

            # Evolving costs are only given for capital cost so only for new techs
            if is_new(variant): evolving_cost[variant] = evolving_cost[base_tech]



# Remove outdated base techs
for old_tech in old_techs:
    generic_techs.pop(old_tech)
    evolving_cost.pop(old_tech)



"""
##############################################################
    Existing generation capacity
##############################################################
"""

# Keep track of data aggregated by tech, vintage and region
rtv_data = dict()

# ExistingCapacity
for generator in existing_gen:

    tech = translator['generator_types'][generator['gen_type'].upper()]['CANOE_tech'] + '-EXS'
    generator_name = f"{generator['project_name']} ({generator['owner']})"
    region = translator['regions'][generator['copper_balancing_area'].upper()]['CANOE_region']

    if region == 'EX': continue # If not representing all provinces

    capacity = generator['install_capacity_in_mw']
    if capacity <= 0:
        print(f"Existing {region} generator {generator['project_name']} has {capacity} MW capacity and so was excluded")
        continue
    
    if 'HYD' in tech and params['no_hydro_retirement'] == 'true':
        vint = 2020 # If hydro doesn't retire might as well aggregate
    else:
        vint = generator['previous_renewal_year']
        if vint is None: vint = generator['start_year']

    # Aggregate all other existing vintages by specified num years
    exs_y = int(params['exs_aggregation_years'])
    vint = min(min(model_periods)-1,int(exs_y * round(float(vint)/exs_y))) # Round to the nearest exs_y years but before first model period

    # Add all existing vintages as existing time periods
    curs.execute(f"""REPLACE INTO
                time_periods(t_periods, flag)
                VALUES({vint}, "e")""")

    life = generic_techs[tech]['service_life_years']

    # Skip non-viable vintages
    if vint + life <= model_periods[0]:
        print(f"Existing {region} generator {generator['project_name']} would retire before first model period and so was excluded. Vintage: {vint}, life: {life}")
        continue
    
    # Keeping a record of valid region-tech-vintage sets (existing here but future added later)
    if region not in rtv_data.keys(): rtv_data[region] = dict()
    if tech not in rtv_data[region].keys(): rtv_data[region][tech] = dict()
    if vint not in rtv_data[region][tech].keys(): rtv_data[region][tech][vint] = {'capacity': capacity, 'description': string_cleaner(generator_name)}
    else:
        rtv_data[region][tech][vint]['capacity'] += capacity
        rtv_data[region][tech][vint]['description'] += " - " + string_cleaner(generator_name)

    exist_cap = translator['units']['capacity']['conversion_factor'] * rtv_data[region][tech][vint]['capacity']
    exist_cap_notes = rtv_data[region][tech][vint]['description']

    curs.execute(f"""REPLACE INTO
                ExistingCapacity(regions, tech, vintage, exist_cap, exist_cap_units, exist_cap_notes)
                VALUES("{region}", "{tech}", "{vint}", "{exist_cap}", "{translator['units']['capacity']['CANOE_unit']}", "{string_cleaner(exist_cap_notes)}")""")



"""
##############################################################
    Generic technology data
##############################################################
"""

# Add generic technology data
for region in all_regions:
    if region == 'EX': continue

    for tech in tech_variants[region]:

        # Generic data on this tech
        generic_tech = generic_techs[tech]

        # Collect some generic data for the tech
        eff = generic_tech['efficiency']

        # Generate a tech description
        description = generic_tech['description']
        if is_exs(tech): description = 'existing ' + description
        elif is_new(tech): description = 'new ' + description

        # Some generic data based on gen type
        gen_type = generic_tech['generation_type'].upper()
        input_comm = translator['generator_types'][gen_type]['input_comm']
        output_comm = translator['generator_types'][gen_type]['output_comm']
        flag = translator['generator_types'][gen_type]['flag']
        tech_sets = translator['generator_types'][gen_type]['tech_sets']
        include_fuel_cost = translator['generator_types'][gen_type]['include_fuel_cost'] == 'true'

        # Some generic data based on units
        cost_invest = translator['units']['cost_invest']['conversion_factor'] * generic_tech['total_project_cost_2020_CAD_per_kW']
        cost_fixed = translator['units']['cost_fixed']['conversion_factor'] * generic_tech['fixed_om_cost_CAD_per_MWyear']
        cost_variable = translator['units']['cost_variable']['conversion_factor'] * generic_tech['variable_om_cost_CAD_per_MWh']
        if include_fuel_cost: cost_variable += translator['units']['cost_fuel']['conversion_factor'] * generic_tech['average_fuel_price_CAD_per_GJ']
        emis_act = translator['units']['emission_activity']['conversion_factor'] * generic_tech['carbon_emissions_tCO2eq_per_MWh']


        # Skip existing variants with no existing capacity (unused)
        if is_exs(tech) and tech not in rtv_data[region].keys(): continue

        
        # commodities
        curs.execute(f"""INSERT OR IGNORE INTO
                    commodities(comm_name, flag)
                    VALUES("{input_comm}", "p")""")
        curs.execute(f"""INSERT OR IGNORE INTO
                    commodities(comm_name, flag)
                    VALUES("{output_comm}", "p")""")
        

        # Add to specified sets
        if tech_sets is not None:
            for tech_set in tech_sets.split(','):
                # Doing insert or ignore as a better descriptor might be present
                curs.execute(f"""INSERT OR IGNORE INTO
                            {tech_set}(tech, notes)
                            VALUES('{tech}', '{description}')""")


        # LifetimeTech
        if 'HYD' in tech and params['no_hydro_retirement'] == 'true': life = 200
        else: life = generic_tech['service_life_years']
        curs.execute(f"""REPLACE INTO
                    LifetimeTech(regions, tech, life, life_notes)
                    VALUES("{region}", "{tech}", "{life}", "{description}")""")


        # CapacityToActivity
        curs.execute(f"""REPLACE INTO
                    CapacityToActivity(regions, tech, c2a, c2a_notes)
                    VALUES("{region}", "{tech}", "{config.c2a}", "{config.c2a_unit}")""")
        

        # RampUp and RampDown
        ramp_rate = generic_tech['ramp_rate_percent_per_min']
        if ramp_rate is not None:
            ramp_rate = translator['units']['ramp_rate']['conversion_factor'] * float(ramp_rate)
            if 0.0 < ramp_rate < 1.0:
                curs.execute(f"""REPLACE INTO
                            RampUp(regions, tech, ramp_up)
                            VALUES("{region}", "{tech}", "{ramp_rate}")""")
                curs.execute(f"""REPLACE INTO
                            RampDown(regions, tech, ramp_down)
                            VALUES("{region}", "{tech}", "{ramp_rate}")""")
                curs.execute(f"""REPLACE INTO
                            tech_ramping(tech, notes)
                            VALUES("{tech}", "{description}")""")


        # CostInvest
        if cost_invest != 0 and is_new(tech):
            for period in model_periods:
                cost_invest = translator['units']['cost_invest']['conversion_factor'] * evolving_cost[tech][str(period) + '_CAD_per_kW']
                curs.execute(f"""REPLACE INTO
                            CostInvest(regions, tech, vintage, cost_invest, cost_invest_units, cost_invest_notes)
                            VALUES("{region}", "{tech}", "{period}", "{cost_invest}", "{translator['units']['cost_invest']['CANOE_unit']}", "{description}")""")
    

        # Give all techs future vintages
        if tech not in rtv_data[region].keys():
            rtv_data[region][tech] = dict()
        [rtv_data[region][tech].update({period: {'capacity': 0, 'description': description}}) for period in model_periods]

        for vint in rtv_data[region][tech]:
            
            # Only existing techs for past vintages and new techs for future vintages
            if vint in model_periods and is_exs(tech): continue
            elif vint not in model_periods and is_new(tech): continue

            # This is a list of projects for existing tech, or generic for new tech
            description = rtv_data[region][tech][vint]['description']


            # technologies
            curs.execute(f"""REPLACE INTO
                        technologies(tech, flag, sector, tech_desc)
                        VALUES("{tech}", "{flag}", "electric", "{description}")""")


            # Efficiency
            if "ethos" in input_comm:
                # Efficiency is arbitrary for ethos
                curs.execute(f"""REPLACE INTO
                            Efficiency(regions, input_comm, tech, vintage, output_comm, efficiency, eff_notes)
                            VALUES("{region}", "{input_comm}", "{tech}", "{vint}", "{output_comm}", 1, "{description}")""")
            elif eff is None:
                # CODERS database does not provide an efficiency so don't override an existing manual entry
                curs.execute(f"""INSERT OR IGNORE INTO
                            Efficiency(regions, input_comm, tech, vintage, output_comm, eff_notes)
                            VALUES("{region}", "{input_comm}", "{tech}", "{vint}", "{output_comm}", "{description}")""")
            else:
                # CODERS database provides an efficiency
                curs.execute(f"""REPLACE INTO
                            Efficiency(regions, input_comm, tech, vintage, output_comm, efficiency, eff_notes)
                            VALUES("{region}", "{input_comm}", "{tech}", "{vint}", "{output_comm}", "{eff}", "{description}")""")
            
            # EmissionActivity
            if emis_act != 0:
                curs.execute(f"""REPLACE INTO
                            EmissionActivity(regions, emis_comm, input_comm, tech, vintage, output_comm, emis_act, emis_act_units, emis_act_notes)
                            VALUES("{region}", "{translator['units']['emission_commodity']['CANOE_unit']}", "{input_comm}", "{tech}", "{vint}", "{output_comm}",
                            "{emis_act}", "{translator['units']['emission_activity']['CANOE_unit']}", "{description}")""")

            for period in model_periods:
                
                if vint > period or vint + life <= period: continue

                # CostFixed
                if cost_fixed != 0:
                    curs.execute(f"""REPLACE INTO
                                CostFixed(regions, periods, tech, vintage, cost_fixed, cost_fixed_units, cost_fixed_notes)
                                VALUES("{region}", "{period}", "{tech}", "{vint}", "{cost_fixed}", "{translator['units']['cost_fixed']['CANOE_unit']}", "{description}")""")

                # CostVariable
                if cost_variable != 0:
                    curs.execute(f"""REPLACE INTO
                                CostVariable(regions, periods, tech, vintage, cost_variable, cost_variable_units, cost_variable_notes)
                                VALUES("{region}", "{period}", "{tech}", "{vint}", "{cost_variable}", "{translator['units']['cost_variable']['CANOE_unit']}", "{description}")""")



"""
##############################################################
    Inter-regional interties
##############################################################
"""

# Regional interfaces
# Get flows and fix for each boundary
# Do this up here so it doesn't slam the CODERS database twice for no reason
intertie_flows = dict()
for interties in translator['transfer_regions'].keys():

    base_tech = translator['generator_types']['INTERTIE']['CANOE_tech']
    tech = base_tech + "-" + translator['transfer_regions'][interties]['tech']

    # There are multiple interties per some region boundaries so skip duplicates
    if tech in intertie_flows.keys(): continue

    region_1 = translator['transfer_regions'][interties]['region_1']
    region_2 = translator['transfer_regions'][interties]['region_2']

    region_1_CANOE = translator['regions'][region_1]['CANOE_region']
    region_2_CANOE = translator['regions'][region_2]['CANOE_region']

    # Do not represent interties outside the model
    if region_1_CANOE == 'EX' and region_2_CANOE == 'EX': continue

    # Get 8760 transfers from the data year for this boundary and convert MWh to PJ
    conv_factor = translator['units']['activity']['conversion_factor']
    from_region_1, from_region_2 = intertie_transfers.get_transfered_mwh(region_1, region_2, translator['transfer_regions'][interties]['type'], from_cache=from_cache)
    intertie_flows[tech] = {region_1_CANOE: conv_factor*from_region_1, region_2_CANOE: conv_factor*from_region_2}


interfaces = coders_api.get_json(end_point='interface_capacities',from_cache=from_cache)

interface_techs = dict() # keys are CANOE techs

elc_comm = translator['generator_types']['INTERTIE']['input_comm']
ex_comm = translator['generator_types']['INTERTIE']['output_comm']

# Remember that everything here runs twice, regions 1-2 then 2-1
for interface in interfaces:

    interties = interface['associated_interties']

    base_tech = translator['generator_types']['INTERTIE']['CANOE_tech']
    tech = base_tech + "-" + translator['transfer_regions'][interties]['tech']

    from_region = translator['regions'][interface['export_from'].upper()]['CANOE_region']
    to_region = translator['regions'][interface['export_to'].upper()]['CANOE_region']

    # Don't represent interties outside the model or interties with insufficient data
    if from_region == 'EX' and to_region == 'EX': continue
    if (from_region == 'EX') != (to_region == 'EX') and intertie_flows[tech][from_region] is None: continue

    if tech not in interface_techs.keys():
        interface_techs[tech] = {
                'description': string_cleaner(interties),
                'regions': [from_region, to_region],
                'transfers_from': {from_region: intertie_flows[tech][from_region], to_region: intertie_flows[tech][to_region]},
                'capacity_from': {from_region: {'summer': 0, 'winter': 0}, to_region: {'summer': 0, 'winter': 0}},
                'efficiency': 1.0
            }
    elif string_cleaner(interties) not in interface_techs[tech]['description']:
        interface_techs[tech]['description'] += ' - ' + string_cleaner(interties)

    # CODERS gives different capacities for summer/winter and for directions of flow -> capacity factor
    summer_capacity = translator['units']['capacity']['conversion_factor'] * interface['summer_capacity_mw']
    winter_capacity = translator['units']['capacity']['conversion_factor'] * interface['winter_capacity_mw']

    # Take the largest of summer/winter capacity then aggregate all interties per region boundary
    interface_techs[tech]['capacity_from'][from_region]['summer'] += summer_capacity
    interface_techs[tech]['capacity_from'][from_region]['winter'] += winter_capacity



for tech in interface_techs.keys():

    interface = interface_techs[tech]
    
    # Max capacity is largest of both directions and summer/winter (TEMOA demands a single capacity per intertie)
    max_capacity = max(sum([list(v.values()) for v in list(interface['capacity_from'].values())],[])) # it works dont mess with it
    if max_capacity <= 0: continue # zero capacity comes up with retired interfaces

    # Some interface flows exceed rated capacity so take max hourly flow as max cap and convert from PJ/h to GW
    # This is for fixed-flow model boundary interfaces
    if (interface['regions'][0] == 'EX') != (interface['regions'][1] == 'EX'):
        max_capacity = max( max(interface['transfers_from'][interface['regions'][0]]), max(interface['transfers_from'][interface['regions'][1]]) )
        max_capacity *= translator['units']['capacity']['conversion_factor'] / translator['units']['activity']['conversion_factor']

    description = interface['description']

    # technologies
    curs.execute(f"""REPLACE INTO
                technologies(tech, flag, sector, tech_desc)
                VALUES("{tech}", "p", "electric", "{description}")""")
    
    # tech_exchange
    curs.execute(f"""REPLACE INTO
                tech_exchange(tech, notes)
                VALUES("{tech}", "{description}")""")
    
    # tech_curtailment set as flows are fixed
    curs.execute(f"""REPLACE INTO
                tech_curtailment(tech, notes)
                VALUES("{tech}", "{description}")""")
    

    # Fill tables for r1-r2 and r2-r1
    for r in [0,1]:

        from_region = interface['regions'][r]
        to_region = interface['regions'][1-r]
        region = from_region + '-' + to_region

        input_comm = ex_comm if from_region == "EX" else elc_comm
        output_comm = ex_comm if to_region == "EX" else elc_comm

        # commodities
        curs.execute(f"""INSERT OR IGNORE INTO
                    commodities(comm_name, flag)
                    VALUES("{input_comm}", "p")""")
        curs.execute(f"""INSERT OR IGNORE INTO
                    commodities(comm_name, flag)
                    VALUES("{output_comm}", "p")""")

        # Note describing fixed flow interties
        fixed_flow_note = params['intertie_fixed_flow_note'].replace("<year>", config.params['default_data_year'])

        if from_region == 'EX' and to_region == 'EX': continue # if not representing all provinces

        # ExistingCapacity
        curs.execute(f"""REPLACE INTO
                    ExistingCapacity(regions, tech, vintage, exist_cap, exist_cap_units, exist_cap_notes)
                    VALUES("{region}", "{tech}", 2020, "{max_capacity}", "{translator['units']['capacity']['CANOE_unit']}", "{description}")""")

        # LifetimeTech
        curs.execute(f"""REPLACE INTO
                    LifetimeTech(regions, tech, life, life_notes)
                    VALUES("{region}", "{tech}", 200, "does not retire")""")
        
        # CapacityToActivity
        curs.execute(f"""REPLACE INTO
                    CapacityToActivity(regions, tech, c2a, c2a_notes)
                    VALUES("{region}", "{tech}", "{config.c2a}", "{config.c2a_unit}")""")
        
        # CapacityFactorTech
        # Endogenous intertie, set summer/winter to/from capacities
        if from_region != 'EX' and to_region != 'EX':

            for hour in range(8760):

                season = config.seas_8760[hour]
                time_of_day = config.tofd_8760[hour]

                summer_winter = translator['time'][hour]['summer_winter']
                capacity = interface['capacity_from'][from_region][summer_winter]

                curs.execute(f"""REPLACE INTO
                            CapacityFactorTech(regions, season_name, time_of_day_name, tech, cf_tech, cf_tech_notes)
                            VALUES("{region}", "{season}", "{time_of_day}", "{tech}", "{capacity/max_capacity}", "{description}")""")
        
        # Intertie crosses model boundary, fix hourly flow
        elif (from_region == 'EX') != (to_region == 'EX'):

            for hour in range(8760):

                season = config.seas_8760[hour]
                time_of_day = config.tofd_8760[hour]

                cf = interface['transfers_from'][from_region][hour]/max_capacity/1000

                curs.execute(f"""REPLACE INTO
                            CapacityFactorTech(regions, season_name, time_of_day_name, tech, cf_tech, cf_tech_notes)
                            VALUES("{region}", "{season}", "{time_of_day}", "{tech}", "{cf}", "{fixed_flow_note}")""")
        
        for period in model_periods:

            # Efficiency
            # No intertie efficiencies in CODERS right now so don't override manual data
            curs.execute(f"""INSERT OR IGNORE INTO
                        Efficiency(regions, input_comm, tech, vintage, output_comm, efficiency)
                        VALUES("{region}", "{input_comm}", "{tech}", 2020, "{output_comm}", 1)""")



"""
##############################################################
    Dummy transmission techs
##############################################################
"""

# Transmission techs ELC_TX <--> ELC_DX --> D_ELC
tx_techs = ["TX_TO_DX", "DX_TO_TX"]
dummy_techs = ["DX_TO_DEM", "G_TO_TX", "GRPS_TO_TX"]
for tx_tech in tx_techs + dummy_techs:
    #technologies
    curs.execute(f"""REPLACE INTO
                technologies(tech, flag, sector, tech_desc)
                VALUES("{translator['generator_types'][tx_tech]['CANOE_tech']}", "p", "electric", "Transmission dummy tech")""")

# Regional parameters
ca_sys_params = coders_api.get_json(end_point='CA_system_parameters',from_cache=from_cache)
for province in ca_sys_params:

    region = translator['regions'][province['province'].upper()]['CANOE_region']

    if region == 'EX': continue # if not representing all provinces

    # PlanningReserveMargin
    reserve_margin = province['reserve_requirements_percent']
    curs.execute(f"""REPLACE INTO
                PlanningReserveMargin(regions, reserve_margin)
                VALUES("{region}", "{reserve_margin}")""")
    
    # Transmission loss techs
    line_loss = province["system_line_losses_percent"]
    for tx_tech in tx_techs + dummy_techs:
        tech = translator['generator_types'][tx_tech]['CANOE_tech']
        input_comm = translator['generator_types'][tx_tech]['input_comm']
        output_comm = translator['generator_types'][tx_tech]['output_comm']

        # commodities
        curs.execute(f"""INSERT OR IGNORE INTO
                    commodities(comm_name, flag)
                    VALUES("{input_comm}", "p")""")
        curs.execute(f"""INSERT OR IGNORE INTO
                    commodities(comm_name, flag)
                    VALUES("{output_comm}", "p")""")

        # Eff is line loss for TX <-> DX or 1.0 for dummy techs
        eff = 1.0 - line_loss if tx_tech in tx_techs else 1

        # Efficiency
        curs.execute(f"""REPLACE INTO
                    Efficiency(regions, input_comm, tech, vintage, output_comm, efficiency)
                    VALUES("{region}", "{input_comm}", "{tech}", {model_periods[0]}, "{output_comm}", {eff})""")



"""
##############################################################
    Some final input file constraints
##############################################################
"""

# TODO could probably generalise this step to all constraint tables
# MaxCapacity
for region in all_regions:
    if region == 'EX': continue
    
    for tech in config.cap_limits[region].index:
        for period in model_periods:

            max_cap = float(config.cap_limits[region].loc[tech, period]) * translator['units']['capacity']['conversion_factor']

            curs.execute(f"""REPLACE INTO
                         MaxCapacity(regions, periods, tech, maxcap, maxcap_units)
                         VALUES('{region}', {period}, '{tech}', {max_cap}, '{translator['units']['capacity']['CANOE_unit']}')""")
        


conn.commit()
conn.close()

print(f"CODERS API data pulled into {os.path.basename(database_file)}")