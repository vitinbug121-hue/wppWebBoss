from pymongo import MongoClient
import os
from dotenv import load_dotenv
load_dotenv()
c = MongoClient(os.environ["MONGODB_URI"], serverSelectionTimeoutMS=10000)
print(c.admin.command("ping"))