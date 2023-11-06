"""
Calculates capacity credits from IESO demand data
and calculated 8760 capacity factor data
Written by Ian David Elder for the CANOE model
"""

import pandas as pd
import numpy as np
import ieso_capacity_factors as ieso_cf
import matplotlib.pyplot as pp
import sqlite3
import os
import utils
from setup import config

params = config.params
batched_cap = config.batched_cap["ON"]
translator = config.translator


data_year = params['default_data_year']

this_dir = os.path.realpath(os.path.dirname(__file__)) + "/"
coders_db = this_dir + "coders_db.sqlite"
ieso_data = this_dir + "ieso_data/"
cc_file = ieso_data + 'capacity_credits.csv'

_show_plots = False



# Initialise vres and their capacity factors
vres = ['WIND_ONSHORE','SOLAR_PV','HYDRO_RUN']
cfs = ieso_cf.get_capacity_factors() # gets hydro daily as 365 days
cfs['HYDRO_DLY'] = pd.read_csv(ieso_data + 'hydro_dly_cf_8760.csv',index_col=0,header=0)['0']



# Get Ontario demand and initialise net load
demand = utils.get_data(f"http://reports.ieso.ca/public/Demand/PUB_Demand_{data_year}.csv", index_col=False, skiprows=3, nrows=8760).rename(columns={'Market Demand': 'load'})
demand['net_load'] = demand['load'].copy()

capacity_mw = dict()
for vre in vres:
    capacity_mw[vre] = ieso_cf.get_database_capacity_gw(vre)*1000
    production_mwh = cfs[vre] * capacity_mw[vre]
    demand['net_load'] -= production_mwh



def get_capacity_credit(vre, new_mw=0, mw_step=1000):

    # Net load without this VRE generation
    if new_mw == 0: load = demand['net_load'].copy() + cfs[vre]*capacity_mw[vre]
    else: load = demand['net_load'].copy() - cfs[vre]*(new_mw - mw_step)
    ldc = load.sort_values(ascending=False)

    # Net load with this VRE generation
    net_load = demand['net_load'].copy() - cfs[vre]*new_mw
    nldc = net_load.sort_values(ascending=False)

    # plot existing and first new batch
    if (new_mw == mw_step and _show_plots):
        pp.figure(vre + "LDC - NLDC")
        pp.plot(range(8760),ldc,label="LDC")
        pp.plot(range(8760),nldc,label="NLDC")
        pp.xlabel("Hour")
        pp.ylabel("Load / net load MW")
        pp.title(vre + f" LDC vs. NLDC existing and first {mw_step} new MW")

    # LDC - NLDC top 100 hours
    cv = np.mean(ldc[0:100] - nldc[0:100])
    marg_cap = capacity_mw[vre] if new_mw == 0 else mw_step

    # Divided by capacity for cc
    cc = cv/marg_cap # capacity in GW in database

    return cc



def get_cc_curve(vre, mw_steps):

    ccs = list()

    new_mw = 0
    new_mws = list()
    new_mw_max = sum(mw_steps)

    for i in range(len(mw_steps)):
        new_mw += mw_steps[i]
        new_mws.append(new_mw)
        ccs.append(get_capacity_credit(vre=vre, new_mw=new_mw, mw_step=mw_steps[i]))

    if _show_plots:
        pp.figure(vre + " CC")
        pp.plot(new_mws, ccs, label='LDC marginal 100H')
        mean_cf = np.mean(cfs[vre])
        pp.plot([0,new_mw_max],[mean_cf,mean_cf],'k-', label='Annual CF')
        pp.legend(loc=1)
        pp.xlabel("New MW capacity")
        pp.ylabel("Capacity credit")
        pp.title(vre + " marginal capacity credit")

    return ccs



def get_capacity_credits():

    # Capacity credit curves per VRE
    ccs_vres = dict()

    # Largest row count (to match column lengths)
    max_n = max([int(translator['technologies'][translator['generator_types'][vre]['CANOE_tech']]['new_cap_steps']) for vre in vres])

    for vre in vres:

        if vre not in batched_cap.index:
            print(f"Tried to get capacity credits for {vre} but no batches specified in input files.")
            continue

        n_batches = int(translator['technologies'][translator['generator_types'][vre]['CANOE_tech']]['new_cap_steps'])
        mw_steps = [0, *batched_cap.loc[vre, 1:n_batches].tolist()]

        # Have to pad smaller lists to match column lengths to build the dataframe
        ccs = [*get_cc_curve(vre, mw_steps), *[None for n in range(max_n - n_batches)]]

        ccs_vres[vre] = ccs

    # Print out the capacity credits and write to csv file
    df = pd.DataFrame.from_dict(ccs_vres)
    print('IESO VRE capacity credits:')
    print(df.head(max_n+1))
    df.to_csv(cc_file)

    if _show_plots: pp.show()

    return ccs_vres



# Write capacity credits to CODERS database
def write_to_coders_db(show_plots=False):
    
    global _show_plots
    _show_plots = show_plots

    ccs_vres = get_capacity_credits()

    conn = sqlite3.connect(coders_db)
    curs = conn.cursor()

    note = params['capacity_credit_note']
    reference = params['ieso_reference'].replace('<year>',data_year)

    curs.execute(f"""REPLACE INTO
                 'references'('reference')
                 VALUES('{reference}')""")
    
    for vre in vres:

        if vre not in ccs_vres.keys(): continue # Occurs when no batches specified in input files

        base_tech = translator['generator_types'][vre]['CANOE_tech']
        ccs = ccs_vres[vre]

        # Get all variants of this vre tech
        techs = [tech[0] for tech in curs.execute(f"SELECT tech FROM technologies WHERE tech like '%{base_tech}%'").fetchall()]
        
        for tech in techs:
            
            # Get period-vintage pairs for this variant
            vints = [v[0] for v in curs.execute(f"SELECT vintage FROM Efficiency WHERE tech == '{tech}'").fetchall()]
            life = curs.execute(f"SELECT life FROM LifetimeTech WHERE tech == '{tech}'").fetchone()[0]

            for vint in vints:
                for period in config.model_periods:

                    if vint > period or vint + life <= period: continue

                    ending = tech.split("-")[-1]
                    if ending == 'EXS': ending = 0
                    if ending == 'NEW': ending = 1

                    cc = ccs[int(ending)]

                    curs.execute(f"""REPLACE INTO
                                    CapacityCredit(regions, periods, tech, vintage, cf_tech, cf_tech_notes, reference)
                                    VALUES("ON", {period}, '{tech}', {vint}, {cc}, '{note}', '{reference}')""")
                    

                    if tech in config.generic_techs.keys():
                        # Use tech descriptions if running this in chain after coders_pull.py where techs are updated
                        curs.execute(f"""REPLACE INTO
                                    tech_reserve(tech, notes)
                                    VALUES('{tech}', '{config.generic_techs[tech]['description']}')""")
                    else:
                        # Otherwise dont override descriptions in database
                        curs.execute(f"""INSERT OR IGNORE INTO
                                    tech_reserve(tech)
                                    VALUES('{tech}')""")

    conn.commit()
    conn.close()