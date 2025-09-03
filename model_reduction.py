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

    # Maps all coders existing storage types to canoe techs
    existing_map = dict()
    for tech_code, row in config.gen_techs.iterrows():
        if pd.isna(row['coders_existing']): continue
        for coders_equiv in row['coders_existing'].split("+"):
            existing_map[coders_equiv] = tech_code

    ## Get annual capacity factors for each type of generator for each region
    # Existing generators indexed by tech
    df_existing, date_accessed = coders_api.get_data(end_point='generators')
    df_existing['tech'] = df_existing['gen_type'].str.lower().map(existing_map)
    df_existing['region'] = df_existing['operating_region'].str.lower().map(config.region_map)
    df_existing.set_index('tech', inplace=True)

    for region in config.model_regions:

        df_exs = df_existing.loc[df_existing['region'] == region]

        # Annual capacity factors of existing technologies in this region averaged over existing capacities
        df_acf = (df_exs['capacity_factor_in_%'] * df_exs['install_capacity_in_mw']).groupby('tech').sum()
        df_cap = df_exs.groupby('tech')['install_capacity_in_mw'].sum()
        df_acf = df_acf.divide(df_cap.loc[df_cap>0])

        # Some manual additions
        if 'ng_ccs' not in df_acf.index and 'ng_cc' in df_acf.index: df_acf.loc['ng_ccs'] = df_acf.loc['ng_cc']
        df_acf.loc['nuclear_smr'] = 0.86 # from CODERS

        df_acf.index = [config.gen_techs.loc[tech_code, 'base_tech'] for tech_code in df_acf.index]

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
    curs.execute(f"INSERT OR IGNORE INTO time_periods(t_periods, flag) VALUES({config.model_periods[0]-1}, 'e')") # Needs one existing period apparently
    curs.execute(f"DELETE FROM time_season")
    curs.execute(f"DELETE FROM tod")
    curs.execute(f"DELETE FROM SegFrac")
    curs.execute(f"INSERT OR IGNORE INTO time_season(t_season) VALUES('S01')")
    curs.execute(f"INSERT OR IGNORE INTO tod(t_day) VALUES('D01')")
    curs.execute(f"INSERT OR IGNORE INTO SegFrac(season_name, tod_name, segfrac) VALUES('S01', 'D01', 1)")
            
    # Remove unused commodities
    curs.execute(f"DELETE FROM commodities WHERE comm_name == 'CO2eq'")
    curs.execute(f"DELETE FROM commodities WHERE comm_name like '%ELC%'")
    curs.execute(f"INSERT INTO commodities(comm_name, flag, comm_desc) VALUES('elc', 'p', 'electricity')")
    curs.execute(f"UPDATE Efficiency SET input_comm == 'elc' WHERE input_comm LIKE '%ELC%'")
    curs.execute(f"UPDATE Efficiency SET output_comm == 'elc' WHERE output_comm LIKE '%ELC%'")

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
        
        # Change -NEW techs to base techs
        for tech in techs:
            curs.execute(f"UPDATE {table} SET tech = '{tech.split('-NEW')[0]}' WHERE tech == '{tech}'")
        
        curs.execute(f"DELETE FROM {table} WHERE tech like '%-NEW%'")


    conn.commit()
    conn.close()



if __name__ == "__main__":

    simplify_model()