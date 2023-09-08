import requests
import pandas as pd
import os
import sqlite3

this_dir = os.path.realpath(os.path.dirname(__file__)) + "/"
turbine_file = this_dir + 'wind_turbine_database'

url = 'https://ftp.cartes.canada.ca/pub/nrcan_rncan/Wind-energy_Energie-eolienne/wind_turbines_database/Wind_Turbine_Database_FGP.xlsx'

def download_turbine_db():
    r = requests.get(url, verify=False)

    output = open(turbine_file + '.xlsx', 'wb')
    output.write(r.content)
    output.close()

    target = turbine_file + ".sqlite"

    # This is important as otherwise the excel file will conflict with sqlite
    if os.path.exists(target):
        os.remove(target)

    con = sqlite3.connect(target)
    wb = pd.read_excel(turbine_file + '.xlsx', sheet_name = None)

    for sheet in wb:
        wb[sheet].to_sql(sheet, con, if_exists='append', index=False)

    con.commit()
    con.close()