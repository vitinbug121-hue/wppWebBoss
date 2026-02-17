import tkinter as tk
from tkinter import scrolledtext, messagebox
import requests
import json
import os
import re
from datetime import datetime

# --- CONFIGURAÇÕES MERCADO LIVRE ---
ML_ACCESS_TOKEN = 'SEU_ACCESS_TOKEN_ML'
SELLER_ID = 'SEU_ID_DE_VENDEDOR'
DB_FILE = 'vendas_coleta.json'
CONTATOS_FILE = 'base_clientes.txt'

# --- CONFIGURAÇÕES WHATSAPP (META CLOUD API) ---
# Obtenha em: developers.facebook.com
WA_TOKEN = 'SEU_TOKEN_META'
WA_PHONE_NUMBER_ID = 'SEU_PHONE_NUMBER_ID'
WA_VERSION = 'v18.0' # Verifique a versão atual na documentação

class AppColetorZap:
    def __init__(self, root):
        self.root = root
        self.root.title("Sistema de Gestão de Leads - ML para WhatsApp")
        self.root.geometry("950x750")

        tk.Label(root, text="Automação: Coleta ML -> WhatsApp Meta API", font=("Arial", 12, "bold")).pack(pady=10)
        
        btn_frame = tk.Frame(root)
        btn_frame.pack(pady=10)

        tk.Button(btn_frame, text="1. Pedir Zap (ML)", command=self.pedir_whatsapp, bg="#D1E8FF", width=25).grid(row=0, column=0, padx=5)
        tk.Button(btn_frame, text="2. Extrair Dados", command=self.extrair_dados, bg="#C8E6C9", width=25).grid(row=0, column=1, padx=5)
        tk.Button(btn_frame, text="3. Chamar Novos no Zap", command=self.chamar_no_whatsapp, bg="#FFCC80", width=25).grid(row=0, column=2, padx=5)

        self.log = scrolledtext.ScrolledText(root, height=25, width=130, font=("Consolas", 9))
        self.log.pack(pady=10)

    def logger(self, texto, tipo="INFO"):
        prefixo = f"[{datetime.now().strftime('%H:%M:%S')}] [{tipo}]"
        self.log.insert(tk.END, f"{prefixo} {texto}\n")
        self.log.see(tk.END)
        self.root.update_idletasks()

    # --- FUNÇÃO DE ENVIO API WHATSAPP (META) ---
    def enviar_whatsapp_meta(self, numero, nome_cliente, produto):
        """ Envia mensagem usando a API oficial da Meta """
        # Limpar o número para conter apenas dígitos e garantir formato internacional (Ex: 5511999999999)
        numero_limpo = re.sub(r'\D', '', numero)
        if not numero_limpo.startswith('55'):
            numero_limpo = '55' + numero_limpo

        url = f"https://graph.facebook.com/{WA_VERSION}/{WA_PHONE_NUMBER_ID}/messages"
        headers = {
            "Authorization": f"Bearer {WA_TOKEN}",
            "Content-Type": "application/json"
        }
        
        # Estrutura de mensagem de texto simples
        # NOTA: A Meta exige que a primeira mensagem seja um TEMPLATE aprovado 
        # se o cliente não falou com você nas últimas 24h.
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": numero_limpo,
            "type": "text",
            "text": {
                "body": f"Atendimento WhatsApp\n\nOlá {nome_cliente}!\nReferente ao seu pedido: {produto}\nComo podemos ajudar?"
            }
        }

        try:
            res = requests.post(url, json=payload, headers=headers, timeout=10)
            return res.status_code in [200, 201]
        except Exception as e:
            self.logger(f"Erro na API Meta: {e}", "ERRO")
            return False

    # --- PASSO 3: CHAMAR NOVOS ---
    def chamar_no_whatsapp(self):
        self.logger("Iniciando rotina de chamadas no WhatsApp...")
        db = self.carregar_db()
        contatos_chamados = 0
        
        # Filtra no DB quem tem número salvo mas ainda não foi contatado
        for order_id, dados in db.items():
            if dados.get('zap') and not dados.get('contatado'):
                nome = dados.get('nome', 'Cliente')
                produto = dados.get('produto', 'Pedido ML')
                numero = dados.get('zap')

                self.logger(f"Chamando {nome} ({numero})...")
                
                if self.enviar_whatsapp_meta(numero, nome, produto):
                    # Marca como contatado para não repetir
                    db[order_id]['contatado'] = True
                    db[order_id]['data_contato'] = datetime.now().strftime("%Y-%m-%d %H:%M")
                    contatos_chamados += 1
                    self.logger(f"Sucesso: {nome} notificado!", "ZAP")
                else:
                    self.logger(f"Falha ao enviar para {nome}. Verifique Token/Configurações.", "ERRO")

        self.salvar_db(db)
        self.logger(f"Fim da rotina. {contatos_chamados} novos clientes foram chamados.")

    # --- PASSO 2: EXTRAÇÃO (ATUALIZADO PARA ALIMENTAR O DB) ---
    def extrair_dados(self):
        self.logger("Varrendo chats para buscar respostas dos clientes...")
        chats = self.buscar_chats()
        db = self.carregar_db()
        contatos_extraidos = 0

        for chat in chats:
            pack_id = chat['id']
            order_id = str(chat['order_id'])
            
            # Puxa histórico do chat
            url_conversa = f"https://api.mercadolibre.com/messages/packs/{pack_id}/sellers/{SELLER_ID}"
            headers = {'Authorization': f'Bearer {ML_ACCESS_TOKEN}'}
            res = requests.get(url_conversa, headers=headers)
            
            if res.status_code == 200:
                mensagens = res.json().get('messages', [])
                for m in mensagens:
                    if str(m.get('from', {}).get('id')) != str(SELLER_ID):
                        texto = m.get('text', '')
                        num_encontrado = re.search(r'(\d{2}\s?9?\d{4}-?\d{4})', texto)
                        
                        if num_encontrado:
                            zap = num_encontrado.group(1)
                            # Se já temos o zap e não tínhamos gravado no DB, atualiza
                            if order_id in db and not db[order_id].get('zap'):
                                nome_cliente = chat.get('buyer', {}).get('first_name', 'Cliente')
                                nome_produto = self.obter_nome_produto(order_id)
                                
                                # Atualiza DB com dados para o WhatsApp
                                db[order_id]['zap'] = zap
                                db[order_id]['nome'] = nome_cliente
                                db[order_id]['produto'] = nome_produto
                                db[order_id]['contatado'] = db[order_id].get('contatado', False)
                                
                                # Salva também no TXT como backup
                                linha = f"CLIENTE: {nome_cliente} | PRODUTO: {nome_produto} | ZAP: {zap}\n"
                                self.salvar_no_txt(linha, order_id)
                                
                                self.logger(f"DADO CAPTURADO: {nome_cliente} -> {zap}")
                                contatos_extraidos += 1
                                break 
        self.salvar_db(db)
        self.logger(f"Extração finalizada. {contatos_extraidos} novos números prontos para chamar.")

    # --- MÉTODOS AUXILIARES (IGUAIS AO ANTERIOR) ---
    def obter_nome_produto(self, order_id):
        try:
            url = f"https://api.mercadolibre.com/orders/{order_id}"
            headers = {'Authorization': f'Bearer {ML_ACCESS_TOKEN}'}
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                return res.json()['order_items'][0]['item']['title']
            return "Produto Não Identificado"
        except: return "Erro ao buscar produto"

    def pedir_whatsapp(self):
        self.logger("Iniciando solicitação de Zap nos novos pedidos...")
        chats = self.buscar_chats()
        db = self.carregar_db()
        for chat in chats:
            order_id = str(chat['order_id'])
            if order_id not in db:
                msg = "Olá! Para agilizarmos o envio do seu rastreio, por favor, envie seu WhatsApp com DDD:"
                if self.enviar_mensagem_ml(chat['id'], msg):
                    db[order_id] = {"solicitado": True, "contatado": False, "data_solicitacao": datetime.now().strftime("%Y-%m-%d")}
                    self.logger(f"Pedido {order_id}: Mensagem enviada no ML.")
        self.salvar_db(db)

    def buscar_chats(self):
        try:
            url = f"https://api.mercadolibre.com/messages/packs/search?seller_id={SELLER_ID}&tag=post_sale"
            headers = {'Authorization': f'Bearer {ML_ACCESS_TOKEN}'}
            res = requests.get(url, headers=headers, timeout=15)
            return res.json().get('results', [])
        except: return []

    def enviar_mensagem_ml(self, pack_id, texto):
        try:
            url = f"https://api.mercadolibre.com/messages/packs/{pack_id}/sellers/{SELLER_ID}?tag=post_sale"
            headers = {'Authorization': f'Bearer {ML_ACCESS_TOKEN}'}
            res = requests.post(url, json={"text": texto}, headers=headers)
            return res.status_code in [200, 201]
        except: return False

    def carregar_db(self):
        if os.path.exists(DB_FILE):
            with open(DB_FILE, 'r') as f: return json.load(f)
        return {}

    def salvar_db(self, db):
        with open(DB_FILE, 'w') as f: json.dump(db, f, indent=4)

    def salvar_no_txt(self, linha, order_id):
        if os.path.exists(CONTATOS_FILE):
            with open(CONTATOS_FILE, 'r') as f:
                if order_id in f.read(): return False
        with open(CONTATOS_FILE, 'a') as f:
            f.write(f"ID:{order_id} | {linha}")
        return True

if __name__ == "__main__":
    root = tk.Tk()
    app = AppColetorZap(root)
    root.mainloop()