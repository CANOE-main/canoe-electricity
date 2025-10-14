"""
Gets historical hourly capacity factors for hydroelectric generation in Ontario
from IESO public data. Then saves as a csv to be pulled from elsewhere.
Written by Ian David Elder for the CANOE model.
"""

import pandas as pd
from setup import config
from setup import reference
import os
import sqlite3
import numpy as np
import utils
from matplotlib import pyplot as pp

this_dir = os.path.realpath(os.path.dirname(__file__)) + "/"

# Get generator types for some common generator names from local file
# This file was made by manually cross-referencing generators with CODERS
df_types = pd.read_csv(this_dir + 'hydro_types.csv', index_col=0)

weather_year = config.params['weather_year']



def aggregate_cfs(df_rtv: pd.DataFrame):
    
    cfs, note, ref = get_capacity_factors(weather_year)

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()

    # CapacityFactorTech has no vintage index but still need to validate vintages
    df_rtv['end'] = df_rtv['vint'] + df_rtv['life']
    df_end = df_rtv.groupby(['region','tech','tech_code'])['end'].max()
    df_rt = df_rtv.groupby(['region','tech','tech_code']).sum(numeric_only=True).reset_index()

    # Run of river hydro
    for _idx, rt in df_rt.loc[df_rt['tech_code'] == 'hydro_run'].iterrows():
        
        # Summing curtailed generation to get net load for capacity credit calculations
        config.exs_vre_gen[rt['region']] += np.array(cfs['hydro_run']) * rt['capacity']

        data = []
        for period in config.model_periods:

            # Check that there exists an existing vintage that will exist in this period
            if df_end.loc[(rt['region'], rt['tech'], rt['tech_code'])] <= period: continue
            
            for h, time in config.time.iterrows():

                if time['tod'] == config.time.iloc[0]['tod']:
                    data.append([rt['region'], period, time['season'], time['tod'], rt['tech'], cfs['hydro_run'][h], note,
                            ref.id, 1, 1, 1, 1, 3, utils.data_id(rt['region'])])
                else:
                    data.append([rt['region'], period, time['season'], time['tod'], rt['tech'], cfs['hydro_run'][h],
                                 None, None, None, None, None, None, None, utils.data_id(rt['region'])])
                 
        curs.executemany(f"""REPLACE INTO
                        CapacityFactorTech(region, period, season, tod, tech, factor, notes,
                        data_source, dq_cred, dq_geog, dq_struc, dq_tech, dq_time, data_id)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", data)
            
    note += " Averaged over each day."
            
    # Daily storage hydro
    # This will break if daily hydro isn't aggregated to a single vintage
    for _idx, rt in df_rt.loc[df_rt['tech_code'] == 'hydro_daily'].iterrows():
        for period in config.model_periods:
            for seas in config.time['season'].unique():

                hours = config.time.loc[config.time['season'] == seas].index.to_list()
                cf_dly = np.mean(cfs['hydro_daily'][min(hours):max(hours)+1])

                curs.execute(f"""REPLACE INTO
                            LimitSeasonalCapacityFactor(region, period, season, tech, operator, factor, notes,
                            data_source, dq_cred, dq_geog, dq_struc, dq_tech, dq_time, data_id)
                            VALUES('{rt['region']}', {period}, '{seas}', '{rt['tech']}', "le", {cf_dly}, '{note}',
                            '{ref.id}', 1, 1, 1, 1, 3, "{utils.data_id(rt['region'])}")""")
    
    conn.commit()
    conn.close()



def get_capacity_factors(year: int) -> tuple[dict[str, list[float]], str, reference]:

    if year < 2019: cf_dly, cf_ror = get_annual_cfs_before_2019(year)
    elif year > 2019: cf_dly, cf_ror = get_annual_cfs_after_2019(year)
    else:
        print("Tried to get ON historical hydro data for the year 2019. "
        "Data for that year is split over two IESO data directories and aggregation isn't configured, yet. "
        "Taking data from 2020, instead.")
        get_annual_cfs_after_2019(2020)

    # To handle leap years
    cf_dly = cf_dly[0:8760]
    cf_ror = cf_ror[0:8760]

    cf_dly[cf_dly < config.params['cf_tolerance']] = 0
    cf_ror[cf_ror < config.params['cf_tolerance']] = 0

    # Save as csvs so other scripts can pull from them
    pd.DataFrame(cf_dly).to_csv(this_dir + f"output_data/cf_hydro_run_{year}.csv")
    pd.DataFrame(cf_ror).to_csv(this_dir + f"output_data/cf_hydro_daily_{year}.csv")
    
    # Plot if that is on
    if config.params['show_plots']:
        figure, axis = pp.subplots(2, 1, constrained_layout=True)
        figure.suptitle(f"Ontario {year} historical capacity factors")

        axis[0].plot(cf_dly)
        axis[0].plot(range(0,365*24,24),[np.mean(cf_dly[d*24:d*24+24]) for d in range(365)],'r-')
        axis[0].set_title('Daily storage')
        axis[0].set_ylim(0,1)
        axis[1].plot(cf_ror)
        axis[1].set_title('Run-of-river')
        axis[1].set_ylim(0,1)

    # Referencing
    note = f"{year} hourly generator output divided by capability."
    ref = config.refs.add('ieso_exs_monthly', f"{config.params['ieso_reference'].replace('<year>', str(year))}GenOutputCapabilityMonth/")

    return {'hydro_daily': cf_dly, 'hydro_run': cf_ror}, note, ref


def get_annual_cfs_before_2019(year) -> tuple[list[float], list[float]]:

    url = f"https://www.ieso.ca/-/media/Files/IESO/Power-Data/data-directory/GOC-{year}.xlsx"

    # Hourly outputs and available capacities from IESO data, by generator
    df_out = utils.get_data(url, index_col=0, sheet_name='Output', name=f"on_gen_output_{year}.csv")
    df_cap = utils.get_data(url, index_col=0, sheet_name='Available Capacities', name=f"on_gen_capacity_{year}.csv")

    # Split into daily versus run of river based on local file of matched generators
    dly_gens = df_types.loc[df_types['hydro_type'] == 'hydro_daily'].index.tolist()
    ror_gens = df_types.loc[df_types['hydro_type'] == 'hydro_run'].index.tolist()

    df_out_dly = df_out[[gen for gen in df_out.columns if gen in dly_gens]]
    df_cap_dly = df_cap[[gen for gen in df_cap.columns if gen in dly_gens]]

    df_out_ror = df_out[[gen for gen in df_out.columns if gen in ror_gens]]
    df_cap_ror = df_cap[[gen for gen in df_cap.columns if gen in ror_gens]]

    # Capacity factor is output over available capacity
    cf_dly = df_out_dly.astype(float).sum(axis=1) / df_cap_dly.astype(float).sum(axis=1)
    cf_ror = df_out_ror.astype(float).sum(axis=1) / df_cap_ror.astype(float).sum(axis=1)


    ## Output the total hydro capacity factor (solely for representative day clustering)
    # Get the daily total output and available capacity for daily hydro
    df_out_dly = df_out_dly.astype(float).sum(axis=1).groupby(level='Date').sum()
    df_cap_dly = df_cap_dly.astype(float).sum(axis=1).groupby(level='Date').sum()

    # Prepare the hourly output and available capacity for run of river
    df_out = df_out_ror.astype(float).sum(axis=1)
    df_cap = df_cap_ror.astype(float).sum(axis=1)

    # Add the daily average outputs and capacities to hourly run of river outputs and capacities
    for day in df_out.index.unique(): df_out.loc[day] += df_out_dly.loc[day] / 24
    for day in df_cap.index.unique(): df_cap.loc[day] += df_cap_dly.loc[day] / 24

    # CF is total output over total available capacity per hour
    df_cf = df_out / df_cap
    df_cf.index = pd.date_range('2018-01-01', '2019-01-01', freq='1h', inclusive='left', tz=config.params['timezone']) # timezone index
    df_cf.to_csv(this_dir + "output_data/cf_all_hydro_2018.csv") # save to file


    # Return hourly capacity factors for each generator type
    return cf_dly.tolist(), cf_ror.tolist()



def get_annual_cfs_after_2019(year) -> tuple[list[float], list[float]]:

    # Initialise hourly cf list for the year by hydro type
    cf_dly = []
    cf_ror = []

    # Append hourly CFs for each month to annual list
    for month in range(12):
        cf_d, cf_r = get_month_cfs(year, month)
        cf_dly.extend(cf_d)
        cf_ror.extend(cf_r)

    return cf_dly, cf_ror



def get_month_cfs(year: int, month: int) -> tuple[list[float], list[float]]:

    mm = str(month+1) if month+1>9 else '0' + str(month+1)
    url = f"""http://reports.ieso.ca/public/GenOutputCapabilityMonth/PUB_GenOutputCapabilityMonth_{year}{mm}.csv"""

    # Get hourly generated mwh per generator for this month
    df_mon = utils.get_data(url, skiprows=3, index_col=False).drop(columns='Fuel Type')

    # Long story short, getting hourly capacity factors by hydro type
    df_mon['type'] = df_mon['Generator'].map(df_types[1]) # map out type of hydro, daily or run of river
    df_mon = df_mon.loc[df_mon['type'].notna()] # drop any that we can't identify
    df_mon = df_mon.set_index(['Delivery Date','type','Measurement','Generator']).apply(pd.to_numeric, errors='coerce') # change data to numeric
    df_mon = df_mon.groupby(['Delivery Date','type','Measurement']).sum() # sum output and capability hourly by hydro type
    df_mon = df_mon.query('Measurement == "Output"').divide(df_mon.query('Measurement == "Capability"').values).fillna(0) # divide output/capability = cf
    df_mon = df_mon.reset_index().drop(columns='Measurement') # so we can split by type and remove excess columns

    # Split into types and prepare to listify
    df_dly = df_mon.loc[df_mon['type']=='hydro_daily'].transpose().drop(['Delivery Date','type'])
    df_ror = df_mon.loc[df_mon['type']=='hydro_run'].transpose().drop(['Delivery Date','type'])

    # Initialise hourly capacity factors for the month
    cf_dly = []
    cf_ror = []

    # Listify that table
    for col in df_dly.columns: cf_dly.extend(df_dly[col].values)
    for col in df_ror.columns: cf_ror.extend(df_ror[col].values)

    return cf_dly, cf_ror