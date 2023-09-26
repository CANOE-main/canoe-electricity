"""
This script calculates pricing for Canada-US intertie transfers
Written by Ian David Elder for the TEMOA Canada / CANOE model
"""

import requests
import statistics
import sqlite3
import numpy as np
from matplotlib import pyplot

def get_price(province, us_region):

    transfers = requests.get(f"""http://206.12.95.90/international_transfers?year=2020&province={province}&us_region={us_region}""").json()

    prices = np.zeros(8760)

    for h in range(8760):
        price = transfers[h]['price_cad']

        if price is not None:
            prices[h] = price

    return np.mean(prices)

def get_transfers(province, us_region):

    transfers = requests.get(f"""http://206.12.95.90/international_transfers?year=2020&province={province}&us_region={us_region}""").json()

    hourly_MWh = np.zeros(8760)

    for h in range(8760):
        MWh = transfers[h]['transfers_MWh']

        if MWh is not None:
            hourly_MWh[h] = MWh

    forward = hourly_MWh
    forward[forward < 0] = 0

    backward = hourly_MWh
    backward[backward > 0] = 0

    return forward, backward

get_price(1, 2)