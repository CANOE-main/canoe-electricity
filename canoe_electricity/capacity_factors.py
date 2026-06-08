"""
Aggregates capacity factors except for new wind and solar
Written by Ian David Elder for the CANOE model
"""

import pandas as pd

# Provincial scripts
import provincial_data.on.existing_vre_capacity_factors as on_vre_exs
import provincial_data.on.existing_hydro_capacity_factors as on_hydro_exs
import provincial_data.default.existing_hydro_capacity_factors as def_hydro_exs
import provincial_data.default.existing_vre_capacity_factors as def_vre_exs



# Sends existing capacity to relevant provincial scripts
def aggregate_existing(df_rtv: pd.DataFrame):

    # Ontario has good open data
    on_vre_exs.aggregate_cfs(df_rtv.loc[(df_rtv['region'] == 'ON') & (df_rtv['tech_code'].isin(['solar','wind_onshore','wind_offshore']))].copy())
    on_hydro_exs.aggregate_cfs(df_rtv.loc[(df_rtv['region'] == 'ON') & (df_rtv['tech_code'].isin(['hydro_daily','hydro_run']))].copy()) # (ontario has no monthly storage)

    # Synthesise data for every other province
    def_vre_exs.aggregate_cfs(df_rtv.loc[(df_rtv['region'] != 'ON') & (df_rtv['tech_code'].isin(['solar','wind_onshore','wind_offshore']))].copy())
    def_hydro_exs.aggregate_cfs(df_rtv.loc[(df_rtv['region'] != 'ON') & (df_rtv['tech_code'].isin(['hydro_daily','hydro_run','hydro_monthly']))].copy())



# Aggregates capacity factors for new capacity
# Currently do not allow new hydro because the data is non existent
def aggregate_new(df_rtv: pd.DataFrame):

    # TODO for now, assuming future hydro for all regions looks like existing hydro for Ontario
    on_hydro_exs.aggregate_cfs(df_rtv.loc[df_rtv['tech_code'].isin(['hydro_daily','hydro_run'])].copy()) # ontario existing hydro cfs

    # TODO for now, use existing for wind offshore
    # on_vre_exs.aggregate_cfs(df_rtv.loc[df_rtv['tech_code'].isin(['wind_offshore'])]) # ontario existing vre cfs