"""
Aggregates capacity credits
Written by Ian David Elder for the CANOE model
"""

import pandas as pd

# Provincial scripts
import provincial_data.ontario.existing_capacity_credits as on_cc_exs


# Sends existing capacity to relevant provincial scripts
def aggregate_existing(df_rtv: pd.DataFrame):

    on_cc_exs.aggregate_ccs(df_rtv.loc[df_rtv['region'] == 'ON']) # ontario existing capacity credits