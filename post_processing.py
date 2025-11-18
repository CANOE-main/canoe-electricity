"""
Performs some final post-processing on aggregated data
Written by Ian David Elder for the CANOE model
"""

import sqlite3
from setup import config
import pandas as pd
import utils



def process():

    if config.params['include_imports']: aggregate_imports()
    if config.params['include_capacity_limits']: aggregate_capacity_limits()

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()


    """
    ##############################################################
        Add any used commodities
    ##############################################################
    """

    # First get all the used commodities from the Efficiency and EmissionActivity tables
    eff = curs.execute("SELECT input_comm, output_comm FROM Efficiency").fetchall()
    emis = curs.execute("SELECT emis_comm FROM EmissionActivity").fetchall()

    used_comms = set()
    for io in eff:
        used_comms.add(io[0])
        used_comms.add(io[1])
    for e in emis: used_comms.add(e[0])

    # Add any used comms to the commodities table
    for code, comm in config.commodities.iterrows():
        if comm['commodity'] in used_comms:
            curs.execute(
                f"""REPLACE INTO
                Commodity(name, flag, description, data_id)
                VALUES('{comm['commodity']}', '{comm['flag']}', '({comm['units']}) {comm['description']}', "{utils.data_id()}")"""
            )
        

    """
    ##############################################################
        Unused techs
    ##############################################################
    """

    used_techs = [t[0] for t in curs.execute("SELECT tech FROM Efficiency")]
    all_techs = [t[0] for t in curs.execute("SELECT tech FROM Technology")]
    all_tables = [t[0] for t in curs.execute("SELECT name FROM sqlite_master WHERE type='table';")]

    for tech in all_techs:
        if tech not in used_techs:

            print(f"Not using technology {tech} so it was removed.")

            for table in all_tables:
                cols = [row[1] for row in curs.execute(f"PRAGMA table_info({table})").fetchall()]
                if "tech" in cols:
                    curs.execute(f"DELETE FROM {table} WHERE tech == '{tech}'")
                elif "tech_or_group" in cols:
                    curs.execute(f"DELETE FROM {table} WHERE tech_or_group == '{tech}'")


    """
    ##############################################################
        References
    ##############################################################
    """

    # Add all references in the bibliography to the references tables
    for reference in config.refs:
        curs.execute(f"""REPLACE INTO
                     DataSource(source_id, source, data_id)
                     VALUES('{reference.id}', '{reference.citation}', "{utils.data_id()}")""")
        

    """
    ##############################################################
        Data IDs
    ##############################################################
    """

    for id in sorted(config.data_ids):
        curs.execute(
            f"""REPLACE INTO
            DataSet(data_id)
            VALUES('{id}')"""
        )
    
    # Check for missing data IDs
    tables = [t[0] for t in curs.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]

    for table in tables:
        cols = [c[1] for c in curs.execute(f"PRAGMA table_info({table})").fetchall()]
        if "data_id" in cols:
            bad_rows = pd.read_sql_query(f"SELECT * FROM {table} WHERE data_id is NULL", conn)
            if len(bad_rows) > 0:
                print(f"Found some rows missing data IDs in {table}")
                print(bad_rows)
        

    conn.commit()
    conn.close()



def aggregate_capacity_limits(): 

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()

    """
    ##############################################################
        Some final input file constraints
    ##############################################################
    """

    # LimitCapacity
    for region in config.model_regions:
        for period in config.model_periods:
            for tech in config.cap_limits[region].index:

                max_cap = float(config.cap_limits[region].loc[tech, period]) * config.units.loc['capacity', 'conversion_factor']
                note = config.cap_limits[region].loc[tech, 'note']
                reference = config.cap_limits[region].loc[tech, 'reference']
                if pd.isna(reference): reference = ''
                dq_est = config.cap_limits[region].loc[tech, 'dq_est']

                if dq_est > 0:
                    curs.execute(f"""REPLACE INTO
                                LimitCapacity(region, period, tech_or_group, operator, capacity, units, notes, data_source, dq_cred, data_id)
                                VALUES('{region}', {period}, '{tech}', 'le', {max_cap}, '{config.units.loc['capacity', 'units']}',
                                "{note}", "{reference}", {dq_est}, "{utils.data_id(region)}")""")
                else:
                    curs.execute(f"""REPLACE INTO
                                LimitCapacity(region, period, tech_or_group, operator, capacity, units, notes, data_source, data_id)
                                VALUES('{region}', {period}, '{tech}', 'le', {max_cap}, '{config.units.loc['capacity', 'units']}',
                                "{note}", "{reference}", "{utils.data_id(region)}")""")
                    
    conn.commit()
    conn.close()



def aggregate_imports():

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()

    # Get the last period the import is used in this region and convert to a lifetime, to prevent supply orphans
    df_life = pd.read_sql_query("SELECT region, tech, lifetime FROM LifetimeTech", conn).set_index(['region','tech']).astype(int)
    df_eff = pd.read_sql_query("SELECT region, input_comm, tech, vintage FROM Efficiency", conn)
    df_eff = df_eff.loc[df_eff['tech'].isin(df_life.index.get_level_values('tech'))]
    df_eff['life'] = [
        row['vintage'] + df_life.loc[(row['region'], row['tech'])].iloc[0] - config.model_periods[0]
        for (_, row) in df_eff.iterrows()
    ]
    df_life = df_eff.groupby(['region','input_comm'])['life'].max().astype(int)
    
    for region in config.model_regions:
        for tech, row in config.import_techs.iterrows():
            
            # Get CANOE nomenclature for imported commodity
            out_comm = config.commodities.loc[row['out_comm']]
            
            # Check if used in this region
            inputs = curs.execute(f"SELECT * FROM Efficiency WHERE input_comm=='{out_comm['commodity']}' and region=='{region}'").fetchall()
            if len(inputs) == 0: continue
            
            description = f"import dummy for {out_comm['description']}"

            curs.execute(f"""REPLACE INTO
                        Technology(tech, flag, sector, description, data_id)
                        VALUES('{tech}', 'p', 'electricity', '{description}', "{utils.data_id()}")""")
            
            # A single vintage at first model period with no other parameters, classic dummy tech
            curs.execute(f"""REPLACE INTO
                        Efficiency(region, input_comm, tech, vintage, output_comm, efficiency, notes, data_id)
                        VALUES('{region}', '{config.commodities.loc[row['in_comm'], 'commodity']}', '{tech}',
                        '{config.model_periods[0]}', '{out_comm['commodity']}', 1, '{description}', "{utils.data_id(region)}")""")
            
            # The dummy needs to retire when it is no longer used
            # (or it will be orphaned and removed by network checks)
            life = df_life.loc[(region, out_comm['commodity'])]
            if life < config.model_periods[-1] - config.model_periods[0]:
                curs.execute(f"""REPLACE INTO
                        LifetimeTech(region, tech, lifetime, notes, data_id)
                        VALUES("{region}", "{tech}", "{life}", "(y) retires when no longer used", "{utils.data_id(region)}")""")

    conn.commit()
    conn.close()



if __name__ == "__main__":

    process()