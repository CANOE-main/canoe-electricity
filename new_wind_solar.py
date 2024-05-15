"""
Uses resource characterisation work by Sutubra to generate capacity factors
and capacity credits for clusters of new wind and solar capacity
Written by Ian David Elder for the CANOE model
"""

import pandas as pd
from setup import config
from matplotlib import pyplot as pp
import capacity_credits
import os
import sqlite3
import utils

atb_year = config.params['atb']['year']
atb_reference = config.params['atb']['reference']
vre_year = config.params['sutubra_vre']['year']
vre_reference = config.params['sutubra_vre']['reference']



def aggregate(df_rtv: pd.DataFrame):

    for region in config.model_regions:
        df_rtv_reg = df_rtv.loc[df_rtv['region'] == region]
        aggregate_wind(df_rtv_reg.loc[df_rtv_reg['tech_code'] == 'wind_onshore'].copy(), region)
        aggregate_solar(df_rtv_reg.loc[df_rtv_reg['tech_code'] == 'solar'].copy(), region)



def aggregate_wind(df_rtv: pd.DataFrame, region: str):

    print(f"Aggregating {region} new wind capacity data...")
    print(f"Filling the CapacityFactorProcess table. This may take a minute...")

    """
    ##############################################################
        Gather data for each bin of wind capacity
    ##############################################################
    """

    wind_dir = os.path.realpath(os.path.dirname(__name__)) + f"/provincial_data/{region}/new_wind/"
    df_comp = pd.read_csv(wind_dir + 'Cluster Composition.csv', index_col=0)
    df_cf = pd.read_csv(wind_dir + 'Cluster Capacity Factors.csv', index_col=0)
    df_cf = utils.realign_timezone(df_cf, from_utc_offset=-4)
    df_spur_cost = pd.read_csv(wind_dir + 'Cluster Spur Costs.csv', index_col=0)

    ## Get cost data for each class of turbine T1-3
    wind_config = config.gen_techs.loc['wind_onshore']
    invest_metric = config.params['atb']['cost_invest_metric'] # which ATB metric to use for cost invest

    # Calculating weighted ATB data for each cluster
    class_data = {'t1': dict(), 't2': dict(), 't3': dict()}
    for wind_class, class_dict in class_data.items():

        tech_config = wind_config.copy()
        tech_config['atb_display_name'] = config.params['new_wind_techs'][wind_class]
        tech_config.name = f"wind_onshore_{wind_class}" # atb_data method uses caching on this name

        # Get projected invest and fixed cost and capacity factor tables from ATB
        class_dict['cost_invest'], invest_note = utils.atb_data(tech_config, core_metric_parameter=invest_metric)
        class_dict['cost_invest'] = class_dict['cost_invest'].set_index('core_metric_variable')['value']
        
        class_dict['cost_fixed'], fixed_note = utils.atb_data(tech_config, core_metric_parameter='Fixed O&M')
        class_dict['cost_fixed'] = class_dict['cost_fixed'].set_index('core_metric_variable')['value']

        class_dict['capacity_factor'], cf_note = utils.atb_data(tech_config, core_metric_parameter='CF')
        class_dict['capacity_factor'] = class_dict['capacity_factor'].set_index('core_metric_variable')['value']


    ## Calculate ATB projections for each cluster
    df_invest = pd.DataFrame(columns=df_comp.index.values)
    df_fixed = pd.DataFrame(columns=df_comp.index.values)
    df_cf_index = pd.DataFrame(columns=df_comp.index.values)

    for cluster, comp in df_comp.iterrows():
        
        # Invest and fixed costs and capacity factor improvements from ATB weighted by capacity fractions of turbine class for each cluster
        df_invest[cluster] = sum([class_data[t]['cost_invest'].astype(float) * comp[f"Fraction {t.upper()}"] for t in class_data.keys()])
        df_invest[cluster] += df_spur_cost.loc[cluster, 'WeightedAvgSpur (USD/MW)'] / 1000 # plus spur line cost for invest $/MW -> $/kW

        df_fixed[cluster] = sum([class_data[t]['cost_fixed'].astype(float) * comp[f"Fraction {t.upper()}"] for t in class_data.keys()])

        df_cf_index[cluster] = sum([class_data[t]['capacity_factor'].astype(float) * comp[f"Fraction {t.upper()}"] for t in class_data.keys()])
        df_cf_index[cluster] = df_cf_index[cluster] / df_cf_index[cluster]['2030'] # index to ATB wind base year, 2030

    df_invest *= config.units.loc['cost_invest', 'atb_conv_fact']
    df_fixed *= config.units.loc['cost_fixed', 'atb_conv_fact']

    # Sort by LCOE, then take top n clusters where n = n_bins in generator techs csv
    l = df_rtv.iloc[0]['life']
    i = config.params['global_discount_rate']
    A_P = (i*(1+i)**l)/((1+i)**l-1)
    df_comp['LCOE with Spur'] = df_comp.index.map(
        lambda cluster:
        ( A_P*df_invest.loc['2030', cluster] + df_fixed.loc['2030', cluster] ) # using 2030 because that's the turbine base year
        / (df_comp.loc[cluster, 'Maximum Capacity (MW)'] * df_cf[str(cluster)].sum())
    )

    # Assign cluster to all vints of each bin and set max capacity
    df_rtv.index = df_rtv['bin'].map(lambda n: df_comp.index[n])
    df_rtv.index.name = 'cluster'
    df_rtv['max_cap'] = df_rtv.index.map(lambda cluster: df_comp.loc[cluster, 'Maximum Capacity (MW)'])

    # Aggregate capacity credits based on projected capacity factor
    for vint in df_rtv['vint'].unique():

        # Get bins for this vintage
        _df_rtv = df_rtv.loc[df_rtv['vint'] == vint].copy()

        # Index capacity factor to ATB projections
        _df_cf = df_cf.copy()
        for cluster in _df_rtv.index: _df_cf[str(cluster)] *= df_cf_index.loc[str(vint), cluster]

        # Calculate capacity credits and add to database
        capacity_credits.aggregate_vre(_df_rtv, _df_cf, region, vint)


    """
    ##############################################################
        Add wind data to database
    ##############################################################
    """

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()

    # Group rtv by cluster to calculate CC of each cluster (i.e. ignoring vintage)
    df_rt = df_rtv.groupby('cluster').first().sort_values('bin')

    input_comm = config.commodities.loc[wind_config['in_comm']]
    output_comm = config.commodities.loc[wind_config['out_comm']]


    ## MaxCapacity
    note = f"Wind characterisation work done by Sutubra. Grid cells binned by ascending LCOE (Sutubra, {vre_year})."
    reference = vre_reference
    for cluster, rt in df_rt.iterrows():
        for period in config.model_periods:

            max_cap = rt['max_cap'] / 1000 # TODO MW vs GW

            curs.execute(f"""REPLACE INTO
                         MaxCapacity(regions, periods, tech, maxcap, maxcap_units, maxcap_notes,
                         reference, data_year, dq_est, dq_rel, dq_comp, dq_time, dq_geog, dq_tech)
                         VALUES("{rt['region']}", {period}, "{rt['tech']}", {max_cap}, "({config.units.loc['capacity','units']})", "{note}",
                         "{reference}", {vre_year}, 1, 1, 1, {utils.dq_time(config.params['weather_year'], period)}, 1, 1)""")

    
    # Indexed by region, tech, and vintage
    for cluster, rtv in df_rtv.iterrows():

        ## Efficiency
        curs.execute(f"""REPLACE INTO
                    Efficiency(regions, input_comm, tech, vintage, output_comm, efficiency, eff_notes)
                    VALUES("{region}", "{input_comm['commodity']}", "{rtv['tech']}", {rtv['vint']}, "{output_comm['commodity']}", 1,
                    "({input_comm['units']}/{output_comm['units']}) dummy input so arbitrary")""")
        
        
        ## CostInvest
        note = (
            f"NREL ATB {rtv['vint']} {invest_metric} (NREL, {atb_year}) weighted by capacity shares of turbine class "
            f"plus estimated spur line cost from existing transmissions lines (Sutubra, {vre_year}). "
        )
        reference = f"{atb_reference}; {vre_reference}"

        ci = df_invest.loc[str(rtv['vint']), cluster]

        curs.execute(f"""REPLACE INTO
                    CostInvest(regions, tech, vintage, cost_invest_units, cost_invest_notes, data_cost_invest, data_cost_year, data_curr, reference, dq_est)
                    VALUES("{region}", "{rtv['tech']}", {rtv['vint']}, "({config.units.loc['cost_invest', 'units']})", "{note}", {ci},
                    {config.params['atb']['currency_year']}, "{config.params['atb']['currency']}", "{config.references['atb']}", 1)""")


        ## CapacityFactorProcess
        note = (
            f"Wind characterisation work done by Sutubra. Grid cells binned by ascending LCOE (Sutubra, {vre_year}). "
            f"Capacity factors further indexed to those in NREL ATB, by construction year with 2030 as base year. "
            f"Bounded to <= 1 (NREL, {atb_year})."
        )
        reference = vre_reference

        cf: pd.Series = df_cf[str(cluster)] * df_cf_index.loc[str(rtv['vint']), cluster]
        cf = cf.clip(0,1)
        tod_0 = config.time.iloc[0]['time_of_day']
        dq_time = utils.dq_time(vre_year, rtv['vint'])
        
        for h, time in config.time.iterrows():
            
            # Only add extraneous entries for first hour of each day otherwise this table is several GB per region
            if time['time_of_day'] == tod_0:
                curs.execute(f"""REPLACE INTO
                            CapacityFactorProcess(regions, season_name, time_of_day_name, tech, vintage, cf_process, cf_process_notes,
                            reference, data_year, dq_est, dq_rel, dq_comp, dq_time, dq_geog, dq_tech)
                            VALUES('{rtv['region']}', '{time['season']}', '{time['time_of_day']}', '{rtv['tech']}', {rtv['vint']}, {cf.iloc[h]}, '{note}',
                            '{reference}', {vre_year}, 1, 1, 1, {dq_time}, 1, 1)""")
            else:
                curs.execute(f"""REPLACE INTO
                            CapacityFactorProcess(regions, season_name, time_of_day_name, tech, vintage, cf_process)
                            VALUES('{rtv['region']}', '{time['season']}', '{time['time_of_day']}', '{rtv['tech']}', {rtv['vint']}, {cf.iloc[h]})""")

            
        

        ## CostFixed
        note = f"NREL ATB {rtv['vint']} Fixed O&M (NREL, {atb_year}) weighted by capacity shares of turbine class (Sutubra, {vre_year})."
        reference = f"{atb_reference}; {vre_reference}"
        for period in config.model_periods:

            if rtv['vint'] > period or rtv['vint'] + rtv['life'] <= period: continue

            cf = df_fixed.loc[str(rtv['vint']), cluster]

            curs.execute(f"""REPLACE INTO
                        CostFixed(regions, periods, tech, vintage, cost_fixed_units, cost_fixed_notes, data_cost_fixed, data_cost_year, data_curr, reference, dq_est)
                        VALUES("{region}", {period}, "{rtv['tech']}", {rtv['vint']}, "({config.units.loc['cost_fixed', 'units']})", "{note}", {cf},
                        {config.params['atb']['currency_year']}, "{config.params['atb']['currency']}", "{config.references['atb']}", 1)""")


    conn.commit()
    conn.close()

    print(f"{region} new wind capacity data aggregated into {os.path.basename(config.database_file)}")



def aggregate_solar(df_rtv: pd.DataFrame, region: str):

    print(f"Aggregating {region} new solar capacity data...")
    print(f"Filling the CapacityFactorProcess table. This may take a minute...")

    """
    ##############################################################
        Gather data for each bin of solar capacity
    ##############################################################
    """

    solar_dir = os.path.realpath(os.path.dirname(__name__)) + f"/provincial_data/{region}/new_solar/"

    df_bins = pd.read_csv(solar_dir + 'Solar Resource Summary.csv', index_col=False).astype(float)
    
    # Sort solar bins by configured metric
    sort_by = config.params['sutubra_vre']['sort_solar_by']
    if sort_by == 'lcoe': df_bins = df_bins.sort_values('LCOE with Spur', ascending=True)
    elif sort_by == 'cf': df_bins = df_bins.sort_values('Capacity Factor', ascending=True)

    df_bins = df_bins.iloc[0:df_rtv['bin'].max()+1] # only need n grid cells, not all 5000
    df_bins.index = df_bins.index.map(lambda idx: f"({df_bins.loc[idx, 'x']}, {df_bins.loc[idx, 'y']})") # turn coordinates into string index

    df_cf = pd.read_csv(solar_dir + 'Hourly PV Capacity Factors.csv', index_col=0)
    df_cf = utils.realign_timezone(df_cf, from_utc_offset=-4)

    df_rtv.index = df_rtv['bin'].map(lambda bin: df_bins.index[bin]) # assign cluster to all vints of each bin
    df_rtv.index.name = 'cluster'
    df_rtv['max_cap'] = df_rtv.index.map(lambda cluster: df_bins.loc[cluster, 'Max Capacity (MW)'])
    
    solar_config = config.gen_techs.loc['solar']
    invest_metric = config.params['atb']['cost_invest_metric'] # which ATB metric to use for cost invest

    ## Get ATB projections for each bin
    invest, invest_note = utils.atb_data(solar_config, core_metric_parameter=invest_metric)
    fixed, fixed_note = utils.atb_data(solar_config, core_metric_parameter='Fixed O&M')
    cf_index, cf_note = utils.atb_data(solar_config, core_metric_parameter='CF')

    invest = invest.set_index('core_metric_variable')['value'].astype(float)
    fixed = fixed.set_index('core_metric_variable')['value'].astype(float)
    cf_index = cf_index.set_index('core_metric_variable')['value'].astype(float)
    cf_index /= cf_index['2022'] # index to base year for solar, 2022

    invest *= config.units.loc['cost_invest', 'atb_conv_fact']
    fixed *= config.units.loc['cost_fixed', 'atb_conv_fact']
    
    # Aggregate capacity credits based on projected capacity factor
    for vint in df_rtv['vint'].unique():

        # Get bins for this vintage
        _df_rtv = df_rtv.loc[df_rtv['vint'] == vint].copy()

        # Index capacity factor to ATB projections
        _df_cf = df_cf.copy()
        for cluster in _df_rtv.index: _df_cf[str(cluster)] *= cf_index[str(vint)]

        # Calculate capacity credits and add to database
        capacity_credits.aggregate_vre(_df_rtv, _df_cf, region, vint)


    """
    ##############################################################
        Add solar pv data to database
    ##############################################################
    """

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()

    # Group rtv by cluster to calculate CC of each cluster (i.e. ignoring vintage)
    df_rt = df_rtv.groupby('cluster').first().sort_values('bin')

    input_comm = config.commodities.loc[solar_config['in_comm']]
    output_comm = config.commodities.loc[solar_config['out_comm']]


    ## MaxCapacity
    note = f"Solar characterisation work done by Sutubra. Grid cells sorted by ascending LCOE (Sutubra, {vre_year})."
    reference = vre_reference
    for cluster, rt in df_rt.iterrows():
        for period in config.model_periods:

            max_cap = rt['max_cap'] / 1000 # TODO MW vs GW

            curs.execute(f"""REPLACE INTO
                         MaxCapacity(regions, periods, tech, maxcap, maxcap_units, maxcap_notes,
                         reference, data_year, dq_est, dq_rel, dq_comp, dq_time, dq_geog, dq_tech)
                         VALUES("{rt['region']}", {period}, "{rt['tech']}", {max_cap}, "({config.units.loc['capacity','units']})", "{note}",
                         "{reference}", {vre_year}, 1, 1, 1, {utils.dq_time(config.params['weather_year'], period)}, 1, 1)""")

            
    # Indexed by region, tech, and vintage
    for cluster, rtv in df_rtv.iterrows():

        bin_config = df_bins.loc[rtv.name]

        ## Efficiency
        curs.execute(f"""REPLACE INTO
                    Efficiency(regions, input_comm, tech, vintage, output_comm, efficiency, eff_notes)
                    VALUES("{region}", "{input_comm['commodity']}", "{rtv['tech']}", {rtv['vint']}, "{output_comm['commodity']}", 1,
                    "({input_comm['units']}/{output_comm['units']}) dummy input so arbitrary")""")
        
        
        ## CostInvest
        note = (
            f"{invest_note}. "
            f"Plus estimated spur line cost from existing transmissions lines (Sutubra, {vre_year}). "
        )
        reference = f"{atb_reference}; {vre_reference}"

        ci = invest[str(rtv['vint'])] + bin_config['Interconnection Cost ($/kW)']

        curs.execute(f"""REPLACE INTO
                    CostInvest(regions, tech, vintage, cost_invest_units, cost_invest_notes, data_cost_invest, data_cost_year, data_curr, reference, dq_est)
                    VALUES("{region}", "{rtv['tech']}", {rtv['vint']}, "({config.units.loc['cost_invest', 'units']})", "{note}", {ci},
                    {config.params['atb']['currency_year']}, "{config.params['atb']['currency']}", "{config.references['atb']}", 1)""")


        ## CapacityFactorProcess
        note = (
            f"Wind characterisation work done by Sutubra. Grid cells binned by ascending LCOE (Sutubra, {vre_year}). "
            f"Capacity factors further indexed to those in NREL ATB, by construction year with 2030 as base year. "
            f"Bounded to <= 1 (NREL, {atb_year})."
        )
        reference = vre_reference
            
        cf: pd.Series = df_cf[str(cluster)] * cf_index[str(rtv['vint'])]
        cf = cf.clip(0,1)
        tod_0 = config.time.iloc[0]['time_of_day']
        dq_time = utils.dq_time(vre_year, rtv['vint'])
        
        for h, time in config.time.iterrows():

            if time['time_of_day'] == tod_0:
                curs.execute(f"""REPLACE INTO
                            CapacityFactorProcess(regions, season_name, time_of_day_name, tech, vintage, cf_process, cf_process_notes,
                            reference, data_year, dq_est, dq_rel, dq_comp, dq_time, dq_geog, dq_tech)
                            VALUES('{rtv['region']}', '{time['season']}', '{time['time_of_day']}', '{rtv['tech']}', {rtv['vint']}, {cf.iloc[h]}, '{note}',
                            '{reference}', {vre_year}, 1, 1, 1, {dq_time}, 1, 1)""")
            else:
                curs.execute(f"""REPLACE INTO
                            CapacityFactorProcess(regions, season_name, time_of_day_name, tech, vintage, cf_process,
                            data_year, dq_est, dq_rel, dq_comp, dq_time, dq_geog, dq_tech)
                            VALUES('{rtv['region']}', '{time['season']}', '{time['time_of_day']}', '{rtv['tech']}', {rtv['vint']}, {cf.iloc[h]},
                            {vre_year}, 1, 1, 1, {dq_time}, 1, 1)""")
        

        ## CostFixed
        note = fixed_note
        reference = f"{atb_reference}; {vre_reference}"
        for period in config.model_periods:

            if rtv['vint'] > period or rtv['vint'] + rtv['life'] <= period: continue

            cf = fixed[str(rtv['vint'])]

            curs.execute(f"""REPLACE INTO
                        CostFixed(regions, periods, tech, vintage, cost_fixed_units, cost_fixed_notes, data_cost_fixed, data_cost_year, data_curr, reference, dq_est)
                        VALUES("{region}", {period}, "{rtv['tech']}", {rtv['vint']}, "({config.units.loc['cost_fixed', 'units']})", "{note}", {cf},
                        {config.params['atb']['currency_year']}, "{config.params['atb']['currency']}", "{config.references['atb']}", 1)""")


    conn.commit()
    conn.close()

    print(f"{region} new solar capacity data aggregated into {os.path.basename(config.database_file)}")