import requests
import pandas as pd
import numpy as np
from matplotlib import pyplot as pp
import json
import sqlite3
import os
import utils
import shutil
from setup import config
import ieso_capacity_factors as ieso_cf
import coders_api

if os.path.isfile('coders_schema.sqlite'): os.remove('coders_schema.sqlite')

shutil.copy('temoa_schema.sqlite', 'coders_schema.sqlite')

conn = sqlite3.connect('coders_schema.sqlite')
curs = conn.cursor()

fetched = curs.execute("""SELECT name FROM sqlite_master WHERE type='table'""").fetchall()
all_tables = [table[0] for table in fetched
              if (not table[0].startswith('Output'))
              if (table[0] != 'references')]
data_tables = [table for table in all_tables if table.upper()[0] == table[0]]
cost_tables = [table for table in all_tables if table.startswith('Cost')]
index_tables = [table for table in all_tables if table.upper()[0] != table[0]]

for table in cost_tables:
    cost_type = table.lower().replace("cost","cost_")
    curs.execute(f"""ALTER TABLE {table}
                 ADD COLUMN data_{cost_type} REAL""")
    curs.execute(f"""ALTER TABLE {table}
                 ADD COLUMN data_cost_year INTEGER""")
    curs.execute(f"""ALTER TABLE {table}
                 ADD COLUMN data_curr TEXT REFERENCES currencies(curr_label)""")

for table in all_tables:
    curs.execute(f"""ALTER TABLE {table}
                 ADD COLUMN reference TEXT REFERENCES 'references'(reference)""")

for table in data_tables:
    curs.execute(f"""ALTER TABLE {table}
                 ADD COLUMN data_year INTEGER""")
    curs.execute(f"""ALTER TABLE {table}
                 ADD COLUMN data_flags TEXT""")
    curs.execute(f"""ALTER TABLE {table}
                 ADD COLUMN dq_est INTEGER""")
    curs.execute(f"""ALTER TABLE {table}
                 ADD COLUMN dq_rel INTEGER""")
    curs.execute(f"""ALTER TABLE {table}
                 ADD COLUMN dq_comp INTEGER""")
    curs.execute(f"""ALTER TABLE {table}
                 ADD COLUMN dq_time INTEGER""")
    curs.execute(f"""ALTER TABLE {table}
                 ADD COLUMN dq_geog INTEGER""")
    curs.execute(f"""ALTER TABLE {table}
                 ADD COLUMN dq_tech INTEGER""")

for table in all_tables:
    curs.execute(f"""ALTER TABLE {table}
                 ADD COLUMN additional_notes TEXT""")

conn.commit()
conn.close()