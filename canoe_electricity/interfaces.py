"""
Aggregates intertie data
Written by Ian David Elder for the CANOE model
"""

import numpy as np
import canoe_electricity.coders_api as coders_api
import sqlite3
import os
import pandas as pd
from matplotlib import pyplot as pp
from canoe_electricity.setup import config
import canoe_electricity.utils as utils
from provincial_data.default import cost_tx_dx
from canoe_schema.v4_0.models import (
    Technology, Efficiency, CapacityToActivity, Commodity, Demand,
    DemandSpecificDistribution, ExistingCapacity, CapacityFactorTech,
)

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

    _coders_kwargs = dict(
        cache_dir=config.cache_dir,
        force_download=config.params.get('force_download', False),
        api_key_file=config.input_files + config.params['coders_api_key_file'],
        debug=config.debug,
    )

    # Provincial systems parameters for average provincial line loss
    df_sys, date_accessed = coders_api.get_data(end_point='CA_system_parameters', **_coders_kwargs)
    df_sys['region'] = [config.region_map[p.lower()] for p in df_sys['province'].values]
    df_sys.set_index('region', inplace=True)
    config.refs.add('ca_system_parameters', config.params['coders']['reference'].replace('<table>', 'ca_system_parameters').replace('<date>', date_accessed))

    # Get interfaces data for seasonal capacity limits and associated interties
    df_interfaces, date_accessed = coders_api.get_data(end_point='interface_capacities', **_coders_kwargs)
    config.refs.add('interface_capacities', config.params['coders']['reference'].replace("<date>", date_accessed).replace("<table>","interface_capacities"))

    # Want to group by region set (order agnostic) so get canoe regions but do not sort horizontally
    df_interfaces[['region_1','region_2']] = [[config.region_map[ft[0].lower()], config.region_map[ft[1].lower()]]
                                              for ft in df_interfaces[['from_province_state','to_province_state']].values]
    
    # For concatenating associated interties
    df_interfaces['network_node_names'] = df_interfaces['network_node_names'].str.replace('; ',' - ') + ' - '

    # Aggregate interfaces by regional boundary
    df_interfaces = df_interfaces.groupby(['region_1','region_2']).sum()[['network_node_names','ttc_summer','ttc_winter']]

    # For concatenating associated interties
    df_interfaces['network_node_names'] = df_interfaces['network_node_names'].str.removesuffix(' - ')

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
    _coders_kwargs = dict(
        cache_dir=config.cache_dir,
        force_download=config.params.get('force_download', False),
        api_key_file=config.input_files + config.params['coders_api_key_file'],
        debug=config.debug,
    )
    df_prov, _date = coders_api.get_data('interprovincial_transfers', **_coders_kwargs)
    df_int, _date = coders_api.get_data('international_transfers', **_coders_kwargs)

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
    df_interties['intertie_names'] = [df_interfaces.loc[(r1_r2[0], r1_r2[1]), 'network_node_names'] for r1_r2 in df_interties[['region_1','region_2']].values]
    
    # Only want boundary interfaces
    if config.params['full_dataset']:
        # If either region is in the model, aggregate the data in that direction
        for (r1, r2), interface in df_interties.groupby(['region_1','region_2']):
            if r1 in config.model_regions: aggregate_boundary_interface(r1, r2, interface)
            if r2 in config.model_regions: aggregate_boundary_interface(r2, r1, interface)
    else:
        # If only ONE of the regions is in the model, aggregate that data only in the OUTWARD direction
        for (r1, r2), interface in df_interties.groupby(['region_1','region_2']):
            if r1 in config.model_regions and r2 not in config.model_regions: aggregate_boundary_interface(r1, r2, interface)
            elif r2 in config.model_regions and r1 not in config.model_regions: aggregate_boundary_interface(r2, r1, interface)



def aggregate_boundary_interface(in_region: str, out_region: str, interface: pd.DataFrame):
    
    intertie_names = interface['intertie_names'].values[0]

    data_id = utils.data_id(f"BINT{in_region}{out_region}")

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
        print(f"No flows found for boundary interface {in_region}-{out_region} so it was skipped.")
        return

    pp.figure()
    pp.title(f"{in_region}: outgoing (blue) and incoming (red)\ninterface flows for all interties to {out_region}.")
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
        dem_comm = config.commodities.loc[tech_config['out_comm']].copy()
        dem_comm['commodity'] += f'_{out_region.lower()}'
        ann_dem = sum(out_mwh) * config.units.loc['activity', 'coders_conv_fact'] # MWh to PJ

        tech = f"{tech_config['tech']}-{out_region}"
        desc = f"{tech_config['description']} - {in_region} out to {out_region}"


        ## Technology
        curs.executemany(*Technology.bulk_insert_or_ignore_sql([Technology(
            tech=tech, flag='p', sector='electricity', unlim_cap=1, annual=1,
            description=desc, data_id=data_id,
        )]))

        ## Efficiency
        eff = 1.0 - float(df_sys.loc[in_region, 'system_line_losses_percent'])
        note = f"({dem_comm['units']}/{input_comm['units']}) {in_region} system_line_losses_percent"
        curs.executemany(*Efficiency.bulk_insert_or_ignore_sql([Efficiency(
            region=in_region, input_comm=input_comm['commodity'],
            tech=tech, vintage=vint, output_comm=dem_comm['commodity'],
            efficiency=eff, notes=note,
            data_source=config.refs.get('ca_system_parameters').id, dq_cred=2,
            data_id=data_id,
        )]))

        ## CapacityToActivity
        curs.executemany(*CapacityToActivity.bulk_insert_or_ignore_sql([CapacityToActivity(
            region=in_region, tech=tech, c2a=config.params['c2a'],
            notes=f"({config.params['c2a_unit']})", data_id=data_id,
        )]))

        ## Commodity
        curs.executemany(*Commodity.bulk_insert_or_ignore_sql([Commodity(
            name=dem_comm['commodity'], flag='d',
            description=dem_comm['description'], data_id=data_id,
        )]))

        demand_rows = []
        for period in config.model_periods:
            demand_rows.append(Demand(
                region=in_region, period=period,
                commodity=dem_comm['commodity'], demand=ann_dem,
                units=f"({dem_comm['units']})",
                notes=f"sum of {weather_year} hourly flows leaving the model boundary from {in_region} along all interties - {intertie_names}",
                data_source=config.refs.get("transfers").id, dq_cred=2, data_id=data_id,
            ))
            ## CostVariable
            cost_tx_dx.aggregate(in_region, period, tech, vint, curs, data_id, 'tx')
        if demand_rows:
            curs.executemany(*Demand.bulk_insert_or_ignore_sql(demand_rows))

        ## DemandSpecificDistribution
        note = f"{weather_year} hourly flow divided by total annual flow leaving model boundary from {in_region}"
        ref = config.refs.get("transfers")

        dsd_rows = []
        for period in config.model_periods:
            for h, time in config.time.iterrows():
                dsd = out_mwh[h] * config.units.loc['activity', 'coders_conv_fact'] / ann_dem
                if time['tod'] == config.time.iloc[0]['tod']:
                    dsd_rows.append(DemandSpecificDistribution(
                        region=in_region, period=period,
                        season=time['season'], tod=time['tod'],
                        demand_name=dem_comm['commodity'], dsd=dsd,
                        notes=note, data_source=ref.id, dq_cred=2, data_id=data_id,
                    ))
                else:
                    dsd_rows.append(DemandSpecificDistribution(
                        region=in_region, period=period,
                        season=time['season'], tod=time['tod'],
                        demand_name=dem_comm['commodity'], dsd=dsd, data_id=data_id,
                    ))
        if dsd_rows:
            curs.executemany(*DemandSpecificDistribution.bulk_insert_or_ignore_sql(dsd_rows))
    
    else:
        print(f"Got zero flow for boundary intertie from {in_region} out to {out_region}. Skipped outgoing intertie.")

    
    """
    ##############################################################
        Variable generator entering region
    ##############################################################
    """

    if max(in_mwh) > 0:

        tech_config = config.trans_techs.loc['int_in']
        input_comm = config.commodities.loc[tech_config['in_comm']]
        output_comm = config.commodities.loc[tech_config['out_comm']]

        tech = f"{tech_config['tech']}-{out_region}"
        desc = f"{tech_config['description']} - {out_region} into {in_region}"


        ## Technology
        curs.executemany(*Technology.bulk_insert_or_ignore_sql([Technology(
            tech=tech, flag='p', sector='electricity', curtail=1,
            description=desc, data_id=data_id,
        )]))

        ## ExistingCapacity
        capacity = max(in_mwh) * config.units.loc['intertie_capacity', 'coders_conv_fact'] # MWh/h to GW
        curs.executemany(*ExistingCapacity.bulk_insert_or_ignore_sql([ExistingCapacity(
            region=in_region, tech=tech, vintage=vint, capacity=capacity,
            units=f"({config.units.loc['capacity', 'units']})",
            notes=f"max {weather_year} hourly flow entering {in_region} once summed along all interties - {intertie_names}",
            data_source=config.refs.get("transfers").id, dq_cred=2, data_id=data_id,
        )]))

        ## Efficiency
        curs.executemany(*Efficiency.bulk_insert_or_ignore_sql([Efficiency(
            region=in_region, input_comm=input_comm['commodity'],
            tech=tech, vintage=vint, output_comm=output_comm['commodity'],
            efficiency=1, notes="dummy input so arbitrary", data_id=data_id,
        )]))

        ## CapacityToActivity
        curs.executemany(*CapacityToActivity.bulk_insert_or_ignore_sql([CapacityToActivity(
            region=in_region, tech=tech, c2a=config.params['c2a'],
            notes=f"({config.params['c2a_unit']})", data_id=data_id,
        )]))

        ## CapacityFactorTech (no period in v4)
        note = f"{weather_year} hourly flow entering {in_region} divided by max hourly flow"
        ref = config.refs.get("transfers")

        cf_rows = []
        for h, time in config.time.iterrows():
            cf = in_mwh[h] / max(in_mwh)
            if cf < config.params['cf_tolerance']: cf = 0
            if time['tod'] == config.time.iloc[0]['tod']:
                cf_rows.append(CapacityFactorTech(
                    region=in_region, season=time['season'], tod=time['tod'],
                    tech=tech, factor=cf, notes=note,
                    data_source=ref.id, dq_cred=2, data_id=data_id,
                ))
            else:
                cf_rows.append(CapacityFactorTech(
                    region=in_region, season=time['season'], tod=time['tod'],
                    tech=tech, factor=cf, data_id=data_id,
                ))
        if cf_rows:
            curs.executemany(*CapacityFactorTech.bulk_insert_or_ignore_sql(cf_rows))
        
    else:
        print(f"Got zero flow for boundary intertie from {out_region} into {in_region}. Skipped incoming intertie.")



def aggregate_endogenous_interfaces(df_interfaces: pd.DataFrame):

    # This gets only fully endogenous interfaces
    if config.params['full_dataset']:
        # Only interfaces between Canadian regions
        df_endogenous = df_interfaces.loc[['USA' not in r1_r2 for r1_r2 in df_interfaces.index]]
    else:
        # Only interfaces between endogenous regions
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
        r1r2 = f"{region_1}-{region_2}"

        sorted_r = sorted(r1_r2)
        data_id = utils.data_id(f"EINT{sorted_r[0]}{sorted_r[1]}")

        tech_config = config.trans_techs.loc['int']
        input_comm = config.commodities.loc[tech_config['in_comm']]
        output_comm = config.commodities.loc[tech_config['out_comm']]


        ## Technology
        curs.executemany(*Technology.bulk_insert_or_ignore_sql([Technology(
            tech=tech_config['tech'], flag='p', sector='electricity', exchange=1,
            description=tech_config['description'], data_id=utils.data_id(),
        )]))

        ## Efficiency
        eff = 1.0 - float(df_sys.loc[region_1, 'system_line_losses_percent'])
        note = f"({output_comm['units']}/{input_comm['units']}) {region_1} system_line_losses_percent"
        curs.executemany(*Efficiency.bulk_insert_or_ignore_sql([Efficiency(
            region=r1r2, input_comm=input_comm['commodity'],
            tech=tech_config['tech'], vintage=vint,
            output_comm=output_comm['commodity'], efficiency=eff, notes=note,
            data_source=config.refs.get('ca_system_parameters').id, dq_cred=2,
            data_id=data_id,
        )]))

        ## CapacityToActivity
        curs.executemany(*CapacityToActivity.bulk_insert_or_ignore_sql([CapacityToActivity(
            region=r1r2, tech=tech_config['tech'], c2a=config.params['c2a'],
            notes=f"({config.params['c2a_unit']})", data_id=data_id,
        )]))

        ## ExistingCapacity
        # Capacity in each direction is max seasonal capacity
        reverse_interface = df_endogenous.loc[region_2, region_1]
        reverse_capacity = max(reverse_interface['ttc_summer'], reverse_interface['ttc_winter'])
        forward_capacity = max(interface['ttc_summer'], interface['ttc_winter'])

        # Capacity r1-r2 must equal r2-r1 by the RegionalExchangeCapacity_Constraint
        capacity = max(forward_capacity, reverse_capacity) * config.units.loc['capacity', 'coders_conv_fact'] # MW to GW

        curs.executemany(*ExistingCapacity.bulk_insert_or_ignore_sql([ExistingCapacity(
            region=r1r2, tech=tech_config['tech'], vintage=vint, capacity=capacity,
            units=f"({config.units.loc['capacity', 'units']})",
            notes=f"max of seasonal capacities in either direction - {interface['network_node_names']}",
            data_source=config.refs.get('interface_capacities').id, dq_cred=2,
            data_id=data_id,
        )]))

        ## CapacityFactorTech (no period in v4)
        # Needed if capacity in either direction or season is less than max capacity
        if len({reverse_interface['ttc_summer'], reverse_interface['ttc_winter'],
            interface['ttc_summer'], interface['ttc_winter']}) > 1:

            cf_rows = []
            for h, time in config.time.iterrows():
                cf = interface[f"ttc_{time['summer_winter']}"] * config.units.loc['capacity', 'coders_conv_fact'] / capacity
                if cf < config.params['cf_tolerance']: cf = 0
                if time['tod'] == config.time.iloc[0]['tod']:
                    cf_rows.append(CapacityFactorTech(
                        region=r1r2, season=time['season'], tod=time['tod'],
                        tech=tech_config['tech'], factor=cf,
                        notes="seasonal, directional capacity divided by max capacity in either season or direction",
                        data_source=config.refs.get('interface_capacities').id, dq_cred=2,
                        data_id=data_id,
                    ))
                else:
                    cf_rows.append(CapacityFactorTech(
                        region=r1r2, season=time['season'], tod=time['tod'],
                        tech=tech_config['tech'], factor=cf, data_id=data_id,
                    ))
            if cf_rows:
                curs.executemany(*CapacityFactorTech.bulk_insert_or_ignore_sql(cf_rows))


        ## CostVariable
        for period in config.model_periods:
            cost_tx_dx.aggregate(r1r2, period, tech_config['tech'], vint, curs, data_id, 'tx')



"""
##############################################################
    Retrieves historical hourly flows for a given intertie
##############################################################
"""

# Gets MWh transferred for each hour of the base year along a given intertie
def get_transfered_mwh(region_1, region_2, intertie_type) -> tuple[np.ndarray, np.ndarray]:

    data_year = config.params['weather_year']

    _coders_kwargs = dict(
        cache_dir=config.cache_dir,
        force_download=config.params.get('force_download', False),
        api_key_file=config.input_files + config.params['coders_api_key_file'],
        debug=config.debug,
    )
    if intertie_type == 'international':
        df_transfers, date_accessed = coders_api.get_data(end_point="international_transfers", year=data_year, province=region_1, us_state=region_2, **_coders_kwargs)
    elif intertie_type == 'interprovincial':
        df_transfers, date_accessed = coders_api.get_data(end_point="interprovincial_transfers", year=data_year, province1=region_1, province2=region_2, **_coders_kwargs)

    if df_transfers is None or (len(df_transfers) < 8760):
        print(f"Insufficient {intertie_type} transfer data on {region_1}-{region_2}.")
        return None, None
    
    # Add reference for both directions for ease of pulling
    reference = config.params['coders']['reference'].replace("<date>", date_accessed).replace("<table>","international_transfers, interprovincial_transfers")
    config.refs.add(f"transfers", reference)
  
    hourly_mwh = df_transfers['transfers_MWh'].iloc[0:8760].astype(float).ffill().to_numpy()

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