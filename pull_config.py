"""
This builds and handles the CODERS translator
Written by Ian David Elder for the CANOE model
"""


import os
import sqlite3



# Get the schema, target, and database translation files
translation_file = "CODERS_CANOE_translation.sqlite"



# Connect to the translator file
conn = sqlite3.connect(translation_file)
curs = conn.cursor()

# Convert translator database into a dictionary to speed things up
# usage: translator['table name']['value of first column']['column value needed']
translator = dict()



# Get future model periods
curs.execute("""SELECT periods FROM model_periods""")
model_periods = [period[0] for period in curs.fetchall()]

# Get all regions
curs.execute("""SELECT CANOE_region FROM regions""")
all_regions = set(region[0] for region in curs.fetchall())

# Get capacity to activity
fetch = curs.execute("""SELECT CANOE_unit, conversion_factor FROM units WHERE metric = 'capacity_to_activity'""").fetchone()
c2a_unit, c2a = fetch[0], fetch[1]

# hour out of 8760 -> time of day or season name
curs.execute("""SELECT time_of_day FROM time""")
tofd_8760 = [tofd[0] for tofd in curs.fetchall()]
curs.execute("""SELECT season FROM time""")
seas_8760 = [seas[0] for seas in curs.fetchall()]



curs.execute("SELECT name FROM sqlite_master WHERE type='table'")
all_tables = [table[0] for table in curs.fetchall()]

for table in all_tables:
    translator.update({table: dict()})

    rows = curs.execute("SELECT * FROM " + table)
    column_names = [column[0] for column in rows.description]
    
    rows = rows.fetchall()

    for r in range(len(rows)):
        translator[table].update({rows[r][0]: dict()})

        for c in range(len(column_names)):
            translator[table][rows[r][0]].update({column_names[c]: rows[r][c]})



# Get global values
rows = curs.execute("SELECT * FROM global_values")
column_names = [column[0] for column in rows.description]
rows = rows.fetchall()

global_values = list()
for r in range(len(rows)):

    global_value = dict()
    global_values.append(global_value)

    for c in range(len(column_names)):
        global_value.update({column_names[c]: rows[r][c]})



params = dict()
for param in translator['pull_parameters']:
    params.update({param: translator['pull_parameters'][param]['value']})



# Close connection to translator
conn.close()