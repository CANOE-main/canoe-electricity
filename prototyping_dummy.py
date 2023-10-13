import requests
import pandas as pd
import numpy as np
from matplotlib import pyplot as plot
import json
import sqlite3
import os
import tools
from setup import config

for gen_tech in config.batched_cap["ON"].index:
    base_tech = config.translator['generator_types'][gen_tech]['CANOE_tech']
    n_batches = config.batched_cap["ON"].loc[gen_tech, 'batches']

    variants = [f"{base_tech}-EXS", *[f"{base_tech}-NEW-{n}" for n in range(1,n_batches+1)]]