import pandas as pd
import numpy as np
import importCSV

yes = ["y","Y","Yes","YES","yes"]
no = ["n","N","No","NO","no"]

df = importCSV.load_csv('input/titanic/train.csv', 'PassengerId', 'Survived')

#iteratively print the datatype of each column in the dataframe
def typeClassifier(df,response):
    cols = {}
    for column in df.columns:
        if column == response:
            print(f"Skipping response variable {response}")
            continue
        print(f"Evaluating {column}: {df[column].dtype}")
        if df[column].dtype in ['int64','float64']:
            print(f"Determined {column} is numeric by default - classifying based on unique values")
            if contOrDiscrete(df, column) == "Continuous":
                print(f"{column} has {df[column].nunique()} unique values - classifying as continuous\n") 
                cols[column] = "Continuous"
            else:
                print(f"{column} has {df[column].nunique()} unique values - classifying as ordinal\n")
                cols[column] = "Ordinal"
        if df[column].dtype == 'object':
            print(f"Determined {column} contains string - classifying based on unique values")
            if contOrDiscrete(df, column,20) == "Discrete":
                print(f"{column} has {df[column].nunique()} unique values - classifying as categorical\n")
                cols[column] = 'Categorical'
            else:
                print(f"{column} has {df[column].nunique()} unique values - skipping as likely descriptive\n")
                continue
    return cols

def fineClassNumeric(df, independent, bins):
    _, edges = pd.qcut(df[independent], bins, retbins=True)
    df[independent + "_bin"] = pd.qcut(df[independent], bins, labels=edges[:-1])
    df[independent + "_bin"] = df[independent + "_bin"].cat.add_categories('Missing').fillna('Missing')
    return df

#determines whether a numeric variable is continuous or discrete
#defaults to 20 or fewer bins = discrete and more than 20 bins = continuous
def contOrDiscrete(df, independent, tolerance = 20):
    if df[independent].nunique() <= tolerance:
        return "Discrete"
    return "Continuous"

colTypes = typeClassifier(df, 'Survived')
print(colTypes)
print(df.dtypes)