import pandas as pd

import provincial_data.default.ramp_rates as rr
import provincial_data.default.cogen as cg


def aggregate(df_rtv: pd.DataFrame):
    """
    Redirects to provincial scripts
    """

    rr.aggregate(df_rtv)
    cg.aggregate(df_rtv)