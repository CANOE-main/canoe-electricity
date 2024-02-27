"""
Reduces residential sector from full resolution to simple version
Written by Ian David Elder for the CANOE model
"""

import sqlite3
from setup import config
import coders_api
import pandas as pd


def simplify_model():

    # Connect to the new database file
    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor() # Cursor object interacts with the sqlite db

    for region in config.model_regions:

        ## Get annual capacity factors for each type of generator for each region
        # Existing generators indexed by tech
        _existing_json, df_existing, date_accessed = coders_api.get_data(end_point='generators')
        df_existing['tech'] = df_existing['gen_type'].str.upper().map(config.tech_map)

        # Existing generators by tech for this region
        df_existing['region'] = df_existing['operating_region'].str.upper().map(config.region_map)
        df_existing.loc[df_existing['region'] == region]
        df_existing.set_index('tech', inplace=True)

        # Annual capacity factors of existing technologies in this region averaged over existing capacities
        df_acf = (df_existing['capacity_factor_in_%'] * df_existing['effective_capacity_in_mw']).groupby('tech').sum()
        df_cap = df_existing.groupby('tech')['effective_capacity_in_mw'].sum()
        df_acf = df_acf.divide(df_cap)
        df_acf.loc['E_BAT'] = 2/24 # one 2-hour storage cycle per day (NREL ATB)
        df_acf.loc['E_HYD_PMP'] = 6/24 # one 6-hour storage cycle per day
        df_acf.loc['E_NG_CCS'] = df_acf.loc['E_NG_CC']
        df_acf.loc['E_NUC_SMR'] = df_acf.loc['E_NUC']
        df_acf.loc['E_WND_OFF'] = df_acf.loc['E_WND_ON']

        tv_pairs = curs.execute(f"SELECT tech, vintage FROM Efficiency WHERE regions == '{region}'").fetchall()

        for tech, vint in tv_pairs:
            
            # Get basic parameters from full resolution model
            life = curs.execute(f"SELECT life FROM LifetimeTech WHERE regions == '{region}' AND tech like '{tech}%'").fetchone()
            if life is None: continue # Dummy tech
            else: life = life[0]

            c2a = curs.execute(f"SELECT c2a FROM CapacityToActivity WHERE regions == '{region}' AND tech like '{tech}%'").fetchone()[0]
            acf = df_acf.loc[tech.split('-')[0]]
            
            # Need to know annual activity to calculate levelised cost of activity
            annual_act = c2a * acf
            
            # Amortise capital cost over the lifetime of the technology using global discount rate
            cost_invest = curs.execute(f"SELECT cost_invest FROM CostInvest WHERE regions == '{region}' AND tech like '{tech}%' AND vintage == {vint}").fetchone()
            cost_invest = cost_invest[0] if cost_invest is not None else 0
            i = config.params['global_discount_rate']
            annuity = cost_invest * i * (1+i)**life / ((1+i)**life - 1)

            # Get fixed cost from table
            cost_fixed = curs.execute(f"SELECT cost_fixed FROM CostFixed WHERE regions == '{region}' AND tech like '{tech}%' and vintage == {vint}").fetchone()
            cost_fixed = cost_fixed[0] if cost_fixed is not None else 0

            # Get fixed cost from table
            cost_variable = curs.execute(f"SELECT cost_variable FROM CostVariable WHERE regions == '{region}' AND tech like '{tech}%' and vintage == {vint}").fetchone()
            cost_variable = cost_variable[0] if cost_variable is not None else 0

            # Levelised cost of activity is variable cost plus annual fixed O&M plus annualised capital cost divided by annual activity
            lcoa = cost_variable + (cost_fixed + annuity) / annual_act
            
            if lcoa == 0: continue # No associated cost

            # Add LCOA as a variable cost
            for period in config.model_periods:
                if vint > period or vint + life <= period: continue

                curs.execute(f"""REPLACE INTO
                            CostVariable(regions, periods, tech, vintage, cost_variable, cost_variable_units, cost_variable_notes)
                                VALUES('{region}', {period}, '{tech}', {vint}, {lcoa}, 'MCAD2020', 'Levelised cost of activity based on average annual capacity factor of existing capacity')""")
    

    # Only one time slice per year: S01, D01
    curs.execute(f"DELETE FROM time_periods WHERE flag == 'e'")
    curs.execute(f"DELETE FROM time_season")
    curs.execute(f"DELETE FROM time_of_day")
    curs.execute(f"DELETE FROM SegFrac")
    curs.execute(f"INSERT OR IGNORE INTO time_season(t_season) VALUES('S01')")
    curs.execute(f"INSERT OR IGNORE INTO time_of_day(t_day) VALUES('D01')")
    curs.execute(f"INSERT OR IGNORE INTO SegFrac(season_name, time_of_day_name, segfrac) VALUES('S01', 'D01', 1)")
            
    # Remove unused commodities
    curs.execute(f"DELETE FROM commodities WHERE comm_name == 'CO2eq'")
    curs.execute(f"DELETE FROM commodities WHERE comm_name like '%ELC%'")
    curs.execute(f"INSERT INTO commodities(comm_name, flag, comm_desc) VALUES('ELC', 'p', 'electricity')")
    curs.execute(f"UPDATE Efficiency SET input_comm == 'ELC' WHERE input_comm LIKE '%ELC%'")
    curs.execute(f"UPDATE Efficiency SET output_comm == 'ELC' WHERE output_comm LIKE '%ELC%'")

    # Clear unnecessary data
    curs.execute(f"DELETE FROM tech_curtailment")
    curs.execute(f"DELETE FROM tech_ramping")
    curs.execute(f"DELETE FROM CostFixed")
    curs.execute(f"DELETE FROM CostInvest")
    curs.execute(f"DELETE FROM RampDown")
    curs.execute(f"DELETE FROM RampUp")
    curs.execute(f"DELETE FROM CapacityToActivity")
    curs.execute(f"DELETE FROM CapacityFactorTech")
    curs.execute(f"DELETE FROM MinSeasonalActivity")
    curs.execute(f"DELETE FROM MaxSeasonalActivity")
    curs.execute(f"DELETE FROM MaxCapacity")
    curs.execute(f"DELETE FROM EmissionActivity")
    curs.execute(f"DELETE FROM ExistingCapacity")

    # Clear some tech variants
    techs = [t[0] for t in curs.execute(f"""SELECT tech FROM technologies
                                             WHERE tech LIKE '%-%H-NEW'
                                             OR tech LIKE '%-NEW'
                                             OR tech LIKE '%-NEW-1'""").fetchall()]

    for table in ['CostVariable', 'Efficiency', 'LifetimeTech', 'technologies', 'StorageDuration']:

        # Remove existing capacity
        curs.execute(f"DELETE FROM {table} WHERE tech like '%-EXS'")
        
        for tech in techs:
            print(f"UPDATE {table} SET tech = '{tech.split('-NEW')[0]}' WHERE tech == '{tech}'")
            curs.execute(f"UPDATE {table} SET tech = '{tech.split('-NEW')[0]}' WHERE tech == '{tech}'")
        
        curs.execute(f"DELETE FROM {table} WHERE tech like '%-NEW%'")


    conn.commit()
    conn.close()



if __name__ == "__main__":

    simplify_model()