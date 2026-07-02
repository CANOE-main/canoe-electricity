"""
Performs some final post-processing on aggregated data
Written by Ian David Elder for the CANOE model
"""

import sqlite3
from canoe_electricity.setup import config
import pandas as pd
import canoe_electricity.utils as utils
from canoe_schema.v4_0.models import Commodity, DataSource, DataSet, Technology, Efficiency, LifetimeTech, LimitCapacity



def process():

    if config.include_imports: aggregate_imports()
    if config.include_capacity_limits: aggregate_capacity_limits()

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()


    """
    ##############################################################
        Add any used commodities
    ##############################################################
    """

    # First get all the used commodities from the efficiency and emission_activity tables
    eff = curs.execute("SELECT input_comm, output_comm FROM efficiency").fetchall()
    emis = curs.execute("SELECT emis_comm FROM emission_activity").fetchall()

    used_comms = set()
    for io in eff:
        used_comms.add(io[0])
        used_comms.add(io[1])
    for e in emis: used_comms.add(e[0])

    rows = [
        Commodity(
            name=comm['commodity'],
            flag=comm['flag'],
            description=comm['description'],
            units=comm['units'],
            data_id=utils.data_id(),
        )
        for _code, comm in config.commodities.iterrows()
        if comm['commodity'] in used_comms
    ]
    if rows:
        curs.executemany(*Commodity.bulk_insert_or_ignore_sql(rows))


    """
    ##############################################################
        Unused techs
    ##############################################################
    """

    used_techs = [t[0] for t in curs.execute("SELECT tech FROM efficiency")]
    all_techs = [t[0] for t in curs.execute("SELECT tech FROM technology")]
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

    rows = [DataSource(source_id=ref.id, source=ref.citation, data_id=utils.data_id()) for ref in config.refs]
    if rows:
        curs.executemany(*DataSource.bulk_insert_or_ignore_sql(rows))


    """
    ##############################################################
        Data IDs
    ##############################################################
    """

    rows = [DataSet(data_id=id) for id in sorted(config.data_ids)]
    if rows:
        curs.executemany(*DataSet.bulk_insert_or_ignore_sql(rows))

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

                curs.executemany(*LimitCapacity.bulk_insert_or_ignore_sql([LimitCapacity(
                    region=region, period=period, tech_or_group=tech,
                    operator='le', capacity=max_cap,
                    units=config.units.loc['capacity', 'units'],
                    notes=note, data_source=reference or None,
                    dq_cred=int(dq_est) if dq_est > 0 else None,
                    data_id=utils.data_id(region),
                )]))

    conn.commit()
    conn.close()



def aggregate_imports():

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()

    # Get the last period the import is used in this region and convert to a lifetime, to prevent supply orphans
    df_life = pd.read_sql_query("SELECT region, tech, lifetime FROM lifetime_tech", conn).set_index(['region','tech']).astype(int)
    df_eff = pd.read_sql_query("SELECT region, input_comm, tech, vintage FROM efficiency", conn)
    df_eff = df_eff.loc[df_eff['tech'].isin(df_life.index.get_level_values('tech'))]
    df_eff['life'] = [
        row['vintage'] + df_life.loc[(row['region'], row['tech'])].iloc[0] - config.model_periods[0]
        for (_, row) in df_eff.iterrows()
    ]
    df_life = df_eff.groupby(['region','input_comm'])['life'].max().astype(int)

    tech_rows = []
    eff_rows = []
    life_rows = []

    for region in config.model_regions:
        for tech, row in config.import_techs.iterrows():

            # Get CANOE nomenclature for imported commodity
            out_comm = config.commodities.loc[row['out_comm']]

            # Check if used in this region
            inputs = curs.execute(
                f"SELECT * FROM efficiency WHERE input_comm=='{out_comm['commodity']}' and region=='{region}'"
            ).fetchall()
            if len(inputs) == 0: continue

            description = f"import dummy for {out_comm['description']}"

            tech_rows.append(Technology(tech=tech, flag='p', sector='electricity', description=description, data_id=utils.data_id()))
            eff_rows.append(Efficiency(
                region=region,
                input_comm=config.commodities.loc[row['in_comm'], 'commodity'],
                tech=tech,
                vintage=config.model_periods[0],
                output_comm=out_comm['commodity'],
                efficiency=1,
                notes=description,
                data_id=utils.data_id(region),
            ))

            # The dummy needs to retire when it is no longer used
            life = df_life.loc[(region, out_comm['commodity'])]
            if life < config.model_periods[-1] - config.model_periods[0]:
                life_rows.append(LifetimeTech(
                    region=region,
                    tech=tech,
                    lifetime=life,
                    notes="(y) retires when no longer used",
                    data_id=utils.data_id(region),
                ))

    if tech_rows:
        curs.executemany(*Technology.bulk_insert_or_ignore_sql(tech_rows))
    if eff_rows:
        curs.executemany(*Efficiency.bulk_insert_or_ignore_sql(eff_rows))
    if life_rows:
        curs.executemany(*LifetimeTech.bulk_insert_or_ignore_sql(life_rows))

    conn.commit()
    conn.close()



if __name__ == "__main__":

    process()
