"""
Gets historical hourly capacity factors for hydroelectric generation in Ontario
from IESO public data. Then saves as a csv to be pulled from elsewhere.
Written by Ian David Elder for the CANOE model.
"""

import pandas as pd
from setup import config
import os
import sqlite3
import numpy as np
import utils
from matplotlib import pyplot as pp

this_dir = os.path.realpath(os.path.dirname(__file__)) + "/"

data_year = 2020 # disaggregated data not available pre-2020



def aggregate_cfs(df_rtv: pd.DataFrame):
    
    cfs, note, reference = get_capacity_factors(data_year)

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()

    # Run of river hydro
    for _idx, ror in df_rtv.loc[df_rtv['tech_code'] == 'hydro_run'].iterrows():
        for h, time in config.time.iterrows():

            curs.execute(f"""REPLACE INTO
                        CapacityFactorTech(regions, season_name, time_of_day_name, tech, cf_tech, cf_tech_notes,
                        reference, data_year, dq_rel, dq_comp, dq_time, dq_geog, dq_tech)
                        VALUES('{ror['region']}', '{time['season']}', '{time['time_of_day']}', '{ror['tech']}', {cfs['hydro_run'][h]}, '{note}',
                        '{reference}', {data_year}, 1, 1, 1, 1, 1)""")
            
    min_note = note + " Summed per day and multiplied by existing capacity. Times 0.99 for computational slack"
    max_note = note + " Summed per day and multiplied by existing capacity. Times 1.01 for computational slack"
            
    # Daily storage hydro
    # This will break if daily hydro isn't aggregated to a single vintage
    for _idx, dly in df_rtv.loc[df_rtv['tech_code'] == 'hydro_daily'].iterrows():
        for seas in config.time['season'].unique():

            hours = config.time.loc[config.time['season'] == seas].index.to_list()

            cap = dly['capacity']
            act_dly = cap * sum(cfs['hydro_daily'][min(hours):max(hours)+1]) * 3.6E-6 # MWh to PJ

            for period in config.model_periods:

                curs.execute(f"""REPLACE INTO
                            MinSeasonalActivity(regions, periods, season_name, tech, minact, minact_units, minact_notes,
                            reference, data_year, dq_rel, dq_comp, dq_time, dq_geog, dq_tech)
                            VALUES('{dly['region']}', {period}, '{seas}', '{dly['tech']}', {act_dly*0.99}, '(PJ)', '{min_note}',
                            '{reference}', {data_year}, 1, 1, 1, 1, 1)""")
                curs.execute(f"""REPLACE INTO
                            MaxSeasonalActivity(regions, periods, season_name, tech, maxact, maxact_units, maxact_notes,
                            reference, data_year, dq_rel, dq_comp, dq_time, dq_geog, dq_tech)
                            VALUES('{dly['region']}', {period}, '{seas}', '{dly['tech']}', {act_dly*1.01}, '(PJ)', '{max_note}',
                            '{reference}', {data_year}, 1, 1, 1, 1, 1)""")
            
    conn.commit()
    conn.close()



def get_capacity_factors(year: int) -> tuple[dict[str, list[float]], str, str]:

    # Initialise hourly cf list for the year by hydro type
    cf_dly = []
    cf_ror = []

    # Append hourly CFs for each month to annual list
    for month in range(12):
        cf_d, cf_r = get_month_cfs(year, month)
        cf_dly.extend(cf_d)
        cf_ror.extend(cf_r)

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
    reference = f"{config.params['ieso_reference'].replace('<year>', str(year))}GenOutputCapabilityMonth/"

    return {'hydro_daily': cf_dly, 'hydro_run': cf_ror}, note, reference



def get_month_cfs(year: int, month: int) -> tuple[list[float], list[float]]:

    mm = str(month+1) if month+1>9 else '0' + str(month+1)
    url = f"""http://reports.ieso.ca/public/GenOutputCapabilityMonth/PUB_GenOutputCapabilityMonth_{year}{mm}.csv"""

    # Get hourly generated mwh per generator for this month
    df_mon = utils.get_data(url, skiprows=3, index_col=False).drop(columns='Fuel Type')

    # Get generator types for some common generator names from local file
    # This file was made by manually cross-referencing generators with CODERS
    df_types = pd.read_csv(this_dir + 'hydro_types.csv', index_col=0, header=None)

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