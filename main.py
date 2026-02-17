import tkinter as tk
from tkinter import scrolledtext
import requests
import json
import os
import re
from datetime import datetime

# --- CONFIGURAÇÕES ---
ACCESS_TOKEN = 'SEU_ACCESS_TOKEN'
SELLER_ID = 'SEU_ID_DE_VENDEDOR'
DB_FILE = 'vendas_coleta.json'
CONTATOS_FILE = 'base_clientes.txt'

class AppColetorZap:
    def __init__(self, root):
        self.root = root
        self.root.title("Sistema de Coleta de Leads ML - Full Data")
        self.root.geometry("900x700")

        tk.Label(root, text="Automação: Captura de Nome de Produto e WhatsApp", font=("Arial", 12, "bold")).pack(pady=10)
        
        btn_frame = tk.Frame(root)
        btn_frame.pack(pady=10)

        tk.Button(btn_frame, text="Passo 1: Pedir Zap (Novos)", command=self.pedir_whatsapp, bg="#D1E8FF", width=35).grid(row=0, column=0, padx=5)
        tk.Button(btn_frame, text="Passo 2: Extrair Produto + Zap", command=self.extrair_dados, bg="#C8E6C9", width=35).grid(row=0, column=1, padx=5)

        self.log = scrolledtext.ScrolledText(root, height=25, width=160, font=("Consolas", 9))
        self.log.pack(pady=10)

    def logger(self, texto, tipo="INFO"):
        prefixo = f"[{datetime.now().strftime('%H:%M:%S')}] [{tipo}]"
        self.log.insert(tk.END, f"{prefixo} {texto}\n")
        self.log.see(tk.END)
        self.root.update_idletasks()

    # --- NOVO: BUSCAR NOME DO PRODUTO VIA API ---
    def obter_nome_produto(self, order_id):
        try:
            url = f"https://api.mercadolibre.com/orders/{order_id}"
            headers = {'Authorization': f'Bearer {ACCESS_TOKEN}'}
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                # Pega o título do primeiro item da lista de itens da venda
                return data['order_items'][0]['item']['title']
            return "Produto Não Identificado"
        except Exception as e:
            return f"Erro ao buscar produto: {str(e)}"

    # --- PASSO 1: SOLICITAÇÃO ATUALIZADO ---
    def pedir_whatsapp(self):
        self.logger("Iniciando conferência de novos pedidos...")
        chats = self.buscar_chats()
        db = self.carregar_db()
        
        # Contador de chats lidos
        total_chats = len(chats)
        self.logger(f"Total de chats identificados para leitura: {total_chats}")
        
        chats_processados = 0
        for chat in chats:
            order_id = str(chat['order_id'])
            pack_id = chat['id']
            chats_processados += 1
            
            if order_id not in db or not db[order_id].get('solicitado'):
                msg = "Olá! Para agilizarmos o envio do seu rastreio e fotos do pacote, por favor, envie seu WhatsApp com DDD:"
                
                if self.enviar_mensagem(pack_id, msg):
                    db[order_id] = {
                        "solicitado": True, 
                        "data_pedido": datetime.now().strftime("%Y-%m-%d")
                    }
                    self.logger(f"[{chats_processados}/{total_chats}] Pedido {order_id}: Mensagem enviada.")

        self.salvar_db(db)
        self.logger(f"Conferência finalizada. Total de chats lidos: {total_chats}")

    # --- PASSO 2: EXTRAÇÃO ATUALIZADO ---
    def extrair_dados(self):
        self.logger("Varrendo chats e consultando produtos...")
        chats = self.buscar_chats()
        
        total_chats = len(chats)
        self.logger(f"Analisando histórico de {total_chats} conversas...")
        
        contatos_salvos = 0
        chats_analisados = 0

        for chat in chats:
            pack_id = chat['id']
            order_id = str(chat['order_id'])
            chats_analisados += 1
            
            # Puxa histórico do chat
            url_conversa = f"https://api.mercadolibre.com/messages/packs/{pack_id}/sellers/{SELLER_ID}"
            headers = {'Authorization': f'Bearer {ACCESS_TOKEN}'}
            res = requests.get(url_conversa, headers=headers)
            
            if res.status_code == 200:
                mensagens = res.json().get('messages', [])
                
                for m in mensagens:
                    if str(m.get('from', {}).get('id')) != str(SELLER_ID):
                        texto = m.get('text', '')
                        num_encontrado = re.search(r'(\d{2}\s?9?\d{4}-?\d{4})', texto)
                        
                        if num_encontrado:
                            zap = num_encontrado.group(1)
                            nome_cliente = chat.get('buyer', {}).get('first_name', 'Cliente')
                            data_venda = datetime.now().strftime("%d/%m/%Y")
                            nome_produto = self.obter_nome_produto(order_id)

                            linha = f"CLIENTE: {nome_cliente} | PRODUTO: {nome_produto} | DATA: {data_venda} | ZAP: {zap}\n"
                            
                            if self.salvar_no_txt(linha, order_id):
                                self.logger(f"[{chats_analisados}/{total_chats}] EXTRAÍDO: {nome_cliente} ({zap})")
                                contatos_salvos += 1
                                break 

        self.logger(f"Fim da análise. Chats lidos: {total_chats} | Novos contatos salvos: {contatos_salvos}")
        self.logger("Varrendo chats e consultando produtos...")
        chats = self.buscar_chats()
        contatos_salvos = 0

        for chat in chats:
            pack_id = chat['id']
            order_id = str(chat['order_id'])
            
            # 1. Puxa histórico do chat
            url_conversa = f"https://api.mercadolibre.com/messages/packs/{pack_id}/sellers/{SELLER_ID}"
            headers = {'Authorization': f'Bearer {ACCESS_TOKEN}'}
            res = requests.get(url_conversa, headers=headers)
            
            if res.status_code == 200:
                mensagens = res.json().get('messages', [])
                
                for m in mensagens:
                    # Se não for mensagem do vendedor
                    if str(m.get('from', {}).get('id')) != str(SELLER_ID):
                        texto = m.get('text', '')
                        # Procura número de telefone
                        num_encontrado = re.search(r'(\d{2}\s?9?\d{4}-?\d{4})', texto)
                        
                        if num_encontrado:
                            zap = num_encontrado.group(1)
                            nome_cliente = chat.get('buyer', {}).get('first_name', 'Cliente')
                            data_venda = datetime.now().strftime("%d/%m/%Y")
                            
                            # BUSCA O PRODUTO REAL AQUI
                            nome_produto = self.obter_nome_produto(order_id)

                            linha = f"CLIENTE: {nome_cliente} | PRODUTO: {nome_produto} | DATA: {data_venda} | ZAP: {zap}\n"
                            
                            if self.salvar_no_txt(linha, order_id):
                                self.logger(f"EXTRAÍDO: {nome_cliente} comprou {nome_produto[:30]}... Tel: {zap}")
                                contatos_salvos += 1
                                break 

        self.logger(f"Processo concluído. {contatos_salvos} novos contatos no TXT.")

    # --- AUXILIARES ---
    def buscar_chats(self):
        try:
            url = f"https://api.mercadolibre.com/messages/packs/search?seller_id={SELLER_ID}&tag=post_sale"
            headers = {'Authorization': f'Bearer {ACCESS_TOKEN}'}
            res = requests.get(url, headers=headers, timeout=15)
            return res.json().get('results', [])
        except: return []

    def enviar_mensagem(self, pack_id, texto):
        try:
            url = f"https://api.mercadolibre.com/messages/packs/{pack_id}/sellers/{SELLER_ID}?tag=post_sale"
            headers = {'Authorization': f'Bearer {ACCESS_TOKEN}'}
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