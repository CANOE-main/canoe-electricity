"""
Sets up configuration for electricity sector aggregation
Written by Ian David Elder for the CANOE model
"""

import os
import sqlite3
import pandas as pd
import coders_api

# I'll be honest I mostly just wanted to practice python objects
# but maybe this will save memory
class config:

    # File locations
    this_dir = os.path.realpath(os.path.dirname(__file__)) + "/"
    translation_file = this_dir + "CODERS_CANOE_translation.sqlite"
    batch_file = this_dir + "input_files/batched_new_capacity.xlsx"
    cap_limit_file = this_dir + "input_files/capacity_limits.xlsx"

    _instance = None # singleton pattern

    def __new__(cls, *args, **kwargs):

        if isinstance(cls._instance, cls): return cls._instance

        cls._instance = super(config, cls).__new__(cls, *args, **kwargs)
            
        # Connect to the translator file
        conn = sqlite3.connect(cls.translation_file)
        curs = conn.cursor()

        cls._build_translator(curs)
        cls._get_params(curs)

        conn.close()

        print('Instantiated setup config.')

        return cls._instance

        

    def _get_params(curs):

        # Get future model periods
        curs.execute("""SELECT periods FROM model_periods""")
        config.model_periods = [period[0] for period in curs.fetchall()]

        # Get all techs
        curs.execute("""SELECT CANOE_tech FROM technologies""")
        config.all_techs = set(tech[0] for tech in curs.fetchall())

        # Get all commodities
        curs.execute("""SELECT input_comm FROM technologies""")
        config.all_comms = set(comm[0] for comm in curs.fetchall())
        curs.execute("""SELECT output_comm FROM technologies""")
        [config.all_comms.add(comm[0]) for comm in curs.fetchall()]

        # Get all regions
        curs.execute("""SELECT CANOE_region FROM regions""")
        config.all_regions = set(region[0] for region in curs.fetchall())

        # Get capacity to activity
        fetch = curs.execute("""SELECT CANOE_unit, conversion_factor FROM units WHERE metric = 'capacity_to_activity'""").fetchone()
        config.c2a_unit, config.c2a = fetch[0], fetch[1]

        # hour out of 8760 -> time of day or season name
        curs.execute("""SELECT time_of_day FROM time""")
        config.tofd_8760 = [tofd[0] for tofd in curs.fetchall()]
        curs.execute("""SELECT season FROM time""")
        config.seas_8760 = [seas[0] for seas in curs.fetchall()]

        # General pull parameters
        config.params = dict()
        for param in config.translator['pull_parameters']:
            config.params[param] = config.translator['pull_parameters'][param]['value']

        # Batched new capacities
        config.batched_cap = dict()
        for region in config.all_regions:
            if region == 'EX': continue

            batches = pd.read_excel(config.batch_file, sheet_name=region, index_col=0, skiprows=2)
            config.batched_cap[region] = batches

        # New capacity limits
        config.cap_limits = dict()
        for region in config.all_regions:
            if region == 'EX': continue

            limits = pd.read_excel(config.cap_limit_file, sheet_name=region, index_col=0, skiprows=2)
            config.cap_limits[region] = limits

        # Collect generic tech data
        generic_json, date_accessed = coders_api.get_json(end_point='generation_generic',from_cache=(config.params['pull_from_cache'] == 'true'))
        config.generic_techs = dict({config.translator['generator_types'][tech['generation_type'].upper()]['CANOE_tech']: tech for tech in generic_json})

        # Dictionary of references
        config.references = {'generation_generic': config.params['coders_reference'] + date_accessed}



    def _build_translator(curs):

        # Convert translator database into a dictionary to speed things up
        # usage: translator['table name']['value of first column']['column value needed']
        config.translator = dict()

        curs.execute("SELECT name FROM sqlite_master WHERE type='table'")
        all_tables = [table[0] for table in curs.fetchall()]

        for table in all_tables:
            config.translator[table] = dict()

            rows = curs.execute("SELECT * FROM " + table)
            column_names = [column[0] for column in rows.description]
            
            rows = rows.fetchall()

            for r in range(len(rows)):
                config.translator[table][rows[r][0]] = dict()

                for c in range(len(column_names)):
                    config.translator[table][rows[r][0]][column_names[c]] = rows[r][c]



# Instantiate on import
config()