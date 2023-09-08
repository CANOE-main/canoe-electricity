"""
This script builds an 8760 capacity factor vector for existing solar generators in Canada
"""

import os
import sqlite3
from solar_power_model import solar_capacity_factor
import numpy as np
from matplotlib import pyplot
from geopy.distance import geodesic
import requests
import cwec_stations

zero_thresh = 10^-5 # Threshold to zero very low capacity factors

script_path = os.path.realpath(os.path.dirname(__file__)) + "/"
cwec_db = script_path + "CWEC/cwec.sqlite"

conn = sqlite3.connect(cwec_db)
curs = conn.cursor()

def get_exs_cf(generators, region, translator):

    solar_generators = list()
    for generator in generators:
        this_region = translator['regions'][generator['copper_balancing_area'].upper()]['CANOE_region']
        if 'SOLAR' in generator['gen_type'].upper() and this_region == region:
            solar_generators.append(generator)

    hourly_mw = np.zeros(8760)
    total_cap = 0
    avg_mw = 0

    for generator in solar_generators:
        lat = generator['latitude']
        long = generator['longitude']
        cap = generator['install_capacity_in_mw']
        cf = generator['capacity_factor_in_%']

        station_id = cwec_stations.get_nearest(lat, long)

        DNI = np.array([el[0] for el in curs.execute(f"""SELECT
                        direct_normal_irradiance_kjm2
                        FROM '{station_id}'""").fetchall()])
        DHI = np.array([el[0] for el in curs.execute(f"""SELECT
                        diffuse_horizontal_irradiance_kjm2
                        from '{station_id}'""").fetchall()])

        total_cap += cap
        avg_mw += cap * cf
        hourly_mw += cap*solar_capacity_factor(DNI, DHI, long, lat)

    if total_cap == 0: return None

    exs_cf = hourly_mw / total_cap
    exs_cf[exs_cf < zero_thresh] = 0

    return exs_cf