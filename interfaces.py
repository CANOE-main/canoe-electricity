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

# Globalise so we only have one connection
conn: sqlite3.Connection
curs: sqlite3.Cursor

# Vintage is always last existing period as interties do not retire
vint = config.model_periods[0] - 1
weather_year = config.params['weather_year']

# Provincial parameters for line loss
df_sys: pd.DataFrame



def aggregate():

    global conn, curs, df_sys

    print("Aggregating interfaces...")

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()

    # Provincial systems parameters for average provincial line loss
    _ca_sys_params, df_sys, date_accessed = coders_api.get_data(end_point='CA_system_parameters')
    df_sys['region'] = [config.region_map[p.lower()] for p in df_sys['province'].values]
    df_sys.set_index('region', inplace=True)
    config.references['ca_system_parameters'] = config.params['coders']['reference'].replace('<table>', 'ca_system_parameters').replace('<date>', date_accessed)

    # Get interfaces data for seasonal capacity limits and associated interties
    interfaces, df_interfaces, date_accessed = coders_api.get_data(end_point='interface_capacities')
    config.references['interface_capacities'] = config.params['coders']['reference'].replace("<date>", date_accessed).replace("<table>","interface_capacities")

    # Want to group by region set (order agnostic) so get canoe regions but do not sort horizontally
    df_interfaces[['region_1','region_2']] = [[config.region_map[ft[0].lower()], config.region_map[ft[1].lower()]]
                                              for ft in df_interfaces[['province_state_from','province_state_to']].values]
    
    # For concatenating associated interties
    df_interfaces['associated_interties'] = df_interfaces['associated_interties'].str.replace('; ',' - ') + ' - '

    # Aggregate interfaces by regional boundary
    df_interfaces = df_interfaces.groupby(['region_1','region_2']).sum()[['associated_interties','summer_capacity','winter_capacity']]

    # For concatenating associated interties
    df_interfaces['associated_interties'] = df_interfaces['associated_interties'].str.removesuffix(' - ')

    if config.params['include_boundary_interfaces']: aggregate_boundary_interfaces(df_interfaces)
    if config.params['include_endogenous_interfaces']: aggregate_endogenous_interfaces(df_interfaces)

    conn.commit()
    conn.close()

    print(f"Interfaces aggregated into {os.path.basename(config.database_file)}\n")



"""
##############################################################
    Boundary interface (crosses model boundary)
    Treat as a demand going out and a VRE coming in
##############################################################
"""

def aggregate_boundary_interfaces(df_interfaces):

    # Get all interties that cross model boundary and group by in-model region
    # This is done by sorting regions left-right then grouping as pairs
    #df_interties = pd.read_csv(config.input_files + 'interties.csv')
    _json, df_prov, _date = coders_api.get_data('interprovincial_transfers')
    _json, df_int, _date = coders_api.get_data('international_transfers')

    df_prov['type'] = 'interprovincial'
    df_int['type'] = 'international'
    
    # Convert to generic column names
    df_prov.rename(columns={'province_1':'coders_from', 'province_2':'coders_to'}, inplace=True)
    df_int.rename(columns={'province':'coders_from', 'us_state':'coders_to'}, inplace=True)

    # Combine into one interties dataframe
    df_interties = pd.concat([df_prov, df_int])

    # Get CANOE region names
    df_interties[['region_1','region_2']] = [np.sort([config.region_map[ft[0].lower()], config.region_map[ft[1].lower()]])
                                                        for ft in df_interties[['coders_from','coders_to']].values]
    
    # Get associated intertie names for each boundary interface
    df_interties['intertie_names'] = [df_interfaces.loc[(r1_r2[0], r1_r2[1]), 'associated_interties'] for r1_r2 in df_interties[['region_1','region_2']].values]

    # Only want boundary interfaces
    df_boundary = df_interties.loc[df_interties['region_1'].isin(config.model_regions) != df_interties['region_2'].isin(config.model_regions)]

    # Aggregate all intertie flows leaving or entering each model region. Only one of region_1 or region_2 is endogenous
    for r1_r2, interface in df_boundary.groupby(['region_1','region_2']): aggregate_boundary_interface(r1_r2, interface)



def aggregate_boundary_interface(r1_r2: tuple, interface: pd.DataFrame):

    region_1 = r1_r2[0]
    region_2 = r1_r2[1]
    intertie_names = interface['intertie_names'].values[0]
    
    # Work out which region is inside and which is outside the model
    in_region = region_1 if region_1 in config.model_regions else region_2

    out_mwh = np.zeros(8760)
    in_mwh = np.zeros(8760)

    for _idx, intertie in interface.iterrows():

        if str(weather_year) not in intertie['year'].split(','):
            print(f"No intertie transfer data available for {intertie['coders_from']}-{intertie['coders_to']} for year {weather_year} so it was skipped.")
            continue

        # Get hourly flows into and out of the model on this intertie for the base year
        forward_mwh, back_mwh = get_transfered_mwh(intertie['coders_from'], intertie['coders_to'], intertie['type'])
        if forward_mwh is None and intertie['type'] != 'international': back_mwh, forward_mwh = get_transfered_mwh(intertie['coders_to'], intertie['coders_from'], intertie['type'])

        # Boundary intertie got no flow data so skip it
        if forward_mwh is None:
            print(f"No flows found for boundary intertie {intertie['coders_from']}-{intertie['coders_to']} so it was skipped.")
            continue

        # Assign forward/backward flows to in/out flows based on whether the endogenous region was the from region
        # The index was sorted horizontally for grouping so it no longer corresponds to the coders from/to regions
        out_mwh += forward_mwh if config.region_map[intertie['coders_from'].lower()] == in_region else back_mwh
        in_mwh += back_mwh if config.region_map[intertie['coders_from'].lower()] == in_region else forward_mwh
    
    

    # If no flows on this boundary at all, skip
    if in_mwh is None or out_mwh is None or (max(in_mwh) == 0 and max(out_mwh) == 0):
        print(f"No flows found for boundary interface {region_1}-{region_2} so it was skipped.")
        return

    pp.figure()
    pp.title(f"{in_region}: outgoing (blue) and incoming (red)\ninterface flows for all connected interties.")
    pp.ylabel("MWh")
    pp.xlabel("Hour of year")
    pp.plot(out_mwh, 'b-')
    pp.plot(in_mwh, 'r-')



    """
    ##############################################################
        Demand for electricity leaving region
    ##############################################################
    """

    if max(out_mwh) > 0:

        tech_config = config.trans_techs.loc['int_out']
        input_comm = config.commodities.loc[tech_config['in_comm']]
        output_comm = config.commodities.loc[tech_config['out_comm']]


        ## Efficiency
        eff = 1.0 - float(df_sys.loc[in_region, 'system_line_losses_percent'])
        note = f"({output_comm['units']}/{input_comm['units']}) {in_region} system_line_losses_percent"

        curs.execute(f"""REPLACE INTO
                    Efficiency(regions, input_comm, tech, vintage, output_comm, efficiency, eff_notes, reference, data_flags, dq_est)
                    VALUES("{in_region}", "{input_comm['commodity']}", "{tech_config['tech']}", {config.model_periods[0]},"{output_comm['commodity']}",
                    {eff}, "{note}", "{config.references['ca_system_parameters']}", "coders", 1)""")
        

        ## CapacityToActivity
        curs.execute(f"""REPLACE INTO
                    CapacityToActivity(regions, tech, c2a, c2a_notes)
                    VALUES("{in_region}", "{tech_config['tech']}", "{config.params['c2a']}", "({config.params['c2a_unit']})")""")
    

        ## Demand
        ann_dem = sum(out_mwh) * config.units.loc['activity', 'coders_conv_fact'] # MWh to PJ
        dem_comm = config.commodities.loc[tech_config['out_comm']]

        for period in config.model_periods:
            curs.execute(f"""REPLACE INTO
                        Demand(regions, periods, demand_comm, demand, demand_units, demand_notes, reference, data_flags, dq_est)
                        VALUES("{in_region}", {period}, "{dem_comm['commodity']}", {ann_dem}, "({dem_comm['units']})",
                        "sum of {weather_year} hourly flows leaving the model boundary from {in_region} along all interties - {intertie_names}",
                        "{config.references[f"{region_1}-{region_2}"]}", "coders", 1)""")
        

        ## DemandSpecificDistribution
        note = f"{weather_year} hourly flow divided by total annual flow leaving model boundary from {in_region}"
        reference = config.references[f"{region_1}-{region_2}"]
        for h, time in config.time.iterrows():

            dsd = out_mwh[h] * config.units.loc['activity', 'coders_conv_fact'] / ann_dem

            if time['time_of_day'] == config.time.iloc[0]['time_of_day']:
                _note = note
                _ref = reference
            else: _note=_ref=''

            curs.execute(f"""REPLACE INTO
                        DemandSpecificDistribution(regions, season_name, time_of_day_name, demand_name, dsd, dsd_notes, reference, data_flags, dq_est)
                        VALUES("{in_region}", "{time['season']}", "{time['time_of_day']}", "{dem_comm['commodity']}", {dsd},
                        "{_note}", "{_ref}", "coders", 1)""")
        

    
    """
    ##############################################################
        Variable generator entering region
    ##############################################################
    """

    if max(in_mwh) > 0:

        tech_config = config.trans_techs.loc['int_in']
        input_comm = config.commodities.loc[tech_config['in_comm']]
        output_comm = config.commodities.loc[tech_config['out_comm']]

        ## tech_curtailment
        curs.execute(f"""REPLACE INTO
                     tech_curtailment(tech)
                     VALUES("{tech_config['tech']}")""")


        ## ExistingCapacity
        capacity = max(in_mwh) * config.units.loc['intertie_capacity', 'coders_conv_fact'] # MWh/h to GW

        curs.execute(f"""REPLACE INTO
                    ExistingCapacity(regions, tech, vintage, exist_cap, exist_cap_units, exist_cap_notes, reference, data_flags, dq_est)
                    VALUES("{in_region}", "{tech_config['tech']}", {vint}, "{capacity}", "({config.units.loc['capacity', 'units']})",
                    "max {weather_year} hourly flow entering {in_region} once summed along all interties - {intertie_names}",
                    "{config.references[f"{region_1}-{region_2}"]}", "coders", 1)""")
        

        ## Efficiency
        curs.execute(f"""REPLACE INTO
                    Efficiency(regions, input_comm, tech, vintage, output_comm, efficiency, eff_notes)
                    VALUES("{in_region}", "{input_comm['commodity']}", "{tech_config['tech']}", {vint}, "{output_comm['commodity']}", 1, "dummy input so arbitrary")""")
        

        ## CapacityToActivity
        curs.execute(f"""REPLACE INTO
                    CapacityToActivity(regions, tech, c2a, c2a_notes)
                    VALUES("{in_region}", "{tech_config['tech']}", "{config.params['c2a']}", "({config.params['c2a_unit']})")""")
        

        ## CapacityFactorTech
        note = f"{weather_year} hourly flow entering {in_region} divided by max hourly flow"
        reference = config.references[f"{region_1}-{region_2}"]
        for h, time in config.time.iterrows():

            cf = in_mwh[h] / max(in_mwh)

            if time['time_of_day'] == config.time.iloc[0]['time_of_day']:
                _note = note
                _ref = reference
            else: _note=_ref=''

            curs.execute(f"""REPLACE INTO
                        CapacityFactorTech(regions, season_name, time_of_day_name, tech, cf_tech, cf_tech_notes, reference, data_flags, dq_est)
                        VALUES("{in_region}", "{time['season']}", "{time['time_of_day']}", "{tech_config['tech']}", {cf},
                        "{_note}", "{_ref}", "coders", 1)""")



def aggregate_endogenous_interfaces(df_interfaces: pd.DataFrame):

    # This gets only fully endogenous interfaces
    df_endogenous = df_interfaces.loc[[(r1_r2[0] in config.model_regions) and (r1_r2[1] in config.model_regions) for r1_r2 in df_interfaces.index]]

    """
    ##############################################################
        Add data for each endogenous interface
        This whole loop runs r1-r2 then r2-r1 for every
        regional pair
    ##############################################################
    """

    for r1_r2, interface in df_endogenous.iterrows():

        region_1 = r1_r2[0]
        region_2 = r1_r2[1]

        tech_config = config.trans_techs.loc['int']
        input_comm = config.commodities.loc[tech_config['in_comm']]
        output_comm = config.commodities.loc[tech_config['out_comm']]


        ## Efficiency
        eff = 1.0 - float(df_sys.loc[region_1, 'system_line_losses_percent'])
        note = f"({output_comm['units']}/{input_comm['units']}) {region_1} system_line_losses_percent"

        curs.execute(f"""REPLACE INTO
                    Efficiency(regions, input_comm, tech, vintage, output_comm, efficiency, eff_notes, reference, data_flags, dq_est)
                    VALUES("{region_1}-{region_2}", "{input_comm['commodity']}", "{tech_config['tech']}", {vint},
                    "{output_comm['commodity']}", {eff}, "{note}", "{config.references['ca_system_parameters']}", "coders", 1)""")
        

        ## Tech_exchange
        curs.execute(f"""REPLACE INTO
                        tech_exchange(tech, notes)
                        VALUES("{tech_config['tech']}","{tech_config['description']}")""")
        

        ## CapacityToActivity
        curs.execute(f"""REPLACE INTO
                    CapacityToActivity(regions, tech, c2a, c2a_notes)
                    VALUES("{region_1}-{region_2}", "{tech_config['tech']}", "{config.params['c2a']}", "({config.params['c2a_unit']})")""")
        

        ## ExistingCapacity
        # Capacity in each direction is max seasonal capacity
        reverse_interface = df_endogenous.loc[region_2, region_1]
        reverse_capacity = max(reverse_interface['summer_capacity'], reverse_interface['winter_capacity'])
        forward_capacity = max(interface['summer_capacity'], interface['winter_capacity'])

        # Capacity r1-r2 must equal r2-r1 by the RegionalExchangeCapacity_Constraint
        capacity = max(forward_capacity, reverse_capacity) * config.units.loc['capacity', 'coders_conv_fact'] # MW to GW

        curs.execute(f"""REPLACE INTO
                    ExistingCapacity(regions, tech, vintage, exist_cap, exist_cap_units, exist_cap_notes, reference, data_flags, dq_est)
                    VALUES("{region_1}-{region_2}", "{tech_config['tech']}", {vint}, "{capacity}", "({config.units.loc['capacity', 'units']})",
                    "max of seasonal capacities in either direction - {interface['associated_interties']}",
                    "{config.references['interface_capacities']}", "coders", 1)""")
        

        ## CapacityFactorTech
        # Needed if capacity in either direction or season is less than max capacity
        if len({reverse_interface['summer_capacity'], reverse_interface['winter_capacity'],
            interface['summer_capacity'], interface['winter_capacity']}) > 1:

            for h, row in config.time.iterrows():

                cf = interface[f"{row['summer_winter']}_capacity"] * config.units.loc['capacity', 'coders_conv_fact'] / capacity

                curs.execute(f"""REPLACE INTO
                            CapacityFactorTech(regions, season_name, time_of_day_name, tech, cf_tech, cf_tech_notes, reference, data_flags, dq_est)
                            VALUES("{region_1}-{region_2}", "{row['season']}", "{row['time_of_day']}", "{tech_config['tech']}", {cf},
                            "seasonal, directional capacity divided by max capacity in either season or direction",
                            "{config.references['interface_capacities']}", "coders", 1)""")
        

        ## CostVariable TODO



"""
##############################################################
    Retrieves historical hourly flows for a given intertie
##############################################################
"""

# Gets MWh transferred for each hour of the base year along a given intertie
def get_transfered_mwh(region_1, region_2, intertie_type) -> tuple[np.ndarray, np.ndarray]:

    data_year = config.params['weather_year']

    if intertie_type == 'international':
        _transfers, df_transfers, date_accessed = coders_api.get_data(end_point="international_transfers", year=data_year, province=region_1, us_state=region_2)
        reference = config.params['coders']['reference'].replace("<date>", date_accessed).replace("<table>","international_transfers")
    elif intertie_type == 'interprovincial':
        _transfers, df_transfers, date_accessed = coders_api.get_data(end_point="interprovincial_transfers", year=data_year, province1=region_1, province2=region_2)
        reference = config.params['coders']['reference'].replace("<date>", date_accessed).replace("<table>","interprovincial_transfers")

    if df_transfers is None or (len(df_transfers) < 8760):
        print(f"Insufficient {intertie_type} transfer data on {region_1}-{region_2}.")
        return None, None
    
    # Add reference for both directions for ease of pulling
    config.references[f"{config.region_map[region_1.lower()]}-{config.region_map[region_2.lower()]}"] = reference
    config.references[f"{config.region_map[region_2.lower()]}-{config.region_map[region_1.lower()]}"] = reference
  
    hourly_mwh = df_transfers['transfers_MWh'].iloc[0:8760].ffill().to_numpy()

    # TODO transfer flows were reversed in CODERS update. Check they haven't been reversed back again.
    # Forward is negative flows (apparently)
    forward = hourly_mwh.copy()
    forward[forward > 0] = 0
    forward *= -1

    # Backward is positive flows
    backward = hourly_mwh.copy()
    backward[backward < 0] = 0

    return forward, backward



if __name__ == "__main__":

    aggregate()