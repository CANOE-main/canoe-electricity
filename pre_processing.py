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
    # curs.execute(f"UPDATE MetaDataReal SET value = {config.params['global_discount_rate']} WHERE element == 'global_discount_rate'")

    # Add future model periods
    for i, period in enumerate([*config.model_periods, config.model_periods[-1] + config.params['period_step']]): 
        curs.execute(f"""REPLACE INTO
                    TimePeriod(sequence, period, flag)
                    VALUES({i}, {period}, "f")""")

    # Add regions
    for region in config.model_regions:
        description = "outside model" if region == "EX" else config.regions.loc[region, 'description']
        curs.execute(f"""REPLACE INTO
                    Region(region, notes)
                    VALUES("{region}", "{description}")""")
    
    # Add seasons and times of day
    curs.execute(f"DELETE FROM SeasonLabel")
    curs.execute(f"DELETE FROM TimeOfDay")
    for h, row in config.time.iterrows():
        curs.execute(f"""INSERT OR IGNORE INTO
                    SeasonLabel(season)
                    VALUES("{row['season']}")""")
        curs.execute(f"""INSERT OR IGNORE INTO
                    TimeOfDay(sequence, tod)
                    VALUES({h}, "{row['tod']}")""")


    conn.commit()
    conn.close()



if __name__ == "__main__":

    process()