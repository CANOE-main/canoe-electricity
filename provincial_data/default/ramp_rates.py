from setup import config
import pandas as pd
import sqlite3
import utils

df_rates: pd.Series = pd.read_csv('provincial_data/default/ramp_rates.csv', index_col=0)
note = 'Taken from SI Table 7 - Ramping Constraints'
ref = config.refs.add('default_ramping','Dolter, B., & Rivers, N. (2018). The cost of decarbonizing the Canadian electricity system. Energy Policy, 113, 135–148. https://doi.org/10.1016/j.enpol.2017.10.040')


def aggregate(df_rtv: pd.DataFrame):

    """
    Uses default hourly ramp rate constraints from ramp_rates.csv
    """

    print("Aggregating ramp rate constraints...")

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()

    df_rt = df_rtv.groupby(['region','tech','tech_code']).sum(numeric_only=True).reset_index()

    for _idx, rt in df_rt.iterrows():

        if rt['tech_code'] not in df_rates.index: continue

        data_id = utils.data_id(rt['region'])

        rate = df_rates.loc[rt['tech_code']].iloc[0]

        for ud in ('Up','Down'):

            curs.execute(
                f"""REPLACE INTO
                Ramp{ud}Hourly(region, tech, rate, notes, data_source, dq_cred, data_id)
                VALUES('{rt['region']}', '{rt['tech']}', {rate}, '{note}',
                '{ref.id}', 3, '{data_id}')"""
            )

    conn.commit()
    conn.close()