import sqlite3
from pathlib import Path
import pandas as pd
import duckdb


def _get_pk_columns(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(f'PRAGMA table_info("{table}")')
        pk_cols = [row[1] for row in cur.fetchall() if row[5] > 0]
        return pk_cols
    finally:
        conn.close()


def replace_from_parquet(
    parquet_paths,
    target_db_path,
    code_column="data_id",
    new_suffix_version="003",
    table_names=None,
    # missing_ok=False
):
    """
    Load rows from parquet files and REPLACE INTO matching rows in a SQLite
    database, rewriting `code_column` so its last digit becomes
    `new_suffix_digit` (e.g. 'ABC1001' -> 'ABC1003').

    NOTE: REPLACE INTO deletes any existing row with the same primary key
    and inserts a fresh one. Every column the target table expects MUST be
    present in the parquet data, or missing columns will be reset to
    NULL/default. This also means rowid changes on replace (unless rowid
    IS the declared PK), and any ON DELETE triggers/cascades will fire.

    Args:
        parquet_paths: list of paths to .parquet files (one per table).
        target_db_path: path to the target SQLite .db file.
        code_column: name of the column holding the code to rewrite.
        new_suffix_digit: digit to force as the last character (default "3").
        table_names: optional dict {parquet_path: table_name}. If omitted,
                     inferred from the file stem, e.g. "capacity_factor.parquet" -> "capacity_factor".
    """
    table_names = table_names or {}

    # Resolve table names up front
    resolved = {}
    for path in parquet_paths:
        path = Path(path)
        table = table_names.get(str(path.stem), path.stem)
        resolved[path] = table

    # --- Do ALL sqlite3 schema reads BEFORE DuckDB ever touches the file ---
    conn = sqlite3.connect(target_db_path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA cache_size = -2000000")

    schemas = {}
    for path, table in resolved.items():
        cur = conn.execute(f'PRAGMA table_info("{table}")')
        info = cur.fetchall()
        pk_cols = [row[1] for row in info if row[5] > 0]
        all_cols = [row[1] for row in info]
        if not pk_cols:
            conn.close()
            raise ValueError(f"Table '{table}' has no primary key defined.")
        schemas[table] = (pk_cols, set(all_cols))

    conn.close()  # fully release the stdlib connection before DuckDB attaches

    # --- Now DuckDB owns the file exclusively for the rest of the run ---
    con = duckdb.connect()
    con.execute(f"ATTACH '{target_db_path}' AS target (TYPE sqlite)")

    for path, table in resolved.items():
        pk_cols, target_cols = schemas[table]
        pk_list = ", ".join(f'"{c}"' for c in pk_cols)

        total_before = con.execute(f"SELECT count(*) FROM read_parquet('{path}')").fetchone()[0]

        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE staged AS
            SELECT * EXCLUDE (_rn) FROM (
                SELECT *,
                       ROW_NUMBER() OVER (PARTITION BY {pk_list} ORDER BY {pk_list}) AS _rn
                FROM (
                    SELECT * REPLACE (
                        (left({code_column}, -3) || '{new_suffix_version}') AS {code_column}
                    )
                    FROM read_parquet('{path}')
                )
            )
            WHERE _rn = 1
        """)

        total_after = con.execute("SELECT count(*) FROM staged").fetchone()[0]
        if total_after < total_before:
            print(f"{table}: WARNING — {total_before - total_after} duplicate rows "
                  f"collapsed onto the same PK after rewriting {code_column}; kept one arbitrarily.")

        staged_cols_all = [row[0] for row in con.execute("DESCRIBE staged").fetchall()]
        staged_cols = [c for c in staged_cols_all if c in target_cols]

        dropped = set(staged_cols_all) - set(staged_cols)
        if dropped:
            print(f"{table}: ignoring columns not present in target table: {dropped}")

        col_list = ", ".join(f'"{c}"' for c in staged_cols)

        con.execute(f"""
            DELETE FROM target."{table}"
            WHERE ({pk_list}) IN (SELECT {pk_list} FROM staged)
        """)

        con.execute(f'''
            INSERT INTO target."{table}" ({col_list})
            SELECT {col_list} FROM staged
        ''')

        n = con.execute("SELECT count(*) FROM staged").fetchone()[0]
        print(f"{table}: matched on {pk_cols}, replaced {n} rows "
              f"({len(staged_cols)}/{len(target_cols)} cols supplied, rest set NULL)")

    con.close()
