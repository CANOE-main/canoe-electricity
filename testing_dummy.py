"""
For testing code snippets
"""

import pandas as pd
from setup import config
import os
import utils
import coders_api
from matplotlib import pyplot as pp
import provincial_data.ontario.existing_capacity_credits as on_cc
import provincial_data.ontario.existing_hydro_capacity_factors as on_hydro_cf
import provincial_data.ontario.existing_vre_capacity_factors as on_vre_cf

interfaces, df_interfaces, date_accessed = coders_api.get_data(end_point='interface_capacities')

print(df_interfaces['province_state_from'].unique())
print(df_interfaces['province_state_to'].unique())