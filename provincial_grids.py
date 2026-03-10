"""
Aggregates transmission dummy techs, line losses and planning reserve margin
Written by Ian David Elder for the CANOE model
"""

import sqlite3
from setup import config
import coders_api
import os
from matplotlib import pyplot as pp
import pandas as pd
import utils

from provincial_data.default import cost_tx_dx

# Provincial parameters
df_sys: pd.DataFrame

weather_year = config.params['weather_year']



def aggregate():

    global df_sys

    # Provincial system parameters
    df_sys, date_accessed = coders_api.get_data(end_point='CA_system_parameters')
    df_sys['region'] = [config.region_map[p.lower()] for p in df_sys['province'].values]
    df_sys = df_sys.loc[df_sys['region'].isin(config.model_regions)]
    df_sys.set_index('region', inplace=True)
    citation = config.params['coders']['reference'].replace('<table>', 'ca_system_parameters').replace('<date>', date_accessed)
    ref = config.refs.add('ca_system_parameters', citation)

    if config.params['include_reserve_margin']: aggregate_reserve_margin()
    aggregate_demand()
    aggregate_transmission()



def aggregate_reserve_margin():

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()


    """
    ##############################################################
        Planning reserve margin
    ##############################################################
    """

    for region, row in df_sys.iterrows():

        ## PlanningReserveMargin
        reserve_margin = row['reserve_requirements_percent']
        ref = config.refs.get('ca_system_parameters')
        curs.execute(f"""REPLACE INTO
                    PlanningReserveMargin(region, margin, notes, data_source, dq_cred, data_id)
                    VALUES("{region}", "{reserve_margin}", "CODERS - ca_system_parameters - reserve_requirements_percent", "{ref.id}", 2, "{utils.data_id(region)}")""")

    print(f"Planning reserve margin aggregated into {os.path.basename(config.database_file)}\n")

    conn.commit()
    conn.close()



# In-province grid transmission structure
def aggregate_transmission():

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()


    """
    ##############################################################
        Transmission techs
    ##############################################################
    """

    # Transmission techs ELC_TX <--> ELC_DX --> D_ELC
    for code in ['tx_to_dx', 'dx_to_dem']:

        tech_config = config.trans_techs.loc[code]

        ## Technology
        curs.execute(f"""REPLACE INTO
                    Technology(tech, flag, sector, unlim_cap, description, data_id)
                    VALUES("{tech_config['tech']}", "p", "electricity", 1, "{tech_config['description']}", "{utils.data_id()}")""")
        

    ## CostVariable
    for region, row in df_sys.iterrows():
        for period in config.model_periods:
            cost_tx_dx.aggregate(region, period, config.trans_techs.loc['tx_to_dx']['tech'], config.model_periods[0], curs, utils.data_id(region), 'tx')
            cost_tx_dx.aggregate(region, period, config.trans_techs.loc['dx_to_dem']['tech'], config.model_periods[0], curs, utils.data_id(region), 'dx')


    ## Efficiency
    # TX to DX includes line loss
    for region, row in df_sys.iterrows():
        
        tech_config = config.trans_techs.loc['tx_to_dx']

        input_comm = config.commodities.loc[tech_config['in_comm']]
        output_comm = config.commodities.loc[tech_config['out_comm']]

        note = f"({output_comm['units']}/{input_comm['units']}) coders {region} system_line_losses_percent"
        curs.execute(f"""REPLACE INTO
                    Efficiency(region, input_comm, tech, vintage, output_comm, efficiency, notes, data_source, data_id)
                    VALUES("{region}", "{input_comm['commodity']}", "{tech_config['tech']}", {config.model_periods[0]}, "{output_comm['commodity']}",
                    {1.0 - float(row["system_line_losses_percent"])}, "{note}", "{config.refs.get('ca_system_parameters').id}", "{utils.data_id(region)}")""")
    
    # DX to DEM just a dummy for distribution costs
    for region in config.model_regions:
        
        tech_config = config.trans_techs.loc['dx_to_dem']

        input_comm = config.commodities.loc[tech_config['in_comm']]
        output_comm = config.commodities.loc[tech_config['out_comm']]

        curs.execute(f"""REPLACE INTO
                    Efficiency(region, input_comm, tech, vintage, output_comm, efficiency, notes, data_id)
                    VALUES("{region}", "{input_comm['commodity']}", "{tech_config['tech']}", {config.model_periods[0]}, "{output_comm['commodity']}",
                    1, "dummy tech for distribution costs", "{utils.data_id(region)}")""")

    print(f"Transmission aggregated into {os.path.basename(config.database_file)}\n")

    conn.commit()
    conn.close()



def aggregate_demand():

    print("Aggregating provincial electricity demand...")

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()

    # Annual demand projections
    df_annual, date_accessed = coders_api.get_data(end_point="forecasted_annual_demand")
    citation = config.params['coders']['reference'].replace("<date>", date_accessed).replace("<table>", "forecasted_annual_demand")
    config.refs.add('forecasted_annual_demand', citation)
    df_annual['region'] = [config.region_map[p.lower()] for p in df_annual['province']]
    df_annual.set_index('region', inplace=True)

    # Demand tech and commodity data
    dem_comm = config.commodities.loc['demand']
    tech_config = config.trans_techs.loc['demand']
    input_comm = config.commodities.loc[tech_config['in_comm']]
    output_comm = config.commodities.loc[tech_config['out_comm']]

    # Get available data provinces and years from coders
    df_avail, _date = coders_api.get_data(end_point="provincial_demand")

    for _idx, prov in df_avail.iterrows():

        region = config.region_map[prov['province'].lower()]
        if region not in config.model_regions: continue

        data_id = utils.data_id(f"DEM{region}")


        """
        ##############################################################
            Hourly provincial electricity demand
        ##############################################################
        """

        if str(weather_year) not in prov['year']:
            print(f"Provincial hourly demand data not available for {region} for year {weather_year} so DemandSpecificDistribution was skipped.")
            continue

        df_hourly, date_accessed = coders_api.get_data(end_point="provincial_demand", year=weather_year, province=prov['province'])
        dsd_reference = config.params['coders']['reference'].replace("<date>", date_accessed).replace("<table>", "provincial_demand")
        ref = config.refs.add(f"provincial_demand", dsd_reference)

        if df_hourly is None or (len(df_hourly) < 8760):
            print(f"Insufficient hourly demand data available for {region} so DemandSpecificDistribution was skipped.")
            continue

        hourly_dem = df_hourly['demand_MWh'].iloc[0:8760].astype(float).ffill().to_numpy()

        # Store hourly demand to calculate capacity credits for VREs
        # Can't turn back before this point or wont be able to calculate CCs
        config.provincial_demand[region] = hourly_dem


        ## Technology
        curs.execute(f"""REPLACE INTO
                    Technology(tech, flag, sector, unlim_cap, annual, description, data_id)
                    VALUES("{tech_config['tech']}", "p", "electricity", 1, 1, "{tech_config['description']}", "{utils.data_id()}")""")


        ## Efficiency
        curs.execute(f"""REPLACE INTO
                    Efficiency(region, input_comm, tech, vintage, output_comm, efficiency, notes, data_id)
                    VALUES("{region}", "{input_comm['commodity']}", "{tech_config['tech']}",
                    {config.model_periods[0]}, "{output_comm['commodity']}", 1, "dummy tech", "{data_id}")""")


        # If not including demand, don't go any further
        if not config.params['include_provincial_demand'] or not config.regions.loc[region, 'include_demand']: continue
        

        # Apply tolerance and normalise
        hourly_dem[hourly_dem < hourly_dem.mean() * config.params['dsd_tolerance']] = 0
        dsd = hourly_dem / hourly_dem.sum()

        # Plot provincial demand
        pp.figure()
        pp.plot(dsd)
        pp.title(f"{region} normalised hourly electricity demand")
        pp.ylabel("DSD")
        pp.xlabel("Hour of year")


        ## DemandSpecificDistribution
        note = f"{weather_year} hourly demand divided by sum of hourly demand for that year"

        data = []
        for period in config.model_periods:
            for h, time in config.time.iterrows():

                if time['tod'] == config.time.iloc[0]['tod']:
                    data.append([region, period, time['season'], time['tod'], dem_comm['commodity'], dsd[h], note, ref.id, 2, data_id])
                else:
                    data.append([region, period, time['season'], time['tod'], dem_comm['commodity'], dsd[h], None, None, None, data_id])

        curs.executemany(f"""REPLACE INTO
                    DemandSpecificDistribution(region, period, season, tod, demand_name, dsd, notes, data_source, dq_cred, data_id)
                    VALUES(?,?,?,?,?,?,?,?,?,?)""", data)
        

        """
        ##############################################################
            Annual provincial electricity demand
        ##############################################################
        """

        ## Demand
        for period in config.model_periods:
            
            demand_year = str(utils.data_year(period))
            ann_dem = config.units.loc['demand', 'coders_conv_fact'] * df_annual.loc[region, demand_year]

            curs.execute(f"""REPLACE INTO
                        Demand(region, period, commodity, demand, units, notes, data_source, dq_cred, data_id)
                        VALUES("{region}", {period}, "{dem_comm['commodity']}", {ann_dem}, "({dem_comm['units']})",
                        "provincial electricity demand projection {df_annual.loc[region, 'province']} {demand_year}",
                        "{config.refs.get("forecasted_annual_demand").id}", 2, "{data_id}")""")
            
    
    conn.commit()
    conn.close()

    print(f"Provincial electricity demand data aggregated into {os.path.basename(config.database_file)}\n")



if __name__ == "__main__":

    aggregate()