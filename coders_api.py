"""
This script gets a requested table from the CODERS API, and handles local caching
Returns the requested json data, same data in pandas dataframe, and the date it was accessed

Usage is
    json_data, df_data, date_accessed = coders_api.get_json(end_point='generators', from_cache=False, update_cache=True)
or
    json_data, df_data, date_accessed = coders_api.get_json(end_point='interprovincial_transfers', from_cache=True, update_cache=True, province1='ON', province2='MB', year=2020)
"""

import requests
import json
import os
from datetime import datetime
from datetime import date
import pandas as pd
import utils
from setup import config

cache = config.cache_dir
coders_root = "https://api.sesit.ca/"

if not os.path.isdir(cache): os.mkdir(cache)

api_key = None



def _get_api_key():
    global api_key
    if not os.path.isfile(config.input_files + config.params['coders_api_key_file']):
        print(f"\nTo get CODERS data, must save a CODERS API key! Configured location:\n{config.input_files + config.params['coders_api_key_file']}\n")
        return
    with open(config.input_files + config.params['coders_api_key_file'], 'r') as open_file:
        api_key = open_file.read()



# Converts CODERS listed json data into pandas dataframe
def _to_dataframe(json_data):
    return pd.DataFrame(index=range(len(json_data)), data=json_data)



def get_data(end_point=None, **kwargs) -> tuple[pd.DataFrame, str] | None:

    if config.debug: print("Getting CODERS data: ", end_point, kwargs)

    # Adding additional arguments to the endpoint, e.g. year, province, then finally api key
    end_point += '?'

    if len(kwargs.keys()) > 0:
        for key in kwargs.keys():
            end_point += f"{key}={kwargs[key]}&"

    clean_endpoint = utils.string_cleaner(end_point)

    dates_file = cache + 'dates.csv'
    if os.path.isfile(dates_file):
        try:
            df_dates = pd.read_csv(dates_file, index_col=0)
        except:
            df_dates = pd.Series(name='date_accessed')
            df_dates.index = df_dates.index.rename('end_point')
            df_dates.to_csv(dates_file)
    else:
        df_dates = pd.Series(name='date_accessed')
        df_dates.index = df_dates.index.rename('end_point')

    # Filename for local json cache
    csv_cache = cache + clean_endpoint + ".csv"
    
    # Initialising variables
    data_json = None
    date_accessed = str(date.today()) # date accessed is today if downloaded

    # If from_cache=True, try getting the json data from the local cache
    if not config.params['force_download'] and os.path.isfile(csv_cache):
        
        try:
            df = pd.read_csv(csv_cache, index_col=0)

            # Data accessed for a cached file
            try:
                date_accessed = df_dates.loc[clean_endpoint].iloc[0]
            except:
                date_accessed = 'na'

            print(f"Got CODERS data from local cache, endpoint={end_point[0:-1]}")

            return df, date_accessed
        
        except:
            print(f"Could not get data from local cache for endpoint={end_point[0:-1]}. Downloading instead.")
  
    elif config.params['force_download']:
        print(f"Params configured to force download. Downloading endpoint={end_point[0:-1]}.")

    elif not os.path.isfile(csv_cache):
        print(f"No local cache was found for endpoint={end_point[0:-1]}. Downloading instead.")

    # Didn't get from local cache so download from the CODERS API
    if api_key is None: _get_api_key()

    try:
        data_json = requests.get(coders_root + end_point + f"key={api_key}").json()

        # If update_cache=True, save this downloaded file to the local cache
        if data_json is not None:

            df = _to_dataframe(data_json)

            print(f"Downloaded CODERS data, endpoint={end_point[0:-1]}")

            try:
                df_dates.loc[clean_endpoint] = date_accessed
                df_dates.to_csv(dates_file)
                df.to_csv(csv_cache)
                print(f"Cached CODERS data locally, endpoint={end_point[0:-1]}.")
            except:
                print(f"Could not cache CODERS data locally, endpoint={end_point[0:-1]}")

            return df, date_accessed

    except:
        print(f"Could not retrieve CODERS data from {coders_root}{end_point}key={api_key}")

        return None, date_accessed