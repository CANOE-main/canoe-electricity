import requests
import pandas as pd
import numpy as np
from matplotlib import pyplot as pp
import json
import sqlite3
import os
import utils
import shutil
#from setup import config
import coders_api
from setup import config

# Existing storage
_storage_exs, df_storage, date_accessed = coders_api.get_data(end_point='storage')
config.references['storage'] = config.params['coders_reference'].replace("<date>", date_accessed)
df_storage['tech'] = df_storage['generation_type'].str.upper().map(config.tech_map)

print(df_storage)