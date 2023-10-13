"""
Gets aggregate 2020 electricity production by fuel type from IESO data
to calculate 8760 capacity factors
Written by Ian David Elder for the CANOE model
"""

import os
import sqlite3
import requests
import json
import numpy as np
import xmltodict
import pandas as pd
from pathlib import Path
from matplotlib import pyplot
from setup import config
import tools

params = config.params
translator = config.translator


data_year = params['default_data_year']

this_dir = os.path.realpath(os.path.dirname(__file__)) + "/"
translation_file = this_dir + "CODERS_CANOE_translation.sqlite"
coders_db = this_dir + "coders_db.sqlite"

ieso_data = this_dir + "ieso_data/"
cache = ieso_data +  f"ieso_gen_hourly_{data_year}.txt"



def get_ieso_production():

    data = tools.get_file(f"http://reports.ieso.ca/public/GenOutputbyFuelHourly/PUB_GenOutputbyFuelHourly_{data_year}.xml")

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



def get_capacity_factors():

    hourly_production = get_ieso_production()

    wind_total_cap = get_total_capacity('WIND_ONSHORE')
    solar_total_cap = get_total_capacity('SOLAR_PV')
    hydro_total_cap = get_total_capacity('HYDRO')

    wind_cf = np.array(hourly_production['WIND']) / wind_total_cap / 1000 # MWh/GW.h to PJ/PJ
    solar_cf = np.array(hourly_production['SOLAR']) / solar_total_cap / 1000
    hydro_cf = np.array(hourly_production['HYDRO']) / hydro_total_cap / 1000
    hydro_ror_cf = np.array(pd.read_csv(ieso_data + 'hydro_ror_cf.csv',index_col=0,header=0)['0'])
    hydro_dly_cf = np.array(pd.read_csv(ieso_data + 'hydro_dly_cf_365.csv',index_col=0,header=0)['0']) * 3600 * 24 / 10**6 # GWd to PJ

    return dict({
        'WIND_ONSHORE':wind_cf,
        'SOLAR_PV':solar_cf,
        'HYDRO_ROR':hydro_ror_cf,
        'HYDRO_DLY':hydro_dly_cf,
        'HYDRO':hydro_cf
        })



def get_total_capacity(vre_type):
    
    conn = sqlite3.connect(coders_db)
    curs = conn.cursor()

    tech_like = dict({
        'WIND_ONSHORE':'%WND_ON%',
        'SOLAR_PV':'%SOL_PV%',
        'HYDRO_ROR':'%HYD_ROR%',
        'HYDRO_DLY':'%HYD_DLY%',
        'HYDRO':'%HYD%'
        })[vre_type]

    cap = sum([gen[0] for gen in curs.execute(f"SELECT exist_cap FROM ExistingCapacity WHERE regions == 'ON' AND tech LIKE '{tech_like}'")])

    conn.close()

    return cap



def write_to_coders_db(download=False, update_cache=False):

    cfs = get_capacity_factors(download=download, update_cache=update_cache)

    hydro_dly_total_cap = get_total_capacity('HYDRO_DLY')
    hydro_dly_seas_act = cfs['HYDRO_DLY'] * hydro_dly_total_cap

    conn = sqlite3.connect(coders_db)
    curs = conn.cursor()

    # Run these separately to keep the database in order
    for h in range(8760):
        curs.execute(f"""REPLACE INTO
                    CapacityFactorTech(regions, season_name, time_of_day_name, tech, cf_tech)
                    VALUES('ON', '{config.seas_8760[h]}', '{config.tofd_8760[h]}', 'E_WND_ON', {cfs['WIND'][h]})""")
    for h in range(8760):
        curs.execute(f"""REPLACE INTO
                    CapacityFactorTech(regions, season_name, time_of_day_name, tech, cf_tech)
                    VALUES('ON', '{config.seas_8760[h]}', '{config.tofd_8760[h]}', 'E_SOL_PV', {cfs['SOLAR'][h]})""")
    for h in range(8760):
        curs.execute(f"""REPLACE INTO
                    CapacityFactorTech(regions, season_name, time_of_day_name, tech, cf_tech)
                    VALUES('ON', '{config.seas_8760[h]}', '{config.tofd_8760[h]}', 'E_HYD_ROR', {cfs['HYDRO_ROR'][h]})""")
        
    for period in range(2020,2055,5):
        for d in range(365):
            curs.execute(f"""REPLACE INTO
                        MinSeasonalActivity(regions, periods, season_name, tech, minact, minact_units)
                        VALUES('ON', {period}, '{config.seas_8760[d]}', 'E_HYD_DLY', {hydro_dly_seas_act[d]}, 'PJ')""")
            curs.execute(f"""REPLACE INTO
                        MaxSeasonalActivity(regions, periods, season_name, tech, maxact, maxact_units)
                        VALUES('ON', {period}, '{config.seas_8760[d]}', 'E_HYD_DLY', {hydro_dly_seas_act[d]}, 'PJ')""")

    conn.commit()
    conn.close()