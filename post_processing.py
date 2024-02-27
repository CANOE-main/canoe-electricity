"""
Performs some final post-processing on aggregated data
Written by Ian David Elder for the CANOE model
"""

import sqlite3
from setup import config
import pandas as pd



def process():

    if config.params['include_imports']: aggregate_imports()


    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()


    """
    ##############################################################
        Add any used technologies and commodities
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
            curs.execute(f"""REPLACE INTO
                        commodities(comm_name, flag, comm_desc)
                        VALUES('{comm['commodity']}', '{comm['flag']}', '({comm['units']}) {comm['description']}')""")


    """
    ##############################################################
        Some final input file constraints
    ##############################################################
    """

    # TODO could probably generalise this step to all constraint tables
    # MaxCapacity
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
                                MaxCapacity(regions, periods, tech, maxcap, maxcap_units, maxcap_notes, reference, dq_est)
                                VALUES('{region}', {period}, '{tech}', {max_cap}, '{config.units.loc['capacity', 'units']}',
                                "{note}", "{reference}", {dq_est})""")
                else:
                    curs.execute(f"""REPLACE INTO
                                MaxCapacity(regions, periods, tech, maxcap, maxcap_units, maxcap_notes, reference)
                                VALUES('{region}', {period}, '{tech}', {max_cap}, '{config.units.loc['capacity', 'units']}',
                                "{note}", "{reference}")""")



    """
    ##############################################################
        References
    ##############################################################
    """

    for ref in config.references.values():
        curs.execute(f"""REPLACE INTO
                    'references'('reference')
                    VALUES('{ref}')""")


    conn.commit()
    conn.close()



def aggregate_imports():

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()

    # Get which fuel commodities are actually being used
    used_comms = set([c[0] for c in curs.execute(f"SELECT input_comm FROM Efficiency").fetchall()])

    for tech, row in config.import_techs.iterrows():
        
        # Get CANOE nomenclature for imported commodity
        out_comm = config.commodities.loc[row['out_comm']]

        # Make sure the model is using this imported commodity otherwise skip
        if out_comm['commodity'] not in used_comms: continue
        
        description = f"import dummy for {out_comm['description']}"

        curs.execute(f"""REPLACE INTO
                     technologies(tech, flag, sector, tech_desc)
                     VALUES('{tech}', 'r', 'electricity', '{description}')""")
        
        # A single vintage at first model period with no other parameters, classic dummy tech
        for region in config.model_regions:
            curs.execute(f"""REPLACE INTO
                        Efficiency(regions, input_comm, tech, vintage, output_comm, efficiency, eff_notes)
                        VALUES('{region}', '{config.commodities.loc[row['in_comm'], 'commodity']}', '{tech}',
                        '{config.model_periods[0]}', '{out_comm['commodity']}', 1, '{description})')""")
            
    conn.commit()
    conn.close()