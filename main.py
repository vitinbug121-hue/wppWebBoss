from logging import config
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
import logging
import subprocess

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
        self.wpp_ativo = False  # Estado inicial: desligado
        self.auth_ml = GerenciadorTokenML()
        logging.getLogger().setLevel(logging.CRITICAL) # Silencia logs automáticos de bibliotecas externas
        
        self.setup_ui()
        
        # # ALTERAÇÃO: Função central para validar e-mail e retornar a pasta correta
    def get_pasta_conta(self):
        email = self.var_email.get().strip()
        if not email:
            messagebox.showerror("Erro", "Por favor, digite o E-MAIL da conta para prosseguir.")
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
        self.var_ordem_ids = tk.StringVar()
        self.var_data_entrega = tk.StringVar()
        self.rodar_reclamacao_var = tk.BooleanVar(value=False)
        self.rodar_wa_var = tk.BooleanVar(value=False)

        tk.Label(input_frame, text="Prazo Entrega:").grid(row=0, column=0, sticky="w", padx=5)
        tk.Entry(input_frame, textvariable=self.var_prazo, width=15).grid(row=0, column=1, padx=10)

        tk.Label(input_frame, text="Cód. Rastreio:").grid(row=0, column=2, sticky="w", padx=5)
        tk.Entry(input_frame, textvariable=self.var_rastreio, width=20).grid(row=0, column=3, padx=10)

        tk.Label(input_frame, text="Página Inicial (Offset):").grid(row=0, column=4, sticky="w", padx=5)
        tk.Entry(input_frame, textvariable=self.var_pag_inicial, width=10).grid(row=0, column=5, padx=10)
        
        tk.Label(input_frame, text="Conta do Cliente. Email: ").grid(row=0, column=6, sticky="w", padx=5)
        tk.Entry(input_frame, textvariable=self.var_email, width=40).grid(row=0, column=7, padx=10)
        
        tk.Label(input_frame, text="Ordem IDs").grid(row=0, column=8, sticky="w", padx=5)
        tk.Entry(input_frame, textvariable=self.var_ordem_ids, width=40).grid(row=0, column=9, padx=10)
        
        tk.Label(input_frame, text="Data Entrega:").grid(row=0, column=10, sticky="w", padx=5)
        tk.Entry(input_frame, textvariable=self.var_data_entrega, width=40).grid(row=0, column=11, padx=10)

        self.progress = ttk.Progressbar(self.root, orient="horizontal", length=400, mode="determinate")
        self.progress.pack(pady=5, padx=20, fill=tk.X)

        
        # --- Container de Botões ---
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=10)

        estilo = {"width": 22, "height": 2, "font": ("Arial", 9, "bold")}

        # Linha 1: Comandos Gerais
        tk.Button(btn_frame, text="AUTORIZAR ML", command=self.fluxo_autorizacao_ml, bg="#002357", fg="white", **estilo).grid(row=0, column=0, padx=5, pady=5)
        tk.Button(btn_frame, text="PRIMEIRA MSG E WPP", command=lambda: self.iniciar_thread_processamento(acao="solicitar"), bg="#002357", fg="white", **estilo).grid(row=0, column=1, padx=5, pady=5)
        tk.Button(btn_frame, text="DASHBOARD", command=self.abrir_dashboard_vendas, bg="#002357", fg="white", **estilo).grid(row=0, column=2, padx=5, pady=5)
        tk.Button(btn_frame, text="EXPORTAR EXCEL", command=self.exportar_para_excel, bg="#002357", fg="white", **estilo).grid(row=0, column=3, padx=5, pady=5)
        tk.Button(btn_frame, text="ATUALIZAR PAGOS", command=self.atualizar_blt_pagos_thread, bg="#002357", fg="white", **estilo).grid(row=0, column=4, padx=5, pady=5)
        tk.Button(btn_frame, text="CHAMAR WPP", command=self.iniciar_thread_wpp_inicial, bg="#002357", fg="white", **estilo).grid(row=0, column=5, padx=5, pady=5)
        self.btn_wpp = tk.Button(btn_frame, text="LOGAR WPP", command=self.ativarWpp, bg="#FF0000", fg="white", **estilo)
        self.btn_wpp.grid(row=0, column=6, padx=5, pady=5)
        
        
        btn_frame_reclamacao = ttk.Frame(self.root)
        btn_frame_reclamacao.pack(pady=10)

        # reclamação
        self.chk_reclamacao = ttk.Checkbutton(
            btn_frame_reclamacao, 
            text="Rodar apenas Reclamações?", 
            variable=self.rodar_reclamacao_var
        )
        self.chk_reclamacao.pack(side=tk.LEFT, padx=20)
        # WPP
        self.chk_wa = ttk.Checkbutton(
            btn_frame_reclamacao, 
            text="Rodar via WhatsApp?", 
            variable=self.rodar_wa_var
        )
        self.chk_wa.pack(side=tk.LEFT, padx=20)

        
        # Linha 2: Ações Específicas (Substituindo os Yes/No)
        tk.Button(btn_frame, text="ENVIAR RASTREIO", command=lambda: self.iniciar_thread_processamento(acao="rastreio"), bg="#002357", fg="white", **estilo).grid(row=1, column=0, padx=5, pady=5)
        tk.Button(btn_frame, text="ENVIAR BOLETO", command=lambda: self.iniciar_thread_processamento(acao="boleto"), bg="#002357", fg="white", **estilo).grid(row=1, column=1, padx=5, pady=5)
        tk.Button(btn_frame, text="ERRO NO BOLETO", command=lambda: self.iniciar_thread_processamento(acao="erro_boleto"), bg="#002357", fg="white", **estilo).grid(row=1, column=2, padx=5, pady=5)
        tk.Button(btn_frame, text="REENVIAR BOLETO", command=lambda: self.iniciar_thread_processamento(acao="reenviar_boleto"), bg="#002357", fg="white", **estilo).grid(row=1, column=3, padx=5, pady=5)
        tk.Button(btn_frame, text="COBRAR DOBRADO", command=lambda: self.iniciar_thread_processamento(acao="cobrar_dobrado"), bg="#002357", fg="white", **estilo).grid(row=1, column=4, padx=5, pady=5)
        tk.Button(btn_frame, text="AGRADECIMENTO", command=lambda: self.iniciar_thread_processamento(acao="agradecimento"), bg="#002357", fg="white", **estilo).grid(row=1, column=5, padx=5, pady=5)

        # --- Log ---
        self.log = scrolledtext.ScrolledText(self.root, height=50, width=190, font=("Consolas", 9), bg="#F5F5F5")
        self.log.pack(pady=10, padx=20)

    def logger(self, msg, tag="INFO"):
        # 1. Tentar configurar o logging para a pasta da conta atual
        email = self.var_email.get().strip()
        if email:
            # Caminho: contas/email@clinte.com/logs/
            log_dir = os.path.join(ACCOUNTS_DIR, email, 'logs')
            if not os.path.exists(log_dir):
                os.makedirs(log_dir)
            
            log_path = os.path.join(log_dir, f"log_{datetime.now().strftime('%Y-%m-%d')}.txt")
            
            # Configura o logger para escrever neste arquivo específico
            # Usamos o nome do email como nome do logger para evitar conflitos de handlers
            file_logger = logging.getLogger(email)
            if not file_logger.handlers:
                file_handler = logging.FileHandler(log_path, encoding='utf-8')
                formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
                file_handler.setFormatter(formatter)
                file_logger.addHandler(file_handler)
                file_logger.setLevel(logging.INFO)

            # Registra a mensagem no arquivo
            if tag == "ERRO":
                file_logger.error(msg)
            elif tag == "ALERTA":
                file_logger.warning(msg)
            else:
                file_logger.info(msg)

        # 2. Atualização visual no ScrolledText (Tkinter)
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log.insert(tk.END, f"[{timestamp}] [{tag}] {msg}\n")
        self.log.see(tk.END)
        
        # Força a atualização da interface para não "congelar"
        try:
            self.root.update_idletasks()
        except:
            pass
    
    
    def ativarWpp(self): 
        try:
            if not self.wpp_ativo:
                # --- LÓGICA PARA LIGAR ---
                subprocess.Popen(r'docker-compose up -d', shell=True)
                time.sleep(2)  # Espera o Docker iniciar (ajuste conforme necessário)
                
                url = f"http://localhost:8080/manager/"
                webbrowser.open(url)
                self.wpp_ativo = True
                self.btn_wpp.config(
                    text="WPP ATIVO", 
                    bg="#25D366", # Verde WhatsApp
                    fg="white"
                )
                self.logger("WhatsApp/Docker iniciado com sucesso.", "SUCESSO")
            else:
                # --- LÓGICA PARA DESLIGAR ---
                subprocess.Popen(r'docker-compose stop', shell=True)
                
                self.wpp_ativo = False
                self.btn_wpp.config(
                    text="LOGAR WPP", 
                    bg="#FF0000", # Volta para o Vermelho
                    fg="white"
                )
                self.logger("WhatsApp/Docker interrompido.", "AVISO")
                
        except Exception as e:  
            messagebox.showerror("Erro no WhatsApp", f"Falha ao alterar estado do serviço: {e}")
            self.logger(f"Erro ao alternar WPP: {e}", "ERRO") 
        
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
        
        # Lista todos os tokens disponíveis
        tokens = [valor for chave, valor in config.items() if chave.startswith("TOKEN_MP") and valor]
        if not tokens:
            self.logger("Token do Mercado Pago não encontrado.", "ERRO")
            return
            
        atualizados = 0
        
        for order_id, d in db.items():
            # --- LÓGICA PARA BOLETO NORMAL ---
            if d.get('boleto_enviado') and not d.get('boleto_pago'):
                payment_id = d.get('id_payment')
                encontrado_em_algum_token = False
                ultimo_erro = ""

                for token in tokens:
                    url = f"https://api.mercadopago.com/v1/payments/{payment_id}"
                    headers = {"Authorization": f"Bearer {token}"}
                    response = requests.get(url, headers=headers)
                    
                    if response.status_code == 200:
                        encontrado_em_algum_token = True
                        resultado = response.json().get('status')
                        if resultado in ['approved', 'refunded']:
                            db[order_id]['boleto_pago'] = True
                            db[order_id]['data_boleto_pago'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                            atualizados += 1
                            self.logger(f"Ordem {order_id}: Boleto marcado como pago.")
                        break  # Se achou o pagamento (200), para de testar outros tokens
                    
                    else:
                        # Guarda o erro caso nenhum token funcione
                        ultimo_erro = f"{response.status_code} - {response.text}"

                # Se após testar todos os tokens, não houve sucesso (200)
                if not encontrado_em_algum_token:
                    # Se o último erro capturado foi 404, marca como vencido
                    if "404" in ultimo_erro:
                        db[order_id]['boleto_vencido'] = True
                        self.logger(f"Ordem {order_id}: Boleto não encontrado (vencido).", "AVISO")
                    else:
                        self.logger(f"Erro ao verificar ordem {order_id}: {ultimo_erro}", "ERRO")

            # --- LÓGICA PARA BOLETO DOBRO ---
            if d.get('boleto_pago') and d.get('cobrado_dobro') and not d.get('boleto_pago_dobro'):
                payment_id_dobro = d.get('id_payment_dobro')
                encontrado_dobro = False
                ultimo_erro_dobro = ""

                for token in tokens:
                    url = f"https://api.mercadopago.com/v1/payments/{payment_id_dobro}"
                    headers = {"Authorization": f"Bearer {token}"}
                    response = requests.get(url, headers=headers)

                    if response.status_code == 200:
                        encontrado_dobro = True
                        resultado = response.json().get('status')
                        if resultado in ['approved', 'refunded']:
                            db[order_id]['boleto_pago_dobro'] = True
                            db[order_id]['data_boleto_pago_dobro'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                            atualizados += 1
                            self.logger(f"Ordem {order_id}: Boleto dobro pago.")
                        break
                    else:
                        ultimo_erro_dobro = f"{response.status_code} - {response.text}"

                if not encontrado_dobro:
                    if "404" in ultimo_erro_dobro:
                        db[order_id]['boleto_vencido_dobro'] = True
                    self.logger(f"Erro boleto dobro {order_id}: {ultimo_erro_dobro}", "ERRO")

        self.salvar_db(db)
        self.logger(f"Atualização finalizada. Pagos: {atualizados}")  

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
    
    def iniciar_thread_processamento(self, acao="solicitar"):
        """Inicia o processamento baseado no botão clicado."""
        folder = self.get_pasta_conta()
        if not folder: return
        
        token = self.get_token_ml(folder)
        if not token: return
        
        config = self.carregar_config_cliente(folder)
        if not config: return
        
        prazo_usuario = self.var_prazo.get()
        pagInicial = self.var_pag_inicial.get()
        
        if acao == "solicitar" or acao == "rastreio":
          if not prazo_usuario or not pagInicial:
            self.logger("Erro: Prazo e Página Inicial são obrigatórios.", "ERRO")
            return
        
        if acao in ["boleto", "agradecimento", "cobrar_dobrado"]:
            if not self.var_data_entrega.get().strip():
                self.logger("Erro: Data de Entrega é obrigatória para esta ação.", "ERRO")
                return
            
        executar_reclamacao = self.rodar_reclamacao_var.get()
        if executar_reclamacao: 
            self.logger("Modo RECLAMAÇÕES ativado: Serão processados apenas os pedidos com reclamações abertas.")
            chats, total_chats = self.buscar_todas_reclamacoes(token, offset=pagInicial)
        else:
            self.logger("Modo COMUM ativado: Serão processados todos os pedidos.")
            chats, total_chats = self.buscar_vendas_paginadas(config['ML_SELLER_ID'], token, offset_inicial=pagInicial)
        
        self.logger(f"Iniciando ação: {acao.upper()}...")
        
        self.progress["maximum"] = total_chats
        self.progress["value"] = 0

        # Inicializa todas as flags como False
        env_rastreio = False
        rodar_wpp = False
        lim_rastreio = 0
        env_boleto = False
        lim_boleto = 0
        env_erroBoleto = False
        reenviarBoleto = False
        solicitar = False
        env_boleto_agradecimento = False
        cobrar_dobrado = False
        cod_rastreio = self.var_rastreio.get().strip()
        tipo_proc = "all"
        processarByid = messagebox.askyesno("Processar", "Deseja processar apenas os IDs específicos inseridos no campo 'Ordem IDs'?")
        if processarByid:
            ids_input = self.var_ordem_ids.get().strip()
            if not ids_input:
                messagebox.showerror("Erro", "Para processar por ID, preencha o campo 'Ordem IDs'!")
                return
            tipo_proc = "by_id"
            self.logger(f"Iniciando processamento by IDs")

        if self.rodar_wa_var.get():
            if self.wpp_ativo:
               rodar_wpp = True
               self.logger("Processamento via WhatsApp selecionado. As mensagens serão enviadas usando a API do WhatsApp.")
            else:
               self.logger("Erro: Para enviar mensagens via WhatsApp, o serviço deve estar ativo. Por favor, ative o WhatsApp antes de iniciar esta ação.", "ERRO")
               return
        
        # Define as flags de acordo com o botão apertado
        if acao == "rastreio":
            if not cod_rastreio:
                messagebox.showerror("Erro", "Preencha o campo 'Cód. Rastreio'!")
                return
            lim_rastreio = simpledialog.askinteger("Limite", f"Quantos rastreios enviar? (Total: {total_chats})", minvalue=1)
            if not lim_rastreio: return
            env_rastreio = True

        elif acao == "boleto":
            lim_boleto = simpledialog.askinteger("Limite", f"Quantos boletos enviar? (Total: {total_chats})", minvalue=1)
            if not lim_boleto: return
            env_boleto = True

        elif acao == "erro_boleto":
            env_erroBoleto = True

        elif acao == "reenviar_boleto":
            reenviarBoleto = True

        elif acao == "agradecimento":
            env_boleto_agradecimento = True
        elif acao == "solicitar":
            solicitar = True    
        elif acao == "cobrar_dobrado":
            cobrar_dobrado = True 
            
            
        # Dispara a thread com a configuração específica
        thread = threading.Thread(
            target=self.passo_1_solicitar, 
            args=(token, env_rastreio, lim_rastreio, cod_rastreio, env_boleto, lim_boleto, 
                  pagInicial, prazo_usuario, chats, config, env_erroBoleto, tipo_proc, 
                  env_boleto_agradecimento, reenviarBoleto, solicitar,cobrar_dobrado,executar_reclamacao,rodar_wpp )
        )
        thread.daemon = True
        thread.start()
        self.logger(f"Thread de {acao} iniciada...")
    
    # --- PASSO 1: SOLICITAÇÃO ---
    def passo_1_solicitar(self, token, env_rastreio, lim_rastreio, cod_rastreio, env_boleto, lim_boleto, pagInicial, prazo_usuario, chats, config,env_erroBoleto, tipo,env_boleto_agradecimento,reenviarBoleto,solicitar,cobrar_dobrado,executar_reclamacao,rodar_wpp):
        folder = self.get_pasta_conta()
        if not folder: return
        
        token = self.get_token_ml(folder)
        if not token: return
        
        rastreios_contagem = 0
        boletos_contagem = 0
        msg_padrao = f"Olá, tudo bem? O frete é grátis para todo Brasil e o prazo estimado de entrega é até {prazo_usuario}. Lembrando que os produtos são importados, vem de fora do país! Vamos fazer o envio e mandar o código de rastreio. \n \nA transportadora precisa do seu telefone pra preencher os seus dados de entrega e enviar o código de rastreio pra você acompanhar."
        headers = {
            "Authorization": f"Bearer {token}"
        }
        pedidos = chats
        pagInicial = int(pagInicial) - 1
        
        try:
            db = self.carregar_db()
            enviados = 0

            for i, pedido in enumerate(pedidos):
                buyer_id = ""
                nome_prod = ""
                valor = ""
                corProduto = ""   
                claim_id = None

                
                
                if executar_reclamacao:
                    order_id = str(pedido['resource_id'])
                    claim_id = str(pedido['id'])
                else:
                    order_id = str(pedido['id'])
                    buyer_id = str(pedido.get('buyer', {}).get('id'))
                    nome_prod = str(pedido['payments'][0]['reason']) 
                    valor = str(pedido['total_amount'])
                    corProduto = str(pedido['order_items'][0]['item']['variation_attributes'][0]['value_name']) 
                    
                    #if order_id not in db:
                        #self.logger(f"Ordem {order_id} ignorada (não está na lista do banco de dados).")
                        #continue
                       
                if(tipo == "by_id"):
                    ordem_ids_input = self.var_ordem_ids.get().strip()
                    if not ordem_ids_input:
                        self.logger("Erro: Para processamento por ID, o campo 'Ordem IDs' deve ser preenchido.", "ERRO")
                        return
                    ordem_ids = [oid.strip() for oid in ordem_ids_input.split(",")]
                    if order_id not in ordem_ids:
                        self.logger(f"Ordem {order_id} ignorada (não está na lista de IDs).")
                        continue
                
                # APOS 2 OU 3 DIAS DO ENVIO DO CODIGO DE RASTREIO, ENVIAR MSG E BOLETO PARA PAGAMENTO DE TAXA E SALVAR NO DB QUE O BOLETO FOI ENVIADO
                url_msg = f"https://api.mercadolibre.com/messages/packs/{order_id}/sellers/{config['ML_SELLER_ID']}?tag=post_sale"
                # Se a ordem não existe no DB, inicializamos como dicionário vazio
                if order_id not in db:
                    #self.logger(f"Ordem {order_id} ignorada (não está na lista do banco de dados).")
                    #continue
                    db[order_id] = {}
                    
                dados_pedido = db[order_id]    
                
                if(not db[order_id].get('buyer_id')):
                        db[order_id]['buyer_id'] = buyer_id
                
                # Usamos after() para que a Main Thread faça a pintura do widget    
                self.root.after(0, lambda v=i+1: self.progress.configure(value=v))    
                
                if not dados_pedido.get('numero_cliente'):
                    dados_pedido['numero_cliente'] = pagInicial + pedidos.index(pedido) + 1 
                
                
                if order_id in db and (dados_pedido.get('rastreio_enviado')):
                    #data_rastreio = dados_pedido.get('data_rastreio')
                    try:
                        #data_envio = datetime.strptime(data_rastreio, "%d/%m/%Y %H:%M")
                        #diferenca = datetime.now() - data_envio
                        if env_boleto and boletos_contagem < lim_boleto and not dados_pedido.get('boleto_enviado'):
                            self.logger(f"Enviando boleto para pagamento de taxa para a ordem {order_id}...")
                            
                            boleto_numero = None
                            indice_boleto = None
                            id_payment = None
                            boleto_info = self.buscar_proximo_boleto()
                            if boleto_info:
                                boleto_numero = boleto_info["numero"]
                                indice_boleto = boleto_info["indice"]
                                id_payment = boleto_info["id_payment"]
                            if(not boleto_numero):
                                self.logger(f"Não foi possível encontrar um boleto disponível para a ordem {order_id}. Verifique o Excel de registros.", "ERRO")
                                break       
                            # -- AVISO Q TAXOU
                            text = ("Olá, tudo bem?\nO seu painel importado chegou no Brasil. 🥳\nPorém, a Receita Federal taxou o seu produto no valor de R$ 138,98.\n\nÉ necessário realizar o pagamento desta taxa, para dar continuidade na entrega. Caso seja pago hoje, o seu pedido chegará na " + self.var_data_entrega.get().strip() + " 😉\n\nO pagamento é feito exclusivamente pelo boleto do Mercado Pago que enviamos. A transportadora utiliza o sistema do Mercado Pago para garantir a segurança da plataforma!")
                            envio = self.enviarMSG(order_id, buyer_id, text, headers, config['ML_SELLER_ID'], executar_reclamacao, claim_id)
                            if envio:
                                # -- AVISO PRÉ BOLETO
                                text = ("Vamos gerar o boleto agora mesmo!\n\nProntinho, boleto gerado! Só copiar todo o código de barras abaixo e pagar pelo aplicativo do seu Banco: 👇")
                                envioMsgpreBoleto = self.enviarMSG(order_id, buyer_id, text, headers, config['ML_SELLER_ID'], executar_reclamacao, claim_id)
                                if envioMsgpreBoleto:      
                                    # -- NUMERO BOLETO
                                    text = f"{boleto_numero}"
                                    envioBoleto = self.enviarMSG(order_id, buyer_id, text, headers, config['ML_SELLER_ID'], executar_reclamacao, claim_id)
                                    if envioBoleto:
                                        # -- ENVIO COMPROVANTE
                                        text = f"Esperamos o comprovante! Att, Time Living Shop"
                                        envioBoletoComprovante = self.enviarMSG(order_id, buyer_id, text, headers, config['ML_SELLER_ID'], executar_reclamacao, claim_id)
                                        if envioBoletoComprovante:
                                            self.atualizar_status_boleto(indice_boleto)
                                            db[order_id]['boleto_enviado'] = True
                                            db[order_id]['data_boleto'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                                            db[order_id]['codigo_boleto'] = boleto_numero
                                            db[order_id]['id_payment'] = id_payment
                                            rastreios_contagem += 1
                                            self.salvar_db(db)
                                            self.logger(f"Boleto enviado com sucesso para a ordem {order_id}!")
                                            continue
                                        else:
                                            self.logger(f"Falha ao enviar mensagem de comprovante para a ordem {order_id}: {envioBoletoComprovante.text}", "ERRO")
                                    else:
                                        self.logger(f"Falha ao enviar código do boleto para a ordem {order_id}: {envioBoleto.text}", "ERRO")
                                else:
                                    self.logger(f"Falha ao enviar mensagem pré boleto para a ordem {order_id}: {envioMsgpreBoleto.text}", "ERRO")        
                            else:
                                self.logger(f"Falha ao enviar boleto para a ordem {order_id}: {envio.text}", "ERRO")
                        elif dados_pedido.get('boleto_enviado') and not dados_pedido.get('boleto_pago') and env_erroBoleto:
                            # --- ENVIO ATUALIZAR BOLETO 
                            text = ("Olá, tudo bem?\nPor favor, desconsidere o código de barras enviado anteriormente, pois houve uma atualização no system.\n Segue o novo código de barras para pagamento da taxa: 👇\n\n")
                            envio = self.enviarMSG(order_id, buyer_id, text, headers, config['ML_SELLER_ID'], executar_reclamacao, claim_id) 
                            if envio:
                                boleto_numero = None
                                indice_boleto = None
                                id_payment = None
                                
                                boleto_info = self.buscar_proximo_boleto()
                                if boleto_info:
                                    boleto_numero = boleto_info["numero"]
                                    indice_boleto = boleto_info["indice"]
                                    id_payment = boleto_info["id_payment"]
                                if(not boleto_numero):
                                    self.logger(f"Não foi possível encontrar um boleto disponível para a ordem {order_id}. Verifique o Excel de registros.", "ERRO")
                                    break    
                                # -- NUMERO BOLETO
                                text = f"{boleto_numero}"
                                envioBoleto = self.enviarMSG(order_id, buyer_id, text, headers, config['ML_SELLER_ID'], executar_reclamacao, claim_id) 
                                if envioBoleto:
                                    # -- ENVIO COMPROVANTE
                                    text = f"Esperamos o comprovante! Att, Time Living Shop"
                                    envioBoletoComprovante = self.enviarMSG(order_id, buyer_id, text, headers, config['ML_SELLER_ID'], executar_reclamacao, claim_id)
                                    if envioBoletoComprovante:
                                        self.atualizar_status_boleto(indice_boleto)
                                        db[order_id]['boleto_enviado'] = True
                                        db[order_id]['data_boleto'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                                        db[order_id]['codigo_boleto'] = boleto_numero
                                        db[order_id]['id_payment'] = id_payment
                                        self.salvar_db(db)
                                        self.logger(f"Boleto reenviado com sucesso para a ordem {order_id}!")
                                        continue
                                    else:
                                        self.logger(f"Falha ao enviar mensagem de comprovante para a ordem {order_id}: {envioBoletoComprovante.text}", "ERRO")
                        elif dados_pedido.get('boleto_enviado') and dados_pedido.get('boleto_pago') and not dados_pedido.get('boleto_pago_agradecimento') and env_boleto_agradecimento:
                            # --- ENVIO AGRADECIMENTO BOLETO PAGO
                            text = (f"Obrigado, o pagamento da taxa foi realizado Vamos dar continuidade a entrega.\nO seu pedido vai chegar na {self.var_data_entrega.get().strip()} no período da tarde! 😉")
                            envio = self.enviarMSG(order_id, buyer_id, text, headers, config['ML_SELLER_ID'], executar_reclamacao, claim_id)
                            if envio:
                                db[order_id]['boleto_pago_agradecimento'] = True
                                self.salvar_db(db)
                                self.logger(f"Mensagem de boleto pago enviada para a ordem {order_id}.")
                                continue           
                        elif dados_pedido.get('boleto_enviado') and reenviarBoleto:
                                boleto_numero = None
                                indice_boleto = None
                                id_payment = None
                                boleto_info = self.buscar_proximo_boleto()
                                if boleto_info:
                                    boleto_numero = boleto_info["numero"]
                                    indice_boleto = boleto_info["indice"]
                                    id_payment = boleto_info["id_payment"]
                                if(not boleto_numero):
                                    self.logger(f"Não foi possível encontrar um boleto disponível para a ordem {order_id}. Verifique o Excel de registros.", "ERRO")
                                    break       
                                # -- AVISO PRÉ BOLETO
                                text = ("Vamos gerar o boleto agora mesmo!\n\nProntinho, boleto gerado! Só copiar todo o código de barras abaixo e pagar pelo aplicativo do seu Banco: 👇")
                                envioMsgpreBoleto = self.enviarMSG(order_id, buyer_id, text, headers, config['ML_SELLER_ID'], executar_reclamacao, claim_id)                    
                                if envioMsgpreBoleto:   
                                    # -- NUMERO BOLETO   
                                    text = f"{boleto_numero}"
                                    envioBoleto = self.enviarMSG(order_id, buyer_id, text, headers, config['ML_SELLER_ID'], executar_reclamacao, claim_id) 
                                    if envioBoleto:
                                        # -- ENVIO COMPROVANTE
                                        text = f"Esperamos o comprovante! Att, Time Living Shop"
                                        envioBoletoComprovante = self.enviarMSG(order_id, buyer_id, text, headers, config['ML_SELLER_ID'], executar_reclamacao, claim_id)
                                        if envioBoletoComprovante:
                                            self.atualizar_status_boleto(indice_boleto)
                                            db[order_id]['boleto_enviado'] = True
                                            db[order_id]['data_boleto'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                                            db[order_id]['codigo_boleto'] = boleto_numero
                                            db[order_id]['id_payment'] = id_payment
                                            rastreios_contagem += 1
                                            self.salvar_db(db)
                                            self.logger(f"Boleto enviado com sucesso para a ordem {order_id}!")
                                            continue
                                        else:
                                            self.logger(f"Falha ao enviar mensagem de comprovante para a ordem {order_id}: {envioBoletoComprovante.text}", "ERRO")
                                    else:
                                        self.logger(f"Falha ao enviar código do boleto para a ordem {order_id}: {envioBoleto.text}", "ERRO")
                                else:
                                    self.logger(f"Falha ao enviar mensagem pré boleto para a ordem {order_id}: {envioMsgpreBoleto.text}", "ERRO")
                        elif dados_pedido.get('boleto_pago') and dados_pedido.get('boleto_pago_agradecimento') and not dados_pedido.get('cobrado_dobro') and cobrar_dobrado:
                                boleto_numero = None
                                indice_boleto = None
                                id_payment = None
                                boleto_info = self.buscar_proximo_boleto()
                                
                                if boleto_info:
                                    boleto_numero = boleto_info["numero"]
                                    indice_boleto = boleto_info["indice"]
                                    id_payment = boleto_info["id_payment"]
                                if(not boleto_numero):
                                    self.logger(f"Não foi possível encontrar um boleto disponível para a ordem {order_id}. Verifique o Excel de registros.", "ERRO")
                                    break       
                                #COBRAR DOBRO
                                text = (f"Olá, tudo bem?\n\nOcorreu um erro aqui de comunicação com a transportadora e a receita\n\nA taxa era R$238,98 e passaram R$138,98, foi um erro da transportadora\n\nFalta mais R$100 pra pagar a taxa, para a transportadora entregar o seu painel que chegará na {self.var_data_entrega.get().strip()}")
                                envio = self.enviarMSG(order_id, buyer_id, text, headers, config['ML_SELLER_ID'], executar_reclamacao, claim_id)
                                if envio:
                                    # -- AVISO PRÉ BOLETO
                                    text = ("Vamos gerar o boleto agora mesmo!\n\nProntinho, boleto gerado! Só copiar todo o código de barras abaixo e pagar pelo aplicativo do seu Banco: 👇")
                                    envioMsgpreBoleto = self.enviarMSG(order_id, buyer_id, text, headers, config['ML_SELLER_ID'], executar_reclamacao, claim_id)
                                    if envioMsgpreBoleto:      
                                        # -- NUMERO BOLETO   
                                        text = f"{boleto_numero}"
                                        envioBoleto = self.enviarMSG(order_id, buyer_id, text, headers, config['ML_SELLER_ID'], executar_reclamacao, claim_id) 
                                        if envioBoleto:
                                             # -- ENVIO COMPROVANTE
                                            text = f"Esperamos o comprovante! Att, Time Living Shop"
                                            envioBoletoComprovante = self.enviarMSG(order_id, buyer_id, text, headers, config['ML_SELLER_ID'], executar_reclamacao, claim_id)
                                            if envioBoletoComprovante:
                                                self.atualizar_status_boleto(indice_boleto)
                                                db[order_id]['cobrado_dobro'] = True
                                                db[order_id]['data_cobro_dobro'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                                                db[order_id]['codigo_boleto_dobro'] = boleto_numero
                                                db[order_id]['id_payment_dobro'] = id_payment
                                                self.salvar_db(db)
                                                self.logger(f"Mensagem de cobrança dobrada enviada para a ordem {order_id}.")
                                                continue
                                            else:
                                                self.logger(f"Falha ao enviar mensagem de comprovante para a ordem {order_id}: {envioBoletoComprovante.text}", "ERRO")
                                        else:
                                            self.logger(f"Falha ao enviar código do boleto para a ordem {order_id}: {envioBoleto.text}", "ERRO")    
                                    else:
                                        self.logger(f"Falha ao enviar mensagem pré boleto para a ordem {order_id}: {envioMsgpreBoleto.text}", "ERRO")        
                                else:
                                    self.logger(f"Falha ao enviar mensagem de cobrança dobrada para a ordem {order_id}: {envio.text}", "ERRO")            
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
                            # -- ENVIO RASTREIO
                            text = textwrap.dedent(f"""\
                                        ACOMPANHE O SEU PEDIDO
                                        Segue abaixo o seu código de rastreamento:
                                        >>> {cod_rastreio} 

                                        Para rastrear, basta acessar o site oficial dos Correios 👇
                                        https://rastreamento.correios.com.br/app/index.php

                                        Lembrando que:

                                        O produto é importado e PODE SER TAXADO, mas é bem difícil! O pedido é entregue pela transportadora, os Correios apenas fazem o rastreamento e podem demorar até 3 dias para atualizar o status.

                                        Mas não se preocupe, o seu pedido já está a caminho.
                                        
                                        Dúvidas? Estamos à disposição! 😉""").strip()
                            
                            # --- ENVIO DA MENSAGEM (Caso não esteja no DB e não esteja no Chat) ---
                            envio = self.enviarMSG(order_id, buyer_id, text, headers, config['ML_SELLER_ID'], executar_reclamacao, claim_id)
                            db[order_id]['rastreio_enviado'] = True
                            db[order_id]['data_rastreio'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                            db[order_id]['codigo_rastreio'] = cod_rastreio
                            boletos_contagem += 1
                            self.salvar_db(db)
                            continue
                    except Exception as e:
                        self.logger(f"Erro ao verificar data inicial da ordem {order_id}: {str(e)}", "ERRO")
                
                # --- TRATATIVA 2: Validar se a mensagem já existe no chat ---
                if solicitar:
                    conversaCompleta = self.obter_conversa_completa(order_id, order_id, config['ML_SELLER_ID'], token)
                    if order_id in db and (dados_pedido.get('solicitado') and not dados_pedido.get('numero_extraido') and not dados_pedido.get('rastreio_enviado')):
                        for m in conversaCompleta:
                            texto = m.get('texto', '')
                            # Regex robusto para capturar vários formatos de telefone BR
                            match = re.search(r'(?:\+?55\s?)?\(?(\d{2})\)?\s*(9)?\s*(\d{4,5})[\s.-]?(\d{4})', texto)
                            if match:
                                    zap_bruto = "".join(g for g in match.groups() if g is not None)
                                    zap = "".join(re.findall(r'\d+', zap_bruto))
                                    #nome_cli = self.obter_nome_cliente(order_id, token)
                                    db[order_id]['zap_extraido'] = zap
                                    db[order_id]['numero_extraido'] = True
                                    self.salvar_db(db)
                                    self.logger(f"Finalizado extração de telefone para a ordem {order_id}: {zap}")
                                    if not dados_pedido.get('rastreio_enviado'):
                                        # -- AGRADECER TELEFONE
                                        text = "Olá! recebemos seu telefone. Obrigado! \nVamos dar continuidade ao processo de envio do seu pedido. \nAssim que o código de rastreio estiver disponível, enviaremos para você acompanhar a entrega. 😉"
                                        envio = self.enviarMSG(order_id, buyer_id, text, headers, config['ML_SELLER_ID'], executar_reclamacao, claim_id)
                                    break
                            
                    if order_id in db:
                        data_solicitacao = dados_pedido.get('data_solicitacao')
                        if data_solicitacao:
                            try:
                                data_envio = datetime.strptime(data_solicitacao, "%d/%m/%Y %H:%M")
                                diferenca = datetime.now() - data_envio
                                if diferenca.days >= 1 and not dados_pedido.get('numero_extraido') and not dados_pedido.get('tentativa_', 0) < 2 and not dados_pedido.get('boleto_enviado'):
                                    # -- COBRAR NUMERO TELEFONE
                                    text = "Olá! Não recebemos seu telefone. \n A transportadora precisa pra preencher os seus dados de entrega e enviar o código de rastreio pra você acompanhar."
                                    envio = self.enviarMSG(order_id, buyer_id, text, headers, config['ML_SELLER_ID'], executar_reclamacao , claim_id)
                                    if envio:
                                        db[order_id]['data_solicitacao'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                                        db[order_id]['tentativa_'] = dados_pedido.get('tentativa_', 0) + 1
                                        self.salvar_db(db)
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
                    
                
                    # -- ENVIO MSG INICIAL
                    envio = self.enviarMSG(order_id, buyer_id, msg_padrao, headers, config['ML_SELLER_ID'], executar_reclamacao, claim_id)
                    
                    if envio:
                        db[order_id]['solicitado'] = True
                        db[order_id]['buyer_id'] = pedido.get('buyer', {}).get('id')
                        db[order_id]['pack_id'] = pedido.get('pack_id')
                        db[order_id]['corProduto'] = corProduto
                        db[order_id]['produto'] = nome_prod
                        db[order_id]['valor'] = valor
                        db[order_id]['data_solicitacao'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                        db[order_id]['data_solicitacao_inicial'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                        enviados += 1
                        self.salvar_db(db)
                        self.logger(f"Ordem {order_id}: Mensagem enviada e registrada.")
                    else:
                        self.logger(f"Falha ao enviar mensagem para {order_id}", "AVISO")

                self.logger(f"Processamento da ordem {order_id} concluído. Próxima ordem...")
            # Salva o progresso no banco de dados local
            self.salvar_db(db)
            self.logger(f"Fim da Execução. Novas solicitações enviadas: {enviados}")

        except Exception as e:
            self.logger(f"Erro no Passo 1: {str(e)}", "ERRO")
            
    def buscar_proximo_boleto(self):
        caminho_excel = r"C:\Users\mathe\Meu Drive\Sistema JV V1\Nova pasta\dist\registros_pedidos.xlsx"
        
        try:
            df = pd.read_excel(caminho_excel)
            
            for index, row in df.iterrows():
                # Verifica se o boleto não foi usado
                if str(row['Boleto Usado']) == 'False':
                    return {
                        "numero": str(row['Código']),
                        "indice": index,
                        "id_payment": str(row['id_payment'])
                    }
            
            return None  # Retorna None se não encontrar nenhum disponível
            
        except Exception as e:
            self.logger(f"Erro ao ler planilha de boletos: {e}")
            return None
        
    def atualizar_status_boleto(self, indice, status="Enviado"):
        caminho_excel = r"C:\Users\mathe\Meu Drive\Sistema JV V1\Nova pasta\dist\registros_pedidos.xlsx"
        try:
            # Carrega a planilha atualizada
            df = pd.read_excel(caminho_excel)
            
            # Atualiza o valor no índice específico
            df.at[indice, 'Boleto Usado'] = status
            
            # Salva de volta no Excel
            df.to_excel(caminho_excel, index=False)
            return True
        except Exception as e:
            self.logger(f"Erro ao atualizar planilha: {e}")
            return False   
    def enviarMSG(self, order_id, buyer_id, texto_ml, headers=None, seller_id=None, reclamacao=False, claim_id=None):
        """
        Decide se envia via Mercado Livre ou WhatsApp Template.
        """
        db = self.carregar_db()
        dados = db.get(order_id, {})
        
        # Se o flag de WhatsApp estiver ativo E tivermos um template definido
        if self.rodar_wa_var.get():
            if not dados.get('zap_extraido'):
                self.logger(f"Erro: Para enviar via WhatsApp, é necessário ter o número do cliente extraído para a ordem {order_id}.", "ERRO")
                return False
            self.logger(f"Enviando via WhatsApp para {order_id}...")
            res = self.enviar_wa_template(dados,texto_ml, order_id)
            return res
        else:
            return self.enviarMsgML(order_id, buyer_id, texto_ml, headers, seller_id, reclamacao, claim_id)     
        
    def enviarMsgML(self, order_id, buyer_id, texto, headers, ML_SELLER_ID, reclamacao, claim_id): 
        if reclamacao:
            url_msg = f"https://api.mercadolibre.com/post-purchase/v1/claims/{claim_id}/actions/send-message"
            payload = { 
                "receiver_role": "complainant",
                "message": texto
            }
            try:
                envio = requests.post(url_msg, json=payload, headers=headers)
                if envio.status_code in [200, 201]:
                    # Se reclamação foi enviada com sucesso, enviar mensagem de encerramento
                    self.enviar_msg_encerrar_reclamacao(order_id, buyer_id, headers, ML_SELLER_ID, claim_id)
                    return True
                return False
            except Exception as e:
                self.logger(f"Erro ao enviar mensagem de reclamação para {buyer_id}: {str(e)}", "ERRO")
                return False
        else:    
            url_msg = f"https://api.mercadolibre.com/messages/packs/{order_id}/sellers/{ML_SELLER_ID}?tag=post_sale"
            payload = {
                "from": {   
                    "user_id": ML_SELLER_ID
                },
                "to": {
                    "user_id": buyer_id
                },
                "text": texto
            }
            try:
                envio = requests.post(url_msg, json=payload, headers=headers)
                return envio.status_code in [200, 201]
            except Exception as e:
                self.logger(f"Erro ao enviar mensagem COMUM para {buyer_id}: {str(e)}", "ERRO")
                return False
    
    def enviar_msg_encerrar_reclamacao(self, order_id, buyer_id, headers, ML_SELLER_ID, claim_id):
        """
        Envia mensagem para o cliente encerrar a reclamação.
        Máximo 2x por ordem, apenas se o boleto ainda não foi enviado.
        """
        db = self.carregar_db()
        dados_pedido = db.get(order_id, {})
        
        # Verificar se boleto já foi enviado
        if dados_pedido.get('boleto_enviado'):
            self.logger(f"Ordem {order_id}: Boleto já enviado, não enviando msg de encerramento.")
            return False
        
        # Obter contador de envios
        qtd_envios = dados_pedido.get('QtdenvioEncerrarReclamacao', 0)
        
        # Não enviar se já atingiu limite de 2x
        if qtd_envios >= 2:
            self.logger(f"Ordem {order_id}: Limite de 2 mensagens de encerramento atingido.")
            return False
        
        # Preparar e enviar a mensagem
        msg_encerramento = "Poderia encerrar a reclamação, Esse passo é necessário para que o sistema libere a continuidade da sua entrega."
        url_msg = f"https://api.mercadolibre.com/post-purchase/v1/claims/{claim_id}/actions/send-message"
        
        payload = {
            "receiver_role": "complainant",
            "message": msg_encerramento
        }
        
        try:
            envio = requests.post(url_msg, json=payload, headers=headers)
            
            if envio.status_code in [200, 201]:
                # Incrementar contador e salvar
                db[order_id]['QtdenvioEncerrarReclamacao'] = qtd_envios + 1
                self.salvar_db(db)
                self.logger(f"Ordem {order_id}: Mensagem de encerramento enviada ({qtd_envios + 1}/2).")
                return True
            else:
                self.logger(f"Erro ao enviar mensagem de encerramento para {order_id}: Status {envio.status_code}", "AVISO")
                return False
                
        except Exception as e:
            self.logger(f"Erro ao enviar mensagem de encerramento para {order_id}: {str(e)}", "ERRO")
            return False
            
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
    def enviar_wa_template(self, dados, msg, order_id):
        numero = dados.get('zap_extraido')
        
        if not numero.startswith('55'): numero = '55' + numero
        self.logger(f"Enviando WhatsApp para {order_id} no número {numero}")
        
        instance = dados.get('zap_instancia')
        
        url_wa = "https://127.0.0.1:8080/message/sendText/{instance}"
        
        payload = {
            "number": numero,
            "text": msg,
        }
        headers = {
            "apikey": dados.get('zap_api_key'),
            "Content-Type": "application/json"
        }

        try:
            res = requests.post(url_wa, json=payload, headers=headers)
            return res.status_code in [200, 201]
        except Exception as e:
            self.logger(f"Erro WhatsApp: {str(e)}", "ERRO")
            return False
        
    def iniciar_thread_wpp_inicial(self):
     threading.Thread(target=self.processar_chamada_wpp_inicial, daemon=True).start()

    # --- SISTEMA DE WHATSAPP DISTRIBUÍDO ---
    def carregar_config_wpp(self):
        """
        Carrega a configuração dos 5 WhatsApps do arquivo config_wpp.json
        """
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config_wpp.json')
        try:
            if not os.path.exists(config_path):
                self.logger(f"Arquivo config_wpp.json não encontrado em {config_path}", "ERRO")
                return None
            
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            self.logger(f"Erro ao carregar config_wpp.json: {str(e)}", "ERRO")
            return None

    def salvar_config_wpp(self, config_wpp):
        """
        Salva a configuração atualizada dos WhatsApps
        """
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config_wpp.json')
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config_wpp, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            self.logger(f"Erro ao salvar config_wpp.json: {str(e)}", "ERRO")
            return False

    def obter_whatsapp_disponivel(self, config_wpp):
        """
        Obtém o próximo WhatsApp disponível que não atingiu o limite de 200 conversas.
        Retorna: dict com dados do WhatsApp ou None se todos estão cheios
        """
        try:
            whatsapps = config_wpp.get('whatsapps', [])
            
            for wa in whatsapps:
                if wa.get('ativo') and wa.get('contador_enviados', 0) < wa.get('limite', 200):
                    return wa
            
            # Se chegou aqui, todos estão cheios
            self.logger("ALERTA: Todos os 5 WhatsApps atingiram o limite de 200 conversas!", "AVISO")
            return None
            
        except Exception as e:
            self.logger(f"Erro ao obter WhatsApp disponível: {str(e)}", "ERRO")
            return None

    def enviar_msg_wpp_inicial(self, numero, produto, valor, wa_config):
        """
        Envia mensagem inicial via WhatsApp para apresentação da loja.
        """
        try:
            numero_formatado = numero if numero.startswith('55') else f'55{numero}'
            
            msg = (f"Ola, somos a loja bossx4! 👋\n"
                   f"Vi que você comprou o produto: {produto}\n"
                   f"No valor de: R$ {valor}\n\n"
                   f"Vamos dar seguimento à sua entrega por aqui! 📦\n"
                   f"Por favor, adicione nosso número para não perder as atualizações do pedido. 😊")
            
            # Monta a URL da API ZAP
            porta = wa_config.get('porta', '8080')
            instancia = wa_config.get('instancia')
            url_wa = f"https://127.0.0.1:{porta}/message/sendText/{instancia}"
            
            payload = {
                "number": numero_formatado,
                "text": msg,
            }
            
            headers = {
                "apikey": wa_config.get('token'),
                "Content-Type": "application/json"
            }
            
            response = requests.post(url_wa, json=payload, headers=headers, timeout=15, verify=False)
            
            if response.status_code in [200, 201]:
                self.logger(f"Mensagem inicial enviada via WhatsApp ({numero_formatado}) - Instância {instancia}")
                return True
            else:
                self.logger(f"Erro ao enviar via WhatsApp ({numero_formatado}): Status {response.status_code}", "AVISO")
                return False
                
        except requests.exceptions.Timeout:
            self.logger(f"Timeout ao enviar mensagem para {numero} (WhatsApp {wa_config.get('numero')})", "ERRO")
            return False
        except Exception as e:
            self.logger(f"Erro ao enviar mensagem WhatsApp para {numero}: {str(e)}", "ERRO")
            return False

    def processar_chamada_wpp_inicial(self):
        """
        Processa chamadas iniciais via WhatsApp de forma distribuída entre 5 instâncias.
        Máximo 200 mensagens por WhatsApp para evitar bloqueios por spam.
        """
        try:
            db = self.carregar_db()
            config_wpp = self.carregar_config_wpp()
            
            if not db:
                self.logger("Banco de dados vazio. Nenhum contato a processar.", "AVISO")
                return
            
            if not config_wpp:
                self.logger("Falha ao carregar configuração dos WhatsApps.", "ERRO")
                return
            
            self.logger("🚀 Iniciando contato inicial via WhatsApp (Sistema Distribuído)...")
            
            sucess_count = 0
            erro_count = 0
            skip_count = 0
            
            for order_id, dados in db.items():
                try:
                    # Validar condições
                    if not dados.get('numero_extraido'):
                        continue  # Sem número, pular
                    
                    if dados.get('boleto_pago'):
                        continue  # Já pagou, pular
                    
                    if dados.get('contatado_wa'):
                        skip_count += 1
                        continue  # Já foi contatado, pular
                    
                    # Obter WhatsApp disponível
                    wa_disponivel = self.obter_whatsapp_disponivel(config_wpp)
                    if not wa_disponivel:
                        self.logger(f"Abortando: Nenhum WhatsApp disponível. Já processados: {sucess_count}", "AVISO")
                        break
                    
                    # Preparar dados
                    numero = dados.get('numero_extraido')
                    produto = dados.get('produto', 'seu produto')
                    valor = dados.get('valor', 'valor não informado')
                    
                    # Enviar mensagem
                    if self.enviar_msg_wpp_inicial(numero, produto, valor, wa_disponivel):
                        # Atualizar DB com informações do WhatsApp utilizado
                        db[order_id]['contatado_wa'] = True
                        db[order_id]['zap_instancia'] = wa_disponivel.get('instancia')
                        db[order_id]['zap_api_key'] = wa_disponivel.get('token')
                        db[order_id]['porta'] = wa_disponivel.get('porta')
                        db[order_id]['numero_wpp_usado'] = wa_disponivel.get('numero')
                        db[order_id]['data_contatado_wa'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                        
                        # Atualizar contador no config_wpp
                        for wa in config_wpp.get('whatsapps', []):
                            if wa.get('numero') == wa_disponivel.get('numero'):
                                wa['contador_enviados'] = wa.get('contador_enviados', 0) + 1
                                self.logger(f"WhatsApp {wa['numero']}: {wa['contador_enviados']}/200 mensagens enviadas")
                                break
                        
                        sucess_count += 1
                        
                        # Pequeno delay para não sobrecarregar - ALTERAR DPS EM PROD
                        time.sleep(0.5)
                    else:
                        erro_count += 1
                
                except Exception as e:
                    self.logger(f"Erro ao processar ordem {order_id}: {str(e)}", "ERRO")
                    erro_count += 1
                    continue
            
            # Salvar atualizações
            self.salvar_db(db)
            self.salvar_config_wpp(config_wpp)
            
            # Log final
            self.logger(f"✅ Processamento concluído!", "SUCESSO")
            self.logger(f"   ✓ Enviados: {sucess_count}")
            self.logger(f"   ⊘ Pulados (já contatados): {skip_count}")
            self.logger(f"   ✗ Erros: {erro_count}")
            
        except Exception as e:
            self.logger(f"Erro fatal em processar_chamada_wpp_inicial: {str(e)}", "ERRO")    

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
                
    def buscar_todas_reclamacoes(self, token, offset=0):
        reclamacoes_completas = []
        limit = 50
        offset = 0
        
        while True:
                # Filtramos apenas pelas abertas (opened)
                url = f"https://api.mercadolibre.com/post-purchase/v1/claims/search?status=opened&limit={limit}&offset={offset}"
                headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}
                
                try:
                    self.logger(f"Buscando offset {offset}...")   
                    response = requests.get(url, headers=headers)
                    if response.status_code != 200:
                        self.logger(f"Erro API Claims: {response.status_code}", "ERRO")
                        break
                     
                    dados = response.json()
                    claims_da_pagina = dados.get('data', [])
                    reclamacoes_completas.extend(claims_da_pagina)
                    
                    paging = dados.get('paging', {})
                    total = paging.get('total', 0)
                    
                    offset += limit
                    time.sleep(1)
                    if offset >= total:
                        self.logger(f"Busca finalizada. Total capturado: {len(reclamacoes_completas)}")
                        break
                      
                except Exception as e:
                    self.logger(f"Erro na conexão de claims: {e}", "ERRO")
                    break
                
        return reclamacoes_completas, len(reclamacoes_completas) 
        
        
    # --- NOVAS FUNCIONALIDADES: DASHBOARD E EXCEL ---
    def abrir_dashboard_vendas(self):
        db = self.carregar_db()
        if not db:
            messagebox.showinfo("Dashboard", "Banco de dados vazio.")
            return

        etapas = {"Solicitado (E1)": [], "Rastreio (E2)": [], "Boleto (E3)": [], "Boleto Pago (E4)": [], "Boleto Vencido (E5)": [], "Cobrança Dobrada (E6)": [], "Boleto Pago Dobro (E7)": []}
        for oid, dados in db.items():
            
            if dados.get('boleto_pago_dobro'): etapas["Boleto Pago Dobro (E7)"].append(oid)
            elif dados.get('cobrado_dobro'): etapas["Cobrança Dobrada (E6)"].append(oid)
            elif dados.get('boleto_pago'): etapas["Boleto Pago (E4)"].append(oid)
            elif dados.get('boleto_vencido'): etapas["Boleto Vencido (E5)"].append(oid)
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
        cores = ['#007bff', '#ffc107', '#28a745', "#6e1cbb", "#6c757d"]  # Azul, Amarelo, Verde, Roxo, Cinza

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
            "id_payment", "boleto_Pago", "boleto_vencido"
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
                "boleto_Pago": "Sim" if d.get('boleto_pago') else "Não",
                "boleto_vencido": "Sim" if d.get('boleto_vencido') else "Não",
                "cobrança_dobrada": "Sim" if d.get('cobrado_dobro') else "Não",
                "boleto_pago_dobro": "Sim" if d.get('boleto_pago_dobro') else "Não",
                "boleto_vencido_dobro": "Sim" if d.get('boleto_vencido_dobro') else "Não"
                
                
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