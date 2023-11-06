"""
Gets non-VRE capacity credits from IESO reliability outlook
Written by Ian David Elder for the CANOE model
"""

import sqlite3
import utils
from setup import config
import pandas as pd

# The most recent or desired ieso reliability outlook
yyyy, mmm = config.params['ieso_rel_yyyy_mmm'].split("_")

rel_outlook_url = f"https://www.ieso.ca/-/media/Files/IESO/Document-Library/planning-forecasts/reliability-outlook/ReliabilityOutlookTables_{yyyy}{mmm}.ashx"
note = "Forecasted capability at normal summer peak divided by total installed capacity"
reference = f"IESO. ({yyyy}, {mmm}). Reliability Outlook. https://www.ieso.ca/en/Sector-Participants/Planning-and-Forecasting/Reliability-Outlook"

# Get the reliability outlook forecast peak table and calculate capacity credits
ieso_rel = utils.get_data(rel_outlook_url, file_type='xlsx', sheet_name='Table 4.1', skiprows=4, header=0, nrows=6, index_col=0)
ieso_rel['capacity_credit'] = ieso_rel[f"Forecast Capability at 2024 Summer Peak [{config.params['ieso_rel_peak_type']}] (MW)"] / pd.to_numeric(ieso_rel['Total Installed Capacity\n(MW)'])
print('IESO reliability outlook capacity credits:')
print(ieso_rel.iloc[:,-1:])

# Specify which techs to assign capacity credits by fuel type
fuel_tech_like = {
    'Nuclear':['NUC'],
    'Hydroelectric':['HYD_DLY','HYD_MLY','HYD_ANN'],
    'Gas/Oil':['DIES','GSL','NGS','OIL'],
    'Wind':['WND_OFF'],
    'Biofuel':['BIO','MSW'],
    'Solar':[]
}



def write_to_coders_db():

    conn = sqlite3.connect('coders_db.sqlite')
    curs = conn.cursor()

    curs.execute(f"""REPLACE INTO
                 'references'('reference')
                 VALUES('{reference}')""")

    for fuel in fuel_tech_like.keys():

        techs = set()
        
        for tech_like in fuel_tech_like[fuel]:
            [techs.add(tech[0]) for tech in curs.execute(f"SELECT tech FROM Efficiency WHERE tech like '%{tech_like}%' and regions == 'ON'").fetchall()]

        cc = ieso_rel.loc[fuel, 'capacity_credit']

        for tech in techs:

            # Get period-vintage pairs for this variant
            vints = [v[0] for v in curs.execute(f"SELECT vintage FROM Efficiency WHERE tech == '{tech}'").fetchall()]
            life = curs.execute(f"SELECT life FROM LifetimeTech WHERE tech == '{tech}'").fetchone()[0]

            for period in config.model_periods:
                for vint in vints:
                    if vint > period or vint + life < period: continue

                    curs.execute(f"""REPLACE INTO
                                CapacityCredit(regions, periods, tech, vintage, cf_tech, cf_tech_notes, reference)
                                VALUES("ON", {period}, '{tech}', {vint}, {cc}, '{note}', '{reference}')""")
                

                    if tech in config.generic_techs.keys():
                        # Use tech descriptions if running this in chain after coders_pull.py where techs are updated
                        curs.execute(f"""REPLACE INTO
                                    tech_reserve(tech, notes)
                                    VALUES('{tech}', '{config.generic_techs[tech]['description']}')""")
                    else:
                        # Otherwise dont override descriptions in database
                        curs.execute(f"""INSERT OR IGNORE INTO
                                    tech_reserve(tech)
                                    VALUES('{tech}')""")
                        
    conn.commit()
    conn.close()