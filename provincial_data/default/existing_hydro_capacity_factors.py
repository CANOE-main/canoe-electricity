"""
Gets historical hourly capacity factors for hydroelectric generation in Ontario
from IESO public data. Then saves as a csv to be pulled from elsewhere.
Written by Ian David Elder for the CANOE model.
"""

import pandas as pd
from setup import config
import sqlite3
import numpy as np
import utils
from matplotlib import pyplot as pp
from provincial_data.on import existing_hydro_capacity_factors as on_cf

weather_year = config.params['weather_year']
days_per_month = [31,28,31,30,31,30,31,31,30,31,30,31]

note = (
    f'Total monthly hydro output by region from StatCan table 25100015 for year {weather_year}'
    ' apportioned by average annual unit energy from CODERS by type of existing hydro generators.'
)
ref = (
    'Government of Canada, S. C. (2018, June 27). Electric power generation, monthly generation by '
    'type of electricity. https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=2510001501; '
    f"{config.params['coders']['reference']}"
)
ref = config.refs.add(
    'default_hydro_cf',
    ref
)


def get_daily_outputs():

    # Download monthly generation data from StatCan
    df = utils.get_statcan_table(
        table=25100015,
        save_as='monthly_hydro_gen',
        filter=lambda df: df.loc[
            np.array(df['Type of electricity generation'] == 'Hydraulic turbine') &
            np.array(df['Class of electricity producer'] == 'Total all classes of electricity producer') &
            np.array(df['GEO'].str.lower().map(config.region_map).isin(config.model_regions)) &
            np.array([int(s[0]) == weather_year for s in df['REF_DATE'].str.split('-')])
        ],
        usecols=['REF_DATE','GEO','Class of electricity producer','Type of electricity generation','VALUE'],
    ).reset_index()

    # Group by region and month
    df['region'] = df['GEO'].str.lower().map(config.region_map)
    df['month'] = [int(s[1])-1 for s in df['REF_DATE'].str.split('-')]
    df_monthly = df.set_index(['region','month'])['VALUE'] # MWh / month

    # Spread these average values over seasons in the model (MWh / day)
    data = []
    for _idx, row in config.time.iterrows():
        if row['tod'] != 'H01': continue
        data.append(tuple(
            df_monthly.loc[(region, row['month'])] / days_per_month[row['month']]
            for region in config.model_regions
        ))
    df_daily = pd.DataFrame(data=data, columns=config.model_regions, index=config.time['season'].unique())

    return df_daily


def aggregate_cfs(df_rtv: pd.DataFrame):

    print("Aggregating capacity factors for existing hydroelectric capacity...")
    
    df_daily = get_daily_outputs()

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()

    # CapacityFactorTech has no vintage index but still need to validate vintages by period
    df_rtv['end'] = df_rtv['vint'] + df_rtv['life']
    df_end = df_rtv.groupby(['region','tech','tech_code'])['end'].max()
    df_rt = df_rtv.groupby(['region','tech','tech_code']).sum(numeric_only=True).reset_index()

    df_total_energy = df_rtv.groupby('region')['unit_average_annual_energy'].sum()

    cfs = {region: {code: np.zeros(8760) for code in ('hydro_run','hydro_daily','hydro_monthly')} for region in config.model_regions}

    # Run of river hydro
    _note = note + ' Available energy assumed constant for each hour within each month.'
    for _idx, rt in df_rt.iterrows():
        
        # Hourly generation to get net load for capacity credit calculations (MWh/h, i.e., MW)
        hourly = np.array([(df_daily.loc[row['season']][rt['region']])/24.0 for (_idx, row) in config.time.iterrows()])
        hourly *= rt['unit_average_annual_energy'] / df_total_energy.loc[rt['region']] # apportion to average annual energy
        hourly /= 1000 # MW to GW

        cf = hourly / rt['capacity'] # GW / GW
        cf[cf < config.params['cf_tolerance']] = 0
        cfs[rt['region']][rt['tech_code']] = cf

        if rt['tech_code'] != 'hydro_run': continue # only need CFs for plotting

        # Add to VRE outputs to calculate capacity credits of new wind and solar
        config.exs_vre_gen[rt['region']] += hourly

        data = []
        for period in config.model_periods:

            # Check that there exists an existing vintage that will exist in this period
            if df_end.loc[(rt['region'], rt['tech'], rt['tech_code'])] <= period: continue
            
            for h, time in config.time.iterrows():

                if time['tod'] == config.time.iloc[0]['tod']:
                    data.append([rt['region'], period, time['season'], time['tod'], rt['tech'], cf[h], _note,
                            ref.id, 1, 1, 1, 1, 3, utils.data_id(rt['region'])])
                else:
                    data.append([rt['region'], period, time['season'], time['tod'], rt['tech'], cf[h],
                                 None, None, None, None, None, None, None, utils.data_id(rt['region'])])
                 
        curs.executemany(f"""REPLACE INTO
                        CapacityFactorTech(region, period, season, tod, tech, factor, notes,
                        data_source, dq_cred, dq_geog, dq_struc, dq_tech, dq_time, data_id)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", data)
            
    # Daily and monthly storage hydro
    # This will break if hydro isn't aggregated to a single vintage
    _note = note + ' Available energy assumed constant for each day within each month.' # TODO LDES
    for _idx, rt in df_rt.loc[df_rt['tech_code'].isin(('hydro_daily','hydro_monthly'))].iterrows():
        for period in config.model_periods:
            for seas in config.time['season'].unique():

                hourly = df_daily.loc[seas, rt['region']] / 24.0
                hourly *= rt['unit_average_annual_energy'] / df_total_energy.loc[rt['region']]
                hourly /= 1000
                cf_seas = hourly / rt['capacity'] # GW / GW
                cf_seas[cf_seas < config.params['cf_tolerance']] = 0

                curs.execute(f"""REPLACE INTO
                            LimitSeasonalCapacityFactor(region, period, season, tech, operator, factor, notes,
                            data_source, dq_cred, dq_geog, dq_struc, dq_tech, dq_time, data_id)
                            VALUES('{rt['region']}', {period}, '{seas}', '{rt['tech']}', "le", {cf_seas}, '{_note}',
                            '{ref.id}', 1, 1, 1, 1, 3, "{utils.data_id(rt['region'])}")""")
    
    conn.commit()
    conn.close()

    # Plotting if set to show
    if config.params['show_plots']:
        for region in df_rt['region'].unique():
            
            figure, axis = pp.subplots(3, 1, constrained_layout=True)
            figure.suptitle(
                f"{region} {config.params['weather_year']} synthesized hourly capacity factors\n"
                "for existing hydroelectric capacity (real data in red, if available)"
            )

            # Compare to real data for Ontario
            if region == 'ON':
                on_cfs, _, _ = on_cf.get_capacity_factors(config.params['weather_year'])
                axis[0].plot(range(8760), on_cfs['hydro_run'], 'r')
                axis[1].plot(range(8760), on_cfs['hydro_daily'], 'r')
            
            axis[0].plot(range(8760), cfs[region]['hydro_run'])
            axis[0].set_title('Run of river')
            axis[0].set_ylim(0,1)
            axis[0].set_xlim(0,8760)
            axis[1].plot(range(8760), cfs[region]['hydro_daily'])
            axis[1].set_title('Daily storage')
            axis[1].set_ylim(0,1)
            axis[1].set_xlim(0,8760)
            axis[2].plot(range(8760), cfs[region]['hydro_monthly'])
            axis[2].set_title('Monthly storage')
            axis[2].set_ylim(0,1)
            axis[2].set_xlim(0,8760)