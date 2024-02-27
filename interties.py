"""
Aggregates intertie data
Written by Ian David Elder for the CANOE model
"""

import numpy as np
import coders_api
import sqlite3
import os
from setup import config
from utils import string_cleaner



def aggregate_interties():

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()


    """
    ##############################################################
        Determine hourly flows for each intertie in base year
    ##############################################################
    """

    int_tech = config.trans_techs.loc['intertie', 'tech']

    # Regional interfaces
    # Get flows and fix for each boundary
    # Do this up here so it doesn't slam the CODERS database twice for no reason
    intertie_flows = dict()
    for interties, row in config.trans_regions.iterrows():
        
        tech = int_tech + "-" + row['tag']

        # There are multiple interties per some region boundaries so skip duplicates
        if tech in intertie_flows.keys(): continue

        region_1_canoe = config.region_map[row['region_1'].lower()]
        region_2_canoe = config.region_map[row['region_2'].lower()]

        # Do not represent interties for provinces not included. Note us states always included
        if (region_1_canoe not in config.model_regions) and (region_2_canoe not in config.model_regions): continue

        # Get 8760 transfers from the data year for this boundary in MWh
        from_region_1, from_region_2 = get_transfered_mwh(row['region_1'], row['region_2'], row['type'])
        if from_region_1 is None:
            print(f"Failed to get flow data for {row['type']} intertie {row['region_1']}-{row['region_2']}")
        intertie_flows[tech] = {region_1_canoe: from_region_1, region_2_canoe: from_region_2}


    interfaces, df_interfaces, date_accessed = coders_api.get_data(end_point='interface_capacities')
    config.references['interface_capacities'] = config.params['coders']['reference'].replace("<date>", date_accessed).replace("<table>","interface_capacities")

    interface_techs = dict() # keys are CANOE techs

    elc_comm = config.commodities.loc[config.trans_techs.loc['intertie', 'in_comm']]
    ex_comm = config.commodities.loc[config.trans_techs.loc['intertie', 'out_comm']]

    # Remember that everything here runs twice, regions 1-2 then 2-1
    for idx, row in df_interfaces.iterrows():

        interties = row['associated_interties']

        tech = int_tech + "-" + config.trans_regions.loc[interties, 'tag']

        from_region = config.region_map[row['export_from'].lower()]
        to_region = config.region_map[row['export_to'].lower()]

        # Don't represent interties outside the model or boundary interties with insufficient data
        if (from_region not in config.model_regions) and (to_region not in config.model_regions): continue
        if ((from_region in config.model_regions) != (to_region in config.model_regions)) and intertie_flows[tech][from_region] is None:
            print(f"Boundary intertie {row['export_from'].lower()}-{row['export_to'].lower()} skipped for lack of flow data")
            continue

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
        summer_capacity = config.units.loc['capacity', 'coders_conv_fact'] * row['summer_capacity_mw']
        winter_capacity = config.units.loc['capacity', 'coders_conv_fact'] * row['winter_capacity_mw']

        # Take the largest of summer/winter capacity then aggregate all interties per region boundary
        interface_techs[tech]['capacity_from'][from_region]['summer'] += summer_capacity
        interface_techs[tech]['capacity_from'][from_region]['winter'] += winter_capacity

    

    """
    ##############################################################
        Add intertie data to database
    ##############################################################
    """

    print(f"Adding intertie data to database...")

    # Now that data is ready for each interface, add to database
    for tech, interface in interface_techs.items():
        
        # Max capacity is largest of both directions and summer/winter (TEMOA demands a single capacity per intertie)
        max_capacity = max( [max(val.values()) for val in list(interface_techs[tech]['capacity_from'].values())] ) # it works dont mess with it
        if max_capacity <= 0: continue # zero capacity comes up with retired interfaces

        description = interface['description']

        
        # Boundary intertie
        if (interface['regions'][0] in config.model_regions) != (interface['regions'][1] in config.model_regions):

            # Some interface flows exceed rated capacity so take max hourly flow as max cap and convert from MWh/h to GW
            max_capacity = max( max(interface['transfers_from'][interface['regions'][0]]), max(interface['transfers_from'][interface['regions'][1]]) )
            max_capacity /= 1000 # MWh/h to GW

            description = "boundary intertie - " + description
        
        # Endogenous intertie
        else: description = "endogenous intertie - " + description
        


        ## Technologies
        curs.execute(f"""REPLACE INTO
                    technologies(tech, flag, sector, tech_desc)
                    VALUES("{tech}", "p", "electric", "{description}")""")
        

        # Fill tables for r1-r2 and r2-r1
        for r in [0,1]:

            from_region = interface['regions'][r]
            to_region = interface['regions'][1-r]
            region = from_region + '-' + to_region

            # If endogenous, capacity is from interface capacities table
            if from_region in config.model_regions and to_region in config.model_regions:
                
                config.references[region] = config.references['interface_capacities']

                ## Tech_exchange set
                curs.execute(f"""REPLACE INTO
                            tech_exchange(tech, notes)
                            VALUES("{tech}", "{description}")""")
                

            input_comm = ex_comm if from_region not in config.model_regions else elc_comm
            output_comm = ex_comm if to_region not in config.model_regions else elc_comm

            
            ## Commodities
            curs.execute(f"""REPLACE INTO
                        commodities(comm_name, flag, comm_desc)
                        VALUES('{input_comm['commodity']}', '{input_comm['flag']}', '{input_comm['description']}')""")
            curs.execute(f"""REPLACE INTO
                        commodities(comm_name, flag, comm_desc)
                        VALUES('{output_comm['commodity']}', '{output_comm['flag']}', '{output_comm['description']}')""")

            # Note describing fixed flow interties
            fixed_flow_note = config.params['intertie_fixed_flow_note'].replace("<year>", str(config.params['default_data_year']))

            if from_region not in config.model_regions and to_region not in config.model_regions: continue # both regions outside model


            ## ExistingCapacity
            curs.execute(f"""REPLACE INTO
                        ExistingCapacity(regions, tech, vintage, exist_cap, exist_cap_units, exist_cap_notes, reference, data_flags, dq_est)
                        VALUES("{region}", "{tech}", {config.model_periods[0]}, "{max_capacity}", "{config.units.loc['capacity', 'units']}",
                        "{description}", "{config.references[from_region+"-"+to_region]}", "coders", 1)""")


            ## LifetimeTech
            curs.execute(f"""REPLACE INTO
                        LifetimeTech(regions, tech, life, life_notes)
                        VALUES("{region}", "{tech}", 100, "(y) no retirement")""")
            

            ## CapacityToActivity
            curs.execute(f"""REPLACE INTO
                        CapacityToActivity(regions, tech, c2a, c2a_notes)
                        VALUES("{region}", "{tech}", "{config.params['c2a']}", "({config.params['c2a_unit']})")""")
            

            ## CapacityFactorTech
            # Endogenous intertie, set summer/winter to/from capacity factors
            if from_region in config.model_regions and to_region in config.model_regions:


                ## Efficiency
                curs.execute(f"""REPLACE INTO
                            Efficiency(regions, input_comm, tech, vintage, output_comm, efficiency, eff_notes)
                            VALUES("{region}", "{input_comm['commodity']}", "{tech}", {config.model_periods[0]}, "{output_comm['commodity']}", 1, "{description}")""")

                for h in range(8760):

                    season = config.time.loc[h, 'season']
                    time_of_day = config.time.loc[h, 'time_of_day']
                    summer_winter = config.time.loc[h, 'summer_winter']

                    capacity = interface['capacity_from'][from_region][summer_winter]

                    curs.execute(f"""REPLACE INTO
                                CapacityFactorTech(regions, season_name, time_of_day_name, tech, cf_tech, cf_tech_notes, reference, data_flags, dq_est)
                                VALUES("{region}", "{season}", "{time_of_day}", "{tech}", "{capacity/max_capacity}",
                                "summer/winter seasonal capacity - {description}", "{config.references['interface_capacities']}", "coders", 1)""")
            
            
            # Intertie crosses model boundary, fix hourly flow
            elif (from_region in config.model_regions) != (to_region in config.model_regions):

                    # Leaving the model boundary, treat as a demand
                    if from_region in config.model_regions:

                        ann_dem = sum(interface['transfers_from'][from_region]) * config.units.loc['activity', 'coders_conv_fact']
                        if ann_dem == 0: continue

                        note = f"Intertie outflow treated as demand using {config.params['default_data_year']} flows"
                        dem_comm = f"D_{tech}"


                        ## Efficiency
                        curs.execute(f"""REPLACE INTO
                                    Efficiency(regions, input_comm, tech, vintage, output_comm, efficiency, eff_notes)
                                    VALUES("{region}", "{input_comm['commodity']}", "{tech}", {config.model_periods[0]}, "{dem_comm}", 1, "{description}")""")

                        for period in config.model_periods:


                            ## Commodities
                            curs.execute(f"""REPLACE INTO
                                        commodities(comm_name, flag, comm_desc)
                                        VALUES('{dem_comm}', 'd', '({elc_comm['units']}) demand for electricity on {description}')""")
                            

                            ## Demand
                            curs.execute(f"""REPLACE INTO
                                        DEMAND(regions, periods, demand_comm, demand, demand_units, demand_notes, reference, data_flags, dq_est)
                                        VALUES("{region}", {period}, "{dem_comm}", {ann_dem}, "({config.units.loc['activity', 'units']})", "{note}",
                                        "{config.references[region]}", "coders", 1)""")
                            

                            ## DemandSpecificDistribution
                            for h in range(8760):

                                season = config.time.loc[h, 'season']
                                time_of_day = config.time.loc[h, 'time_of_day']

                                dsd = interface['transfers_from'][from_region][h] * config.units.loc['activity', 'coders_conv_fact'] / ann_dem
                                if dsd == 0: continue

                                curs.execute(f"""REPLACE INTO
                                            DemandSpecificDistribution(regions, season_name, time_of_day_name, demand_name, dsd, dsd_notes, reference, data_flags, dq_est)
                                            VALUES("{region}", "{season}", "{time_of_day}", "{dem_comm}", {dsd}, "{note}", "{config.references[region]}", "coders", 1)""")
                    
                    # Entering the model boundary, treat like a renewable generator
                    else:

                        ## Efficiency
                        curs.execute(f"""REPLACE INTO
                                    Efficiency(regions, input_comm, tech, vintage, output_comm, efficiency, eff_notes)
                                    VALUES("{region}", "{input_comm['commodity']}", "{tech}", {config.model_periods[0]}, "{output_comm['commodity']}", 1, "{description}")""")
            
                        for h in range(8760):

                            season = config.time.loc[h, 'season']
                            time_of_day = config.time.loc[h, 'time_of_day']

                            ## CapacityFactorTech
                            cf = interface['transfers_from'][from_region][h]/1000 / max_capacity # MWh/GW.h to GW/GW

                            curs.execute(f"""REPLACE INTO
                                        CapacityFactorTech(regions, season_name, time_of_day_name, tech, cf_tech, cf_tech_notes, reference, data_flags, dq_est)
                                        VALUES("{region}", "{season}", "{time_of_day}", "{tech}", "{cf}", "{fixed_flow_note}",
                                        "{config.references[from_region+"-"+to_region]}", "coders", "1")""")


    print(f"Intertie data aggregated into {os.path.basename(config.database_file)}\n")

    conn.commit()
    conn.close()



# Gets MWh transferred for each hour of the base year along a given intertie
def get_transfered_mwh(region_1, region_2, intertie_type) -> tuple[np.ndarray, np.ndarray]:

    data_year = config.params['default_data_year']

    if intertie_type == 'international':
        transfers, df_transfers, date_accessed = coders_api.get_data(end_point="international_transfers", year=data_year, province=region_1, us_region=region_2)
        reference = config.params['coders']['reference'].replace("<date>", date_accessed).replace("<table>","international_transfers")
    elif intertie_type == 'interprovincial':
        transfers, df_transfers, date_accessed = coders_api.get_data(end_point="interprovincial_transfers", year=data_year, province1=region_1, province2=region_2)
        reference = config.params['coders']['reference'].replace("<date>", date_accessed).replace("<table>","interprovincial_transfers")

    if transfers is None or (len(transfers) < 8760):
        print(f"Insufficient transfer data on {region_1}-{region_2}. Try switching the intertie regions.")
        return None, None
    
    # Add reference in either direction to make things easier
    config.references[f"{config.region_map[region_1.lower()]}-{config.region_map[region_2.lower()]}"] = reference
    config.references[f"{config.region_map[region_2.lower()]}-{config.region_map[region_1.lower()]}"] = reference
  
    hourly_mwh = np.zeros(8760)

    for h in range(8760):
        mwh = df_transfers.loc[h, 'transfers_MWh']

        if mwh is not None:
            hourly_mwh[h] = mwh

    forward = hourly_mwh.copy()
    forward[forward < 0] = 0

    backward = hourly_mwh.copy()
    backward[backward > 0] = 0
    backward *= -1

    return forward, backward