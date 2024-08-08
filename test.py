import pandas as pd
from functions import *
id = 1
url = f'https://www.wenku8.net/novel/{id//1000}/{id}/index.htm'
webdata = GetData(url)
print(url)
df = pd.DataFrame({'id':[],'Name':[], 'Author':[], 'Status':[]})
res = []
print(df)