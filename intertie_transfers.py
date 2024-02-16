"""
This script gets 8760 transfer flows per regional boundary
Written by Ian David Elder for the TEMOA Canada / CANOE model
"""

import numpy as np
import coders_api
from setup import config

data_year = config.params['default_data_year']



def get_transfered_mwh(region_1, region_2, intertie_type, from_cache=False) -> tuple[np.ndarray, np.ndarray] | None:

    transfers = list()
    if intertie_type == 'international': transfers, df_transfers, date_accessed = coders_api.get_data(end_point="international_transfers", year=data_year, province=region_1, us_region=region_2)
    elif intertie_type == 'interprovincial': transfers, df_transfers, date_accessed = coders_api.get_data(end_point="interprovincial_transfers", year=data_year, province1=region_1, province2=region_2)

    if (len(transfers) < 8760):
        print(f"Insufficient transfer data on {region_1}-{region_2}. Try switching the intertie regions.")
        return None
    
    # Add reference in either direction to make things easier
    config.references[f"{config.region_map[region_1]}-{config.region_map[region_2]}"] = config.params['coders_reference'].replace('<date>', date_accessed)
    config.references[f"{config.region_map[region_2]}-{config.region_map[region_1]}"] = config.params['coders_reference'].replace('<date>', date_accessed)
  
    hourly_mwh = np.zeros(8760)

    for h in range(8760):
        mwh = df_transfers.loc[h, 'transfers_MWh']

        if mwh is not None:
            hourly_mwh[h] = mwh

    forward = hourly_mwh.copy()
    forward[forward < 0] = 0

    backward = hourly_mwh.copy()
    backward[backward > 0] = 0
    backward *= -1

    return forward, backward