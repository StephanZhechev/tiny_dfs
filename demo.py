# Assumes that all the dependencies from client_api/requirements.py
# have been installed. All two of them.

import json
from client_api import tinyGFSClient

client = tinyGFSClient(client_name="user")
client.getStatus()


