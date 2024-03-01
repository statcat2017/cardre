import pandas as pd
import numpy as np
import importCSV
import seaborn as sns
import matplotlib.pyplot as plt

#returns a dataframe with a new column that is 1 if the value is above zero, 0 if its zero, preserving nulls
def zeroOrValue(df,independent):
    df[independent + "_zeroOrValue"] = df[independent].apply(lambda x: 1 if x > 0 else 0 if x <= 0 else x)
    return df
    

    

