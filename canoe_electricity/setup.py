"""
Sets up configuration for electricity sector aggregation
Written by Ian David Elder for the CANOE model
"""

import os
import pandas as pd
import yaml
import sqlite3
import numpy as np
import urllib.request 



def instantiate_database():
    
    # Check if database exists or needs to be built
    build_db = not os.path.exists(config.database_file)

    # Connect to the new database file
    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor() # Cursor object interacts with the sqlite db

    # Build the database if it doesn't exist. Otherwise clear all data if forced
    if build_db: curs.executescript(open(config.schema_file, 'r').read())
    elif config.params['force_wipe_database']:
        tables = [t[0] for t in curs.execute("""SELECT name FROM sqlite_master WHERE type='table';""").fetchall()]
        for table in tables: curs.execute(f"DELETE FROM '{table}'")
        curs.executescript(open(config.schema_file, 'r').read())
        print("Database wiped prior to aggregation. See params.\n")

    conn.commit()

    # VACUUM operation to clean up any empty rows
    conn.execute("VACUUM;")
    conn.commit()

    conn.close()



class reference:
    """
    Stores a single reference and its attributes
    - id: the unique id for the source_id column
    - citation: the full citation to go in the DataSource table
    """

    id: str
    citation: str

    def __init__(self, id: str, citation: str):
        self.id = id
        self.citation = citation


class bibliography:
    """This class stores references and handles unique indexing"""

    references: dict[str, reference] = dict()

    def __iter__(self):
        for name, ref in self.references.items():
            yield ref

    def add(cls, name: str, citation: str) -> reference | None:
        """Add a reference to the log and return the reference object"""

        if name in cls.references:
            return cls.references[name]
        else:
            num = len(cls.references.keys()) + 1
            id = f"E{num}" if num >= 10 else f"E0{num}" # E01 -> E99 unique IDs
            ref = reference(id=id, citation=citation)
            cls.references[name] = ref
            return ref
    
    def get(cls, name: str) -> reference | None:
        """Returns a reference by its semantic name"""

        if name not in cls.references:
            print(f"Tried to get a reference that had not been added yet: {name}")
            return
        else:
            return cls.references[name]



class config:
    """A singleton-pattern class to contain general configuration data"""

    # File locations
    _this_dir = os.path.realpath(os.path.dirname(__file__)) + "/"
    input_files = _this_dir + 'input_files/'
    cache_dir = _this_dir + "data_cache/"

    if not os.path.exists(cache_dir): os.mkdir(cache_dir)
    
    refs: bibliography = bibliography()
    data_ids = set()
    provincial_demand: dict[str, np.ndarray] = {}

    exs_vre_gen = dict()
    """Regional dictionary of hourly total generation of existing VRE in the weather year in GWh"""

    _instance = None # singleton pattern



    def __new__(cls, *args, **kwargs):

        if isinstance(cls._instance, cls): return cls._instance
        cls._instance = super(config, cls).__new__(cls, *args, **kwargs)

        if not os.path.isdir(config.cache_dir): os.mkdir(config.cache_dir)

        cls._get_params(cls._instance)
        cls._get_files(cls._instance)
        cls._download_atb_master(cls._instance)

        print('Instantiated setup config.\n')

        return cls._instance

        

    def _get_params(cls):

        stream = open(config.input_files + "params.yaml", 'r')
        config.params = dict(yaml.load(stream, Loader=yaml.Loader))
        config.debug = config.params['debug']

        config.commodities = pd.read_csv(config.input_files + 'commodities.csv', index_col=0)
        config.regions = pd.read_csv(config.input_files + 'regions.csv', index_col=0)
        config.time = pd.read_csv(config.input_files + 'time.csv', index_col=0)
        config.units = pd.read_csv(config.input_files + 'units.csv', index_col=0)
        config.trans_techs = pd.read_csv(config.input_files + 'transmission_technologies.csv', index_col=0)
        config.gen_techs = pd.read_csv(config.input_files + 'generator_technologies.csv', index_col=0)
        config.storage_techs = pd.read_csv(config.input_files + 'storage_technologies.csv', index_col=0)
        config.import_techs = pd.read_csv(config.input_files + 'import_technologies.csv', index_col=0)
        config.ccs_techs = pd.read_csv(config.input_files + 'ccs_retrofit_technologies.csv', index_col=0)
        config.atb_master_tables = pd.read_csv(config.input_files + 'atb_master_tables.csv', index_col=0)
        
        # Only want the included retrofit techs
        config.ccs_techs = config.ccs_techs.loc[config.ccs_techs['include']]

        # Fill in missing columns versus gen_techs
        config.storage_techs['tech_sets'] = pd.NA # what sets would you add them to?
        config.storage_techs['include_fuel_cost'] = False # no fuel for storage techs

        # Included regions and future periods
        config.model_periods = list(config.params['model_periods'])
        config.model_periods.sort()
        config.regions['endogenous'] = config.regions['endogenous'].astype('boolean').fillna(False)
        config.model_regions = config.regions.loc[(config.regions['endogenous'])].index.unique().to_list()
        config.model_regions.sort()

        # Initialise VRE hourly generation, for calculating capacity credits
        for region in config.model_regions: config.exs_vre_gen[region] = np.zeros(8760)

        # Maps all coders gen types to canoe techs
        config.gen_map = dict()
        for tech_code, row in config.gen_techs.iterrows():
            config.gen_map[row['coders_equiv']] = tech_code

        # Maps all coders storage types to canoe techs
        config.storage_map = dict()
        for tech_code, row in config.storage_techs.iterrows():
            key = (row['coders_equiv'], row['duration'])
            config.storage_map[key] = tech_code

        # Maps all types of coders regions to canoe regions
        config.region_map = dict()
        for region, row in config.regions.iterrows():
            for coders_equiv in row['coders_equivs'].split("+"):
                config.region_map[coders_equiv] = region
                # else: config.region_map[coders_equiv] = 'X'

        # Maps all coders existing storage types to canoe techs
        config.existing_map = dict()
        for tech_code, row in config.gen_techs.iterrows():
            if pd.isna(row['coders_existing']): continue
            for coders_equiv in row['coders_existing'].split("+"):
                config.existing_map[coders_equiv] = tech_code

        # Batched new capacities and new capacity limits
        # Deprecated
        # config.batched_cap = dict()
        # config.cap_limits = dict()
        # for region in config.model_regions:
        #     config.batched_cap[region] = pd.read_excel(config.input_files + 'batched_new_capacity.xlsx', sheet_name=region, index_col=0, skiprows=2)
        #     config.cap_limits[region] = pd.read_excel(config.input_files + 'capacity_limits.xlsx', sheet_name=region, index_col=0, skiprows=2)
            


    def _get_files(cls):

        config.schema_file = config.input_files + config.params['sqlite_schema']
        config.database_file = config.params['sqlite_database']#config._this_dir + config.params['sqlite_database']
        config.excel_template_file = config.input_files + config.params['excel_template']
        config.excel_target_file = config._this_dir + config.params['excel_output']

    

    def _download_atb_master(cls):

        config.atb_master_file = config.cache_dir + config.params['atb']['master_url'].split('/')[-1]

        if not os.path.isfile(config.atb_master_file):
            print("Downloading ATB master workbook...")
            urllib.request.urlretrieve(config.params['atb']['master_url'], config.atb_master_file)
        


# Instantiate config on import
config()