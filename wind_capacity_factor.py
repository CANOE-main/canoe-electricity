"""
Gets 8760 capacity factor for existing wind farms in Canada
"""

import turbine_database_downloader as tdd
import os
import sqlite3

# tdd.download_turbine_db()

this_dir = os.path.realpath(os.path.dirname(__file__)) + "/"
turbine_db = this_dir + 'wind_turbine_database.sqlite'

conn = sqlite3.connect(turbine_db)
curs = conn.cursor()
turbines = curs.execute("""SELECT
                        [Province/Territory], [Turbine rated capacity (kW)], 
                        [Hub height (m)], [Manufacturer], [Model], [Latitude],
                        [Longitude]
                        FROM 'Wind Turbine Apr 27'""").fetchall()
conn.close()

print(turbines[1])
