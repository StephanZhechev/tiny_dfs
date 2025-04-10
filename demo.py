# Assumes that all the dependencies from client_api/requirements.py
# have been installed. All two of them.

import json
import pandas as pd
from client_api import tinyGFSClient

def run_demo():
    client = tinyGFSClient(client_name="user")
    client.getStatus()

    df = pd.DataFrame({'a': [1, 2, 3], 'b': [4, 5, 6]}).to_json()
    ls = json.dumps(list(range(1000000)))

    res = client.uploadFile(df, 'df')
    print("Uploading df response", res)

    res = client.uploadFile(ls, "ls")
    print("Uploading list response", res)

if __name__ == "__main__":
    run_demo()
    print("The end")
