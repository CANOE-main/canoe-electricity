"""
Aggregates intertie data
Written by Ian David Elder for the CANOE model
"""

import numpy as np
import coders_api
import sqlite3
import os
import pandas as pd
from matplotlib import pyplot as pp
from setup import config
from utils import string_cleaner



def aggregate_interties():

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()



    """
    ##############################################################
        Prepare some general data
    ##############################################################
    """

    # Existing vintage is always one before first model period
    vint = config.model_periods[0] - config.params['period_step']
    base_year = config.params['default_data_year']



    """
    ##############################################################
        Prepare interface data
    ##############################################################
    """

    # Get interfaces data for seasonal capacity limits
    interfaces, df_interfaces, date_accessed = coders_api.get_data(end_point='interface_capacities')
    config.references['interface_capacities'] = config.params['coders']['reference'].replace("<date>", date_accessed).replace("<table>","interface_capacities")

    # Trying to group by region set (order agnostic) so get canoe regions, remove any interfaces outside model and sort regions against eachother before grouping
    df_interfaces[['region_1','region_2']] = [[config.region_map[ft[0].lower()], config.region_map[ft[1].lower()]]
                                              for ft in df_interfaces[['export_from','export_to']].values]

    # Remove interfaces outside the model
    df_interfaces = df_interfaces.loc[(df_interfaces['region_1'].isin(config.model_regions)) | (df_interfaces['region_2'].isin(config.model_regions))]

    # Format concatenation
    df_interfaces['associated_interties'] = [string_cleaner(s.replace('; ',' - ')) + ' - ' for s in df_interfaces['associated_interties']]

    # Aggregate interfaces by regional boundary
    df_interfaces = df_interfaces.groupby(['region_1','region_2']).sum()[['associated_interties','summer_capacity_mw','winter_capacity_mw']]
    df_interfaces['associated_interties'] = df_interfaces['associated_interties'].str.removesuffix(' - ')



    """
    ##############################################################
        Add data for each intertie
    ##############################################################
    """

    for r1_r2, interface in df_interfaces.iterrows():

        region_1 = r1_r2[0]
        region_2 = r1_r2[1]



        if (region_1 in config.model_regions) != (region_2 in config.model_regions):

            """
            ##############################################################
                Boundary interface (crosses model boundary)
                Treat as a demand going out and a VRE coming in
            ##############################################################
            """

            if r1_r2 not in config.interties.index: continue
            else: interties = config.interties.loc[region_1, region_2]
            
            # Work out which region is inside and which is outside the model
            in_region = region_1 if region_1 in config.model_regions else region_2

            forward_mwh = np.zeros(8760)
            back_mwh = np.zeros(8760)

            for _idx, intertie in interties.iterrows():

                # Get hourly flows into and out of the model on this intertie for the base year
                f_mwh, b_mwh = get_transfered_mwh(intertie['coders_from'], intertie['coders_to'], intertie['type'])
                if f_mwh is None: b_mwh, f_mwh = get_transfered_mwh(intertie['coders_to'], intertie['coders_from'], intertie['type'])

                # Boundary intertie got no flow data so skip it
                if f_mwh is None:
                    print(f"No flows found for boundary intertie {intertie['label']} so it was skipped.")
                    continue
                
                # Add to interface total flows
                forward_mwh += f_mwh
                back_mwh += b_mwh
            
            # Assign forward/backward flows to in/out flows based on whether the endogenous region was the from region
            out_mwh = forward_mwh if config.region_map[intertie['coders_from'].lower()] == in_region else back_mwh
            in_mwh = back_mwh if config.region_map[intertie['coders_from'].lower()] == in_region else forward_mwh

            # If no flows on this boundary at all, skip
            if in_mwh is None or out_mwh is None or (max(in_mwh) == 0 and max(out_mwh) == 0):
                print(f"No flows found for boundary interface {region_1}-{region_2} so it was skipped.")
                continue

            pp.figure()
            pp.title(f"{in_region}: outgoing (blue) and incoming (red)\ninterface flows for all connected interties.")
            pp.plot(out_mwh, 'b-')
            pp.plot(in_mwh, 'r-')


            ##############################################################
            #    Demand going out
            ##############################################################

            if max(out_mwh) > 0:

                tech_config = config.trans_techs.loc['int_out']
                input_comm = config.commodities.loc[tech_config['in_comm']]
                output_comm = config.commodities.loc[tech_config['out_comm']]


                ## Efficiency
                curs.execute(f"""REPLACE INTO
                            Efficiency(regions, input_comm, tech, vintage, output_comm, efficiency, eff_notes)
                            VALUES("{in_region}", "{input_comm['commodity']}", "{tech_config['tech']}", {vint}, "{output_comm['commodity']}", 1, "dummy tech so arbitrary")""")
                

                ## Demand
                ann_dem = sum(out_mwh) * config.units.loc['activity', 'coders_conv_fact'] # MWh to PJ
                dem_comm = config.commodities.loc[tech_config['out_comm']]

                for period in config.model_periods:
                    curs.execute(f"""REPLACE INTO
                                Demand(regions, periods, demand_comm, demand, demand_units, demand_notes, reference, data_flags, dq_est)
                                VALUES("{in_region}", {period}, "{dem_comm['commodity']}", {ann_dem}, "({dem_comm['units']})",
                                "sum of {base_year} hourly flows leaving the model boundary from {in_region} along all interties",
                                "{config.references[f"{region_1}-{region_2}"]}", "coders", 1)""")
                

                ## DemandSpecificDistribution
                for h, row in config.time.iterrows():

                    dsd = out_mwh[h] * config.units.loc['activity', 'coders_conv_fact'] / ann_dem

                    curs.execute(f"""REPLACE INTO
                                DemandSpecificDistribution(regions, season_name, time_of_day_name, demand_name, dsd, dsd_notes, reference, data_flags, dq_est)
                                VALUES("{in_region}", "{row['season']}", "{row['time_of_day']}", "{dem_comm['commodity']}", {dsd},
                                "{base_year} hourly flow divided by total annual flow leaving model boundary from {in_region}",
                                "{config.references[f"{region_1}-{region_2}"]}", "coders", 1)""")
                
            
            ##############################################################
            #    Variable generator coming in
            ##############################################################
                    
            if max(in_mwh) > 0:

                tech_config = config.trans_techs.loc['int_in']
                input_comm = config.commodities.loc[tech_config['in_comm']]
                output_comm = config.commodities.loc[tech_config['out_comm']]


                ## ExistingCapacity
                capacity = max(in_mwh) * config.units.loc['intertie_capacity', 'coders_conv_fact'] # MWh/h to GW

                curs.execute(f"""REPLACE INTO
                            ExistingCapacity(regions, tech, vintage, exist_cap, exist_cap_units, exist_cap_notes, reference, data_flags, dq_est)
                            VALUES("{in_region}", "{tech_config['tech']}", {vint}, "{capacity}", "{config.units.loc['capacity', 'units']}",
                            "max {base_year} hourly flow entering {in_region} once summed along all interties",
                            "{config.references[f"{region_1}-{region_2}"]}", "coders", 1)""")
                

                ## Efficiency
                curs.execute(f"""REPLACE INTO
                            Efficiency(regions, input_comm, tech, vintage, output_comm, efficiency, eff_notes)
                            VALUES("{in_region}", "{input_comm['commodity']}", "{tech_config['tech']}", {vint}, "{output_comm['commodity']}", 1, "dummy input so arbitrary")""")
                

                ## CapacityFactorTech
                for h, row in config.time.iterrows():

                    cf = in_mwh[h] / max(in_mwh)
                    if pd.isna(cf): print(in_mwh)

                    curs.execute(f"""REPLACE INTO
                                CapacityFactorTech(regions, season_name, time_of_day_name, tech, cf_tech, cf_tech_notes, reference, data_flags, dq_est)
                                VALUES("{in_region}", "{row['season']}", "{row['time_of_day']}", "{tech_config['tech']}", {cf},
                                "{base_year} hourly flow entering {in_region} divded by max hourly flow",
                                "{config.references['interface_capacities']}", "coders", 1)""")



        elif (region_1 in config.model_regions) and (region_2 in config.model_regions):

            """
            ##############################################################
                Endogenous interties (between modelled regions)
                Exchange technology with seasonal capacity limits
            ##############################################################
            """

            tech_config = config.trans_techs.loc['int']
            input_comm = config.commodities.loc[tech_config['in_comm']]
            output_comm = config.commodities.loc[tech_config['out_comm']]


            ## Efficiency
            curs.execute(f"""REPLACE INTO
                        Efficiency(regions, input_comm, tech, vintage, output_comm, efficiency, eff_notes)
                        VALUES("{region_1}-{region_2}", "{input_comm['commodity']}", "{tech_config['tech']}", {vint}, "{output_comm['commodity']}",
                        0.99, "arbitrarily small transmission loss")""")
            

            ## Tech_exchange
            curs.execute(f"""REPLACE INTO
                         tech_exchange(tech, notes)
                         VALUES("{tech_config['tech']}","{tech_config['description']}")""")
            

            ## ExistingCapacity
            # Capacity in each direction is max seasonal capacity
            reverse_interface = df_interfaces.loc[region_2, region_1]
            reverse_capacity = max(reverse_interface['summer_capacity_mw'], reverse_interface['winter_capacity_mw'])
            forward_capacity = max(interface['summer_capacity_mw'], interface['winter_capacity_mw'])

            # Capacity r1-r2 must equal r2-r1 by the RegionalExchangeCapacity_Constraint
            capacity = max(forward_capacity, reverse_capacity) * config.units.loc['capacity', 'coders_conv_fact'] # MW to GW

            curs.execute(f"""REPLACE INTO
                        ExistingCapacity(regions, tech, vintage, exist_cap, exist_cap_units, exist_cap_notes, reference, data_flags, dq_est)
                        VALUES("{region_1}-{region_2}", "{tech_config['tech']}", {vint}, "{capacity}", "{config.units.loc['capacity', 'units']}",
                        "max of seasonal capacities in either direction",
                        "{config.references['interface_capacities']}", "coders", 1)""")
            

            ## CapacityFactorTech
            # Needed if capacity in either direction or season is less than max capacity
            if len({reverse_interface['summer_capacity_mw'], reverse_interface['winter_capacity_mw'],
                interface['summer_capacity_mw'], interface['winter_capacity_mw']}) > 1:

                for h, row in config.time.iterrows():

                    cf = interface[f"{row['summer_winter']}_capacity_mw"] * config.units.loc['capacity', 'coders_conv_fact'] / capacity

                    curs.execute(f"""REPLACE INTO
                                CapacityFactorTech(regions, season_name, time_of_day_name, tech, cf_tech, cf_tech_notes, reference, data_flags, dq_est)
                                VALUES("{region_1}-{region_2}", "{row['season']}", "{row['time_of_day']}", "{tech_config['tech']}", {cf},
                                "seasonal, directional capacity divided by max capacity in either season or direction",
                                "{config.references['interface_capacities']}", "coders", 1)""")
            

            ## CostVariable TODO
            for period in config.model_periods:
                curs.execute(f"""REPLACE INTO
                            CostVariable(regions, periods, tech, vintage, cost_variable_notes, data_cost_variable, data_cost_year, data_curr, reference, dq_est)
                            VALUES("{region_1}-{region_2}", {period}, "{tech_config['tech']}", {vint}, "TODO", {0.01}, {config.params['atb']['currency_year']},
                            "{config.params['atb']['currency']}", "{config.references['atb']}", 1)""")
        

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
        print(f"Insufficient transfer data on {region_1}-{region_2}.")
        return None, None
    
    # Add reference for both directions for ease of pulling
    config.references[f"{config.region_map[region_1.lower()]}-{config.region_map[region_2.lower()]}"] = reference
    config.references[f"{config.region_map[region_2.lower()]}-{config.region_map[region_1.lower()]}"] = reference
  
    hourly_mwh = np.zeros(8760)

    for h in range(8760):
        mwh = df_transfers.loc[h, 'transfers_MWh']

        if mwh is not None:
            hourly_mwh[h] = mwh

    # Forward is positive flows
    forward = hourly_mwh.copy()
    forward[forward < 0] = 0

    # Backward is negative flows
    backward = hourly_mwh.copy()
    backward[backward > 0] = 0
    backward *= -1

    return forward, backward