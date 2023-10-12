"""
Various tools
Written by Ian David Elder for the TEMOA Canada / CANOE model
"""


import os
import pandas as pd
import requests
import xmltodict
import json



this_dir = os.path.realpath(os.path.dirname(__file__)) + "/"
cache_dir = this_dir + "download_cache/"



def string_cleaner(string):

    clean_string = ''.join(letter for letter in string if letter in '- ()' or letter.isalnum())

    return clean_string



def get_file(url, file_type=None, name=None, use_cache=True, **kwargs):

    # Get the original file name
    if name == None: name = url.split("/")[-1].split("\\")[-1]
    if file_type == None: file_type = url.split(".")[-1]

    file_type = file_type.lower()

    if file_type == "xml": name = os.path.splitext(name)[0] + ".json"
    cache_file = cache_dir + name

    data = None
    if (use_cache and os.path.isfile(cache_file)):

        # Get from existing local cache
        if file_type == "csv": data = pd.read_csv(cache_file, index_col=0)
        elif "xl" in file_type: data = pd.read_excel(cache_file, index_col=0)
        elif file_type == "xml": data = json.load(open(cache_file))
        print(f"Got {name} from local cache.")
        
    else:

        # Download from url
        if file_type == "csv": data = pd.read_csv(url, **kwargs)
        elif "xl" in file_type: data = pd.read_excel(url, **kwargs)
        elif file_type == "xml": data = json.dumps(xmltodict.parse(requests.get(url).content))
        print(f"Downloaded {name}.")

        # Try to cache
        try:
            if file_type == "csv": data.to_csv(cache_file)
            elif "xl" in file_type: data.to_excel(cache_file)
            elif file_type == "xml":
                with open(cache_file, 'w') as outfile: outfile.write(data)
            print(f"Cached {name}.")
        except Exception as e:
            print(e)

    return data