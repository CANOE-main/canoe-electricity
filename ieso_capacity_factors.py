"""
Gets aggregate 2020 electricity production by fuel type from IESO data
to calculate 8760 capacity factors
"""

import os
import sqlite3
import requests
import json
import numpy as np
import xmltodict
import pandas as pd
from matplotlib import pyplot

# TODO: replace with something in the translator db
# times of day and season names for 8760 hours
tofd_8760 = 1 + np.mod( np.arange(8760) , 24 )
seas_8760 = 1 + np.int32(np.floor( np.arange(8760) / 24 ))

HH = lambda h: 'H' + ('0' if h<10 else '') + str(h)
DDD = lambda d: 'D' + ('0' if d<100 else '') + ('0' if d<10 else '') + str(d)

def get_ieso_production(download=False, update_cache=False):

    data = None # do you have to initialize variables in python? feels wrong not to
    if (download):

        url = 'http://reports.ieso.ca/public/GenOutputbyFuelHourly/PUB_GenOutputbyFuelHourly_2020.xml'
        xml_data = requests.get(url).content
        data = json.dumps(xmltodict.parse(xml_data))

        if update_cache:
            # Overwrite local data cache with newly downloaded file
            file = open('ieso_gen_hourly_2020.txt', 'w')
            file.write(data)
            file.close()

        print('Downloaded hourly production data from IESO')

    else:

        # Pull data from saved json text file
        file = open('ieso_gen_hourly_2020.txt')
        data = json.loads(file.read())

        print('Got hourly IESO production data from local cache')

    if data == None: return None



    fuels = ['NUCLEAR', 'GAS', 'HYDRO', 'WIND', 'SOLAR', 'BIOFUEL']
    hourly_production = dict()

    for fuel in fuels:
        hourly_production.update({fuel: list()})

        for day in range(365):
            for hour in range(24):

                # Data was originally in a horribly nested xml format like:
                # data['Document']['DocBody']['DailyData'][day 1-366]['HourlyData'][hour 1 - 24]['FuelTotal'][any vals where val['Fuel'] == fuel]['EnergyValue']['Output']
                hour_data = data['Document']['DocBody']['DailyData'][day]['HourlyData'][hour]['FuelTotal']
                fuel_values = [values for values in hour_data if values['Fuel'] == fuel]
                fuel_value = float(fuel_values[0]['EnergyValue']['Output'])
                hourly_production[fuel].append(fuel_value)

    return hourly_production



hourly_production = get_ieso_production(download=False)

this_dir = os.path.realpath(os.path.dirname(__file__)) + "/"
coders_db = this_dir + "coders_db.sqlite"

conn = sqlite3.connect(coders_db)
curs = conn.cursor()

wind_total_cap = sum([gen[0] for gen in curs.execute("SELECT exist_cap FROM ExistingCapacity WHERE regions == 'ON' AND tech LIKE '%WND%'")])
solar_total_cap = sum([gen[0] for gen in curs.execute("SELECT exist_cap FROM ExistingCapacity WHERE regions == 'ON' AND tech LIKE '%SOL%'")])
hydro_dly_total_cap = sum([gen[0] for gen in curs.execute("SELECT exist_cap FROM ExistingCapacity WHERE regions == 'ON' AND tech LIKE '%HYD_DLY%'")])

wind_cf = np.array(hourly_production['WIND']) / wind_total_cap / 1000 # MWh/GW.h to PJ/PJ
solar_cf = np.array(hourly_production['SOLAR']) / solar_total_cap / 1000
hydro_ror_cf = np.array(pd.read_csv('ieso_hydro_ror_cf.csv')['0'])
hydro_dly_cf = np.array(pd.read_csv('ieso_hydro_dly_cf.csv')['0']) * 3600 * 24 / 10**6 # GWd to PJ

hydro_dly_seas_act = hydro_dly_cf * hydro_dly_total_cap

# Run these separately to keep the database in order
for h in range(8760):
    curs.execute(f"""REPLACE INTO
                 CapacityFactorTech(regions, season_name, time_of_day_name, tech, cf_tech)
                 VALUES('ON', '{DDD(seas_8760[h])}', '{HH(tofd_8760[h])}', 'E_WND_ON', {wind_cf[h]})""")
for h in range(8760):
    curs.execute(f"""REPLACE INTO
                 CapacityFactorTech(regions, season_name, time_of_day_name, tech, cf_tech)
                 VALUES('ON', '{DDD(seas_8760[h])}', '{HH(tofd_8760[h])}', 'E_SOL_PV', {solar_cf[h]})""")
for h in range(8760):
    curs.execute(f"""REPLACE INTO
                 CapacityFactorTech(regions, season_name, time_of_day_name, tech, cf_tech)
                 VALUES('ON', '{DDD(seas_8760[h])}', '{HH(tofd_8760[h])}', 'E_HYD_ROR', {hydro_ror_cf[h]})""")
    
for period in range(2020,2055,5):
    for d in range(365):
        curs.execute(f"""REPLACE INTO
                    MinSeasonalActivity(regions, periods, season_name, tech, minact, minact_units)
                    VALUES('ON', {period}, '{DDD(seas_8760[d])}', 'E_HYD_DLY', {hydro_dly_seas_act[d]}, 'PJ')""")
        curs.execute(f"""REPLACE INTO
                    MaxSeasonalActivity(regions, periods, season_name, tech, maxact, maxact_units)
                    VALUES('ON', {period}, '{DDD(seas_8760[d])}', 'E_HYD_DLY', {hydro_dly_seas_act[d]}, 'PJ')""")


    
conn.commit()
conn.close()