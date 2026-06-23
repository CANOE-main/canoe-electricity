from setup import config
import pandas as pd
import sqlite3
import utils
import currency_conversion

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

    curs.execute(
        f"""REPLACE INTO
        CostVariable(region, period, tech, vintage, cost, units, notes,
        data_source, dq_cred, dq_geog, dq_struc, dq_time, data_id)
        VALUES('{region}', {period}, '{tech}', {vintage}, {cost}, '{config.units.loc['cost_variable','units']}',
        '{_note}', '{ref.id}', 1, 3, 4, 1, '{data_id}')"""
    )