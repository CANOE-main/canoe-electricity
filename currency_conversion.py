"""
Applies currency conversions to all cost tables
Written by Ian David Elder for the CANOE model
"""

import sqlite3
import pandas as pd
from setup import config


# Exchange rate and inflation tables
exchange = pd.read_csv(config.input_files + 'currency_exchange.csv', index_col=0)
inflation = pd.read_csv(config.input_files + 'cad_inflation.csv', index_col=0)

# Currency and currency year for final data, converting to this
base_curr = config.params['final_currency']
base_year = config.params['final_currency_year']

# Multiplier for final currency (to normalise if not using CAD2020)
base_fact = exchange.loc[base_year, base_curr] * inflation.loc[base_year, config.params['inflation_index']]


def conv_curr(orig_cost, orig_year: int, orig_curr: str):
    """
    Converts a cost from its original currency and year to the base currency and year

    params:
    - orig_cost: the original cost as given in the data source
    - orig_year: the original currency year in the data source
    - orig_curr: the orignal currency in the data source (USD, EUR, GDP, AUD)

    For example, if the original cost from data is $2500 USD (2010),
    cost = conv_curr(2500, 2010, 'USD')
    """
    
    return orig_cost * exchange.loc[orig_year, orig_curr] * inflation.loc[orig_year, config.params['inflation_index']] / base_fact


def convert_currencies():

    # Names of tables and relevant data columns
    cost_tables = {'CostInvest': 'cost_invest', 'CostFixed': 'cost_fixed', 'CostVariable': 'cost_variable'}

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()

    # For each cost table...
    for table, header in cost_tables.items():

        # Get all data
        df = pd.read_sql_query(f"SELECT * FROM {table}", conn)

        # Convert data cost to final currency cost
        df[header] = [
            conv_curr(cost, year, curr)
            for cost, year, curr in df[[f"data_{header}",'data_cost_year','data_curr']].values
        ]

        # Add units of final currency
        df[f"{header}_units"] += f" {base_year} {base_curr}"

        # Clear the table
        curs.execute(f"DELETE FROM {table}")

        # Refill it with converted currency
        df.to_sql(table, conn, if_exists='append', index=False)


    conn.commit()
    conn.close()

    print(f"Currencies converted to {base_year} {base_curr}.\n")



if __name__ == "__main__":

    convert_currencies()