from canoe_electricity.setup import config
import pandas as pd
import sqlite3
import canoe_electricity.utils as utils
import canoe_electricity.currency_conversion as currency_conversion
from canoe_schema.v4_0.models import CostVariable

df_cost: pd.DataFrame = pd.read_csv('provincial_data/default/cost_tx_dx.csv', index_col=0)
df_cost = currency_conversion.conv_curr(df_cost, 2024, 'USD')
df_cost *= 2.778e+8/100/1E6 # c/kwh to M$/PJ

note = 'EIA/AEO levelised costs converted from USD2024 to CAD2020 using GDP deflator index'
ref = config.refs.add('default_tx_dx_cost','https://www.eia.gov/outlooks/aeo/data/browser/#/?id=8-AEO2025&cases=ref2025&sourcekey=0')

def aggregate(
        region:str,
        period:int,
        tech:str,
        vintage:int,
        curs:sqlite3.Cursor,
        data_id:str,
        dx_tx:str='both'
    ):
    """
    Apply default levelised transmission and distribution costs from AEO
    """

    cost = df_cost[str(utils.data_year(period))]

    match dx_tx:
        case 'dx':
            cost = cost['distribution']
            _note = note + ' - distribution cost'
        case 'tx':
            cost = cost['transmission']
            _note = note + ' - transmission cost'
        case 'both':
            cost = cost['transmission'] + cost['distribution']
            _note = note + ' - transmission and distribution cost'

    row = CostVariable(
        region=region,
        period=period,
        tech=tech,
        vintage=vintage,
        cost=cost,
        units=config.units.loc['cost_variable', 'units'],
        notes=_note,
        data_source=ref.id,
        dq_cred=1,
        dq_geog=3,
        dq_struc=4,
        dq_time=1,
        data_id=data_id,
    )
    curs.executemany(*CostVariable.bulk_insert_or_ignore_sql([row]))
