"""
Performs some final post-processing on aggregated data
Written by Ian David Elder for the CANOE model
"""

import sqlite3
from setup import config



def process():

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()


    """
    ##############################################################
        Fill basic tables
    ##############################################################
    """

    # Add default global discount rate. No index on this table so clear it first.
    curs.execute("DELETE FROM GlobalDiscountRate")
    curs.execute(f"INSERT INTO GlobalDiscountRate(rate) VALUES({config.params['global_discount_rate']})")

    # Add future model periods
    for period in [*config.model_periods, config.model_periods[-1] + config.params['period_step']]: 
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
    curs.execute(f"DELETE FROM time_season")
    curs.execute(f"DELETE FROM time_of_day")
    for h, row in config.time.iterrows():
        curs.execute(f"""INSERT OR IGNORE INTO
                    time_season(t_season)
                    VALUES("{row['season']}")""")
        curs.execute(f"""INSERT OR IGNORE INTO
                    time_of_day(t_day)
                    VALUES("{row['time_of_day']}")""")


    conn.commit()
    conn.close()