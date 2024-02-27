"""
Various tools
Written by Ian David Elder for the TEMOA Canada / CANOE model
"""


import os
import shutil
from openpyxl import load_workbook
import sqlite3
import pandas as pd
import requests
import xmltodict
import json
from setup import config
import urllib.request
import zipfile
import itertools
import time
import threading
import sys


# Identify existing or tech variants
def is_exs(tech: str) -> bool: return tech.endswith('-EXS')



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
    
    conn.commit()
    conn.close()



# Cleans up strings for filenames, databases, etc.
def string_cleaner(string):

    return ''.join(letter for letter in string if letter in '- /()–' or letter.isalnum())



def string_letters(string):

    return ''.join(letter for letter in string_cleaner(string) if letter not in '123456789')



def clean_index(df):

    df.index = [string_letters(idx).lower() for idx in df.index]



def compr_db_url(region, table_number):

    return str(config.params['nrcan_url']).replace('<y>', str(config.params['base_year'])).replace('<r>', region.lower()).replace('<t>', str(table_number))



def get_statcan_table(table, save_as=None, **kwargs):

    if save_as == None: save_as = f"statcan_{table}.csv"
    if os.path.splitext(save_as)[1] != ".csv": save_as += ".csv"

    if not config.params['force_download'] and os.path.isfile(config.cache_dir + save_as):

        try:

            df = pd.read_csv(config.cache_dir + save_as, index_col=0)
            
            print(f"Got Statcan table {table} from local cache.")
            return df
        
        except Exception as e:

            print(f"Could not get Statcan table {table} from local cache. Trying to download instead.")

    # Make a request from the API for the table, returns response status and url for download
    url = f"https://www150.statcan.gc.ca/t1/wds/rest/getFullTableDownloadCSV/{table}/en"
    response = requests.get(url).json()

    # If successful, download the table
    if response['status'] == 'SUCCESS':

        print(f"Downloading Statcan table {table}...")

        # Download and open the zip file
        filehandle,_ = urllib.request.urlretrieve(response['object'])
        zip_file_object = zipfile.ZipFile(filehandle, 'r')

        # Read the table from inside the zip file
        from_file = zip_file_object.open(f"{table}.csv", "r")
        df = pd.read_csv(from_file, **kwargs)
        from_file.close()

        df.to_csv(config.cache_dir + save_as)

        print(f"Cached Statcan table {table}.")
        return df

    else:

        print(f"Request for {table} from Statcan failed. Status: {response['status']}")
        return None
    


def get_compr_db(region, table_number, first_row=0, last_row=None):

    table = get_data(compr_db_url(region, table_number), skiprows=10)
    table = table.loc[first_row::] if last_row is None else table.loc[first_row:last_row]
    table = table.drop("Unnamed: 0", axis=1).set_index('Unnamed: 1').dropna()
    table.index.name = None
    clean_index(table)

    return table



# Downloads and handles local caching of data sources
def get_data(url, file_type=None, cache_file_type=None, name=None, **kwargs) -> pd.DataFrame:

    # Get the original file name
    if name == None: name = url.split("/")[-1].split("\\")[-1]
    if file_type == None: file_type = url.split(".")[-1]

    file_type = file_type.lower()

    if cache_file_type == None:
        if file_type == "xml": cache_file_type = "json"
        elif file_type == "xls": cache_file_type = "xlsx"
        else: cache_file_type = file_type
    
    # If file type is different from new file type
    if url.split(".")[-1] != cache_file_type: name = os.path.splitext(name)[0] + "."+cache_file_type
    cache_file = config.cache_dir + name

    data = None
    if (not config.params['force_download'] and os.path.isfile(cache_file)):
        
        # Get from existing local cache
        if cache_file_type == "csv": data = pd.read_csv(cache_file, index_col=0, dtype='unicode')
        elif "xl" in cache_file_type: data = pd.read_excel(cache_file, index_col=0)
        elif cache_file_type == "xml": data = json.load(open(cache_file))
        print(f"Got {name} from local cache.")
        
    else:

        print(f"Downloading {name} ...")

        is_done = [False]
        #working_wheel(is_done)

        try:
            # Download from url
            if file_type == "csv": data = pd.read_csv(url, **kwargs)
            elif "xl" in file_type: data = pd.read_excel(url, **kwargs)
            elif file_type == "xml": data = json.dumps(xmltodict.parse(requests.get(url).content))
        except Exception as e:
            print(url)
            print(e)
        finally:
            is_done[0] = True

        # Try to cache downloaded file
        try:
            if not os.path.exists(config.cache_dir): os.mkdir(config.cache_dir)

            if cache_file_type == "csv": data.to_csv(cache_file)
            elif "xl" in cache_file_type: data.to_excel(cache_file)
            elif cache_file_type == "xml":
                with open(cache_file, 'w') as outfile: outfile.write(data)
            print(f"Cached {name}.")
        except Exception as e:
            print(e)

    return data



# Gives data quality time-related indicator based on time gap from data
def dq_time(from_year, to_year):
    diff = abs(from_year - to_year)

    data_quality = {
        3: 1,
        6: 2,
        10: 3,
        15: 4
    }

    for key in data_quality.keys():
        if diff <= key: return data_quality[key]
    
    return 5 # greater than 15 years time difference
    


class DatabaseConverter:
    
    # Singleton pattern
    _instance = None

    def __new__(cls, *args, **kwargs):

        if isinstance(cls._instance, cls): return cls._instance

        cls._instance = super(DatabaseConverter, cls).__new__(cls, *args, **kwargs)

        print('Instantiated database converter.')

        return cls._instance

    def clone_sqlite_to_excel(self, from_sqlite_file: str, to_excel_file: str, excel_template_file: str = None):
        
        print(f"\nCloning {os.path.basename(from_sqlite_file)} into target {os.path.basename(to_excel_file)}."\
              "\nThis may take a minute...")

        # Check that the target file or template file exists
        if (excel_template_file is None):
            print("Aborted. Must provide a template excel file in input files. Check name is correct in res_config.yaml.")
            return
        
        # Handle numbering if existing excel file
        if os.path.isfile(to_excel_file):
            name, ext = os.path.splitext(to_excel_file)
            n = 1
            while os.path.isfile(f"{name} ({n}){ext}"): n+=1
            to_excel_file = f"{name} ({n}){ext}"

        # Copy template to make target file if target doesn't yet exist
        shutil.copy(excel_template_file, to_excel_file)
        
        # Load the target workbook
        wb = load_workbook(to_excel_file)

        # Connect to the sqlite from file and get data table names
        conn = sqlite3.connect(from_sqlite_file)
        curs = conn.cursor()
        fetched = curs.execute("""SELECT name FROM sqlite_master WHERE type='table'""").fetchall()

        # Skipping output tables, since this was written for input data
        all_tables = [table[0] for table in fetched if (not table[0].startswith('Output'))]

        for sheet in wb.sheetnames:
            if sheet not in all_tables: print(f"Target sheet {sheet} missing from sqlite database.")

        # Copy tables from sqlite to excel target
        for table_name in all_tables:
            
            if table_name not in wb.sheetnames:
                print(f"Table {table_name} missing from target workbook and was ignored.")
                continue
            
            # Get sqlite column names and all data rows, put into pandas dataframe
            rows = curs.execute(f"SELECT * FROM '{table_name}'")
            sql_cols = [desc[0] for desc in rows.description]
            sql_df = pd.DataFrame(data=rows.fetchall(), columns=sql_cols)

            # Get this table from the target excel workbook and its headers (might not be same as sql)
            ws = wb[table_name]
            xl_headers = [cell.value for cell in ws[1]]

            # Flag a warning if a sqlite column does not have a counterpart in the target excel workbook
            for sql_col in sql_cols:
                if sql_col not in xl_headers: print(f"Sqlite column {sql_col} missing from spreadsheet table {table_name} and was ignored.")
            
            # Prepare a target dataframe matching the target excel workbook template
            xl_df = pd.DataFrame(columns=xl_headers)
            for xl_head in xl_headers:

                # Flag a warning if sqlite table is missing a column that is in the excel workbook
                # This might not be an issue, but maybe that column should be added to the sqlite database
                if xl_head not in sql_cols:
                    print(f"Spreadsheet column {xl_head} missing from sqlite table {table_name}.")
                    continue
                
                # Fill target workbook dataframe with data from sqlite dataframe
                xl_df[xl_head] = sql_df[xl_head]

            # Clear the target excel table
            ws.delete_rows(2, ws.max_row)

            # Refill the target excel table with data from sqlite
            for index, row in xl_df.iterrows():
                ws.append(row.values.tolist())

        wb.save(to_excel_file)



def animate_wheel(is_done):
    for c in itertools.cycle(['|', '/', '-', '\\']):
        time.sleep(0.1)
        if is_done[0]:
            break
        sys.stdout.write('\r' + c)
        sys.stdout.flush()
        time.sleep(0.1)
    sys.stdout.write('\r')
    sys.stdout.flush()



def working_wheel(is_done):
    t = threading.Thread(target=animate_wheel, args=(is_done,))
    t.start()