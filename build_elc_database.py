"""
Builds the electricity sector database to be merged into the larger model
Written by Ian David Elder for the CANOE model
"""

import CODERS_pull # Runs on import... for now...
import ieso_vre_capacity_credits as ieso_vre_cc
import ieso_rel_capacity_credits as ieso_rel_cc
import ieso_capacity_factors as ieso_cf
import sqlite3
import utils
from setup import config

ieso_cf.write_to_coders_db()
ieso_vre_cc.write_to_coders_db(show_plots=False)
ieso_rel_cc.write_to_coders_db()

utils.DatabaseConverter().clone_sqlite_to_excel('coders_db.sqlite', 'electricity_generation.xlsx', excel_template_file='Template spreadsheet (make a copy).xlsx')

"""
##############################################################
    The following is setup for electricity sector testing
##############################################################
"""

conn = sqlite3.connect('coders_db.sqlite')
curs = conn.cursor()

data_year = 2020

demand = utils.get_data(f"http://reports.ieso.ca/public/Demand/PUB_Demand_{data_year}.csv", index_col=False, skiprows=3, nrows=8760).rename(columns={"Ontario Demand": "demand"})
mwh_to_pj = 3600/1E9
demand['demand'] = demand["demand"] * mwh_to_pj
total_demand = sum(demand['demand'])

pop_index = {
    2025: 1.0755,
    2030: 1.1465,
    2035: 1.2092,
    2040: 1.2641,
    2045: 1.3130,
    2050: 1.3579
}

for period in config.model_periods:
    curs.execute(f"""REPLACE INTO Demand(regions, periods, demand_comm, demand, demand_units)
                 VALUES("ON", {period}, 'D_ELC', {total_demand*pop_index[period]}, "PJ")""")

for h in range(8760):
    curs.execute(f"""REPLACE INTO DemandSpecificDistribution(regions, season_name, time_of_day_name, demand_name, dds)
                 VALUES("ON", '{config.seas_8760[h]}', '{config.tofd_8760[h]}', 'D_ELC', {demand['demand'][h]/total_demand})""")
    
curs.execute(f"""UPDATE Efficiency
                SET efficiency = 0.80
                WHERE tech like '%PMP%'""")
curs.execute(f"""UPDATE Efficiency
                SET efficiency = 0.90
                WHERE tech like '%BAT%'""")

days = ['D001','D009','D089','D103','D128','D173','D196']
curs.execute(f"DELETE FROM time_season")
[curs.execute(f"INSERT OR IGNORE INTO time_season(t_season) VALUES('{day}')") for day in days]

seas_tables = [
    'CapacityFactorTech',
    'DemandSpecificDistribution',
    'MinSeasonalActivity',
    'MaxSeasonalActivity'
    ]

for table in seas_tables:
    curs.execute(f"DELETE FROM {table} WHERE season_name NOT IN (SELECT t_season from time_season)")

total_dsd = sum([dsd[0] for dsd in curs.execute("SELECT dds FROM DemandSpecificDistribution").fetchall()])
curs.execute(f"""UPDATE DemandSpecificDistribution
             SET dds = dds / {total_dsd}""")

curs.execute(f"""REPLACE INTO commodities(comm_name, flag)
             VALUES('D_ELC', 'd')""")

for day in days:
    for h in range(24):
        curs.execute(f"""REPLACE INTO SegFrac(season_name, time_of_day_name, segfrac)
                    VALUES('{day}', '{config.tofd_8760[h]}', {1/(24*7)})""")

base_emis = 3200
emis = {
    2025: 1,
    2030: 0.8,
    2035: 0.6,
    2040: 0.4,
    2045: 0.2,
    2050: 0
}

for period in config.model_periods:
    curs.execute(f"""REPLACE INTO
                EmissionLimit(regions, periods, emis_comm, emis_limit, emis_limit_units)
                VALUES("ON", {period}, "CO2eq", {emis[period]*base_emis}, "ktCO2eq")""")

conn.commit()
conn.close()

print("Finished.")