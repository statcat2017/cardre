import pandas as pd
import numpy as np
from sklearn.cluster import KMeans

import importCSV





df, UID, response = importCSV.load_csv('input/titanic/train.csv', None, "Class")

#replace all nans with none
df = df.where(pd.notna(df), None)

df = df.select_dtypes(include=['number'])


    
kmeans = KMeans(n_clusters = 6)

kmeans.fit(df)

clusters = kmeans.labels_

for variable, cluster in zip(df.columns, clusters):
    print(f'Variable {variable} is in cluster {cluster}.')







