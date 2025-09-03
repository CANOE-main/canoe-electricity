import sqlite3

import provincial_data.default.ramp_rates as def_rr


def aggregate(region:str, tech:str, tech_code:str, curs:sqlite3.Cursor):
    """
    Redirects region-tech combos to provincial data
    """

    # Default values for now
    def_rr.aggregate(region, tech, tech_code, curs)