"""
Builds the electricity sector database to be merged into the larger model
Written by Ian David Elder for the CANOE model
"""

import sqlite3
import utils
import pre_processing
import post_processing
import os
import model_reduction
import interfaces
import setup
import currency_conversion
import generators
import provincial_grids
from setup import config
from matplotlib import pyplot as pp



def build_database():

    print(f"Aggregating electricity sector into {os.path.basename(config.database_file)}...\n")

    setup.instantiate_database()

    pre_processing.process()

    generators.aggregate()
    interfaces.aggregate()
    provincial_grids.aggregate()

    currency_conversion.convert_currencies()
    if config.params['simplify_model']: model_reduction.simplify_model()
    
    post_processing.process()
    
    if config.params['clone_to_excel']: utils.database_converter().clone_sqlite_to_excel()

    print(f"Electricity sector aggregated into {os.path.basename(config.database_file)}\n")
    
    if config.params['show_plots']: pp.show()



if __name__ == "__main__":

    build_database()



"""
##############################################################
    The following is setup for electricity sector testing
##############################################################
"""

def prepare_test_model():

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()

    data_year = 2020

    demand = utils.get_data(f"http://reports.ieso.ca/public/Demand/PUB_Demand_{data_year}.csv", index_col=False, skiprows=3, nrows=8760).rename(columns={"Ontario Demand": "demand"})
    mwh_to_pj = 3600/1E9
    demand['demand'] = demand["demand"] * mwh_to_pj
    total_demand = sum(demand['demand'])

    gdp_index = {
        2025: 1.088,
        2030: 1.184,
        2035: 1.300,
        2040: 1.429,
        2045: 1.562,
        2050: 1.708
    }

    for period in config.model_periods:
        curs.execute(f"""REPLACE INTO Demand(regions, periods, demand_comm, demand, demand_units)
                    VALUES("ON", {period}, 'D_ELC', {total_demand*gdp_index[period]}, "PJ")""")
        
    rep_days = {
        'D001': 'Jan',
        'D009': 'Jan',
        'D045': 'Feb',
        'D103': 'Apr',
        'D128': 'May',
        'D173': 'Jun',
        'D184': 'Jul'
        }

    for h in range(8760):
        curs.execute(f"""REPLACE INTO DemandSpecificDistribution(regions, season_name, time_of_day_name, demand_name, dsd)
                    VALUES("ON", '{config.time.loc[h, 'season']}', '{config.time.loc[h, 'time_of_day']}', 'D_ELC', {demand['demand'][h]})""")
        
    curs.execute(f"""REPLACE INTO sector_labels(sector) VALUES('electric')""")
        
    curs.execute(f"""UPDATE Efficiency
                    SET efficiency = 0.80
                    WHERE tech like '%PMP%'""")
    curs.execute(f"""UPDATE Efficiency
                    SET efficiency = 0.90
                    WHERE tech like '%BAT%'""")

    curs.execute(f"DELETE FROM time_season")
    [curs.execute(f"INSERT INTO time_season(t_season) VALUES('{day}')") for day in rep_days.keys()]

    seas_tables = [
        'CapacityFactorTech',
        'DemandSpecificDistribution',
        'MinSeasonalActivity',
        'MaxSeasonalActivity'
        ]

    for table in seas_tables:
        curs.execute(f"DELETE FROM {table} WHERE season_name NOT IN (SELECT t_season from time_season)")

    total_dsd = sum([dsd[0] for dsd in curs.execute("SELECT dsd FROM DemandSpecificDistribution").fetchall()])
    curs.execute(f"""UPDATE DemandSpecificDistribution
                SET dsd = dsd / {total_dsd}""")

    for day in rep_days.keys():
        for h in range(24):
            curs.execute(f"""REPLACE INTO SegFrac(season_name, time_of_day_name, segfrac)
                        VALUES('{day}', '{config.time.loc[h, 'time_of_day']}', {1/(24*7)})""")

    base_emis = 3200
    emis = {
        2025: 1,
        2030: 0.8,
        2035: 0.6,
        2040: 0.4,
        2045: 0.2,
        2050: 0
    }

    for period in config.model_periods:
        curs.execute(f"""REPLACE INTO
                    EmissionLimit(regions, periods, emis_comm, emis_limit, emis_limit_units)
                    VALUES("ON", {period}, "CO2eq", {emis[period]*base_emis}, "ktCO2eq")""")

    conn.commit()
    conn.close()

    print("Finished.")