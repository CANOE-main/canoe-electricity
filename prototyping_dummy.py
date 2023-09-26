import requests
import pandas as pd
import numpy as np
from matplotlib import pyplot as plot
import json
import sqlite3
import os

cf_ror = np.array(pd.read_csv('ieso_hydro_ror_cf.csv')['0'])
cf_dly = np.array(pd.read_csv('ieso_hydro_dly_cf.csv')['0'])

print(cf_ror)
print(cf_dly)