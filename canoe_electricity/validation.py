"""
Pre-write validation for the electricity sector module.

Checks that the shared database (created by canoe-base) contains the periods,
regions, and time-slices that this module's configuration expects to use.
Runs before any writes so mismatches are caught early.

TODO: update function signatures to accept CANOEElectricityConfig (Step 5)
      once the Pydantic config model is introduced.
"""

import sqlite3
from loguru import logger

from canoe_schema.v4_0.models import Region, TimePeriod, TimeSeason, TimeOfDay


def check_missing_periods(
    db_conn: sqlite3.Connection,
    existing_periods: list[int],
    future_periods: list[int],
) -> list[tuple[int, str]]:
    """Return (period, expected_flag) pairs that are absent or have the wrong flag."""
    cur = db_conn.cursor()
    results = []

    for values, flag in [(existing_periods, "e"), (future_periods, "f")]:
        if not values:
            continue
        placeholders = ", ".join("?" * len(values))

        # Periods present but with the wrong flag
        cur.execute(
            f"SELECT period FROM {TimePeriod.__table_name__}"
            f" WHERE period IN ({placeholders}) AND flag != ?",
            (*values, flag),
        )
        wrong_flag = {row[0] for row in cur.fetchall()}

        # Periods entirely absent
        cur.execute(
            f"SELECT period FROM {TimePeriod.__table_name__}"
            f" WHERE period IN ({placeholders})",
            values,
        )
        found = {row[0] for row in cur.fetchall()}
        missing = set(values) - found

        results += [(val, flag) for val in missing | wrong_flag]

    return results


def check_missing_regions(
    db_conn: sqlite3.Connection,
    model_regions: list[str],
) -> list[str]:
    """Return region codes that are absent from the region table."""
    cur = db_conn.cursor()
    if not model_regions:
        return []
    placeholders = ", ".join("?" * len(model_regions))
    cur.execute(
        f"SELECT region FROM {Region.__table_name__}"
        f" WHERE region IN ({placeholders})",
        model_regions,
    )
    found = {row[0] for row in cur.fetchall()}
    return [r for r in model_regions if r not in found]


def check_missing_seasons(
    db_conn: sqlite3.Connection,
    seasons: list[str],
) -> list[str]:
    """Return season codes absent from time_season."""
    cur = db_conn.cursor()
    if not seasons:
        return []
    placeholders = ", ".join("?" * len(seasons))
    cur.execute(
        f"SELECT t_season FROM {TimeSeason.__table_name__}"
        f" WHERE t_season IN ({placeholders})",
        seasons,
    )
    found = {row[0] for row in cur.fetchall()}
    return [s for s in seasons if s not in found]


def check_missing_tods(
    db_conn: sqlite3.Connection,
    tods: list[str],
) -> list[str]:
    """Return time-of-day codes absent from time_of_day."""
    cur = db_conn.cursor()
    if not tods:
        return []
    placeholders = ", ".join("?" * len(tods))
    cur.execute(
        f"SELECT tod FROM {TimeOfDay.__table_name__}"
        f" WHERE tod IN ({placeholders})",
        tods,
    )
    found = {row[0] for row in cur.fetchall()}
    return [t for t in tods if t not in found]


def validate_db_against_config(config, db_conn: sqlite3.Connection) -> bool:
    """Validate that the shared DB contains everything this module's config needs.

    Raises ValueError (or warns, depending on config.params['validation_behavior'])
    if any expected periods, regions, seasons, or times-of-day are absent.

    Args:
        config: the canoe_electricity.setup.config singleton (replaced by
                CANOEElectricityConfig in Step 5).
        db_conn: open connection to the shared canoe-base database.
    """
    behavior = config.validation_behavior

    def _handle(message: str):
        if behavior == "error":
            raise ValueError(message)
        logger.warning(message)

    # -- Periods --
    existing_periods = list(config.existing_periods)
    future_periods = list(config.model_periods)

    missing_periods = check_missing_periods(db_conn, existing_periods, future_periods)
    if missing_periods:
        vals, flags = zip(*missing_periods)
        _handle(
            f"Periods missing or with wrong flag in {TimePeriod.__table_name__}: "
            f"{list(zip(vals, flags))}"
        )

    # -- Regions --
    missing_regions = check_missing_regions(db_conn, config.model_regions)
    if missing_regions:
        _handle(
            f"Regions missing from {Region.__table_name__}: {missing_regions}"
        )

    # -- Seasons --
    # Electricity writes (season, tod)-indexed rows so both must exist in the DB.
    seasons = config.time["season"].dropna().unique().tolist() if hasattr(config, "time") else []
    missing_seasons = check_missing_seasons(db_conn, seasons)
    if missing_seasons:
        _handle(
            f"Seasons missing from {TimeSeason.__table_name__}: {missing_seasons}"
        )

    # -- Times of day --
    tods = config.time["tod"].dropna().unique().tolist() if hasattr(config, "time") else []
    missing_tods = check_missing_tods(db_conn, tods)
    if missing_tods:
        _handle(
            f"Times-of-day missing from {TimeOfDay.__table_name__}: {missing_tods}"
        )

    return True
