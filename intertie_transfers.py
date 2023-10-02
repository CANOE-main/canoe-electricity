"""
This script calculates pricing for Canada-US intertie transfers
Written by Ian David Elder for the TEMOA Canada / CANOE model
"""

import requests
import statistics
import sqlite3
import numpy as np
from matplotlib import pyplot
import coders_data

def get_price(province, us_region):

    transfers = requests.get(f"""http://206.12.95.90/international_transfers?year=2020&province={province}&us_region={us_region}""").json()

    prices = np.zeros(8760)

    for h in range(8760):
        price = transfers[h]['price_cad']

        if price is not None:
            prices[h] = price

    return np.mean(prices)

# TODO allow for interprovincial transfers
def get_transfers(region_1, region_2, intertie_type, from_cache=False):

    transfers = list()
    if intertie_type == 'international': transfers = coders_data.get_json(end_point=f"international_transfers?year=2020&province={region_1}&us_region={region_2}", from_cache=from_cache)
    elif intertie_type == 'interprovincial': transfers = coders_data.get_json(end_point=f"interprovincial_transfers?year=2020&province1={region_1}&province2={region_2}", from_cache=from_cache)

    if (len(transfers) < 8760):
        print(f"Insufficient transfer data on {region_1}-{region_2}. Try switching the intertie regions.")
        return None, None
  
    hourly_MWh = np.zeros(8760)

    for h in range(8760):
        MWh = transfers[h]['transfers_MWh']

        if MWh is not None:
            hourly_MWh[h] = MWh

    forward = hourly_MWh.copy()
    forward[forward < 0] = 0

    backward = hourly_MWh.copy()
    backward[backward > 0] = 0
    backward *= -1

    return forward, backward