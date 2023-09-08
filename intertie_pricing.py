"""
This script calculates pricing for Canada-US intertie transfers
Written by Ian David Elder for the TEMOA Canada / CANOE model
"""

import requests
import statistics
import sqlite3
from matplotlib import pyplot

def get_price(province, us_region):

    transfers = requests.get(f"""http://206.12.95.90/international_transfers?year=2020&province={province}&us_region={us_region}""").json()

    prices = list()

    for transfer in transfers:
        price = transfer['price_cad']

        if price is not None:
            prices.append(price)

    return statistics.mean(prices)