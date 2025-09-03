"""
Aggregates capacity credits except for new wind and solar
Written by Ian David Elder for the CANOE model
"""

import pandas as pd
from setup import config
from matplotlib import pyplot as pp
import utils
import numpy as np
import sqlite3

# Provincial scripts
import provincial_data.on.existing_capacity_credits as on_cc_exs

exs_ccs = dict()


# Sends existing capacity to relevant provincial scripts
def aggregate_existing(df_rtv: pd.DataFrame):

    exs_ccs['ON'] = on_cc_exs.aggregate_capacity_credits(df_rtv) #.loc[df_rtv['region'] == 'ON']) # for now, using Ontario for all # use ontario existing capacity credits


# Aggregates new generators capacity credits
def aggregate_new(df_rtv: pd.DataFrame):

    # Most generators same as existing
    on_cc_exs.aggregate_capacity_credits(df_rtv) #.loc[df_rtv['region'] == 'ON']) # for now, using Ontario for all # use ontario existing capacity credits


# Aggregates new storage capacity credits
def aggregate_storage(df_rtv: pd.DataFrame):

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()

    # Temporary for now. CC = 1
    for _idx, rtv in df_rtv.iterrows():
        for period in config.model_periods:

            if rtv['vint'] > period or rtv['vint'] + rtv['life'] <= period: continue

            curs.execute(f"""REPLACE INTO
                        CapacityCredit(region, period, tech, vintage, credit, notes, dq_cred, data_id)
                        VALUES('{rtv['region']}', {period}, '{rtv['tech']}', {rtv['vint']}, 0.9,
                        'Assumed for now. Improved method on TODO list', 5, "{utils.data_id(rtv['region'])}")""")
            
    conn.commit()
    conn.close()



## Uses the NREL ReEDS method (LDC-NLDC) top 100h to calculate marginal capacity credits of VREs
def aggregate_vre(df_rtv: pd.DataFrame, df_cf: pd.DataFrame, region: str, vint: int):
    
    # Only show plots for first and last vintage, to show change
    plot = config.params['show_plots'] and vint in [config.model_periods[0], config.model_periods[-1]]

    tech_code = df_rtv.iloc[0]['tech_code'] # assume all are the same base tech

    # Group rtv by cluster to calculate CC of each cluster (i.e. ignoring vintage)
    df_clusters = df_rtv.groupby('cluster').first().sort_values('bin')

    # Get hourly generation from existing VREs to calculate prior net load
    exs_vre_gen = config.exs_vre_gen[region] * 1000 # GWh to MWh units here
    load = config.provincial_demand[region] # hourly load is provincial demand
    net_load = load - exs_vre_gen # first net load is demand minus hourly generation of existing VREs

    if plot:
        # Set up the capacity credit plot, hourly above and ldc/cc side-by-side below
        figure, axes = pp.subplot_mosaic([['hourly','hourly'], ['dc','cc']], figsize=(10, 8))
        figure.suptitle(f"{vint} {region} {tech_code} capacity credits\n"
                        "Demand load (blue) net load with existing capacity (green) marginal net load with new capacity (yellow-red)")
        pp.subplots_adjust(hspace=0.3, wspace=0.3, top=0.87, bottom=0.1, left=0.1, right=0.9)

        # Plot prior load and net load, and ldc/nldc
        axes['hourly'].set_title(f"marginal hourly net load")
        axes['hourly'].set_xlabel(f"hour of year")
        axes['hourly'].set_ylabel(f"load (MW)")
        axes['hourly'].plot(range(len(load)), load, color=(0, 0, 1, 0.5))
        axes['hourly'].plot(range(len(net_load)), net_load, color=(0, 1, 0, 0.5), zorder=-5)

        axes['dc'].set_title(f"marginal net load duration curve")
        axes['dc'].set_xlabel(f"sorted by hourly load (descending)")
        axes['dc'].set_ylabel(f"load (MW)")
        axes['dc'].plot(range(len(load)), np.sort(load)[::-1], color=(0, 0, 1, 1)) # original ldc
        axes['dc'].plot(range(len(net_load)), np.sort(net_load)[::-1], color=(0, 1, 0, 1)) # nldc after existing capacity

    ## Calculate each marginal capacity credit and add to plots
    green = 1 # Colour gradient from yellow to red by reducing green
    zorder = -5 # layering each marginal plot backward
    for cluster, rtv in df_clusters.iterrows():

        # Subtract generation from this cluster from previous net load to get next marginal net load and nldc
        marginal_net_load: np.ndarray = net_load - df_cf[str(cluster)].to_numpy() * rtv['max_cap'] # TODO unit conversions, timezone alignment
        marginal_nldc = np.sort(marginal_net_load)[::-1]

        # Capacity credit is mean of nldc reduction in top 100 hours (NREL ReEDS) divided by nameplate capacity
        cc = (np.sort(net_load)[::-1] - marginal_nldc)[0:100].mean() / rtv['max_cap']
        df_rtv.loc[cluster, 'cc'] = cc # save to each rtv set
        df_clusters.loc[cluster, 'cc'] = cc # and save to each cluster, just for plotting

        # Save this marginal net load for next loop
        net_load = marginal_net_load

        if plot:
            # Add to duration curve and hourly plots
            zorder -= 5
            green -= 1 / len(df_clusters.index) # reduce green linearly so yellow turns gradually to red
            axes['dc'].plot(range(len(marginal_nldc)), marginal_nldc, color=(1, green, 0, 1))
            axes['hourly'].plot(range(len(marginal_net_load)), marginal_net_load, color=(1, green, 0, 0.5), zorder=zorder)

    if plot:
        # Plot marginal capacity credits by VRE cluster
        axes['cc'].set_title(f"marginal capacity credit")
        axes['cc'].set_xlabel(f"new capacity bins")
        axes['cc'].set_ylabel(f"capacity credit (% capacity)")
        ccs = df_clusters['cc'].values.tolist()
        axes['cc'].plot(range(len(ccs)), ccs)
        # axes['cc'].plot(range(len(ccs)+1), [exs_ccs["ON"].loc[tech_code, 'cc'], *ccs]) # TODO regionalise when better data is found

    ## Write capacity credits to database
    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()

    note = (
        f"NREL ReEDS method (NREL, {config.params['capacity_credits']['year']}). "
        "Marginal net load duration curve reduction at top 100 hours. "
        "Assumed capacity bins are fully built out in order of LCOE, "
        "one type of renewable at a time, for now."
    )
    ref = config.refs.add('capacity_credits', config.params['capacity_credits']['reference'])

    for _idx, rtv in df_rtv.iterrows():
        for period in config.model_periods:

            if rtv['vint'] > period or rtv['vint'] + rtv['life'] <= period: continue

            curs.execute(f"""REPLACE INTO
                        CapacityCredit(region, period, tech, vintage, credit, notes,
                        data_source, dq_cred, dq_geog, dq_struc, dq_tech, dq_time, data_id)
                        VALUES('{rtv['region']}', {period}, '{rtv['tech']}', {rtv['vint']}, {rtv['cc']}, '{note}',
                        '{ref.id}', 3, 1, 3, 1, 3, "{utils.data_id(rtv['region'])}")""")

    conn.commit()
    conn.close()