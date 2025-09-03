import sqlite3

import provincial_data.default.cost_tx_dx as def_cost


def aggregate(
        region:str,
        period:int,
        tech:str,
        vintage:int,
        curs:sqlite3.Cursor,
        data_id:str,
        tx_dx:str='both'
    ):
    """
    Redirects region-tech combos to provincial data
    """

    # Default values for now TODO break into provincial data
    def_cost.aggregate(region, period, tech, vintage, curs, data_id, tx_dx)