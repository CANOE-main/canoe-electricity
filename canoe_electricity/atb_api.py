"""
NREL Annual Technology Baseline (ATB) data access.

External source: NREL ATB Master Workbook (Excel .xlsb)
  URL configured in params.yaml under atb.master_url
  Cache: data_cache/<workbook_filename>            (downloaded workbook)
         data_cache/atb_technology_specific_variables_<sheet>.csv  (per-sheet CSV cache)

Two kinds of ATB data are used by this module:

1. Technology-specific variables (TSV) — per-technology heat rates, emissions,
   ramp rates, etc. from the ATB master workbook.  Accessed via load_tsv().

2. Cost/performance summary (CSV) — capital costs, O&M, efficiencies indexed
   by display_name / scenario / core_metric_case.  This is handled by
   utils.atb_data() and will be migrated here in Step 4.

Citation: each sheet+row combination represents a distinct data source; callers
are responsible for registering the reference via config.refs.add() using the
note string that load_tsv() returns.
"""

import os
import urllib.request

import pandas as pd


_tsv_cache: dict[str, pd.DataFrame] = {}


def download_master(url: str, cache_dir: str, force_download: bool = False) -> str:
    """Download the ATB master workbook if not already cached.

    Args:
        url: direct download URL for the ATB master .xlsb file.
        cache_dir: local directory to save the workbook.
        force_download: re-download even if the file already exists.

    Returns:
        Absolute path to the cached workbook file.
    """
    filename = url.split("/")[-1]
    cache_file = os.path.join(cache_dir, filename)

    if not os.path.isfile(cache_file) or force_download:
        print("Downloading ATB master workbook...")
        urllib.request.urlretrieve(url, cache_file)

    return cache_file


def load_tsv(
    sheet: str,
    row: str,
    master_file: str,
    master_tables: pd.DataFrame,
    cache_dir: str,
    headers_map: dict[str, str],
    force_download: bool = False,
) -> tuple[pd.Series | None, str]:
    """Load one row of an ATB technology-specific variables (TSV) table.

    Reads the requested sheet from the ATB master workbook, caches it as a CSV,
    and returns the row for the given technology.

    Args:
        sheet: ATB master workbook sheet name (e.g. 'Natural Gas').
        row: row label within the sheet (e.g. 'NG_F_Class1').
        master_file: path to the downloaded ATB master workbook (.xlsb).
        master_tables: DataFrame from atb_master_tables.csv describing sheet
                       layout (columns, first_row, last_row).
        cache_dir: directory for per-sheet CSV caches.
        headers_map: dict mapping raw ATB column strings to friendly names,
                     from params['atb']['tsv_headers'].
        force_download: bypass the CSV cache and re-read from the workbook.

    Returns:
        (row_series, note) where note is a human-readable citation string, or
        (None, note) if the sheet is not specified.
    """
    note = f"{sheet} - {row}"

    if pd.isna(sheet):
        return None, note

    if sheet in _tsv_cache and not force_download:
        return _tsv_cache[sheet].loc[row], note

    cache_file = os.path.join(cache_dir, f"atb_technology_specific_variables_{sheet}.csv")

    if os.path.isfile(cache_file) and not force_download:
        df = pd.read_csv(cache_file, index_col=0)
        _tsv_cache[sheet] = df
        return df.loc[row], note

    table = master_tables.loc[master_tables["table"] == "tsv"].loc[sheet]

    df = pd.read_excel(
        master_file,
        dtype="unicode",
        sheet_name=sheet,
        usecols=table["columns"],
        skiprows=int(table["first_row"]) - 1,
        nrows=int(table["last_row"]) - int(table["first_row"]),
        index_col=0,
    )

    # Concatenate split headers that ATB spreads across multiple rows
    def _no_unnamed(s: str) -> str:
        return s.replace(" ", "") if "Unnamed" not in s else ""

    def _no_na(v) -> str:
        return str(v).replace(" ", "") if not pd.isna(v) else ""

    df.columns = [
        _no_unnamed(df.columns[i]) + _no_na(df.iloc[0, i]) + _no_na(df.iloc[1, i])
        for i in range(len(df.columns))
    ]

    # Keep only columns we want and rename them
    df = df[[c for c in headers_map if c in df.columns]]
    df.columns = [headers_map[c] for c in df.columns]

    # Add NaN columns for expected fields that were absent in this sheet
    for col in headers_map.values():
        if col not in df.columns:
            df[col] = pd.NA

    df = df.iloc[2:]  # drop leading descriptor rows

    df.to_csv(cache_file)
    _tsv_cache[sheet] = df

    return df.loc[row], note
