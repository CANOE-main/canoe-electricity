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
import tools
from pull_config import params, translator



data_year = params['default_data_year']

this_dir = os.path.realpath(os.path.dirname(__file__)) + "/"
coders_db = this_dir + "coders_db.sqlite"
ieso_data = this_dir + "ieso_data/"
batch_file = this_dir + "input_files/batched_new_capacity.xlsx"
cc_file = ieso_data + 'capacity_credits.csv'
# TODO ref
reference = "1. Frew, B., Cole, W., Sun, Y., Richards, J. & Mai, T. 8760-Based Method for Representing Variable Generation Capacity Value in Capacity Expansion Models: Preprint."



batched_cap = pd.read_excel(batch_file, sheet_name="ON", index_col=0, skiprows=2)

vres = ['WIND_ONSHORE','SOLAR_PV']
cfs = ieso_cf.get_capacity_factors() # gets hydro daily as 365 days
cfs.update({'HYDRO_DLY':pd.read_csv(ieso_data + 'hydro_dly_cf_8760.csv',index_col=0,header=0)['0']})

intertie_flow = tools.get_file(f"http://reports.ieso.ca/public/IntertieScheduleFlowYear/PUB_IntertieScheduleFlowYear_{data_year}.csv", index_col=False, skiprows=4, nrows=8760)
demand = tools.get_file(f"http://reports.ieso.ca/public/Demand/PUB_Demand_{data_year}.csv", index_col=False, skiprows=3, nrows=8760).rename(columns={'Ontario Demand': 'load'})
demand['load'] += intertie_flow['Exp.14'] - intertie_flow['Imp.14']
demand['net_load'] = demand['load'].copy()

capacity_mw = dict()
production_mwh = dict()
for vre in vres:
    capacity_mw.update({vre: ieso_cf.get_total_capacity(vre)*1000})
    production_mwh.update({vre: cfs[vre] * capacity_mw[vre]})
    demand['net_load'] -= production_mwh[vre]



def get_capacity_credit(vre, new_mw=0, mw_step=1000):

    # Net load without this VRE generation
    if new_mw == 0: load = demand['net_load'].copy() + cfs[vre]*capacity_mw[vre]
    else: load = demand['net_load'].copy() - cfs[vre]*(new_mw - mw_step)
    ldc = load.sort_values(ascending=False)

    # Net load with this VRE generation
    net_load = demand['net_load'].copy() - cfs[vre]*new_mw
    nldc = net_load.sort_values(ascending=False)

    if (new_mw == 0):
        pp.figure(vre)
        pp.plot(range(8760),ldc,label="LDC")
        pp.plot(range(8760),nldc,label="NLDC")

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

    pp.figure()
    pp.plot(new_mws, ccs, label='LDC marginal 100H')
    mean_cf = np.mean(cfs[vre])
    pp.plot([0,new_mw_max],[mean_cf,mean_cf],'k-', label='Annual CF')
    pp.legend(loc=1)
    pp.title(vre)

    return ccs



# Write capacity credits to CODERS database
def write_to_coders_db(ccs_vres):

    conn = sqlite3.connect(coders_db)
    curs = conn.cursor()
    
    for vre in vres:
        base_tech = translator['generator_types'][vre]['CANOE_tech']
        ccs = ccs_vres[vre]

        for i in range(len(ccs)):

            cc = ccs[i]
            if cc is None: break

            tech = f"{base_tech}-NEW-{i}" if i > 0 else base_tech
            print(tech)

            curs.execute(f"""
                         UPDATE CapacityCredit
                         SET
                          cf_tech={cc},
                          cf_tech_notes='LDC - NLDC top 100 hours from IESO public data [{reference}]'
                         WHERE
                          regions=='ON' and tech=='{tech}'
                        """)
    
    conn.commit()
    conn.close()
        


ccs_vres = dict()
max_n = max(batched_cap['batches'])
for vre in vres:

    n_batches = batched_cap.loc[vre, 'batches']
    mw_steps = [0, *batched_cap.loc[vre, 1:n_batches].tolist()]

    # Have to pad smaller lists to build the dataframe
    ccs = [*get_cc_curve(vre, mw_steps), *[None for n in range(max_n - n_batches)]]
    ccs_vres.update({vre: ccs})

df = pd.DataFrame.from_dict(ccs_vres)
print(df.head(max_n+1))
df.to_csv(cc_file)

write_to_coders_db(ccs_vres)

pp.show()