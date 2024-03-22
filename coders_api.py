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
coders_root = "http://206.12.95.102/"

if not os.path.isdir(cache): os.mkdir(cache)

api_key: str = None



def _get_api_key():
    global api_key
    with open(config.input_files + config.params['coders_api_key_file'], 'r') as open_file:
        api_key = open_file.read()



# Converts CODERS listed json data into pandas dataframe
def _to_dataframe(json_data):
    data_dict = dict()
    [data_dict.update({idx: json_data[idx]}) for idx in range(len(json_data))]

    # Convert to pandas dataframe
    return pd.DataFrame.from_dict(data_dict).transpose()



def get_data(end_point=None, **kwargs) -> tuple[list[dict], pd.DataFrame, str] | None:

    global api_key
    if api_key is None: _get_api_key()

    # Adding additional arguments to the endpoint, e.g. year, province, then finally api key
    end_point += '?'

    if len(kwargs.keys()) > 0:
        for key in kwargs.keys():
            end_point += f"{key}={kwargs[key]}&"

    # Filename for local json cache
    json_cache = cache + utils.string_cleaner(end_point[0:-1]) + ".json"
    
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

            print(f"Got CODERS data from local cache, endpoint={end_point[0:-1]}")

            return data_json, df, date_accessed
        
        except:
            print(f"Could not get data from local cache for endpoint={end_point[0:-1]}. Downloading instead.")
  
    elif config.params['force_download']:
        print(f"Params configured to force download. Downloading endpoint={end_point[0:-1]}.")

    elif not os.path.isfile(json_cache):
        print(f"No local cache was found for endpoint={end_point[0:-1]}. Downloading instead.")

    # Didn't get from local cache so download from the CODERS API
    try:
        data_json = requests.get(coders_root + end_point + f"key={api_key}").json()

        # If update_cache=True, save this downloaded file to the local cache
        if data_json is not None:

            df = _to_dataframe(data_json)

            print(f"Downloaded CODERS data, endpoint={end_point[0:-1]}")

            try:
                with open(json_cache, "w") as outfile:
                    json.dump(data_json, outfile)
                print(f"Cached CODERS data locally, endpoint={end_point[0:-1]}.")
            except:
                print(f"Could not cache CODERS data locally, endpoint={end_point[0:-1]}")

            return data_json, df, date_accessed

    except:
        print(f"Could not retrieve CODERS data from {coders_root}{end_point}key={api_key}")

        return None, None, date_accessed