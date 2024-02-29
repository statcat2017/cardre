import pandas as pd
import numpy as np
import importCSV

yes = ["y","Y","Yes","YES","yes"]
no = ["n","N","No","NO","no"]

df = importCSV.load_csv('input/titanic/train.csv', 'PassengerId', 'Survived')

def typeClassifier(df, col_exclusions):
    cols = {}
    for column in df.columns:
        if column in col_exclusions:
            print(f"Skipping excluded variable {column}\n")
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

#determines whether a numeric variable is continuous or discrete
#defaults to 20 or fewer bins = discrete and more than 20 bins = continuous
def contOrDiscrete(df, independent, tolerance = 20):
    if df[independent].nunique() <= tolerance:
        return "Discrete"
    return "Continuous"

def fineClassNumeric(df, independent, bins):
    _, edges = pd.qcut(df[independent], bins, retbins=True)
    df[independent + "_bin"] = pd.qcut(df[independent], bins, labels=edges[:-1])
    df[independent + "_bin"] = df[independent + "_bin"].cat.add_categories('Missing').fillna('Missing')
    return df

def fineClassOrdinal(df, independent):
    df[independent + "_bin"] = df[independent].astype('category').cat.add_categories('Missing').fillna('Missing')
    return df

def fineClassCategorical(df, independent):
    df[independent + "_bin"] = df[independent].astype('category').cat.add_categories('Missing').fillna('Missing')
    return df

colTypes = typeClassifier(df, ['Survived', 'PassengerId'])

for col in colTypes:
    if colTypes[col] == ("Continuous"):
        print(f"Fine classing continuous variable {col}...")
        df = fineClassNumeric(df, col, min(20,df[col].nunique()-1))
    elif colTypes[col] == ("Ordinal"):
        print(f"Fine classing ordinal variable {col}...")
        df = fineClassOrdinal(df, col)
    elif colTypes[col] == ("Categorical"):
        print(f"Fine classing categorical variable {col}...")
        df = fineClassCategorical(df, col)
    else:
        print(f"Skipping fine classing for {col} as it requires different methodoloy")

