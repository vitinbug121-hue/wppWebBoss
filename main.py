import tkinter as tk
from tkinter import scrolledtext, messagebox, simpledialog
from turtle import pd
import requests
import json
import os
import re
import webbrowser
from datetime import datetime, timedelta
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
        tk.Button(btn_frame, text="TRABALHO ESCRAVO ML", command=self.passo_1_solicitar, bg="#1976D2", fg="white", **estilo).grid(row=0, column=1, padx=10)
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
    def passo_1_solicitar(self):
        token = self.get_token_ml()
        if not token: 
            return
        
        # --- SOLICITAÇÃO DO PRAZO AO USUÁRIO ---
        prazo_usuario = simpledialog.askstring("Prazo de Entrega", "Informe o prazo estimado de entrega (ex: 15/05 ou 10 dias):")
        codigo_rastreio = simpledialog.askstring("Código de Rastreio", "Informe o código de rastreio do produto:")
        # Se o usuário clicar em cancelar ou deixar vazio, interrompe o processo
        if not prazo_usuario or not codigo_rastreio:
            self.logger("Operação cancelada: O prazo de entrega e o código de rastreio são obrigatórios.", "AVISO")
            return
        prazo_usuario = (datetime.now() + timedelta(days=5)).strftime("%d/%m")
        msg_padrao = f"Olá, tudo bem? O frete é grátis para todo Brasil e o prazo estimado de entrega é até {prazo_usuario}. Lembrando que os produtos são importados, vem de fora do país! Vamos fazer o envio e mandar o código de rastreio. \n \n \n A transportadora precisa do seu telefone pra preencher os seus dados de entrega e enviar o código de rastreio pra você acompanhar."
        
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
                nome_prod = str(pedido['payments'][0]['reason']) 
                valor = str(pedido['total_amount'])
                corProduto = str(pedido['order_items'][0]['item']['variation_attributes'][0]['value_name'])
                # APOS 2 OU 3 DIAS DO ENVIO DO CODIGO DE RASTREIO, ENVIAR MSG E BOLETO PARA PAGAMENTO DE TAXA E SALVAR NO DB QUE O BOLETO FOI ENVIADO
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

                            payload = {
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
                            envio = requests.post(url_msg, json=payload, headers=headers)
                            if envio.status_code in [200, 201]:
                                db[order_id]['boleto_enviado'] = True
                                db[order_id]['data_boleto'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                                self.logger(f"Boleto enviado com sucesso para a ordem {order_id}!")
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
                            payload = {
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
                            envio = requests.post(url_msg, json=payload, headers=headers)
                            db[order_id]['rastreio_enviado'] = True
                            db[order_id]['data_rastreio'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                            db[order_id]['codigo_rastreio'] = codigo_rastreio
                            self.salvar_db(db)
                    except Exception as e:
                        self.logger(f"Erro ao verificar data inicial da ordem {order_id}: {str(e)}", "ERRO")

                if order_id in db:
                    data_solicitacao = db[order_id].get('data_solicitacao')
                    if data_solicitacao:
                        try:
                            data_envio = datetime.strptime(data_solicitacao, "%d/%m/%Y %H:%M")
                            diferenca = datetime.now() - data_envio
                            if diferenca.days >= 1 and not db[order_id].get('numero_extraido') and not db[order_id].get('rastreio_enviado'):
                                payload = {
                                "from": {
                                    "user_id": ML_SELLER_ID
                                },
                                "to": {
                                    "user_id": buyer_id
                                },
                                "text": "Olá! Não recebemos seu telefone. \n A transportadora precisa pra preencher os seus dados de entrega e enviar o código de rastreio pra você acompanhar."
                            }
                            # --- ENVIO DA MENSAGEM (Caso não esteja no DB e não esteja no Chat) ---
                            envio = requests.post(url_msg, json=payload, headers=headers)
                            if envio.status_code in [200, 201]:
                                db[order_id]['data_solicitacao'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                                self.logger(f"Reenvio: Mensagem reenviada para {order_id} após 1 dia sem resposta.")
                        except Exception as e:
                            self.logger(f"Erro ao reenviar mensagem para {order_id}: {str(e)}", "ERRO")    

                if order_id in db and (db[order_id].get('solicitado')):
                    self.logger(f"Mensagem já Enviada no chat da Ordem {order_id}...")
                    continue

                self.logger(f"Verificando histórico de mensagens para Ordem: {order_id}")
                
                # --- TRATATIVA 2: Validar se a mensagem já existe no chat ---
                url_msg = f"https://api.mercadolibre.com/messages/packs/{order_id}/sellers/{ML_SELLER_ID}?tag=post_sale"
                res_historico = requests.get(url_msg, headers=headers).json()
                mensagens_no_chat = res_historico.get('messages', [])
                
                # Verifica se algum texto no histórico é igual à nossa mensagem padrão
                #buscar apenas pelo pedaço da frase "Olá, tudo bem? O frete é grátis para todo Brasil"
                msg_padrao_parte = "Olá, tudo bem? O frete é grátis para todo Brasil"
                ja_enviado_no_ml = any(msg_padrao_parte in m.get('text', '') for m in mensagens_no_chat)

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
                        "pack_id": pedido.get('pack_id'),
                        "corProduto": corProduto,
                        "produto": nome_prod,
                        "valor": valor,
                        "numero_extraido": False,
                        "data_solicitacao": datetime.now().strftime("%d/%m/%Y %H:%M"),
                        "data_solicitacao_inicial": datetime.now().strftime("%d/%m/%Y %H:%M")
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