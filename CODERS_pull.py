"""
This script pulls data from the CODERS database and fills a TEMOA schema 
Written by Ian David Elder for the TEMOA Canada / CANOE model
"""

import sqlite3
import pandas as pd
import os
import intertie_transfers
from utils import string_cleaner
import coders_api
from setup import config



def aggregate():

    # Connect to the new database file
    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor() # Cursor object interacts with the sqlite db

    ## Collect some general data
    # Existing generators
    _existing_json, df_existing, date_accessed = coders_api.get_data(end_point='generators')
    config.references['generators'] = config.params['coders_reference'].replace("<date>", date_accessed)
    df_existing['tech'] = df_existing['gen_type'].str.upper().map(config.tech_map)

    # Existing storage
    _storage_exs, df_storage, date_accessed = coders_api.get_data(end_point='storage')
    config.references['storage'] = config.params['coders_reference'].replace("<date>", date_accessed)
    df_storage['tech'] = df_storage['generation_type'].str.upper().map(config.tech_map)

    # Generic generator data
    _generic_json, df_generic, date_accessed = coders_api.get_data(end_point='generation_generic')
    config.references['generation_generic'] = config.params['coders_reference'].replace("<date>", date_accessed)
    df_generic['tech'] = df_generic['generation_type'].str.upper().map(config.tech_map) # set index to canoe tech
    df_generic.set_index('tech', inplace=True)
    df_generic = df_generic[~df_generic.index.duplicated(keep='first')] # drop duplicate rows

    # Capital cost evolution
    _cost_json, df_cost, date_accessed = coders_api.get_data(end_point='generation_cost_evolution')
    config.references['generation_cost_evolution'] = config.params['coders_reference'].replace("<date>", date_accessed)
    df_cost['tech'] = df_cost['gen_type'].str.upper().map(config.tech_map) # set index to canoe tech
    df_cost.set_index('tech', inplace=True)
    df_cost = df_cost[~df_cost.index.duplicated(keep='first')] # drop duplicate rows



    """
    ##############################################################
        Fill basic tables
    ##############################################################
    """

    # Add default global discount rate. No index on this table so clear it first.
    curs.execute("DELETE FROM GlobalDiscountRate")
    curs.execute(f"INSERT INTO GlobalDiscountRate(rate) VALUES({config.params['global_discount_rate']})")

    # Add future model periods
    for period in config.model_periods: 
        curs.execute(f"""REPLACE INTO
                    time_periods(t_periods, flag)
                    VALUES({period}, "f")""")

    # Add regions
    for region in config.model_regions:
        description = "outside model" if region == "EX" else config.regions.loc[region, 'description']
        curs.execute(f"""REPLACE INTO
                        regions(regions, region_note)
                        VALUES("{region}", "{description}")""")
        
    # Add seasons and times of day
    for h, row in config.time.iterrows():
        curs.execute(f"""INSERT OR IGNORE INTO
                    time_season(t_season)
                    VALUES("{row['season']}")""")
        curs.execute(f"""INSERT OR IGNORE INTO
                    time_of_day(t_day)
                    VALUES("{row['time_of_day']}")""")

    # Add emission commodity TODO will need changing with additional emission types
    emis_comm = config.params['emissions_commodity']
    curs.execute(f"""REPLACE INTO
                commodities(comm_name, flag, comm_desc)
                VALUES('{emis_comm}', 'e', '{config.commodities.loc[emis_comm, 'description']}')""")
        


    # To determine whether a tech is existing or new
    is_exs = lambda tech: '-EXS' in tech
    is_new = lambda tech: '-NEW' in tech



    """
    ##############################################################
        Existing storage capacity
    ##############################################################
    """

    # Discard storage that would retire before first model period
    df_storage = df_storage.loc[df_storage['closure_year'] > config.model_periods[0]]

    # Convert to canoe regions and discard storage of excluded regions
    df_storage['region'] = df_storage['operating_region'].str.upper().map(config.region_map)
    df_storage = df_storage.loc[df_storage['region'].isin(config.model_regions)]

    # Nomenclature difference between storage and generic generation tables
    df_storage['install_capacity_in_mw'] = df_storage['storage_capacity_in_mw']

    # Keep track of outdated tech names to drop
    old_techs = set()

    for idx, row in df_storage.iterrows():

        # Get the storage tech name e.g. E_BAT_4H
        base_tech = row['tech']
        gen_type = row['generation_type'].upper()
        duration = int(round(row['duration']))

        if base_tech not in df_generic.index:
            print(f"""Existing storage technology {gen_type} has no generic data and was ignored!
                Site: {row['project_name']} ({row['owner']})
                Region: {region}
                Capacity: {row['storage_capacity_in_mw']} MW""")
            df_storage.drop(idx, inplace=True)
            continue
            
        # Update tech with duration tag
        tech = f"{base_tech}-{duration}H"
        df_storage.loc[idx, 'tech'] = tech

        # Update data tables to account for new tech labels
        old_techs.add(base_tech)
        config.technologies.loc[tech] = config.technologies.loc[base_tech]
        df_generic.loc[tech] = df_generic.loc[base_tech]
        df_cost.loc[tech] = df_cost.loc[base_tech]

        notes = "1 hour storage" if duration == 1 else str(duration) + " hours storage"

        # Can use insert or ignore here as the tech name is now tied to the duration
        curs.execute(f"""REPLACE INTO
                    StorageDuration(regions, tech, duration, duration_notes, reference)
                    VALUES("{region}", "{tech}-NEW", "{duration}", "{notes}", "{config.references['storage']}")""")
        curs.execute(f"""REPLACE INTO
                    StorageDuration(regions, tech, duration, duration_notes, reference)
                    VALUES("{region}", "{tech}-EXS", "{duration}", "{notes}", "{config.references['storage']}")""")
    
    # Add existing storage to existing generators table
    df_existing = pd.concat([df_existing, df_storage])

    # Drop old tech names from data tables
    for old_tech in old_techs:
        config.technologies.drop(old_tech, inplace=True)
        df_generic.drop(old_tech, inplace=True)
        df_cost.drop(old_tech, inplace=True)
    old_techs.clear()



    """
    ##############################################################
        Setup existing/new capacity batches (tech variants)
    ##############################################################
    """

    # Handle batches of new techs
    region_techs = dict() # All technologies by region
    for region in config.batched_cap.keys():

        region_techs[region] = list()

        # For techs with specified batch sizes get from csv
        for base_tech, row in config.technologies.iterrows():

            if base_tech not in df_generic.index:
                print(f"Technology {base_tech} has no generic data and was ignored!")
                continue
            
            # Number of specified new capacity batches. Default 1 if not specified and include_new is true
            n_batches = int(row['new_cap_batches']) if not pd.isna(row['new_cap_batches']) else 1

            if not row['include_new']: techs = [f"{base_tech}-EXS"] # No new capacity allowed
            elif n_batches > 1: techs = [f"{base_tech}-EXS", *[f"{base_tech}-NEW-{n}" for n in range(1,n_batches+1)]] # Specified batches
            else: techs = [f"{base_tech}-EXS", f"{base_tech}-NEW"] # Not specified or 1 so allow new and existing

            # Add all these techs to regional list of all techs
            region_techs[region].extend(techs)

            # Add base tech to removal list
            old_techs.add(base_tech)

            # Update data tables to account for new tech labels
            for tech in techs:
                config.technologies.loc[tech] = config.technologies.loc[base_tech]
                df_generic.loc[tech] = df_generic.loc[base_tech]

                # Evolving costs are only given for capital cost so only for new techs
                if is_new(tech): df_cost.loc[tech] = df_cost.loc[base_tech]

    # Drop old tech names from data tables
    for old_tech in old_techs:
        config.technologies.drop(old_tech, inplace=True)
        df_generic.drop(old_tech, inplace=True)
        df_cost.drop(old_tech, inplace=True)
    old_techs.clear()


    """
    ##############################################################
        Existing generation capacity
    ##############################################################
    """

    # Keep track of data aggregated by tech, vintage and region
    rtv_data = dict()

    # ExistingCapacity
    for idx, row in df_existing.iterrows():

        region = config.region_map[row['copper_balancing_area'].upper()]
        if not config.regions.loc[region, 'include']: continue # not including this region

        # Add existing tech tag
        tech = row['tech'] + '-EXS'

        description = f"{row['project_name']} ({row['owner']})"
        
        capacity = row['install_capacity_in_mw']
        if capacity <= 0:
            print(f"Existing {region} generator {row['project_name']} has {capacity} MW capacity and so was excluded")
            continue
        
        if 'HYD' in tech and config.params['no_hydro_retirement']:
            vint = 2020 # If hydro doesn't retire might as well aggregate
        else:
            vint = row['previous_renewal_year'] # take start of life as year of last renewal
            if vint is None: vint = row['start_year'] # if no renewal has occurred

        # Aggregate all other existing vintages by specified num years
        step = int(config.params['period_step'])
        vint = min(config.model_periods[0] - step, int(step * round(float(vint) / step))) # round to the nearest 5 years but before first model period

        # Add existing vintages as existing time periods
        curs.execute(f"""REPLACE INTO
                    time_periods(t_periods, flag)
                    VALUES({vint}, "e")""")

        life = df_generic.loc[tech, 'service_life_years']

        # Skip non-viable vintages
        if vint + life <= config.model_periods[0]:
            print(f"Existing {region} generator {row['project_name']} would retire before first model period and so was excluded. Vintage: {vint}, life: {life}")
            continue
        
        # Keeping a record of valid region-tech-vintage sets (existing only so far but future added later)
        if region not in rtv_data.keys(): rtv_data[region] = dict()
        if tech not in rtv_data[region].keys(): rtv_data[region][tech] = dict()
        if vint not in rtv_data[region][tech].keys(): rtv_data[region][tech][vint] = {'capacity': capacity, 'description': string_cleaner(description)}
        else:
            rtv_data[region][tech][vint]['capacity'] += capacity
            rtv_data[region][tech][vint]['description'] += " - " + string_cleaner(description)

        exist_cap = config.units.loc['capacity', 'conversion_factor'] * rtv_data[region][tech][vint]['capacity']
        exist_cap_notes = rtv_data[region][tech][vint]['description']

        # This overwrites each loop as new existing capacity is found
        curs.execute(f"""REPLACE INTO
                    ExistingCapacity(regions, tech, vintage, exist_cap, exist_cap_units, exist_cap_notes, reference, data_flags, dq_est)
                    VALUES("{region}", "{tech}", "{vint}", "{exist_cap}", "{config.units.loc['capacity', 'units']}",
                    "{string_cleaner(exist_cap_notes)}", "{config.references['generators']}", "coders", 1)""")



    """
    ##############################################################
        Generic technology data
    ##############################################################
    """

    # Add generic technology data
    for region in config.model_regions:

        for tech in region_techs[region]:

            # Skip existing variants with no existing capacity (unused)
            if is_exs(tech) and tech not in rtv_data[region].keys(): continue

            # Generic data on this tech
            generic_tech = df_generic.loc[tech]

            # Collect some generic data for the tech
            eff = generic_tech['efficiency']

            # Generate a tech description
            description = generic_tech['description']
            if is_exs(tech): description = 'existing ' + description
            elif is_new(tech): description = 'new ' + description

            # Some generic data based on gen type
            gen_type = generic_tech['generation_type'].upper()
            input_comm = config.technologies.loc[tech, 'input_comm']
            output_comm = config.technologies.loc[tech, 'output_comm']
            flag = config.technologies.loc[tech, 'flag']
            tech_sets = config.technologies.loc[tech, 'tech_sets']
            include_fuel_cost = config.technologies.loc[tech, 'include_fuel_cost']

            # Some generic data based on units
            cost_invest = config.units.loc['cost_invest', 'conversion_factor'] * generic_tech['total_project_cost_2020_CAD_per_kW']
            cost_fixed = config.units.loc['cost_fixed', 'conversion_factor'] * generic_tech['fixed_om_cost_CAD_per_MWyear']
            cost_variable = config.units.loc['cost_variable', 'conversion_factor'] * generic_tech['variable_om_cost_CAD_per_MWh']
            if include_fuel_cost: cost_variable += config.units.loc['cost_fuel', 'conversion_factor'] * generic_tech['average_fuel_price_CAD_per_GJ'] / float(generic_tech['efficiency'])
            emis_act = config.units.loc['emission_activity', 'conversion_factor'] * generic_tech['carbon_emissions_tCO2eq_per_MWh']
            
            # commodities. Doing this here in case a commodity is unused
            curs.execute(f"""REPLACE INTO
                        commodities(comm_name, flag, comm_desc)
                        VALUES('{input_comm}', '{config.commodities.loc[input_comm, 'flag']}', '{config.commodities.loc[input_comm, 'description']}')""")
            curs.execute(f"""REPLACE INTO
                        commodities(comm_name, flag, comm_desc)
                        VALUES('{output_comm}', '{config.commodities.loc[output_comm, 'flag']}', '{config.commodities.loc[output_comm, 'description']}')""")
            

            # Add to specified sets
            if not pd.isna(tech_sets):
                for tech_set in tech_sets.split(','):
                    curs.execute(f"""REPLACE INTO
                                {tech_set}(tech, notes)
                                VALUES('{tech}', '{description}')""")


            # LifetimeTech
            life = generic_tech['service_life_years']
            curs.execute(f"""REPLACE INTO
                        LifetimeTech(regions, tech, life, life_notes, reference, data_flags, dq_est)
                        VALUES("{region}", "{tech}", "{life}", "{description}", "{config.references['generation_generic']}", "coders", 1)""")


            # CapacityToActivity
            curs.execute(f"""REPLACE INTO
                        CapacityToActivity(regions, tech, c2a, c2a_notes)
                        VALUES("{region}", "{tech}", "{config.params['c2a']}", "{config.params['c2a_unit']}")""")
            

            # RampUp and RampDown
            ramp_rate = generic_tech['ramp_rate_percent_per_min']
            if ramp_rate is not None:
                ramp_rate = config.units.loc['ramp_rate', 'conversion_factor'] * float(ramp_rate)
                if 0.0 < ramp_rate < 1.0:
                    curs.execute(f"""REPLACE INTO
                                RampUp(regions, tech, ramp_up, reference, data_flags, dq_est)
                                VALUES("{region}", "{tech}", "{ramp_rate}", "{config.references['generation_generic']}", "coders", 3)""")
                    curs.execute(f"""REPLACE INTO
                                RampDown(regions, tech, ramp_down, reference, data_flags, dq_est)
                                VALUES("{region}", "{tech}", "{ramp_rate}", "{config.references['generation_generic']}", "coders", 3)""")
                    curs.execute(f"""REPLACE INTO
                                tech_ramping(tech, notes, reference)
                                VALUES("{tech}", "{description}", "{config.references['generation_generic']}")""")


            # CostInvest
            if cost_invest != 0 and is_new(tech):
                for period in config.model_periods:
                    cost_invest = config.units.loc['cost_invest', 'conversion_factor'] * df_cost.loc[tech, str(period) + '_CAD_per_kW']
                    curs.execute(f"""REPLACE INTO
                                CostInvest(regions, tech, vintage, cost_invest, cost_invest_units, cost_invest_notes, reference, data_flags, dq_est)
                                VALUES("{region}", "{tech}", "{period}", "{cost_invest}", "{config.units.loc['cost_invest', 'units']}",
                                "{description}", "{config.references['generation_cost_evolution']}", "coders", 1)""")
        

            # Give all techs future vintages
            if tech not in rtv_data[region].keys(): # applies to new techs
                rtv_data[region][tech] = dict()
            [rtv_data[region][tech].update({period: {'capacity': 0, 'description': description}}) for period in config.model_periods]

            for vint in rtv_data[region][tech]:
                
                # Only existing techs for past vintages and new techs for future vintages
                if vint in config.model_periods and is_exs(tech): continue
                elif vint not in config.model_periods and is_new(tech): continue

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
                                Efficiency(regions, input_comm, tech, vintage, output_comm, efficiency, eff_notes, reference, data_flags, dq_est)
                                VALUES("{region}", "{input_comm}", "{tech}", "{vint}", "{output_comm}", 1, "{description}", "{config.references['generation_generic']}", "coders", 1)""")
                elif eff is None:
                    # CODERS database does not provide an efficiency so don't override an existing manual entry
                    curs.execute(f"""INSERT OR IGNORE INTO
                                Efficiency(regions, input_comm, tech, vintage, output_comm, eff_notes, reference, data_flags, dq_est)
                                VALUES("{region}", "{input_comm}", "{tech}", "{vint}", "{output_comm}", "{description}", "{config.references['generation_generic']}", "coders", 1)""")
                else:
                    # CODERS database provides an efficiency
                    curs.execute(f"""REPLACE INTO
                                Efficiency(regions, input_comm, tech, vintage, output_comm, efficiency, eff_notes, reference, data_flags, dq_est)
                                VALUES("{region}", "{input_comm}", "{tech}", "{vint}", "{output_comm}", "{eff}", "{description}", "{config.references['generation_generic']}", "coders", 1)""")
                
                # EmissionActivity
                if emis_act != 0:
                    curs.execute(f"""REPLACE INTO
                                EmissionActivity(regions, emis_comm, input_comm, tech, vintage, output_comm, emis_act, emis_act_units, emis_act_notes, reference, data_flags, dq_est)
                                VALUES("{region}", "{config.commodities.loc[emis_comm, 'units']}", "{input_comm}", "{tech}", "{vint}", "{output_comm}",
                                "{emis_act}", "{config.commodities.loc[emis_comm, 'units']}", "{description}", "{config.references['generation_generic']}", "coders", 1)""")

                for period in config.model_periods:
                    
                    if vint > period or vint + life <= period: continue

                    # CostFixed
                    if cost_fixed != 0:
                        curs.execute(f"""REPLACE INTO
                                    CostFixed(regions, periods, tech, vintage, cost_fixed, cost_fixed_units, cost_fixed_notes, reference, data_flags, dq_est)
                                    VALUES("{region}", "{period}", "{tech}", "{vint}", "{cost_fixed}", "{config.units.loc['cost_fixed', 'units']}",
                                    "{description}", "{config.references['generation_generic']}", "coders", 1)""")

                    # CostVariable
                    if cost_variable != 0:
                        curs.execute(f"""REPLACE INTO
                                    CostVariable(regions, periods, tech, vintage, cost_variable, cost_variable_units, cost_variable_notes, reference, data_flags, dq_est)
                                    VALUES("{region}", "{period}", "{tech}", "{vint}", "{cost_variable}", "{config.units.loc['cost_variable', 'units']}",
                                    "{description}", "{config.references['generation_generic']}", "coders", 1)""")



    """
    ##############################################################
        Inter-regional interties
    ##############################################################
    """

    int_tech = config.trans_techs.loc['INTERTIE', 'tech']

    # Regional interfaces
    # Get flows and fix for each boundary
    # Do this up here so it doesn't slam the CODERS database twice for no reason
    intertie_flows = dict()
    for interties, row in config.trans_regions.iterrows():
        
        tech = int_tech + "-" + row['tag']

        # There are multiple interties per some region boundaries so skip duplicates
        if tech in intertie_flows.keys(): continue

        region_1_canoe = config.region_map[row['region_1']]
        region_2_canoe = config.region_map[row['region_2']]

        # Do not represent interties for provinces not included. Note us states always included
        if (region_1_canoe not in config.model_regions) and (region_2_canoe not in config.model_regions): continue

        # Get 8760 transfers from the data year for this boundary and convert MWh to PJ
        from_region_1, from_region_2 = intertie_transfers.get_transfered_mwh(row['region_1'], row['region_2'], row['type'])
        intertie_flows[tech] = {region_1_canoe: from_region_1, region_2_canoe: from_region_2}


    interfaces, df_interfaces, date_accessed = coders_api.get_data(end_point='interface_capacities')
    config.references['interface_capacities'] = config.params['coders_reference'].replace('<date>', date_accessed)

    interface_techs = dict() # keys are CANOE techs

    elc_comm = config.trans_techs.loc['INTERTIE', 'input_comm']
    ex_comm = config.trans_techs.loc['INTERTIE', 'output_comm']

    # Remember that everything here runs twice, regions 1-2 then 2-1
    for idx, row in df_interfaces.iterrows():

        interties = row['associated_interties']

        tech = int_tech + "-" + config.trans_regions.loc[interties, 'tag']

        from_region = config.region_map[row['export_from'].upper()]
        to_region = config.region_map[row['export_to'].upper()]

        # Don't represent interties outside the model or boundary interties with insufficient data
        if (from_region not in config.model_regions) and (to_region not in config.model_regions): continue
        if (from_region in config.model_regions) != (to_region in config.model_regions) and intertie_flows[tech][from_region] is None: continue

        # Prepare some data about this interface
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
        summer_capacity = config.units.loc['capacity', 'conversion_factor'] * row['summer_capacity_mw']
        winter_capacity = config.units.loc['capacity', 'conversion_factor'] * row['winter_capacity_mw']

        # Take the largest of summer/winter capacity then aggregate all interties per region boundary
        interface_techs[tech]['capacity_from'][from_region]['summer'] += summer_capacity
        interface_techs[tech]['capacity_from'][from_region]['winter'] += winter_capacity


    # Now that data is ready for each interface, add to database
    for tech, interface in interface_techs.items():
        
        # Max capacity is largest of both directions and summer/winter (TEMOA demands a single capacity per intertie)
        max_capacity = max( [max(val.values()) for val in list(interface_techs[tech]['capacity_from'].values())] ) # it works dont mess with it
        if max_capacity <= 0: continue # zero capacity comes up with retired interfaces

        # Some interface flows exceed rated capacity so take max hourly flow as max cap and convert from MWh/h to GW
        # This is for fixed-flow model boundary interfaces
        if (interface['regions'][0] in config.model_regions) != (interface['regions'][1] in config.model_regions):
            max_capacity = max( max(interface['transfers_from'][interface['regions'][0]]), max(interface['transfers_from'][interface['regions'][1]]) )
            max_capacity /= 1000 # MWh/h to GW

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

            input_comm = ex_comm if from_region not in config.model_regions else elc_comm
            output_comm = ex_comm if to_region not in config.model_regions else elc_comm

            # commodities
            curs.execute(f"""REPLACE INTO
                        commodities(comm_name, flag, comm_desc)
                        VALUES('{input_comm}', '{config.commodities.loc[input_comm, 'flag']}', '{config.commodities.loc[input_comm, 'description']}')""")
            curs.execute(f"""REPLACE INTO
                        commodities(comm_name, flag, comm_desc)
                        VALUES('{output_comm}', '{config.commodities.loc[output_comm, 'flag']}', '{config.commodities.loc[output_comm, 'description']}')""")

            # Note describing fixed flow interties
            fixed_flow_note = config.params['intertie_fixed_flow_note'].replace("<year>", str(config.params['default_data_year']))

            if from_region not in config.model_regions and to_region not in config.model_regions: continue # both regions outside model

            # ExistingCapacity
            curs.execute(f"""REPLACE INTO
                        ExistingCapacity(regions, tech, vintage, exist_cap, exist_cap_units, exist_cap_notes, reference, data_flags, dq_est)
                        VALUES("{region}", "{tech}", 2020, "{max_capacity}", "{config.units.loc['capacity', 'units']}",
                        "{description}", "{config.references[from_region+"-"+to_region]}", "coders", 1)""")

            # LifetimeTech
            curs.execute(f"""REPLACE INTO
                        LifetimeTech(regions, tech, life, life_notes)
                        VALUES("{region}", "{tech}", 200, "does not retire")""")
            
            # CapacityToActivity
            curs.execute(f"""REPLACE INTO
                        CapacityToActivity(regions, tech, c2a, c2a_notes)
                        VALUES("{region}", "{tech}", "{config.params['c2a']}", "{config.params['c2a_unit']}")""")
            
            # CapacityFactorTech
            # Endogenous intertie, set summer/winter to/from capacities
            if from_region in config.model_regions and to_region in config.model_regions:

                for h in range(8760):

                    season = config.time.loc[h, 'season']
                    time_of_day = config.time.loc[h, 'time_of_day']
                    summer_winter = config.time.loc[h, 'summer_winter']

                    capacity = interface['capacity_from'][from_region][summer_winter]

                    curs.execute(f"""REPLACE INTO
                                CapacityFactorTech(regions, season_name, time_of_day_name, tech, cf_tech, cf_tech_notes, reference, data_flags, dq_est)
                                VALUES("{region}", "{season}", "{time_of_day}", "{tech}", "{capacity/max_capacity}",
                                "{description}", "{config.references['interface_capacities']}", "coders", 1)""")
            
            # Intertie crosses model boundary, fix hourly flow
            elif (from_region in config.model_regions) != (to_region in config.model_regions):

                for h in range(8760):

                    season = config.time.loc[h, 'season']
                    time_of_day = config.time.loc[h, 'time_of_day']

                    cf = interface['transfers_from'][from_region][h]/1000 / max_capacity # MWh/h to PJ

                    curs.execute(f"""REPLACE INTO
                                CapacityFactorTech(regions, season_name, time_of_day_name, tech, cf_tech, cf_tech_notes, reference, data_flags, dq_est)
                                VALUES("{region}", "{season}", "{time_of_day}", "{tech}", "{cf}", "{fixed_flow_note}", "{config.references[from_region+"-"+to_region]}", "coders", "1")""")
            
            for period in config.model_periods:

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
    for trans_tech in tx_techs + dummy_techs:
        #technologies
        curs.execute(f"""REPLACE INTO
                    technologies(tech, flag, sector, tech_desc)
                    VALUES("{config.trans_techs.loc[trans_tech, 'tech']}", "p", "electric", "Transmission dummy tech")""")

    # Regional parameters
    ca_sys_params, df_sys, date_accessed = coders_api.get_data(end_point='CA_system_parameters')
    df_sys.set_index('province', inplace=True)
    config.references['ca_system_parameters'] = config.params['coders_reference'].replace('<date>', date_accessed)

    for province, row in df_sys.iterrows():

        region = config.region_map[province.upper()]
        if region not in config.model_regions: continue # skip unrepresented provinces

        # PlanningReserveMargin
        reserve_margin = row['reserve_requirements_percent']
        curs.execute(f"""REPLACE INTO
                    PlanningReserveMargin(regions, reserve_margin, reference, data_flags, dq_est)
                    VALUES("{region}", "{reserve_margin}", "{config.references['ca_system_parameters']}", "coders", 1)""")
        
        # Transmission loss techs
        line_loss = row["system_line_losses_percent"]

        for trans_tech in tx_techs + dummy_techs:

            row = config.trans_techs.loc[trans_tech]
            tech = row['tech']
            input_comm = row['input_comm']
            output_comm = row['output_comm']

            # commodities
            curs.execute(f"""REPLACE INTO
                        commodities(comm_name, flag, comm_desc)
                        VALUES('{input_comm}', '{config.commodities.loc[input_comm, 'flag']}', '{config.commodities.loc[input_comm, 'description']}')""")
            curs.execute(f"""REPLACE INTO
                        commodities(comm_name, flag, comm_desc)
                        VALUES('{output_comm}', '{config.commodities.loc[output_comm, 'flag']}', '{config.commodities.loc[output_comm, 'description']}')""")

            # Eff is line loss for TX <-> DX or 1.0 for dummy techs
            eff = 1.0 - line_loss if trans_tech in tx_techs else 1
            note = "average provincial system line losses" if trans_tech in tx_techs else "dummy tech"

            # Efficiency
            curs.execute(f"""REPLACE INTO
                        Efficiency(regions, input_comm, tech, vintage, output_comm, efficiency, eff_notes, data_flags, dq_est)
                        VALUES("{region}", "{input_comm}", "{tech}", {config.model_periods[0]}, "{output_comm}", {eff}, "{note}", "coders", 1)""")



    """
    ##############################################################
        Some final input file constraints
    ##############################################################
    """

    # TODO could probably generalise this step to all constraint tables
    # MaxCapacity
    for region in config.model_regions:
        for period in config.model_periods:

            for tech in config.cap_limits[region].index:

                max_cap = float(config.cap_limits[region].loc[tech, period]) * config.units.loc['capacity', 'conversion_factor']
                note = config.cap_limits[region].loc[tech, 'note']
                reference = config.cap_limits[region].loc[tech, 'reference']
                if str(reference) == 'nan': reference = ''
                dq_est = config.cap_limits[region].loc[tech, 'dq_est']

                if dq_est > 0:
                    curs.execute(f"""REPLACE INTO
                                MaxCapacity(regions, periods, tech, maxcap, maxcap_units, maxcap_notes, reference, dq_est)
                                VALUES('{region}', {period}, '{tech}', {max_cap}, '{config.units.loc['capacity', 'units']}',
                                "{note}", "{reference}", {dq_est})""")
                else:
                    curs.execute(f"""REPLACE INTO
                                MaxCapacity(regions, periods, tech, maxcap, maxcap_units, maxcap_notes, reference)
                                VALUES('{region}', {period}, '{tech}', {max_cap}, '{config.units.loc['capacity', 'units']}',
                                "{note}", "{reference}")""")



    """
    ##############################################################
        References
    ##############################################################
    """

    for ref in config.references.values():
        curs.execute(f"""REPLACE INTO
                    'references'('reference')
                    VALUES('{ref}')""")



    conn.commit()
    conn.close()

    print(f"CODERS API data pulled into {os.path.basename(config.database_file)}")