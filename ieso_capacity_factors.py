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
from matplotlib import pyplot
import solar_capacity_factor

# TODO: replace with something in the translator db
# times of day and season names for 8760 hours
tofd_8760 = 1 + np.mod( np.arange(8760) , 24 )
seas_8760 = 1 + np.int32(np.floor( np.arange(8760) / 24 ))

def get_ieso_production(download=False):

    data = None # do you have to initialize variables in python? feels wrong not to
    if (download):
        url = 'http://reports.ieso.ca/public/GenOutputbyFuelHourly/PUB_GenOutputbyFuelHourly_2020.xml'
        xml_data = requests.get(url).content
        data = json.dumps(xmltodict.parse(xml_data))

        """
        # Uncomment this section to write data to txt file
        file = open('ieso_gen_hourly_2020.txt', 'w')
        file.write(data)
        file.close()
        """
        print('Downloaded hourly production data from IESO')
    else:
        # Pull data from saved json text file
        file = open('ieso_gen_hourly_2020.txt')
        data = json.loads(file.read())
        print('Got hourly IESO production data from local cache')
    if data == None: return None

    # Data was originally in a horribly nested xml format
    # data['Document']['DocBody']['DailyData'][day 1-366]['HourlyData'][hour 1 - 24]['FuelTotal'][where 'Fuel' == e.g. 'NUCLEAR']['EnergyValue']['Output']

    fuels = ['NUCLEAR', 'GAS', 'HYDRO', 'WIND', 'SOLAR', 'BIOFUEL']
    hourly_production = dict()

    for fuel in fuels:
        hourly_production.update({fuel: list()})

        for day in range(365):
            for hour in range(24):
                hourly_data = data['Document']['DocBody']['DailyData'][day]['HourlyData'][hour]['FuelTotal']
                fuel_values = [values for values in hourly_data if values['Fuel'] == fuel]
                fuel_value = float(fuel_values[0]['EnergyValue']['Output'])
                hourly_production[fuel].append(fuel_value)

    return hourly_production



hourly_production = get_ieso_production(download=False)

this_dir = os.path.realpath(os.path.dirname(__file__)) + "/"
database_file = this_dir + "coders_db.sqlite"

conn = sqlite3.connect(database_file)
curs = conn.cursor()

wind_total_cap = sum([gen[0] for gen in curs.execute("SELECT exist_cap FROM ExistingCapacity WHERE regions == 'ON' AND tech LIKE '%WND%'")])
solar_total_cap = sum([gen[0] for gen in curs.execute("SELECT exist_cap FROM ExistingCapacity WHERE regions == 'ON' AND tech LIKE '%SOL%'")])
hydro_total_cap = sum([gen[0] for gen in curs.execute("SELECT exist_cap FROM ExistingCapacity WHERE regions == 'ON' AND tech LIKE '%HYD%'")])

wind_cf = np.array(hourly_production['WIND']) / wind_total_cap / 1000
solar_cf = np.array(hourly_production['SOLAR']) / solar_total_cap / 1000
hydro_cf = np.array(hourly_production['HYDRO']) / hydro_total_cap / 1000

# Run these separately to keep the database tidy
for h in range(8760):
    curs.execute(f"""REPLACE INTO
                 CapacityFactorTech(regions, season_name, time_of_day_name, tech, cf_tech)
                 VALUES('ON', '{seas_8760[h]}', '{tofd_8760[h]}', 'E_WND_ON', {wind_cf[h]})""")
for h in range(8760):
    curs.execute(f"""REPLACE INTO
                 CapacityFactorTech(regions, season_name, time_of_day_name, tech, cf_tech)
                 VALUES('ON', '{seas_8760[h]}', '{tofd_8760[h]}', 'E_SOL_PV', {solar_cf[h]})""")


    
conn.commit()
conn.close()