"""
This script fills the translation file with CODERS nomenclature
Written by Ian David Elder for the TEMOA Canada / CANOE model
"""

import requests
import sqlite3

conn = sqlite3.connect('CODERS_CANOE_translation.sqlite')
curs = conn.cursor()

tables = requests.get('http://206.12.95.90/tables').json()
print(tables)
print('\n\n')

generators = requests.get('http://206.12.95.90/generators').json()
print(generators[0])
print('\n\n')

for generator in generators:
    gen_type = generator["gen_type"].upper()
    region = generator["copper_balancing_area"].upper()

    curs.execute(f'INSERT OR IGNORE INTO generator_types(gen_type) VALUES(\"{gen_type}\")')
    curs.execute(f'INSERT OR IGNORE INTO regions(CODERS_region) VALUES(\"{region}\")')

generation_generic = requests.get('http://206.12.95.90/generation_generic').json()
print(generation_generic[0])
print('\n\n')

for generator in generation_generic:
    gen_type = generator["generation_type"].upper()

    curs.execute(f'INSERT OR IGNORE INTO generator_types(gen_type) VALUES(\"{gen_type}\")')

interfaces = requests.get('http://206.12.95.90/interface_capacities').json()
print(interfaces[0])
print('\n\n')

for interface in interfaces:

    region_one = interface["export_from"].upper()
    region_two = interface["export_to"].upper()

    curs.execute(f"""INSERT OR IGNORE INTO
                 transfer_regions(interties, region_1, region_2)
                 VALUES("{interface['associated_interties']}", "{region_one}", "{region_two}")""")

    for region in region_one, region_two:
        curs.execute(f'INSERT OR IGNORE INTO regions(CODERS_region) VALUES(\"{region}\")')

conn.commit()
conn.close()