from setup import config
import pandas as pd
import sqlite3
import utils

df_rates: pd.Series = pd.read_csv('provincial_data/default/ramp_rates.csv', index_col=0)
note = 'Taken from SI Table 7 - Ramping Constraints'
ref = config.refs.add('default_ramping','Dolter, B., & Rivers, N. (2018). The cost of decarbonizing the Canadian electricity system. Energy Policy, 113, 135–148. https://doi.org/10.1016/j.enpol.2017.10.040')


def aggregate(region:str, tech:str, tech_code:str, curs:sqlite3.Cursor):

    """
    Uses default hourly ramp rate constraints from ramp_rates.csv
    """

    if tech_code not in df_rates.index: return

    data_id = utils.data_id(region)

    rate = df_rates.loc[tech_code].iloc[0]

    for ud in ('Up','Down'):

        curs.execute(
            f"""REPLACE INTO
            Ramp{ud}Hourly(region, tech, rate, notes, data_source, dq_cred, data_id)
            VALUES('{region}', '{tech}', {rate}, '{note}',
            '{ref.id}', 3, '{data_id}')"""
        )