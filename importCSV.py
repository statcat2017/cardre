import pandas as pd
import os
import sys

def load_csv(data_file="", UID = "", outcomes = ""):
    if data_file == "":
        data_file = input('Enter the path of the file you want to load: ')

    try:
        df = pd.read_csv(data_file)
    except FileNotFoundError:
        print('File not found')
        sys.exit()
    except Exception as e:
        print(f'Error loading DataFrame: {str(e)}')
        sys.exit()

    if UID =="":
        UID = input('Enter the name of the unique identifer: ')

    while UID not in df.columns:
        print(f'Field {UID} not found in DataFrame')
        UID = input('Enter the name of the field containing the outcomes\nor "None" to create generic UID\nor "quit" to exit: ')
        if UID == "quit":
            sys.exit()
        if UID == "None":
            UID = "UID"
            df['UID'] = range(1, len(df) + 1)
            print(f"Created generic UID field {UID}")

    if outcomes == "":
        outcomes = input('Enter the name of the field containing the outcomes: ')

    while outcomes not in df.columns:
        print(f'Field {outcomes} not found in DataFrame')
        outcomes = input('Enter the name of the field containing the outcomes: ')
        if outcomes == "quit":
            sys.exit()

    print(f"Loaded {len(df)} rows and {len(df.columns)} columns")

    return df, UID, outcomes





