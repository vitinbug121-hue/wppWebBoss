"""
extrair_conversas_pos_boleto.py
--------------------------------
Percorre as contas ATIVAS da pasta 'contas/', busca (no Mercado Livre) a
conversa COMPLETA de cada pedido que já teve boleto enviado e vai salvando
tudo em um .txt AOS POUCOS, conta por conta, pedido por pedido.

Comportamento:
  1) Salva a conversa inteira de cada pedido (do início ao fim), sem cortar
     no código de barras do boleto.
  2) Percorre todas as contas ativas; qualquer conta com erro (config/token/
     banco de dados faltando, ou exceção inesperada) é pulada e o script
     segue para a próxima.
  3) Sem limite de quantidade. Cada pedido é gravado no .txt (com flush
     imediato em disco) assim que sua conversa é obtida, e as estatísticas
     em CSV são atualizadas ao final de cada conta. Isso permite interromper
     o script a qualquer momento (Ctrl+C) sem perder o que já foi extraído
     até ali.

Não depende do main.py / Tkinter — é 100% standalone.
"""

import os
import csv
import json
import time
import requests
from datetime import datetime, timezone

# ==========================================================
# CONFIGURAÇÃO - AJUSTE SE NECESSÁRIO

# ==========================================================

def _encontrar_accounts_dir():
    candidatos = []
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidatos.append(os.path.join(script_dir, 'contas'))
    candidatos.append(os.path.join(os.path.dirname(script_dir), 'contas'))
    candidatos.append(os.path.join(os.getcwd(), 'contas'))
    candidatos.append(os.path.join(os.path.dirname(os.getcwd()), 'contas'))

    for c in candidatos:
        if os.path.exists(c):
            return c
    return candidatos[0]


ACCOUNTS_DIR = _encontrar_accounts_dir()

OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'conversas_pos_boleto.txt')
STATS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'estatisticas_conversao.csv')

DELAY_ENTRE_REQUESTS = 0.4
INCLUIR_BOLETO_PAGO = True
INCLUIR_BOLETO_NAO_PAGO = True


# ==========================================================
# FUNÇÕES AUXILIARES DE CONTA / CONFIG
# ==========================================================

def get_registered_emails():
    emails = []
    if os.path.exists(ACCOUNTS_DIR):
        for pasta in os.listdir(ACCOUNTS_DIR):
            caminho = os.path.join(ACCOUNTS_DIR, pasta)
            if os.path.isdir(caminho):
                emails.append(pasta)
    return sorted(emails)


def get_account_metadata(email):
    path = os.path.join(ACCOUNTS_DIR, email, 'config_conta.json')
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def is_account_active(email):
    metadata = get_account_metadata(email)
    ativo = metadata.get('ATIVO')
    return True if ativo is None else bool(ativo)


def carregar_config_cliente(folder):
    path = os.path.join(folder, 'config_conta.json')
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def carregar_db_pasta(folder):
    path = os.path.join(folder, 'database_vendas.json')
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def carregar_tokens_ml(folder):
    path = os.path.join(folder, 'ml_tokens_autorizacao.json')
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def salvar_tokens_ml(folder, dados):
    path = os.path.join(folder, 'ml_tokens_autorizacao.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(dados, f, indent=4)


def renovar_access_token(folder, config):
    tokens = carregar_tokens_ml(folder)
    if not tokens or not config:
        return None

    url = "https://api.mercadolibre.com/oauth/token"
    payload = {
        'grant_type': 'refresh_token',
        'client_id': config.get('ML_CLIENT_ID'),
        'client_secret': config.get('ML_CLIENT_SECRET'),
        'refresh_token': tokens.get('refresh_token')
    }
    try:
        res = requests.post(url, data=payload, timeout=15)
        if res.status_code == 200:
            novos_tokens = res.json()
            salvar_tokens_ml(folder, novos_tokens)
            return novos_tokens.get('access_token')
        print(f"    [ERRO] Falha ao renovar token: {res.status_code} - {res.text}")
        return None
    except Exception as e:
        print(f"    [ERRO] Exceção ao renovar token: {e}")
        return None


# ==========================================================
# BUSCA DE CONVERSA COMPLETA (Chat Comum + Reclamação)
# ==========================================================

def _chave_ordenacao_data(msg):
    data = msg.get('data') if isinstance(msg, dict) else None

    if isinstance(data, dict):
        data = (
            data.get('created') or data.get('received') or
            data.get('notified') or data.get('available') or data.get('read')
        )

    if not data or not isinstance(data, str):
        return datetime.min.replace(tzinfo=timezone.utc)

    texto = data.strip()
    if texto.endswith('Z'):
        texto = texto[:-1] + '+00:00'

    try:
        dt = datetime.fromisoformat(texto)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def obter_conversa_completa(order_id, seller_id, token):
    """Retorna a conversa completa (chat comum + reclamação, se houver) já ordenada por data."""
    headers = {"Authorization": f"Bearer {token}"}
    conversa = []
    claim_ids = []

    url_comum = f"https://api.mercadolibre.com/messages/packs/{order_id}/sellers/{seller_id}"
    limit, offset, total = 10, 0, None

    try:
        while True:
            params = {"tag": "post_sale", "limit": limit, "offset": offset}
            res = requests.get(url_comum, headers=headers, params=params, timeout=15)
            if res.status_code != 200:
                break

            dados = res.json()
            msgs = dados.get('messages', []) or []

            status_conversa = dados.get('conversation_status', {})
            if status_conversa.get('claim_ids'):
                claim_ids = status_conversa.get('claim_ids', [])

            for m in msgs:
                sender_id = (
                    m.get('from', {}).get('user_id') or
                    m.get('sender', {}).get('user_id') or
                    m.get('sender_id')
                )
                conversa.append({
                    "texto": m.get('text'),
                    "data": m.get('message_date'),
                    "is_seller": str(sender_id) == str(seller_id),
                })

            paging = dados.get('paging', {}) or {}
            total = paging.get('total', len(msgs) if total is None else total)
            offset += limit

            if not msgs or offset >= (total or 0):
                break
            time.sleep(DELAY_ENTRE_REQUESTS)

    except Exception as e:
        print(f"    [AVISO] Erro no chat comum da ordem {order_id}: {e}")

    for claim_id in claim_ids:
        try:
            url_claim = f"https://api.mercadolibre.com/post-purchase/v1/claims/{claim_id}/messages"
            res = requests.get(url_claim, headers=headers, timeout=15)
            if res.status_code != 200:
                continue

            dados = res.json()
            if isinstance(dados, list):
                msgs_claim = dados
            elif isinstance(dados, dict):
                msgs_claim = dados.get("messages") or dados.get("data") or []
            else:
                msgs_claim = []

            for mc in msgs_claim:
                if not isinstance(mc, dict):
                    continue
                sender = mc.get("sender") if isinstance(mc.get("sender"), dict) else {}
                sender_id = sender.get("id") or sender.get("user_id") or mc.get("sender_id")
                sender_role = str(mc.get("sender_role") or mc.get("role") or sender.get("role") or "").lower()
                conversa.append({
                    "texto": mc.get('message') or mc.get('text'),
                    "data": mc.get('date_created') or mc.get('message_date'),
                    "is_seller": str(sender_id) == str(seller_id) or sender_role in ["respondent", "seller"],
                })
            time.sleep(DELAY_ENTRE_REQUESTS)
        except Exception as e:
            print(f"    [AVISO] Erro na reclamação {claim_id}: {e}")

    conversa.sort(key=_chave_ordenacao_data)
    return conversa


# ==========================================================
# EXECUÇÃO PRINCIPAL
# ==========================================================

def _stats_vazias():
    return {
        "total_boleto_enviado": 0,
        "pagos": 0,
        "nao_pagos": 0,
        "com_conversa_extraida": 0,
        "pagos_com_conversa": 0,
        "nao_pagos_com_conversa": 0,
    }


def _gravar_csv_estatisticas(stats_por_conta, stats_geral):
    with open(STATS_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, delimiter=';')  # ';' abre certinho no Excel PT-BR
        writer.writerow([
            "Conta",
            "Total Boletos Enviados",
            "Boletos Pagos",
            "Boletos Não Pagos",
            "Taxa de Conversão (%)",
            "Conversas Extraídas p/ IA",
        ])

        for email in sorted(stats_por_conta.keys()):
            s = stats_por_conta[email]
            total = s["total_boleto_enviado"]
            taxa = (s["pagos"] / total * 100) if total else 0
            writer.writerow([
                email,
                total,
                s["pagos"],
                s["nao_pagos"],
                f"{taxa:.1f}",
                s["com_conversa_extraida"],
            ])

        total_geral = stats_geral["total_boleto_enviado"]
        taxa_geral = (stats_geral["pagos"] / total_geral * 100) if total_geral else 0
        writer.writerow([])
        writer.writerow([
            "TOTAL GERAL",
            total_geral,
            stats_geral["pagos"],
            stats_geral["nao_pagos"],
            f"{taxa_geral:.1f}",
            stats_geral["com_conversa_extraida"],
        ])


def _imprimir_tabela_estatisticas(stats_por_conta, stats_geral):
    print("\n" + "=" * 78)
    print("TAXA DE CONVERSÃO POR CONTA (boleto enviado -> boleto pago)")
    print("=" * 78)
    cab = f"{'Conta':<32}{'Enviados':>10}{'Pagos':>8}{'Não Pagos':>11}{'Conversão':>12}"
    print(cab)
    print("-" * 78)

    for email in sorted(stats_por_conta.keys()):
        s = stats_por_conta[email]
        total = s["total_boleto_enviado"]
        taxa = (s["pagos"] / total * 100) if total else 0
        nome = (email[:29] + "...") if len(email) > 32 else email
        print(f"{nome:<32}{total:>10}{s['pagos']:>8}{s['nao_pagos']:>11}{taxa:>11.1f}%")

    print("-" * 78)
    total_geral = stats_geral["total_boleto_enviado"]
    taxa_geral = (stats_geral["pagos"] / total_geral * 100) if total_geral else 0
    print(f"{'TOTAL GERAL':<32}{total_geral:>10}{stats_geral['pagos']:>8}{stats_geral['nao_pagos']:>11}{taxa_geral:>11.1f}%")
    print("=" * 78)


def processar_conta(email, out, stats_por_conta, stats_geral):
    """
    Processa uma única conta por completo, escrevendo cada conversa no
    arquivo 'out' já aberto (compartilhado entre todas as contas) IMEDIATAMENTE
    após obtê-la, com flush em disco a cada pedido — assim, se o script for
    interrompido (Ctrl+C) no meio do caminho, nada do que já foi escrito se
    perde.

    Ao final da conta, atualiza stats_por_conta/stats_geral e regrava o CSV
    de estatísticas, para que ele também fique sempre atualizado até onde o
    script chegou.

    Retorna (sucesso, total_processados, total_com_conversa).
    sucesso=False significa que a conta foi pulada (faltou config/token/db)
    e o chamador deve seguir para a próxima conta sem contabilizá-la.
    Qualquer erro inesperado durante o processamento também é tratado pelo
    chamador (main), que pula para a próxima conta.
    """
    folder = os.path.join(ACCOUNTS_DIR, email)
    print(f"=== Conta: {email} ===")

    stats_conta = _stats_vazias()

    config = carregar_config_cliente(folder)
    if not config:
        print("  [SKIP] Sem config_conta.json.")
        return False, 0, 0

    seller_id = config.get('ML_SELLER_ID')
    if not seller_id:
        print("  [SKIP] Sem ML_SELLER_ID configurado.")
        return False, 0, 0

    token = renovar_access_token(folder, config)
    if not token:
        print("  [SKIP] Não foi possível obter access_token.")
        return False, 0, 0

    db = carregar_db_pasta(folder)
    if not db:
        print("  [SKIP] Sem database_vendas.json ou vazio.")
        return False, 0, 0

    pedidos_com_boleto_todos = [
        (oid, dados) for oid, dados in db.items() if dados.get('boleto_enviado')
    ]

    for _, dados in pedidos_com_boleto_todos:
        stats_conta["total_boleto_enviado"] += 1
        if dados.get('boleto_pago'):
            stats_conta["pagos"] += 1
        else:
            stats_conta["nao_pagos"] += 1

    pedidos_para_extrair = [
        (oid, dados) for oid, dados in pedidos_com_boleto_todos
        if (dados.get('boleto_pago') and INCLUIR_BOLETO_PAGO)
        or (not dados.get('boleto_pago') and INCLUIR_BOLETO_NAO_PAGO)
    ]

    print(f"  Pedidos com boleto enviado: {len(pedidos_com_boleto_todos)} "
          f"(pagos: {stats_conta['pagos']}, não pagos: {stats_conta['nao_pagos']})")
    print(f"  Selecionados para extração de conversa: {len(pedidos_para_extrair)}")

    total_processados = 0
    total_com_conversa = 0

    for order_id, dados in pedidos_para_extrair:
        total_processados += 1

        try:
            conversa = obter_conversa_completa(order_id, seller_id, token)
        except Exception as e:
            print(f"    [ERRO] Ordem {order_id}: falha ao buscar conversa: {e}")
            continue

        if not conversa:
            continue

        total_com_conversa += 1
        stats_conta["com_conversa_extraida"] += 1

        pago = bool(dados.get('boleto_pago'))
        if pago:
            stats_conta["pagos_com_conversa"] += 1
        else:
            stats_conta["nao_pagos_com_conversa"] += 1

        status_pagamento = "PAGO" if pago else "NÃO PAGO"

        out.write(f"--- Conta: {email} | Pedido: {order_id} | Status do boleto: {status_pagamento} ---\n")
        for m in conversa:
            texto = (m.get('texto') or '').strip()
            if not texto:
                continue
            quem = "VENDEDOR" if m.get('is_seller') else "CLIENTE"
            out.write(f"[{quem}] {texto}\n")
        out.write("\n" + "-" * 70 + "\n\n")

        # Grava em disco na hora — não espera o script inteiro terminar.
        out.flush()
        os.fsync(out.fileno())

        time.sleep(DELAY_ENTRE_REQUESTS)

    # Atualiza e regrava as estatísticas assim que a conta termina, para que
    # o CSV também reflita o progresso mesmo que o script pare logo depois.
    stats_por_conta[email] = stats_conta
    for chave in stats_geral:
        stats_geral[chave] += stats_conta[chave]
    _gravar_csv_estatisticas(stats_por_conta, stats_geral)

    print()
    return True, total_processados, total_com_conversa


def main():
    emails_ativos = [e for e in get_registered_emails() if is_account_active(e)]

    if not emails_ativos:
        print("Nenhuma conta ativa encontrada em:", ACCOUNTS_DIR)
        return

    print(f"Contas ativas encontradas: {len(emails_ativos)}")
    print(f"Pasta de contas: {ACCOUNTS_DIR}")
    print(f"Arquivo de saída (conversas): {OUTPUT_FILE}")
    print(f"Arquivo de saída (estatísticas): {STATS_FILE}")
    print("Modo: processa todas as contas ativas (pulando as que derem erro). "
          "Sem limite — o .txt e o CSV vão sendo salvos aos poucos, então dá "
          "pra interromper com Ctrl+C a qualquer momento sem perder o que já "
          "foi extraído.\n")

    total_pedidos_processados = 0
    total_pedidos_com_conversa = 0
    contas_com_sucesso = 0
    contas_puladas = 0
    interrompido = False

    stats_por_conta = {}
    stats_geral = _stats_vazias()

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as out:
        out.write("CONVERSAS COMPLETAS DE PEDIDOS COM BOLETO ENVIADO\n")
        out.write(f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n")
        out.write("=" * 70 + "\n\n")
        out.flush()

        for email in emails_ativos:
            try:
                sucesso, total_processados, total_com_conversa = processar_conta(
                    email, out, stats_por_conta, stats_geral
                )
            except KeyboardInterrupt:
                print(f"\n[INTERROMPIDO] Execução interrompida pelo usuário durante a conta {email}. "
                      f"O que já foi extraído até agora está salvo.\n")
                interrompido = True
                break
            except Exception as e:
                print(f"  [ERRO] Falha inesperada processando a conta {email}: {e}")
                print("  Pulando para a próxima conta...\n")
                contas_puladas += 1
                continue

            if not sucesso:
                contas_puladas += 1
                continue

            contas_com_sucesso += 1
            total_pedidos_processados += total_processados
            total_pedidos_com_conversa += total_com_conversa

    _gravar_csv_estatisticas(stats_por_conta, stats_geral)
    _imprimir_tabela_estatisticas(stats_por_conta, stats_geral)

    print("\nRESUMO DA EXTRAÇÃO DE TEXTO")
    if interrompido:
        print("  (execução interrompida manualmente antes de terminar todas as contas)")
    print(f"  Contas processadas com sucesso        : {contas_com_sucesso}")
    print(f"  Contas puladas (erro ou config faltando): {contas_puladas}")
    print(f"  Pedidos verificados (para extração)   : {total_pedidos_processados}")
    print(f"  Pedidos com conversa extraída          : {total_pedidos_com_conversa}")
    print(f"  Arquivo de conversas                   : {OUTPUT_FILE}")
    print(f"  Arquivo de estatísticas                : {STATS_FILE}")


if __name__ == "__main__":
    main()