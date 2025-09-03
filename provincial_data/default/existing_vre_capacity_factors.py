import utils
import coders_api
from setup import config
import pandas as pd
import os
import time
import numpy as np
import sqlite3
from datetime import datetime
from matplotlib import pyplot as pp


note = (
    "Hourly capacity factors from Renewables Ninja API, for location of each facility in "
    "CODERS generators table. Average of all existing facilities weighted by facility capacity."
)


def aggregate_cfs(df_rtv: pd.DataFrame):

    print("Aggregating hourly capacity factors for existing VREs...")

    ref = f"{config.params['renewables_ninja']['reference']}{config.refs.get('generators').citation}"
    ref = config.refs.add('rninja-coders', ref)

    cfs_solar = aggregate_vre(df_rtv.loc[df_rtv['tech_code'] == 'solar'].copy(), 'cf_solar')
    cfs_wind_on = aggregate_vre(df_rtv.loc[df_rtv['tech_code'] == 'wind_onshore'].copy(), 'cf_wind_on')
    cfs_wind_off = aggregate_vre(df_rtv.loc[df_rtv['tech_code'] == 'wind_offshore'].copy(), 'cf_wind_off')

    # Plotting if set to show
    if config.params['show_plots']:
        for region in df_rtv['region'].unique():
            
            figure, axis = pp.subplots(3, 1, constrained_layout=True)
            figure.suptitle(
                f"{region} {config.params['weather_year']} synthesized hourly capacity factors\n"
                "for existing VRE (real data in red, if available)"
            )

            # Compare to real data for Ontario
            if region == 'ON':
                df = pd.read_csv('provincial_data/on/output_data/cf_solar_2018.csv', index_col=0)
                axis[0].plot(range(8760), df, 'r')
                df = pd.read_csv('provincial_data/on/output_data/cf_wind_2018.csv', index_col=0)
                axis[1].plot(range(8760), df, 'r')

            axis[0].plot(range(8760), cfs_solar[region])
            axis[0].set_title('Solar PV')
            axis[0].set_ylim(0,1)
            axis[0].set_xlim(0,8760)
            axis[1].plot(range(8760), cfs_wind_on[region])
            axis[1].set_title('Wind onshore')
            axis[1].set_ylim(0,1)
            axis[1].set_xlim(0,8760)
            axis[2].plot(range(8760), cfs_wind_off[region])
            axis[2].set_title('Wind offshore')
            axis[2].set_ylim(0,1)
            axis[2].set_xlim(0,8760)


def aggregate_vre(df_rtv: pd.DataFrame, cf_file: str):

    ref = config.refs.get('rninja-coders')

    cf_file = f'provincial_data/default/output_data/{cf_file}.csv'
    if not os.path.isfile(cf_file):
        print(f"Cached capacity factors file {cf_file} not found.")
        if input(
            "Run capacity factor collection? It could take a few hours if a large "
            "number of facilities are missing. Otherwise, this facility will be "
            "skipped in capacity factor calculation (Y/N): "
        ).lower() == 'y':
            cf_grabber().gather_cfs()
    df_cf = pd.read_csv(cf_file, index_col=0).fillna(0)

    # Using CapacityFactorTech which does not have a vintage index
    df_rtv['end'] = df_rtv['vint'] + df_rtv['life']
    df_end = df_rtv.groupby(['region','tech'])['end'].max()
    df_rt = df_rtv.groupby(['region', 'tech'])[['facilities','capacity','unit_average_annual_energy']].sum(numeric_only=False).reset_index()

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()
    
    cfs = {region: np.zeros(8760) for region in config.model_regions}
    for _idx, rt in df_rt.iterrows():
        
        # Sum up facility-specific hourly generation
        gen_mwh = np.zeros(8760)
        facilities = rt['facilities'].split(';')[0:-1]
        for facility in facilities:
            code = facility.split(',')[0]
            if code not in df_cf.columns:
                print(f"Facility {code} not found in {cf_file}.")
                if input(
                    "Run capacity factor collection? It could take a few hours if a large "
                    "number of facilities are missing. Otherwise, this facility will be "
                    "skipped in capacity factor calculation (Y/N): "
                ).lower() == 'y':
                    cf_grabber().gather_cfs()
            capacity = float(facility.split(',')[1])
            gen_mwh += capacity * df_cf[code]

        # Adjust the total annual energy to match typical
        energy_adjust = rt['unit_average_annual_energy'] / gen_mwh.sum()

        # Divide by total rt capacity to get aggregate capacity factor for all existing capacity
        # Adjust for expected annual energy and clip to [0:1] again
        cf: pd.Series = energy_adjust * gen_mwh / rt['capacity']
        cf = cf.clip(0, 1)
        
        # For net load for capacity credit calculations
        config.exs_vre_gen[rt['region']] += cf * capacity

        cfs[rt['region']] = cf

        data = []
        for period in config.model_periods:
            
            # Check that there exists an existing vintage that will exist in this period
            if df_end.loc[(rt['region'], rt['tech'])] <= period: continue

            for h, time in config.time.iterrows():

                if time['tod'] == config.time.iloc[0]['tod']:
                    data.append([rt['region'], period, time['season'], time['tod'], rt['tech'], cf.iloc[h],
                                 note, ref.id, 3, 1, 2, 2, 3, utils.data_id(rt['region'])])
                else:
                    data.append([rt['region'], period, time['season'], time['tod'], rt['tech'], cf.iloc[h],
                                 None, None, None, None, None, None, None, utils.data_id(rt['region'])])

        curs.executemany(f"""REPLACE INTO
                    CapacityFactorTech(region, period, season, tod, tech, factor, notes,
                    data_source, dq_cred, dq_geog, dq_struc, dq_tech, dq_time, data_id)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", data)
            
    conn.commit()
    conn.close()

    return cfs



class cf_grabber:
    """
    This gets hourly capacity factors for each facility in the CODERS generators table and saves it locally.
    Can be run on its own from the root directory by calling existing_vre_capacity_factors.cf_grabber().gather_cfs()
    """

    data_dir = 'provincial_data/default/output_data/'

    count_total = 0
    count_completed = 0
    last_time = 0


    def gather_cfs(cls):

        # Get the existing generators from CODERS data
        df_existing, date_accessed = coders_api.get_data(end_point='generators')

        # Convert to CANOE tech codes and regions
        df_existing['tech_code'] = df_existing['gen_type'].str.lower().map(config.existing_map)
        df_existing['region'] = df_existing['operating_region'].str.lower().map(config.region_map)

        # Group by facility
        df_existing = df_existing.groupby('generation_facility_code').first()

        # Filter by solar PV and wind
        df_solar = df_existing.loc[df_existing['tech_code'] == 'solar']
        df_wind_on = df_existing.loc[df_existing['tech_code'] == 'wind_onshore']
        df_wind_off = df_existing.loc[df_existing['tech_code'] == 'wind_offshore']

        cls.count_total = len(df_solar) + len(df_wind_on) + len(df_wind_off)

        print(
            "\nBeginning to collect capacity factor data from the Renewables Ninja API."
            "\nPlease note that this program must run slowly due to API usage limits."
        )

        # Start grabbing data from rninja
        api = utils.renewables_ninja_api()
        cls._gather_solar_cfs(api, df_solar)
        cls._gather_wind_on_cfs(api, df_wind_on)
        cls._gather_wind_off_cfs(api, df_wind_off)


    def _gather_solar_cfs(cls, api: utils.renewables_ninja_api, df_solar: pd.DataFrame):

        file = cls.data_dir + 'cf_solar.csv'
        df_cf = cls._get_cf_file(file)

        for facility_code, facility in df_solar.iterrows():
            if facility_code not in df_cf.columns:
                cls._wait() # API timeout
                df_out, metadata = api.get_pv_data(
                    lat = facility['latitude'],
                    lon = facility['longitude'],
                    tilt = 45,
                )
                df_cf[facility_code] = df_out['electricity']
                cls._save_cf_file(file, df_cf)
            cls.count_completed += 1
            cls._update_progress()


    def _gather_wind_on_cfs(cls, api: utils.renewables_ninja_api, df_wind_on: pd.DataFrame):

        file = cls.data_dir + 'cf_wind_on.csv'
        df_cf = cls._get_cf_file(file)

        for facility_code, facility in df_wind_on.iterrows():
            if facility_code not in df_cf.columns:
                cls._wait() # API timeout
                df_out, metadata = api.get_wind_data(
                    lat = facility['latitude'],
                    lon = facility['longitude'],
                    height = 110,
                    turbine = 'Vestas V112 3000'
                )
                df_cf[facility_code] = df_out['electricity']
                cls._save_cf_file(file, df_cf)
            cls.count_completed += 1
            cls._update_progress()


    def _gather_wind_off_cfs(cls, api: utils.renewables_ninja_api, df_wind_off: pd.DataFrame):

        file = cls.data_dir + 'cf_wind_off.csv'
        df_cf = cls._get_cf_file(file)

        for facility_code, facility in df_wind_off.iterrows():
            if facility_code not in df_cf.columns:
                cls._wait() # API timeout
                df_out, metadata = api.get_wind_data(
                    lat = facility['latitude'],
                    lon = facility['longitude'],
                    height = 150,
                    turbine='Vestas V164 9500'
                )
                df_cf[facility_code] = df_out['electricity']
                cls._save_cf_file(file, df_cf)
            cls.count_completed += 1
            cls._update_progress()


    def _get_cf_file(cls, file: str):
        
        df = None
        if os.path.isfile(file):
            try:
                df = pd.read_csv(file, index_col=0)
            except Exception as e:
                print(f"Failed to read stashed capacity factor file {file}")
                print(e)
        else:
            index = pd.date_range(
                start=f"{config.params['weather_year']}-01-01 00:00:00",
                end=f"{config.params['weather_year']}-12-31 23:00:00",
                freq="h",
                tz="EST"
            )
            pd.DataFrame(index=index).to_csv(file)
        
        if df is not None:
            return df
        else:
            index = pd.date_range(
                start=f"{config.params['weather_year']}-01-01 00:00:00",
                end=f"{config.params['weather_year']}-12-31 23:00:00",
                freq="h",
                tz="EST"
            )
            return pd.DataFrame(index=index)
        

    def _save_cf_file(cls, file: str, df_cf: pd.DataFrame):

        try:
            df_cf.to_csv(file)
        except Exception as e:
            print(f"Could not save capacity factor file {file}")
            print(e)


    def _wait(cls):
        timeout = max(0, 3600/50 - (time.time() - cls.last_time))
        time.sleep(timeout) # To stay within API usage limits
        cls.last_time = time.time()


    def _update_progress(cls):
        runtime = (cls.count_total - cls.count_completed) / 50
        time_finish = time.time() + runtime * 3600
        finish_time = datetime.fromtimestamp(time_finish).strftime("%H:%M")
        progress = cls.count_completed / cls.count_total * 100
        print(f"\rProgress: {progress:.2f}% | Estimated finish time: {finish_time}", end="")