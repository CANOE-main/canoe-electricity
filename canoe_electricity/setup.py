"""
Sets up configuration for electricity sector aggregation.
Written by Ian David Elder for the CANOE model.

Exposes `config` — a module-level CANOEElectricityConfig singleton — plus
`open_database()` for pre-flight DB validation and selective data wipe.
"""

import os
import sqlite3

import canoe_electricity.atb_api as atb_api
from canoe_electricity.config import (
    CANOEElectricityConfig,
    bibliography,   # re-exported for callers that import from setup
    reference,      # re-exported for callers that import from setup
)


# ---------------------------------------------------------------------------
# Module-level config singleton (loaded from TOML on first import)
# ---------------------------------------------------------------------------

config: CANOEElectricityConfig = CANOEElectricityConfig.load()

# Download ATB master workbook and stash the path on the config
config.atb_master_file = atb_api.download_master(
    url=config.atb.master_url,
    cache_dir=config.cache_dir,
    force_download=config.force_download,
)

print('Instantiated setup config.\n')


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def open_database() -> None:
    """Validate that the shared DB exists and optionally wipe module data.

    The electricity module no longer creates or seeds the database — it only
    appends module-specific rows.  Run canoe-base first to produce the DB.

    If ``config.force_wipe_database`` is True, only rows belonging to this
    module (identified by data_id prefix) are deleted before the run, leaving
    canoe-base and other modules' data intact.
    """
    if not os.path.exists(config.database_file):
        raise FileNotFoundError(
            f"Expected shared database at {config.database_file!r}. "
            "Run canoe-base first to create and seed the database."
        )

    conn = sqlite3.connect(config.database_file)
    if config.force_wipe_database:
        _wipe_module_data(conn)
    conn.close()


def _wipe_module_data(conn: sqlite3.Connection) -> None:
    """Delete only this module's rows (data_id prefix match) from the shared DB."""
    prefix = config.data_id_prefix
    curs = conn.cursor()
    tables = [t[0] for t in curs.execute(
        "SELECT name FROM sqlite_master WHERE type='table';"
    ).fetchall()]
    for table in tables:
        cols = [row[1] for row in curs.execute(f"PRAGMA table_info('{table}')").fetchall()]
        if 'data_id' in cols:
            curs.execute(f"DELETE FROM '{table}' WHERE data_id LIKE '{prefix}%'")
    conn.commit()
    print(f"Cleared electricity module data (prefix='{prefix}') from database.\n")
