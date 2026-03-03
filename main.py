import textwrap
import tkinter as tk
from tkinter import scrolledtext, messagebox, simpledialog, filedialog
from tkinter import ttk
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
import sys
import threading

# Load variables from .env file
load_dotenv()

# ==========================================
# CONFIGURAÇÕES DE API (PREENCHA AQUI)
# ==========================================
WA_TOKEN = 'SEU_TOKEN_PERMANENTE_META'
WA_PHONE_ID = 'SEU_PHONE_NUMBER_ID'
WA_TEMPLATE_NAME = 'atendimento_cliente_ml' # Deve estar aprovado na Meta

# # ALTERAÇÃO: Pasta raiz onde todas as contas ficarão
ACCOUNTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'contas')

BASE_DIR = "dist/database_vendas.json"

DB_FILE = os.path.join(BASE_DIR, 'database_vendas.json')
TOKEN_FILE = 'ml_tokens_autorizacao.json'

class GerenciadorTokenML:
    # # ALTERAÇÃO: Agora recebe 'folder' para gerenciar tokens específicos
    @staticmethod
    def salvar_tokens(dados, folder):
        path = os.path.join(folder, 'ml_tokens_autorizacao.json')
        with open(path, 'w') as f:
            json.dump(dados, f, indent=4)

    @staticmethod
    def carregar_tokens(folder):
        path = os.path.join(folder, 'ml_tokens_autorizacao.json')
        if os.path.exists(path):
            with open(path, 'r') as f:
                return json.load(f)
        return None

    # # ALTERAÇÃO: Usa o config local da pasta em vez de variáveis globais
    def renovar_access_token(self, folder, config):
        tokens = self.carregar_tokens(folder)
        if not tokens or not config: return None
        
        url = "https://api.mercadolibre.com/oauth/token"
        payload = {
            'grant_type': 'refresh_token',
            'client_id': config.get('ML_CLIENT_ID'),
            'client_secret': config.get('ML_CLIENT_SECRET'),
            'refresh_token': tokens['refresh_token']
        }
        try:
            res = requests.post(url, data=payload, timeout=15)
            if res.status_code == 200:
                novos_tokens = res.json()
                self.salvar_tokens(novos_tokens, folder)
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
        
        # # ALTERAÇÃO: Função central para validar e-mail e retornar a pasta correta
    def get_pasta_conta(self):
        email = self.var_email.get().strip()
        if not email:
            messagebox.showerror("Erro", "Por favor, digite o E-MAIL da conta para prosseguir.")
            self.ent_email.focus_set()
            return None
        
        pasta = os.path.join(ACCOUNTS_DIR, email)
        if not os.path.exists(pasta):
            os.makedirs(pasta)
        return pasta
    
    
    def carregar_config_cliente(self, folder):
        path = os.path.join(folder, 'config_conta.json')
        if not os.path.exists(path):
            messagebox.showerror("Erro", f"Falta o arquivo config_conta.json em: {folder}")
            return None
        with open(path, 'r') as f:
            return json.load(f)

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
        self.var_email = tk.StringVar()

        tk.Label(input_frame, text="Prazo Entrega:").grid(row=0, column=0, sticky="w", padx=5)
        tk.Entry(input_frame, textvariable=self.var_prazo, width=15).grid(row=0, column=1, padx=10)

        tk.Label(input_frame, text="Cód. Rastreio:").grid(row=0, column=2, sticky="w", padx=5)
        tk.Entry(input_frame, textvariable=self.var_rastreio, width=20).grid(row=0, column=3, padx=10)

        tk.Label(input_frame, text="Página Inicial (Offset):").grid(row=0, column=4, sticky="w", padx=5)
        tk.Entry(input_frame, textvariable=self.var_pag_inicial, width=10).grid(row=0, column=5, padx=10)
        
        tk.Label(input_frame, text="Conta do Cliente. Email: ").grid(row=0, column=6, sticky="w", padx=5)
        tk.Entry(input_frame, textvariable=self.var_email, width=40).grid(row=0, column=7, padx=10)
        
        self.progress = ttk.Progressbar(self.root, orient="horizontal", length=400, mode="determinate")
        self.progress.pack(pady=5, padx=20, fill=tk.X)

        # --- Container de Botões ---
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=10)

        estilo = {"width": 20, "height": 2, "font": ("Arial", 9, "bold")}

        tk.Button(btn_frame, text="AUTORIZAR ML", command=self.fluxo_autorizacao_ml, bg="#9C27B0", fg="white", **estilo).grid(row=0, column=0, padx=5)
        tk.Button(btn_frame, text="PROCESSAMENTO ALL", command=self.iniciar_thread_processamento, bg="#1976D2", fg="white", **estilo).grid(row=0, column=1, padx=5)
        tk.Button(btn_frame, text="DASHBOARD", command=self.abrir_dashboard_vendas, bg="#5007DA", fg="white", **estilo).grid(row=0, column=2, padx=5)
        tk.Button(btn_frame, text="EXPORTAR EXCEL", command=self.exportar_para_excel, bg="#083A33", fg="white", **estilo).grid(row=0, column=3, padx=5)
        tk.Button(btn_frame, text="ATUALIZAR BLT PAGOS", command=self.atualizar_blt_pagos_thread, bg="#189108", fg="white", **estilo).grid(row=0, column=4, padx=5)

        # --- Log ---
        self.log = scrolledtext.ScrolledText(self.root, height=25, width=140, font=("Consolas", 9), bg="#F5F5F5")
        self.log.pack(pady=10, padx=20)

    def logger(self, msg, tag="INFO"):
        time = datetime.now().strftime("%H:%M:%S")
        self.log.insert(tk.END, f"[{time}] [{tag}] {msg}\n")
        self.log.see(tk.END)
        self.root.update_idletasks()
        
        
    def atualizar_blt_pagos_thread(self):    
         # --- DISPARA A THREAD ---
        # Passamos as respostas como argumentos para a thread
        thread = threading.Thread(target=self.atualizar_blt_pagos, args=())
        thread.daemon = True # Faz a thread fechar se você fechar a janela
        thread.start()
        self.logger("Thread de processamento iniciada em segundo plano...")
        
    def atualizar_blt_pagos(self):
        folder = self.get_pasta_conta()
        if not folder: return
        
        db = self.carregar_db()
        if not db:
            messagebox.showinfo("Info", "Nenhum registro encontrado para atualizar.")
            return
        
        config = self.carregar_config_cliente(folder)
        if not config: return
        
        access_token = config.get("TOKEN_MP")
        if not access_token:
            self.logger("Token do Mercado Pago não encontrado.", "ERRO")
            return
        
        atualizados = 0

        for order_id, d in db.items():
            if d.get('boleto_enviado') and not d.get('boleto_pago'):
               url = f"https://api.mercadopago.com/v1/payments/{d.get('id_payment')}"
               headers = {"Authorization": f"Bearer {access_token}"}
               response = requests.get(url, headers=headers)
               if response.status_code == 200:
                    resultado = response.json().get('status')
                    if resultado == 'approved' or resultado == 'refunded':
                        db[order_id]['boleto_pago'] = True
                        db[order_id]['data_boleto_pago'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                        atualizados += 1
                        self.logger(f"Ordem {order_id}: Boleto marcado como pago.")
               else:
                   self.logger(f"Erro ao verificar status do pagamento da ordem {order_id}: {response.status_code} - {response.text}", "ERRO")
                   break

        self.salvar_db(db)
        self.logger(f"Atualização finalizada. Total de boletos marcados como pagos: {atualizados}")    

    # --- LÓGICA DE AUTENTICAÇÃO ---
    def fluxo_autorizacao_ml(self):
        
        folder = self.get_pasta_conta()
        if not folder: return
        
        config = self.carregar_config_cliente(folder)
        if not config: return
        
        url = f"https://auth.mercadolibre.com/authorization?response_type=code&client_id={config['ML_CLIENT_ID']}&redirect_uri={config['ML_REDIRECT_URI']}"
        webbrowser.open(url)
        self.logger("Navegador aberto. Autorize e cole o código 'TG-...' abaixo.")
        
        codigo = simpledialog.askstring("OAuth ML", "Insira o código gerado na URL (code=...):")
        if codigo:
            url_token = "https://api.mercadolibre.com/oauth/token"
            data = {
                'grant_type': 'authorization_code',
                'client_id': config['ML_CLIENT_ID'],
                'client_secret': config['ML_CLIENT_SECRET'],
                'code': codigo,
                'redirect_uri': config['ML_REDIRECT_URI']
            }
            res = requests.post(url_token, data=data)
            if res.status_code == 200:
                self.auth_ml.salvar_tokens(res.json(), folder)
                self.logger("Tokens salvos com sucesso!", "SUCESSO")
            else:
                self.logger(f"Erro na troca de código: {res.text}", "ERRO")

    def get_token_ml(self, folder):
        token = self.auth_ml.renovar_access_token(folder, config=self.carregar_config_cliente(folder))
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
                total_disponivel = data.get("paging", {}).get("total", 0)
                current_offset += limit_por_request

                if current_offset >= total_disponivel or current_offset >= limite_maximo:
                    self.logger(f"Busca finalizada. Total capturado: {len(todos_os_pedidos)}")
                    break
                
                time.sleep(1) # Delay leve para evitar 429

            except requests.exceptions.RequestException as e:
                self.logger(f"Erro na requisição: {e}", "ERRO")
                break

        return todos_os_pedidos, len(todos_os_pedidos)
    
    def iniciar_thread_processamento(self):
        """Captura os dados na Main Thread e inicia o background."""
        folder = self.get_pasta_conta()
        if not folder: return
        
        token = self.get_token_ml(folder)
        if not token: return
        
        config = self.carregar_config_cliente(folder)
        if not config: return
        
        # --- DEMAIS INPUTS ---
        prazo_usuario = self.var_prazo.get()
        pagInicial = self.var_pag_inicial.get()
        if not prazo_usuario or not pagInicial:
            self.logger("Erro: Prazo e Página Inicial são obrigatórios.", "ERRO")
            return
        
        # Se o usuário clicar em cancelar ou deixar vazio, interrompe o processo
        if not prazo_usuario or not pagInicial:
            self.logger("Operação cancelada: O prazo de entrega e página inicial são obrigatórios.", "AVISO")
            return

        self.logger("Iniciando varredura de vendas via /orders/search...")
        # --- AS PERGUNTAS (RODAM NA MAIN THREAD) ---
        chats, total_chats = self.buscar_vendas_paginadas(config['ML_SELLER_ID'], token, offset_inicial=pagInicial)
        env_rastreio = messagebox.askyesno("Enviar Rastreio", "Deseja enviar código de rastreio agora?")
        lim_rastreio = 0
        cod_rastreio = self.var_rastreio.get().strip()
        
        # Configura o máximo da barra de progresso
        self.progress["maximum"] = total_chats
        self.progress["value"] = 0

        # Perguntas (Na Main Thread para não dar erro)
        # ... logic de simpledialog para lim_rastreio e lim_boleto ...
            
        if env_rastreio:
            if not cod_rastreio:
                messagebox.showerror("Erro", "Preencha o campo 'Cód. Rastreio'!")
                return
            lim_rastreio = simpledialog.askinteger("Limite", f"Quantas vendas recebera o rastreios? \nTotal de vendas: {total_chats}", minvalue=1)
            if not lim_rastreio: return

        env_boleto = messagebox.askyesno("Enviar Boleto", "Deseja enviar boletos agora?")
        lim_boleto = 0
        if env_boleto:
            lim_boleto = simpledialog.askinteger("Limite", f"Quantos vendas recebera o boleto? \nTotal de vendas: {total_chats}", minvalue=1)
            if not lim_boleto: return

        # --- DISPARA A THREAD ---
        # Passamos as respostas como argumentos para a thread
        thread = threading.Thread(target=self.passo_1_solicitar, args=(token, env_rastreio, lim_rastreio, cod_rastreio, env_boleto, lim_boleto, pagInicial, prazo_usuario, chats, config))
        thread.daemon = True # Faz a thread fechar se você fechar a janela
        thread.start()
        self.logger("Thread de processamento iniciada em segundo plano...")
    
    # --- PASSO 1: SOLICITAÇÃO ---
    def passo_1_solicitar(self, token, env_rastreio, lim_rastreio, cod_rastreio, env_boleto, lim_boleto, pagInicial, prazo_usuario, chats, config):
        folder = self.get_pasta_conta()
        if not folder: return
        
        token = self.get_token_ml(folder)
        if not token: return
        
        rastreios_contagem = 0
        boletos_contagem = 0
    
        
        msg_padrao = f"Olá, tudo bem? O frete é grátis para todo Brasil e o prazo estimado de entrega é até {prazo_usuario}. Lembrando que os produtos são importados, vem de fora do país! Vamos fazer o envio e mandar o código de rastreio. \n \n \nA transportadora precisa do seu telefone pra preencher os seus dados de entrega e enviar o código de rastreio pra você acompanhar."
        
        
        headers = {
            "Authorization": f"Bearer {token}"
        }
        pedidos = chats
        pagInicial = int(pagInicial) - 1
        #preciso salvar essa pagina inicial na planilha onde cada registro começa aparti dela e o proximo soma 1
        
        try:
            db = self.carregar_db()
            enviados = 0

            for i, pedido in enumerate(pedidos):
                # Pegamos o ID da ordem (ou pack_id se preferir, mas seguindo sua instrução: order_id)
                #se o array de pedido tiver na posição 10 parar o loop e encerrar para um teste
                #if pedidos.index(pedido) >= 5:
                #    self.logger("Limite de 5 pedidos atingido para teste. Encerrando loop.")
                #    break
                order_id = str(pedido['id'])
                buyer_id = str(pedido.get('buyer', {}).get('id'))
                nome_prod = str(pedido['payments'][0]['reason']) 
                valor = str(pedido['total_amount'])
                corProduto = str(pedido['order_items'][0]['item']['variation_attributes'][0]['value_name'])
                # APOS 2 OU 3 DIAS DO ENVIO DO CODIGO DE RASTREIO, ENVIAR MSG E BOLETO PARA PAGAMENTO DE TAXA E SALVAR NO DB QUE O BOLETO FOI ENVIADO
                url_msg = f"https://api.mercadolibre.com/messages/packs/{order_id}/sellers/{config['ML_SELLER_ID']}?tag=post_sale"
                # Se a ordem não existe no DB, inicializamos como dicionário vazio
                if order_id not in db:
                    db[order_id] = {}
                    
                dados_pedido = db[order_id]    
                # Usamos after() para que a Main Thread faça a pintura do widget    
                self.root.after(0, lambda v=i+1: self.progress.configure(value=v))    
                
                if not dados_pedido.get('numero_cliente'):
                    dados_pedido['numero_cliente'] = pagInicial + pedidos.index(pedido) + 1 
                
                
                if order_id in db and (dados_pedido.get('rastreio_enviado') and dados_pedido.get('data_rastreio')):
                    data_rastreio = dados_pedido.get('data_rastreio')
                    try:
                        data_envio = datetime.strptime(data_rastreio, "%d/%m/%Y %H:%M")
                        diferenca = datetime.now() - data_envio
                        if env_boleto and boletos_contagem < lim_boleto and diferenca.days > 1 and not dados_pedido.get('boleto_enviado'):
                            self.logger(f"Enviando boleto para pagamento de taxa para a ordem {order_id}...")
                            caminho_excel = r"C:\Users\mathe\Meu Drive\Sistema JV V1\Nova pasta\dist\registros_pedidos.xlsx"
                            df = pd.read_excel(caminho_excel)
                            boleto_numero = None
                            indice_boleto = None
                            for index, row in df.iterrows():
                                if str(row['Boleto Usado']) == 'False':
                                    boleto_numero = str(row['Código'])
                                    indice_boleto = index # Guarda o índice para marcar como usado depois
                                    break
                            if(not boleto_numero):
                                self.logger(f"Não foi possível encontrar um boleto disponível para a ordem {order_id}. Verifique o Excel de registros.", "ERRO")
                                break       
                            payloadBoleto = {
                                "from": {
                                    "user_id": config['ML_SELLER_ID']
                                },
                                "to": {
                                    "user_id": buyer_id
                                },
                                "text": (
                                    "Olá, tudo bem?\n\n"
                                    "O seu painel importado chegou no Brasil. 🥳\n"
                                    "Porém, a Receita Federal taxou o seu produto no valor de R$ 138,98.\n\n"
                                    "É necessário realizar o pagamento desta taxa para liberar o seu pedido. "
                                    "Caso seja pago hoje, a previsão de entrega é para terça-feira, dia 10. 😉\n\n"
                                    "O pagamento é feito exclusivamente pelo boleto do Mercado Pago que enviamos. "
                                    "A transportadora utiliza o sistema do Mercado Pago para garantir a segurança da plataforma!\n\n"
                                    "Vamos gerar o boleto agora mesmo!\n\n"
                                    "Prontinho, boleto gerado! Só copiar todo o código de barras abaixo e pagar pelo aplicativo do seu Banco: 👇"
                                )
                            }
                            # --- ENVIO DA MENSAGEM (Caso não esteja no DB e não esteja no Chat) ---
                            envio = requests.post(url_msg, json=payloadBoleto, headers=headers)
                            if envio.status_code in [200, 201]:
                                
                                payloadBoletoCodigo = {
                                    "from": {
                                        "user_id": config['ML_SELLER_ID']
                                    },
                                    "to": {
                                        "user_id": buyer_id
                                    },
                                    "text": f"{boleto_numero}"
                                }
                                envio = requests.post(url_msg, json=payloadBoletoCodigo, headers=headers)
                                if(envio.status_code in [200, 201]):
                                    df.at[indice_boleto, 'Boleto Usado'] = "Enviado"
                                    df.to_excel(caminho_excel, index=False)
                                    db[order_id]['boleto_enviado'] = True
                                    db[order_id]['data_boleto'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                                    db[order_id]['codigo_boleto'] = boleto_numero
                                    db[order_id]['id_payment'] = str(row['id_payment'])
                                    rastreios_contagem += 1
                                    self.salvar_db(db)
                                    self.logger(f"Boleto enviado com sucesso para a ordem {order_id}!")
                                    continue
                                else:
                                    self.logger(f"Falha ao enviar código do boleto para a ordem {order_id}: {envio.text}", "ERRO")
                            else:
                                self.logger(f"Falha ao enviar boleto para a ordem {order_id}: {envio.text}", "ERRO")
                    except Exception as e:
                        self.logger(f"Erro ao verificar data de envio do rastreio para a ordem {order_id}: {str(e)}", "ERRO")
                
                    
           
                #VERIFICAR SE A DATA INICIAL SE PASSOU 4 OU 5 DIAS ENVIAR CODIGO DE RASTREIO 
                if order_id in db and (dados_pedido.get('solicitado') and dados_pedido.get('data_solicitacao_inicial')):
                    #data_solicitacao_inicial = dados_pedido.get('data_solicitacao_inicial')
                    try:
                        #data_envio = datetime.strptime(data_solicitacao_inicial, "%d/%m/%Y %H:%M")
                        #diferenca = datetime.now() - data_envio
                        if env_rastreio and rastreios_contagem < lim_rastreio and not dados_pedido.get('rastreio_enviado'): 
                            self.logger(f"Enviando código de rastreio para a ordem {order_id}...")
                            payloadRastreio = {
                                "from": {
                                    "user_id": config['ML_SELLER_ID']
                                },
                                "to": {
                                    "user_id": buyer_id
                                },
                                "text": textwrap.dedent(f"""\
                                        ACOMPANHE O SEU PEDIDO
                                        Segue abaixo o seu código de rastreamento:
                                        >>> {cod_rastreio} 

                                        Para rastrear, basta acessar o site oficial dos Correios 👇
                                        https://rastreamento.correios.com.br/app/index.php

                                        Lembrando que:

                                        O produto é importado e PODE SER TAXADO, mas é bem difícil! O pedido é entregue pela transportadora, os Correios apenas fazem o rastreamento e podem demorar até 3 dias para atualizar o status.

                                        Mas não se preocupe, o seu pedido já está a caminho.
                                        
                                        Dúvidas? Estamos à disposição! 😉""").strip()
                            }
                            # --- ENVIO DA MENSAGEM (Caso não esteja no DB e não esteja no Chat) ---
                            envio = requests.post(url_msg, json=payloadRastreio, headers=headers)
                            db[order_id]['rastreio_enviado'] = True
                            db[order_id]['data_rastreio'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                            db[order_id]['codigo_rastreio'] = cod_rastreio
                            boletos_contagem += 1
                            self.salvar_db(db)
                            continue
                    except Exception as e:
                        self.logger(f"Erro ao verificar data inicial da ordem {order_id}: {str(e)}", "ERRO")
                
                # --- TRATATIVA 2: Validar se a mensagem já existe no chat ---
                conversaCompleta = self.obter_conversa_completa(order_id, order_id, config['ML_SELLER_ID'], token)
                #res_historico = requests.get(url_msg, headers=headers).json()
                if order_id in db and (dados_pedido.get('solicitado') and not dados_pedido.get('numero_extraido')):
                    for m in conversaCompleta:
                        texto = m.get('texto', '')
                        # Regex robusto para capturar vários formatos de telefone BR
                        match = re.search(r'(?:\+?55\s*)?\(?(\d{2,3})\)?\s*(9[.\s-]*)?(\d{4,5})[\s.:-]*(\d{4})', texto)
                        if match:
                                zap_bruto = "".join(g for g in match.groups() if g is not None)
                                zap = "".join(re.findall(r'\d+', zap_bruto))
                                #nome_cli = self.obter_nome_cliente(order_id, token)
                                db[order_id]['zap_extraido'] = zap
                                db[order_id]['numero_extraido'] = True
                                self.salvar_db(db)
                                self.logger(f"Finalizado extração de telefone para a ordem {order_id}: {zap}")
                                payloadReenvio = {
                                        "from": {
                                            "user_id": config['ML_SELLER_ID']
                                        },
                                        "to": {
                                            "user_id": buyer_id
                                        },
                                        "text": "Olá! recebemos seu telefone. Obrigado! \nVamos dar continuidade ao processo de envio do seu pedido. \nAssim que o código de rastreio estiver disponível, enviaremos para você acompanhar a entrega. 😉"
                                }
                                    # --- ENVIO DA MENSAGEM (Caso não esteja no DB e não esteja no Chat) ---
                                envio = requests.post(url_msg, json=payloadReenvio, headers=headers)
                                break
                
                if order_id in db:
                    data_solicitacao = dados_pedido.get('data_solicitacao')
                    if data_solicitacao:
                        try:
                            data_envio = datetime.strptime(data_solicitacao, "%d/%m/%Y %H:%M")
                            diferenca = datetime.now() - data_envio
                            if diferenca.days >= 1 and not dados_pedido.get('numero_extraido') and not dados_pedido.get('tentativa_', 0) < 2:
                                payloadReenvio = {
                                    "from": {
                                        "user_id": config['ML_SELLER_ID']
                                    },
                                    "to": {
                                        "user_id": buyer_id
                                    },
                                    "text": "Olá! Não recebemos seu telefone. \n A transportadora precisa pra preencher os seus dados de entrega e enviar o código de rastreio pra você acompanhar."
                                }
                                 # --- ENVIO DA MENSAGEM (Caso não esteja no DB e não esteja no Chat) ---
                                #envio = requests.post(url_msg, json=payloadReenvio, headers=headers)
                                if envio.status_code in [200, 201]:
                                    db[order_id]['data_solicitacao'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                                    db[order_id]['tentativa_'] = dados_pedido.get('tentativa_', 0) + 1
                                    self.logger(f"Reenvio: Mensagem reenviada para {order_id} após 1 dia sem resposta.")
                                    continue
                        except Exception as e:
                            self.logger(f"Erro ao reenviar mensagem para {order_id}: {str(e)}", "ERRO")    

                if order_id in db and (dados_pedido.get('solicitado')):
                    self.logger(f"Mensagem já Enviada no chat da Ordem {order_id}...")
                    continue

                self.logger(f"Verificando histórico de mensagens para Ordem: {order_id}")
                
                
                # Verifica se algum texto no histórico é igual à nossa mensagem padrão
                #buscar apenas pelo pedaço da frase "Olá, tudo bem? O frete é grátis para todo Brasil"
                msg_padrao_parte = "Olá, tudo bem? O frete é grátis para todo Brasil"
                ja_enviado_no_ml = any(msg_padrao_parte in m.get('texto', '') for m in conversaCompleta)

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
                    self.salvar_db(db)
                    continue
                
                payload = {
                    "from": {
                        "user_id": config['ML_SELLER_ID']
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
            
            
    def obter_conversa_completa(self, order_id, pack_id, seller_id, token):
        headers = {"Authorization": f"Bearer {token}"}
        conversa_unificada = []
        claim_ids = []

        # --- PARTE A: Chat de Pós-Venda Comum ---
        url_comum = f"https://api.mercadolibre.com/messages/packs/{pack_id}/sellers/{seller_id}?tag=post_sale"
        try:
            res_comum = requests.get(url_comum, headers=headers, timeout=10)
            if res_comum.status_code == 200:
                dados = res_comum.json()
                msgs = dados.get('messages', [])
                
                # Extração correta dos claim_ids que vimos no seu debugger
                status_conversa = dados.get('conversation_status', {})
                claim_ids = status_conversa.get('claim_ids', [])
                
                for m in msgs:
                    conversa_unificada.append({
                        "origem": "Chat Comum",
                        "texto": m.get('text'),
                        "data": m.get('message_date')
                    })
        except Exception as e:
            self.logger(f"Erro ao buscar chat comum {order_id}: {e}")

        # --- PARTE B: Chat de Reclamação (Claim) ---
        if(len(claim_ids) > 0):
            for claim_id in claim_ids:
                try:
                    url_msg_claim = f"https://api.mercadolibre.com/post-purchase/v1/claims/{claim_id}/messages"
                    res_msg_claim = requests.get(url_msg_claim, headers=headers, timeout=10)
                    
                    if res_msg_claim.status_code == 200:
                        msgs_claim = res_msg_claim.json()
                        for mc in msgs_claim:
                            conversa_unificada.append({
                                "origem": f"Reclamação ({claim_id})",
                                "texto": mc.get('message'),
                                "data": mc.get('date_created') 
                            })  
                except Exception as e:
                    self.logger(f"Erro na reclamação {claim_id}: {e}")

        return conversa_unificada

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

    # # ALTERAÇÃO: Ajustado para usar a pasta do e-mail
    def carregar_db(self):
        folder = self.get_pasta_conta()
        if not folder: return {}
        
        db_path = os.path.join(folder, "database_vendas.json")
        if not os.path.exists(db_path): return {}
        with open(db_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    # # ALTERAÇÃO: Ajustado para salvar na pasta do e-mail
    def salvar_db(self, db):
        folder = self.get_pasta_conta()
        if folder:
            db_path = os.path.join(folder, "database_vendas.json")
            with open(db_path, 'w', encoding='utf-8') as f:
                json.dump(db, f, indent=4)
        
    # --- NOVAS FUNCIONALIDADES: DASHBOARD E EXCEL ---
    def abrir_dashboard_vendas(self):
        db = self.carregar_db()
        if not db:
            messagebox.showinfo("Dashboard", "Banco de dados vazio.")
            return

        etapas = {"Solicitado (E1)": [], "Rastreio (E2)": [], "Boleto (E3)": [], "Boleto Pago (E4)": []}
        for oid, dados in db.items():
            if dados.get('boleto_pago'): etapas["Boleto Pago (E4)"].append(oid)
            elif dados.get('boleto_enviado'): etapas["Boleto (E3)"].append(oid)
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
        cores = ['#007bff', '#ffc107', '#28a745', "#6e1cbb"]  # Azul, Amarelo, Verde, Cinza

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
        # Mantemos a ordem das colunas para facilitar a escrita depois
        colunas = [
            "Numero do Cliente", "Order ID", "Status", "Produto", "Data", 
            "Rastreio", "corProduto", "valor", "numero", "boleto_enviado", 
            "id_payment", "boleto_Pago"
        ]

        for order_id, d in db.items():
            etapa = "Etapa 1"
            if d.get('boleto_enviado'): etapa = "Etapa 3"
            elif d.get('rastreio_enviado'): etapa = "Etapa 2"

            dados_excel.append({
                "Numero do Cliente": d.get('numero_cliente', 'N/A'),
                "Order ID": order_id,
                "Status": etapa,
                "Produto": d.get('produto', 'N/A'),
                "Data": d.get('data_solicitacao_inicial', 'N/A'),
                "Rastreio": d.get('codigo_rastreio', 'Pendente'),
                "corProduto": d.get('corProduto', 'N/A'),
                "valor": d.get('valor', 'N/A'),
                "numero": d.get('zap_extraido', 'N/A'),
                "boleto_enviado": d.get('codigo_boleto', 'N/A'),
                "id_payment": d.get('id_payment', 'N/A'),
                "boleto_Pago": "Sim" if d.get('boleto_pago') else "Não"
            })

        df = pd.DataFrame(dados_excel, columns=colunas)
        caminho = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")])
        
        if caminho:
            # 1. Usar o engine xlsxwriter
            writer = pd.ExcelWriter(caminho, engine='xlsxwriter')
            df.to_excel(writer, index=False, sheet_name='Vendas')

            workbook  = writer.book
            worksheet = writer.sheets['Vendas']

            # 2. Definir formato visual do link (Azul e Sublinhado)
            format_link = workbook.add_format({'font_color': 'blue', 'underline': 1})

            # 3. Identificar o índice da coluna "Order ID" (neste caso é a coluna B, índice 1)
            col_idx = colunas.index("Order ID")

            # 4. Sobrescrever apenas a coluna de Order ID com os links
            base_url = "https://www.mercadolivre.com.br/vendas/{}/detalhe#source=excel"
            
            for row_num, order_id in enumerate(df['Order ID']):
                url = base_url.format(order_id)
                # row_num + 1 para pular o cabeçalho
                worksheet.write_url(row_num + 1, col_idx, url, string=str(order_id), cell_format=format_link)

            # 5. Salvar
            writer.close()
            
            self.logger(f"Excel salvo em: {caminho}", "SUCESSO")
            messagebox.showinfo("Sucesso", "Arquivo Excel exportado com links!")
   
            
         

if __name__ == "__main__":
    root = tk.Tk()
    app = AppColetorPro(root)
    root.mainloop()