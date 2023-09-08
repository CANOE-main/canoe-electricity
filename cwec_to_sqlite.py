""" 
This script compiles CWEC data into many tables of a sqlite database
Written by Ian David Elder for the TEMOA Canada / CANOE model
"""

import csv
import os
import sqlite3
from datetime import datetime

script_path = os.path.realpath(os.path.dirname(__file__)) + "/"
cwec_folder = script_path + "CWEC/"
cwec_db = script_path + "cwec.sqlite"

csv_files = []

print("\nSearching for CWEC .csv files in directory:")
print(script_path)

print("\nFound:")
for root, dir, files in os.walk(cwec_folder):
    for file in files:
        name = os.path.join(root, file)
        filename, file_extension = os.path.splitext(name)
        if (file_extension == '.csv'):
            print(os.path.basename(name))
            csv_files.append(name)

conn = sqlite3.connect(cwec_db)
curs = conn.cursor()



def clean_column(column):
    column = column.lower().replace(' / ','_').replace(' ','_')
    clean_string = ''.join(letter for letter in column if letter == '_' or letter.isalnum())
    return clean_string



time_start = datetime.now()

for s in range(len(csv_files)):

    if s != 0:
        time = datetime.now()

        completed = s/len(csv_files)
        remaining = (1 - completed)/completed*(time - time_start)

        print(f"""{round(100*completed,2)} % completed, time remaining: {str(remaining).split(".")[0]}""")

    with open(csv_files[s], newline='') as csvfile:
        
        # Fill stations table with station metadata
        rows = list()
        spamreader = csv.reader(csvfile, delimiter=',', quotechar='|')

        for row in spamreader:
            rows.append(row)

        
        metadata = dict()
        
        for c in range(len(rows[0])):
            column = rows[0][c].lower().replace(' ','_')
            metadata.update({column: rows[1][c]})

        curs.execute(f"""INSERT OR IGNORE INTO
                    stations(station_id)
                    VALUES("{metadata["station_id"]}")""")
        
        for column in metadata.keys():
            if column == "station_id": continue

            if type(metadata[column]) is str:
                curs.execute(f"""UPDATE stations
                            SET {column} = "{metadata[column]}"
                            WHERE station_id = '{metadata["station_id"]}'""")
            else:
                curs.execute(f"""UPDATE stations
                            SET {column} = {metadata[column]}
                            WHERE station_id = '{metadata["station_id"]}'""")
                


        # Create station table of all other data
        curs.execute(f"""CREATE TABLE IF NOT EXISTS
                        '{metadata['station_id']}'
                        (hour integer PRIMARY KEY);""")
        
        for c in range(0,len(rows[2])):
            column = clean_column(rows[2][c])
            if column == 'flag': column = 'flag_' + clean_column(rows[2][c-1])

            try:
                isnum = float(rows[3][c])
                curs.execute(f"""ALTER TABLE
                            '{metadata['station_id']}'
                            ADD {column} REAL;""")
            except:
                curs.execute(f"""ALTER TABLE
                            '{metadata['station_id']}'
                            ADD {column} TEXT;""")
        

        for h in range(1,8761):
            r = h+2

            cols = 'hour'
            vals = str(h)
            for c in range(0,len(rows[2])):
                column = clean_column(rows[2][c])
                if column == 'flag': column = 'flag_' + clean_column(rows[2][c-1])

                cols += ", " + column

                value = rows[r][c]
                vals += f", '{str(value)}'"

            curs.execute(f"""REPLACE INTO
                        '{metadata['station_id']}'({cols})
                        VALUES({vals})""")

            

conn.commit()
conn.close()