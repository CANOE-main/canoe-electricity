import requests
import pandas as pd
import numpy as np
from matplotlib import pyplot as plot
import json
import sqlite3
import os
from string_cleaner import string_cleaner

this_dir = os.path.realpath(os.path.dirname(__file__)) + "/"
coders_cache = this_dir + "coders_cache/"
coders_root = "http://206.12.95.90/"

if not os.path.isdir(coders_cache): os.mkdir(coders_cache)

def get_json(end_point=None, from_cache=False, update_cache=True):

    json_cache = coders_cache + string_cleaner(end_point) + ".json"
    
    data_json = None
    downloaded = False
    if from_cache and os.path.isfile(json_cache):
        with open(json_cache, 'r') as in_file:
            data_json = json.load(in_file)
        print(f"Got CODERS data from cache, endpoint={end_point}")
    else:
        data_json = requests.get(coders_root + end_point).json()
        downloaded = True
        print(f"Downloaded CODERS data, endpoint={end_point}")

    if (downloaded and update_cache):
        with open(json_cache, "w") as outfile:
            json.dump(data_json, outfile)

    return data_json

print(get_json(end_point="interprovincial_transfers?year=2020&province1=ON&province2=MB",from_cache=True)[0])