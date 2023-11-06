"""
Gets aggregate 2020 electricity production by fuel type from IESO data
to calculate 8760 capacity factors
Written by Ian David Elder for the CANOE model
"""

import os
import sqlite3
import numpy as np
import pandas as pd
from setup import config
from matplotlib import pyplot as pp
import utils
import coders_api

params = config.params
translator = config.translator


data_year = params['default_data_year']

this_dir = os.path.realpath(os.path.dirname(__file__)) + "/"
translation_file = this_dir + "CODERS_CANOE_translation.sqlite"
coders_db = this_dir + "coders_db.sqlite"

ieso_data = this_dir + "ieso_data/"
cache = ieso_data +  f"ieso_gen_hourly_{data_year}.txt"

show_plots=False

tech_like = {
        'WIND_ONSHORE':f"%WND%", # to get on and offshore
        'SOLAR_PV':f"%{translator['generator_types']['SOLAR_PV']['CANOE_tech']}%",
        'HYDRO_RUN':f"%{translator['generator_types']['HYDRO_RUN']['CANOE_tech']}%",
        'HYDRO_DAILY':f"%{translator['generator_types']['HYDRO_DAILY']['CANOE_tech']}%",
        'HYDRO':'%HYD%'
        }


def get_ieso_production():

    monthly = utils.get_data(f"http://reports.ieso.ca/public/GenOutputbyFuelMonthly/PUB_GenOutputbyFuelMonthly_{data_year}.xml")
    hourly = utils.get_data(f"http://reports.ieso.ca/public/GenOutputbyFuelHourly/PUB_GenOutputbyFuelHourly_{data_year}.xml")

    fuels = ['NUCLEAR', 'GAS', 'HYDRO', 'WIND', 'SOLAR', 'BIOFUEL']
    hourly_production = dict()
    annual_production = dict()

    # Monthly
    for fuel in fuels:
        annual_production[fuel] = 0

        for month in range(12):
            # Data was originally in a horribly nested xml format like:
            # data['Document']['DocBody']['MonthData'][month 0-11]['FuelTotal'][any vals where val['Fuel'] == fuel]['EnergyGW'] = GWh per month
            month_data = monthly['Document']['DocBody']['MonthData'][month]['FuelTotal']
            fuel_values = [values for values in month_data if values['Fuel'] == fuel]
            gwh_per_month = float(fuel_values[0]['EnergyGW'])
            annual_production[fuel] += gwh_per_month * 1000

    # Hourly
    for fuel in fuels:
        hourly_production[fuel] = np.zeros(8760)

        for day in range(365):
            for hour in range(24):

                # Data was originally in a horribly nested xml format like:
                # data['Document']['DocBody']['DailyData'][day 1-366]['HourlyData'][hour 1 - 24]['FuelTotal'][any vals where val['Fuel'] == fuel]['EnergyValue']['Output'] = MWh per hour
                hour_data = hourly['Document']['DocBody']['DailyData'][day]['HourlyData'][hour]['FuelTotal']
                fuel_values = [values for values in hour_data if values['Fuel'] == fuel]
                mwh_per_hour = float(fuel_values[0]['EnergyValue']['Output'])
                hourly_production[fuel][24*day + hour] = mwh_per_hour

        # Hourly production only includes <20MW generators so adjust for monthly data which includes them
        hourly_production[fuel] *= annual_production[fuel] / sum(hourly_production[fuel])

    return hourly_production



def get_capacity_factors():

    hourly_production = get_ieso_production()

    wind_total_cap = get_past_capacity_mw('WIND_ONSHORE')
    solar_total_cap = get_past_capacity_mw('SOLAR')
    hydro_total_cap = get_past_capacity_mw('HYDRO')

    wind_cf = np.array(hourly_production['WIND']) / wind_total_cap # MWh/GW.h to W/W
    solar_cf = np.array(hourly_production['SOLAR']) / solar_total_cap
    hydro_cf = np.array(hourly_production['HYDRO']) / hydro_total_cap
    hydro_ror_cf = np.array(pd.read_csv(ieso_data + 'hydro_ror_cf.csv',index_col=0,header=0)['0'])
    hydro_dly_cf = np.array(pd.read_csv(ieso_data + 'hydro_dly_cf_365.csv',index_col=0,header=0)['0']) * 3600 * 24 / 10**6 # GWd to PJ

    return dict({
        'WIND_ONSHORE':wind_cf,
        'SOLAR_PV':solar_cf,
        'HYDRO_RUN':hydro_ror_cf,
        'HYDRO_DAILY':hydro_dly_cf,
        'HYDRO':hydro_cf
        })



# Get data year capacity of a VRE where unit capacities >20MW
def get_past_capacity_mw(vre_type):

    existing_gens, date_accessed = coders_api.get_json('generators', from_cache=True)

    total_cap = 0
    for gen in existing_gens:

        if vre_type not in gen['gen_type'].upper(): continue
        if "ONTARIO" not in gen['operating_region'].upper(): continue
        if gen['install_capacity_in_mw'] < 20: continue # IESO ignores <20MW in hourly data -> must match for CFs

        vint = gen['previous_renewal_year']
        if vint is None: vint = gen['start_year']
        if vint > int(data_year): continue
        
        total_cap += gen['install_capacity_in_mw']

    return total_cap



# Get total existing capacity of a VRE in the database
def get_database_capacity_gw(vre_type):
    
    conn = sqlite3.connect(coders_db)
    curs = conn.cursor()

    cap = sum([gen[0] for gen in curs.execute(f"SELECT exist_cap FROM ExistingCapacity WHERE regions == 'ON' AND tech LIKE '{tech_like[vre_type]}'").fetchall()])

    conn.close()

    return cap



def write_to_coders_db():

    cfs = get_capacity_factors()

    mean_cfs = dict()
    for vre in ['WIND_ONSHORE','SOLAR_PV','HYDRO_RUN']:
        mean_cfs[vre] = np.mean(cfs[vre])

    print('IESO capacity factors:')
    print(pd.DataFrame(columns=['mean cf'], index=mean_cfs.keys(), data=mean_cfs.values()))

    # Hydro daily storage uses a daily energy allotment (Min/MaxSeasonalActivity)
    hydro_dly_total_cap = get_database_capacity_gw('HYDRO_DAILY')
    hydro_dly_seas_act = cfs['HYDRO_DAILY'] * hydro_dly_total_cap * 3600/1E6 # GWh/day to PJ

    conn = sqlite3.connect(coders_db)
    curs = conn.cursor()

    reference = params['ieso_reference'].replace('<year>',data_year)
    cf_note = params['capacity_factor_note'].replace('<year',data_year)

    curs.execute(f"""REPLACE INTO
                 'references'('reference')
                 VALUES('{reference}')""")

    for vre in ['HYDRO_RUN', 'SOLAR_PV', 'WIND_ONSHORE']:

        # Get all variants of this vre tech
        techs = [tech[0] for tech in curs.execute(f"SELECT tech FROM technologies WHERE tech like '{tech_like[vre]}'").fetchall()]

        for tech in techs:
            # Do in this order to keep tech rows together in the database
            for h in range(8760):
                curs.execute(f"""REPLACE INTO
                            CapacityFactorTech(regions, season_name, time_of_day_name, tech, cf_tech, cf_tech_notes, reference)
                            VALUES('ON', '{config.seas_8760[h]}', '{config.tofd_8760[h]}', '{tech}', {cfs[vre][h]}, '{cf_note}', '{reference}')""")


    dly_note = params['hydro_daily_note'].replace('<year>',data_year)

    hyd_dly_variants = [tech[0] for tech in curs.execute(f"SELECT tech FROM technologies WHERE tech like '{tech_like['HYDRO_DAILY']}'").fetchall()]

    for tech in hyd_dly_variants:
        for period in config.model_periods:
            for d in range(365):
                h = d*24
                curs.execute(f"""REPLACE INTO
                            MinSeasonalActivity(regions, periods, season_name, tech, minact, minact_units, minact_notes, reference)
                            VALUES('ON', {period}, '{config.seas_8760[h]}', '{tech}', {hydro_dly_seas_act[d]}, 'PJ', '{dly_note}', '{reference}')""")
                curs.execute(f"""REPLACE INTO
                            MaxSeasonalActivity(regions, periods, season_name, tech, maxact, maxact_units, maxact_notes, reference)
                            VALUES('ON', {period}, '{config.seas_8760[h]}', '{tech}', {hydro_dly_seas_act[d]}, 'PJ', '{dly_note}', '{reference}')""")

    conn.commit()
    conn.close()