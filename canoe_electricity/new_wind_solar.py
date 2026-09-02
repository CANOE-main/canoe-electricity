"""
Uses resource characterisation work by Sutubra to generate capacity factors
and capacity credits for clusters of new wind and solar capacity
Written by Ian David Elder for the CANOE model
"""

import pandas as pd
from canoe_electricity.setup import config
from matplotlib import pyplot as pp
import canoe_electricity.capacity_credits as capacity_credits
import os
import sqlite3
import canoe_electricity.utils as utils
from canoe_electricity.currency_conversion import conv_curr
from canoe_schema.v4_0.models import Efficiency, CostInvest, CapacityFactorProcess, LimitCapacity, CostFixed

atb_year = config.atb.year
atb_ref = config.refs.add('atb', config.atb.reference)
sutubra_year = config.sutubra_vre.year
sutubra_ref = config.refs.add('sutubra_vre', config.sutubra_vre.reference)
combo_ref = config.refs.add('atb_sut_vre', f"{atb_ref.citation}; {sutubra_ref.citation}")



def aggregate(df_rtv: pd.DataFrame):
    if config.include_new_wind_solar:
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

    # wind_dir = os.path.realpath(os.path.dirname(__name__)) + f"/provincial_data/{region}/new_wind/"
    wind_dir = os.path.realpath(os.path.dirname(__name__)) + f"/provincial_data/on/new_wind/" # TODO other provinces data
    df_comp = pd.read_csv(wind_dir + 'Cluster Composition.csv', index_col=0)
    df_cf = pd.read_csv(wind_dir + 'Cluster Capacity Factors.csv', index_col=0)
    df_cf = utils.realign_timezone(df_cf, from_utc_offset=-4) # TODO this was a temp bug fix
    df_spur_cost = pd.read_csv(wind_dir + 'Cluster Spur Costs.csv', index_col=0)

    ## Get cost data for each class of turbine T1-3
    wind_config = config.gen_techs_by_code['wind_onshore']
    invest_metric = config.atb.cost_invest_metric  # which ATB metric to use for cost invest

    # Calculating weighted ATB data for each cluster
    class_data = {'t1': dict(), 't2': dict(), 't3': dict()}
    for wind_class, class_dict in class_data.items():

        tech_config = wind_config.model_copy(update={
            'atb_display_name': config.new_wind_techs[wind_class],
            'code': f"wind_onshore_{wind_class}",  # atb_data method uses caching on this code
        })

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
        df_invest[cluster] += df_spur_cost.loc[cluster, 'WeightedAvgSpur (USD/MW)'] # note this is actually in /kW, just a typo

        df_fixed[cluster] = sum([class_data[t]['cost_fixed'].astype(float) * comp[f"Fraction {t.upper()}"] for t in class_data.keys()])

        df_cf_index[cluster] = sum([class_data[t]['capacity_factor'].astype(float) * comp[f"Fraction {t.upper()}"] for t in class_data.keys()])
        df_cf_index[cluster] = df_cf_index[cluster] / df_cf_index[cluster]['2030'] # index to ATB wind base year, 2030

    # Convert cost denominator units
    df_invest *= config.units.loc['cost_invest', 'atb_conv_fact']
    df_fixed *= config.units.loc['cost_fixed', 'atb_conv_fact']

    # Convert currency
    df_invest = conv_curr(df_invest, config.atb.currency_year, config.atb.currency)
    df_fixed = conv_curr(df_fixed, config.atb.currency_year, config.atb.currency)

    # Sort by LCOE, then take top n clusters where n = n_bins in generator techs csv
    l = df_rtv.iloc[0]['life']
    i = config.global_discount_rate
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
        for cluster in _df_rtv.index: _df_cf[str(cluster)] *= df_cf_index.loc[str(utils.data_year(vint)), cluster]

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

    input_comm = config.commodities.loc[wind_config.in_comm]
    output_comm = config.commodities.loc[wind_config.out_comm]


    ## MaxCapacity
    _lc_note = f"Wind characterisation work done by Sutubra. Grid cells binned by ascending LCOE."
    lc_rows = []
    for cluster, rt in df_rt.iterrows():
        for period in config.model_periods:
            max_cap = rt['max_cap'] / 1000 # TODO MW vs GW
            lc_rows.append(LimitCapacity(
                region=rt['region'], period=period, tech_or_group=rt['tech'],
                operator='le', capacity=max_cap,
                units=f"({config.units.loc['capacity','units']})",
                notes=_lc_note, data_source=sutubra_ref.id,
                dq_cred=1, dq_geog=1, dq_struc=1, dq_tech=1, dq_time=3,
                data_id=utils.data_id(rt['region']),
            ))
    if lc_rows:
        curs.executemany(*LimitCapacity.bulk_insert_or_ignore_sql(lc_rows, include_nulls=True))

    # Indexed by region, tech, and vintage
    for cluster, rtv in df_rtv.iterrows():

        data_year = utils.data_year(rtv['vint'])

        ## Efficiency
        curs.executemany(*Efficiency.bulk_insert_or_ignore_sql([Efficiency(
            region=rtv['region'], input_comm=input_comm['commodity'],
            tech=rtv['tech'], vintage=rtv['vint'], output_comm=output_comm['commodity'],
            efficiency=1,
            notes=f"({input_comm['units']}/{output_comm['units']}) dummy input so arbitrary",
            data_id=utils.data_id(rtv['region']),
        )]))

        ## CostInvest
        note = (
            f"{invest_note} - {data_year} (NREL, {atb_year}) weighted by capacity shares of turbine class "
            f"plus estimated spur line cost from existing transmissions lines. "
        )
        ci = df_invest.loc[str(data_year), cluster]
        curs.executemany(*CostInvest.bulk_insert_or_ignore_sql([CostInvest(
            region=rtv['region'], tech=rtv['tech'], vintage=rtv['vint'],
            cost=ci, units=f"({config.units.loc['cost_invest', 'units']})",
            notes=note, data_source=combo_ref.id, dq_cred=1,
            data_id=utils.data_id(rtv['region']),
        )]))

        ## CapacityFactorProcess (no period in v4)
        note = (
            f"Wind characterisation work done by Sutubra. Grid cells binned by ascending LCOE. "
            f"Capacity factors further indexed to those in NREL ATB, by construction year with 2030 as base year. "
            f"Bounded to <= 1."
        )

        cf: pd.Series = df_cf[str(cluster)] * df_cf_index.loc[str(data_year), cluster]
        cf = cf.clip(0, 1)
        cf[cf < config.cf_tolerance] = 0
        tod_0 = config.time.iloc[0]['tod']

        cf_rows = []
        for h, time in config.time.iterrows():
            if time['tod'] == tod_0:
                cf_rows.append(CapacityFactorProcess(
                    region=rtv['region'], season=time['season'], tod=time['tod'],
                    tech=rtv['tech'], vintage=rtv['vint'], factor=cf.iloc[h],
                    notes=note, data_source=sutubra_ref.id,
                    dq_cred=1, dq_geog=1, dq_struc=1, dq_tech=1, dq_time=3,
                    data_id=utils.data_id(rtv['region']),
                ))
            else:
                cf_rows.append(CapacityFactorProcess(
                    region=rtv['region'], season=time['season'], tod=time['tod'],
                    tech=rtv['tech'], vintage=rtv['vint'], factor=cf.iloc[h],
                    data_id=utils.data_id(rtv['region']),
                ))
        if cf_rows:
            curs.executemany(*CapacityFactorProcess.bulk_insert_or_ignore_sql(cf_rows, include_nulls=True))

        ## CostFixed
        note = f"NREL ATB {rtv['vint']} Fixed O&M (NREL, {atb_year}) weighted by capacity shares of turbine class."
        cf_fixed_rows = []
        for period in config.model_periods:

            if rtv['vint'] > period or rtv['vint'] + rtv['life'] <= period: continue

            cf_fixed = df_fixed.loc[str(data_year), cluster]
            cf_fixed_rows.append(CostFixed(
                region=rtv['region'], period=period, tech=rtv['tech'], vintage=rtv['vint'],
                cost=cf_fixed, units=f"({config.units.loc['cost_fixed', 'units']})",
                notes=note, data_source=combo_ref.id, dq_cred=1,
                data_id=utils.data_id(rtv['region']),
            ))
        if cf_fixed_rows:
            curs.executemany(*CostFixed.bulk_insert_or_ignore_sql(cf_fixed_rows, include_nulls=True))


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

    # solar_dir = os.path.realpath(os.path.dirname(__name__)) + f"/provincial_data/{region}/new_solar/"
    solar_dir = os.path.realpath(os.path.dirname(__name__)) + f"/provincial_data/on/new_solar/" # TODO other provinces

    df_bins = pd.read_csv(solar_dir + 'Solar Resource Summary.csv', index_col=False).astype(float)
    
    # Sort solar bins by configured metric
    sort_by = config.sutubra_vre.sort_solar_by
    if sort_by == 'lcoe': df_bins = df_bins.sort_values('LCOE with Spur', ascending=True)
    elif sort_by == 'cf': df_bins = df_bins.sort_values('Capacity Factor', ascending=True)

    df_bins = df_bins.iloc[0:df_rtv['bin'].max()+1] # only need n grid cells, not all 5000
    df_bins.index = df_bins.index.map(lambda idx: f"({df_bins.loc[idx, 'x']}, {df_bins.loc[idx, 'y']})") # turn coordinates into string index

    df_cf = pd.read_csv(solar_dir + 'Hourly PV Capacity Factors.csv', index_col=0)
    df_cf = utils.realign_timezone(df_cf, from_utc_offset=-4)

    df_rtv.index = df_rtv['bin'].map(lambda bin: df_bins.index[bin]) # assign cluster to all vints of each bin
    df_rtv.index.name = 'cluster'
    df_rtv['max_cap'] = df_rtv.index.map(lambda cluster: df_bins.loc[cluster, 'Max Capacity (MW)'])
    
    solar_config = config.gen_techs_by_code['solar']
    invest_metric = config.atb.cost_invest_metric  # which ATB metric to use for cost invest

    ## Get ATB projections for each bin
    df_invest, invest_note = utils.atb_data(solar_config, core_metric_parameter=invest_metric)
    df_fixed, fixed_note = utils.atb_data(solar_config, core_metric_parameter='Fixed O&M')
    cf_index, cf_note = utils.atb_data(solar_config, core_metric_parameter='CF')

    df_invest = df_invest.set_index('core_metric_variable')['value'].astype(float)
    df_fixed = df_fixed.set_index('core_metric_variable')['value'].astype(float)
    cf_index = cf_index.set_index('core_metric_variable')['value'].astype(float)
    cf_index /= cf_index['2022'] # index to base year for solar, 2022

    # Convert cost denominator units
    df_invest *= config.units.loc['cost_invest', 'atb_conv_fact']
    df_fixed *= config.units.loc['cost_fixed', 'atb_conv_fact']

    # Convert currency
    df_invest = conv_curr(df_invest, config.atb.currency_year, config.atb.currency)
    df_fixed = conv_curr(df_fixed, config.atb.currency_year, config.atb.currency)
    
    # Aggregate capacity credits based on projected capacity factor
    for vint in df_rtv['vint'].unique():

        # Get bins for this vintage
        _df_rtv = df_rtv.loc[df_rtv['vint'] == vint].copy()

        # Index capacity factor to ATB projections
        _df_cf = df_cf.copy()
        for cluster in _df_rtv.index: _df_cf[str(cluster)] *= cf_index[str(utils.data_year(vint))]

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

    input_comm = config.commodities.loc[solar_config.in_comm]
    output_comm = config.commodities.loc[solar_config.out_comm]

    deg_rate = config.solar_degradation.rate
    deg_ref = config.solar_degradation.reference
    cf_note = (
        f"Wind characterisation work done by Sutubra. Grid cells binned by ascending LCOE. "
        f"Capacity factors further indexed to those in NREL ATB, by construction year with 2030 as base year. "
        f"Bounded to <= 1. Finally, assume {deg_rate*100:.2f}% degradation per year."
    )
    cf_ref = config.refs.add("solar_cf", f"{sutubra_ref.citation}; {deg_ref}")


    ## MaxCapacity
    _lc_note = f"Solar characterisation work done by Sutubra. Grid cells sorted by ascending LCOE."
    lc_rows = []
    for cluster, rt in df_rt.iterrows():
        for period in config.model_periods:
            max_cap = rt['max_cap'] / 1000 # TODO MW vs GW
            lc_rows.append(LimitCapacity(
                region=rt['region'], period=period, tech_or_group=rt['tech'],
                operator='le', capacity=max_cap,
                units=f"({config.units.loc['capacity','units']})",
                notes=_lc_note, data_source=sutubra_ref.id,
                dq_cred=1, dq_geog=1, dq_struc=1, dq_tech=1, dq_time=3,
                data_id=utils.data_id(rt['region']),
            ))
    if lc_rows:
        curs.executemany(*LimitCapacity.bulk_insert_or_ignore_sql(lc_rows, include_nulls=True))

    # Indexed by region, tech, and vintage
    for cluster, rtv in df_rtv.iterrows():

        data_year = utils.data_year(rtv['vint'])
        bin_config = df_bins.loc[rtv.name]

        ## Efficiency
        curs.executemany(*Efficiency.bulk_insert_or_ignore_sql([Efficiency(
            region=rtv['region'], input_comm=input_comm['commodity'],
            tech=rtv['tech'], vintage=rtv['vint'], output_comm=output_comm['commodity'],
            efficiency=1,
            notes=f"({input_comm['units']}/{output_comm['units']}) dummy input so arbitrary",
            data_id=utils.data_id(rtv['region']),
        )]))

        ## CostInvest
        note = (
            f"{invest_note} - {data_year}. "
            f"Plus estimated spur line cost from existing transmissions lines. "
        )
        cost_invest = df_invest[str(data_year)] + bin_config['Interconnection Cost ($/kW)']
        cost_invest = conv_curr(cost_invest, config.atb.currency_year, config.atb.currency)
        curs.executemany(*CostInvest.bulk_insert_or_ignore_sql([CostInvest(
            region=rtv['region'], tech=rtv['tech'], vintage=rtv['vint'],
            cost=cost_invest, units=f"({config.units.loc['cost_invest', 'units']})",
            notes=note, data_source=combo_ref.id, dq_cred=1,
            data_id=utils.data_id(rtv['region']),
        )]))

        ## CapacityFactorProcess (no period in v4; use vintage-year CF, degradation not applied)
        cf: pd.Series = df_cf[str(cluster)] * cf_index[str(data_year)]
        cf = cf.clip(0, 1)
        cf[cf < config.cf_tolerance] = 0
        tod_0 = config.time.iloc[0]['tod']

        cf_rows = []
        for h, time in config.time.iterrows():
            _cf = cf.iloc[h]
            if time['tod'] == tod_0:
                cf_rows.append(CapacityFactorProcess(
                    region=rtv['region'], season=time['season'], tod=time['tod'],
                    tech=rtv['tech'], vintage=rtv['vint'], factor=_cf,
                    notes=cf_note, data_source=cf_ref.id,
                    dq_cred=1, dq_geog=1, dq_struc=1, dq_tech=1, dq_time=3,
                    data_id=utils.data_id(rtv['region']),
                ))
            else:
                cf_rows.append(CapacityFactorProcess(
                    region=rtv['region'], season=time['season'], tod=time['tod'],
                    tech=rtv['tech'], vintage=rtv['vint'], factor=_cf,
                    data_id=utils.data_id(rtv['region']),
                ))
        if cf_rows:
            curs.executemany(*CapacityFactorProcess.bulk_insert_or_ignore_sql(cf_rows, include_nulls=True))

        ## CostFixed
        fixed_note += f" - {data_year}"
        cf_fixed_rows = []
        for period in config.model_periods:

            if rtv['vint'] > period or rtv['vint'] + rtv['life'] <= period: continue

            cost_fixed = df_fixed[str(data_year)]
            cost_fixed = conv_curr(cost_fixed, config.atb.currency_year, config.atb.currency)
            cf_fixed_rows.append(CostFixed(
                region=rtv['region'], period=period, tech=rtv['tech'], vintage=rtv['vint'],
                cost=cost_fixed, units=f"({config.units.loc['cost_fixed', 'units']})",
                notes=fixed_note, data_source=atb_ref.id, dq_cred=1,
                data_id=utils.data_id(rtv['region']),
            ))
        if cf_fixed_rows:
            curs.executemany(*CostFixed.bulk_insert_or_ignore_sql(cf_fixed_rows, include_nulls=True))


    conn.commit()
    conn.close()

    print(f"{region} new solar capacity data aggregated into {os.path.basename(config.database_file)}")