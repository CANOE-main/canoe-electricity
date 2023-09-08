import requests
import pandas as pd
import json
import math
import numpy as np
import os
import sqlite3
import urllib.request as urlrq
import certifi
import xmltodict
from matplotlib import pyplot
import solar_capacity_factor

""" this_dir = os.path.realpath(os.path.dirname(__file__)) + "/"
turbine_xlsx = this_dir + 'Wind_Turbine_Database_FGP.xlsx'

url = 'http://reports.ieso.ca/public/GenOutputbyFuelHourly/PUB_GenOutputbyFuelHourly_2020.xml'

http = requests.get(url).content

data = json.dumps(xmltodict.parse(http))

print(data)

file = open('fuelhourly.txt', 'w')
file.write(data)
file.close() """

file = open('fuelhourly.txt')
data = json.loads(file.read())

# data['Document']['DocBody']['DailyData'][day 1-366]['HourlyData'][hour 1 - 24]['FuelTotal'][where 'Fuel' == e.g. 'NUCLEAR']['EnergyValue']['Output']

fuels = ['NUCLEAR', 'GAS', 'HYDRO', 'WIND', 'SOLAR', 'BIOFUEL']

fuels_hourly = dict()

for fuel in fuels:
    fuels_hourly.update({fuel: list()})

    for day in range(365):
        for hour in range(24):
            hourly_data = data['Document']['DocBody']['DailyData'][day]['HourlyData'][hour]['FuelTotal']
            fuel_values = [values for values in hourly_data if values['Fuel'] == fuel]
            fuel_value = float(fuel_values[0]['EnergyValue']['Output'])
            fuels_hourly[fuel].append(fuel_value)

    print((day)*24 + 1+hour)
    
exs_cf = solar_capacity_factor.get_exs_cf(None, None)

pyplot.plot(exs_cf,'r-')
pyplot.plot((np.array(fuels_hourly['SOLAR']) / 663),'b-')
pyplot.show()

print(sum(exs_cf), sum(np.array(fuels_hourly['SOLAR']) / 663))