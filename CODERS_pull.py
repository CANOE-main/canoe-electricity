"""
This script pulls data from the CODERS database and fills a TEMOA schema 
Written by Ian David Elder for the TEMOA Canada / CANOE model
"""



import requests
import sqlite3
import shutil
import os
import intertie_transfers
from string_cleaner import string_cleaner
from datetime import date
import solar_capacity_factor
import numpy as np
import coders_data



# Pull CODERS data from the local cache or download it new
from_cache = True



# Get the schema, target, and database translation files
this_dir = os.path.realpath(os.path.dirname(__file__)) + "/"
schema_file = this_dir + "temoa_schema.sqlite"
database_file = this_dir + "coders_db.sqlite"
translation_file = this_dir + "CODERS_CANOE_translation.sqlite"

# If db does not exist make a copy of the schema
if not os.path.exists(database_file):
    shutil.copy(schema_file, database_file)



# Connect to the translator file
conn = sqlite3.connect(translation_file)
curs = conn.cursor()

# Convert translator database into a dictionary to speed things up
# usage: translator['table name']['value of first column']['column value needed']
translator = dict()

# Get CODERS reference
curs.execute("""SELECT reference FROM coders_reference""")
reference = curs.fetchone()[0] + str(date.today())

# Get future model periods
curs.execute("""SELECT periods FROM model_periods""")
model_periods = [period[0] for period in curs.fetchall()]

# Get all regions
curs.execute("""SELECT CANOE_region FROM regions""")
all_regions = set(region[0] for region in curs.fetchall())

# Get emission commodity
curs.execute("""SELECT CANOE_unit FROM units WHERE metric = 'emission_commodity'""")
emis_comm = curs.fetchone()[0]

# Get capacity to activity
fetch = curs.execute("""SELECT CANOE_unit, conversion_factor FROM units WHERE metric = 'capacity_to_activity'""").fetchone()
c2a_unit, c2a = fetch[0], fetch[1]

# hour out of 8760 -> time of day or season name
curs.execute("""SELECT time_of_day FROM time""")
tofd_8760 = [tofd[0] for tofd in curs.fetchall()]
curs.execute("""SELECT season FROM time""")
seas_8760 = [seas[0] for seas in curs.fetchall()]



curs.execute("SELECT name FROM sqlite_master WHERE type='table';")
all_tables = [table[0] for table in curs.fetchall()]

for table in all_tables:
    translator.update({table: dict()})

    rows = curs.execute("SELECT * FROM " + table)
    column_names = [column[0] for column in rows.description]
    
    rows = rows.fetchall()

    for r in range(len(rows)):
        translator[table].update({rows[r][0]: dict()})

        for c in range(len(column_names)):
            translator[table][rows[r][0]].update({column_names[c]: rows[r][c]})



# Get global values
rows = curs.execute("SELECT * FROM global_values")
column_names = [column[0] for column in rows.description]
rows = rows.fetchall()

global_values = list()
for r in range(len(rows)):

    global_value = dict()
    global_values.append(global_value)

    for c in range(len(column_names)):
        global_value.update({column_names[c]: rows[r][c]})


# Close connection to translator
conn.close()



# Connect to the new database file
conn = sqlite3.connect(database_file)
curs = conn.cursor() # Cursor object interacts with the sqlite db

# Get times of day
curs.execute("""SELECT t_day FROM time_of_day""")
times_of_day = [t_day[0] for t_day in curs.fetchall()]

# Collect generic tech data. Need this now to get lifetimes for viable existing vintages
generic_json = coders_data.get_json(end_point='generation_generic',from_cache=from_cache)
generic_techs = dict({translator['generator_types'][tech['generation_type'].upper()]['CANOE_tech']: tech for tech in generic_json})

# Collect existing generator data
existing_gen = coders_data.get_json(end_point='generators',from_cache=from_cache)

# Collect evolving cost data
cost_json = coders_data.get_json(end_point='generation_cost_evolution',from_cache=from_cache)
evolving_cost = dict({translator['generator_types'][tech['gen_type'].upper()]['CANOE_tech']: tech for tech in cost_json})

# Add future model periods
for period in model_periods: 
    curs.execute(f"""INSERT OR IGNORE INTO
                time_periods(t_periods, flag)
                VALUES({period}, "f")""")

# Add regions
for region in all_regions:
    curs.execute(f"""INSERT OR IGNORE INTO
                    regions(regions)
                    VALUES("{region}")""")



# Add storage technology data
storage_exs = coders_data.get_json(end_point='storage',from_cache=from_cache)

old_storage_techs = set() # Storage techs without duration disaggregation to be removed
for storage in storage_exs:

    if storage['closure_year'] <= model_periods[0]:
        print(f"Existing storage {storage['project_name']} would retire before first model period and so was excluded.")

    # Get the storage tech name e.g. E_BAT_4H
    CODERS_gen_type = storage['generation_type'].upper()
    duration = int(round(storage['duration']))
    CANOE_tech = translator['generator_types'][CODERS_gen_type]['CANOE_tech']
    tech = f"{CANOE_tech}_{duration}H"

    # Some nomenclature differences between merged tables
    storage.update({'install_capacity_in_mw': storage['storage_capacity_in_mw']})
    storage.update({'gen_type': tech}) # Updated duration-tagged tech

    # Have to add updated duration-tagged tech to translator
    translator['generator_types'].update({tech: dict()})
    translator['generator_types'][tech].update({'CANOE_tech': tech})

    try:
        generic_techs.update({tech: generic_techs[CANOE_tech]})
        evolving_cost.update({tech: evolving_cost[CANOE_tech]})
        existing_gen.append(storage)
    except:
        print(f"""Existing storage technology {CODERS_gen_type} has no generic data and was excluded. Capacity: {storage['storage_capacity_in_mw']} MW""")
        continue

    old_storage_techs.add(CANOE_tech)

    for region in all_regions:
        if region == 'EX': continue

        notes = "1 hour storage" if duration == 1 else str(duration) + " hours storage"

        # Can use insert or ignore here as the tech name is now tied to the duration
        curs.execute(f"""REPLACE INTO
                    StorageDuration(regions, tech, duration, duration_notes)
                    VALUES("{region}", "{tech}", "{duration}", "{notes}")""")

for old_tech in old_storage_techs: generic_techs.pop(old_tech, None)



# Keep track of data aggregated by tech, vintage and region
rtv_data = dict()

# ExistingCapacity
for generator in existing_gen:

    capacity = generator['install_capacity_in_mw']
    if capacity <= 0:
        print(f"Existing {region} generator {generator['project_name']} has {capacity} MW capacity and so was excluded")
        continue
    
    tech = translator['generator_types'][generator['gen_type'].upper()]['CANOE_tech']
    generator_name = f"{generator['project_name']} ({generator['owner']})"
    region = translator['regions'][generator['copper_balancing_area'].upper()]['CANOE_region']

    if region == 'EX': continue # If not representing all provinces

    vint = 2020 if 'HYD' in tech else generator['previous_renewal_year'] # Hydro doesn't retire so might as well aggregate
    if vint is None: vint = generator['start_year']
    vint = min(2023,int(5 * round(float(vint)/5))) # Remove this line to have yearly vintages

    curs.execute(f"""INSERT OR IGNORE INTO
                time_periods(t_periods, flag)
                VALUES({vint}, "e")""")

    life = generic_techs[tech]['service_life_years']

    # Skip non-viable vintages
    if vint + life <= model_periods[0]:
        print(f"Existing {region} generator {generator['project_name']} would retire before first model period and so was excluded. Vintage: {vint}, life: {life}")
        continue

    if region not in rtv_data.keys(): rtv_data.update({region: dict()})
    if tech not in rtv_data[region].keys(): rtv_data[region].update({tech: dict()})
    if vint not in rtv_data[region][tech].keys(): rtv_data[region][tech].update({vint: dict({'capacity': capacity, 'description': generator_name})})
    else:
        rtv_data[region][tech][vint]['capacity'] += capacity
        rtv_data[region][tech][vint]['description'] += " - " + generator_name

    exist_cap = translator['units']['capacity']['conversion_factor'] * rtv_data[region][tech][vint]['capacity']
    exist_cap_notes = rtv_data[region][tech][vint]['description']

    curs.execute(f"""REPLACE INTO
                ExistingCapacity(regions, tech, vintage, exist_cap, exist_cap_units, exist_cap_notes)
                VALUES("{region}", "{tech}", "{vint}", "{exist_cap}", "{translator['units']['capacity']['CANOE_unit']}", "{string_cleaner(exist_cap_notes)}")""")



# Add generic technology data
for tech in list(generic_techs.keys()):

    generic_tech = generic_techs[tech]

    # Collect some generic data for the tech
    eff = generic_tech['efficiency']

    description = generic_tech['description']
    if 'project_name' in generic_tech.keys(): description += " - " + generic_tech['project_name']
    description = string_cleaner(description)

    input_comm = translator['generator_types'][generic_tech['generation_type'].upper()]['input_comm']
    output_comm = translator['generator_types'][generic_tech['generation_type'].upper()]['output_comm']

    cost_invest = translator['units']['cost_invest']['conversion_factor'] * generic_tech['overnight_capital_cost_CAD_per_kW']
    cost_fixed = translator['units']['cost_fixed']['conversion_factor'] * generic_tech['fixed_om_cost_CAD_per_MWyear']
    cost_variable = translator['units']['cost_variable']['conversion_factor'] * generic_tech['variable_om_cost_CAD_per_MWh']
    emis_act = translator['units']['emission_activity']['conversion_factor'] * generic_tech['carbon_emissions_tCO2eq_per_MWh']

    # technologies
    curs.execute(f"""INSERT OR IGNORE INTO
                technologies(tech, tech_desc)
                VALUES("{tech}", "{description}")""")
    
    # commodities
    for comm in (input_comm, output_comm):
        curs.execute(f"""INSERT OR IGNORE INTO
                    commodities(comm_name, flag)
                    VALUES("{comm}", "p")""")
        


    for region in all_regions:
        if region == 'EX': continue


        # LifetimeTech
        life = 200 if 'HYD' in tech else generic_tech['service_life_years']
        curs.execute(f"""REPLACE INTO
                    LifetimeTech(regions, tech, life, life_notes)
                    VALUES("{region}", "{tech}", "{life}", "{description}")""")


        # CapacityToActivity
        curs.execute(f"""REPLACE INTO
                    CapacityToActivity(regions, tech, c2a, c2a_notes)
                    VALUES("{region}", "{tech}", "{c2a}", "{c2a_unit}")""")
        

        # RampUp and RampDown
        ramp_rate = generic_tech['ramp_rate_percent_per_min']
        if ramp_rate is not None:
            ramp_rate = translator['units']['ramp_rate']['conversion_factor'] * float(ramp_rate)
            if ramp_rate < 1.0:
                curs.execute(f"""REPLACE INTO
                            RampUp(regions, tech, ramp_up)
                            VALUES("{region}", "{tech}", "{ramp_rate}")""")
                curs.execute(f"""REPLACE INTO
                            RampDown(regions, tech, ramp_down)
                            VALUES("{region}", "{tech}", "{ramp_rate}")""")


        # CostInvest
        if cost_invest != 0:
            for period in model_periods:
                cost_invest = translator['units']['cost_invest']['conversion_factor'] * evolving_cost[tech][str(period) + '_CAD_per_kW']
                curs.execute(f"""REPLACE INTO
                            CostInvest(regions, tech, vintage, cost_invest, cost_invest_units, cost_invest_notes)
                            VALUES("{region}", "{tech}", "{period}", "{cost_invest}", "{translator['units']['cost_invest']['CANOE_unit']}", "{description}")""")
    

        # All techs should have future vintages
        if tech not in rtv_data[region].keys():
            rtv_data[region].update({tech: dict()})
        [rtv_data[region][tech].update({period: {'capacity': 0, 'description': description}}) for period in model_periods]

        for vint in rtv_data[region][tech]:

            description = string_cleaner(rtv_data[region][tech][vint]['description'])

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
                            VALUES("{region}", "{emis_comm}", "{input_comm}", "{tech}", "{vint}", "{output_comm}", "{emis_act}", "{translator['units']['emission_activity']['CANOE_unit']}", "{description}")""")

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
        
            
        # CapacityFactorTech
        # regions season_name time_of_day_name tech cf_tech
        # Min/Max annual CF table?

        # CapacityCredit?



# Regional interfaces
# Get variable prices for each set of interties as defined in interface_capacities
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

    from_region_1, from_region_2 = intertie_transfers.get_transfers(region_1, region_2, translator['transfer_regions'][interties]['type'], from_cache=from_cache)

    intertie_flows.update({tech: {region_1_CANOE: from_region_1, region_2_CANOE: from_region_2}})


interfaces = coders_data.get_json(end_point='interface_capacities',from_cache=from_cache)

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
        interface_techs.update({
            tech: dict({
                'description': string_cleaner(interties),
                'regions': [from_region, to_region],
                'transfers_from': {from_region: intertie_flows[tech][from_region], to_region: intertie_flows[tech][to_region]},
                'capacity_from': {from_region: {'summer': 0, 'winter': 0}, to_region: {'summer': 0, 'winter': 0}},
                'efficiency': 1.0
            })
        })
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
    max_capacity = max(sum([list(v.values()) for v in list(interface['capacity_from'].values())],[])) # it works dont question it
    if max_capacity <= 0: continue # zero capacity comes up with retired interfaces

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

        if from_region == 'EX' and to_region == 'EX': continue # if not representing all provinces

        # FIXME The QC-ON interlink seems to significantly exceed capacity (4408/2750) so do this for now
        if (from_region == 'EX') != (to_region == 'EX'): max_capacity = 5

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
                    VALUES("{region}", "{tech}", "{c2a}", "{c2a_unit}")""")
        
        # CapacityFactorTech
        # Endogenous intertie, set summer/winter to/from capacities
        if from_region != 'EX' and to_region != 'EX':

            for hour in range(8760):

                season = seas_8760[hour]
                time_of_day = tofd_8760[hour]

                summer_winter = translator['time'][hour]['summer_winter']
                capacity = interface['capacity_from'][from_region][summer_winter]

                curs.execute(f"""REPLACE INTO
                            CapacityFactorTech(regions, season_name, time_of_day_name, tech, cf_tech, cf_tech_notes)
                            VALUES("{region}", "{season}", "{time_of_day}", "{tech}", "{capacity/max_capacity}", "{description}")""")
        
        # Intertie crosses model boundary, fix hourly flow
        elif (from_region == 'EX') != (to_region == 'EX'):

            for hour in range(8760):

                season = seas_8760[hour]
                time_of_day = tofd_8760[hour]

                cf = interface['transfers_from'][from_region][hour]/max_capacity/1000

                curs.execute(f"""REPLACE INTO
                            CapacityFactorTech(regions, season_name, time_of_day_name, tech, cf_tech, cf_tech_notes)
                            VALUES("{region}", "{season}", "{time_of_day}", "{tech}", "{cf}", "{description}")""")
        
        for period in model_periods:

            # Efficiency
            # No efficiencies in CODERS right now so don't override manual data
            input_comm = ex_comm if from_region == "EX" else elc_comm
            output_comm = ex_comm if to_region == "EX" else elc_comm
            curs.execute(f"""INSERT OR IGNORE INTO
                        Efficiency(regions, input_comm, tech, vintage, output_comm, efficiency)
                        VALUES("{region}", "{input_comm}", "{tech}", 2020, "{output_comm}", 1)""")



# Transmission techs ELC_TX <--> ELC_DX --> D_ELC
tx_techs = ["TX_TO_DX", "DX_TO_TX"]
dummy_techs = ["DX_TO_DEM", "G_TO_TX", "GRPS_TO_TX"]
for tx_tech in tx_techs + dummy_techs:
    curs.execute(f"""INSERT OR IGNORE INTO
                technologies(tech)
                VALUES("{translator['generator_types'][tx_tech]['CANOE_tech']}")""")
    curs.execute(f"""INSERT OR IGNORE INTO
                commodities(comm_name)
                VALUES("{translator['generator_types'][tx_tech]['input_comm']}")""")
    curs.execute(f"""INSERT OR IGNORE INTO
                commodities(comm_name)
                VALUES("{translator['generator_types'][tx_tech]['output_comm']}")""")

# Regional parameters
ca_sys_params = coders_data.get_json(end_point='CA_system_parameters',from_cache=from_cache)
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
        input = translator['generator_types'][tx_tech]['input_comm']
        output = translator['generator_types'][tx_tech]['output_comm']

        eff = 1.0 - line_loss if tx_tech in tx_techs else 1

        for period in model_periods:
            # Efficiency
            curs.execute(f"""REPLACE INTO
                        Efficiency(regions, input_comm, tech, vintage, output_comm, efficiency)
                        VALUES("{region}", "{input}", "{tech}", {model_periods[0]}, "{output}", "{eff}")""")
                 


# Overwrite with global values from translator database
for region in all_regions:
    for global_value in global_values:

        if region == 'EX': continue
        
        curs.execute(f"""REPLACE INTO
                     {global_value['table']}(regions, tech, {global_value['columns']})
                     VALUES('{region}', '{global_value['CANOE_tech']}', {global_value['global_values']})""")
        


conn.commit()
conn.close()