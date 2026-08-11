"""
Builds the electricity sector database to be merged into the larger model
Written by Ian David Elder for the CANOE model
"""

from __future__ import annotations

import os
import re
import sqlite3

import pandas as pd
from matplotlib import pyplot as pp

import canoe_electricity.generators as generators
import canoe_electricity.interfaces as interfaces
import canoe_electricity.post_processing as post_processing
import canoe_electricity.provincial_grids as provincial_grids
import canoe_electricity.setup as setup
import canoe_electricity.utils as utils
import canoe_electricity.validation as validation
from canoe_electricity import patch_solar_wind
from canoe_electricity.config import CANOEElectricityConfig
from canoe_electricity.setup import config as _default_config


def build_database(cfg: CANOEElectricityConfig | None = None) -> None:
    """Orchestrate electricity sector aggregation.

    1. Resolve config (use supplied cfg or module-level default).
    2. Validate database pre-conditions.
    3. Aggregate provincial grids (demand, transmission, reserve margin).
    4. Aggregate generators (existing + new) and storage.
    5. Aggregate intertie interfaces.
    6. Run post-processing (commodities, references, data IDs).
    7. Optionally clone to Excel and save plots.
    """
    cfg = cfg or _default_config

    print(f"Aggregating electricity sector into {os.path.basename(cfg.database_file)}...\n")

    # 2. Pre-flight: ensure DB exists; optionally wipe stale module rows
    setup.open_database()

    # 3. Validate DB schema against config expectations
    conn = sqlite3.connect(cfg.database_file)
    validation.validate_db_against_config(cfg, conn)

    # Use the discount rate from the shared DB so all modules agree on one value.
    row = conn.execute(
        "SELECT value FROM metadata_real WHERE element = 'global_discount_rate'"
    ).fetchone()
    if row is not None:
        cfg.global_discount_rate = float(row[0])
        print(f"global_discount_rate = {cfg.global_discount_rate} (from database metadata_real)\n")

    conn.close()

    # 4. Provincial grids — must precede generators so demand data is ready for capacity credits
    provincial_grids.aggregate()

    # 5. Generators and storage
    generators.aggregate()

    # 6. Intertie interfaces
    interfaces.aggregate()

    # 7. Post-processing: commodities, references, data IDs; optional capacity limits / imports
    post_processing.process()

    # 8. Patch solar/wind data
    patch_solar_wind.replace_from_parquet(
        parquet_paths=[f"{cfg.input_files}/renewables_cache/{val}.parquet" for val in
            ["capacity_credit",
            "capacity_factor",
            "cost_fixed",
            "cost_invest",
            "max_capacity"]],
        table_names={"max_capacity": "limit_capacity", "capacity_factor": "capacity_factor_process"},
        new_suffix_version=cfg.data_version,
        target_db_path=cfg.database_file,
    )

    # 9. Optional Excel clone
    if cfg.clone_to_excel:
        utils.database_converter().clone_sqlite_to_excel()

    print(f"Electricity sector aggregated into {os.path.basename(cfg.database_file)}\n")

    # 9. Save plots produced during aggregation
    if cfg.show_plots:
        save_plots()


def save_plots(output_dir='output_plots'):
    os.makedirs(output_dir, exist_ok=True)
    print("Finished and saving plots.")
    for fig_num in pp.get_fignums():
        fig = pp.figure(fig_num)
        # Try suptitle first, then first axes title, then fall back to figure number
        title = fig.get_suptitle()
        if not title and fig.axes:
            title = fig.axes[0].get_title()
        filename = title if title else f"figure_{fig_num}"
        # Sanitize filename: replace characters that are invalid in Windows filenames
        filename = re.sub(r'[\\/:*?"<>|\x00-\x1f .,]', '_', filename)
        filepath = os.path.join(output_dir, f"{filename}.pdf")
        fig.savefig(filepath, bbox_inches='tight')
        print(f"Saved {filepath}")



"""
##############################################################
    The following is setup for electricity sector testing
##############################################################
"""

def prepare_test_model():

    config = _default_config
    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()

    rep_days = [
        'D006', # Coldest day ON 2018
        'D035',
        'D070',
        'D105',
        'D140',
        'D185' # Hottest day ON 2018
    ]

    curs.execute("""REPLACE INTO sector_labels(sector) VALUES('electricity')""")

    curs.execute("DELETE FROM time_season")
    [curs.execute(f"INSERT INTO time_season(season) VALUES('{day}')") for day in rep_days]

    seas_tables = [
        'CapacityFactorTech',
        'CapacityFactorProcess',
        'DemandSpecificDistribution',
        'MinSeasonalActivity',
        'MaxSeasonalActivity'
        ]

    for table in seas_tables:
        curs.execute(f"DELETE FROM {table} WHERE season_name NOT IN (SELECT season from time_season)")

    df_dsd = pd.read_sql_query("SELECT * FROM DemandSpecificDistribution", conn)
    df_dsd = df_dsd.groupby(['regions','demand_name'])
    for grp in df_dsd.groups:
        df_grp = df_dsd.get_group(grp)
        total_dsd = df_grp['dsd'].sum()
        curs.execute(f"""UPDATE DemandSpecificDistribution
                    SET dsd = dsd / {total_dsd}
                    WHERE regions = '{df_grp['regions'].iloc[0]}'
                    AND demand_name == '{df_grp['demand_name'].iloc[0]}'""")

    for day in rep_days:
        for h in range(24):
            curs.execute(f"""REPLACE INTO SegFrac(season_name, tod, segfrac)
                        VALUES('{day}', '{config.time.loc[h, 'tod']}', {1/(24*6)})""")

    base_emis = 3200
    emis = {
        2021: 1.00,
        2025: 0.80,
        2030: 0.65,
        2035: 0.50,
        2040: 0.35,
        2045: 0.20,
        2050: 0.05
    }

    emis_comms = [c[0] for c in curs.execute("SELECT comm_name FROM commodities WHERE flag == 'e'")]

    for emis_comm in emis_comms:
        for period in config.model_periods:
            curs.execute(f"""REPLACE INTO
                        EmissionLimit(regions, periods, emis_comm, emis_limit, emis_limit_units)
                        VALUES("global", {period}, "{emis_comm}", {emis[period]*base_emis}, "kt")""")

    conn.commit()
    conn.execute("VACUUM;")

    conn.commit()
    conn.close()

    print("Finished.")



if __name__ == "__main__":

    build_database()
