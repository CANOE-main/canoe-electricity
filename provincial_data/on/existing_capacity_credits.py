"""
Gets non-VRE capacity credits from IESO reliability outlook
Written by Ian David Elder for the CANOE model
"""

import sqlite3
import canoe_electricity.utils as utils
import os
from canoe_electricity.setup import config
import pandas as pd
from canoe_schema.v4_0.models import CapacityCredit, ReserveCapacityDerate



def aggregate_capacity_credits(df_rtv: pd.DataFrame):

    df_cc, note, year = get_capacity_credits()
    ref = config.refs.get('cc')

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()

    for _idx, rtv in df_rtv.iterrows():

        cc_rows = []
        for period in config.model_periods:

            if rtv['vint'] > period or rtv['vint'] + rtv['life'] <= period: continue

            cc_rows.append(CapacityCredit(
                region=rtv['region'],
                period=period,
                tech=rtv['tech'],
                vintage=rtv['vint'],
                credit=float(df_cc.loc[rtv['tech_code']].iloc[0]),
                notes=note,
                data_source=ref.id,
                dq_cred=1,
                dq_geog=1,
                dq_struc=2,
                dq_tech=2,
                dq_time=3,
                data_id=utils.data_id(rtv['region']),
            ))

        if cc_rows:
            curs.executemany(*CapacityCredit.bulk_insert_or_ignore_sql(cc_rows))

            # ReserveCapacityDerate has no period in v4 — write once per (rtv, season)
            rcd_rows = [
                ReserveCapacityDerate(
                    region=rtv['region'],
                    season=season,
                    tech=rtv['tech'],
                    vintage=rtv['vint'],
                    factor=float(df_cc.loc[rtv['tech_code']].iloc[0]),
                    notes=note,
                    data_source=ref.id,
                    dq_cred=1,
                    dq_geog=1,
                    dq_struc=2,
                    dq_tech=2,
                    dq_time=3,
                    data_id=utils.data_id(rtv['region']),
                )
                for season in config.time['season'].unique()
            ]
            curs.executemany(*ReserveCapacityDerate.bulk_insert_or_ignore_sql(rcd_rows))

    conn.commit()
    conn.close()

    return df_cc



def get_capacity_credits() -> tuple[pd.DataFrame, str, str, str]:

    this_dir = os.path.realpath(os.path.dirname(__file__)) + "/"

    # The most recent or desired ieso reliability outlook
    yyyy, mmm = config.ieso_rel_yyyy_mmm.split("_")
    peak_type: str = config.ieso_rel_peak_type

    rel_outlook_url = f"https://www.ieso.ca/-/media/Files/IESO/Document-Library/planning-forecasts/reliability-outlook/ReliabilityOutlookTables_{yyyy}{mmm}.xlsx"
    note = f"Forecasted capability at {peak_type.lower()} summer peak divided by total installed capacity"
    config.refs.add('cc', f"IESO. ({yyyy}, {mmm}). Reliability Outlook. https://www.ieso.ca/en/Sector-Participants/Planning-and-Forecasting/Reliability-Outlook")

    # Get the reliability outlook forecast peak table and calculate capacity credits
    df_rel = utils.get_data(rel_outlook_url, file_type='xlsx', cache_file_type='csv', sheet_name='Table 4.1', skiprows=4, header=0, nrows=6, index_col=0).astype(float)
    df_rel['cc'] = df_rel[f"Forecast Capability at {yyyy} Summer Peak [{peak_type}] (MW)"] / df_rel['Total Installed Capacity\n(MW)']
    df_rel.index = df_rel.index.str.lower()
    df_cc = pd.DataFrame()

    # Convert from IESO fuel types to CANOE generator codes
    df_types = pd.read_csv(this_dir + 'fuel_types.csv', index_col=0)

    for fuel_type, row in df_types.iterrows():
        for code in row['codes'].split("+"):
            df_cc.loc[code, 'cc'] = df_rel.loc[fuel_type, 'cc']

    # Output to csv for readability
    df_cc.to_csv(this_dir + f"output_data/capacity_credits_{yyyy}_{mmm}.csv")

    return df_cc, note, int(yyyy)
