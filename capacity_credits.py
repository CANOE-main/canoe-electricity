"""
Aggregates capacity credits
Written by Ian David Elder for the CANOE model
"""

import pandas as pd
from setup import config
import utils
import sqlite3

# Provincial scripts
import provincial_data.ontario.existing_capacity_credits as on_cc_exs


# Sends existing capacity to relevant provincial scripts
def aggregate_existing(df_rtv: pd.DataFrame):

    on_cc_exs.aggregate_capacity_credits(df_rtv) #.loc[df_rtv['region'] == 'ON']) # for now, using Ontario for all # use ontario existing capacity credits


# Aggregates new generators capacity credits
def aggregate_new(df_rtv: pd.DataFrame):

    # Most generators same as existing
    on_cc_exs.aggregate_capacity_credits(df_rtv) #.loc[df_rtv['region'] == 'ON']) # for now, using Ontario for all # use ontario existing capacity credits

    ## TODO
    # wind/solar/hydro ror -> NREL ReEDS method


# Aggregates new storage capacity credits
def aggregate_storage(df_rtv: pd.DataFrame):

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()

    # Temporary for now. CC = 1
    for _idx, rtv in df_rtv.iterrows():
        for period in config.model_periods:

            if rtv['vint'] > period or rtv['vint'] + rtv['life'] <= period: continue

            curs.execute(f"""REPLACE INTO
                        CapacityCredit(regions, periods, tech, vintage, cc_tech, cc_tech_notes, dq_est)
                        VALUES('{rtv['region']}', {period}, '{rtv['tech']}', {rtv['vint']}, 1,
                        'Assumed for now. Improved method on TODO list', 5)""")
            
    conn.commit()
    conn.close()