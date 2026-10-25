import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()
c = MongoClient(os.environ["MONGODB_URI"], serverSelectionTimeoutMS=10000)
db = c[os.environ.get("MONGODB_DB", "coletor_pro")]
s = db.command("collStats", "vendas")

print("Documentos:", s["count"])
print("Tamanho médio por pedido (bytes):", round(s["avgObjSize"]))
print("Dados (MB):", round(s["size"] / 1024 / 1024, 2))
print("Armazenado (MB):", round(s["storageSize"] / 1024 / 1024, 2))
print("Índices (MB):", round(s["totalIndexSize"] / 1024 / 1024, 2))