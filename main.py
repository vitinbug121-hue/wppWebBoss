import tkinter as tk
from tkinter import scrolledtext, messagebox, simpledialog
import requests
import json
import os
import re
import webbrowser
from datetime import datetime
from dotenv import load_dotenv

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
        # Header
        header = tk.Frame(self.root, bg="#212121", height=60)
        header.pack(fill=tk.X)
        tk.Label(header, text="PAINEL DE CONTROLE DE LEADS", fg="white", bg="#212121", font=("Arial", 14, "bold")).pack(pady=15)

        # Container de Botões
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=20)

        # Estilo dos botões
        estilo = {"width": 25, "height": 2, "font": ("Arial", 10, "bold")}

        tk.Button(btn_frame, text="0. AUTORIZAR APP ML", command=self.fluxo_autorizacao_ml, bg="#9C27B0", fg="white", **estilo).grid(row=0, column=0, padx=10)
        tk.Button(btn_frame, text="1. PEDIR ZAP (NOVOS)", command=self.passo_1_solicitar, bg="#1976D2", fg="white", **estilo).grid(row=0, column=1, padx=10)
        tk.Button(btn_frame, text="2. EXTRAIR DADOS", command=self.passo_2_extrair, bg="#388E3C", fg="white", **estilo).grid(row=0, column=2, padx=10)
        tk.Button(btn_frame, text="3. CHAMAR NO WHATSAPP", command=self.passo_3_disparar_wa, bg="#FBC02D", fg="black", **estilo).grid(row=0, column=3, padx=10)

        # Log
        self.log = scrolledtext.ScrolledText(self.root, height=30, width=150, font=("Consolas", 9), bg="#F5F5F5")
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

    # --- PASSO 1: SOLICITAÇÃO ---
    import requests

    def passo_1_solicitar(self):
        token = self.get_token_ml()
        if not token: 
            return

        msg_padrao = "Olá! A transportadora precisa pra preencher os seus dados de entrega e enviar o código de rastreio pra você acompanhar, por favor envie seu WhatsApp com DDD:"
        
        self.logger("Iniciando varredura de vendas via /orders/search...")
        
        # 1. Buscar vendas recentes com status 'paid'
        url_vendas = f"https://api.mercadolibre.com/orders/search?seller={ML_SELLER_ID}&order.status=paid"
        headers = {'Authorization': f'Bearer {token}'}
        
        try:
            res_vendas = requests.get(url_vendas, headers=headers).json()
            pedidos = res_vendas.get('results', [])
            
            db = self.carregar_db()
            enviados = 0

            for pedido in pedidos:
                # Pegamos o ID da ordem (ou pack_id se preferir, mas seguindo sua instrução: order_id)
                order_id = str(pedido['id'])
                buyer_id = str(pedido.get('buyer', {}).get('id'))
                
                # --- TRATATIVA 1: Controle Local (Banco de Dados) ---
                # Se já marcamos como solicitado no DB, pulamos a consulta de mensagens
                if order_id in db and db[order_id].get('solicitado'):
                    continue

                self.logger(f"Verificando histórico de mensagens para Ordem: {order_id}")
                
                # --- TRATATIVA 2: Validar se a mensagem já existe no chat ---
                url_msg = f"https://api.mercadolibre.com/messages/packs/{order_id}/sellers/{ML_SELLER_ID}?tag=post_sale"
                res_historico = requests.get(url_msg, headers=headers).json()
                mensagens_no_chat = res_historico.get('messages', [])
                
                # Verifica se algum texto no histórico é igual à nossa mensagem padrão
                ja_enviado_no_ml = any(msg_padrao in m.get('text', '') for m in mensagens_no_chat)

                if ja_enviado_no_ml:
                    self.logger(f"Mensagem já constava no chat da Ordem {order_id}. Atualizando controle local.")
                    # Atualizamos o DB para não consultar esta ordem novamente na próxima execução
                    db[order_id] = {"solicitado": True, "data_check": "sync"}
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
                    db[order_id] = {
                        "solicitado": True, 
                        "buyer_id": pedido.get('buyer', {}).get('id'),
                        "pack_id": pedido.get('pack_id')
                    }
                    enviados += 1
                    self.logger(f"Ordem {order_id}: Mensagem enviada e registrada.")
                else:
                    self.logger(f"Falha ao enviar mensagem para {order_id}: {envio.text}", "AVISO")

            # Salva o progresso no banco de dados local
            self.salvar_db(db)
            self.logger(f"Fim do Passo 1. Novas solicitações enviadas: {enviados}")

        except Exception as e:
            self.logger(f"Erro no Passo 1: {str(e)}", "ERRO")

    # --- PASSO 2: EXTRAÇÃO ---
    def passo_2_extrair(self):
        token = self.get_token_ml()
        if not token: return

        db = self.carregar_db()
        headers = {'Authorization': f'Bearer {token}'}
        extraidos = 0

        for order_id, dados in db.items():
            if not dados.get('zap_extraido'):
                pack_id = dados['pack_id']
                url_hist = f"https://api.mercadolibre.com/messages/packs/{pack_id}/sellers/{ML_CLIENT_ID}"
                
                res = requests.get(url_hist, headers=headers)
                if res.status_code == 200:
                    mensagens = res.json().get('messages', [])
                    for m in mensagens:
                        # Se a mensagem for do comprador (diferente do meu ID)
                        if str(m.get('from', {}).get('id')) != str(ML_CLIENT_ID):
                            texto = m.get('text', '')
                            # Regex robusto para capturar vários formatos de telefone BR
                            match = re.search(r'(\d{2})[-.\s]?(9?\d{4})[-.\s]?(\d{4})', texto)
                            
                            if match:
                                zap = "".join(match.groups())
                                # Busca o nome do produto para o DB
                                nome_prod = self.obter_produto_ml(order_id, token)
                                nome_cli = self.obter_nome_cliente(order_id, token)

                                db[order_id].update({
                                    "zap_extraido": zap,
                                    "nome_cliente": nome_cli,
                                    "produto": nome_prod,
                                    "status": "pronto_para_wa"
                                })
                                extraidos += 1
                                self.logger(f"Sucesso: {nome_cli} ({zap}) capturado para o pedido {order_id}")
                                break
        self.salvar_db(db)
        self.logger(f"Fim do Passo 2. Novos números extraídos: {extraidos}")

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
        if os.path.exists(DB_FILE):
            with open(DB_FILE, 'r') as f: return json.load(f)
        return {}

    def salvar_db(self, db):
        with open(DB_FILE, 'w') as f: json.dump(db, f, indent=4)

if __name__ == "__main__":
    root = tk.Tk()
    app = AppColetorPro(root)
    root.mainloop()