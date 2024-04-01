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
import pandas as pd
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

    # TODO temp for prototyping
    # prepare_test_model()
    
    if config.params['show_plots']: pp.show()



"""
##############################################################
    The following is setup for electricity sector testing
##############################################################
"""

def prepare_test_model():

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()
      
    rep_days = {
        'D001': 'Jan',
        'D009': 'Jan',
        'D045': 'Feb',
        'D103': 'Apr',
        'D128': 'May',
        'D173': 'Jun',
        'D184': 'Jul'
        }

    curs.execute(f"""REPLACE INTO sector_labels(sector) VALUES('electric')""")

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

    df_dsd = pd.read_sql_query("SELECT * FROM DemandSpecificDistribution", conn)
    df_dsd = df_dsd.groupby(['regions','demand_name'])
    for grp in df_dsd.groups:
        df_grp = df_dsd.get_group(grp)
        total_dsd = df_grp['dsd'].sum()
        curs.execute(f"""UPDATE DemandSpecificDistribution
                    SET dsd = dsd / {total_dsd}
                    WHERE regions = '{df_grp['regions'].iloc[0]}'
                    AND demand_name == '{df_grp['demand_name'].iloc[0]}'""")

    for day in rep_days.keys():
        for h in range(24):
            curs.execute(f"""REPLACE INTO SegFrac(season_name, time_of_day_name, segfrac)
                        VALUES('{day}', '{config.time.loc[h, 'time_of_day']}', {1/(24*7)})""")

    base_emis = 52000
    emis = {
        2021: 1.00,
        2025: 0.80,
        2030: 0.65,
        2035: 0.50,
        2040: 0.35,
        2045: 0.20,
        2050: 0.05
    }

    emis_comms = [c[0] for c in curs.execute("SELECT comm_name FROM commodities WHERE flag == 'e'")]

    for emis_comm in emis_comms:
        for period in config.model_periods:
            curs.execute(f"""REPLACE INTO
                        EmissionLimit(regions, periods, emis_comm, emis_limit, emis_limit_units)
                        VALUES("global", {period}, "{emis_comm}", {emis[period]*base_emis}, "kt")""")

    conn.commit()
    conn.close()

    print("Finished.")



if __name__ == "__main__":

    build_database()