from common_imports import pd, np, sns, plt
import importCSV

yes = ["y","Y","Yes","YES","yes"]
no = ["n","N","No","NO","no"]

def contOrDiscrete(df, independent, tolerance = 20):
    if df[independent].nunique() <= tolerance:
        return "Discrete"
    return "Continuous"

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

def ivFromVariable(df,variable,response):
    iv_df = df[[variable, response]].value_counts().reset_index()
    iv_df['Response'] = (iv_df[response] * iv_df['count'])
    iv_df = iv_df.groupby(variable, observed=False).sum().drop(response, axis=1)
    iv_df['No_Response'] = iv_df['count'] - iv_df['Response']
    iv_df['Percent_Response'] = iv_df['Response'] / iv_df['Response'].sum()
    iv_df['Percent_No_Response'] = iv_df['No_Response'] / iv_df['No_Response'].sum()
    iv_df['WOE'] = np.log(iv_df['Percent_Response'] / iv_df['Percent_No_Response'])
    iv_df['IV'] = (iv_df['Percent_Response'] - iv_df['Percent_No_Response']) * iv_df['WOE']
    iv_df.replace([np.inf, -np.inf], np.nan, inplace=True)
    iv_df['Variable'] = variable
    return iv_df
    
    #return (variable,iv_df['IV'].sum())

def fineClass(path,UID="",response=""):
    df, UID, response = importCSV.load_csv(path, UID, response)
    colTypes = typeClassifier(df, [response, UID])
    for col in colTypes:
        if colTypes[col] == "Continuous":
            print(f"Fine classing continuous variable {col}...")
            df = fineClassNumeric(df, col, min(20,df[col].nunique()-1))
        elif colTypes[col] == "Ordinal":
            print(f"Fine classing ordinal variable {col}...")
            df = fineClassOrdinal(df, col)
        elif colTypes[col] == "Categorical":
            print(f"Fine classing categorical variable {col}...")
            df = fineClassCategorical(df, col)
        else:
            print(f"Skipping fine classing for {col} as it requires different methodology")
    
    allIVs = []
    for column in df.columns:
        if column.endswith('_bin'):
                print(f"Calculating IV for Variable {column}...")
                allIVs.append(ivFromVariable(df,column,response))
    IV_table = pd.concat(allIVs)
    print(IV_table.head(10))

    #group IV_table by Variable and find the sum of IV
    var_ivs = IV_table.groupby('Variable').IV.sum().reset_index()
    var_ivs = var_ivs.sort_values(by='IV',ascending=False)
    print(var_ivs)

    plt.figure(figsize=(5,5))
    sns.barplot(x='IV',y='Variable',data=var_ivs)
    plt.title('IV by Variable')
    plt.show()
    return IV_table

fineClass('input/credit/creditcard.csv')
    


