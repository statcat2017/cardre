import pandas as pd
import numpy as np
import importCSV

in_df = importCSV.load_csv('input/titanic/train.csv', 'PassengerId', 'Survived')

def iv_numeric_series(in_df, independent, response, null_value, bins=20):
    bins = np.linspace(in_df[independent].min(), in_df[independent].max()+1, bins)
    bins = np.round(bins).astype(int)
    bins = np.append(bins, null_value)

    # Replace missing values in the independent variable with the null value
    in_df[independent] = in_df[independent].fillna(null_value)

    # Create the bin_df
    bin_df = pd.DataFrame(columns=['Variable', 'Bin_Start_Inc', 'Bin_End_Exc'])
    bin_df['Bin_Start_Inc'] = bins[:-1]
    bin_df['Bin_End_Exc'] = bins[1:]
    
        # Remove last bin
    bin_df = bin_df[:-1]
    bin_df = pd.concat([bin_df, pd.DataFrame({'Bin_Start_Inc': [null_value], 'Bin_End_Exc': [null_value]})], ignore_index=True)

    #Create the bin count
    bin_df['Bin_Count'] = bin_df.apply(lambda x: in_df[(in_df[independent] >= x['Bin_Start_Inc']) & (in_df[independent] < x['Bin_End_Exc'])].shape[0], axis=1)
    #Update the bin count for the final null value bin only
    bin_df.loc[bin_df['Bin_Start_Inc'] == null_value, 'Bin_Count'] = (in_df[independent] == null_value).sum()

    # Create the bads and goods by bin
    bin_df['Bin_Bad'] = bin_df.apply(lambda x: in_df[(in_df[independent] >= x['Bin_Start_Inc']) & (in_df[independent] < x['Bin_End_Exc'])][response].sum(), axis=1)
    #Update bin bads for the final null value bin only
    bin_df.loc[bin_df['Bin_Start_Inc'] == null_value, 'Bin_Bad'] = in_df[in_df[independent] == null_value][response].sum()  
    bin_df['Bin_Good'] = bin_df['Bin_Count'] - bin_df['Bin_Bad']

    #create bad rate and good rate by bin
    bin_df['Bin_Bad_Rate'] = bin_df['Bin_Bad'] / bin_df['Bin_Count']
    bin_df['Bin_Good_Rate'] = bin_df['Bin_Good'] / bin_df['Bin_Count']

    #create bin iv
    bin_df['IV'] = (bin_df['Bin_Bad_Rate'] - bin_df['Bin_Good_Rate']) * np.log(bin_df['Bin_Bad_Rate'] / bin_df['Bin_Good_Rate'])
    #add variable name
    bin_df['Variable'] = independent

    return bin_df

#if if_df exists create it as the output of the function, otherwise append to it

def numeric_series(in_df,independent, response,null_value = -1, bins = 20):
    try:
        iv_df
    except NameError:
        return iv_numeric_series(in_df, independent, response, null_value, bins)
    else:
        return pd.concat([iv_df, iv_numeric_series(in_df, independent, response, null_value, bins)], ignore_index=True)

iv_df = numeric_series(in_df, 'Fare', 'Survived', -1,50)
iv_df = numeric_series(in_df, 'Age', 'Survived', -1,20)

print(iv_df)
