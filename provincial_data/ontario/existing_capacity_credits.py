"""
Gets non-VRE capacity credits from IESO reliability outlook
Written by Ian David Elder for the CANOE model
"""

import sqlite3
import utils
import os
from setup import config
import pandas as pd



def aggregate_ccs(df_rtv: pd.DataFrame):
    
    df_cc, note, reference, year = get_capacity_credits()

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()

    for _idx, rtv in df_rtv.iterrows():
        for period in config.model_periods:

            if rtv['vint'] > period or rtv['vint'] + rtv['life'] <= period: continue

            curs.execute(f"""REPLACE INTO
                        CapacityCredit(regions, periods, tech, vintage, cc_tech, cc_tech_notes,
                        reference, data_year, dq_rel, dq_comp, dq_time, dq_geog, dq_tech)
                        VALUES('{rtv['region']}', {period}, '{rtv['tech']}', {rtv['vint']}, {float(df_cc.loc[rtv['tech_code']])}, '{note}',
                        '{reference}', {year}, 1, 1, {utils.dq_time(year, period)}, 1, 1)""")
            
    conn.commit()
    conn.close()



def get_capacity_credits() -> tuple[pd.DataFrame, str, str, str]:

    this_dir = os.path.realpath(os.path.dirname(__file__)) + "/"

    # The most recent or desired ieso reliability outlook
    yyyy, mmm = config.params['ieso_rel_yyyy_mmm'].split("_")
    peak_type: str = config.params['ieso_rel_peak_type']

    rel_outlook_url = f"https://www.ieso.ca/-/media/Files/IESO/Document-Library/planning-forecasts/reliability-outlook/ReliabilityOutlookTables_{yyyy}{mmm}.ashx"
    note = f"Forecasted capability at {peak_type.lower()} summer peak divided by total installed capacity"
    reference = f"IESO. ({yyyy}, {mmm}). Reliability Outlook. https://www.ieso.ca/en/Sector-Participants/Planning-and-Forecasting/Reliability-Outlook"

    # Get the reliability outlook forecast peak table and calculate capacity credits
    df_rel = utils.get_data(rel_outlook_url, file_type='xlsx', cache_file_type='csv', sheet_name='Table 4.1', skiprows=4, header=0, nrows=6, index_col=0).astype(float)
    df_rel['cc'] = df_rel[f"Forecast Capability at 2024 Summer Peak [{peak_type}] (MW)"] / df_rel['Total Installed Capacity\n(MW)']
    df_rel.index = df_rel.index.str.lower()
    df_cc = pd.DataFrame()

    # Convert from IESO fuel types to CANOE generator codes
    df_types = pd.read_csv(this_dir + 'fuel_types.csv', index_col=0)

    for fuel_type, row in df_types.iterrows():
        for code in row['codes'].split("+"):
            df_cc.loc[code, 'cc'] = df_rel.loc[fuel_type, 'cc']

    # Output to csv for readability
    df_cc.to_csv(this_dir + f"output_data/capacity_credits_{yyyy}_{mmm}.csv")

    return df_cc, note, reference, int(yyyy)