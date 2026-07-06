"""
CODERS API client — fetches electricity-sector data from the SESIT CODERS API
and handles local caching.

External source: CODERS API (https://api.sesit.ca/)
  - generators        — existing generation fleet by province
  - storage           — existing storage fleet by province
  - generation_cost_evolution — capital-cost trajectories by tech type
  - generation_generic        — generic technoeconomic parameters by tech type
  - CA_system_parameters      — provincial reserve margins, line losses, etc.
  - interface_capacities       — interprovincial transfer capacity limits
  - (and others, passed as end_point keyword)

Cache: data_cache/<end_point>.csv  (one CSV per endpoint)
Date accessed: logged in data_cache/dates.csv

Usage:
    df, date_accessed = coders_api.get_data(
        end_point='generators',
        cache_dir='data_cache/',
        force_download=False,
        api_key_file='input_files/coders_api_key.txt',
    )
"""

import os
from datetime import date

import pandas as pd
import requests

CODERS_ROOT = "https://api.sesit.ca/"


def _string_cleaner(string: str) -> str:
    return "".join(c for c in string if c in "- /()–" or c.isalnum())


def _read_api_key(api_key_file: str) -> str | None:
    if not os.path.isfile(api_key_file):
        print(
            f"\nTo get CODERS data, save a CODERS API key at:\n{api_key_file}\n"
        )
        return None
    with open(api_key_file, "r") as f:
        return f.read().strip()


def _to_dataframe(json_data) -> pd.DataFrame:
    return pd.DataFrame(index=range(len(json_data)), data=json_data)


def get_data(
    end_point: str,
    cache_dir: str,
    force_download: bool = False,
    api_key_file: str | None = None,
    debug: bool = False,
    **kwargs,
) -> tuple[pd.DataFrame | None, str]:
    """Fetch a CODERS table, using a local CSV cache where available.

    Args:
        end_point: CODERS API table name (e.g. 'generators').
        cache_dir: directory for local CSV cache files.
        force_download: bypass cache and re-download even if a cached file exists.
        api_key_file: path to a file containing the CODERS API key.
        debug: print extra progress messages when True.
        **kwargs: additional query-string parameters (e.g. province='ON', year=2020).

    Returns:
        (DataFrame, date_accessed_str) on success, or None on failure.
    """
    if debug:
        print("Getting CODERS data: ", end_point, kwargs)

    query = end_point + "?"
    for key, value in kwargs.items():
        query += f"{key}={value}&"

    clean_key = _string_cleaner(query)

    dates_file = os.path.join(cache_dir, "dates.csv")
    if os.path.isfile(dates_file):
        try:
            df_dates = pd.read_csv(dates_file, index_col=0)
        except Exception:
            df_dates = pd.Series(name="date_accessed")
            df_dates.index = df_dates.index.rename("end_point")
            df_dates.to_csv(dates_file)
    else:
        df_dates = pd.Series(name="date_accessed")
        df_dates.index = df_dates.index.rename("end_point")

    csv_cache = os.path.join(cache_dir, clean_key + ".csv")
    date_accessed = str(date.today())

    if not force_download and os.path.isfile(csv_cache):
        try:
            df = pd.read_csv(csv_cache, index_col=0)
            try:
                date_accessed = df_dates.loc[clean_key].iloc[0]
            except Exception:
                date_accessed = "na"
            print(f"Got CODERS data from local cache, endpoint={end_point}")
            return df, date_accessed
        except Exception:
            print(
                f"Could not read local cache for endpoint={end_point}. Downloading instead."
            )
    elif force_download:
        print(f"Force download configured. Downloading endpoint={end_point}.")
    else:
        print(f"No local cache for endpoint={end_point}. Downloading instead.")

    api_key = _read_api_key(api_key_file) if api_key_file else None

    try:
        data_json = requests.get(CODERS_ROOT + query + f"key={api_key}").json()

        if data_json is not None:
            df = _to_dataframe(data_json)
            print(f"Downloaded CODERS data, endpoint={end_point}")
            try:
                df_dates.loc[clean_key] = date_accessed
                df_dates.to_csv(dates_file)
                df.to_csv(csv_cache)
                print(f"Cached CODERS data locally, endpoint={end_point}.")
            except Exception:
                print(f"Could not cache CODERS data locally, endpoint={end_point}")
            return df, date_accessed

    except Exception:
        print(f"Could not retrieve CODERS data from {CODERS_ROOT}{query}key=***")

    return None, date_accessed
