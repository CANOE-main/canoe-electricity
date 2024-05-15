"""
Aggregates capacity factors except for new wind and solar
Written by Ian David Elder for the CANOE model
"""

import pandas as pd

# Provincial scripts
import provincial_data.on.existing_vre_capacity_factors as on_vre_exs
import provincial_data.on.existing_hydro_capacity_factors as on_hydro_exs



# Sends existing capacity to relevant provincial scripts
def aggregate_existing(df_rtv: pd.DataFrame):

    #on_vre_exs.aggregate_cfs(df_rtv.loc[(df_rtv['region'] == 'ON') & (df_rtv['tech_code'].isin(['solar','wind_onshore','wind_offshore']))]) # ontario existing vre cfs
    #on_hydro_exs.aggregate_cfs(df_rtv.loc[(df_rtv['region'] == 'ON') & (df_rtv['tech_code'].isin(['hydro_daily','hydro_run']))]) # ontario existing hydro cfs

    # TODO temporarily using Ontario for all regions to get things running
    on_vre_exs.aggregate_cfs(df_rtv.loc[df_rtv['tech_code'].isin(['solar','wind_onshore','wind_offshore'])]) # ontario existing vre cfs
    on_hydro_exs.aggregate_cfs(df_rtv.loc[df_rtv['tech_code'].isin(['hydro_daily','hydro_run'])]) # ontario existing hydro cfs



# Aggregates capacity factors for new capacity
def aggregate_new(df_rtv: pd.DataFrame):

    # TODO for now, assuming future hydro for all regions looks like existing hydro for Ontario
    on_hydro_exs.aggregate_cfs(df_rtv.loc[df_rtv['tech_code'].isin(['hydro_daily','hydro_run'])]) # ontario existing hydro cfs

    # TODO for now, use existing for wind offshore (this technology shouldn't be included anyway)
    # on_vre_exs.aggregate_cfs(df_rtv.loc[df_rtv['tech_code'].isin(['wind_offshore'])]) # ontario existing vre cfs