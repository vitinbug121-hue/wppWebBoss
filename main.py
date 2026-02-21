import tkinter as tk
from tkinter import scrolledtext, messagebox, simpledialog, filedialog
#from turtle import tur
import requests
import json
import os
import re
import webbrowser
from datetime import datetime, timedelta
from dotenv import load_dotenv
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.ticker import MaxNLocator
import time

# Load variables from .env file
load_dotenv()

# ==========================================
# CONFIGURAÇÕES DE API (PREENCHA AQUI)
# ==========================================
ML_CLIENT_ID = os.getenv("ML_CLIENT_ID") # Seu Client ID do Mercado Livre
ML_CLIENT_SECRET = os.getenv("ML_CLIENT_SECRET")
ML_REDIRECT_URI = os.getenv("ML_REDIRECT_URI")
ML_SELLER_ID = os.getenv("ML_SELLER_ID") # ID do vendedor no Mercado Livre

WA_TOKEN = 'SEU_TOKEN_PERMANENTE_META'
WA_PHONE_ID = 'SEU_PHONE_NUMBER_ID'
WA_TEMPLATE_NAME = 'atendimento_cliente_ml' # Deve estar aprovado na Meta

# Arquivos locais
DB_FILE = 'database_vendas.json'
TOKEN_FILE = 'ml_tokens_autorizacao.json'

class GerenciadorTokenML:
    """Responsável por toda a autenticação OAuth 2.0 do Mercado Livre"""
    @staticmethod
    def salvar_tokens(dados):
        with open(TOKEN_FILE, 'w') as f:
            json.dump(dados, f, indent=4)

    @staticmethod
    def carregar_tokens():
        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE, 'r') as f:
                return json.load(f)
        return None

    def renovar_access_token(self):
        tokens = self.carregar_tokens()
        if not tokens: return None
        
        url = "https://api.mercadolibre.com/oauth/token"
        payload = {
            'grant_type': 'refresh_token',
            'client_id': ML_CLIENT_ID,
            'client_secret': ML_CLIENT_SECRET,
            'refresh_token': tokens['refresh_token']
        }
        try:
            res = requests.post(url, data=payload, timeout=15)
            if res.status_code == 200:
                novos_tokens = res.json()
                self.salvar_tokens(novos_tokens)
                return novos_tokens['access_token']
            return None
        except:
            return None

class AppColetorPro:
    def __init__(self, root):
        self.root = root
        self.root.title("SISTEMA FULL DATA - ML & WHATSAPP API")
        self.root.geometry("1100x800")
        self.auth_ml = GerenciadorTokenML()
        
        self.setup_ui()

    def setup_ui(self):
        # --- Header ---
        header = tk.Frame(self.root, bg="#212121", height=60)
        header.pack(fill=tk.X)
        tk.Label(header, text="PAINEL DE CONTROLE DE LEADS", fg="white", bg="#212121", font=("Arial", 14, "bold")).pack(pady=15)

        # --- Seção de Inputs (Novos Campos) ---
        input_frame = tk.LabelFrame(self.root, text=" Configurações de Busca e Envio ", font=("Arial", 10, "bold"), padx=10, pady=10)
        input_frame.pack(fill=tk.X, padx=20, pady=10)

        # Layout em Grid para os campos
        self.var_prazo = tk.StringVar()
        self.var_rastreio = tk.StringVar()
        self.var_pag_inicial = tk.StringVar(value="0")

        tk.Label(input_frame, text="Prazo Entrega:").grid(row=0, column=0, sticky="w", padx=5)
        tk.Entry(input_frame, textvariable=self.var_prazo, width=20).grid(row=0, column=1, padx=10)

        tk.Label(input_frame, text="Cód. Rastreio:").grid(row=0, column=2, sticky="w", padx=5)
        tk.Entry(input_frame, textvariable=self.var_rastreio, width=25).grid(row=0, column=3, padx=10)

        tk.Label(input_frame, text="Página Inicial (Offset):").grid(row=0, column=4, sticky="w", padx=5)
        tk.Entry(input_frame, textvariable=self.var_pag_inicial, width=10).grid(row=0, column=5, padx=10)

        # --- Container de Botões ---
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=10)

        estilo = {"width": 20, "height": 2, "font": ("Arial", 9, "bold")}

        tk.Button(btn_frame, text="AUTORIZAR ML", command=self.fluxo_autorizacao_ml, bg="#9C27B0", fg="white", **estilo).grid(row=0, column=0, padx=5)
        tk.Button(btn_frame, text="PROCESSAMENTO ALL", command=self.passo_1_solicitar, bg="#1976D2", fg="white", **estilo).grid(row=0, column=1, padx=5)
        tk.Button(btn_frame, text="DASHBOARD", command=self.abrir_dashboard_vendas, bg="#4CAF50", fg="white", **estilo).grid(row=0, column=2, padx=5)
        tk.Button(btn_frame, text="EXPORTAR EXCEL", command=self.exportar_para_excel, bg="#2E7D32", fg="white", **estilo).grid(row=0, column=3, padx=5)

        # --- Log ---
        self.log = scrolledtext.ScrolledText(self.root, height=25, width=140, font=("Consolas", 9), bg="#F5F5F5")
        self.log.pack(pady=10, padx=20)

    def logger(self, msg, tag="INFO"):
        time = datetime.now().strftime("%H:%M:%S")
        self.log.insert(tk.END, f"[{time}] [{tag}] {msg}\n")
        self.log.see(tk.END)
        self.root.update_idletasks()

    # --- LÓGICA DE AUTENTICAÇÃO ---
    def fluxo_autorizacao_ml(self):
        url = f"https://auth.mercadolibre.com/authorization?response_type=code&client_id={ML_CLIENT_ID}&redirect_uri={ML_REDIRECT_URI}"
        webbrowser.open(url)
        self.logger("Navegador aberto. Autorize e cole o código 'TG-...' abaixo.")
        
        codigo = simpledialog.askstring("OAuth ML", "Insira o código gerado na URL (code=...):")
        if codigo:
            url_token = "https://api.mercadolibre.com/oauth/token"
            data = {
                'grant_type': 'authorization_code',
                'client_id': ML_CLIENT_ID,
                'client_secret': ML_CLIENT_SECRET,
                'code': codigo,
                'redirect_uri': ML_REDIRECT_URI
            }
            res = requests.post(url_token, data=data)
            if res.status_code == 200:
                self.auth_ml.salvar_tokens(res.json())
                self.logger("Tokens salvos com sucesso!", "SUCESSO")
            else:
                self.logger(f"Erro na troca de código: {res.text}", "ERRO")

    def get_token_ml(self):
        token = self.auth_ml.renovar_access_token()
        if not token:
            self.logger("Não foi possível obter um token válido. Autorize novamente.", "ALERTA")
        return token

    def buscar_vendas_paginadas(self, seller_id, access_token, offset_inicial=0, limite_maximo=1000):
        url_base = "https://api.mercadolibre.com/orders/search"
        limit_por_request = 50
        current_offset = int(offset_inicial) # Garante que é um inteiro
        
        headers = {"Authorization": f"Bearer {access_token}"}
        todos_os_pedidos = []

        while True:
            # A URL e os parâmetros devem ser montados aqui dentro para atualizar o offset
            params = {
                "seller": seller_id,
                "order.status": "paid",
                "offset": current_offset,
                "limit": limit_por_request
            }

            try:
                self.logger(f"Buscando offset {current_offset}...")
                # Passamos os params separadamente para o requests montar a URL corretamente
                response = requests.get(url_base, headers=headers, params=params)
                response.raise_for_status()
                
                data = response.json()
                resultados = data.get("results", [])

                if not resultados:
                    self.logger("Nenhum pedido encontrado nesta faixa.")
                    break

                todos_os_pedidos.extend(resultados)
                break
                total_disponivel = data.get("paging", {}).get("total", 0)
                current_offset += limit_por_request

                if current_offset >= total_disponivel or current_offset >= limite_maximo:
                    self.logger(f"Busca finalizada. Total capturado: {len(todos_os_pedidos)}")
                    break
                
                time.sleep(1) # Delay leve para evitar 429

            except requests.exceptions.RequestException as e:
                self.logger(f"Erro na requisição: {e}", "ERRO")
                break

        return todos_os_pedidos
    
    # --- PASSO 1: SOLICITAÇÃO ---
    def passo_1_solicitar(self):
        token = self.get_token_ml()
        if not token: 
            return
        
        # --- SOLICITAÇÃO DO PRAZO AO USUÁRIO ---
        prazo_usuario = self.var_prazo.get()
        codigo_rastreio = self.var_rastreio.get()
        pagInicial = self.var_pag_inicial.get()
        
    
        # Se o usuário clicar em cancelar ou deixar vazio, interrompe o processo
        if not prazo_usuario or not codigo_rastreio or not pagInicial:
            self.logger("Operação cancelada: O prazo de entrega, código de rastreio e página inicial são obrigatórios.", "AVISO")
            return
        msg_padrao = f"Olá, tudo bem? O frete é grátis para todo Brasil e o prazo estimado de entrega é até {prazo_usuario}. Lembrando que os produtos são importados, vem de fora do país! Vamos fazer o envio e mandar o código de rastreio. \n \n \n A transportadora precisa do seu telefone pra preencher os seus dados de entrega e enviar o código de rastreio pra você acompanhar."
        
        self.logger("Iniciando varredura de vendas via /orders/search...")
        headers = {
            "Authorization": f"Bearer {token}"
        }
        pedidos = self.buscar_vendas_paginadas(ML_SELLER_ID, token, offset_inicial=pagInicial)
        
        try:
            db = self.carregar_db()
            enviados = 0

            for pedido in pedidos:
                # Pegamos o ID da ordem (ou pack_id se preferir, mas seguindo sua instrução: order_id)
                #se o array de pedido tiver na posição 10 parar o loop e encerrar para um teste
                if pedidos.index(pedido) >= 10:
                    self.logger("Limite de 10 pedidos atingido para teste. Encerrando loop.")
                    break
                order_id = str(pedido['id'])
                buyer_id = str(pedido.get('buyer', {}).get('id'))
                nome_prod = str(pedido['payments'][0]['reason']) 
                valor = str(pedido['total_amount'])
                corProduto = str(pedido['order_items'][0]['item']['variation_attributes'][0]['value_name'])
                # APOS 2 OU 3 DIAS DO ENVIO DO CODIGO DE RASTREIO, ENVIAR MSG E BOLETO PARA PAGAMENTO DE TAXA E SALVAR NO DB QUE O BOLETO FOI ENVIADO
                url_msg = f"https://api.mercadolibre.com/messages/packs/{order_id}/sellers/{ML_SELLER_ID}?tag=post_sale"
                # Se a ordem não existe no DB, inicializamos como dicionário vazio
                if order_id not in db:
                    db[order_id] = {}
                
                if order_id in db and (db[order_id].get('rastreio_enviado') and db[order_id].get('data_rastreio')):
                    data_rastreio = db[order_id].get('data_rastreio')
                    try:
                        data_envio = datetime.strptime(data_rastreio, "%d/%m/%Y %H:%M")
                        diferenca = datetime.now() - data_envio
                        if diferenca.days >= 3 and not db[order_id].get('boleto_enviado'):
                            self.logger(f"Enviando boleto para pagamento de taxa para a ordem {order_id}...")
                            df = pd.read_excel(r"C:\Users\mathe\Meu Drive\Sistema JV V1\Nova pasta\dist\registros_pedidos.xlsx")
                            boleto_numero = None
                            for index, row in df.iterrows():
                                if str(row['Order ID']) == order_id and str(row['Boleto Usado']) == 'FALSE':
                                    boleto_numero = str(row['Código'])
                                    break

                            payloadBoleto = {
                                "from": {
                                    "user_id": ML_SELLER_ID
                                },
                                "to": {
                                    "user_id": buyer_id
                                },
                                "text": f"""
                                    ( Living Shop )
                                    Boa tarde, tudo bem?

                                    O seu painel importado chegou no Brasil. 🥳
                                    Porém, a receita federal taxou o seu produto no valor de R$ 138,98.

                                    É necessário ser paga essa taxa, para liberar o seu pedido. Caso seja pago hoje, o seu pedido chegará nessa quarta, 25. 😉
                                    
                                    O pagamento é feito somente pelo boleto do Mercado Pago que enviamos, a transportadora só está aceitando boleto do Mercado Pago
                                    com a segurança da plataforma!
                                    
                                    >>> {boleto_numero} <<<
                                """
                            }
                            # --- ENVIO DA MENSAGEM (Caso não esteja no DB e não esteja no Chat) ---
                            envio = requests.post(url_msg, json=payloadBoleto, headers=headers)
                            if envio.status_code in [200, 201]:
                                db[order_id]['boleto_enviado'] = True
                                db[order_id]['data_boleto'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                                self.logger(f"Boleto enviado com sucesso para a ordem {order_id}!")
                                continue
                            else:
                                self.logger(f"Falha ao enviar boleto para a ordem {order_id}: {envio.text}", "ERRO")
                    except Exception as e:
                        self.logger(f"Erro ao verificar data de envio do rastreio para a ordem {order_id}: {str(e)}", "ERRO")
                
                    
           
                #VERIFICAR SE A DATA INICIAL SE PASSOU 4 OU 5 DIAS ENVIAR CODIGO DE RASTREIO 
                if order_id in db and (db[order_id].get('solicitado') and db[order_id].get('data_solicitacao_inicial')):
                    data_solicitacao_inicial = db[order_id].get('data_solicitacao_inicial')
                    try:
                        data_envio = datetime.strptime(data_solicitacao_inicial, "%d/%m/%Y %H:%M")
                        diferenca = datetime.now() - data_envio
                        if diferenca.days >= 5:  # Se passou 5 dias, enviar código de rastreio
                            self.logger(f"Enviando código de rastreio para a ordem {order_id}...")
                            payloadRastreio = {
                                "from": {
                                    "user_id": ML_SELLER_ID
                                },
                                "to": {
                                    "user_id": buyer_id
                                },
                                "text": f"""
                                    ACOMPANHE O SEU PEDIDO
                                    Segue abaixo, o seu código de rastreamento.

                                    >>> {codigo_rastreio} 
                                    
                                    Para rastrear, basta acessar o site oficial dos Correios 👇
                                    https://rastreamento.correios.com.br/app/index.php
                                    
                                    
                                    
                                    Lembrando que ..
                                    Os produtos são importados e PODE SER TAXADO mas é bem difícil! O pedido é entregue pela transportadora, os Correios apenas fazem o rastreamento. Os Correios demora até 3 dias para atualizar. 
                                    Mas não se preocupe, o seu pedido já está a caminho. 

                                    Dúvidas, estamos à disposição 😉
                                    """
                            }
                            # --- ENVIO DA MENSAGEM (Caso não esteja no DB e não esteja no Chat) ---
                            envio = requests.post(url_msg, json=payloadRastreio, headers=headers)
                            db[order_id]['rastreio_enviado'] = True
                            db[order_id]['data_rastreio'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                            db[order_id]['codigo_rastreio'] = codigo_rastreio
                            self.salvar_db(db)
                            continue
                    except Exception as e:
                        self.logger(f"Erro ao verificar data inicial da ordem {order_id}: {str(e)}", "ERRO")
                

                
                if order_id in db:
                    data_solicitacao = db[order_id].get('data_solicitacao')
                    if data_solicitacao:
                        try:
                            data_envio = datetime.strptime(data_solicitacao, "%d/%m/%Y %H:%M")
                            diferenca = datetime.now() - data_envio
                            if diferenca.days >= 1 and not db[order_id].get('numero_extraido') and not db[order_id].get('rastreio_enviado'):
                                payloadReenvio = {
                                    "from": {
                                        "user_id": ML_SELLER_ID
                                    },
                                    "to": {
                                        "user_id": buyer_id
                                    },
                                    "text": "Olá! Não recebemos seu telefone. \n A transportadora precisa pra preencher os seus dados de entrega e enviar o código de rastreio pra você acompanhar."
                                }
                                 # --- ENVIO DA MENSAGEM (Caso não esteja no DB e não esteja no Chat) ---
                                envio = requests.post(url_msg, json=payloadReenvio, headers=headers)
                                if envio.status_code in [200, 201]:
                                    db[order_id]['data_solicitacao'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                                    self.logger(f"Reenvio: Mensagem reenviada para {order_id} após 1 dia sem resposta.")
                                    continue
                        except Exception as e:
                            self.logger(f"Erro ao reenviar mensagem para {order_id}: {str(e)}", "ERRO")    

                if order_id in db and (db[order_id].get('solicitado')):
                    self.logger(f"Mensagem já Enviada no chat da Ordem {order_id}...")
                    continue

                self.logger(f"Verificando histórico de mensagens para Ordem: {order_id}")
                
                # --- TRATATIVA 2: Validar se a mensagem já existe no chat ---
                res_historico = requests.get(url_msg, headers=headers).json()
                mensagens_no_chat = res_historico.get('messages', [])
                for m in mensagens_no_chat:
                    texto = m.get('text', '')
                    # Regex robusto para capturar vários formatos de telefone BR
                    match = re.search(r'(?:\+?55\s?)?\(?(\d{2})\)?\s?(9?\d{4})[\s.-]?(\d{4})', texto)
                    if match:
                            zap = "".join(match.groups())
                            #nome_cli = self.obter_nome_cliente(order_id, token)
                            db[order_id]['zap_extraido'] = zap
                            db[order_id]['numero_extraido'] = True
                        
                            self.logger(f"Finalizado extração de telefone para a ordem {order_id}: {zap}")
                            break
                
                
                # Verifica se algum texto no histórico é igual à nossa mensagem padrão
                #buscar apenas pelo pedaço da frase "Olá, tudo bem? O frete é grátis para todo Brasil"
                msg_padrao_parte = "Olá, tudo bem? O frete é grátis para todo Brasil"
                ja_enviado_no_ml = any(msg_padrao_parte in m.get('text', '') for m in mensagens_no_chat)

                if ja_enviado_no_ml:
                    self.logger(f"Mensagem já constava no chat da Ordem {order_id}. Atualizando controle local.")
                    # Atualizamos o DB para não consultar esta ordem novamente na próxima execução
                    db[order_id]['solicitado'] = True
                    db[order_id]['buyer_id'] = pedido.get('buyer', {}).get('id')
                    db[order_id]['pack_id'] = pedido.get('pack_id')
                    db[order_id]['corProduto'] = corProduto
                    db[order_id]['produto'] = nome_prod
                    db[order_id]['valor'] = valor
                    db[order_id]['data_solicitacao'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                    db[order_id]['data_solicitacao_inicial'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                    continue
                
                payload = {
                    "from": {
                        "user_id": ML_SELLER_ID
                    },
                    "to": {
                        "user_id": buyer_id
                    },
                    "text": msg_padrao
                }
                # --- ENVIO DA MENSAGEM (Caso não esteja no DB e não esteja no Chat) ---
                envio = requests.post(url_msg, json=payload, headers=headers)
                
                if envio.status_code in [200, 201]:
                    db[order_id]['solicitado'] = True
                    db[order_id]['buyer_id'] = pedido.get('buyer', {}).get('id')
                    db[order_id]['pack_id'] = pedido.get('pack_id')
                    db[order_id]['corProduto'] = corProduto
                    db[order_id]['produto'] = nome_prod
                    db[order_id]['valor'] = valor
                    db[order_id]['data_solicitacao'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                    db[order_id]['data_solicitacao_inicial'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                    enviados += 1
                    self.logger(f"Ordem {order_id}: Mensagem enviada e registrada.")
                else:
                    self.logger(f"Falha ao enviar mensagem para {order_id}: {envio.text}", "AVISO")

            # Salva o progresso no banco de dados local
            self.salvar_db(db)
            self.logger(f"Fim do Passo 1. Novas solicitações enviadas: {enviados}")

        except Exception as e:
            self.logger(f"Erro no Passo 1: {str(e)}", "ERRO")


    # --- PASSO 3: DISPARO WHATSAPP META ---
    def passo_3_disparar_wa(self):
        self.logger("Iniciando fila de disparos via Meta Cloud API...")
        db = self.carregar_db()
        disparos = 0

        for order_id, d in db.items():
            if d.get('zap_extraido') and not d.get('contatado_wa'):
                numero = d['zap_extraido']
                if not numero.startswith('55'): numero = '55' + numero

                url_wa = f"https://graph.facebook.com/v18.0/{WA_PHONE_ID}/messages"
                headers_wa = {"Authorization": f"Bearer {WA_TOKEN}", "Content-Type": "application/json"}
                
                payload = {
                    "messaging_product": "whatsapp",
                    "to": numero,
                    "type": "template",
                    "template": {
                        "name": WA_TEMPLATE_NAME,
                        "language": {"code": "pt_BR"},
                        "components": [
                            {"type": "body", "parameters": [
                                {"type": "text", "text": d.get('nome_cliente', 'Cliente')},
                                {"type": "text", "text": (d.get('produto')[:30] + '...') if d.get('produto') else 'seu pedido'}
                            ]}
                        ]
                    }
                }

                try:
                    res = requests.post(url_wa, json=payload, headers=headers_wa, timeout=10)
                    if res.status_code in [200, 201]:
                        db[order_id]['contatado_wa'] = True
                        db[order_id]['data_wa'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                        disparos += 1
                        self.logger(f"WhatsApp enviado com sucesso para {numero}!")
                    else:
                        self.logger(f"Falha API Meta ({res.status_code}): {res.text}", "ERRO")
                except Exception as e:
                    self.logger(f"Erro de conexão Meta: {str(e)}", "ERRO")

        self.salvar_db(db)
        self.logger(f"Fim do Passo 3. Total de clientes chamados: {disparos}")

    # --- AUXILIARES ML ---
    def obter_produto_ml(self, order_id, token):
        try:
            res = requests.get(f"https://api.mercadolibre.com/orders/{order_id}", headers={'Authorization': f'Bearer {token}'})
            return res.json()['order_items'][0]['item']['title']
        except: return "Produto ML"

    def obter_nome_cliente(self, order_id, token):
        try:
            res = requests.get(f"https://api.mercadolibre.com/orders/{order_id}", headers={'Authorization': f'Bearer {token}'})
            return res.json()['buyer']['first_name']
        except: return "Cliente"

    # --- CONTROLE DE DADOS ---
    def carregar_db(self):
    # 1. Verifica se o arquivo existe
        if not os.path.exists(DB_FILE):
            return {}
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                # Tenta carregar o conteúdo
                conteudo = f.read().strip()
                if not conteudo:  # Se o arquivo estiver em branco (vazio)
                    return {}
                return json.loads(conteudo)
                
        except (json.JSONDecodeError, IOError) as e:
            # Se o JSON estiver corrompido ou malformado, 
            # retorna um dicionário vazio para não travar o processo.
            print(f"Aviso: Erro ao ler {DB_FILE} ({e}). Iniciando base vazia.")
            return {}

    def salvar_db(self, db):
        with open(DB_FILE, 'w') as f: json.dump(db, f, indent=4)
        
    # --- NOVAS FUNCIONALIDADES: DASHBOARD E EXCEL ---
    def abrir_dashboard_vendas(self):
        db = self.carregar_db()
        if not db:
            messagebox.showinfo("Dashboard", "Banco de dados vazio.")
            return

        etapas = {"Solicitado (E1)": [], "Rastreio (E2)": [], "Boleto (E3)": []}
        for oid, dados in db.items():
            if dados.get('boleto_enviado'): etapas["Boleto (E3)"].append(oid)
            elif dados.get('rastreio_enviado'): etapas["Rastreio (E2)"].append(oid)
            elif dados.get('solicitado'): etapas["Solicitado (E1)"].append(oid)

        dash_win = tk.Toplevel(self.root)
        dash_win.title("Status de Vendas - Visão Geral")
        dash_win.geometry("1000x600")
        dash_win.configure(bg="#f8f9fa")

        main_frame = tk.Frame(dash_win, bg="#f8f9fa")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # --- CONFIGURAÇÃO DO GRÁFICO ---
        fig, ax = plt.subplots(figsize=(6, 5), dpi=100)
        fig.patch.set_facecolor('#f8f9fa')
        
        nomes = list(etapas.keys())
        valores = [len(v) for v in etapas.values()]
        cores = ['#007bff', '#ffc107', '#28a745']

        bars = ax.bar(nomes, valores, color=cores, width=0.6)
        
        # A MÁGICA AQUI: Força apenas números inteiros no eixo Y
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        
        # Estética do gráfico
        ax.set_title("Volume de Pedidos por Etapa", fontsize=12, fontweight='bold', pad=15)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.grid(axis='y', linestyle='--', alpha=0.7)

        # Adiciona o número exato em cima de cada barra
        for bar in bars:
            height = bar.get_height()
            ax.annotate(f'{int(height)}',
                        xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 3), 
                        textcoords="offset points",
                        ha='center', va='bottom', fontweight='bold')

        canvas = FigureCanvasTkAgg(fig, master=main_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # --- LISTA LATERAL DE ORDER_ID ---
        list_frame = tk.Frame(main_frame, bg="white", bd=1, relief=tk.FLAT)
        list_frame.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(20, 0))

        tk.Label(list_frame, text="LISTA DE ORDER_ID", bg="#343a40", fg="white", font=("Arial", 10, "bold"), pady=5).pack(fill=tk.X)
        
        text_area = scrolledtext.ScrolledText(list_frame, width=30, font=("Consolas", 10), bd=0)
        text_area.pack(fill=tk.BOTH, expand=True)

        for etapa, ids in etapas.items():
            text_area.insert(tk.END, f"\n> {etapa}\n", "header")
            if not ids:
                text_area.insert(tk.END, "  (Vazio)\n")
            for i in ids:
                text_area.insert(tk.END, f"  ID: {i}\n")
        
        text_area.tag_config("header", foreground="#007bff", font=("Consolas", 10, "bold"))
        text_area.configure(state=tk.DISABLED)

    def exportar_para_excel(self):
        db = self.carregar_db()
        if not db: return
        
        dados_excel = []
        for order_id, d in db.items():
            etapa = "Etapa 1"
            if d.get('boleto_enviado'): etapa = "Etapa 3"
            elif d.get('rastreio_enviado'): etapa = "Etapa 2"

            dados_excel.append({
                "Order ID": order_id,
                "Status": etapa,
                "Produto": d.get('produto', 'N/A'),
                "Data": d.get('data_solicitacao_inicial', 'N/A'),
                "Rastreio": d.get('codigo_rastreio', 'Pendente'),
                "corProduto": d.get('corProduto', 'N/A'),
                "valor": d.get('valor', 'N/A'),
                "numero":d.get('zap_extraido', 'N/A')
            })

        df = pd.DataFrame(dados_excel)
        caminho = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")])
        
        if caminho:
            df.to_excel(caminho, index=False)
            self.logger(f"Excel salvo em: {caminho}", "SUCESSO")
            messagebox.showinfo("Sucesso", "Arquivo Excel exportado!")    
            
         

if __name__ == "__main__":
    root = tk.Tk()
    app = AppColetorPro(root)
    root.mainloop()