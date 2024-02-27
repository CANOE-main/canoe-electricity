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
coders_root = "http://206.12.95.90/"

if not os.path.isdir(cache): os.mkdir(cache)



# Converts CODERS listed json data into pandas dataframe
def _to_dataframe(json_data):
    data_dict = dict()
    [data_dict.update({idx: json_data[idx]}) for idx in range(len(json_data))]

    # Convert to pandas dataframe
    return pd.DataFrame.from_dict(data_dict).transpose()



def get_data(end_point=None, **kwargs) -> tuple[list[dict], pd.DataFrame, str] | None:

    # Adding additional arguments to the endpoint, e.g. year, province
    if len(kwargs.keys()) > 0:
        end_point += '?'
        for key in kwargs.keys():
            end_point += f"{key}={kwargs[key]}&"
        end_point = end_point[0:-1] # Remove last excess &

    # Filename for local json cache
    json_cache = cache + utils.string_cleaner(end_point) + ".json"
    
    # Initialising variables
    data_json = None
    date_accessed = str(date.today()) # date accessed is today if downloaded

    # If from_cache=True, try getting the json data from the local cache
    if not config.params['force_download'] and os.path.isfile(json_cache):
        
        try:
            with open(json_cache, 'r') as in_file:
                data_json = json.load(in_file)

            df = _to_dataframe(data_json)

            # Data accessed for a cached file is the last edited time, not great but it'll do
            date_accessed = str(datetime.fromtimestamp(os.path.getmtime(json_cache)).date())

            print(f"Got CODERS data from local cache, endpoint={end_point}")

            return data_json, df, date_accessed
        
        except:
            print(f"Could not get data from local cache for endpoint={end_point}. Downloading instead.")

    # If asked for cache but it doesn't exist
    if config.params['force_download'] and not os.path.isfile(json_cache):
        print(f"No local cache was found for endpoint={end_point}. Downloading instead.")

    # Otherwise, download the json from the CODERS API
    try:
        data_json = requests.get(coders_root + end_point).json()

        # If update_cache=True, save this downloaded file to the local cache
        if data_json is not None:

            df = _to_dataframe(data_json)

            print(f"Downloaded CODERS data, endpoint={end_point}")

            try:
                with open(json_cache, "w") as outfile:
                    json.dump(data_json, outfile)
                print(f"Cached CODERS data locally, endpoint={end_point}.")
            except:
                print(f"Could not cache CODERS data locally, endpoint={end_point}")

            return data_json, df, date_accessed

    except:
        print(f"Could not get data for endpoint={end_point}. No data retrieved.")

        return None, None, date_accessed