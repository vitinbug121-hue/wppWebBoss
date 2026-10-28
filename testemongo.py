import os, json
from dotenv import load_dotenv
from pymongo import MongoClient, UpdateOne

load_dotenv()
CONTA = "alvesguilherme838@gmail.com"
ARQUIVO = r"H:\Meu Drive\Sistema Captura WPP\contas\alvesguilherme838@gmail.com\database_vendas.json"  # ajuste o caminho
SAIDA_CONFLITOS = "conflitos.json"


def vazio(v):
    return v is None or (isinstance(v, str) and v.strip() == "")


def igual(a, b):
    return str(a).strip() == str(b).strip()


local = json.load(open(ARQUIVO, encoding="utf-8"))
c = MongoClient(os.environ["MONGODB_URI"], serverSelectionTimeoutMS=10000)
col = c[os.environ.get("MONGODB_DB", "coletor_pro")]["vendas"]
nuvem = {d["order_id"]: d["dados"] for d in col.find({"conta": CONTA})}

ops, conflitos = [], {}
campos_preenchidos = 0
pedidos_preenchidos = 0

for k, arq in local.items():
    if k not in nuvem:
        continue  # pedidos só no arquivo são tratados por outro script
    atl = nuvem[k]
    novo = dict(atl)
    conf = {}
    preencheu = False

    for campo, v_arq in arq.items():
        if vazio(v_arq):
            continue
        v_atl = atl.get(campo)
        if vazio(v_atl):
            novo[campo] = v_arq
            campos_preenchidos += 1
            preencheu = True
        elif not igual(v_atl, v_arq):
            conf[campo] = {"atlas": v_atl, "arquivo": v_arq}

    if preencheu:
        pedidos_preenchidos += 1
    if conf:
        conflitos[k] = conf
    if novo != atl:
        ops.append(UpdateOne({"_id": f"{CONTA}|{k}"}, {"$set": {"dados": novo}}))

with open(SAIDA_CONFLITOS, "w", encoding="utf-8") as f:
    json.dump(conflitos, f, ensure_ascii=False, indent=2)

print(f"Pedidos a atualizar: {len(ops)}")
print(f"  com campos vazios preenchidos: {pedidos_preenchidos} ({campos_preenchidos} campos)")
print(f"Pedidos com valores conflitantes (mantidos do Atlas): {len(conflitos)}")
print(f"Lista completa salva em {SAIDA_CONFLITOS}")

if ops and input("Confirmar gravação? (s/n): ").strip().lower() == "s":
    res = col.bulk_write(ops, ordered=False)
    print("Atualizados:", res.modified_count)
else:
    print("Nada gravado.")