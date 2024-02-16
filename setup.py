"""
Sets up configuration for electricity sector aggregation
Written by Ian David Elder for the CANOE model
"""

import os
import pandas as pd
import yaml
import requests
import urllib.request
import zipfile

class config:

    # File locations
    _this_dir = os.path.realpath(os.path.dirname(__file__)) + "/"
    input_files = _this_dir + 'input_files/'
    cache_dir = _this_dir + "data_cache/"
    references = dict()

    _instance = None # singleton pattern



    def __new__(cls, *args, **kwargs):

        if isinstance(cls._instance, cls): return cls._instance
        cls._instance = super(config, cls).__new__(cls, *args, **kwargs)

        cls._get_params(cls._instance)
        cls._get_files(cls._instance)

        print('Instantiated setup config.')

        return cls._instance

        

    def _get_params(cls):

        stream = open(config.input_files + "params.yaml", 'r')
        config.params = dict(yaml.load(stream, Loader=yaml.Loader))

        config.commodities = pd.read_csv(config.input_files + 'commodities.csv', index_col=0)
        config.regions = pd.read_csv(config.input_files + 'regions.csv', index_col=0)
        config.trans_regions = pd.read_csv(config.input_files + 'transfer_regions.csv', index_col=0)
        config.trans_techs = pd.read_csv(config.input_files + 'transmission_technologies.csv', index_col=0)
        config.technologies = pd.read_csv(config.input_files + 'technologies.csv', index_col=0)
        config.time = pd.read_csv(config.input_files + 'time.csv', index_col=0)
        config.units = pd.read_csv(config.input_files + 'units.csv', index_col=0)

        config.model_periods = list(config.params['model_periods'])
        config.model_regions = set(config.regions.loc[(config.regions['include']) & (config.regions.index != 'EX')].index)

        # Maps all coders gen types to canoe techs
        config.tech_map = dict()
        for tech, row in config.technologies.iterrows():
            for coders_equiv in row['coders_equivs'].split("+"):
                config.tech_map[coders_equiv] = tech

        # Maps all types of coders regions to canoe regions
        config.region_map = dict()
        for region, row in config.regions.iterrows():
            for coders_equiv in row['coders_equivs'].split("+"):
                config.region_map[coders_equiv] = region

        # Batched new capacities and new capacity limits
        config.batched_cap = dict()
        config.cap_limits = dict()
        for region in config.model_regions:
            config.batched_cap[region] = pd.read_excel(config.input_files + 'batched_new_capacity.xlsx', sheet_name=region, index_col=0, skiprows=2)
            config.cap_limits[region] = pd.read_excel(config.input_files + 'capacity_limits.xlsx', sheet_name=region, index_col=0, skiprows=2)
            



    def _get_files(cls):

        config.schema_file = config.input_files + config.params['sqlite_schema']
        config.database_file = config._this_dir + config.params['sqlite_database']
        config.excel_template_file = config.input_files + config.params['excel_template']
        config.excel_target_file = config._this_dir + config.params['excel_output']



# Instantiate on import
config()