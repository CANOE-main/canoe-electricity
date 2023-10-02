import requests
import pandas as pd
import numpy as np
from matplotlib import pyplot as plot
import json
import sqlite3
import os

rel_outlook_url = 'https://www.ieso.ca/-/media/Files/IESO/Document-Library/planning-forecasts/reliability-outlook/ReliabilityOutlookTables_2023Sep.ashx'

""" ieso_rel = pd.read_excel(rel_outlook_url, 
              sheet_name='Table 4.1', skiprows=4, header=0)

ieso_rel.to_excel('ieso_rel.xlsx') """

ieso_rel = pd.read_excel('ieso_rel.xlsx', index_col=0)
ieso_fuel_techs = pd.read_excel('ieso_rel_fuel_techs.xlsx', index_col=0)

elcc = pd.DataFrame(index=ieso_rel['Fuel Type'].iloc[0:6].str.lower())
elcc['elcc'] = ieso_rel['Forecast Capability at 2024 Summer Peak [Normal] (MW)'].iloc[0:6].to_numpy() / ieso_rel['Total Installed Capacity\n(MW)'].iloc[0:6].to_numpy()

print(ieso_fuel_techs.head(10))

conn = sqlite3.connect('coders_db.sqlite')
curs = conn.cursor()

model_periods = [el[0] for el in curs.execute("SELECT t_periods FROM time_periods WHERE flag == 'f'").fetchall()]

for fuel_type in ieso_fuel_techs.index:
    techs = ieso_fuel_techs.loc[fuel_type].str.split(',')
    
    for tech in techs:
        exs_techs = curs.execute(f"SELECT tech, vintage FROM ExistingCapacity WHERE regions == 'ON' and tech like '%{tech[0]}%'").fetchall()

        for exs_tech in exs_techs:
            tech_name = exs_tech[0]
            vintage = exs_tech[1]

            lifetime = curs.execute(f"SELECT life FROM LifetimeTech WHERE regions == 'ON' and tech == '{tech_name}'").fetchone()[0]

            for period in model_periods:
                if (vintage + lifetime <= period): continue
            
                curs.execute(f"""REPLACE INTO
                            CapacityCredit(regions, periods, tech, vintage, cf_tech, cf_tech_notes)
                            VALUES('ON', {period}, '{tech_name}', {vintage}, {float(elcc.loc[fuel_type])}, 'From IESO Reliability Outlook (Forecast Capability at 2024 Summer Peak [Normal] / Total Installed Capacity (MW)) {rel_outlook_url}' )
                            """)
                
conn.commit()