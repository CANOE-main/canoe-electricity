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

# Provincial parameters
df_sys: pd.DataFrame

weather_year = config.params['weather_year']



def aggregate():

    global df_sys

    # Provincial system parameters
    _ca_sys_params, df_sys, date_accessed = coders_api.get_data(end_point='CA_system_parameters')
    df_sys['region'] = [config.region_map[p.lower()] for p in df_sys['province'].values]
    df_sys = df_sys.loc[df_sys['region'].isin(config.model_regions)]
    df_sys.set_index('region', inplace=True)
    config.references['ca_system_parameters'] = config.params['coders']['reference'].replace('<table>', 'ca_system_parameters').replace('<date>', date_accessed)

    if config.params['include_reserve_margin']: aggregate_reserve_margin()
    if config.params['include_provincial_demand']: aggregate_demand()
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
        curs.execute(f"""REPLACE INTO
                    PlanningReserveMargin(regions, reserve_margin, reference, data_flags, dq_est, additional_notes)
                    VALUES("{region}", "{reserve_margin}", "{config.references['ca_system_parameters']}", "coders", 1, "reserve_requirements_percent")""")

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
    tx_techs = ["tx_to_dx"]
    dummy_techs = ["dx_to_dem", "g_to_tx", "grps_to_tx"]

    for code, tech_config in config.trans_techs.iterrows():
        

        ## Technologies
        curs.execute(f"""REPLACE INTO
                    technologies(tech, flag, sector, tech_desc)
                    VALUES("{tech_config['tech']}", "p", "electricity", "{tech_config['description']}")""")


        ## Efficiency
        for region, row in df_sys.iterrows():

            input_comm = config.commodities.loc[tech_config['in_comm']]
            output_comm = config.commodities.loc[tech_config['out_comm']]

            # Eff is line loss for TX <-> DX or 1 for dummy techs
            if code in tx_techs:
                note = f"({output_comm['units']}/{input_comm['units']}) {region} system_line_losses_percent"
                curs.execute(f"""REPLACE INTO
                            Efficiency(regions, input_comm, tech, vintage, output_comm, efficiency, eff_notes, reference, data_flags, dq_est)
                            VALUES("{region}", "{input_comm['commodity']}", "{tech_config['tech']}", {config.model_periods[0]}, "{output_comm['commodity']}",
                            {1.0 - float(row["system_line_losses_percent"])}, "{note}", "{config.references['ca_system_parameters']}", "coders", 1)""")
            elif code in dummy_techs:
                curs.execute(f"""REPLACE INTO
                            Efficiency(regions, input_comm, tech, vintage, output_comm, efficiency, eff_notes)
                            VALUES("{region}", "{input_comm['commodity']}", "{tech_config['tech']}",
                            {config.model_periods[0]}, "{output_comm['commodity']}", 1, "dummy tech")""")


    print(f"Transmission aggregated into {os.path.basename(config.database_file)}\n")

    conn.commit()
    conn.close()



def aggregate_demand():

    print("Aggregating provincial electricity demand...")

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()

    # Annual demand projections
    _annual, df_annual, date_accessed = coders_api.get_data(end_point="forecasted_annual_demand")
    config.references['forecasted_annual_demand'] = config.params['coders']['reference'].replace("<date>", date_accessed).replace("<table>", "forecasted_annual_demand")
    df_annual['region'] = [config.region_map[p.lower()] for p in df_annual['province']]
    df_annual.set_index('region', inplace=True)

    # Demand commodity
    dem_comm = config.commodities.loc['demand']

    # Get available data provinces and years from coders
    _json, df_avail, _date = coders_api.get_data(end_point="provincial_demand")

    for _idx, prov in df_avail.iterrows():

        region = config.region_map[prov['province'].lower()]
        if region not in config.model_regions: continue
        if not config.regions.loc[region, 'include_demand']: continue

        """
        ##############################################################
            Annual provincial electricity demand
        ##############################################################
        """

        ## Demand
        for period in config.model_periods:

            ann_dem = config.units.loc['demand', 'coders_conv_fact'] * df_annual.loc[region, str(period)]

            curs.execute(f"""REPLACE INTO
                        Demand(regions, periods, demand_comm, demand, demand_units, demand_notes, reference, data_flags, dq_est)
                        VALUES("{region}", {period}, "{dem_comm['commodity']}", {ann_dem}, "({dem_comm['units']})",
                        "provincial electricity demand projection {df_annual.loc[region, 'province']} {period}",
                        "{config.references["forecasted_annual_demand"]}", "coders", 1)""")


        """
        ##############################################################
            Hourly provincial electricity demand
        ##############################################################
        """

        if str(weather_year) not in prov['year']:
            print(f"Provincial hourly demand data not available for {region} for year {weather_year} so DemandSpecificDistribution was skipped.")
            continue

        _hourly, df_hourly, date_accessed = coders_api.get_data(end_point="provincial_demand", year=weather_year, province=prov['province'])
        dsd_reference = config.params['coders']['reference'].replace("<date>", date_accessed).replace("<table>", "provincial_demand")
        config.references[f"provincial_demand_{region.lower()}"] = dsd_reference

        if df_hourly is None or (len(df_hourly) < 8760):
            print(f"Insufficient hourly demand data available for {region} so DemandSpecificDistribution was skipped.")
            continue

        hourly_dem = df_hourly['demand_MWh'].iloc[0:8760].ffill().to_numpy()
        
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
        for h, row in config.time.iterrows():

            curs.execute(f"""REPLACE INTO
                        DemandSpecificDistribution(regions, season_name, time_of_day_name, demand_name, dsd, dsd_notes, reference, data_flags, dq_est)
                        VALUES("{region}", "{row['season']}", "{row['time_of_day']}", "{dem_comm['commodity']}", {dsd[h]},
                        "{weather_year} hourly demand divided by sum of hourly demand for that year",
                        "{dsd_reference}", "coders", 1)""")
            
    
    conn.commit()
    conn.close()

    print(f"Provincial electricity demand data aggregated into {os.path.basename(config.database_file)}\n")



if __name__ == "__main__":

    aggregate()