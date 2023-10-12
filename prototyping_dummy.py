import requests
import pandas as pd
import numpy as np
from matplotlib import pyplot as plot
import json
import sqlite3
import os
import tools

data_year = 2020
url = f"http://reports.ieso.ca/public/IntertieScheduleFlowYear/PUB_IntertieScheduleFlowYear_{data_year}.csv"
data = tools.get_file(url, index_col=False, skiprows=4, nrows=8760)

print(data.head(10))