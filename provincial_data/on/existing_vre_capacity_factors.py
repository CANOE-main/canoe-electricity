"""
Gets aggregate 2020 electricity production by fuel type from IESO data
to calculate 8760 capacity factors
Written by Ian David Elder for the CANOE model
"""

import os
import numpy as np
import pandas as pd
from setup import config
from matplotlib import pyplot as pp
import utils
import sqlite3
import coders_api

weather_year = config.params['weather_year']
df_existing: pd.DataFrame = None


def aggregate_cfs(df_rtv: pd.DataFrame):
    
    cfs, note, reference = get_capacity_factors()

    # CapacityFactorTech has no vintage index
    df_rt = df_rtv.groupby(['region','tech','tech_code']).sum(numeric_only=True).reset_index()

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()

    for _idx, rt in df_rt.iterrows():

        # Summing curtailed generation to get net load for capacity credit calculations
        config.exs_vre_gen[rt['region']] += cfs[rt['tech_code']].astype(float) * rt['capacity']

        for h, time in config.time.iterrows():

            if time['time_of_day'] == config.time.iloc[0]['time_of_day']:
                _note = note
                _ref = reference
            else: _note=_ref=''

            curs.execute(f"""REPLACE INTO
                        CapacityFactorTech(regions, season_name, time_of_day_name, tech, cf_tech, cf_tech_notes,
                        reference, data_year, dq_rel, dq_comp, dq_time, dq_geog, dq_tech)
                        VALUES('{rt['region']}', '{time['season']}', '{time['time_of_day']}', '{rt['tech']}', {cfs[rt['tech_code']][h]}, '{_note}',
                        '{_ref}', {weather_year}, 1, 1, 1, 1, 1)""")
            
    conn.commit()
    conn.close()



def initialise():

    global df_existing

    # Initialise existing generators data
    if df_existing is None: _json, df_existing, date_accessed = coders_api.get_data('generators')
    else: return

    config.references['generators'] = config.params['coders']['reference'].replace("<date>", date_accessed).replace("<table>","generators")
    df_existing = df_existing.loc[df_existing['province'].str.lower() == 'on']



def get_capacity_factors() -> tuple[dict[str, np.ndarray], str, str]:

    initialise()

    # Get hourly generation for the year
    hourly_wind, hourly_solar = get_historical_hourly()

    # Get preexisting capacities
    cf_ann_wind = get_average_annual_cf('wind_onshore')
    cf_ann_solar = get_average_annual_cf('solar')

    # Calculate capacity factors
    cf_wind = np.clip(hourly_wind / np.mean(hourly_wind) * cf_ann_wind, 0, 1)
    cf_solar = np.clip(hourly_solar / np.mean(hourly_solar) * cf_ann_solar, 0, 1)

    # Save as csv for readability
    this_dir = os.path.realpath(os.path.dirname(__file__)) + "/"
    pd.DataFrame(cf_wind).to_csv(this_dir + f"output_data/cf_wind_{weather_year}.csv")
    pd.DataFrame(cf_solar).to_csv(this_dir + f"output_data/cf_solar_{weather_year}.csv")

    # Plotting if set to show
    if config.params['show_plots']:
        figure, axis = pp.subplots(2, 1, constrained_layout=True)
        figure.suptitle(f"Ontario {weather_year} historical capacity factors")

        axis[0].plot(cf_wind)
        axis[0].set_title('Wind')
        axis[0].set_ylim(0,1)
        axis[1].plot(cf_solar)
        axis[1].set_title('Solar')
        axis[1].set_ylim(0,1)

    # Referencing
    note = f"{weather_year} hourly generation by fuel for generators >20MW (IESO) divided by preexisting capacities >20MW (CODERS)"
    reference = f"{config.params['ieso_reference'].replace('<year>', str(weather_year))}GenOutputbyFuelHourly/; {config.references['generators']}"

    return {'wind_onshore': cf_wind, 'wind_offshore': cf_wind, 'solar': cf_solar}, note, reference



def get_historical_hourly() -> tuple[np.ndarray, np.ndarray]:

    # Hourly generation by fuel in MWh/h
    hourly_dict = utils.get_data(f"http://reports.ieso.ca/public/GenOutputbyFuelHourly/PUB_GenOutputbyFuelHourly_{weather_year}.xml")

    fuels = ['WIND', 'SOLAR']
    hourly: dict[str, list] = {}

    # Convert horrible xml format to a numpy vector for the year's generation by fuel
    for fuel in fuels:
        hourly[fuel] = np.zeros(8760)

        for day in range(365):
            for hour in range(24):
                # Data is in a horribly nested xml format like:
                # data['Document']['DocBody']['DailyData'][day 1-366]['HourlyData'][hour 1 - 24]['FuelTotal'][any vals where val['Fuel'] == fuel]['EnergyValue']['Output'] = MWh per hour
                hour_data = hourly_dict['Document']['DocBody']['DailyData'][day]['HourlyData'][hour]['FuelTotal']
                fuel_values = [values for values in hour_data if values['Fuel'] == fuel]
                mwh_per_hour = float(fuel_values[0]['EnergyValue']['Output'])
                hourly[fuel][24*day + hour] = mwh_per_hour

    return hourly['WIND'], hourly['SOLAR']



def get_average_annual_cf(gen_code: str) -> int:

    # CODERs equivalent names for this generator type
    coders_equivs = config.gen_techs.loc[gen_code, 'coders_existing'].split('+')
    df_exs = df_existing.loc[(df_existing['gen_type'].str.lower().isin(coders_equivs))]

    # IESO data only includes generators > 20MW
    df_exs = df_exs.loc[(df_exs['start_year'].astype(int) <= weather_year) & (df_exs['unit_installed_capacity'].astype(float) >= 20)]

    # Get average annual capacity factor of this type of generator
    weighted_cf = df_exs['capacity_factor'].astype(float) * df_exs['unit_installed_capacity'].astype(float)
    cf_ann = weighted_cf.sum() / df_exs['unit_installed_capacity'].astype(float).sum()

    return cf_ann