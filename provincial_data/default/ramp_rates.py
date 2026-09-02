from canoe_electricity.setup import config
import pandas as pd
import sqlite3
import canoe_electricity.utils as utils
from canoe_schema.v4_0.models import RampUpHourly, RampDownHourly

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

    up_rows = []
    down_rows = []

    for _idx, rt in df_rt.iterrows():

        if rt['tech_code'] not in df_rates.index: continue

        data_id = utils.data_id(rt['region'])
        rate = df_rates.loc[rt['tech_code']].iloc[0]

        kwargs = dict(region=rt['region'], tech=rt['tech'], rate=rate, notes=note, data_source=ref.id, dq_cred=3, data_id=data_id)
        up_rows.append(RampUpHourly(**kwargs))
        down_rows.append(RampDownHourly(**kwargs))

    if up_rows:
        curs.executemany(*RampUpHourly.bulk_insert_or_ignore_sql(up_rows, include_nulls=True))
    if down_rows:
        curs.executemany(*RampDownHourly.bulk_insert_or_ignore_sql(down_rows, include_nulls=True))

    conn.commit()
    conn.close()
