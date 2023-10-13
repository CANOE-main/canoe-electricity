""" 
Gets hydro run-of-river and daily-dispatch availability factors
by 8760 hours and 365 days, respectively from IESO public data
then dumps into csv files in this folder for ieso_capacity_factors.py to use

This script takes like an hour to run. If you have to run it multiple times it needs a rewrite
"""

import requests
import pandas as pd
import numpy as np
from matplotlib import pyplot as plot
import json
import sqlite3
import os
import tools
from setup import params



data_year = params['default_data_year']

this_dir = os.path.realpath(os.path.dirname(__file__)) + "/"
ieso_data = this_dir + "ieso_data/"


# A bunch of lambda functions to handle data nonsense
get_ieso_data = lambda month: tools.get_file(url(month), skiprows=3, index_col=False)
url = lambda month: f"""http://reports.ieso.ca/public/GenOutputCapabilityMonth/PUB_GenOutputCapabilityMonth_{str(data_year) + NN(month + 1)}.csv"""
NN = lambda dm: str(dm) if dm>9 else '0' + str(dm)
to_date = lambda month, day: f"{data_year}-{NN(month+1)}-{NN(day+1)}"
get_ieso_value = lambda ieso_data, generator, measurement, month, day, hour: ieso_data.loc[(ieso_data['Generator'] == generator) & (ieso_data['Measurement'] == measurement) & (ieso_data['Delivery Date'] == to_date(month, day))]['Hour ' + str(hour+1)].values[0]


ieso_hydro_gens = pd.read_csv(ieso_data + 'hydro_generators.csv', index_col=False, header=None)
ror_gens = []
dly_gens = []


for r in range(len(ieso_hydro_gens)):
    
    gen_type = ieso_hydro_gens.iloc[r,1]

    if gen_type == 'HYDRO_RUN':
        ror_gens.append(ieso_hydro_gens.iloc[r,0])
    elif gen_type == 'HYDRO_DAILY':
        dly_gens.append(ieso_hydro_gens.iloc[r,0])


output_ror = np.zeros(shape=(8760,1))
cap_ror = np.zeros(shape=(8760,1))
output_dly_365 = np.zeros(shape=(365,1))
cap_dly_365 = np.zeros(shape=(365,1))
output_dly_8760 = np.zeros(shape=(8760,1))
cap_dly_8760 = np.zeros(shape=(8760,1))


days_in_months = [31,28,31,30,31,30,31,31,30,31,30,31]


# As inefficient as possible but how often is it really gonna run
H = 0
D = 0
for month in range(12):

    ieso_data = get_ieso_data(month)

    for day in range(days_in_months[month]):
        for hour in range(24):
            
            # 24h vector outputs
            for gen in ror_gens:
                try:
                    output_ror[H] += int(get_ieso_value(ieso_data, gen, 'Output', month, day, hour))
                    cap_ror[H] += int(get_ieso_value(ieso_data, gen, 'Capability', month, day, hour))
                except:
                    print(f"Value error for {gen}, {to_date(month, day)}, hour {hour+1}")

            for gen in dly_gens:
                try:
                    output_dly_8760[H] += int(get_ieso_value(ieso_data, gen, 'Output', month, day, hour))
                    cap_dly_8760[H] += int(get_ieso_value(ieso_data, gen, 'Capability', month, day, hour))
                except:
                    print(f"Value error for {gen}, {to_date(month, day)}, hour {hour+1}")
            
            # sum days output
            for gen in dly_gens:
                try:
                    output_dly_365[D] += int(get_ieso_value(ieso_data, gen, 'Output', month, day, hour))
                    cap_dly_365[D] += int(get_ieso_value(ieso_data, gen, 'Capability', month, day, hour))
                except:
                    print(f"Value error for {gen}, {to_date(month, day)}, hour {hour+1}")

            H += 1

        D += 1
        print(f"Days completed: {D} / 365")

cf_ror = output_ror / cap_ror
cf_dly_365 = output_dly_365 / cap_dly_365
cf_dly_8760 = output_dly_8760 / cap_dly_8760

plot.figure(1)
plot.plot(cf_ror)
plot.figure(2)
plot.plot(cf_dly_365)
plot.figure(3)
plot.plot(cf_dly_8760)

pd.DataFrame(cf_ror).to_csv(ieso_data + 'hydro_ror_cf.csv')
pd.DataFrame(cf_dly_365).to_csv(ieso_data + 'hydro_dly_cf_365.csv')
pd.DataFrame(cf_dly_8760).to_csv(ieso_data + 'hydro_dly_cf_8760.csv')
pd.DataFrame(output_ror).to_csv(ieso_data + 'hydro_ror_production.csv')
pd.DataFrame(output_dly_365).to_csv(ieso_data + 'hydro_dly_production_365.csv')
pd.DataFrame(output_dly_8760).to_csv(ieso_data + 'hydro_dly_production_8760.csv')

plot.show()