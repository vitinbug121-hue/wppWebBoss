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
import unicodedata
import webbrowser
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv, set_key
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.ticker import MaxNLocator
import numpy as np
import time
import sys
import socket
import threading
import logging
import subprocess
import argparse
import tempfile
import hashlib
import csv
import calendar
from xml.sax.saxutils import escape
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
from selenium.webdriver.common.action_chains import ActionChains

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


class ProcessamentoInterrompido(Exception):
    """Exceção lançada quando o usuário solicita parada urgente."""
    pass

# Load variables from .env file
load_dotenv()

# ==========================================
# CONFIGURAÇÕES DE API (PREENCHA AQUI)
# ==========================================
WA_TOKEN = 'SEU_TOKEN_PERMANENTE_META'
WA_PHONE_ID = 'SEU_PHONE_NUMBER_ID'
WA_TEMPLATE_NAME = 'atendimento_cliente_ml' # Deve estar aprovado na Meta
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")


def _obter_groq_api_keys():
    """
    Coleta todas as chaves GROQ configuradas no .env, na ordem GROQ_API_KEY1, GROQ_API_KEY2, ...
    Também aceita GROQ_API_KEY (sem número) como primeira chave, para compatibilidade.
    """
    keys = []

    chave_unica = os.environ.get("GROQ_API_KEY")
    if chave_unica:
        keys.append(chave_unica)

    indice = 1
    while True:
        chave = os.environ.get(f"GROQ_API_KEY{indice}")
        if not chave:
            break
        if chave not in keys:
            keys.append(chave)
        indice += 1

    return keys


# Índice da última chave que funcionou, para começar por ela na próxima chamada
# (evita ficar testando chaves já esgotadas toda vez).
_groq_indice_chave_atual = 0




import re  # Certifique-se de importar o re no topo do seu arquivo


class GroqEsgotadoError(RuntimeError):
    """Levantado quando TODAS as chaves GROQ atingiram o limite de uso (429)."""
    pass


def gerar_resposta_groq(system_text, user_text):
    global _groq_indice_chave_atual

    api_keys = _obter_groq_api_keys()
    if not api_keys:
        raise RuntimeError(
            "Nenhuma chave GROQ configurada no arquivo .env. "
            "Defina GROQ_API_KEY1, GROQ_API_KEY2, etc."
        )

    try:
        from groq import Groq, APIStatusError
    except ImportError as exc:
        raise RuntimeError("Biblioteca groq não instalada. Execute: pip install groq") from exc

    total_chaves = len(api_keys)
    erro_final = None

    for offset in range(total_chaves):
        indice = (_groq_indice_chave_atual + offset) % total_chaves
        api_key = api_keys[indice]

        try:
            client = Groq(api_key=api_key, timeout=90.0)
            chat_completion = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_text},
                    {"role": "user", "content": user_text},
                ],
                model=GROQ_MODEL,
                temperature=0.1,
                max_tokens=1536,
                reasoning_effort="low", 
            )
            _groq_indice_chave_atual = indice
            
            # Captura a resposta bruta da API
            resposta_bruta = chat_completion.choices[0].message.content or ""
            
            # Remove o bloco <think>...</think> caso o modelo seja do tipo reasoning (Qwen 3, DeepSeek, etc)
            resposta_limpa = re.sub(r'<think>.*?</think>', '', resposta_bruta, flags=re.DOTALL).strip()
            
            return resposta_limpa

        except APIStatusError as exc:
            status_code = getattr(exc, "status_code", None)
            if status_code == 429:
                erro_final = exc
                continue
            raise RuntimeError(f"Erro na API da Groq: {exc}") from exc

    raise GroqEsgotadoError(
        f"Todas as {total_chaves} chaves GROQ atingiram o limite de uso (erro 429). "
        f"Último erro: {erro_final}"
    )


def _obter_gemini_api_keys():
    """
    Coleta todas as chaves GEMINI configuradas no .env, na ordem
    GEMINI_API_KEY1, GEMINI_API_KEY2, ...
    Também aceita GEMINI_API_KEY (sem número) como primeira chave.
    """
    keys = []

    chave_unica = os.environ.get("GEMINI_API_KEY")
    if chave_unica:
        keys.append(chave_unica)

    indice = 1
    while True:
        chave = os.environ.get(f"GEMINI_API_KEY{indice}")
        if not chave:
            break
        if chave not in keys:
            keys.append(chave)
        indice += 1

    return keys


GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-lite")
_gemini_indice_chave_atual = 0


def gerar_resposta_gemini(system_text, user_text):
    """
    Fallback usado quando todas as chaves da Groq estão esgotadas (GroqEsgotadoError).
    Usa a API do Gemini (Google AI Studio) diretamente.
    Chave gerada em: aistudio.google.com/apikey
    """
    global _gemini_indice_chave_atual

    api_keys = _obter_gemini_api_keys()
    if not api_keys:
        raise RuntimeError(
            "Nenhuma chave GEMINI configurada no arquivo .env. "
            "Defina GEMINI_API_KEY (ou GEMINI_API_KEY1, GEMINI_API_KEY2, etc)."
        )

    try:
        from google import genai
        from google.genai import types
        from google.genai.errors import ClientError, ServerError
    except ImportError as exc:
        raise RuntimeError("Biblioteca google-genai não instalada. Execute: pip install google-genai") from exc

    total_chaves = len(api_keys)
    erro_final = None

    for offset in range(total_chaves):
        indice = (_gemini_indice_chave_atual + offset) % total_chaves
        api_key = api_keys[indice]

        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=user_text,
                config=types.GenerateContentConfig(
                    system_instruction=system_text,
                    temperature=0.1,
                    max_output_tokens=1536,
                ),
            )
            _gemini_indice_chave_atual = indice

            resposta_bruta = response.text or ""
            resposta_limpa = re.sub(r'<think>.*?</think>', '', resposta_bruta, flags=re.DOTALL).strip()
            return resposta_limpa

        except ClientError as exc:
            status_code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
            if status_code == 429:
                erro_final = exc
                continue
            raise RuntimeError(f"Erro na API do Gemini: {exc}") from exc
        except ServerError as exc:
            erro_final = exc
            continue

    raise RuntimeError(
        f"Todas as {total_chaves} chaves GEMINI atingiram o limite de uso (erro 429). "
        f"Último erro: {erro_final}"
    )


def precisa_responder_groq(mensagem_cliente: str) -> bool:
    """
    Classificador rápido: decide se a(s) mensagem(ns) do cliente exigem uma resposta
    do vendedor. Usado como filtro antes de gerar a resposta completa com a IA,
    evitando gastar chamada/tempo em mensagens que são só agradecimento/despedida.
    """
    system_text = (
        "Você é um classificador de mensagens de atendimento ao cliente.\n"
        "Analise a mensagem enviada pelo cliente e determine se ela necessita de uma resposta.\n\n"
        "Regras:\n"
        "1. Retorne TRUE se a mensagem for uma dúvida, pergunta, solicitação, reclamação ou exigir continuidade.\n"
        "2. Retorne TRUE se o cliente informar que já pagou, quitou ou realizou algum pagamento "
        "(ex: 'já paguei', 'paguei ontem', 'fiz o pagamento'), pois isso exige confirmação/baixa por parte do vendedor.\n"
        "3. Retorne FALSE se for apenas um agradecimento, confirmação sem novidade ou despedida "
        "(ex: 'ok', 'obrigado', 'valeu', 'entendi', 'perfeito').\n"
        "4. Cliente mandou saudação como ola, oi, bom dia. Retorne TRUE.\n\n"
        "Sua resposta deve conter EXCLUSIVAMENTE a palavra TRUE ou FALSE."
    )

    resposta_raw = gerar_resposta_groq(system_text, mensagem_cliente)
    resposta_limpa = resposta_raw.strip().upper()
    return "TRUE" in resposta_limpa


# # ALTERAÇÃO: Pasta raiz onde todas as contas ficarão
def _encontrar_accounts_dir():
    """
    Tenta encontrar a pasta 'contas' em múltiplos locais.
    Suporta execução normal e executáveis PyInstaller/Frozen.
    """
    candidates = []
    
    # Se for executável empacotado, o local do exe é o melhor ponto de partida.
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        candidates.append(os.path.join(exe_dir, 'contas'))
        candidates.append(os.path.join(os.path.dirname(exe_dir), 'contas'))
        if getattr(sys, '_MEIPASS', None):
            candidates.append(os.path.join(sys._MEIPASS, 'contas'))
            candidates.append(os.path.join(os.path.dirname(sys._MEIPASS), 'contas'))

    # Diretório do script atual e seu pai
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        candidates.append(os.path.join(script_dir, 'contas'))
        candidates.append(os.path.join(os.path.dirname(script_dir), 'contas'))
    except Exception:
        pass

    # Diretório de trabalho atual e seu pai
    try:
        cwd = os.getcwd()
        candidates.append(os.path.join(cwd, 'contas'))
        candidates.append(os.path.join(os.path.dirname(cwd), 'contas'))
    except Exception:
        pass

    # Retorna o primeiro caminho válido encontrado
    for candidate in candidates:
        try:
            if candidate and os.path.exists(candidate):
                return candidate
        except Exception:
            continue

    # Se não encontrou, usa o diretório do executável ou do script como fallback.
    if getattr(sys, 'frozen', False):
        return os.path.join(os.path.dirname(sys.executable), 'contas')

    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(os.path.dirname(script_dir), 'contas')
    except Exception:
        return os.path.join(os.getcwd(), 'contas')


ACCOUNTS_DIR = _encontrar_accounts_dir()

# ==========================================
# TOKEN DE REEMBOLSO (Mercado Pago) - ÚNICO PARA TODAS AS CONTAS
# Salvo em um .env fora da pasta 'contas', na pasta raiz do programa.
# ==========================================
ENV_FILE_PATH = os.path.join(os.path.dirname(ACCOUNTS_DIR), '.env')
if not os.path.exists(ENV_FILE_PATH):
    try:
        open(ENV_FILE_PATH, 'a', encoding='utf-8').close()
    except Exception:
        pass
load_dotenv(ENV_FILE_PATH, override=True)


_reembolso_indice_token_atual = 0  # carrossel: começa pelo último token que funcionou


def _obter_tokens_reembolso_mp():
    """
    Retorna a lista de tokens de reembolso (Mercado Pago), compartilhados entre
    TODAS as contas. Aceita TOKEN_REEMBOLSO_MP (compatibilidade com o token único
    antigo) e TOKEN_REEMBOLSO_MP1, TOKEN_REEMBOLSO_MP2, ... para múltiplos tokens.
    """
    tokens = []

    token_unico = os.environ.get("TOKEN_REEMBOLSO_MP", "").strip()
    if token_unico:
        tokens.append(token_unico)

    indice = 1
    while True:
        token = os.environ.get(f"TOKEN_REEMBOLSO_MP{indice}", "").strip()
        if not token:
            break
        if token not in tokens:
            tokens.append(token)
        indice += 1

    return tokens


def _salvar_tokens_reembolso_mp(tokens):
    """Salva a lista de tokens de reembolso no .env (fora da pasta 'contas'),
    como TOKEN_REEMBOLSO_MP1, TOKEN_REEMBOLSO_MP2, etc."""
    tokens_limpos = []
    for t in (tokens or []):
        t = (t or "").strip()
        if t and t not in tokens_limpos:
            tokens_limpos.append(t)

    try:
        set_key(ENV_FILE_PATH, "TOKEN_REEMBOLSO_MP", "")  # aposenta o formato antigo
    except Exception:
        pass
    os.environ["TOKEN_REEMBOLSO_MP"] = ""

    indice = 1
    while True:
        chave = f"TOKEN_REEMBOLSO_MP{indice}"
        if indice <= len(tokens_limpos):
            valor = tokens_limpos[indice - 1]
        elif os.environ.get(chave):
            valor = ""  # limpa sobra de config antiga com mais tokens
        else:
            break
        try:
            set_key(ENV_FILE_PATH, chave, valor)
        except Exception:
            pass
        os.environ[chave] = valor
        indice += 1

    return tokens_limpos


def get_registered_emails():
    """
    Obtém a lista de emails cadastrados nas pastas de contas.
    Retorna uma lista de emails (nomes das pastas) ordenados alfabeticamente.
    """
    emails = []
    if os.path.exists(ACCOUNTS_DIR):
        try:
            for pasta in os.listdir(ACCOUNTS_DIR):
                caminho = os.path.join(ACCOUNTS_DIR, pasta)
                if os.path.isdir(caminho):
                    emails.append(pasta)
        except Exception as e:
            print(f"Erro ao listar emails em {ACCOUNTS_DIR}: {e}")
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


def get_account_display_name(email):
    metadata = get_account_metadata(email)
    nome = metadata.get('NOME_EXIBICAO') or metadata.get('nome') or metadata.get('nome_conta') or email
    if nome and nome != email:
        return f"{nome} - {email}"
    return email


def is_account_active(email):
    metadata = get_account_metadata(email)
    ativo = metadata.get('ATIVO')
    return True if ativo is None else bool(ativo)


def get_active_account_display_values():
    return sorted(
        [get_account_display_name(email) for email in get_registered_emails() if is_account_active(email)],
        key=lambda v: v.lower()
    )


def parse_email_from_display(value):
    if not value:
        return value
    if ' - ' in value:
        candidate = value.rsplit(' - ', 1)[1].strip()
        if '@' in candidate:
            return candidate
    return value.strip()


# ==========================================
# CONTROLE DE MÁQUINA/CONTEXTO
# ==========================================
_MACHINE_PREFERENCE_FILE = None  # Será inicializado depois
_MACHINE_OVERRIDE = None


def _normalizar_machine_key(machine_key):
    if not machine_key:
        return None
    machine_key = str(machine_key).strip().lower()
    return machine_key if machine_key in ['cliente', 'desenvolvedor'] else None


def _set_machine_override(machine_key):
    global _MACHINE_OVERRIDE
    _MACHINE_OVERRIDE = _normalizar_machine_key(machine_key)
    return _MACHINE_OVERRIDE


def _registrar_log_agendamento(mensagem):
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        log_dir = os.path.join(base_dir, 'logs_agendamentos')
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f'agendador_{datetime.now().strftime("%Y-%m-%d")}.log')
        with open(log_file, 'a', encoding='utf-8') as f:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{timestamp}] {mensagem}\n")
    except Exception:
        pass

def _get_machine_preference_file():
    """
    Obtém o caminho do arquivo de preferência de máquina.

    IMPORTANTE: esse arquivo NÃO fica dentro da pasta do projeto/executável,
    pois essa pasta normalmente está em uma unidade sincronizada (ex.: Google
    Drive "H:\\Meu Drive\\...") e é sobrescrita a cada atualização/deploy do
    código, apagando a preferência salva (cliente/desenvolvedor) e fazendo o
    app "esquecer" a escolha feita na máquina. Por isso usamos uma pasta fixa
    do usuário (%LOCALAPPDATA% no Windows, ~/.appcoletorpro em outros casos),
    que não é tocada por atualizações de código.
    """
    global _MACHINE_PREFERENCE_FILE
    if _MACHINE_PREFERENCE_FILE:
        return _MACHINE_PREFERENCE_FILE

    try:
        base_local = os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA') or os.path.expanduser('~')
        config_dir = os.path.join(base_local, 'AppColetorPro')
    except Exception:
        config_dir = os.path.join(os.path.expanduser('~'), '.appcoletorpro')

    novo_path = os.path.join(config_dir, 'machine_preference.txt')

    # --- Migração: se existir uma preferência salva no formato antigo (dentro
    # da pasta do projeto/executável) e ainda não existir a nova, copia o
    # valor uma única vez para não perder a escolha já feita pelo usuário. ---
    if not os.path.exists(novo_path):
        try:
            if getattr(sys, 'frozen', False):
                exe_dir = os.path.dirname(sys.executable)
                base_dir_antigo = os.path.dirname(exe_dir) if os.path.basename(exe_dir).lower() == 'dist' else exe_dir
            else:
                base_dir_antigo = os.path.dirname(os.path.abspath(__file__))
            path_antigo = os.path.join(base_dir_antigo, '.machine_preference')
            if os.path.exists(path_antigo):
                with open(path_antigo, 'r', encoding='utf-8') as f_old:
                    valor_antigo = _normalizar_machine_key(f_old.read())
                if valor_antigo:
                    os.makedirs(config_dir, exist_ok=True)
                    with open(novo_path, 'w', encoding='utf-8') as f_new:
                        f_new.write(valor_antigo)
                    print(f"[MACHINE] ✓ Preferência migrada do formato antigo: {valor_antigo}")
        except Exception:
            pass

    _MACHINE_PREFERENCE_FILE = novo_path
    return _MACHINE_PREFERENCE_FILE

def _get_selected_machine_key():
    """Obtém a máquina selecionada do arquivo de preferência (cliente ou desenvolvedor)"""
    if _MACHINE_OVERRIDE:
        return _MACHINE_OVERRIDE

    try:
        pref_file = _get_machine_preference_file()
        if os.path.exists(pref_file):
            with open(pref_file, 'r', encoding='utf-8') as f:
                machine_key = _normalizar_machine_key(f.read())
                if machine_key:
                    return machine_key
    except Exception:
        pass
    # Fallback: tenta hostname, mas retorna 'local' se não conseguir
    try:
        hostname = socket.gethostname() or 'local'
        key = re.sub(r'[^A-Za-z0-9_-]', '_', hostname).strip('_')
        return key or 'local'
    except Exception:
        return 'local'

def _save_machine_preference(machine_key):
    """Salva a preferência de máquina no arquivo (fora da pasta do projeto)"""
    try:
        pref_file = _get_machine_preference_file()
        os.makedirs(os.path.dirname(pref_file), exist_ok=True)
        with open(pref_file, 'w', encoding='utf-8') as f:
            f.write(machine_key.strip())
        print(f"[MACHINE] ✓ Preferência salva: {machine_key}")
        return True
    except Exception as e:
        print(f"[MACHINE] ERRO ao salvar preferência: {e}")
        return False

def _get_machine_key():
    """Retorna a chave de máquina para uso nos nomes de arquivo"""
    return _get_selected_machine_key()


def _encontrar_config_file():
    """
    Tenta encontrar o arquivo de configuração de agendamentos para a máquina atual.
    NÃO usa arquivo genérico - apenas específico da máquina para evitar cruzar dados.
    """
    machine_key = _get_machine_key()
    machine_filename = f"agendamentos_config_{machine_key}.json"

    def _listar_candidatos():
        candidatos = []
        
        # Determina o diretório base (raiz do projeto)
        base_dir = None
        try:
            if getattr(sys, 'frozen', False):
                exe_dir = os.path.dirname(sys.executable)
                # Se está em dist/, o base é o pai
                if os.path.basename(exe_dir).lower() == 'dist':
                    base_dir = os.path.dirname(exe_dir)
                else:
                    base_dir = exe_dir
            else:
                script_dir = os.path.dirname(os.path.abspath(__file__))
                base_dir = script_dir
        except Exception:
            pass

        if base_dir:
            candidatos.append(os.path.join(base_dir, machine_filename))
            print(f"[DEBUG] Base dir detectado: {base_dir}")
        
        # Adiciona CWD como alternativa
        cwd = os.getcwd()
        cwd_machine = os.path.join(cwd, machine_filename)
        if cwd_machine not in candidatos:
            candidatos.append(cwd_machine)

        # Adiciona APPDATA como fallback
        try:
            appdata = os.environ.get('APPDATA') or os.path.expanduser('~')
            user_dir = os.path.join(appdata, 'Sistema Captura WPP')
            candidatos.append(os.path.join(user_dir, machine_filename))
        except Exception:
            pass

        print(f"[DEBUG] Candidatos para config: {candidatos}")
        return candidatos

    def _arquivo_json_valido(path):
        if not path or not os.path.exists(path):
            return False
        try:
            with open(path, 'r', encoding='utf-8') as f:
                conteudo = f.read()
            if not conteudo.strip():
                return False
            json.loads(conteudo)
            return True
        except Exception as e:
            print(f"[DEBUG] Arquivo inválido {path}: {e}")
            return False

    candidatos = _listar_candidatos()

    # Procura arquivo específico da máquina
    for path in candidatos:
        if _arquivo_json_valido(path):
            print(f"[CONFIG] ✓ Arquivo de máquina encontrado: {path}")
            return path

    # Se nenhum arquivo existe, retorna o primeiro candidato para criar
    if candidatos:
        path = candidatos[0]
        parent = os.path.dirname(path)
        if parent and not os.path.exists(parent):
            try:
                os.makedirs(parent, exist_ok=True)
                print(f"[CONFIG] Diretório criado: {parent}")
            except Exception as e:
                print(f"[CONFIG] ERRO ao criar diretório {parent}: {e}")
        print(f"[CONFIG] ✓ Novo arquivo será criado em: {path}")
        return path

    # Fallback: APPDATA
    try:
        appdata = os.environ.get('APPDATA') or os.path.expanduser('~')
        user_dir = os.path.join(appdata, 'Sistema Captura WPP')
        if not os.path.exists(user_dir):
            os.makedirs(user_dir, exist_ok=True)
        fallback = os.path.join(user_dir, machine_filename)
        print(f"[CONFIG] ✓ Usando fallback APPDATA: {fallback}")
        return fallback
    except Exception as e:
        print(f"[CONFIG] ERRO no fallback APPDATA: {e}")
        fallback = os.path.join(os.getcwd(), machine_filename)
        print(f"[CONFIG] ✓ Usando fallback final (CWD): {fallback}")
        return fallback



def _encontrar_historico_file(config_file):
    """Resolve o arquivo de histórico de forma compatível com o diretório do app e o projeto.
    NÃO usa arquivo genérico - apenas específico da máquina."""
    machine_key = _get_machine_key()
    machine_filename = f"agendamentos_historico_{machine_key}.json"
    candidates = []

    # Determina o diretório base (mesmo do config_file ou do projeto)
    base_dir = None
    if config_file:
        base_dir = os.path.dirname(config_file)
        candidates.append(os.path.join(base_dir, machine_filename))
    else:
        try:
            if getattr(sys, 'frozen', False):
                exe_dir = os.path.dirname(sys.executable)
                if os.path.basename(exe_dir).lower() == 'dist':
                    base_dir = os.path.dirname(exe_dir)
                else:
                    base_dir = exe_dir
            else:
                script_dir = os.path.dirname(os.path.abspath(__file__))
                base_dir = script_dir
        except Exception:
            pass

        if base_dir:
            candidates.append(os.path.join(base_dir, machine_filename))

    # Adiciona diretório atual como alternativa
    cwd_candidate = os.path.join(os.getcwd(), machine_filename)
    if cwd_candidate not in candidates:
        candidates.append(cwd_candidate)

    # Adiciona APPDATA como fallback
    try:
        appdata = os.environ.get('APPDATA') or os.path.expanduser('~')
        user_dir = os.path.join(appdata, 'Sistema Captura WPP')
        appdata_candidate = os.path.join(user_dir, machine_filename)
        if appdata_candidate not in candidates:
            candidates.append(appdata_candidate)
    except Exception:
        pass

    print(f"[DEBUG] Candidatos para histórico: {candidates}")

    # Busca arquivo válido
    for path in candidates:
        if not path or not os.path.exists(path):
            continue
        try:
            with open(path, 'r', encoding='utf-8') as f:
                conteudo = f.read()
            if conteudo.strip():
                json.loads(conteudo)
                print(f"[HISTORICO] ✓ Arquivo válido encontrado: {path}")
                return path
        except Exception as e:
            print(f"[DEBUG] Arquivo inválido {path}: {e}")
            continue

    # Se nenhum válido, retorna o primeiro (será criado depois)
    if candidates:
        result = candidates[0]
        print(f"[HISTORICO] ✓ Novo arquivo será criado em: {result}")
        return result
    
    # Fallback
    result = os.path.join(os.path.dirname(os.path.abspath(__file__)), machine_filename)
    print(f"[HISTORICO] ✓ Novo arquivo será criado em (fallback): {result}")
    return result

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB_FILE = os.path.join(BASE_DIR, 'database_vendas.json')
TOKEN_FILE = 'ml_tokens_autorizacao.json'

# ==========================================
# SESSION HTTP GLOBAL (evita esgotar portas/buffer no Windows)
# ------------------------------------------
# Antes, cada chamada SESSION.get()/SESSION.post() abria uma conexão TCP
# nova. Em Windows, com muitas chamadas em sequência (ou em threads paralelas),
# os sockets ficam presos em TIME_WAIT e a fila de portas/buffer do sistema
# enche, gerando o erro:
#   [WinError 10055] Uma operação em um soquete não pôde ser executada porque
#   o sistema não tinha espaço suficiente no buffer...
#
# Usando uma única Session com pooling de conexões (keep-alive), as conexões
# TCP são reaproveitadas em vez de recriadas a cada requisição, e o número de
# sockets simultâneos fica limitado por pool_maxsize. Também adicionamos
# retry automático para erros de conexão/instabilidade de rede.
# ==========================================
def _criar_session_http():
    session = requests.Session()
    retries = Retry(
        total=5,
        connect=5,
        read=3,
        backoff_factor=1,          # 1s, 2s, 4s, 8s, 16s entre tentativas
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET", "POST", "PUT", "DELETE", "PATCH"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(
        pool_connections=10,   # nº de hosts distintos mantidos em pool
        pool_maxsize=10,       # nº de conexões mantidas vivas por host
        max_retries=retries,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


SESSION = _criar_session_http()


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
            res = SESSION.post(url, data=payload, timeout=15)
            if res.status_code == 200:
                novos_tokens = res.json()
                self.salvar_tokens(novos_tokens, folder)
                return novos_tokens['access_token']
            return None
        except:
            return None

def _account_lock_path(folder):
    return os.path.join(folder, '.processing.lock')


def adquirir_lock_conta(folder, timeout=30, quem=""):
    """
    Tenta criar um lock exclusivo para a conta.
    Retorna True se conseguiu o lock, False se outra execução já está em andamento.
    timeout: segundos após os quais um lock "esquecido" (processo travou/crashou
    sem liberar) é considerado expirado e pode ser assumido por outro processo.
    """
    lock_path = _account_lock_path(folder)
    try:
        if os.path.exists(lock_path):
            idade = time.time() - os.path.getmtime(lock_path)
            if idade < timeout:
                return False
            print(f"[LOCK] Lock antigo ({idade:.0f}s) em {lock_path}, assumindo liberado.")

        with open(lock_path, 'w', encoding='utf-8') as f:
            f.write(f"pid={os.getpid()} | {quem} | {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        return True
    except Exception as e:
        print(f"[LOCK] Erro ao adquirir lock em {folder}: {e}")
        return False


def liberar_lock_conta(folder):
    lock_path = _account_lock_path(folder)
    try:
        if os.path.exists(lock_path):
            os.remove(lock_path)
    except Exception as e:
        print(f"[LOCK] Erro ao liberar lock em {folder}: {e}")


def ler_info_lock(folder):
    lock_path = _account_lock_path(folder)
    if not os.path.exists(lock_path):
        return None
    try:
        with open(lock_path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except Exception:
        return None


# ==========================================
# LOCK GLOBAL DE AGENDAMENTO
# Regra: um agendamento nunca pode rodar "por cima" de outro que já esteja
# em execução (seja disparado pelo Windows Task Scheduler em outro processo,
# seja por "Executar Agora" dentro do próprio app). Quando isso acontece, a
# nova execução ESPERA (fica em polling) até a anterior terminar, em vez de
# rodar em paralelo ou falhar.
# ==========================================

def _agendamento_lock_path():
    """Caminho do lock global de execução de agendamentos (um por vez)."""
    try:
        config_file = _encontrar_config_file()
        base_dir = os.path.dirname(config_file) if config_file else tempfile.gettempdir()
        if not base_dir:
            base_dir = tempfile.gettempdir()
    except Exception:
        base_dir = tempfile.gettempdir()
    return os.path.join(base_dir, '.agendamento_execucao.lock')


def _processo_vivo(pid):
    """Verifica se um processo com o PID informado ainda está rodando."""
    if not pid:
        return False
    try:
        if os.name == 'nt':
            saida = subprocess.run(
                ['tasklist', '/FI', f'PID eq {pid}'],
                capture_output=True, text=True, **_subprocess_no_window_kwargs()
            )
            return str(pid) in (saida.stdout or "")
        else:
            os.kill(pid, 0)
            return True
    except Exception:
        return False


def aguardar_e_adquirir_lock_agendamento(tarefa_id, nome_tarefa="", timeout_stale=1800, intervalo_poll=30, log_func=None):
    """
    Bloqueia até que nenhum outro agendamento esteja em execução e então adquire
    o lock global. Garante que agendamentos nunca rodem sobrepostos: se outro já
    estiver em andamento, esta chamada ESPERA ele terminar (ou o lock ser
    considerado travado/expirado após `timeout_stale` segundos) antes de seguir.

    log_func, se informado, deve ser algo como app.logger(mensagem, nivel).
    """
    lock_path = _agendamento_lock_path()
    avisado = False

    while True:
        try:
            # Tenta criar o arquivo de lock de forma exclusiva (atômico entre processos)
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(
                    f"pid={os.getpid()} | tarefa={tarefa_id} | {nome_tarefa} | "
                    f"{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
                )
            if avisado:
                msg = f"Lock de agendamento liberado. '{nome_tarefa or tarefa_id}' segue agora."
                _registrar_log_agendamento(msg)
                if log_func:
                    try:
                        log_func(msg, "INFO")
                    except Exception:
                        pass
            return
        except FileExistsError:
            # Já existe outro agendamento rodando (ou um lock travado/esquecido)
            info = ""
            pid_lock = None
            idade = 0
            try:
                with open(lock_path, 'r', encoding='utf-8') as f:
                    info = f.read().strip()
                m = re.search(r'pid=(\d+)', info)
                if m:
                    pid_lock = int(m.group(1))
                idade = time.time() - os.path.getmtime(lock_path)
            except Exception:
                pass

            lock_travado = idade >= timeout_stale or (pid_lock is not None and not _processo_vivo(pid_lock))
            if lock_travado:
                _registrar_log_agendamento(
                    f"Lock de agendamento travado/expirado ({idade:.0f}s) removido: {info}"
                )
                try:
                    os.remove(lock_path)
                except Exception:
                    pass
                continue  # tenta adquirir de novo no próximo loop

            if not avisado:
                msg = (
                    f"Já existe um agendamento em execução ({info}). "
                    f"'{nome_tarefa or tarefa_id}' vai AGUARDAR terminar antes de rodar."
                )
                _registrar_log_agendamento(msg)
                if log_func:
                    try:
                        log_func(msg, "INFO")
                    except Exception:
                        pass
                avisado = True
            time.sleep(intervalo_poll)
        except Exception as e:
            _registrar_log_agendamento(f"[LOCK-AGENDAMENTO] Erro ao adquirir lock: {e}")
            time.sleep(intervalo_poll)


def liberar_lock_agendamento():
    """Libera o lock global de agendamento, permitindo a próxima execução seguir."""
    lock_path = _agendamento_lock_path()
    try:
        if os.path.exists(lock_path):
            os.remove(lock_path)
    except Exception as e:
        _registrar_log_agendamento(f"[LOCK-AGENDAMENTO] Erro ao liberar lock: {e}")


def _subprocess_no_window_kwargs():
    """Kwargs extras para rodar subprocess sem abrir/piscar janela de console (cmd) no Windows."""
    kwargs = {}
    if os.name == 'nt':
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            kwargs['startupinfo'] = startupinfo
        except Exception:
            pass
    return kwargs


class GerenciadorTaskScheduler:
    """Gerencia agendamentos usando Windows Task Scheduler"""
    
    def __init__(self):
        machine_key = _get_machine_key()
        self.task_prefix = f"AppColetorPro_{machine_key}_"
        if getattr(sys, 'frozen', False):
            self.script_dir = os.path.dirname(sys.executable)
        else:
            self.script_dir = os.path.dirname(os.path.abspath(__file__))
    
    def _sanitize_task_name(self, tarefa_id):
        return re.sub(r'[^A-Za-z0-9_-]', '_', tarefa_id)

    def _task_name_base(self, tarefa_id):
        return f"{self.task_prefix}{self._sanitize_task_name(tarefa_id)}"

    def _listar_tarefas_app(self):
        """Lista tarefas do Windows Task Scheduler criadas pelo app."""
        result = subprocess.run(
            ['schtasks', '/query', '/fo', 'csv', '/nh'],
            capture_output=True,
            text=True,
            **_subprocess_no_window_kwargs()
        )
        if result.returncode != 0:
            print(f"[TASK SCHEDULER] Falha ao listar tarefas: {result.stderr or result.stdout}")
            return []

        tarefas = []
        for row in csv.reader(result.stdout.splitlines()):
            if not row:
                continue
            task_path = row[0].strip()
            task_name = task_path.rsplit('\\', 1)[-1]
            if task_name.startswith(self.task_prefix):
                tarefas.append(task_path)
        return tarefas

    def _is_admin(self):
        try:
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False

    def _get_task_principal(self):
        if self._is_admin():
            return "SYSTEM", "ServiceAccount"

        username = os.getenv("USERNAME", "SYSTEM")
        userdomain = os.getenv("USERDOMAIN")
        if userdomain:
            return f"{userdomain}\\{username}", "InteractiveToken"
        return username, "InteractiveToken"

    def _build_task_xml(self, task_name, command, arguments, schedule_type, start_datetime,
                     principal_user, logon_type, run_level, repeat_minutes=0):
        author = escape(principal_user)
        command_text = escape(command)
        arguments_text = escape(arguments)
        start_boundary = start_datetime.strftime('%Y-%m-%dT%H:%M:%S')

        settings = (
            "    <Settings>\n"
            "      <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n"
            "      <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n"
            "      <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n"
            "      <AllowHardTerminate>true</AllowHardTerminate>\n"
            "      <StartWhenAvailable>true</StartWhenAvailable>\n"
            "      <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>\n"
            "      <WakeToRun>true</WakeToRun>\n"
            "      <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>\n"
            "      <Priority>7</Priority>\n"
            "    </Settings>\n"
        )

        repetition_xml = ""
        if repeat_minutes and int(repeat_minutes) > 0:
            repetition_xml = (
                "        <Repetition>\n"
                f"          <Interval>PT{int(repeat_minutes)}M</Interval>\n"
                "          <Duration>P1D</Duration>\n"
                "          <StopAtDurationEnd>false</StopAtDurationEnd>\n"
                "        </Repetition>\n"
            )

        trigger = (
            "    <Triggers>\n"
            "      <CalendarTrigger>\n"
            f"        <StartBoundary>{start_boundary}</StartBoundary>\n"
            "        <Enabled>true</Enabled>\n"
            f"{repetition_xml}"
        )
        if schedule_type == 'DAILY':
            trigger += (
                "        <ScheduleByDay>\n"
                "          <DaysInterval>1</DaysInterval>\n"
                "        </ScheduleByDay>\n"
            )
        trigger += (
            "      </CalendarTrigger>\n"
            "    </Triggers>\n"
        )

        run_level_text = f"      <RunLevel>{run_level}</RunLevel>\n" if run_level else ""

        principal = (
            "  <Principals>\n"
            "    <Principal id=\"Author\">\n"
            f"      <UserId>{author}</UserId>\n"
            f"      <LogonType>{logon_type}</LogonType>\n"
            f"{run_level_text}"
            "    </Principal>\n"
            "  </Principals>\n"
        )

        actions = (
            "  <Actions Context=\"Author\">\n"
            "    <Exec>\n"
            f"      <Command>{command_text}</Command>\n"
            f"      <Arguments>{arguments_text}</Arguments>\n"
            "    </Exec>\n"
            "  </Actions>\n"
        )

        xml_content = (
            '<?xml version="1.0" encoding="UTF-16"?>\n'
            '<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
            '  <RegistrationInfo>\n'
            f'    <Author>{author}</Author>\n'
            f'    <Date>{datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")}</Date>\n'
            '  </RegistrationInfo>\n'
            f'{principal}'
            f'{settings}'
            f'{trigger}'
            f'{actions}'
            '</Task>\n'
        )
        return xml_content

    def _create_task_from_xml(self, task_name, command, arguments, schedule_type, start_datetime,
                           principal_user, logon_type, run_level, repeat_minutes=0):
        xml_content = self._build_task_xml(task_name, command, arguments, schedule_type, start_datetime,
                                        principal_user, logon_type, run_level, repeat_minutes)
      
        with tempfile.NamedTemporaryFile('w', delete=False, suffix='.xml', encoding='utf-16') as tmp_file:
            tmp_file.write(xml_content)
            xml_path = tmp_file.name

        try:
            result = subprocess.run(
                ['schtasks', '/Create', '/TN', task_name, '/XML', xml_path, '/F'],
                capture_output=True,
                text=True,
                **_subprocess_no_window_kwargs()
            )
        finally:
            try:
                os.remove(xml_path)
            except Exception:
                pass

        return result

    def criar_tarefa(self, tarefa_id, nome_tarefa, horarios, config_dados):
        """
        Cria tarefas no Windows Task Scheduler para cada horário
        horarios: lista de strings no formato "HH:MM", ex: ["08:00", "14:00", "20:00"]
        """
        self.deletar_tarefa(tarefa_id)

        try:
            import subprocess

            python_exe = sys.executable
            machine_key = _get_machine_key()
            if getattr(sys, 'frozen', False):
                cmd = python_exe
                arguments = f'--agendamento "{tarefa_id}" --machine "{machine_key}"'
            else:
                cmd = python_exe
                main_script = os.path.join(self.script_dir, "main.py")
                arguments = f'"{main_script}" --agendamento "{tarefa_id}" --machine "{machine_key}"'

            task_command = f'"{cmd}" {arguments}'
            if config_dados.get('tipo') == 'unica':
                horarios = [config_dados.get('horarios', [config_dados.get('hora', '08:00')])[0]]

            for idx, horario in enumerate(horarios):
                task_name = f"{self._task_name_base(tarefa_id)}_{idx}"
                schedule_type = 'ONCE' if config_dados.get('tipo') == 'unica' else 'DAILY'
                start_date = config_dados.get('data') or datetime.now().strftime('%d/%m/%Y')
                start_datetime = datetime.strptime(f"{start_date} {horario}", '%d/%m/%Y %H:%M')

                principal_user, logon_type = self._get_task_principal()
                run_level = 'Highest' if self._is_admin() else None

                result = self._create_task_from_xml(
                    task_name,
                    cmd,
                    arguments,
                    schedule_type,
                    start_datetime,
                    principal_user,
                    logon_type,
                    run_level,
                    repeat_minutes=config_dados.get('intervalo_minutos', 0)   # NOVO
                )

                if result.returncode != 0:
                    print(f"[ERRO] Falha ao criar tarefa '{task_name}' no Task Scheduler")
                    print(f"STDOUT: {result.stdout}")
                    print(f"STDERR: {result.stderr}")
                    return False

                print(f"[TASK SCHEDULER] ✓ Tarefa '{task_name}' criada para {horario}")
                print(f"[TASK SCHEDULER] ✓ WakeToRun habilitado para '{task_name}'")

            return True
        except Exception as e:
            print(f"[ERRO] Falha ao criar tarefa no Task Scheduler: {e}")
            return False
    
    def deletar_tarefa(self, tarefa_id):
        """Deleta todas as tarefas associadas a um agendamento"""
        try:
            task_base = self._task_name_base(tarefa_id)
            removidas = 0
            for task_path in self._listar_tarefas_app():
                task_name = task_path.rsplit('\\', 1)[-1]
                if task_name.startswith(f"{task_base}_"):
                    result = subprocess.run(
                        ['schtasks', '/delete', '/tn', task_path, '/f'],
                        capture_output=True,
                        text=True,
                        **_subprocess_no_window_kwargs()
                    )
                    if result.returncode == 0:
                        removidas += 1
                        print(f"[TASK SCHEDULER] ✓ Tarefa '{task_path}' deletada")
                    else:
                        print(f"[TASK SCHEDULER] Falha ao deletar '{task_path}': {result.stderr or result.stdout}")
            if removidas == 0:
                print(f"[TASK SCHEDULER] Nenhuma tarefa encontrada para '{task_base}'")
            return True
        except Exception as e:
            print(f"[ERRO] Falha ao deletar tarefa do Task Scheduler: {e}")
            return False
    
    def ativar_desativar_tarefa(self, tarefa_id, ativar=True):
        """Ativa ou desativa tarefas"""
        try:
            acao = '/enable' if ativar else '/disable'
            task_base = self._task_name_base(tarefa_id)
            alteradas = 0
            for task_path in self._listar_tarefas_app():
                task_name = task_path.rsplit('\\', 1)[-1]
                if task_name.startswith(f"{task_base}_"):
                    result = subprocess.run(
                        ['schtasks', acao, '/tn', task_path],
                        capture_output=True,
                        text=True,
                        **_subprocess_no_window_kwargs()
                    )
                    if result.returncode == 0:
                        alteradas += 1
                    else:
                        print(f"[TASK SCHEDULER] Falha ao alterar '{task_path}': {result.stderr or result.stdout}")
            if alteradas == 0:
                print(f"[TASK SCHEDULER] Nenhuma tarefa encontrada para '{task_base}'")
            return True
        except Exception as e:
            print(f"[ERRO] Falha ao modificar tarefa do Task Scheduler: {e}")
            return False

class GerenciadorAgendamentos:
    """Gerencia agendamentos de tarefas com persistência em JSON e Windows Task Scheduler"""
    
    def __init__(self):
        self.config_file = _encontrar_config_file()
        self.historico_file = _encontrar_historico_file(self.config_file)
        self.scheduler = BackgroundScheduler()
        self.task_scheduler = GerenciadorTaskScheduler()  # NEW: Windows Task Scheduler
        
        # Log de inicialização
        print(f"\n{'='*70}")
        print(f"[INICIALIZAÇÃO] GerenciadorAgendamentos")
        print(f"  Config file: {self.config_file}")
        print(f"  Histórico file: {self.historico_file}")
        print(f"{'='*70}\n")
        
    def carregar_agendamentos(self):
        """Carrega agendamentos do arquivo JSON"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    conteudo = f.read()
                if not conteudo.strip():
                    return {}
                return json.loads(conteudo)
            except json.decoder.JSONDecodeError as jde:
                print(f"[ERRO] Arquivo de configuração JSON inválido: {self.config_file}: {jde}")
                try:
                    ts = datetime.now().strftime('%Y%m%d-%H%M%S')
                    corrupt_backup = f"{self.config_file}.corrupt-{ts}.bak"
                    os.rename(self.config_file, corrupt_backup)
                    print(f"[INFO] Arquivo corrompido movido para: {corrupt_backup}")
                except Exception as e:
                    print(f"[WARN] Falha ao mover arquivo corrompido: {e}")
                try:
                    with open(self.config_file, 'w', encoding='utf-8') as f:
                        json.dump({}, f, indent=4, ensure_ascii=False)
                    print(f"[INFO] Novo arquivo de configuração criado: {self.config_file}")
                except Exception as e:
                    print(f"[ERRO] Não foi possível criar novo arquivo de configuração: {e}")
                try:
                    import tkinter.messagebox as msg
                    msg.showerror("Arquivo de configuração inválido", f"O arquivo de configuração estava corrompido e foi renomeado. Um novo arquivo vazio foi criado:\n{self.config_file}\n\nVerifique o backup para análise.")
                except Exception:
                    pass
                return {}
            except Exception as e:
                print(f"[ERRO] Falha ao ler agendamentos em {self.config_file}: {e}")
                return {}
        return {}
    
    def salvar_agendamentos(self, dados):
        """Salva agendamentos no arquivo JSON (garante diretório e trata erros)"""
        try:
            config_dir = os.path.dirname(self.config_file)
            if config_dir and not os.path.exists(config_dir):
                os.makedirs(config_dir, exist_ok=True)
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(dados, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"[ERRO] Falha ao salvar agendamentos em {self.config_file}: {e}")
            try:
                import tkinter.messagebox as msg
                msg.showerror("Erro ao salvar agendamentos", f"Não foi possível salvar agendamentos em:\n{self.config_file}\n\n{e}")
            except Exception:
                pass
            return False
    
    def salvar_e_registrar_agendamento(self, tarefa_id, config):
        """Salva agendamento no JSON e registra no Windows Task Scheduler"""
        # Salvar no JSON
        agendamentos = self.carregar_agendamentos()
        agendamentos[tarefa_id] = config
        self.salvar_agendamentos(agendamentos)

        # Atualiza o Task Scheduler
        if config.get('ativo') and config.get('tipo') in ['diaria', 'unica']:
            horarios = config.get('horarios', [config.get('hora', '08:00')])
            return self.task_scheduler.criar_tarefa(tarefa_id, config.get('nome'), horarios, config)

        # Desativa tarefas existentes se o agendamento não estiver ativo
        self.task_scheduler.deletar_tarefa(tarefa_id)
        return True
    
    def deletar_agendamento(self, tarefa_id):
        """Deleta agendamento do JSON e do Windows Task Scheduler"""
        # Deletar do JSON
        agendamentos = self.carregar_agendamentos()
        if tarefa_id in agendamentos:
            del agendamentos[tarefa_id]
            self.salvar_agendamentos(agendamentos)
        
        # Deletar do Windows Task Scheduler
        self.task_scheduler.deletar_tarefa(tarefa_id)
        
        return True
    
    def ativar_desativar_agendamento(self, tarefa_id, ativar=True):
        """Ativa/desativa agendamento no JSON e no Windows Task Scheduler"""
        agendamentos = self.carregar_agendamentos()
        if tarefa_id in agendamentos:
            agendamentos[tarefa_id]['ativo'] = ativar
            self.salvar_agendamentos(agendamentos)
            self.task_scheduler.ativar_desativar_tarefa(tarefa_id, ativar)
        
        return True
    
    def carregar_historico(self):
        """Carrega histórico de execuções"""
        if os.path.exists(self.historico_file):
            try:
                with open(self.historico_file, 'r', encoding='utf-8') as f:
                    conteudo = f.read()
                if not conteudo.strip():
                    return []
                return json.loads(conteudo)
            except Exception as e:
                print(f"[ERRO] Falha ao ler histórico em {self.historico_file}: {e}")
                return []
        return []
    
    def salvar_historico(self, dados):
        """Salva histórico de execuções (garante diretório e trata erros)"""
        try:
            hist_dir = os.path.dirname(self.historico_file)
            if hist_dir and not os.path.exists(hist_dir):
                os.makedirs(hist_dir, exist_ok=True)
            with open(self.historico_file, 'w', encoding='utf-8') as f:
                json.dump(dados, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"[ERRO] Falha ao salvar histórico em {self.historico_file}: {e}")
            return False
    
    def adicionar_historico(self, tarefa_id, tarefa_nome, acao, status, mensagem=""):
        """Adiciona um novo registro ao histórico"""
        historico = self.carregar_historico()
        novo_registro = {
            "id": len(historico) + 1,
            "tarefa_id": tarefa_id,
            "tarefa_nome": tarefa_nome,
            "acao": acao,
            "status": status,
            "mensagem": mensagem,
            "data_hora": datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        }
        historico.append(novo_registro)
        # Manter apenas últimos 100 registros
        if len(historico) > 100:
            historico = historico[-100:]
        if not self.salvar_historico(historico):
            _registrar_log_agendamento(f"ERRO ao salvar histórico em {self.historico_file}")
        else:
            _registrar_log_agendamento(f"Histórico atualizado em {self.historico_file}: tarefa={tarefa_id}, status={status}")
        return novo_registro
    
    def iniciar_scheduler(self, app_instance):
        """Inicializa o Windows Task Scheduler com agendamentos do JSON"""
        agendamentos = self.carregar_agendamentos()
        
        if not agendamentos:
            print("[INFO] Nenhum agendamento encontrado")
            return
        
        total_ativos = 0
        for tarefa_id, config in agendamentos.items():
            if not config.get('ativo'):
                print(f"[SKIP] Tarefa '{config.get('nome')}' desativada")
                continue

            if config.get('tipo') == 'diaria':
                horarios = config.get('horarios', [config.get('hora', '08:00')])
                if self.task_scheduler.criar_tarefa(tarefa_id, config.get('nome'), horarios, config):
                    total_ativos += 1
                    print(f"[SCHEDULER] ✓ Tarefa '{config.get('nome')}' registrada para {', '.join(horarios)}")
            elif config.get('tipo') == 'unica':
                horarios = [config.get('horarios', [config.get('hora', '08:00')])[0]]
                if self.task_scheduler.criar_tarefa(tarefa_id, config.get('nome'), horarios, config):
                    total_ativos += 1
                    print(f"[SCHEDULER] ✓ Tarefa única '{config.get('nome')}' registrada para {config.get('data')} {horarios[0]}")

        if total_ativos > 0:
            print(f"[SCHEDULER] ✓ {total_ativos} tarefa(s) registrada(s) no Windows Task Scheduler")
        else:
            print("[INFO] Nenhuma tarefa ativa para registrar")
    
    def parar_scheduler(self):
        """Para o scheduler (para compatibilidade)"""
        if self.scheduler.running:
            print("[SCHEDULER] Parando APScheduler...")
            self.scheduler.shutdown(wait=False)
            print("[SCHEDULER] ✓ APScheduler parado")
    
    def reiniciar_scheduler(self, app_instance):
        """Reinicia o scheduler"""
        print("[SCHEDULER] Reiniciando scheduler...")
        self.iniciar_scheduler(app_instance)
        print("[SCHEDULER] ✓ Scheduler reiniciado")
    
    def _executar_tarefa(self, app_instance, tarefa_id, config):
        """Executa uma tarefa agendada - usa root.after para thread safety"""
        try:
            acao = config.get('acao')
            email = config.get('email', '')
            nome_tarefa = config.get('nome')
            
            # Log de início
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] [AGENDAMENTO] Iniciando tarefa: {nome_tarefa} ({acao}) para {email}")
            
            # Usa root.after para executar na thread principal do Tkinter
            def executar_na_thread_principal():
                try:
                    app_instance.var_email.set(email)
                    app_instance.iniciar_thread_processamento(acao=acao)
                    
                    self.adicionar_historico(
                        tarefa_id,
                        nome_tarefa,
                        acao,
                        'SUCESSO',
                        f'Executado automaticamente às {timestamp}'
                    )
                except Exception as e_inner:
                    print(f"[ERRO] Falha ao executar tarefa {tarefa_id}: {e_inner}")
                    self.adicionar_historico(
                        tarefa_id,
                        nome_tarefa,
                        acao,
                        'ERRO',
                        str(e_inner)
                    )
            
            # Agenda a execução para a thread principal
            app_instance.root.after(0, executar_na_thread_principal)
            
        except Exception as e:
            print(f"[ERRO] Erro ao agendar execução da tarefa {tarefa_id}: {e}")
            self.adicionar_historico(
                tarefa_id,
                config.get('nome'),
                config.get('acao'),
                'ERRO',
                f"Falha no agendamento: {str(e)}"
            )


class JanelaAgendamentos:
    """Janela para gerenciar agendamentos"""
    
    def __init__(self, parent, gerenciador, app_instance):
        self.gerenciador = gerenciador
        self.app_instance = app_instance
        self.parent = parent
        
        self.janela = tk.Toplevel(parent)
        self.janela.title("Painel de Agendamentos")
        self.janela.geometry("1000x600")
        
        self.acoes_disponiveis = [
            "boleto",
            "rastreio",
            "erro_boleto",
            "autorizar_boleto",
            "nao_autorizados",
            "cobrar_dobrado",
            "agradecimento",
            "solicitar",
            "reclamacao",
            "cobrar_nao_pagos",
            "responder_duvidas_ml",
            "ia"
        ]
        
        self.setup_ui()
        self.atualizar_tabelas()
    
    def setup_ui(self):
        """Cria a interface com abas"""
        # --- Header ---
        header = tk.Frame(self.janela, bg="#FF6600", height=50)
        header.pack(fill=tk.X)
        tk.Label(header, text="⏰ GERENCIADOR DE AGENDAMENTOS", fg="white", bg="#FF6600", font=("Arial", 12, "bold")).pack(pady=10)
        
        # --- Notebook com abas ---
        self.notebook = ttk.Notebook(self.janela)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Aba 1: Agendamentos Futuros
        self.aba_agendamentos = tk.Frame(self.notebook)
        self.notebook.add(self.aba_agendamentos, text="📋 Agendamentos Futuros")
        self._setup_aba_agendamentos()
        
        # Aba 2: Histórico de Execução
        self.aba_historico = tk.Frame(self.notebook)
        self.notebook.add(self.aba_historico, text="📊 Histórico de Execução")
        self._setup_aba_historico()
    
    def _setup_aba_agendamentos(self):
        """Setup da aba de agendamentos futuros"""
        # --- Botões de Ação ---
        btn_frame = tk.Frame(self.aba_agendamentos)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)
        
        tk.Button(btn_frame, text="+ Novo Agendamento", command=self._nova_tarefa, bg="#28a745", fg="white", font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="✏️ Editar", command=self._editar_tarefa, bg="#ffc107", fg="black", font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="🗑️ Deletar", command=self._deletar_tarefa, bg="#dc3545", fg="white", font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="🔁 Ativar/Desativar", command=self._toggle_tarefa, bg="#6c757d", fg="white", font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="▶️ Executar", command=self._executar_agendamento_agora, bg="#FF6600", fg="white", font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="🔄 Atualizar", command=self.atualizar_tabelas, bg="#17a2b8", fg="white", font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=5)
        
        self.status_label = tk.Label(self.aba_agendamentos, text="", fg="#333", font=("Arial", 9), anchor="w")
        self.status_label.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        # --- Tabela de Agendamentos ---
        self._criar_treeview(self.aba_agendamentos, ['tarefa_id', 'nome', 'tipo', 'acao', 'hora', 'data', 'ativo', 'email'])
    
    def _setup_aba_historico(self):
        """Setup da aba de histórico"""
        # --- Botão de Atualizar ---
        btn_frame = tk.Frame(self.aba_historico)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)
        
        tk.Button(btn_frame, text="🔄 Atualizar", command=self.atualizar_tabelas, bg="#17a2b8", fg="white", font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="🗑️ Limpar Histórico", command=self._limpar_historico, bg="#dc3545", fg="white", font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=5)
        
        # --- Tabela de Histórico ---
        self._criar_treeview_historico(self.aba_historico, ['id', 'tarefa_nome', 'acao', 'status', 'data_hora', 'mensagem'])
    
    def _criar_treeview(self, parent, colunas):
        """Cria uma treeview para agendamentos"""
        # Frame para a tabela e scrollbar
        frame = tk.Frame(parent)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Scrollbar vertical
        scrollbar = ttk.Scrollbar(frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # TreeView
        self.tree_agendamentos = ttk.Treeview(
            frame,
            columns=colunas,
            height=15,
            yscrollcommand=scrollbar.set
        )
        scrollbar.config(command=self.tree_agendamentos.yview)
        
        # Definir cabeçalhos
        self.tree_agendamentos.heading('#0', text='ID')
        self.tree_agendamentos.column('#0', width=50)
        
        headers = {
            'tarefa_id': 'ID Tarefa',
            'nome': 'Nome',
            'tipo': 'Tipo',
            'acao': 'Ação',
            'hora': 'Hora',
            'data': 'Data',
            'ativo': 'Ativo',
            'email': 'Email da Conta'
        }
        
        for col in colunas:
            self.tree_agendamentos.heading(col, text=headers.get(col, col))
            if col == 'email':
                width = 200
            elif col == 'nome':
                width = 150
            elif col == 'data':
                width = 100
            elif col == 'tipo':
                width = 80
            else:
                width = 80
            self.tree_agendamentos.column(col, width=width)
        
        self.tree_agendamentos.pack(fill=tk.BOTH, expand=True)
    
    def _criar_treeview_historico(self, parent, colunas):
        """Cria uma treeview para histórico"""
        frame = tk.Frame(parent)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        scrollbar = ttk.Scrollbar(frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.tree_historico = ttk.Treeview(
            frame,
            columns=colunas,
            height=15,
            yscrollcommand=scrollbar.set
        )
        scrollbar.config(command=self.tree_historico.yview)
        
        self.tree_historico.heading('#0', text='ID')
        self.tree_historico.column('#0', width=50)
        
        headers = {
            'id': 'ID',
            'tarefa_nome': 'Tarefa',
            'acao': 'Ação',
            'status': 'Status',
            'data_hora': 'Data/Hora',
            'mensagem': 'Mensagem'
        }
        
        for col in colunas:
            self.tree_historico.heading(col, text=headers.get(col, col))
            if col == 'mensagem':
                width = 250
            elif col in ['data_hora', 'tarefa_nome']:
                width = 150
            else:
                width = 80
            self.tree_historico.column(col, width=width)
        
        self.tree_historico.pack(fill=tk.BOTH, expand=True)
    
    def atualizar_tabelas(self):
        """Atualiza as tabelas com dados atuais"""
        # Limpar treeviews
        for item in self.tree_agendamentos.get_children():
            self.tree_agendamentos.delete(item)
        
        for item in self.tree_historico.get_children():
            self.tree_historico.delete(item)
        
        # Carregar agendamentos
        agendamentos = self.gerenciador.carregar_agendamentos()
        action_labels = {
            "solicitar": "PRIMEIRA MSG E WPP",
            "rastreio": "ENVIAR RASTREIO",
            "boleto": "ENVIAR BOLETO",
            "erro_boleto": "ERRO NO BOLETO",
            "reenviar_boleto": "REENVIAR BOLETO",
            "cobrar_dobrado": "COBRAR DOBRADO",
            "agradecimento": "AGRADECIMENTO",
            "atualizar_pagos": "ATUALIZAR PAGOS",
            "atualizar_pagos_reembolsar": "ATUALIZAR PAGOS + REEMBOLSAR",  # NOVO
            "reclamacao": "EXECUTAR RECLAMAÇÃO",
            "cobrar_nao_pagos": "NÃO PAGOS",
            "nao_pagos": "NÃO PAGOS",
            "vendas_encerradas": "VENDAS ENCERRADAS",
        }
        for i, (tarefa_id, config) in enumerate(agendamentos.items()):
            acao_key = config.get('acao', 'N/A')
            acao_label = action_labels.get(acao_key, acao_key)
            
            # Exibir múltiplos horários ou apenas um (para compatibilidade)
            horarios = config.get('horarios', [config.get('hora', 'N/A')])
            horarios_str = ', '.join(horarios) if horarios else 'N/A'
            
            self.tree_agendamentos.insert(
                '',
                'end',
                iid=tarefa_id,
                values=(
                    tarefa_id,
                    config.get('nome', 'N/A'),
                    config.get('tipo', 'diaria'),
                    acao_label,
                    horarios_str,
                    config.get('data', 'N/A') if config.get('tipo') == 'unica' else '-',
                    '✅' if config.get('ativo') else '❌',
                    config.get('email', 'N/A')
                )
            )
        
        # Carregar histórico
        historico = self.gerenciador.carregar_historico()
        for registro in historico[-20:]:  # Mostrar últimos 20
            self.tree_historico.insert(
                '',
                'end',
                values=(
                    registro.get('id'),
                    registro.get('tarefa_nome', 'N/A'),
                    registro.get('acao', 'N/A'),
                    registro.get('status', 'N/A'),
                    registro.get('data_hora', 'N/A'),
                    registro.get('mensagem', 'N/A')
                )
            )
    
    def _nova_tarefa(self):
        """Cria uma nova tarefa"""
        dialog = JanelaNovaAgendamento(self.janela, self.gerenciador, self.app_instance, self.atualizar_tabelas)
    
    def _editar_tarefa(self):
        """Edita a tarefa selecionada"""
        selecionada = self.tree_agendamentos.selection()
        if not selecionada:
            messagebox.showwarning("Aviso", "Selecione um agendamento para editar")
            return
        
        tarefa_id = selecionada[0]
        agendamentos = self.gerenciador.carregar_agendamentos()
        
        if tarefa_id in agendamentos:
            dialog = JanelaNovaAgendamento(
                self.janela, 
                self.gerenciador, 
                self.app_instance, 
                self.atualizar_tabelas,
                tarefa_id=tarefa_id,
                config_existente=agendamentos[tarefa_id]
            )
    
    def _set_status(self, texto):
        if hasattr(self, 'status_label') and self.status_label:
            self.status_label.config(text=texto)
            self.janela.update_idletasks()

    def _set_busy(self, busy=True):
        cursor = 'watch' if busy else ''
        self.janela.config(cursor=cursor)
        for child in self.janela.winfo_children():
            try:
                child.configure(state=tk.DISABLED if busy else tk.NORMAL)
            except Exception:
                pass
        self.janela.update_idletasks()

    def _deletar_tarefa(self):
        """Deleta a tarefa selecionada (tanto do JSON quanto do Windows Task Scheduler)"""
        selecionada = self.tree_agendamentos.selection()
        if not selecionada:
            messagebox.showwarning("Aviso", "Selecione um agendamento para deletar", parent=self.janela)
            return
        
        if messagebox.askyesno(
            "Confirmar",
            "Tem certeza que deseja deletar este agendamento?\n\nIsso removerá também do Windows Task Scheduler.",
            parent=self.janela
        ):
            tarefa_id = selecionada[0]
            self._set_status("Excluindo agendamento... aguarde")
            self._set_busy(True)
            try:
                self.gerenciador.deletar_agendamento(tarefa_id)
                self.atualizar_tabelas()
                self._set_status("Agendamento excluído com sucesso!")
                self.janela.lift()
                self.janela.focus_force()
                messagebox.showinfo("Sucesso", "Agendamento deletado com sucesso!", parent=self.janela)
            finally:
                self._set_busy(False)
                self.janela.lift()
                self.janela.focus_force()
    
    def _toggle_tarefa(self):
        """Ativa ou desativa a tarefa selecionada"""
        selecionada = self.tree_agendamentos.selection()
        if not selecionada:
            messagebox.showwarning("Aviso", "Selecione um agendamento para ativar/desativar")
            return
        
        tarefa_id = selecionada[0]
        agendamentos = self.gerenciador.carregar_agendamentos()
        
        if tarefa_id in agendamentos:
            ativo_atual = agendamentos[tarefa_id].get('ativo', False)
            novo_estado = not ativo_atual
            
            self.gerenciador.ativar_desativar_agendamento(tarefa_id, novo_estado)
            self.atualizar_tabelas()
            
            estado_str = "ativado" if novo_estado else "desativado"
            messagebox.showinfo("Sucesso", f"Agendamento {estado_str} com sucesso!")
    
    def _executar_agendamento_agora(self):
        """Executa o agendamento selecionado imediatamente"""
        selecionada = self.tree_agendamentos.selection()
        if not selecionada:
            messagebox.showwarning("Aviso", "Selecione um agendamento para executar")
            return
        
        tarefa_id = selecionada[0]
        agendamentos = self.gerenciador.carregar_agendamentos()
        
        if tarefa_id not in agendamentos:
            messagebox.showerror("Erro", "Agendamento não encontrado")
            return
        
        config = agendamentos[tarefa_id]
        if not config.get('ativo', False):
            messagebox.showwarning("Aviso", "Este agendamento está desativado. Deseja ativar e executar?")
            if not messagebox.askyesno("Confirmar", "Ativar e executar este agendamento?"):
                return
            self.gerenciador.ativar_desativar_agendamento(tarefa_id, True)
            config['ativo'] = True
        
        try:
            # Executar em thread para não congelar a interface
            thread = threading.Thread(
                target=self._executar_agendamento_thread,
                args=(tarefa_id, config),
                daemon=True
            )
            thread.start()
            messagebox.showinfo("Sucesso", "Agendamento iniciado em segundo plano!")
            self.atualizar_tabelas()
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao executar agendamento: {e}")
    
    def _executar_agendamento_thread(self, tarefa_id, config):
        """Executa o agendamento em uma thread separada"""
        lock_adquirido = False
        try:
            # Regra do agendamento: nunca rodar por cima de outro já em execução
            # (aqui dentro do app ou em outro processo disparado pelo Windows
            # Task Scheduler). Se já tiver um rodando, espera terminar antes de seguir.
            _registrar_log_agendamento(f"Verificando lock de agendamento para execução manual {tarefa_id}...")
            aguardar_e_adquirir_lock_agendamento(tarefa_id, config.get('nome', ''))
            lock_adquirido = True

            root = tk.Tk()
            root.withdraw()
            app = AppColetorPro(root, start_scheduler=False)
            app.var_email.set(config.get('email', '').strip())
            app.var_prazo.set(config.get('prazo_entrega', '').strip())
            app.var_data_entrega.set(config.get('data_entrega', '').strip())
            app.var_pag_inicial.set(config.get('offset', '0'))
            app.var_ordem_ids.set(config.get('ordem_ids', '').strip())
            
            acao = 'solicitar' if config.get('acao') == 'reclamacao' else config.get('acao', 'solicitar')
            
            app.logger(f"[AGENDAMENTO] Iniciando execução manual de {tarefa_id} para {config.get('email')} com ação {config.get('acao')}", "INFO")
            app.iniciar_thread_processamento(acao=acao, usar_thread=False)
            app.agendamentos.adicionar_historico(
                tarefa_id,
                config.get('nome'),
                config.get('acao'),
                'SUCESSO',
                f"Executado manualmente às {datetime.now().strftime('%H:%M:%S')}"
            )
            app.logger(f"[AGENDAMENTO] Execução finalizada com sucesso!", "SUCESSO")
        except Exception as e:
            self.gerenciador.adicionar_historico(
                tarefa_id,
                config.get('nome'),
                config.get('acao'),
                'ERRO',
                str(e)
            )
        finally:
            if lock_adquirido:
                liberar_lock_agendamento()
    
    def _limpar_historico(self):
        """Limpa o histórico"""
        if messagebox.askyesno("Confirmar", "Tem certeza que deseja limpar todo o histórico?"):
            self.gerenciador.salvar_historico([])
            self.atualizar_tabelas()
            messagebox.showinfo("Sucesso", "Histórico limpo com sucesso!")


class JanelaNovaAgendamento:
    """Janela para criar/editar agendamento com suporte a múltiplos horários"""
    
    def __init__(self, parent, gerenciador, app_instance, callback_atualizar, tarefa_id=None, config_existente=None):
        self.gerenciador = gerenciador
        self.app_instance = app_instance
        self.callback_atualizar = callback_atualizar
        self.tarefa_id = tarefa_id or f"tarefa_{datetime.now().timestamp()}"
        self.config_existente = config_existente or {}
        
        self.acao_labels = {
            "solicitar": "PRIMEIRA MSG E WPP",
            "rastreio": "ENVIAR RASTREIO",
            "boleto": "ENVIAR BOLETO",
            "erro_boleto": "ERRO NO BOLETO",
            "autorizar_boleto": "TAXAR E AUTORIZAR BLT",
            "nao_autorizados": "NAO AUTORIZADOS",
            "cobrar_dobrado": "COBRAR DOBRADO",
            "agradecimento": "AGRADECIMENTO",
            "atualizar_pagos": "ATUALIZAR PAGOS",
            "atualizar_pagos_reembolsar": "ATUALIZAR PAGOS + REEMBOLSAR",  # NOVO
            "reclamacao": "EXECUTAR RECLAMAÇÃO",
            "nao_pagos": "NÃO PAGOS",
            "vendas_encerradas": "VENDAS ENCERRADAS",
            "responder_duvidas_ml": "RESPONDER DÚVIDAS ML",
            "ia": "IA - RESPONDER CHAT E RECLAMAÇÕES",  # NOVO: execução da IA disponível no agendamento
        }
        self.acoes_disponiveis = list(self.acao_labels.values())
        self.acao_keys_por_label = {label: key for key, label in self.acao_labels.items()}
        
        self.horarios = self.config_existente.get('horarios', [self.config_existente.get('hora', '08:00')])
        self.entries_horarios = []
        
        self.janela = tk.Toplevel(parent)
        self.janela.title("Novo Agendamento" if not tarefa_id else "Editar Agendamento")
        self.janela.geometry("750x700")
        self.janela.resizable(False, True)
        self.janela.transient(parent)
        self.janela.grab_set()
        self.janela.focus_force()
        self.janela.protocol("WM_DELETE_WINDOW", self._on_cancelar)
        
        self.setup_ui()
    
    def setup_ui(self):
        """Cria a interface com suporte a múltiplos horários"""
        # Usar canvas com scrollbar para permitir scroll
        canvas = tk.Canvas(self.janela)
        scrollbar = ttk.Scrollbar(self.janela, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # --- Frame Principal (dentro do canvas) ---
        main_frame = scrollable_frame
        
        # --- Nome da Tarefa ---
        tk.Label(main_frame, text="Nome da Tarefa:", font=("Arial", 10, "bold")).grid(row=0, column=0, sticky="w", pady=5, padx=20)
        self.var_nome = tk.StringVar(main_frame, value=self.config_existente.get('nome', ''))
        tk.Entry(main_frame, textvariable=self.var_nome, width=40).grid(row=0, column=1, sticky="ew", pady=5, padx=20)
        
        # --- Email da Conta ---
        tk.Label(main_frame, text="Email da Conta:", font=("Arial", 10, "bold")).grid(row=1, column=0, sticky="w", pady=5, padx=20)
        self.var_email = tk.StringVar(main_frame, value=self.config_existente.get('email', ''))
        
        # Frame para email com botão de adicionar
        email_frame = tk.Frame(main_frame)
        email_frame.grid(row=1, column=1, sticky="ew", pady=5, padx=20)
        
        emails_cadastrados = get_registered_emails()
        email_atual = self.config_existente.get('email', '')
        
        # Se o email atual não está na lista, adiciona
        if email_atual and email_atual not in emails_cadastrados:
            emails_cadastrados.append(email_atual)
            emails_cadastrados = sorted(emails_cadastrados)
        
        # Combobox para seleção de email
        self.combo_email = ttk.Combobox(email_frame, textvariable=self.var_email, 
                                        values=emails_cadastrados, width=37, state="normal")
        self.combo_email.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Botão para adicionar novo email
        btn_novo_email = tk.Button(email_frame, text="+ Novo", command=self._adicionar_novo_email_dialog, 
                                   bg="#007bff", fg="white", width=6, font=("Arial", 8))
        btn_novo_email.pack(side=tk.LEFT, padx=5)

        # --- Prazo Entrega ---
        tk.Label(main_frame, text="Prazo Entrega:", font=("Arial", 10, "bold")).grid(row=2, column=0, sticky="w", pady=5, padx=20)
        self.var_prazo_entrega = tk.StringVar(main_frame, value=self.config_existente.get('prazo_entrega', ''))
        tk.Entry(main_frame, textvariable=self.var_prazo_entrega, width=40).grid(row=2, column=1, sticky="ew", pady=5, padx=20)

        # --- Código de Rastreio ---
        tk.Label(main_frame, text="Cód. Rastreio:", font=("Arial", 10, "bold")).grid(row=3, column=0, sticky="w", pady=5, padx=20)
        self.var_cod_rastreio = tk.StringVar(main_frame, value=self.config_existente.get('cod_rastreio', ''))
        tk.Entry(main_frame, textvariable=self.var_cod_rastreio, width=40).grid(row=3, column=1, sticky="ew", pady=5, padx=20)

        # --- Página Inicial (Offset) ---
        tk.Label(main_frame, text="Página Inicial (Offset):", font=("Arial", 10, "bold")).grid(row=4, column=0, sticky="w", pady=5, padx=20)
        self.var_offset = tk.StringVar(main_frame, value=self.config_existente.get('offset', '0'))
        tk.Entry(main_frame, textvariable=self.var_offset, width=40).grid(row=4, column=1, sticky="ew", pady=5, padx=20)

        # --- Ordem IDs ---
        tk.Label(main_frame, text="Ordem IDs:", font=("Arial", 10, "bold")).grid(row=5, column=0, sticky="w", pady=5, padx=20)
        self.var_ordem_ids = tk.StringVar(main_frame, value=self.config_existente.get('ordem_ids', ''))
        tk.Entry(main_frame, textvariable=self.var_ordem_ids, width=40).grid(row=5, column=1, sticky="ew", pady=5, padx=20)

        # --- Data Entrega ---
        tk.Label(main_frame, text="Data Entrega:", font=("Arial", 10, "bold")).grid(row=6, column=0, sticky="w", pady=5, padx=20)
        self.var_data_entrega = tk.StringVar(main_frame, value=self.config_existente.get('data_entrega', ''))
        tk.Entry(main_frame, textvariable=self.var_data_entrega, width=40).grid(row=6, column=1, sticky="ew", pady=5, padx=20)
        
        # --- Tipo de Agendamento ---
        tk.Label(main_frame, text="Tipo:", font=("Arial", 10, "bold")).grid(row=7, column=0, sticky="w", pady=5, padx=20)
        self.var_tipo = tk.StringVar(main_frame, value=self.config_existente.get('tipo', 'diaria'))
        combo_tipo = ttk.Combobox(main_frame, textvariable=self.var_tipo, values=['diaria', 'unica'], state="readonly", width=37)
        combo_tipo.grid(row=7, column=1, sticky="ew", pady=5, padx=20)
        combo_tipo.bind('<<ComboboxSelected>>', self._on_tipo_change)
        
        # --- Ação ---
        tk.Label(main_frame, text="Ação:", font=("Arial", 10, "bold")).grid(row=8, column=0, sticky="w", pady=5, padx=20)
        acao_key = self.config_existente.get('acao', 'boleto')
        acao_label = self.acao_labels.get(acao_key, self.acao_labels['boleto'])
        self.var_acao = tk.StringVar(main_frame, value=acao_label)
        combo_acao = ttk.Combobox(main_frame, textvariable=self.var_acao, values=self.acoes_disponiveis, state="readonly", width=37)
        combo_acao.grid(row=8, column=1, sticky="ew", pady=5, padx=20)
        
        # --- Data (apenas para execução única) ---
        self.label_data = tk.Label(main_frame, text="Data (DD/MM/YYYY):", font=("Arial", 10, "bold"))
        self.var_data = tk.StringVar(main_frame, value=self.config_existente.get('data', datetime.now().strftime('%d/%m/%Y')))
        self.entry_data = tk.Entry(main_frame, textvariable=self.var_data, width=40)
        
        # --- Separador ---
        ttk.Separator(main_frame, orient='horizontal').grid(row=9, column=0, columnspan=2, sticky="ew", pady=10, padx=20)
        
        # --- MÚLTIPLOS HORÁRIOS ---
        tk.Label(main_frame, text="Quantas execuções diárias?", font=("Arial", 10, "bold")).grid(row=10, column=0, sticky="w", pady=5, padx=20)
        self.var_num_execucoes = tk.IntVar(main_frame, value=len(self.horarios))
        spinbox_exec = ttk.Spinbox(main_frame, from_=1, to=10, textvariable=self.var_num_execucoes, width=10)
        spinbox_exec.grid(row=10, column=1, sticky="w", pady=5, padx=20)
        spinbox_exec.bind('<<Change>>', self._atualizar_horarios)
        
        # Bind manualmente para Spinbox
        spinbox_exec.bind('<KeyRelease>', self._atualizar_horarios)
        spinbox_exec.bind('<ButtonRelease-1>', self._atualizar_horarios)
        
        tk.Label(main_frame, text="Horários de Execução:", font=("Arial", 10, "bold")).grid(row=11, column=0, sticky="w", pady=10, padx=20)
        
        # Frame para os horários
        self.frame_horarios = tk.Frame(main_frame)
        self.frame_horarios.grid(row=12, column=0, columnspan=2, sticky="ew", padx=20)
        
        self._atualizar_horarios()
        
        # --- Ativo ---
        tk.Label(main_frame, text="Ativo:", font=("Arial", 10, "bold")).grid(row=13, column=0, sticky="w", pady=5, padx=20)
        self.var_ativo = tk.BooleanVar(main_frame, value=self.config_existente.get('ativo', True))
        ttk.Checkbutton(main_frame, text="Ativar este agendamento", variable=self.var_ativo).grid(row=13, column=1, sticky="w", pady=5, padx=20)
        
        # --- Intervalo de Repetição (para rodar a cada X minutos) ---
        tk.Label(main_frame, text="Repetir a cada (minutos, 0 = não repetir):", font=("Arial", 10, "bold")).grid(row=14, column=0, sticky="w", pady=5, padx=20)
        self.var_intervalo_min = tk.IntVar(main_frame, value=self.config_existente.get('intervalo_minutos', 0))
        spinbox_intervalo = ttk.Spinbox(main_frame, from_=0, to=1440, increment=5, textvariable=self.var_intervalo_min, width=10)
        spinbox_intervalo.grid(row=14, column=1, sticky="w", pady=5, padx=20)
        tk.Label(main_frame, text="Ex: 30 = roda a cada 30min, o dia todo, a partir do 1º horário", font=("Arial", 8), fg="#666").grid(row=15, column=0, columnspan=2, sticky="w", padx=20)
                
        # --- Botões ---
        btn_frame = tk.Frame(main_frame)
        btn_frame.grid(row=16, column=0, columnspan=2, pady=20)
        
        self.btn_salvar = tk.Button(btn_frame, text="Salvar", command=self._salvar, bg="#28a745", fg="white", font=("Arial", 11, "bold"), width=15)
        self.btn_salvar.pack(side=tk.LEFT, padx=10)
        self.btn_cancelar = tk.Button(btn_frame, text="Cancelar", command=self.janela.destroy, bg="#6c757d", fg="white", font=("Arial", 11, "bold"), width=15)
        self.btn_cancelar.pack(side=tk.LEFT, padx=10)
        
        self.status_label = tk.Label(main_frame, text="", fg="#333", font=("Arial", 9), anchor="w")
        self.status_label.grid(row=17, column=0, columnspan=2, sticky="w", padx=20)
        
        # Empacotar canvas e scrollbar
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Inicializar visibilidade da data
        self._on_tipo_change()
    
    def _adicionar_novo_email_dialog(self):
        """Abre um diálogo para adicionar um novo email"""
        novo_email = simpledialog.askstring(
            "Novo Email", 
            "Digite o novo email (conta):",
            parent=self.janela
        )
        
        if novo_email:
            novo_email = novo_email.strip()
            
            # Validar formato do email
            if '@' not in novo_email:
                messagebox.showerror("Erro", "Por favor, digite um email válido (deve conter @)")
                return
            
            # Verificar se email já existe
            emails_cadastrados = get_registered_emails()
            if novo_email in emails_cadastrados:
                messagebox.showwarning("Aviso", f"O email {novo_email} já está cadastrado.")
                self.var_email.set(novo_email)
                self.combo_email['values'] = sorted(emails_cadastrados)
                return
            
            # Criar pasta para o novo email
            pasta_nova = os.path.join(ACCOUNTS_DIR, novo_email)
            try:
                os.makedirs(pasta_nova, exist_ok=True)
                messagebox.showinfo("Sucesso", f"Email {novo_email} adicionado com sucesso!")
                
                # Atualizar Combobox com o novo email
                emails_cadastrados.append(novo_email)
                self.combo_email['values'] = sorted(emails_cadastrados)
                self.var_email.set(novo_email)
            except Exception as e:
                messagebox.showerror("Erro", f"Erro ao criar pasta para novo email: {e}")
    
    def _atualizar_horarios(self, event=None):
        """Atualiza os campos de entrada de horários baseado na quantidade selecionada"""
        num_exec = self.var_num_execucoes.get()
        
        # Limpar frame anterior
        for widget in self.frame_horarios.winfo_children():
            widget.destroy()
        
        self.entries_horarios = []
        
        # Atualizar lista de horários se necessário
        while len(self.horarios) < num_exec:
            self.horarios.append("08:00")
        while len(self.horarios) > num_exec:
            self.horarios.pop()
        
        # Criar entries para cada horário
        for idx in range(num_exec):
            tk.Label(self.frame_horarios, text=f"Execução {idx+1}:").grid(row=idx, column=0, sticky="w", pady=3)
            
            var_horario = tk.StringVar(value=self.horarios[idx])
            entry = tk.Entry(self.frame_horarios, textvariable=var_horario, width=10)
            entry.grid(row=idx, column=1, sticky="w", pady=3, padx=10)
            
            self.entries_horarios.append((var_horario, entry))
    
    def _on_tipo_change(self, event=None):
        """Mostra/oculta o campo de data baseado no tipo selecionado"""
        # Implementação será feita dinamicamente via canvas
        pass
    
    def _on_cancelar(self):
        if hasattr(self, 'janela'):
            try:
                self.janela.grab_release()
            except Exception:
                pass
            self.janela.destroy()

    def _fechar_janela(self):
        try:
            self.janela.grab_release()
        except Exception:
            pass
        try:
            self.janela.destroy()
        except Exception:
            pass

    def _salvar(self):
        """Salva o agendamento com múltiplos horários"""
        # Validar inputs
        nome = self.var_nome.get().strip()
        email = self.var_email.get().strip()
        tipo = self.var_tipo.get()
        acao = self.var_acao.get()
        
        if not all([nome, email, acao]):
            messagebox.showerror("Erro", "Preencha todos os campos obrigatórios!")
            return
        
        # Coletar e validar horários
        horarios = []
        for var_horario, entry in self.entries_horarios:
            hora = var_horario.get().strip()
            if not hora:
                messagebox.showerror("Erro", "Todos os horários devem estar preenchidos!")
                return
            
            try:
                h, m = hora.split(':')
                int(h), int(m)
                if int(h) < 0 or int(h) > 23 or int(m) < 0 or int(m) > 59:
                    raise ValueError()
                horarios.append(hora)
            except:
                messagebox.showerror("Erro", f"Hora inválida: {hora}! Use o formato HH:MM")
                return
        
        # Validar data para execução única
        data = None
        if tipo == 'unica':
            data = self.var_data.get().strip()
            if not data:
                messagebox.showerror("Erro", "Data é obrigatória para execução única!")
                return
            try:
                datetime.strptime(data, '%d/%m/%Y')
            except:
                messagebox.showerror("Erro", "Data inválida! Use o formato DD/MM/YYYY")
                return
        
        # Salvar no arquivo
        acao_label = self.var_acao.get()
        acao_key = self.acao_keys_por_label.get(acao_label, acao_label)
        
        config = {
            'nome': nome,
            'email': email,
            'tipo': tipo,
            'acao': acao_key,
            'hora': horarios[0],
            'horarios': horarios,
            'ativo': self.var_ativo.get(),
            'intervalo_minutos': self.var_intervalo_min.get(),   # NOVO
            'prazo_entrega': self.var_prazo_entrega.get(),
            'cod_rastreio': self.var_cod_rastreio.get(),
            'offset': self.var_offset.get(),
            'ordem_ids': self.var_ordem_ids.get(),
            'data_entrega': self.var_data_entrega.get()
        }
        if tipo == 'unica':
            config['data'] = data
        
        self.status_label.config(text="Salvando agendamento... aguarde")
        self.btn_salvar.config(state=tk.DISABLED)
        self.btn_cancelar.config(state=tk.DISABLED)
        self.janela.update_idletasks()

        try:
            sucesso = self.gerenciador.salvar_e_registrar_agendamento(self.tarefa_id, config)
        except Exception as e:
            print(f"[ERRO] Falha ao salvar agendamento: {e}")
            sucesso = False

        try:
            self.callback_atualizar()
        except Exception as e:
            print(f"[ERRO] Falha ao atualizar painel de agendamentos: {e}")

        try:
            if sucesso:
                self.status_label.config(text="Agendamento salvo com sucesso!")
                self.janela.update_idletasks()
                messagebox.showinfo("Sucesso", "Agendamento salvo com sucesso!\n\nAs tarefas foram registradas no Windows Task Scheduler.", parent=self.janela)
            else:
                self.status_label.config(text="Falha ao registrar no Windows Task Scheduler.")
                self.janela.update_idletasks()
                messagebox.showwarning(
                    "Atenção",
                    "Agendamento salvo no JSON, mas houve problema ao registrar no Windows Task Scheduler.\n"
                    "Verifique se o aplicativo tem permissão e tente novamente.",
                    parent=self.janela
                )
        except Exception:
            pass
        finally:
            self._fechar_janela()

        try:
            self.parent.lift()
            self.parent.focus_force()
        except Exception:
            pass

class JanelaChamarWpp(tk.Toplevel):
    """
    Janela do Sistema 'Chamar WPP'
    Permite filtrar a planilha de vendas, gerar CSV formatado para o Google Contatos,
    abrir o WhatsApp Web via Chrome em modo Debug e preparar a execução do robô.
    """
    def __init__(self, parent, app_instance):
        super().__init__(parent)
        self.app = app_instance
        self.title("Sistema Chamar WPP - Automação & Filtros")
        self.geometry("640x680")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        # Variáveis dos Campos
        self.var_nome_conta = tk.StringVar()
        self.var_numero_wpp = tk.StringVar()
        self.var_qtd_chamar = tk.StringVar(value="10")
        
        self.driver = None
        self.dados_filtrados = []  # Guarda os registros filtrados da planilha
        # Nome da loja (persistido por conta) e intervalo entre contatos
        self.var_nome_loja = tk.StringVar(value=self._carregar_nome_loja())
        self.var_delay_segundos = tk.StringVar(value="60")

        self._criar_layout()
        
    def _obter_email_atual(self):
        email_bruto = self.app.var_email.get().strip() if hasattr(self.app, 'var_email') else ""
        return parse_email_from_display(email_bruto) if email_bruto else ""

    def _carregar_nome_loja(self):
        """Carrega o nome da loja salvo anteriormente para esta conta (config_conta.json)."""
        email = self._obter_email_atual()
        if not email:
            return ""
        metadata = get_account_metadata(email)
        return metadata.get('NOME_DA_LOJA', '')

    def _salvar_nome_loja(self, nome):
        """Salva o nome da loja como padrão para esta conta."""
        email = self._obter_email_atual()
        if not email or not nome:
            return
        pasta = os.path.join(ACCOUNTS_DIR, email)
        if not os.path.exists(pasta):
            os.makedirs(pasta, exist_ok=True)
        metadata = get_account_metadata(email)
        if metadata.get('NOME_DA_LOJA') == nome:
            return  # já está salvo, evita gravação desnecessária
        metadata['NOME_DA_LOJA'] = nome
        self.app.salvar_config_cliente(pasta, metadata)    

    def _criar_layout(self):
        # Header Info
        header_frame = tk.Frame(self, bg="#002357", pady=10)
        header_frame.pack(fill=tk.X)
        tk.Label(
            header_frame, 
            text="SISTEMA DE CHAMADAS WHATSAPP", 
            font=("Arial", 12, "bold"), 
            bg="#002357", fg="white"
        ).pack()

                # --- CONFIGURAÇÕES DA LOJA E DE ENVIO ---
        frame_loja = tk.LabelFrame(
            self,
            text=" 0. Configurações da Loja e Envio ",
            font=("Arial", 10, "bold"),
            padx=15,
            pady=10
        )
        frame_loja.pack(fill=tk.X, padx=15, pady=(10, 0))

        tk.Label(frame_loja, text="Nome da Loja:", font=("Arial", 9)).grid(row=0, column=0, sticky="w", pady=5)
        entry_nome_loja = tk.Entry(frame_loja, textvariable=self.var_nome_loja, width=35)
        entry_nome_loja.grid(row=0, column=1, pady=5, padx=5, sticky="w")
        entry_nome_loja.bind(
            "<FocusOut>",
            lambda e: self._salvar_nome_loja(self.var_nome_loja.get().strip())
        )
        tk.Label(
            frame_loja, text="(fica salvo como padrão para esta conta)",
            font=("Arial", 8), fg="gray"
        ).grid(row=0, column=2, sticky="w", padx=5)

        tk.Label(frame_loja, text="Segundos entre cada contato:", font=("Arial", 9)).grid(row=1, column=0, sticky="w", pady=5)
        tk.Entry(frame_loja, textvariable=self.var_delay_segundos, width=10).grid(row=1, column=1, pady=5, padx=5, sticky="w")
        tk.Label(
            frame_loja, text="Ex: 60 = espera 60s antes de chamar o próximo contato",
            font=("Arial", 8), fg="gray"
        ).grid(row=1, column=2, sticky="w", padx=5)
        # --- ETAPA 1: Configuração e Extração ---
        frame_config = tk.LabelFrame(
            self, 
            text=" 1. Configurações de Extração da Planilha ", 
            font=("Arial", 10, "bold"), 
            padx=15, 
            pady=10
        )
        frame_config.pack(fill=tk.X, padx=15, pady=10)

        tk.Label(frame_config, text="Digite nome da conta:", font=("Arial", 9)).grid(row=0, column=0, sticky="w", pady=5)
        tk.Entry(frame_config, textvariable=self.var_nome_conta, width=70).grid(row=1, column=0, pady=5, padx=5, sticky="w")

        tk.Label(frame_config, text="Digite número do WPP:", font=("Arial", 9)).grid(row=0, column=1, sticky="w", pady=5)
        tk.Entry(frame_config, textvariable=self.var_numero_wpp, width=20).grid(row=1, column=1, pady=5, padx=5, sticky="w")
        
        frame_botoes_extrair = tk.Frame(frame_config)
        frame_botoes_extrair.grid(row=2, column=0, columnspan=2, sticky="we", pady=(10, 5))
        frame_botoes_extrair.columnconfigure(0, weight=1)
        frame_botoes_extrair.columnconfigure(1, weight=1)

        self.btn_extrair_dobro = tk.Button(
            frame_botoes_extrair,
            text="Extrair Dobro (Pagos)",
            command=self.extrair_numeros_planilha_dobro,
            bg="#007bff", fg="white", font=("Arial", 9, "bold"), height=2
        )
        self.btn_extrair_dobro.grid(row=0, column=0, sticky="we", padx=(0, 5))

        self.btn_extrair_comum = tk.Button(
            frame_botoes_extrair,
            text="Extrair Comum (Não Enviados)",
            command=self.extrair_numeros_planilha_comum,
            bg="#6f42c1", fg="white", font=("Arial", 9, "bold"), height=2
        )
        self.btn_extrair_comum.grid(row=0, column=1, sticky="we", padx=(5, 0))

        # Status da Extração
        self.lbl_status_extracao = tk.Label(frame_config, text="Status: Nenhuma extração realizada", fg="gray", font=("Arial", 9, "italic"))
        self.lbl_status_extracao.grid(row=3, column=0, columnspan=2, sticky="w")

        # --- ETAPA 2: Gerar CSV para Google Contatos ---
        frame_csv = tk.LabelFrame(self, text=" 2. Gerar Contatos ", font=("Arial", 10, "bold"), padx=15, pady=10)
        frame_csv.pack(fill=tk.X, padx=15, pady=5)

        # Frame para os dois botões lado a lado (dividindo a largura em 50/50)
        frame_botoes_contato = tk.Frame(frame_csv)
        frame_botoes_contato.pack(fill=tk.X, pady=5)
        frame_botoes_contato.columnconfigure(0, weight=1)
        frame_botoes_contato.columnconfigure(1, weight=1)

        self.btn_gerar_csv = tk.Button(
            frame_botoes_contato,
            text="Gerar (Google Contatos)",
            command=self.gerar_csv_google,
            bg="#17a2b8", fg="white", font=("Arial", 9, "bold"), state="disabled", height=2
        )
        self.btn_gerar_csv.grid(row=0, column=0, sticky="ew", padx=(0, 5))

        self.btn_gerar_vcf = tk.Button(
            frame_botoes_contato,
            text="Gerar para iCloud/iPhone",
            command=self.gerar_vcard_icloud,
            bg="#000000", fg="white", font=("Arial", 9, "bold"), state="disabled", height=2
        )
        self.btn_gerar_vcf.grid(row=0, column=1, sticky="ew", padx=(5, 0))

        # --- ETAPA 3: Abertura Chrome & Execução do Robô ---
        # DESATIVADO: automação via Chrome debug não é mais utilizada.
        # Era a causa do travamento (driver.get() bloqueando a thread principal).
        # Para reativar no futuro, basta descomentar o bloco abaixo.
        DESATIVAR_AUTOMACAO_WPP_CHROME = True

        self.driver = None  # mantém o atributo existindo para não quebrar outras partes do código

        if not DESATIVAR_AUTOMACAO_WPP_CHROME:
            frame_robo = tk.LabelFrame(self, text=" 3. Automação WhatsApp Web ", font=("Arial", 10, "bold"), padx=15, pady=10)
            frame_robo.pack(fill=tk.X, padx=15, pady=10)

            self.btn_abrir_wpp = tk.Button(
                frame_robo, 
                text="Abrir WPP Web", 
                command=self.executar_chrome_debug, 
                bg="#6c757d", fg="white", font=("Arial", 9, "bold"), height=2
            )
            self.btn_abrir_wpp.pack(fill=tk.X, pady=5)

            # Painel de Disparo
            frame_painel = tk.Frame(frame_robo)
            frame_painel.pack(fill=tk.X, pady=10)

            tk.Label(frame_painel, text="Disponíveis para chamar:", font=("Arial", 9)).grid(row=0, column=0, sticky="w")
            self.lbl_qtd_disponivel = tk.Label(frame_painel, text="0", font=("Arial", 10, "bold"), fg="#007bff")
            self.lbl_qtd_disponivel.grid(row=0, column=1, sticky="w", padx=(5, 20))

            tk.Label(frame_painel, text="Quantos deseja chamar:", font=("Arial", 9)).grid(row=0, column=2, sticky="e")
            tk.Entry(frame_painel, textvariable=self.var_qtd_chamar, width=8, font=("Arial", 9, "bold")).grid(row=0, column=3, sticky="w", padx=5)

            self.btn_executar_robo = tk.Button(
                frame_robo, 
                text="EXECUTAR ROBÔ", 
                command=self.iniciar_execucao_robo, 
                bg="#28a745", fg="white", font=("Arial", 10, "bold"), state="disabled", height=2
            )
            self.btn_executar_robo.pack(fill=tk.X, pady=(5, 0))
            
    def _obter_caminho_planilha(self):
        """Localiza a planilha vendas.xlsx ou vendas.csv dentro da pasta da conta do e-mail selecionado."""
        email_bruto = self.app.var_email.get().strip() if hasattr(self.app, 'var_email') else ""
        
        # Função interna de extração do e-mail (caso esteja formatado "Nome (email@dom.com)")
        email = parse_email_from_display(email_bruto) if 'parse_email_from_display' in globals() else email_bruto

        if not email:
            messagebox.showerror("Erro", "Selecione uma conta/e-mail válido na tela principal!")
            return None

        # Pasta da conta (mesmo local onde é exportado)
        pasta_conta = os.path.join(ACCOUNTS_DIR, email) if 'ACCOUNTS_DIR' in globals() else os.path.join("contas", email)
        
        if not os.path.exists(pasta_conta):
            messagebox.showerror("Erro", f"A pasta da conta não foi encontrada:\n{pasta_conta}")
            return None

        # Procura os arquivos vendas.xlsx ou vendas.csv na pasta
        candidatos = [
            os.path.join(pasta_conta, "vendas.xlsx"),
            os.path.join(pasta_conta, "vendas.csv"),
            os.path.join(pasta_conta, "vendas.xlsx - Vendas.csv")
        ]

        for path in candidatos:
            if os.path.exists(path):
                return path

        messagebox.showerror("Erro", f"Não foi localizada nenhuma planilha 'vendas' na pasta:\n{pasta_conta}")
        return None
    
    
    def extrair_numeros_planilha_comum(self):
        """Extrai os registros que AINDA NÃO tiveram o boleto enviado (boleto_enviado vazio),
        ordenando do mais antigo para o mais recente pelo campo 'Data', respeitando a
        quantidade solicitada para o WPP informado."""
        nome_conta = self.var_nome_conta.get().strip()
        num_wpp = self.var_numero_wpp.get().strip()

        if not nome_conta or not num_wpp:
            messagebox.showwarning("Aviso", "Preencha o 'Nome da conta' e o 'Número do WPP' para prosseguir.")
            return

        caminho_planilha = self._obter_caminho_planilha()
        if not caminho_planilha:
            return

        try:
            if caminho_planilha.endswith('.csv'):
                df = pd.read_csv(caminho_planilha, dtype=str)
            else:
                df = pd.read_excel(caminho_planilha, dtype=str)

            df.columns = [str(c).strip() for c in df.columns]

            colunas_necessarias = ['Order ID', 'boleto_Pago', 'Vendas Encerradas', 'numero', 'Data']
            for col in colunas_necessarias:
                if col not in df.columns:
                    messagebox.showerror("Erro de Coluna", f"A coluna obrigatória '{col}' não foi encontrada na planilha.")
                    return

            mask_nao_enviado = (
                df['boleto_Pago'].isna() |
                (df['boleto_Pago'].astype(str).str.strip().str.upper() != 'SIM')
            )
            mask_encerrada = df['Vendas Encerradas'].astype(str).str.strip().str.upper() == 'NÃO'
            mask_numero = (
                df['numero'].notna() &
                (df['numero'].astype(str).str.strip().str.upper() != 'N/A') &
                (df['numero'].astype(str).str.strip() != '')
            )

            df_filtrado = df[mask_nao_enviado & mask_encerrada & mask_numero].copy()

            # Já foi chamado por algum WPP (evita duplicar chamada)
            if 'Chamado_WPP' in df_filtrado.columns:
                df_filtrado = df_filtrado[df_filtrado['Chamado_WPP'].astype(str).str.strip().str.upper() != 'SIM']

            df_filtrado['_data_ordenacao'] = pd.to_datetime(
                df_filtrado['Data'],
                format='%d/%m/%Y %H:%M',
                errors='coerce'
            )
            df_filtrado = df_filtrado.sort_values(
                by='_data_ordenacao',
                ascending=True,
                na_position='last'
            ).drop(columns=['_data_ordenacao'])

            total_disponivel = len(df_filtrado)

            if total_disponivel == 0:
                self.lbl_status_extracao.config(
                    text="Status: 0 registros encontrados (sem boleto enviado).", fg="red"
                )
                self.lbl_qtd_disponivel.config(text="0")
                self.btn_gerar_csv.config(state="disabled")
                self.btn_gerar_vcf.config(state="disabled")
                messagebox.showinfo(
                    "Extração",
                    "Nenhum registro atende aos critérios (sem boleto_Pago / Vendas Encerradas: não / numero válido)."
                )
                return

            # --- Pergunta a quantidade a extrair para este WPP ---
            qtd_desejada = simpledialog.askinteger(
                "Quantidade a Extrair",
                f"Total de registros disponíveis (Comum): {total_disponivel}\n\n"
                f"Quantos deseja extrair para o WPP '{num_wpp}'?",
                minvalue=1,
                maxvalue=total_disponivel,
                initialvalue=min(30, total_disponivel),
                parent=self
            )
            if not qtd_desejada:
                self.app.logger("Extração (Comum) cancelada (quantidade não informada).", "AVISO")
                return

            df_filtrado = df_filtrado.head(qtd_desejada)

            self.dados_filtrados = df_filtrado.to_dict(orient='records')
            total = len(self.dados_filtrados)

            self.lbl_status_extracao.config(
                text=f"Status: ✓ {total} contatos (COMUM) extraídos para o WPP '{num_wpp}'!", fg="green"
            )
            self.lbl_qtd_disponivel.config(text=str(total))
            self.btn_gerar_csv.config(state="normal")
            self.btn_gerar_vcf.config(state="normal")

            messagebox.showinfo("Sucesso", f"Extração (Comum) concluída!\nTotal extraído: {total} para o WPP '{num_wpp}'.")

        except Exception as e:
            messagebox.showerror("Erro ao Processar Planilha", f"Ocorreu um erro ao carregar/filtrar a planilha:\n{e}")
    
    def extrair_numeros_planilha_dobro(self):
        nome_conta = self.var_nome_conta.get().strip()
        num_wpp = self.var_numero_wpp.get().strip()

        if not nome_conta or not num_wpp:
            messagebox.showwarning("Aviso", "Preencha o 'Nome da conta' e o 'Número do WPP' para prosseguir.")
            return

        caminho_planilha = self._obter_caminho_planilha()
        if not caminho_planilha:
            return

        try:
            if caminho_planilha.endswith('.csv'):
                df = pd.read_csv(caminho_planilha, dtype=str)
            else:
                df = pd.read_excel(caminho_planilha, dtype=str)

            df.columns = [str(c).strip() for c in df.columns]

            colunas_necessarias = ['Order ID', 'boleto_Pago', 'Vendas Encerradas', 'numero']
            for col in colunas_necessarias:
                if col not in df.columns:
                    messagebox.showerror("Erro de Coluna", f"A coluna obrigatória '{col}' não foi encontrada na planilha.")
                    return

            mask_boleto = df['boleto_Pago'].astype(str).str.strip().str.upper() == 'SIM'
            mask_encerrada = df['Vendas Encerradas'].astype(str).str.strip().str.upper() == 'NÃO'
            mask_numero = (
                df['numero'].notna() &
                (df['numero'].astype(str).str.strip().str.upper() != 'N/A') &
                (df['numero'].astype(str).str.strip() != '')
            )

            df_filtrado = df[mask_boleto & mask_encerrada & mask_numero].copy()

            if 'Chamado_WPP' in df_filtrado.columns:
                df_filtrado = df_filtrado[df_filtrado['Chamado_WPP'].astype(str).str.strip().str.upper() != 'SIM']

            if 'Data Boleto Pago' in df_filtrado.columns:
                df_filtrado['_data_ordenacao'] = pd.to_datetime(
                    df_filtrado['Data Boleto Pago'],
                    format='%d/%m/%Y %H:%M',
                    errors='coerce'
                )
                df_filtrado = df_filtrado.sort_values(
                    by='_data_ordenacao',
                    ascending=True,
                    na_position='last'
                ).drop(columns=['_data_ordenacao'])
            else:
                self.app.logger(
                    "Coluna 'Data Boleto Pago' não encontrada na planilha; não foi possível ordenar por data de pagamento.",
                    "AVISO"
                )

            total_disponivel = len(df_filtrado)

            if total_disponivel == 0:
                self.lbl_status_extracao.config(text="Status: 0 registros encontrados com os filtros exigidos.", fg="red")
                self.lbl_qtd_disponivel.config(text="0")
                self.btn_gerar_csv.config(state="disabled")
                self.btn_gerar_vcf.config(state="disabled")
                messagebox.showinfo("Extração", "Nenhum registro atende aos critérios (boleto_Pago: sim / Vendas Encerradas: não / numero != N/A).")
                return

            # --- Pergunta a quantidade a extrair para este WPP ---
            qtd_desejada = simpledialog.askinteger(
                "Quantidade a Extrair",
                f"Total de registros disponíveis (Dobro): {total_disponivel}\n\n"
                f"Quantos deseja extrair para o WPP '{num_wpp}'?",
                minvalue=1,
                maxvalue=total_disponivel,
                initialvalue=min(30, total_disponivel),
                parent=self
            )
            if not qtd_desejada:
                self.app.logger("Extração (Dobro) cancelada (quantidade não informada).", "AVISO")
                return

            df_filtrado = df_filtrado.head(qtd_desejada)

            self.dados_filtrados = df_filtrado.to_dict(orient='records')
            total = len(self.dados_filtrados)

            self.lbl_status_extracao.config(text=f"Status: ✓ {total} contatos (Dobro) extraídos para o WPP '{num_wpp}'!", fg="green")
            self.lbl_qtd_disponivel.config(text=str(total))
            self.btn_gerar_csv.config(state="normal")
            self.btn_gerar_vcf.config(state="normal")

            messagebox.showinfo("Sucesso", f"Extração concluída!\nTotal extraído: {total} para o WPP '{num_wpp}'.")

        except Exception as e:
            messagebox.showerror("Erro ao Processar Planilha", f"Ocorreu um erro ao carregar/filtrar a planilha:\n{e}")

    def gerar_csv_google(self):
        if not self.dados_filtrados:
            messagebox.showwarning("Aviso", "Nenhum dado extraído disponível para gerar o CSV.")
            return

        nome_conta = self.var_nome_conta.get().strip()
        num_wpp = self.var_numero_wpp.get().strip()

        # Abre caixa de diálogo para salvar o CSV
        caminho_salvar = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("Arquivo CSV", "*.csv")],
            initialfile=f"contatos_google_{nome_conta}.csv",
            title="Salvar CSV para Google Contatos"
        )

        if not caminho_salvar:
            return

        try:
            # Regras do Google Contatos:
            # - Delimitador: ;
            # - Cabeçalhos: Name;Mobile Phone
            # - Codificação: utf-8-sig (UTF-8 com BOM)
            with open(caminho_salvar, mode='w', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f, delimiter=';')
                writer.writerow(['Name', 'Mobile Phone'])

                for i, row in enumerate(self.dados_filtrados, start=1):
                    seq = f"{i:02d}"  # 01, 02, 03...
                    order_id = str(row.get('Order ID', '')).strip()
                    
                    # Limpeza do número mantendo apenas dígitos
                    num_bruto = str(row.get('numero', '')).strip()
                    num_limpo = re.sub(r'\D', '', num_bruto)

                    # Formato exato do Nome do Contato:
                    # ML {XX} - {campo texto 1} WPP {campo texto 2} - ORDEM ID: {Order ID}
                    nome_contato = f"ML {seq} - {nome_conta} WPP {num_wpp} - ORDEM ID: {order_id}"

                    writer.writerow([nome_contato, num_limpo])

            messagebox.showinfo(
                "CSV Gerado", 
                f"Arquivo CSV para o Google Contatos gerado com sucesso!\n\nSalvo em:\n{caminho_salvar}\n\n"
                f"Agora você pode baixá-lo e carregá-lo no Google Drive / Google Contatos."
            )

        except Exception as e:
            messagebox.showerror("Erro ao Gerar CSV", f"Não foi possível salvar o arquivo CSV:\n{e}")

    def gerar_vcard_icloud(self):
        """Gera um arquivo .vcf (vCard) no formato que o iCloud aceita para importar contatos."""
        if not self.dados_filtrados:
            messagebox.showwarning("Aviso", "Nenhum dado extraído disponível para gerar o vCard.")
            return

        nome_conta = self.var_nome_conta.get().strip()
        num_wpp = self.var_numero_wpp.get().strip()

        caminho_salvar = filedialog.asksaveasfilename(
            defaultextension=".vcf",
            filetypes=[("vCard (iCloud/iPhone)", "*.vcf")],
            initialfile=f"contatos_icloud_{nome_conta}.vcf",
            title="Salvar vCard para iCloud"
        )

        if not caminho_salvar:
            return

        try:
            # iCloud/vCard usa quebra de linha CRLF (\r\n) conforme especificação RFC 6350
            with open(caminho_salvar, mode='w', encoding='utf-8', newline='') as f:
                for i, row in enumerate(self.dados_filtrados, start=1):
                    seq = f"{i:02d}"
                    order_id = str(row.get('Order ID', '')).strip()

                    num_bruto = str(row.get('numero', '')).strip()
                    num_limpo = re.sub(r'\D', '', num_bruto)

                    # iCloud reconhece melhor o número com código do país (+55)
                    if num_limpo and not num_limpo.startswith('55'):
                        num_limpo = '55' + num_limpo

                    nome_contato = f"ML {seq} - {nome_conta} WPP {num_wpp} - ORDEM ID: {order_id}"

                    f.write("BEGIN:VCARD\r\n")
                    f.write("VERSION:3.0\r\n")
                    f.write(f"N:{nome_contato};;;;\r\n")
                    f.write(f"FN:{nome_contato}\r\n")
                    f.write(f"TEL;TYPE=CELL:+{num_limpo}\r\n")
                    f.write("END:VCARD\r\n")

            messagebox.showinfo(
                "vCard Gerado",
                f"Arquivo .vcf para o iCloud gerado com sucesso!\n\nSalvo em:\n{caminho_salvar}\n\n"
                "Para importar: acesse icloud.com/contacts no navegador → engrenagem (⚙️) no canto "
                "inferior esquerdo → 'Importar vCard' → selecione este arquivo.\n\n"
                "No iPhone, também é possível abrir o arquivo .vcf diretamente (ex: via e-mail/AirDrop) "
                "que ele abre no app Contatos para importar."
            )

        except Exception as e:
            messagebox.showerror("Erro ao Gerar vCard", f"Não foi possível salvar o arquivo .vcf:\n{e}")
    
    
    def executar_chrome_debug(self):
        """Inicia o Google Chrome no modo debug remoto e conecta via Selenium."""
        try:
            comando = r'"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=5555 --user-data-dir="C:\selenium\AutomacaoPerfil"'
            subprocess.Popen(comando, shell=True)

            # Atualiza o estilo do botão para verde
            self.btn_abrir_wpp.configure(
                bg="#28a745",
                fg="white",
                text="✓ WPP Web Aberto (Chrome Debug: 5555)"
            )

            # Conecta o Selenium no Chrome Debug aberto
            chrome_options = Options()
            chrome_options.add_experimental_option("debuggerAddress", "127.0.0.1:5555")
            service = Service()
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            
            # Navega até o WhatsApp Web
            self.driver.get("https://web.whatsapp.com/")

            # Libera o botão de execução do robô
            self.btn_executar_robo.config(state="normal")
            messagebox.showinfo("WhatsApp Web", "Chrome iniciado em modo debug!\n\nConecte o QR Code do WhatsApp e depois clique em 'EXECUTAR ROBÔ'.")

        except Exception as e:
            messagebox.showerror("Erro ao Iniciar Chrome", f"Não foi possível iniciar o Chrome em modo debug:\n{e}")

    def iniciar_execucao_robo(self):
        qtd_disponivel = len(self.dados_filtrados)

        if not self.dados_filtrados:
            messagebox.showwarning("Aviso", "Nenhum contato extraído. Clique em 'Extrair Número da Planilha' primeiro.")
            return

        try:
            qtd_desejada = int(self.var_qtd_chamar.get().strip())
        except ValueError:
            messagebox.showwarning("Aviso", "Digite um valor numérico válido para a quantidade de contatos.")
            return

        if qtd_desejada <= 0:
            messagebox.showwarning("Aviso", "A quantidade a chamar deve ser maior que 0.")
            return

        if not self.driver:
            messagebox.showwarning("Aviso", "Abra o WPP Web (Chrome Debug) antes de executar o robô.")
            return

        nome_loja = self.var_nome_loja.get().strip()
        if not nome_loja:
            messagebox.showwarning("Aviso", "Preencha o Nome da Loja antes de executar o robô.")
            return

        num_wpp_atual = self.var_numero_wpp.get().strip()
        if not num_wpp_atual:
            messagebox.showwarning("Aviso", "Preencha o campo 'Número do WPP' antes de executar o robô, para registrar qual WPP chamou cada ordem.")
            return

        try:
            delay_segundos = int(self.var_delay_segundos.get().strip())
            if delay_segundos < 0:
                raise ValueError()
        except ValueError:
            messagebox.showwarning(
                "Aviso",
                "Informe um valor válido (número inteiro maior ou igual a 0) para os segundos entre contatos."
            )
            return

        caminho_planilha = self._obter_caminho_planilha()
        if not caminho_planilha:
            return

        if self.app._planilha_bloqueada(caminho_planilha):
            messagebox.showerror(
                "Planilha bloqueada",
                f"A planilha '{os.path.basename(caminho_planilha)}' está aberta/bloqueada.\n\n"
                "Feche o arquivo antes de executar o robô, para não perder o controle de quem já foi chamado."
            )
            return

        self._salvar_nome_loja(nome_loja)

        if qtd_desejada > qtd_disponivel:
            qtd_desejada = qtd_disponivel

        registros_para_chamar = self.dados_filtrados[:qtd_desejada]

        self.btn_executar_robo.config(state="disabled", text="EXECUTANDO...")

        thread = threading.Thread(
            target=self._executar_robo_whatsapp,
            args=(registros_para_chamar, caminho_planilha, nome_loja, delay_segundos, num_wpp_atual),
            daemon=True
        )
        thread.start()

        self.app.logger(
            f"Robô de WhatsApp iniciado em segundo plano ({qtd_desejada} contato(s)) para o WPP '{num_wpp_atual}'. "
            "Acompanhe o andamento pelo log abaixo.",
            "INFO"
        )

        self.grab_release()
        self.withdraw()

        self.app.root.deiconify()
        self.app.root.lift()
        self.app.root.focus_force()
    
    def _digitar_mensagem_whatsapp(self, campo, texto):
        """Digita um texto multi-linha no campo contenteditable do WhatsApp Web,
        usando Shift+Enter para quebras de linha (Enter sozinho enviaria a msg)."""
        linhas = texto.split("\n")
        actions = ActionChains(self.driver)
        for i, linha in enumerate(linhas):
            if linha:
                campo.send_keys(linha)
            if i < len(linhas) - 1:
                actions.key_down(Keys.SHIFT).send_keys(Keys.ENTER).key_up(Keys.SHIFT).perform()

    def _executar_robo_whatsapp(self, registros, caminho_planilha, nome_loja, delay_segundos, num_wpp_atual):
        """Percorre os registros filtrados da planilha. Para cada um, busca
        pelo Order ID, abre a conversa, digita a mensagem personalizada com
        produto/valor e envia. Após cada envio bem-sucedido, marca Chamado_WPP=SIM
        na planilha imediatamente. Se qualquer etapa falhar, interrompe todo
        o processo."""
        total = len(registros)
        sucesso = 0
        falhas = 0
        nao_encontrados = []  # lista de (order_id, numero)
        erro_fatal = None

        def _limpar_campo(valor):
            texto = str(valor).strip()
            if texto.upper() in ('', 'NAN', 'NONE', 'N/A'):
                return ""
            return texto

        # --- Pré-varredura: busca o primeiro Produto e o primeiro valor preenchidos
        # entre TODOS os contatos selecionados, para usar como padrão nos que
        # estiverem vazios (já que geralmente são iguais para o mesmo lote). ---
        produto_padrao = ""
        valor_padrao = ""
        for row in registros:
            if not produto_padrao:
                cand = _limpar_campo(row.get('Produto', ''))
                if cand:
                    produto_padrao = cand
            if not valor_padrao:
                cand = _limpar_campo(row.get('valor', ''))
                if cand:
                    valor_padrao = cand
            if produto_padrao and valor_padrao:
                break

        if not produto_padrao or not valor_padrao:
            self.after(0, lambda: messagebox.showerror(
                "Erro de Dados",
                "Não foi encontrado nenhum registro com 'Produto' e 'valor' preenchidos "
                "entre os contatos selecionados para chamar.\n\n"
                "Preencha ao menos uma linha da planilha com essas informações antes de "
                "executar o robô, pois elas são usadas para montar a mensagem."
            ))
            self.after(0, lambda: self.btn_executar_robo.config(state="normal", text="EXECUTAR ROBÔ"))
            return

        try:
            if caminho_planilha.endswith('.csv'):
                df_planilha = pd.read_csv(caminho_planilha, dtype=str)
            else:
                df_planilha = pd.read_excel(caminho_planilha, dtype=str)
            df_planilha.columns = [str(c).strip() for c in df_planilha.columns]

            if 'Order ID' not in df_planilha.columns:
                raise ValueError("Coluna 'Order ID' não encontrada na planilha.")
            if 'Chamado_WPP' not in df_planilha.columns:
                df_planilha['Chamado_WPP'] = ""
            if 'WPP_Usado' not in df_planilha.columns:
                df_planilha['WPP_Usado'] = ""

            df_planilha['Order ID'] = df_planilha['Order ID'].astype(str).str.strip()
        except Exception as e:
            self.after(0, lambda: messagebox.showerror(
                "Erro ao carregar planilha",
                f"Não foi possível carregar a planilha para controlar os contatos chamados:\n{e}"
            ))
            self.after(0, lambda: self.btn_executar_robo.config(state="normal", text="EXECUTAR ROBÔ"))
            return

        def _marcar_chamado_na_planilha(order_id):
            """Marca Chamado_WPP=SIM e registra qual WPP chamou, salvando a planilha imediatamente."""
            if self.app._planilha_bloqueada(caminho_planilha):
                raise RuntimeError(
                    f"A planilha '{os.path.basename(caminho_planilha)}' está aberta/bloqueada. "
                    "Feche o arquivo para permitir salvar o controle de quem já foi chamado."
                )

            idx = df_planilha.index[df_planilha['Order ID'] == str(order_id)]
            if len(idx) == 0:
                self.app.logger(
                    f"Aviso: ordem {order_id} não encontrada na planilha para marcar Chamado_WPP.",
                    "AVISO"
                )
                return

            df_planilha.loc[idx, 'Chamado_WPP'] = "SIM"
            df_planilha.loc[idx, 'WPP_Usado'] = num_wpp_atual

            if caminho_planilha.endswith('.csv'):
                df_planilha.to_csv(caminho_planilha, index=False)
            else:
                df_planilha.to_excel(caminho_planilha, index=False)

        for idx, row in enumerate(registros, start=1):
            order_id = str(row.get('Order ID', '')).strip()
            numero = str(row.get('numero', '')).strip()

            if not order_id:
                falhas += 1
                continue

            # --- Validação de Produto/valor ANTES de montar/digitar a mensagem ---
            produto = _limpar_campo(row.get('Produto', '')) or produto_padrao
            valor = _limpar_campo(row.get('valor', '')) or valor_padrao

            if not produto or not valor:
                falhas += 1
                self.app.logger(
                    f"[{idx}/{total}] Ordem {order_id}: 'Produto'/'valor' ausentes e sem padrão "
                    "disponível. Contato pulado (mensagem não enviada).",
                    "ERRO"
                )
                continue

            try:
                campo_busca = WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((
                        By.CSS_SELECTOR,
                        'div[contenteditable="true"][aria-label="Pesquisar ou começar uma nova conversa"], '
                        'input[aria-label="Pesquisar ou começar uma nova conversa"]'
                    ))
                )

                campo_busca.click()
                campo_busca.send_keys(Keys.CONTROL, 'a')
                campo_busca.send_keys(Keys.BACKSPACE)
                time.sleep(0.3)
                campo_busca.send_keys(order_id)
                time.sleep(1.5)

                # --- Localiza e clica na primeira conversa encontrada ---
                try:
                    primeiro_resultado = WebDriverWait(self.driver, 4).until(
                        EC.element_to_be_clickable((
                            By.CSS_SELECTOR,
                            'div[data-testid="cell-frame-container"]'
                        ))
                    )
                    primeiro_resultado.click()
                    time.sleep(1)
                except (TimeoutException, NoSuchElementException, StaleElementReferenceException):
                    falhas += 1
                    nao_encontrados.append((order_id, numero))
                    self.app.logger(
                        f"[{idx}/{total}] Nenhuma conversa encontrada para a ordem {order_id} (número {numero}).",
                        "AVISO"
                    )
                    campo_busca.click()
                    campo_busca.send_keys(Keys.CONTROL, 'a')
                    campo_busca.send_keys(Keys.BACKSPACE)
                    time.sleep(0.3)
                    continue
                
                # --- Formata o valor garantindo sempre 2 casas decimais (padrão BR com vírgula) ---
                def _formatar_valor_br(valor_bruto):
                    texto = str(valor_bruto).strip()
                    # Normaliza: troca vírgula por ponto para conseguir converter em float
                    texto_normalizado = texto.replace('.', '').replace(',', '.') if ',' in texto and '.' in texto else texto.replace(',', '.')
                    try:
                        valor_float = float(texto_normalizado)
                        return f"{valor_float:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
                    except (ValueError, TypeError):
                        return texto  # fallback: mantém como veio, caso não seja conversível

                valor_formatado = _formatar_valor_br(valor)
                
                # --- Monta a mensagem personalizada ---
                msg = (
                    f"Olá! Aqui é da Loja *{nome_loja}*.\n\n"
                    f"Recebemos o seu pedido:\n*{produto}* no Valor de: *R$ {valor_formatado}*.\n\n"
                    f"Você poderá acompanhar sua entrega por este canal!\n"
                    f"Para não perder nenhuma atualização sobre o envio, *salve o nosso número nos seus contatos.*"
                )

                # --- Localiza o campo de digitação da conversa ---
                try:
                    campo_msg = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((
                            By.CSS_SELECTOR,
                            'div[data-testid="conversation-compose-box-input"]'
                        ))
                    )
                except (TimeoutException, NoSuchElementException) as e:
                    raise RuntimeError(f"Não foi possível localizar o campo de digitação: {e}")

                try:
                    campo_msg.click()
                    self._digitar_mensagem_whatsapp(campo_msg, msg)
                except Exception as e:
                    raise RuntimeError(f"Erro ao digitar a mensagem: {e}")

                # --- Localiza e clica no botão verde de enviar ---
                try:
                    botao_enviar = WebDriverWait(self.driver, 10).until(
                        EC.element_to_be_clickable((
                            By.CSS_SELECTOR,
                            'button[aria-label="Enviar"]'
                        ))
                    )
                    botao_enviar.click()
                except (TimeoutException, NoSuchElementException) as e:
                    raise RuntimeError(f"Não foi possível clicar no botão de enviar: {e}")

                time.sleep(1)

                # --- Marca imediatamente Chamado_WPP=SIM na planilha ---
                _marcar_chamado_na_planilha(order_id)

                sucesso += 1
                self.app.logger(
                    f"[{idx}/{total}] Mensagem enviada com sucesso para a ordem {order_id} e marcada na planilha.",
                    "SUCESSO"
                )

                # Limpa a busca para o próximo contato
                campo_busca.click()
                campo_busca.send_keys(Keys.CONTROL, 'a')
                campo_busca.send_keys(Keys.BACKSPACE)
                time.sleep(0.3)

                # --- Aguarda o intervalo configurado antes do próximo contato ---
                if delay_segundos > 0 and idx < total:
                    self.app.logger(
                        f"Aguardando {delay_segundos}s antes do próximo contato...",
                        "INFO"
                    )
                    time.sleep(delay_segundos)

            except Exception as e:
                erro_fatal = f"Ordem {order_id}: {e}"
                self.app.logger(f"ERRO FATAL - Processo interrompido: {erro_fatal}", "ERRO")
                break

        # --- Relatório final ---
        if nao_encontrados:
            self.app.logger(
                f"=== RELATÓRIO FINAL: {len(nao_encontrados)} contato(s) NÃO encontrado(s) ===",
                "ERRO"
            )
            for order_id, numero in nao_encontrados:
                self.app.logger(f"Não encontrado -> Ordem: {order_id} | Número: {numero}", "ERRO")

        self.after(0, lambda: self.btn_executar_robo.config(state="normal", text="EXECUTAR ROBÔ"))

        if erro_fatal:
            self.after(0, lambda: messagebox.showerror(
                "Robô interrompido por erro",
                f"O processo foi interrompido devido a um erro:\n\n{erro_fatal}\n\n"
                f"Mensagens enviadas e marcadas na planilha antes do erro: {sucesso}\n"
                f"Não encontrados/pulados até então: {falhas}\n\n"
                "Como cada envio já foi salvo na planilha assim que concluído, você não perdeu "
                "o controle de quem já foi chamado."
            ))
        else:
            self.after(0, lambda: messagebox.showinfo(
                "Robô finalizado",
                f"Execução concluída!\n\n"
                f"Mensagens enviadas: {sucesso}\n"
                f"Não encontrados/pulados: {falhas}"
                + ("\n\nVeja o log para a lista completa de não encontrados." if nao_encontrados else "")
            ))


class JanelaDocumentacao:
    """Janela de documentação com as funcionalidades do sistema otimizada visualmente"""
    
    def __init__(self, parent):
        self.janela = tk.Toplevel(parent)
        self.janela.title("📚 Documentação das Funcionalidades")
        self.janela.geometry("1100x750")
        self.janela.resizable(True, True)
        self.janela.configure(bg="#F4F6F9") # Fundo sutil para a janela principal
        
        # Frame superior com título (Header)
        header_frame = tk.Frame(self.janela, bg="#002357", height=65)
        header_frame.pack(fill=tk.X, side=tk.TOP)
        header_frame.pack_propagate(False)
        
        titulo = tk.Label(
            header_frame, 
            text="📑 DOCUMENTAÇÃO DO SISTEMA", 
            font=("Segoe UI", 16, "bold"),
            bg="#002357",
            fg="#FFD700"
        )
        titulo.pack(pady=15)
        
        # Frame para o conteúdo com margens externas limpas
        main_frame = tk.Frame(self.janela, bg="#F4F6F9")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=15)
        
        # ScrolledText com borda suave e padding interno generoso
        self.text_widget = scrolledtext.ScrolledText(
            main_frame,
            font=("Segoe UI", 10),
            bg="#FFFFFF",
            fg="#2D3748",
            wrap=tk.WORD,
            padx=20,
            pady=20,
            bd=1,
            relief=tk.SOLID,
            highlightthickness=0
        )
        self.text_widget.pack(fill=tk.BOTH, expand=True)
        
        # --- Configuração Avançada de Tags para Alta Legibilidade ---
        # Adicionado 'spacing1' e 'spacing3' para criar respiros automáticos entre blocos de texto
        self.text_widget.tag_configure("secao_titulo", foreground="#E65100", font=("Segoe UI", 13, "bold"), spacing1=18, spacing3=6)
        self.text_widget.tag_configure("botao", foreground="#002357", font=("Segoe UI", 10, "bold"))
        self.text_widget.tag_configure("descricao", foreground="#333333", font=("Segoe UI", 10), spacing2=3)
        self.text_widget.tag_configure("destaque", foreground="#2E7D32", font=("Segoe UI", 10, "bold"))
        self.text_widget.tag_configure("info", foreground="#1565C0", font=("Segoe UI", 9, "italic"))
        self.text_widget.tag_configure("linha_sep", foreground="#E0E0E0", font=("Segoe UI", 6), spacing3=10)
        
        # Inserir conteúdo com formatação
        self._inserir_conteudo()
        
        # Desabilitar edição mantendo a seleção ativa
        self.text_widget.config(state=tk.DISABLED)
        
        # Frame inferior com botões (Footer)
        footer_frame = tk.Frame(self.janela, bg="#F4F6F9")
        footer_frame.pack(fill=tk.X, padx=20, pady=15)
        
        # Botões com estilo "Flat UI" modernos
        btn_copiar = tk.Button(
            footer_frame,
            text="📋 Copiar para Clipboard",
            command=self._copiar_documentacao,
            bg="#17A2B8",
            fg="white",
            activebackground="#138496",
            activeforeground="white",
            font=("Segoe UI", 10, "bold"),
            padx=20,
            pady=8,
            bd=0,
            cursor="hand2"
        )
        btn_copiar.pack(side=tk.LEFT)
        
        btn_fechar = tk.Button(
            footer_frame,
            text="✕ Fechar",
            command=self.janela.destroy,
            bg="#6C757D",
            fg="white",
            activebackground="#5A6268",
            activeforeground="white",
            font=("Segoe UI", 10, "bold"),
            padx=20,
            pady=8,
            bd=0,
            cursor="hand2"
        )
        btn_fechar.pack(side=tk.RIGHT)
        
        # Centralizar na tela e prender o foco
        self.janela.transient(parent)
        self.janela.grab_set()
    
    def _inserir_conteudo(self):
        """Insere o conteúdo estruturado com formatação limpa"""
        widget = self.text_widget
        
        # Seção 1: Autenticação e Conexão
        widget.insert(tk.END, "🔑 Autenticação e Conexão\n", "secao_titulo")
        widget.insert(tk.END, "━" * 70 + "\n", "linha_sep")
        
        widget.insert(tk.END, "• ", "info")
        widget.insert(tk.END, "Autorizar ML:", "botao")
        widget.insert(tk.END, " Realiza a conexão com a conta do Mercado Livre gerando um novo token de acesso. Também é utilizado para renovar o token caso ele expire.\n\n", "descricao")
        
        widget.insert(tk.END, "• ", "info")
        widget.insert(tk.END, "Logar WhatsApp:", "botao")
        widget.insert(tk.END, " Realiza a autenticação e conexão com o WhatsApp (via QR Code).\n\n", "descricao")
        
        widget.insert(tk.END, "• ", "info")
        widget.insert(tk.END, "Inserir Token MP:", "botao")
        widget.insert(tk.END, " Conecta a conta do Mercado Pago ao e-mail correspondente para identificar e conciliar os boletos pagos.\n\n", "descricao")
        
        # Seção 2: Automação de Mensagens
        widget.insert(tk.END, "💬 Automação de Mensagens (WhatsApp e ML)\n", "secao_titulo")
        widget.insert(tk.END, "━" * 70 + "\n", "linha_sep")
        
        widget.insert(tk.END, "• ", "info")
        widget.insert(tk.END, "Primeira Msg e Wpp:", "botao")
        widget.insert(tk.END, " Envia a primeira mensagem com o prazo de entrega para novas vendas. Captura o número do WhatsApp do cliente; caso ele não envie, o sistema solicita o número mais duas vezes.\n\n", "descricao")
        
        widget.insert(tk.END, "• ", "info")
        widget.insert(tk.END, "Chamar Wpp:", "botao")
        widget.insert(tk.END, " Dispara a primeira mensagem no WhatsApp percorrendo as linhas da planilha de clientes.\n\n", "descricao")
        
        widget.insert(tk.END, "• ", "info")
        widget.insert(tk.END, "Enviar Rastreio:", "botao")
        widget.insert(tk.END, " Dispara uma mensagem com o código de rastreio (Correios Brasil ou AliExpress).\n", "descricao")
        widget.insert(tk.END, "   ↳ Se houver reclamação aberta: Solicita o encerramento da reclamação.\n", "info")
        widget.insert(tk.END, "   ↳ Se for um caso comum (sem telefone cadastrado): Solicita o número de telefone ao cliente.\n\n", "info")
        
        widget.insert(tk.END, "• ", "info")
        widget.insert(tk.END, "Agradecimento:", "botao")
        widget.insert(tk.END, " Envia uma mensagem de agradecimento aos clientes que configuraram o pagamento do boleto.\n\n", "descricao")
        
        # Seção 3: Gestão de Boletos e Taxas
        widget.insert(tk.END, "💳 Gestão de Boletos e Taxas\n", "secao_titulo")
        widget.insert(tk.END, "━" * 70 + "\n", "linha_sep")
        
        widget.insert(tk.END, "• ", "info")
        widget.insert(tk.END, "Enviar Boleto:", "botao")
        widget.insert(tk.END, " Envia o boleto bancário apenas para os clientes que ainda não receberam a primeira cobrança. Possui o filtro ", "descricao")
        widget.insert(tk.END, "\"Enviar apenas para os que digitou 1?\"", "destaque")
        widget.insert(tk.END, ":\n", "descricao")
        widget.insert(tk.END, "   ↳ Se SIM: Filtra e envia apenas para as vendas onde o cliente digitou \"1\" ou que contenham a frase ", "info")
        widget.insert(tk.END, "\"A liberação do seu boleto já está sendo processada.\"", "destaque")
        widget.insert(tk.END, "\n", "info")
        widget.insert(tk.END, "   ↳ Se NÃO: Envia o boleto para todos que ainda não receberam, independentemente da interação.\n\n", "info")
        
        widget.insert(tk.END, "• ", "info")
        widget.insert(tk.END, "Taxar e Autorizar BLT:", "botao")
        widget.insert(tk.END, " Notifica o cliente que o produto foi taxado e solicita que ele digite \"1\" para autorizar o procedimento.\n\n", "descricao")
        
        widget.insert(tk.END, "• ", "info")
        widget.insert(tk.END, "Erro no Boleto:", "botao")
        widget.insert(tk.END, " Envia uma mensagem solicitando que o cliente desconsidere o código de barras anterior e encaminha um novo boleto válido.\n\n", "descricao")
        
        widget.insert(tk.END, "• ", "info")
        widget.insert(tk.END, "Cobrar Dobrado:", "botao")
        widget.insert(tk.END, " Envia dois boletos simultaneamente para efetuar a cobrança de uma nova taxa.\n\n", "descricao")
        
        widget.insert(tk.END, "• ", "info")
        widget.insert(tk.END, "Reenviar Boleto:", "botao")
        widget.insert(tk.END, " Força o reenvio do boleto com duas opções de abordagem:\n", "descricao")
        widget.insert(tk.END, "   ↳ Com mensagem de atraso: ", "info")
        widget.insert(tk.END, "\"Olá! Passando para pedir desculpas pela demora no envio do seu boleto. Tivemos uma pequena instabilidade, mas já foi resolvido!\"", "destaque")
        widget.insert(tk.END, "\n", "info")
        widget.insert(tk.END, "   ↳ Com mensagem normal: ", "info")
        widget.insert(tk.END, "\"Vamos gerar o boleto agora mesmo! Prontinho, boleto gerado!\"", "destaque")
        widget.insert(tk.END, "\n", "info")
        widget.insert(tk.END, "   ↳ Frase : ", "info")
        widget.insert(tk.END, "\"Estamos gerando seu boleto. Aguarde um momento, por favor.\"", "destaque")
        widget.insert(tk.END, "\n\n", "info")
        
        # Seção 4: Inteligência Artificial
        widget.insert(tk.END, "🤖 Inteligência Artificial (IA)\n", "secao_titulo")
        widget.insert(tk.END, "━" * 70 + "\n", "linha_sep")
        
        widget.insert(tk.END, "• ", "info")
        widget.insert(tk.END, "Rodar IA Reclamação:", "botao")
        widget.insert(tk.END, " Executa a Inteligência Artificial para analisar e responder de forma automatizada às reclamações abertas.\n\n", "descricao")
        
        widget.insert(tk.END, "• ", "info")
        widget.insert(tk.END, "Rodar IA Comum:", "botao")
        widget.insert(tk.END, " Executa a Inteligência Artificial para responder às mensagens e dúvidas gerais dos clientes.\n\n", "descricao")
        
        widget.insert(tk.END, "• ", "info")
        widget.insert(tk.END, "Responder Dúvidas ML:", "botao")
        widget.insert(tk.END, " Utiliza IA para responder automaticamente às perguntas feitas pelos usuários nos anúncios do Mercado Livre.\n\n", "descricao")
        
        # Seção 5: Dashboards e Dados
        widget.insert(tk.END, "📊 Dashboards, Relatórios e Dados\n", "secao_titulo")
        widget.insert(tk.END, "━" * 70 + "\n", "linha_sep")
        
        widget.insert(tk.END, "• ", "info")
        widget.insert(tk.END, "Dashboard:", "botao")
        widget.insert(tk.END, " Gráfico geral de controle e monitoramento da conta.\n\n", "descricao")
        
        widget.insert(tk.END, "• ", "info")
        widget.insert(tk.END, "Todos Pagos:", "botao")
        widget.insert(tk.END, " Gráfico analítico de resultados financeiros e vendas concluídas.\n\n", "descricao")
        
        widget.insert(tk.END, "• ", "info")
        widget.insert(tk.END, "Dash Lote:", "botao")
        widget.insert(tk.END, " Gráfico de desempenho segmentado por lote, baseado na data de envio do código de rastreio.\n\n", "descricao")
        
        widget.insert(tk.END, "• ", "info")
        widget.insert(tk.END, "Exportar Excel:", "botao")
        widget.insert(tk.END, " Gera uma planilha com os dados e a envia para o e-mail informado, salvando-a na pasta padrão do e-mail.\n\n", "descricao")
        
        widget.insert(tk.END, "• ", "info")
        widget.insert(tk.END, "Atualizar Pagos:", "botao")
        widget.insert(tk.END, " Analisa o status dos boletos enviados, identifica os que foram pagos e atualiza as informações na planilha.\n\n", "descricao")
        
        widget.insert(tk.END, "• ", "info")
        widget.insert(tk.END, "Vendas Encerradas:", "botao")
        widget.insert(tk.END, " Atualiza o status de todas as vendas finalizadas, replicando os dados tanto nos gráficos quanto na planilha.\n\n", "descricao")
        
        # Seção 6: Filtros de Status
        widget.insert(tk.END, "⚠️ Pendências\n", "secao_titulo")
        widget.insert(tk.END, "━" * 70 + "\n", "linha_sep")
        
        widget.insert(tk.END, "• ", "info")
        widget.insert(tk.END, "Não Pagos:", "botao")
        widget.insert(tk.END, " Cobra os clientes que receberam o boleto há mais de 24 horas e ainda não realizaram o pagamento.\n\n", "descricao")
        
        widget.insert(tk.END, "• ", "info")
        widget.insert(tk.END, "Não Autorizados:", "botao")
        widget.insert(tk.END, " Cobra os clientes que ainda não deram autorização. O sistema envia a mensagem:\n\n", "descricao")
        widget.insert(tk.END, "   ", "info")
        widget.insert(tk.END, "\"Olá! Precisamos da sua autorização para dar andamento. Caso não receba a confirmação, o pedido será cancelado automaticamente. Para receber o boleto da taxa, DIGITE 1.\"", "destaque")
        widget.insert(tk.END, "\n\n", "info")
        widget.insert(tk.END, "   ↳ Caso a rotina rode novamente e o cliente ainda não tenha digitado \"1\": O sistema envia uma nova mensagem oferecendo brindes para incentivar a resposta.\n\n", "info")
        
        # Seção 7: Controle do Sistema
        widget.insert(tk.END, "⚙️ Controle do Sistema e Rotinas\n", "secao_titulo")
        widget.insert(tk.END, "━" * 70 + "\n", "linha_sep")
        
        widget.insert(tk.END, "• ", "info")
        widget.insert(tk.END, "Agendamentos:", "botao")
        widget.insert(tk.END, " Permite criar e gerenciar tarefas agendadas para que as rotinas do sistema rodem de forma 100% automática.\n\n", "descricao")
        
        widget.insert(tk.END, "• ", "info")
        widget.insert(tk.END, "Stop Urgente:", "botao")
        widget.insert(tk.END, " Interrompe imediatamente todas as operações e execuções do sistema em caso de emergência.\n\n", "descricao")
        
        widget.insert(tk.END, "• ", "info")
        widget.insert(tk.END, "Limpar Tudo:", "botao")
        widget.insert(tk.END, " Limpa os logs e as informações visíveis na tela do sistema.\n", "descricao")

    def _copiar_documentacao(self):
        """Copia a documentação limpa para o clipboard"""
        try:
            conteudo_completo = self.text_widget.get(1.0, tk.END)
            self.janela.clipboard_clear()
            self.janela.clipboard_append(conteudo_completo)
            messagebox.showinfo("Sucesso", "Documentação copiada para o clipboard!", parent=self.janela)
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao copiar: {e}", parent=self.janela)



class AppColetorPro:
    def __init__(self, root, start_scheduler=True):
        self.root = root
        self.root.title("SISTEMA FULL DATA - ML & WHATSAPP API")
        self.root.geometry("1100x800")
        self.wpp_ativo = False  # Estado inicial: desligado
        self.auth_ml = GerenciadorTokenML()
        
        # Controle de máquina (cliente/desenvolvedor)
        self.var_machine_key = tk.StringVar(value=_get_machine_key())
        
        self.agendamentos = GerenciadorAgendamentos()
        self.stop_event = threading.Event()
        logging.getLogger().setLevel(logging.CRITICAL) # Silencia logs automáticos de bibliotecas externas
        
        self.setup_ui()
        
        if start_scheduler:
            # Inicia o scheduler ao abrir a aplicação, mostrando uma tela de
            # carregamento em vez de deixar os cmds do schtasks piscando
            self._sincronizar_scheduler_com_splash()
            
            # Garante que o scheduler é finalizado ao fechar
            self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
        
        # # ALTERAÇÃO: Função central para validar e-mail e retornar a pasta correta
        
    def _encontrar_splash_image(self, nome_arquivo="logo.png"):
        """Localiza a imagem do splash, compatível com execução normal e PyInstaller."""
        candidatos = []

        if getattr(sys, 'frozen', False):
            exe_dir = os.path.dirname(sys.executable)
            candidatos.append(os.path.join(exe_dir, nome_arquivo))
            if getattr(sys, '_MEIPASS', None):
                candidatos.append(os.path.join(sys._MEIPASS, nome_arquivo))

        candidatos.append(os.path.join(BASE_DIR, nome_arquivo))

        for caminho in candidatos:
            if caminho and os.path.exists(caminho):
                return caminho
        return None

    def abrir_janela_chamar_wpp(self):
        """Abre o sistema 'Chamar WPP' apenas se houver uma conta/e-mail selecionado."""
        # Obter o valor atual do campo/combobox de e-mail na tela principal
        email_selecionado = self.var_email.get().strip() if hasattr(self, 'var_email') else ""

        # Valida se está vazio ou se está com o texto padrão de placeholder
        if not email_selecionado or "Selecione" in email_selecionado:
            messagebox.showwarning(
                "Atenção - Conta Não Selecionada", 
                "Por favor, selecione uma conta / e-mail na tela principal antes de abrir o Chamar WPP!"
            )
            return  # Interrompe e NÃO abre a janela

        # Se estiver preenchido, abre a janela
        JanelaChamarWpp(self.root, self)
    
    def _sincronizar_scheduler_com_splash(self):
        """Sincroniza os agendamentos com o Windows Task Scheduler em segundo
        plano, exibindo uma tela de carregamento com imagem de fundo em vez
        das janelas de console (cmd) que o schtasks abriria na tela do cliente.
        A janela principal fica escondida até a sincronização terminar."""

        # Esconde a janela principal enquanto carrega
        try:
            self.root.withdraw()
        except Exception:
            pass

        splash = tk.Toplevel(self.root)
        splash.title("")
        splash.overrideredirect(True)
        splash.configure(bg="#1e1e1e")
        try:
            splash.attributes("-topmost", True)
        except Exception:
            pass

        # Tamanho máximo da janela do splash
        largura_max, altura_max = 560, 560

        largura, altura = largura_max, altura_max
        self._splash_img_tk = None  # guarda referência para não ser descartada pelo GC

        caminho_imagem = self._encontrar_splash_image("logo.png")  # ajuste o nome do arquivo aqui

        if caminho_imagem:
            try:
                from PIL import Image, ImageTk

                img = Image.open(caminho_imagem)
                img_w, img_h = img.size

                # Calcula o tamanho final mantendo a proporção original
                escala = min(largura_max / img_w, altura_max / img_h)
                largura = max(1, int(img_w * escala))
                altura = max(1, int(img_h * escala))

                img = img.resize((largura, altura), Image.LANCZOS)
                self._splash_img_tk = ImageTk.PhotoImage(img)
            except Exception as e:
                print(f"[SPLASH] Erro ao carregar/redimensionar imagem: {e}")
                self._splash_img_tk = None
        else:
            print("[SPLASH] Imagem não encontrada, usando fundo padrão.")

        # Centraliza na TELA (já que a janela principal está escondida)
        splash.update_idletasks()
        screen_w = splash.winfo_screenwidth()
        screen_h = splash.winfo_screenheight()
        x = (screen_w // 2) - (largura // 2)
        y = (screen_h // 2) - (altura // 2)
        splash.geometry(f"{largura}x{altura}+{max(x, 0)}+{max(y, 0)}")

        # --- IMAGEM DE FUNDO (ou fundo sólido, se a imagem falhar) ---
        if self._splash_img_tk:
            label_fundo = tk.Label(splash, image=self._splash_img_tk, bd=0)
            label_fundo.place(x=0, y=0, relwidth=1, relheight=1)
        else:
            borda = tk.Frame(splash, bg="#28a745", bd=0)
            borda.pack(fill=tk.BOTH, expand=True)
            conteudo_fallback = tk.Frame(borda, bg="#1e1e1e")
            conteudo_fallback.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        # --- BARRA DE PROGRESSO POR CIMA DA IMAGEM ---
        barra = ttk.Progressbar(splash, mode="indeterminate", length=min(320, largura - 60))
        barra.place(relx=0.5, rely=0.93, anchor="center")
        barra.start(12)

        splash.lift()
        splash.focus_force()

        resultado = {}

        def _tarefa_background():
            try:
                self.agendamentos.iniciar_scheduler(self)
            except Exception as e:
                resultado['erro'] = str(e)

        def _finalizar():
            try:
                barra.stop()
                splash.destroy()
            except Exception:
                pass

            # Mostra a janela principal novamente
            try:
                self.root.deiconify()
                self.root.lift()
                self.root.focus_force()
            except Exception:
                pass

            if resultado.get('erro'):
                try:
                    self.logger(f"Erro ao sincronizar agendamentos: {resultado['erro']}", "ERRO")
                except Exception:
                    print(f"[ERRO] Falha ao sincronizar agendamentos: {resultado['erro']}")

        def _aguardar_thread(thread):
            if thread.is_alive():
                self.root.after(150, lambda: _aguardar_thread(thread))
            else:
                _finalizar()

        thread = threading.Thread(target=_tarefa_background, daemon=True)
        thread.start()
        _aguardar_thread(thread)   
        

    def get_email(self):
        try:
            email = self.var_email.get().strip()
        except RuntimeError:
            return ""
        if email:
            email = parse_email_from_display(email)
        if not email and hasattr(self, 'entry_email'):
            try:
                email = self.entry_email.get().strip()
            except RuntimeError:
                return ""
            if email:
                self.var_email.set(email)
        return email

    def get_pasta_conta(self):
        email = self.get_email()
        if not email:
            messagebox.showerror("Erro", "Por favor, digite o E-MAIL da conta para prosseguir a ação.")
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
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def salvar_config_cliente(self, folder, config):
        path = os.path.join(folder, 'config_conta.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4)

    def _trocar_machine_key(self, nova_machine):
        """Troca a máquina selecionada e recarrega agendamentos"""
        if nova_machine not in ['cliente', 'desenvolvedor']:
            messagebox.showerror("Erro", "Máquina inválida. Use 'cliente' ou 'desenvolvedor'.")
            return
        
        if nova_machine == _get_machine_key():
            messagebox.showinfo("Info", f"Você já está usando: {nova_machine}")
            return
        
        # Salva a preferência
        if _save_machine_preference(nova_machine):
            self.var_machine_key.set(nova_machine)
            messagebox.showinfo(
                "Máquina Alterada", 
                f"Máquina alterada para: {nova_machine}\n\n"
                f"A aplicação usará: agendamentos_config_{nova_machine}.json\n\n"
                f"Reinicie a aplicação para aplicar as mudanças completamente."
            )
        else:
            messagebox.showerror("Erro", "Falha ao salvar preferência de máquina.")
    
    def abrir_documentacao(self):
        """Abre a janela de documentação com as funcionalidades do sistema"""
        JanelaDocumentacao(self.root)

    def _adicionar_novo_email_main(self):
        """Abre um diálogo para adicionar um novo email na interface principal"""
        novo_email = simpledialog.askstring(
            "Novo Email", 
            "Digite o novo email (conta):",
            parent=self.root
        )
        
        if novo_email:
            novo_email = novo_email.strip()
            
            # Validar formato do email
            if '@' not in novo_email:
                messagebox.showerror("Erro", "Por favor, digite um email válido (deve conter @)")
                return
            
            # Verificar se email já existe
            emails_cadastrados = get_registered_emails()
            if novo_email in emails_cadastrados:
                messagebox.showwarning("Aviso", f"O email {novo_email} já está cadastrado.")
                self.var_email.set(novo_email)
                self.combo_email_main['values'] = get_active_account_display_values()
                self.var_email.set(get_account_display_name(novo_email))
                return
            
            # Criar pasta para o novo email
            pasta_nova = os.path.join(ACCOUNTS_DIR, novo_email)
            try:
                os.makedirs(pasta_nova, exist_ok=True)
                config = {
                    'ATIVO': True,
                    'NOME_EXIBICAO': novo_email
                }
                self.salvar_config_cliente(pasta_nova, config)
                messagebox.showinfo("Sucesso", f"Email {novo_email} adicionado com sucesso!")
                
                # Atualizar Combobox com o novo email
                self.combo_email_main['values'] = get_active_account_display_values()
                self.var_email.set(get_account_display_name(novo_email))
            except Exception as e:
                messagebox.showerror("Erro", f"Erro ao criar pasta para novo email: {e}")

    def _abrir_configuracao_emails(self):
        contas = get_registered_emails()
        if not contas:
            messagebox.showwarning("Aviso", "Nenhum email cadastrado para configurar.")
            return

        janela = tk.Toplevel(self.root)
        janela.title("Configuração de Emails")
        janela.geometry("520x320")
        janela.resizable(False, False)
        janela.transient(self.root)
        janela.grab_set()

        left_frame = tk.Frame(janela)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, padx=10, pady=10, expand=True)
        right_frame = tk.Frame(janela)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, padx=10, pady=10)

        tk.Label(left_frame, text="Contas cadastradas:", font=("Arial", 10, "bold")).pack(anchor="w")
        listbox = tk.Listbox(left_frame, width=32, height=14)
        listbox.pack(fill=tk.BOTH, expand=True)

        for email in sorted(contas):
            ativo_text = "Ativo" if is_account_active(email) else "Inativo"
            listbox.insert(tk.END, f"{email} [{ativo_text}]")

        nome_var = tk.StringVar()
        ativo_var = tk.BooleanVar(value=True)

        def carregar_dados_conta(event=None):
            selection = listbox.curselection()
            if not selection:
                return
            selected_text = listbox.get(selection[0])
            selected_email = selected_text.split(' [', 1)[0]
            metadata = get_account_metadata(selected_email)
            nome_var.set(metadata.get('NOME_EXIBICAO') or selected_email)
            ativo_var.set(bool(metadata.get('ATIVO', True)))

        listbox.bind('<<ListboxSelect>>', carregar_dados_conta)

        tk.Label(right_frame, text="Nome de Exibição:", font=("Arial", 10, "bold")).pack(anchor="w")
        tk.Entry(right_frame, textvariable=nome_var, width=30).pack(pady=5)

        tk.Checkbutton(right_frame, text="Ativo", variable=ativo_var).pack(anchor="w", pady=5)

        def salvar_config_email():
            selection = listbox.curselection()
            if not selection:
                messagebox.showerror("Erro", "Selecione um email na lista para salvar.")
                return
            selected_text = listbox.get(selection[0])
            selected_email = selected_text.split(' [', 1)[0]
            pasta = os.path.join(ACCOUNTS_DIR, selected_email)
            if not os.path.exists(pasta):
                messagebox.showerror("Erro", "Pasta da conta não encontrada.")
                return
            metadata = get_account_metadata(selected_email)
            metadata['NOME_EXIBICAO'] = nome_var.get().strip() or selected_email
            metadata['ATIVO'] = ativo_var.get()
            self.salvar_config_cliente(pasta, metadata)

            # Atualizar texto da lista e combobox
            listbox.delete(0, tk.END)
            for email in sorted(contas):
                ativo_text = "Ativo" if is_account_active(email) else "Inativo"
                listbox.insert(tk.END, f"{email} [{ativo_text}]")

            self.combo_email_main['values'] = get_active_account_display_values()
            self.var_email.set(get_account_display_name(parse_email_from_display(self.var_email.get())))
            messagebox.showinfo("Sucesso", "Configuração salva com sucesso.")

        tk.Button(right_frame, text="Salvar", command=salvar_config_email, bg="#28a745", fg="white", width=12).pack(pady=10)
        tk.Button(right_frame, text="Fechar", command=janela.destroy, bg="#6c757d", fg="white", width=12).pack()

        if contas:
            listbox.selection_set(0)
            carregar_dados_conta()

    def setup_ui(self):
        # --- Header ---
        header = tk.Frame(self.root, bg="#212121", height=80)
        header.pack(fill=tk.X)
        
        # Titulo e seletor de máquina no header
        header_top = tk.Frame(header, bg="#212121")
        header_top.pack(fill=tk.X, padx=20, pady=10)
        
        tk.Label(header_top, text="PAINEL DE CONTROLE DE LEADS", fg="white", bg="#212121", 
                font=("Arial", 14, "bold")).pack(side=tk.LEFT)
        
        tk.Label(header_top, text=" | Contexto: ", fg="white", bg="#212121", 
                font=("Arial", 10)).pack(side=tk.LEFT, padx=10)
        
        machine_label = tk.Label(header_top, textvariable=self.var_machine_key, fg="#FFD700", bg="#212121", 
                                 font=("Arial", 10, "bold"))
        machine_label.pack(side=tk.LEFT)
        
        # Botões para trocar máquina
        header_buttons = tk.Frame(header, bg="#212121")
        header_buttons.pack(fill=tk.X, padx=20, pady=5)
        
        tk.Button(header_buttons, text="🔧 Cliente", command=lambda: self._trocar_machine_key('cliente'),
                 bg="#0056b3", fg="white", font=("Arial", 9), padx=10).pack(side=tk.LEFT, padx=5)
        
        tk.Button(header_buttons, text="⚙️ Desenvolvedor", command=lambda: self._trocar_machine_key('desenvolvedor'),
                 bg="#6f42c1", fg="white", font=("Arial", 9), padx=10).pack(side=tk.LEFT, padx=5)

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
        self.rodar_wa_var = tk.BooleanVar(value=False)

        tk.Label(input_frame, text="Prazo Entrega:").grid(row=0, column=0, sticky="w", padx=5)
        tk.Entry(input_frame, textvariable=self.var_prazo, width=15).grid(row=0, column=1, padx=10)

        tk.Label(input_frame, text="Cód. Rastreio:").grid(row=0, column=2, sticky="w", padx=5)
        tk.Entry(input_frame, textvariable=self.var_rastreio, width=20).grid(row=0, column=3, padx=10)

        tk.Label(input_frame, text="Página Inicial (Offset):").grid(row=0, column=4, sticky="w", padx=5)
        tk.Entry(input_frame, textvariable=self.var_pag_inicial, width=10).grid(row=0, column=5, padx=10)
        
        tk.Label(input_frame, text="Conta do Cliente. Email: ").grid(row=0, column=6, sticky="w", padx=5)
        
        # Frame para email com combobox e botão
        email_frame = tk.Frame(input_frame)
        email_frame.grid(row=0, column=7, columnspan=2, padx=10, sticky="ew")
        
        emails_cadastrados = get_active_account_display_values()
        self.combo_email_main = ttk.Combobox(email_frame, textvariable=self.var_email, 
                                              values=emails_cadastrados, width=30, state="normal")
        self.combo_email_main.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        btn_novo_email_main = tk.Button(email_frame, text="+ Novo", 
                                        command=self._adicionar_novo_email_main, 
                                        bg="#007bff", fg="white", width=6, font=("Arial", 8))
        btn_novo_email_main.pack(side=tk.LEFT, padx=5)

        btn_config_email_main = tk.Button(email_frame, text="Config", 
                                          command=self._abrir_configuracao_emails, 
                                          bg="#17a2b8", fg="white", width=6, font=("Arial", 8))
        btn_config_email_main.pack(side=tk.LEFT, padx=5)
        
        tk.Label(input_frame, text="Ordem IDs").grid(row=0, column=9, sticky="w", padx=5)
        tk.Entry(input_frame, textvariable=self.var_ordem_ids, width=40).grid(row=0, column=10, padx=10)
        
        tk.Label(input_frame, text="Data Entrega:").grid(row=0, column=11, sticky="w", padx=5)
        tk.Entry(input_frame, textvariable=self.var_data_entrega, width=40).grid(row=0, column=12, padx=10)

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
        tk.Button(btn_frame, text="TODOS PAGOS", command=self.abrir_dashboard_boletos_pagos, bg="#28a745", fg="white", **estilo).grid(row=0, column=3, padx=5, pady=5)
        tk.Button(btn_frame, text="DASH LOTES", command=self.abrir_dashboard_lotes, bg="#17a2b8", fg="white", **estilo).grid(row=2, column=7, padx=5, pady=5)
        tk.Button(btn_frame, text="EXPORTAR EXCEL", command=self.exportar_para_excel, bg="#002357", fg="white", **estilo).grid(row=0, column=4, padx=5, pady=5)
        tk.Button(btn_frame, text="ATUALIZAR PAGOS", command=self.atualizar_blt_pagos_thread, bg="#002357", fg="white", **estilo).grid(row=0, column=5, padx=5, pady=5)
        tk.Button(btn_frame, text="ATUALIZAR PIX PAGOS", command=self.atualizar_pix_pagos_thread, bg="#002357", fg="white", **estilo).grid(row=2, column=8, padx=5, pady=5)
        tk.Button(btn_frame, text="VENDAS ENCERRADAS", command=self.atualizar_vendas_encerradas_thread, bg="#002357", fg="white", **estilo).grid(row=0, column=6, padx=5, pady=5)
        tk.Button(btn_frame, text="CHAMAR WPP", command=self.abrir_janela_chamar_wpp, bg="#002357", fg="white", **estilo).grid(row=0, column=7, padx=5, pady=5)
        tk.Button(btn_frame, text="REENVIAR BLT DOBRADO", command=lambda: self.iniciar_thread_processamento(acao="reenviar_boleto_dobrado"), bg="#002357", fg="white", **estilo).grid(row=1, column=9, padx=5, pady=5)
        self.btn_wpp = tk.Button(btn_frame, text="LOGAR WPP", command=self.ativarWpp, bg="#002357", fg="white", **estilo)
        self.btn_wpp.grid(row=0, column=8, padx=5, pady=5)
        self.btn_stop = tk.Button(btn_frame, text="STOP URGENTE", command=self.parar_processamento_urgente, bg="#FF0000", fg="black", state=tk.DISABLED, **estilo)
        self.btn_stop.grid(row=0, column=9, padx=5, pady=5)
        
        btn_frame_reclamacao = ttk.Frame(self.root)
        btn_frame_reclamacao.pack(pady=10)

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
        tk.Button(btn_frame, text="TAXAR E AUTORIZAR BLT", command=lambda: self.iniciar_thread_processamento(acao="autorizar_boleto"), bg="#002357", fg="white", **estilo).grid(row=1, column=2, padx=5, pady=5)
        tk.Button(btn_frame, text="ERRO NO BOLETO", command=lambda: self.iniciar_thread_processamento(acao="erro_boleto"), bg="#002357", fg="white", **estilo).grid(row=1, column=3, padx=5, pady=5)
        tk.Button(btn_frame, text="COBRAR DOBRADO", command=lambda: self.iniciar_thread_processamento(acao="cobrar_dobrado"), bg="#002357", fg="white", **estilo).grid(row=1, column=4, padx=5, pady=5)
        tk.Button(btn_frame, text="AGRADECIMENTO", command=lambda: self.iniciar_thread_processamento(acao="agradecimento"), bg="#002357", fg="white", **estilo).grid(row=1, column=5, padx=5, pady=5)
        tk.Button(btn_frame, text="NÃO PAGOS", command=lambda: self.iniciar_thread_processamento(acao="nao_pagos"), bg="#dc3545", fg="white", **estilo).grid(row=2, column=2, padx=5, pady=5)
        tk.Button(btn_frame, text="📅 AGENDAMENTOS", command=self.abrir_painel_agendamentos, bg="#FF6600", fg="white", **estilo).grid(row=1, column=6, padx=5, pady=5)
        tk.Button(btn_frame, text="LIMPAR TUDO", command=self.limpar_campos, bg="#3B3F3F", fg="white", **estilo).grid(row=1, column=7, padx=5, pady=5)
        #tk.Button(btn_frame, text="CAPTURAR WPP", command=self.capturar_wpp_thread, bg="#002357", fg="white", **estilo).grid(row=1, column=8, padx=5, pady=5)
        tk.Button(btn_frame, text="INSERIR TOKEN MP", command=self.inserir_token_mp, bg="#002357", fg="white", **estilo).grid(row=1, column=8, padx=5, pady=5)
        tk.Button(btn_frame, text="NAO AUTORIZADOS", command=lambda: self.iniciar_thread_processamento(acao="nao_autorizados"), bg="#dc3545", fg="white", **estilo).grid(row=2, column=3, padx=5, pady=5)
        tk.Button(btn_frame, text="RODAR IA", command=lambda: self.iniciar_thread_processamento(acao="ia"), bg="#6f42c1", fg="white", **estilo).grid(row=2, column=0, padx=5, pady=5)
        tk.Button(btn_frame, text="REENVIAR BOLETO", command=lambda: self.iniciar_thread_processamento(acao="reenviar_boleto"), bg="#002357", fg="white", **estilo).grid(row=2, column=1, padx=5, pady=5)
        tk.Button(btn_frame, text="RESPONDER DUVIDAS ML", command=self.iniciar_resposta_duvidas, bg="#1C5021", fg="white", **estilo).grid(row=2, column=4, padx=5, pady=5)
        tk.Button(btn_frame, text="📚 DOCUMENTAÇÃO", command=self.abrir_documentacao, bg="#9c27b0", fg="white", **estilo).grid(row=2, column=5, padx=5, pady=5)
        tk.Button(btn_frame, text="💰 REEMBOLSAR LINK", command=self.abrir_reembolso_link, bg="#8B0000", fg="white", **estilo).grid(row=2, column=6, padx=5, pady=5)
        # --- Log ---
        self.log = scrolledtext.ScrolledText(self.root, height=50, width=190, font=("Consolas", 9), bg="#F5F5F5")
        self.log.tag_configure("log_info", foreground="#2f4a72")
        self.log.tag_configure("log_aviso", foreground="#a7800c")
        self.log.tag_configure("log_error", foreground="#dc3545")
        self.log.tag_configure("log_sucesso", foreground="#0C633A")
        self.log.tag_configure("log_ordem_label", foreground="black")
        self.log.tag_configure("log_ordem", foreground="#0d6efd", font=("Consolas", 9, "bold"))
        self.log.pack(pady=10, padx=20)

    def _on_closing(self):
        """Chamado ao fechar a aplicação"""
        self.agendamentos.parar_scheduler()
        self.root.destroy()

    def abrir_painel_agendamentos(self):
        """Abre a janela do painel de agendamentos"""
        JanelaAgendamentos(self.root, self.agendamentos, self)
        
    def limpar_campos(self):
        """Limpa todos os campos de entrada e a tela de log."""
        # Limpa os campos de entrada
        self.var_rastreio.set("")
        self.var_data_entrega.set("")
        self.var_email.set("")
        self.var_prazo.set("")
        self.var_pag_inicial.set("0")
        self.var_ordem_ids.set("")
        
        # Limpa o log
        self.log.delete(1.0, tk.END)
        
        # Mensagem de confirmação
        self.logger("Todos os campos e o log foram limpos com sucesso!", "SUCESSO")
        
    def carregar_script_ia_reclamacao(self, folder, permitir_dialogo=True):
        candidatos = [
            os.path.join(folder, "scriptIAreclamacao.txt"),
            os.path.join(BASE_DIR, "scriptIAreclamacao.txt"),
            os.path.join(r"H:\Meu Drive\Sistema Captura WPP", "scriptIAreclamacao.txt"),
            os.path.join(r"G:\Meu Drive\Sistema Captura WPP", "scriptIAreclamacao.txt"),
        ]
        for caminho in candidatos:
            if os.path.exists(caminho):
                with open(caminho, "r", encoding="utf-8") as f:
                    texto = f.read().strip()
                    if texto:
                        self.logger(f"Script IA carregado: {caminho}", "INFO")
                        return texto
        self.logger("Script da IA não encontrado. Crie scriptIAreclamacao.txt na pasta da conta, na pasta do sistema ou no Google Drive.", "ERRO")
        return ""
    
    def carregar_script_ia_question(self, folder, permitir_dialogo=True):
        candidatos = [
            os.path.join(folder, "scriptIAquestion.txt"),
            os.path.join(BASE_DIR, "scriptIAquestion.txt"),
            os.path.join(r"H:\Meu Drive\Sistema Captura WPP", "scriptIAquestion.txt"),
            os.path.join(r"G:\Meu Drive\Sistema Captura WPP", "scriptIAquestion.txt"),
        ]
        for caminho in candidatos:
            if os.path.exists(caminho):
                with open(caminho, "r", encoding="utf-8") as f:
                    texto = f.read().strip()
                    if texto:
                        self.logger(f"Script IA carregado: {caminho}", "INFO")
                        return texto
        self.logger("Script da IA não encontrado. Crie scriptIAreclamacao.txt na pasta da conta, na pasta do sistema ou no Google Drive.", "ERRO")
        return ""
    def encontrar_pasta_imagens_brindes(self, folder, nome_pasta="Brindes"):
        """
        Procura a pasta com as imagens dos brindes em múltiplos locais,
        igual é feito com os scripts da IA (conta > sistema > Google Drive).
        """
        candidatos = [
            os.path.join(folder, nome_pasta),
            os.path.join(BASE_DIR, nome_pasta),
            os.path.join(r"H:\Meu Drive\Sistema Captura WPP", nome_pasta),
            os.path.join(r"G:\Meu Drive\Sistema Captura WPP", nome_pasta),
        ]
        for caminho in candidatos:
            if os.path.exists(caminho) and os.path.isdir(caminho):
                self.logger(f"Pasta de imagens de brindes encontrada: {caminho}", "INFO")
                return caminho

        self.logger(
            f"Pasta '{nome_pasta}' não encontrada. Crie-a na pasta da conta, na pasta do "
            "sistema ou no Google Drive (H:\\Meu Drive\\Sistema Captura WPP ou G:\\Meu Drive\\Sistema Captura WPP).",
            "AVISO"
        )
        return None
    def carregar_script_ia_comum(self, folder):
        candidatos = [
            os.path.join(folder, "scriptIAcomum.txt"),
            os.path.join(BASE_DIR, "scriptIAcomum.txt"),
        ]

        for caminho in candidatos:
            if os.path.exists(caminho):
                with open(caminho, "r", encoding="utf-8") as f:
                    texto = f.read().strip()
                if texto:
                    self.logger(f"Script IA comum carregado: {caminho}", "INFO")
                    return texto

        self.logger("Script da IA comum não encontrado. Crie scriptIAcomum.txt na pasta da conta ou na pasta do sistema.", "ERRO")
        return ""

    def _mensagens_cliente_apos_ultima_resposta(self, conversa):
        conversa_ordenada = sorted(conversa, key=lambda m: str(m.get("data") or ""))
        ultima_resposta_idx = None

        for idx, msg in enumerate(conversa_ordenada):
            if msg.get("is_seller"):
                ultima_resposta_idx = idx

        mensagens_recentes = conversa_ordenada[ultima_resposta_idx + 1:] if ultima_resposta_idx is not None else conversa_ordenada
        textos_cliente = []

        for msg in mensagens_recentes:
            texto = str(msg.get("texto") or "").strip()
            if texto and not msg.get("is_seller"):
                textos_cliente.append(texto)

        return textos_cliente
    
    def carregar_db_pasta(self, folder):
        """Carrega o database_vendas.json de uma pasta específica (não depende do campo de email principal)."""
        if not folder:
            return {}
        if not os.path.exists(folder):
            try:
                os.makedirs(folder, exist_ok=True)
            except Exception as e:
                self.logger(f"Erro ao criar pasta {folder}: {e}", "ERRO")
                return {}
        db_path = os.path.join(folder, "database_vendas.json")
        if not os.path.exists(db_path):
            return {}
        try:
            with open(db_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            self.logger(f"Erro ao carregar banco de dados ({folder}): {e}", "ERRO")
            return {}

    def salvar_db_pasta(self, folder, db):
        """Salva o database_vendas.json em uma pasta específica (não depende do campo de email principal)."""
        if not folder:
            self.logger("Erro: pasta não informada para salvar banco de dados.", "ERRO")
            return
        if not os.path.exists(folder):
            try:
                os.makedirs(folder, exist_ok=True)
            except Exception as e:
                self.logger(f"Erro ao criar pasta {folder}: {e}", "ERRO")
                return
        db_path = os.path.join(folder, "database_vendas.json")
        try:
            with open(db_path, 'w', encoding='utf-8') as f:
                json.dump(db, f, indent=4)
        except Exception as e:
            self.logger(f"Erro ao salvar banco de dados ({folder}): {e}", "ERRO")
    
    def abrir_reembolso_link(self):
        """Abre uma janela para selecionar uma ou mais contas e disparar o
        processamento de reembolso (Mercado Pago) em cada uma delas."""
        emails_cadastrados = [e for e in get_registered_emails() if is_account_active(e)]
        if not emails_cadastrados:
            messagebox.showwarning("Aviso", "Nenhuma conta ATIVA cadastrada.")
            return

        janela = tk.Toplevel(self.root)
        janela.title("Reembolsar Link - Selecionar Contas")
        janela.geometry("440x520")
        janela.transient(self.root)
        janela.grab_set()

        tk.Label(
            janela,
            text="Selecione as contas que deseja reembolsar:",
            font=("Arial", 10, "bold")
        ).pack(pady=(10, 5), padx=10, anchor="w")

        frame_lista = tk.Frame(janela)
        frame_lista.pack(fill=tk.BOTH, expand=True, padx=10)

        scrollbar = tk.Scrollbar(frame_lista, orient=tk.VERTICAL)
        listbox = tk.Listbox(
            frame_lista,
            selectmode=tk.MULTIPLE,
            exportselection=False,
            yscrollcommand=scrollbar.set,
            font=("Arial", 10)
        )
        scrollbar.config(command=listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        emails_ordenados = sorted(emails_cadastrados)
        for email in emails_ordenados:
            listbox.insert(tk.END, get_account_display_name(email))

        # Pré-seleciona a conta que já está no campo principal, se existir na lista
        email_atual = self.get_email()
        if email_atual and email_atual in emails_ordenados:
            listbox.select_set(emails_ordenados.index(email_atual))

        botoes_sel_frame = tk.Frame(janela)
        botoes_sel_frame.pack(fill=tk.X, padx=10, pady=(8, 0))
        tk.Button(
            botoes_sel_frame, text="Selecionar Todas",
            command=lambda: listbox.select_set(0, tk.END)
        ).pack(side=tk.LEFT, padx=(0, 5))
        tk.Button(
            botoes_sel_frame, text="Limpar Seleção",
            command=lambda: listbox.select_clear(0, tk.END)
        ).pack(side=tk.LEFT)

        def _confirmar():
            selecionados_idx = listbox.curselection()
            if not selecionados_idx:
                messagebox.showwarning("Aviso", "Selecione ao menos uma conta.", parent=janela)
                return

            emails_selecionados = [emails_ordenados[i] for i in selecionados_idx]
            janela.destroy()
            self._preparar_reembolso_contas(emails_selecionados)

        btn_frame = tk.Frame(janela)
        btn_frame.pack(fill=tk.X, padx=10, pady=15)
        tk.Button(
            btn_frame, text="Continuar", command=_confirmar,
            bg="#28a745", fg="white", font=("Arial", 10, "bold"), width=14
        ).pack(side=tk.LEFT, padx=5)
        tk.Button(
            btn_frame, text="Cancelar", command=janela.destroy,
            bg="#6c757d", fg="white", font=("Arial", 10, "bold"), width=14
        ).pack(side=tk.LEFT, padx=5)
        
    def _contar_boletos_pendentes_reembolso(self, email):
        """Conta quantos boletos pagos ainda não foram reembolsados numa conta."""
        folder = os.path.join(ACCOUNTS_DIR, email)
        db = self.carregar_db_pasta(folder)
        total = 0
        for dados in db.values():
            if (dados.get('boleto_pago') is True
                    and dados.get('rembolsado') is not True
                    and dados.get('id_payment')):
                total += 1
        return total
    
    def _pedir_tokens_reembolso_dialog(self, parent=None):
        """Janela para informar um ou mais tokens de reembolso (MP), um por linha.
        Retorna a lista de tokens ou None se cancelado."""
        parent = parent or self.root
        tokens_atuais = _obter_tokens_reembolso_mp()

        janela = tk.Toplevel(parent)
        janela.title("Token(s) de Reembolso (Mercado Pago)")
        janela.geometry("520x420")
        janela.transient(parent)
        janela.grab_set()

        if tokens_atuais:
            msg = ("Tokens atuais cadastrados (compartilhados entre TODAS as contas).\n"
                   "Edite, adicione ou remova linhas abaixo (um token por linha).")
        else:
            msg = ("Nenhum token cadastrado. Informe um ou mais tokens do Mercado Pago,\n"
                   "um por linha. Cada reembolso vai testar os tokens em ordem até acertar.")

        tk.Label(janela, text=msg, justify=tk.LEFT, wraplength=490).pack(padx=10, pady=(10, 5), anchor="w")

        text_frame = tk.Frame(janela)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10)
        scrollbar = tk.Scrollbar(text_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text_tokens = tk.Text(text_frame, wrap=tk.NONE, yscrollcommand=scrollbar.set, height=14)
        scrollbar.config(command=text_tokens.yview)
        text_tokens.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        if tokens_atuais:
            text_tokens.insert("1.0", "\n".join(tokens_atuais))

        resultado = {"tokens": None}

        def _confirmar():
            conteudo = text_tokens.get("1.0", tk.END)
            tokens = [l.strip() for l in conteudo.splitlines() if l.strip()]
            if not tokens:
                messagebox.showwarning("Aviso", "Informe ao menos um token.", parent=janela)
                return
            resultado["tokens"] = tokens
            janela.destroy()

        def _cancelar():
            janela.destroy()

        btn_frame = tk.Frame(janela)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)
        tk.Button(btn_frame, text="Salvar", command=_confirmar, bg="#28a745", fg="white",
                  font=("Arial", 10, "bold"), width=12).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Cancelar", command=_cancelar, bg="#6c757d", fg="white",
                  font=("Arial", 10, "bold"), width=12).pack(side=tk.LEFT, padx=5)

        janela.wait_window()
        return resultado["tokens"]

    def _preparar_reembolso_contas(self, emails_selecionados):
        tokens = self._pedir_tokens_reembolso_dialog(self.root)
        if tokens is None:
            self.logger("Reembolso cancelado (nenhum token informado).", "AVISO")
            return

        _salvar_tokens_reembolso_mp(tokens)

        contas_processar = []  # lista de (email, folder, tokens)
        for email in emails_selecionados:
            folder = os.path.join(ACCOUNTS_DIR, email)
            if not os.path.exists(folder):
                os.makedirs(folder, exist_ok=True)
            contas_processar.append((email, folder, tokens))

        if not contas_processar:
            self.logger("Nenhuma conta selecionada para reembolsar.", "AVISO")
            return

        # --- NOVO: conta quantos boletos estão pendentes de reembolso ---
        total_pendente = sum(
            self._contar_boletos_pendentes_reembolso(email)
            for email, _, _ in contas_processar
        )

        if total_pendente == 0:
            self.logger("Nenhum boleto pago pendente de reembolso encontrado nas contas selecionadas.", "AVISO")
            messagebox.showinfo("Reembolso", "Nenhum boleto pago pendente de reembolso foi encontrado.")
            return

        # --- NOVO: pergunta o limite de reembolsos para esta execução ---
        limite = simpledialog.askinteger(
            "Limite de Reembolsos",
            f"Total de boletos pagos pendentes de reembolso encontrados: {total_pendente}\n\n"
            "Quantos deseja reembolsar nesta execução?",
            minvalue=1,
            maxvalue=total_pendente,
            initialvalue=total_pendente,
            parent=self.root
        )
        if not limite:
            self.logger("Reembolso cancelado (nenhum limite informado).", "AVISO")
            return

        nomes = "\n".join(f"- {email}" for email, _, _ in contas_processar)
        if not messagebox.askyesno(
            "Confirmar Reembolso em Lote",
            f"Serão reembolsados até {limite} pagamento(s) de um total de {total_pendente} pendente(s), "
            f"percorrendo as contas abaixo:\n\n{nomes}\n\nDeseja continuar?"
        ):
            return

        thread = threading.Thread(
            target=self._processar_reembolsos_contas,
            args=(contas_processar, limite),
            daemon=True
        )
        thread.start()
        self.logger(
            f"Thread de reembolso em lote iniciada para {len(contas_processar)} conta(s), "
            f"limite de {limite} reembolso(s) nesta execução...",
            "INFO")


    def processar_reembolsos_pasta(self, folder, tokens, email=None, limite=None):
        """Percorre o database_vendas.json da pasta e reembolsa (via MP) os
        pagamentos pendentes, testando a lista de 'tokens' em carrossel para
        cada pagamento (útil quando há mais de uma conta/token MP)."""
        global _reembolso_indice_token_atual

        label = email or folder
        if not tokens:
            self.logger(f"Conta {label}: nenhum token de reembolso configurado.", "ERRO")
            return 0

        db = self.carregar_db_pasta(folder)
        if not db:
            self.logger(f"Conta {label}: nenhum registro encontrado para reembolsar.", "AVISO")
            return 0

        total = len(db)
        self.root.after(0, lambda: self.progress.configure(maximum=total, value=0))

        reembolsados = 0
        ja_reembolsados = 0
        sem_payment = 0
        erros = 0
        total_tokens = len(tokens)

        for idx, (order_id, dados) in enumerate(db.items(), start=1):
            self.root.after(0, lambda v=idx: self.progress.configure(value=v))

            if limite is not None and reembolsados >= limite:
                self.logger(f"Conta {label}: limite de {limite} reembolso(s) atingido. Parando o script.", "AVISO")
                break

            if dados.get('boleto_pago') is not True:
                continue
            if dados.get('rembolsado') is True:
                ja_reembolsados += 1
                continue

            id_payment = dados.get('id_payment')
            if not id_payment:
                sem_payment += 1
                continue

            sucesso = False
            ultimo_status = None
            ultimo_detalhe = None

            for offset_tk in range(total_tokens):
                idx_tk = (_reembolso_indice_token_atual + offset_tk) % total_tokens
                token = tokens[idx_tk]
                try:
                    idempotency_key = hashlib.sha256(
                        f"{order_id}-{id_payment}-{token}-{time.time()}".encode()
                    ).hexdigest()
                    headers = {
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {token}",
                        "X-Idempotency-Key": idempotency_key
                    }
                    url = f"https://api.mercadopago.com/v1/payments/{id_payment}/refunds"
                    res = SESSION.post(url, headers=headers, timeout=20)

                    if res.status_code in [200, 201]:
                        _reembolso_indice_token_atual = idx_tk
                        sucesso = True
                        break
                    else:
                        ultimo_status = res.status_code
                        ultimo_detalhe = res.text
                except Exception as e:
                    ultimo_status = "EXCEÇÃO"
                    ultimo_detalhe = str(e)

            if sucesso:
                db[order_id]['rembolsado'] = True
                db[order_id]['data_rembolso'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                self.salvar_db_pasta(folder, db)
                reembolsados += 1
                self.logger(
                    f"Conta {label} - Ordem {order_id}: reembolso do pagamento {id_payment} realizado com sucesso "
                    f"(token {(_reembolso_indice_token_atual % total_tokens) + 1}/{total_tokens}). "
                    f"({reembolsados}{f'/{limite}' if limite is not None else ''})",
                    "SUCESSO"
                )
            else:
                erros += 1
                self.logger(
                    f"Conta {label} - Ordem {order_id}: falha ao reembolsar pagamento {id_payment} em todos os "
                    f"{total_tokens} token(s) testados (último erro: {ultimo_status} - {ultimo_detalhe}).",
                    "ERRO"
                )

            time.sleep(0.3)

        self.salvar_db_pasta(folder, db)
        self.logger(
            f"Conta {label}: reembolso finalizado. Reembolsados agora: {reembolsados} | "
            f"Já estavam reembolsados: {ja_reembolsados} | "
            f"Sem id_payment: {sem_payment} | Erros: {erros}",
            "SUCESSO"
        )
        return reembolsados
        
    
        
    def iniciar_resposta_duvidas(self):
        """Método acionado pelo botão para iniciar o processo em uma Thread separada"""
        # Cria uma thread para não travar a interface do Tkinter
        thread = threading.Thread(target=self.processar_responder_duvidas, daemon=True)
        thread.start()

    def processar_responder_duvidas(self):
        """Função principal que busca, filtra, envia para a IA e responde as perguntas"""
        folder = self.get_pasta_conta()
        if not folder:
            return

        config = self.carregar_config_cliente(folder)
        if not config:
            return

        token = self.get_token_ml(folder)
        if not token:
            return

        # 1. Tenta ler o arquivo de script da IA, se não existir, cria um padrão
        try:
            script_ia = self.carregar_script_ia_question(folder, True)
        except Exception as e:
            self.logger(f"Arquivo não encontrado. ERRO: {e}", "AVISO")

        self.logger("Iniciando busca de perguntas no Mercado Livre...", "INFO")

        # 2. Configurações da API do Mercado Livre
        seller_id = config.get("ML_SELLER_ID")
        if not seller_id:
            self.logger("SELLER_ID não encontrado na configuração da conta. Por favor, adicione o SELLER_ID no config_conta.json.", "ERRO")
            return

        url_resposta = "https://api.mercadolibre.com/answers"

        # IMPORTANTE: Ajuste 'self.ml_access_token' para a sua variável real de Token do Mercado Livre
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        # Variáveis de controle da paginação
        todas_perguntas = []
        limit = 50
        offset = 0

        try:
            # Bloco de busca em lote (50 em 50)
            while True:
                url_busca = f"https://api.mercadolibre.com/questions/search?seller_id={seller_id}&api_version=4&limit={limit}&offset={offset}"

                response = SESSION.get(url_busca, headers=headers)

                if response.status_code != 200:
                    self.logger(f"Erro ao buscar perguntas no offset {offset} (Status {response.status_code}): {response.text}", "ERRO")
                    break

                dados = response.json()
                perguntas_pagina = dados.get("questions", [])
                total_total = dados.get("total", 0)

                if not perguntas_pagina:
                    break  # Se a página vier vazia, encerra o loop

                # Junta as perguntas dessa página na lista principal
                todas_perguntas.extend(perguntas_pagina)
                self.logger(f"Baixadas {len(todas_perguntas)} de {total_total} perguntas totais...", "INFO")

                # Incrementa o offset para a próxima página
                offset += limit

                # Condição de parada: se o próximo offset atingiu ou passou o total geral
                if offset >= total_total:
                    break

                # Pausa rápida de segurança para evitar gargalo de requisições (rate limit)
                time.sleep(0.3)

            # Filtrar apenas as não respondidas ("status": "UNANSWERED")
            perguntas_nao_respondidas = [p for p in todas_perguntas if p.get("status") == "UNANSWERED"]

            self.logger(f"Encontrada(s) {len(perguntas_nao_respondidas)} pergunta(s) sem resposta.", "INFO")

            if not perguntas_nao_respondidas:
                self.logger("Perfeito! Nenhuma pergunta pendente de resposta.", "SUCESSO")
                return

            # 3. Processar cada pergunta encontrada
            for pergunta in perguntas_nao_respondidas:
                question_id = pergunta.get("id")
                prompt_usuario = pergunta.get("text")  # Pega a pergunta no 'text'

                self.logger(f"Enviando pergunta para a IA", "INFO")

                palavrasProibidas = ["golpe", "opnião", "avaliação"]
                # verificar prompt_usuario contem as palavras do array
                if any(palavra in prompt_usuario for palavra in palavrasProibidas):
                    self.logger(f"Pergunta ID {question_id} contém palavras proibidas. Pulando resposta.", "AVISO")
                    continue

                # Chama a IA exatamente como você solicitou
                resposta_ia = gerar_resposta_groq(script_ia, prompt_usuario).strip('"')

                if not resposta_ia:
                    self.logger(f"IA retornou resposta vazia para a pergunta ID {question_id}. Pulando resposta.", "AVISO")
                    break

                # 4. Envia a resposta de volta para o Mercado Livre
                payload_resposta = {
                    "question_id": question_id,
                    "text": resposta_ia
                }

                res_post = SESSION.post(url_resposta, json=payload_resposta, headers=headers)

                if res_post.status_code == 201 or res_post.status_code == 200:
                    self.logger(f"Pergunta ID {question_id} respondida com sucesso!", "SUCESSO")
                else:
                    self.logger(f"Falha ao enviar resposta para ID {question_id}: {res_post.text}", "ERRO")

                # Um pequeno delay entre as respostas para evitar bloqueios por rate limit
                time.sleep(1)

            self.logger(f"Processo de responder dúvidas concluído.", "SUCESSO")
        except Exception as e:
            self.logger(f"Erro geral no processo de responder dúvidas: {e}", "ERRO")

    def _obter_mensagens_reclamacao_ia(self, claim_id, seller_id, headers):
        url = f"https://api.mercadolibre.com/post-purchase/v1/claims/{claim_id}/messages"
        res = SESSION.get(url, headers=headers, timeout=15)
        if res.status_code != 200:
            self.logger(f"Erro ao buscar mensagens da reclamação {claim_id}: {res.status_code}", "ERRO")
            return []

        dados = res.json()
        if isinstance(dados, dict):
            mensagens_api = dados.get("messages") or dados.get("data") or []
        else:
            mensagens_api = dados

        mensagens = []
        for msg in mensagens_api:
            if not isinstance(msg, dict):
                continue
            sender = msg.get("sender") if isinstance(msg.get("sender"), dict) else {}
            sender_id = sender.get("id") or sender.get("user_id") or msg.get("sender_id")
            sender_role = msg.get("sender_role") or msg.get("role") or sender.get("role")
            sender_role_text = str(sender_role or "").lower()
            mensagens.append({
                "origem": f"Reclamação ({claim_id})",
                "texto": msg.get("message") or msg.get("text"),
                "data": msg.get("date_created") or msg.get("message_date"),
                "sender_id": sender_id,
                "sender_role": sender_role,
                "is_seller": str(sender_id) == str(seller_id) or sender_role_text in ["respondent", "seller"],
            })

        return mensagens

    def _obter_mensagens_chat_comum_ia(self, order_id, seller_id, headers):
        url = f"https://api.mercadolibre.com/messages/packs/{order_id}/sellers/{seller_id}?tag=post_sale"
        res = SESSION.get(url, headers=headers, timeout=15)
        if res.status_code != 200:
            self.logger(f"Erro ao buscar chat comum {order_id}: {res.status_code}", "ERRO")
            return [], []

        dados = res.json()
        claim_ids = dados.get("conversation_status", {}).get("claim_ids", []) or []
        mensagens = []

        for msg in dados.get("messages", []):
            if not isinstance(msg, dict):
                continue
            sender_id = (
                msg.get("from", {}).get("user_id") or
                msg.get("sender", {}).get("user_id") or
                msg.get("sender_id")
            )
            mensagens.append({
                "origem": "Chat Comum",
                "texto": msg.get("text"),
                "data": msg.get("message_date"),
                "sender_id": sender_id,
                "is_seller": str(sender_id) == str(seller_id),
            })

        return mensagens, claim_ids

    def _montar_parametros_dinamicos(self, dados_pedido, tem_reclamacao):
        """
        Monta o bloco de PARAMETROS dinâmico a partir do que está salvo no banco
        para aquela ordem, para que a IA (única, via scriptIAcomum.txt) saiba em
        que etapa da conversa o pedido está.
        """
        def _bool(valor):
            return "true" if bool(valor) else "false"

        linhas = [
            f"conversa_com_reclamação = {_bool(tem_reclamacao)}.",
            f"solicitado = {_bool(dados_pedido.get('solicitado'))}.",
            f"rastreio_enviado = {_bool(dados_pedido.get('rastreio_enviado'))}.",
            f"boleto_autorizado_msg = {_bool(dados_pedido.get('boleto_autorizado_msg'))}.",
            f"cliente_autorizou = {_bool(dados_pedido.get('cliente_autorizou'))}.",
            f"boleto_enviado = {_bool(dados_pedido.get('boleto_enviado'))}.",
            f"boleto_pago = {_bool(dados_pedido.get('boleto_pago'))}.",
        ]
        return "\n        ".join(linhas)

    def gerar_resposta_para_cliente(self, mensagem_cliente, script_ia, parametros):
        """
        Gera a resposta final da IA para o cliente, injetando os PARAMETROS
        dinâmicos (etapa atual da conversa) junto com o script único
        (scriptIAcomum.txt) antes da mensagem do cliente.
        """
        prompt_usuario = (
            "PARAMETROS:\n"
            f"        {parametros}\n"
            "Mensagem do cliente:\n"
            f"{mensagem_cliente}"
        )
        try:
            resposta_ia = gerar_resposta_groq(script_ia, prompt_usuario)
        except GroqEsgotadoError as exc:
            self.logger(f"Groq esgotada, usando Gemini como IA reserva: {exc}", "AVISO")
            resposta_ia = gerar_resposta_gemini(script_ia, prompt_usuario)

        return resposta_ia.strip('"')

    def _responder_com_ia_unificada(self, order_id, buyer_id, conversa, headers, seller_id, token, db,
                                     tem_reclamacao=False, claim_id=None):
        """
        Ponto único de resposta por IA (chat comum ou reclamação): usa sempre o
        mesmo script (scriptIAcomum.txt), primeiro pega as últimas mensagens do
        cliente após a minha última resposta, checa com precisa_responder_groq se
        realmente precisa responder, e só então monta os PARAMETROS dinâmicos
        (puxados do banco daquela ordem) e chama a IA para gerar a resposta.
        """
        script_ia = getattr(self, "ia_comum_script", "").strip()
        if not script_ia:
            self.logger("Script único da IA (scriptIAcomum.txt) não carregado. A resposta foi cancelada.", "ERRO")
            return False

        mensagens_cliente = self._mensagens_cliente_apos_ultima_resposta(conversa)
        if not mensagens_cliente:
            self.logger(f"Ordem {order_id}: nenhuma mensagem nova da cliente após a última resposta.", "AVISO")
            return False

        texto_cliente = "\n\n".join(f"Cliente: {texto}" for texto in mensagens_cliente)

        chave_conversa = hashlib.sha256(texto_cliente.encode("utf-8")).hexdigest()
        dados_pedido = db.setdefault(order_id, {})
        if dados_pedido.get("ultima_ia_chave") == chave_conversa:
            self.logger(f"Ordem {order_id}: IA já respondeu essa última sequência de mensagens.", "AVISO")
            return False

        try:
            precisa = precisa_responder_groq(texto_cliente)
        except Exception as e:
            self.logger(f"Ordem {order_id}: erro ao classificar necessidade de resposta: {e}", "ERRO")
            return False

        if not precisa:
            self.logger(f"Ordem {order_id}: mensagem do cliente não exige resposta (agradecimento/despedida).", "INFO")
            dados_pedido["ultima_ia_chave"] = chave_conversa
            self.salvar_db(db)
            return False

        parametros = self._montar_parametros_dinamicos(dados_pedido, tem_reclamacao)

        try:
            self.logger(f"Ordem {order_id}: enviando mensagens para a IA (reclamação={tem_reclamacao})...", "INFO")
            resposta_ia = self.gerar_resposta_para_cliente(texto_cliente, script_ia, parametros)
        except Exception as e:
            self.logger(f"Ordem {order_id}: erro ao chamar IA: {e}", "ERRO")
            return False

        if not resposta_ia:
            self.logger(f"TENTATIVA 2 Ordem {order_id}: enviando mensagens para a IA (reclamação={tem_reclamacao})...", "INFO")
            resposta_ia = self.gerar_resposta_para_cliente(texto_cliente, script_ia, parametros)
            if not resposta_ia:
                self.logger(f"Ordem {order_id}: IA retornou resposta vazia nas duas tentativas.", "ERRO")
                return False
        
        return True
        envio = self.enviarMSG(order_id, buyer_id, resposta_ia, headers, seller_id, tem_reclamacao, claim_id)
        if envio:
            dados_pedido["ultima_ia_chave"] = chave_conversa
            dados_pedido["ultima_ia_resposta"] = resposta_ia
            dados_pedido["data_ultima_ia"] = datetime.now().strftime("%d/%m/%Y %H:%M")
            self.salvar_db(db)
            self.logger(f"Ordem {order_id}: resposta da IA enviada com sucesso.", "SUCESSO")
            return True

        self.logger(f"Ordem {order_id}: falha ao enviar resposta da IA.", "ERRO")
        return False

    def responder_chat_comum_com_ia(self, order_id, buyer_id, headers, seller_id, token, db, reclamacao, claim_id=None):
        """
        Busca TODAS as conversas do pedido (chat comum + reclamação, quando houver)
        através de obter_conversa_completa e envia tudo para o cérebro único da IA.
        """
        conversa = self.obter_conversa_completa(order_id, order_id, seller_id, token, claim_id=claim_id)

        return self._responder_com_ia_unificada(
            order_id, buyer_id, conversa, headers, seller_id, token, db,
            tem_reclamacao=reclamacao, claim_id=claim_id
        )
    
    def _verificar_autorizacao_via_ia(self, order_id, mensagens_cliente):
        """
        Usa a IA para decidir, com base nas mensagens do cliente enviadas após a
        solicitação de autorização (DIGITE 1), se ele deseja receber o boleto.
        Só é chamada quando não foi possível identificar autorização pelo '1'
        isolado nem pela mensagem manual de liberação.
        Retorna True/False.
        """
        if not mensagens_cliente:
            return False

        texto_cliente = "\n".join(f"- {m}" for m in mensagens_cliente)

        system_text = (
            "Você é um classificador de intenção em um chat de atendimento ao cliente.\n"
            "O vendedor solicitou que o cliente confirme se deseja pagar a taxa de frete/envio para gerar o boleto.\n\n"
            "Análise das mensagens do cliente:\n"
            "Responda 'true' se o cliente demonstrar intenção de pagar ou quiser saber como pagar a taxa/frete "
            "(ex: 'vou pagar', 'como faço pra pagar', 'manda o boleto', 'quero pagar').\n"
            "Responda 'false' se o cliente recusar, disser que já pagou, pedir cancelamento ou se o texto for incerto/confuso.\n\n"
            "Responda EXCLUSIVAMENTE com 'true' ou 'false'."
        )
        user_text = f"Mensagens do cliente após a solicitação:\n{texto_cliente}"

        try:
            resposta = gerar_resposta_groq(system_text, user_text)
        except Exception as e:
            self.logger(f"Ordem {order_id}: erro ao consultar IA para verificar autorização: {e}", "ERRO")
            return False

        resposta_normalizada = (resposta or "").strip().lower()
        resultado = resposta_normalizada.startswith("true") or resposta_normalizada.startswith("sim")

        self.logger(
            f"Ordem {order_id}: IA analisou {len(mensagens_cliente)} mensagem(ns) do cliente e "
            f"retornou '{resposta_normalizada}' -> autorizado={resultado}",
            "INFO"
        )
        return resultado

    def responder_reclamacao_com_ia(self, order_id, buyer_id, claim_id, headers, seller_id, token, db):
        conversa = self._obter_mensagens_reclamacao_ia(claim_id, seller_id, headers)
        if not conversa:
            conversa = self.obter_conversa_completa(order_id, order_id, seller_id, token, claim_id=claim_id)

        mensagens_cliente = self._mensagens_cliente_apos_ultima_resposta(conversa)
        texto_cliente = "\n\n".join(f"Cliente: {texto}" for texto in mensagens_cliente)

        # Exceção de negócio (fora da IA): resposta fixa quando o cliente abre a
        # reclamação padrão do Mercado Livre "Tive um problema com a compra e preciso de ajuda".
        if "Tive um problema com a compra e preciso de ajuda" in texto_cliente:
            chave_conversa = hashlib.sha256(texto_cliente.encode("utf-8")).hexdigest()
            dados_pedido = db.setdefault(order_id, {})
            if dados_pedido.get("ultima_ia_chave") == chave_conversa:
                self.logger(f"Ordem {order_id}: já respondida essa última sequência de mensagens.", "AVISO")
                return False

            resposta_ia = """Olá! Entendo perfeitamente e estou aqui para ajudar você a resolver isso da melhor forma.

            Como o seu pedido é importado direto da fábrica, nos raros casos em que a Receita Federal aplica alguma taxa, ficando entre R$ 220 e R$ 300.

            Para que você não saia prejudicado, já garantimos para você a montagem totalmente gratuita do seu móvel, além de brindes especiais: 3 vasos de cerâmica decorativos

            Conte comigo para acompanhar todo o processo até a entrega na sua casa.

            Atenciosamente,
            Living Shop"""
            envio = self.enviarMSG(order_id, buyer_id, resposta_ia, headers, seller_id, True, claim_id)
            if envio:
                dados_pedido["ultima_ia_chave"] = chave_conversa
                dados_pedido["ultima_ia_resposta"] = resposta_ia
                dados_pedido["data_ultima_ia"] = datetime.now().strftime("%d/%m/%Y %H:%M")
                self.salvar_db(db)
                self.logger(f"Ordem {order_id}: resposta enviada com sucesso.", "SUCESSO")
                return True
            return False

        return self._responder_com_ia_unificada(
            order_id, buyer_id, conversa, headers, seller_id, token, db,
            tem_reclamacao=True, claim_id=claim_id
        )

    def parar_processamento_urgente(self):
        self.stop_event.set()
        self.logger("STOP URGENTE acionado! O processamento será interrompido assim que possível.", "ERRO")
        if hasattr(self, 'btn_stop'):
            self.btn_stop.config(text="PARANDO...", state=tk.DISABLED, bg="#880000")

    def _check_stop(self):
        if self.stop_event.is_set():
            raise ProcessamentoInterrompido()

    def reset_stop_event(self):
        self.stop_event.clear()
        if hasattr(self, 'btn_stop'):
            self.btn_stop.config(text="STOP URGENTE", state=tk.DISABLED, bg="#FF0000")

    def logger(self, msg, tag="INFO"):
        # 1. Tentar configurar o logging para a pasta da conta atual
        # (leitura/gravação em arquivo é segura de ser chamada de qualquer thread)
        email = self.var_email.get().strip()
        if email:
            # Caminho: contas/email@clinte.com/logs/
            log_dir = os.path.join(ACCOUNTS_DIR, email, 'logs')
            if not os.path.exists(log_dir):
                os.makedirs(log_dir)
            
            log_path = os.path.join(log_dir, f"log_{datetime.now().strftime('%Y-%m-%d')}.txt")
            
            file_logger = logging.getLogger(email)
            if not file_logger.handlers:
                file_handler = logging.FileHandler(log_path, encoding='utf-8')
                formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
                file_handler.setFormatter(formatter)
                file_logger.addHandler(file_handler)
                file_logger.setLevel(logging.INFO)

            if tag == "ERRO":
                file_logger.error(msg)
            elif tag == "ALERTA":
                file_logger.warning(msg)
            else:
                file_logger.info(msg)

        # 2. Atualização visual no ScrolledText (Tkinter)
        # IMPORTANTE: widgets do Tkinter só podem ser mexidos com segurança pela
        # thread principal. Como o logger() é chamado de threads de processamento
        # em segundo plano, se não estivermos na thread principal, agendamos a
        # atualização visual via self.root.after(0, ...) em vez de mexer no
        # widget diretamente. Isso evita o "congelamento"/"não está respondendo"
        # da interface quando há muitos logs em sequência durante um processamento.
        if threading.current_thread() is threading.main_thread():
            self._atualizar_log_widget(msg, tag)
        else:
            try:
                self.root.after(0, self._atualizar_log_widget, msg, tag)
            except Exception:
                # Se a janela já não existe mais (encerrando o app), apenas ignora.
                pass

    def _atualizar_log_widget(self, msg, tag="INFO"):
        """Só deve ser chamada pela thread principal (via logger(), diretamente
        ou agendada com self.root.after). Faz a escrita de fato no ScrolledText."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        display_tag = "ERROR" if tag == "ERRO" else tag
        tag_styles = {
            "INFO": "log_info",
            "AVISO": "log_aviso",
            "ALERTA": "log_aviso",
            "ERROR": "log_error",
            "ERRO": "log_error",
            "SUCESSO": "log_sucesso",
        }
        log_style = tag_styles.get(display_tag)

        # --- verifica se o usuário já estava com a rolagem no final ---
        # yview() retorna (topo_visivel, fim_visivel) em fração de 0 a 1.
        # Se o fim visível está bem próximo de 1.0, consideramos que ele
        # estava acompanhando o log em tempo real.
        try:
            estava_no_fim = self.log.yview()[1] >= 0.999
        except Exception:
            estava_no_fim = True

        self.log.insert(tk.END, f"[{timestamp}] ")
        self.log.insert(tk.END, f"[{display_tag}]", log_style)
        self.log.insert(tk.END, " ")

        pos = 0
        for match in re.finditer(r"(\bordem\s+)(\d+)", msg, flags=re.IGNORECASE):
            self.log.insert(tk.END, msg[pos:match.start()])
            self.log.insert(tk.END, match.group(1), "log_ordem_label")
            self.log.insert(tk.END, match.group(2), "log_ordem")
            pos = match.end()
        self.log.insert(tk.END, msg[pos:])
        self.log.insert(tk.END, "\n")

        # --- só desce automaticamente se o usuário já estava no final ---
        if estava_no_fim:
            self.log.see(tk.END)

        # Atualiza só o desenho pendente (mais leve que update() completo).
        # Como agora estamos sempre na thread principal aqui, isso é seguro.
        try:
            self.root.update_idletasks()
        except Exception:
            pass
    # --- CAPTURA DE NÚMEROS DE WHATSAPP DAS CONVERSAS ---
    def capturar_wpp_thread(self):
        """Inicia a captura de WPP em uma thread separada."""
        folder = self.get_pasta_conta()
        if not folder:
            messagebox.showerror("Erro", "Selecione uma conta primeiro.")
            return
        
        thread = threading.Thread(target=self.capturar_wpp, daemon=True)
        thread.start()
        self.logger("Thread de captura de WPP iniciada...")

    def capturar_wpp(self):
        """
        Captura números de telefone das conversas para pedidos solicitados.
        Processa apenas pedidos que:
        - Têm 'solicitado' = True
        - NÃO têm 'numero_extraido' = True
        
        Após extrair, envia mensagem apropriada:
        - Se rastreio NÃO foi enviado: agradecimento + info entrega
        - Se rastreio FOI enviado: apenas mensagem cobrando número
        """
        folder = self.get_pasta_conta()
        if not folder:
            return
        
        token = self.get_token_ml(folder)
        if not token:
            return
        
        config = self.carregar_config_cliente(folder)
        if not config:
            return
        
        db = self.carregar_db()
        if not db:
            self.logger("Nenhum banco de dados encontrado.", "AVISO")
            return
        
        headers = {
            "Authorization": f"Bearer {token}"
        }
        
        processados = 0
        extraidos = 0
        
        try:
            # Contar total de pedidos a processar
            pedidos_processar = [
                order_id for order_id, dados in db.items()
                if dados.get('solicitado') and not dados.get('numero_extraido')
            ]
            
            total = len(pedidos_processar)
            self.progress["maximum"] = total
            self.progress["value"] = 0
            
            if total == 0:
                self.logger("Nenhum pedido para capturar WPP (todos já têm número extraído ou não foram solicitados).", "AVISO")
                return
            
            self.logger(f"Iniciando captura de WPP para {total} pedido(s)...")
            
            for idx, order_id in enumerate(pedidos_processar):
                dados_pedido = db[order_id]
                buyer_id = dados_pedido.get('buyer_id', '')
                claim_id = dados_pedido.get('claim_id')
                processados += 1
                
                # Atualizar progress bar
                self.root.after(0, lambda v=idx+1: self.progress.configure(value=v))
                
                try:
                    # Obter conversa completa
                    conversaCompleta = self.obter_conversa_completa(order_id, order_id, config['ML_SELLER_ID'], token)
                    
                    numero_encontrado = False
                    
                    # Procurar por número de telefone na conversa
                    for m in conversaCompleta:
                        texto = m.get('texto', '')
                        # Regex robusto para capturar vários formatos de telefone BR
                        match = re.search(r'(?:\+?55\s?)?\(?(\d{2})\)?\s*(9)?\s*(\d{4,5})[\s.-]?(\d{4})', texto)
                        if match:
                            zap_bruto = "".join(g for g in match.groups() if g is not None)
                            zap = "".join(re.findall(r'\d+', zap_bruto))
                            
                            # Salvar número extraído no DB
                            db[order_id]['zap_extraido'] = zap
                            db[order_id]['numero_extraido'] = True
                            self.salvar_db(db)
                            
                            self.logger(f"Número extraído para ordem {order_id}: {zap}")
                            numero_encontrado = True
                            extraidos += 1
                            
                            # Enviar mensagem apropriada
                            if not dados_pedido.get('rastreio_enviado'):
                                # Caso 1: Rastreio NÃO foi enviado
                                text = "Olá! recebemos seu telefone. Obrigado! \nVamos dar continuidade ao processo de envio do seu pedido. \nAssim que o código de rastreio estiver disponível, enviaremos para você acompanhar a entrega. 😉"
                                envio = self.enviarMSG(order_id, buyer_id, text, headers, config['ML_SELLER_ID'], 
                                                     bool(claim_id), claim_id)
                                if envio:
                                    self.logger(f"Mensagem de agradecimento enviada para {order_id}.")
                                else:
                                    self.logger(f"Falha ao enviar mensagem de agradecimento para {order_id}.", "AVISO")
                            elif dados_pedido.get('rastreio_enviado') and not dados_pedido.get('boleto_enviado'):
                                # Caso 2: Rastreio JÁ foi enviado
                                text = "Olá! recebemos seu telefone. Obrigado! \nVamos dar continuidade ao processo de envio do seu pedido."
                                envio = self.enviarMSG(order_id, buyer_id, text, headers, config['ML_SELLER_ID'], 
                                                     bool(claim_id), claim_id)
                                if envio:
                                    self.logger(f"Mensagem enviada para {order_id}.")
                                else:
                                    self.logger(f"Falha ao enviar mensagem para {order_id}.", "AVISO")
                            
                            break  # Sair do loop assim que encontrar um número
                    
                    if not numero_encontrado:
                        # Se rastreio foi enviado e número não foi extraído, cobrar uma vez
                        if dados_pedido.get('rastreio_enviado') and not dados_pedido.get('numero_extraido') and not dados_pedido.get('boleto_enviado'):
                            tentativas_cobranca = dados_pedido.get('tentativas_cobranca_wpp', 0)
                            
                            # Cobrar apenas uma vez pelo botão CAPTURAR WPP
                            if tentativas_cobranca < 1:
                                text = "Olá! Não recebemos seu telefone.\nA transportadora precisa para avisar as atualizações da entrega."
                                envio = self.enviarMSG(order_id, buyer_id, text, headers, config['ML_SELLER_ID'], 
                                                     bool(claim_id), claim_id)
                                if envio:
                                    db[order_id]['tentativas_cobranca_wpp'] = tentativas_cobranca + 1
                                    self.salvar_db(db)
                                    self.logger(f"Mensagem de cobrança de número enviada para {order_id}.")
                                else:
                                    self.logger(f"Falha ao enviar mensagem de cobrança para {order_id}.", "AVISO")
                            else:
                                self.logger(f"Ordem {order_id}: Limite de cobrança de número atingido (1x).")
                        else:
                            self.logger(f"Nenhum número encontrado na conversa da ordem {order_id}.")
                
                except Exception as e:
                    self.logger(f"Erro ao processar ordem {order_id}: {str(e)}", "ERRO")
                    
            # Salvar DB final
            self.salvar_db(db)
            self.logger(f"Captura de WPP finalizada. Processados: {processados}, Extraídos: {extraidos}")
            
        except Exception as e:
            self.logger(f"Erro geral na captura de WPP: {str(e)}", "ERRO")
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
        thread = threading.Thread(target=self.atualizar_blt_pagos, args=())
        thread.daemon = True
        thread.start()
        self.logger("Thread de atualização de boletos pagos iniciada em segundo plano...")
        
            
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
                        response = SESSION.get(url, headers=headers)
                        
                        if response.status_code == 200:
                            encontrado_em_algum_token = True
                            resultado = response.json().get('status')
                            resultadoDetail = response.json().get('status_detail')
                            if resultado in ['approved', 'refunded']: #or resultadoDetail in ['by_collector']:
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
                        response = SESSION.get(url, headers=headers)

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
            
    def atualizar_pix_pagos_thread(self):
        folder = self.get_pasta_conta()
        if not folder:
            return
        thread = threading.Thread(target=self.atualizar_pix_pagos, daemon=True)
        thread.start()
        self.logger("Thread de atualização de PIX pagos iniciada em segundo plano...")    
     
    def atualizar_pix_pagos(self):
        folder = self.get_pasta_conta()
        if not folder:
            return

        token = self.get_token_ml(folder)
        if not token:
            return

        config = self.carregar_config_cliente(folder)
        if not config:
            return

        db = self.carregar_db()
        if not db:
            self.logger("Nenhum banco de dados encontrado.", "AVISO")
            return

        seller_id = config.get('ML_SELLER_ID')
        if not seller_id:
            self.logger("Seller ID não encontrado na configuração.", "ERRO")
            return

        frase_confirmacao = "Recebemos o pagamento da Taxa."

        pedidos_pix = [
            order_id for order_id, dados in db.items()
            if dados.get('metodo_cobro_dobro') == 'pix' and not dados.get('pago_dobro_pix')
        ]

        total = len(pedidos_pix)
        if total == 0:
            self.logger("Nenhuma venda com cobrança dobrada via PIX pendente de confirmação.", "AVISO")
            return

        self.root.after(0, lambda: self.progress.configure(maximum=total, value=0))
        self.logger(f"Iniciando verificação de {total} venda(s) com cobrança PIX pendente...", "INFO")

        atualizados = 0
        erros = 0

        for idx, order_id in enumerate(pedidos_pix, start=1):
            self.root.after(0, lambda v=idx: self.progress.configure(value=v))

            dados_pedido = db.get(order_id, {})
            claim_id = dados_pedido.get('claim_id')

            try:
                conversa = self.obter_conversa_completa(order_id, order_id, seller_id, token, claim_id=claim_id)

                encontrado = self.mensagem_existe_no_historico(frase_confirmacao, conversa)

                if encontrado:
                    db[order_id]['pago_dobro_pix'] = True
                    db[order_id]['data_pago_dobro_pix'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                    self.salvar_db(db)
                    atualizados += 1
                    self.logger(f"Ordem {order_id}: pagamento PIX confirmado no chat.", "SUCESSO")
                else:
                    self.logger(f"Ordem {order_id}: frase de confirmação não encontrada ainda.", "AVISO")

            except Exception as e:
                erros += 1
                self.logger(f"Erro ao verificar chat da ordem {order_id}: {e}", "ERRO")

            time.sleep(0.3)

        self.logger(
            f"Atualização de PIX pagos finalizada. Confirmados: {atualizados} | Erros: {erros} | Total verificado: {total}",
            "SUCESSO"
        )        
            
    def _processar_reembolsos_contas(self, contas_processar, limite=None):
        total_realizados = 0
        for email, folder, tokens in contas_processar:
            if limite is not None and total_realizados >= limite:
                self.logger(
                    f"Limite de {limite} reembolso(s) atingido. Parando antes da conta {email}.",
                    "AVISO"
                )
                break

            self.logger(f"=== Iniciando reembolso da conta {email} ===", "INFO")
            try:
                restante = None if limite is None else (limite - total_realizados)
                realizados_conta = self.processar_reembolsos_pasta(folder, tokens, email, limite=restante)
                total_realizados += (realizados_conta or 0)
            except Exception as e:
                self.logger(f"Conta {email}: erro geral no processamento de reembolso: {e}", "ERRO")        

    
    def _perguntar_reembolso_automatico(self, usar_thread=True):
        """Pergunta se deseja reembolsar automaticamente e, se sim, dispara
        o reembolso (sem limite) apenas para a conta atualmente selecionada.
        usar_thread=False roda de forma SÍNCRONA (necessário no modo
        agendamento, pois o processo é encerrado logo em seguida e mataria
        uma thread daemon antes dela terminar)."""
        email = self.get_email()
        if not email:
            return

        self.root.lift()
        self.root.focus_force()

        tokens = _obter_tokens_reembolso_mp()
        if not tokens:
            self.logger("Nenhum token de reembolso cadastrado. Reembolso automático cancelado.", "AVISO")
            return

        folder = os.path.join(ACCOUNTS_DIR, email)
        if not os.path.exists(folder):
            os.makedirs(folder, exist_ok=True)

        total_pendente = self._contar_boletos_pendentes_reembolso(email)
        if total_pendente == 0:
            self.logger(f"Conta {email}: nenhum boleto pago pendente de reembolso encontrado.", "AVISO")
            return

        contas_processar = [(email, folder, tokens)]

        if usar_thread:
            thread = threading.Thread(
                target=self._processar_reembolsos_contas,
                args=(contas_processar, None),
                daemon=True
            )
            thread.start()
            self.logger(
                f"Reembolso automático iniciado para a conta {email} "
                f"({total_pendente} boleto(s) pago(s) pendente(s) de reembolso, sem limite).",
                "INFO"
            )
        else:
            self.logger(
                f"Reembolso automático (síncrono) iniciado para a conta {email} "
                f"({total_pendente} boleto(s) pago(s) pendente(s) de reembolso, sem limite).",
                "INFO"
            )
            self._processar_reembolsos_contas(contas_processar, None)  # bloqueia até terminar
            self.logger(f"Reembolso automático (síncrono) finalizado para a conta {email}.", "INFO")
    # --- LÓGICA DE AUTENTICAÇÃO ---
    def fluxo_autorizacao_ml(self):
        folder = self.get_pasta_conta()
        if not folder:
            return

        config_path = os.path.join(folder, 'config_conta.json')
        if not os.path.exists(config_path):
            config = {
                "ML_CLIENT_ID": "",
                "ML_CLIENT_SECRET": "",
                "ML_REDIRECT_URI": "https://engoo.com/app/daily-news",
                "ML_SELLER_ID": "",
                "TOKEN_MP": ""
            }
            self.salvar_config_cliente(folder, config)
            self.logger(f"Arquivo config_conta.json criado em {folder}. Preencha os dados ML.", "INFO")
        else:
            config = self.carregar_config_cliente(folder)
            if not config:
                return
            config.setdefault("ML_CLIENT_ID", "")
            config.setdefault("ML_CLIENT_SECRET", "")
            config.setdefault("ML_REDIRECT_URI", "https://engoo.com/app/daily-news")
            config.setdefault("ML_SELLER_ID", "")
            config.setdefault("TOKEN_MP", "")

        client_id = simpledialog.askstring(
            "ML Client ID",
            "Informe o ML_CLIENT_ID:",
            parent=self.root,
            initialvalue=config.get("ML_CLIENT_ID", "")
        )
        if not client_id:
            self.logger("Autorização ML cancelada: ML_CLIENT_ID não informado.", "ERRO")
            return

        client_secret = simpledialog.askstring(
            "ML Client Secret",
            "Informe o ML_CLIENT_SECRET:",
            parent=self.root,
            initialvalue=config.get("ML_CLIENT_SECRET", "")
        )
        if not client_secret:
            self.logger("Autorização ML cancelada: ML_CLIENT_SECRET não informado.", "ERRO")
            return

        config["ML_CLIENT_ID"] = client_id.strip()
        config["ML_CLIENT_SECRET"] = client_secret.strip()
        if not config.get("ML_REDIRECT_URI"):
            config["ML_REDIRECT_URI"] = "https://engoo.com/app/daily-news"
        self.salvar_config_cliente(folder, config)

        redirect_uri = config["ML_REDIRECT_URI"]
        auth_url = (
            f"https://auth.mercadolibre.com/authorization?response_type=code"
            f"&client_id={config['ML_CLIENT_ID']}"
            f"&redirect_uri={redirect_uri}"
        )
        webbrowser.open(auth_url)
        self.logger("Navegador aberto. Autorize e cole o código 'TG-...' abaixo.", "INFO")

        self.root.lift()
        self.root.focus_force()
        codigo = simpledialog.askstring("OAuth ML", "Insira o código gerado na URL (code=...):", parent=self.root)
        if not codigo:
            self.logger("Autorização ML cancelada: código não informado.", "ERRO")
            return

        token_url = "https://api.mercadolibre.com/oauth/token"
        token_payload = {
            'grant_type': 'authorization_code',
            'client_id': config['ML_CLIENT_ID'],
            'client_secret': config['ML_CLIENT_SECRET'],
            'code': codigo,
            'redirect_uri': redirect_uri
        }

        try:
            res = SESSION.post(token_url, data=token_payload, timeout=15)
        except Exception as e:
            self.logger(f"Erro na requisição de token ML: {e}", "ERRO")
            return

        if res.status_code != 200:
            self.logger(f"Erro na troca de código: {res.status_code} - {res.text}", "ERRO")
            return

        token_data = res.json()
        self.auth_ml.salvar_tokens(token_data, folder)
        self.logger("Tokens salvos com sucesso!", "SUCESSO")

        access_token = token_data.get('access_token')
        if not access_token:
            self.logger("Não foi possível obter access_token do Mercado Livre.", "ERRO")
            return

        headers = {
            "Authorization": f"Bearer {access_token}"
        }
        user_url = "https://api.mercadolibre.com/users/me"

        try:
            user_res = SESSION.get(user_url, headers=headers, timeout=15)
        except Exception as e:
            self.logger(f"Erro ao buscar ML_SELLER_ID: {e}", "ERRO")
            return

        if user_res.status_code != 200:
            self.logger(f"Erro ao buscar usuário ML: {user_res.status_code} - {user_res.text}", "ERRO")
            return

        user_data = user_res.json()
        seller_id = user_data.get('id')
        if not seller_id:
            self.logger("Resposta ML não retornou id do vendedor.", "ERRO")
            return

        config['ML_SELLER_ID'] = str(seller_id)
        self.salvar_config_cliente(folder, config)
        self.logger(f"ML conectado com sucesso. Seller ID salvo: {seller_id}", "SUCESSO")
        
        
    def inserir_token_mp(self):
        email = self.get_email()
        if not email:
            messagebox.showerror("Erro", "Por favor, digite o E-MAIL da conta para prosseguir a ação.")
            return
        
        pasta = os.path.join(ACCOUNTS_DIR, email)
        if not os.path.exists(pasta):
            os.makedirs(pasta)
        
        config_path = os.path.join(pasta, 'config_conta.json')
        if not os.path.exists(config_path):
            messagebox.showerror("Erro", "Arquivo config_conta.json não encontrado.")
            return
        
        token = simpledialog.askstring("Inserir Token MP", "Cole o token do Mercado Pago:")
        if not token:
            return
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        if "TOKEN_MP" not in config:
            config["TOKEN_MP"] = token
        else:
            config["TOKEN_MP2"] = token
        
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4)
        
        messagebox.showinfo("Sucesso", "Token inserido com sucesso!")
        
    def _planilha_bloqueada(self, caminho_excel):
        """Retorna True se a planilha de boletos parece estar aberta/bloqueada
        (arquivo de lock do Excel presente ou impossível abrir para escrita)."""
        if not caminho_excel or not os.path.exists(caminho_excel):
            return False  # se ainda não existe, não há como estar bloqueada

        pasta = os.path.dirname(caminho_excel)
        nome = os.path.basename(caminho_excel)
        lock_file = os.path.join(pasta, f"~${nome}")

        # 1) Excel cria esse arquivo de lock quando alguém abre a planilha
        if os.path.exists(lock_file):
            return True

        # 2) Tenta abrir em modo leitura/escrita sem truncar.
        #    No Windows, se outro processo (Excel) tiver o arquivo aberto,
        #    isso falha com PermissionError.
        try:
            with open(caminho_excel, 'r+b'):
                pass
            return False
        except (PermissionError, OSError):
            return True

    def _garantir_planilha_disponivel(self, order_id=None):
        """Verifica se dá pra salvar na planilha ANTES de enviar qualquer
        mensagem/boleto. Se estiver bloqueada, loga o erro e retorna False —
        o chamador deve interromper o envio para essa ordem."""
        folder = self.get_pasta_conta()
        if not folder:
            return False
        caminho_excel = os.path.join(folder, "registros_pedidos.xlsx")
        if self._planilha_bloqueada(caminho_excel):
            contexto = f" (ordem {order_id})" if order_id else ""
            self.logger(
                f"Planilha 'registros_pedidos.xlsx' está aberta/bloqueada{contexto}. "
                "Feche o arquivo Excel antes de continuar. Nenhuma mensagem foi enviada.",
                "ERRO"
            )
            return False
        return True    
        
        
    def atualizar_vendas_encerradas_thread(self):
        """Inicia a busca de vendas encerradas em uma thread separada."""
        folder = self.get_pasta_conta()
        if not folder:
            messagebox.showerror("Erro", "Selecione uma conta primeiro.")
            return
        
        thread = threading.Thread(target=self.atualizar_vendas_encerradas, daemon=True)
        thread.start()
        self.logger("Thread de vendas encerradas iniciada...")

    def atualizar_vendas_encerradas(self):
        """Busca pedidos cancelados/encerrados no ML e marca no banco de dados."""
        folder = self.get_pasta_conta()
        if not folder:
            return
        
        token = self.get_token_ml(folder)
        if not token:
            self.logger("Token ML não encontrado. Autorize novamente.", "ERRO")
            return
        
        config = self.carregar_config_cliente(folder)
        if not config:
            return
        
        db = self.carregar_db()
        if not db:
            self.logger("Nenhum banco de dados encontrado.", "AVISO")
            return
        
        seller_id = config.get('ML_SELLER_ID')
        if not seller_id:
            self.logger("Seller ID não encontrado na configuração.", "ERRO")
            return
        
        headers = {"Authorization": f"Bearer {token}"}
        resultados = []
        
        try:
            self.logger("Iniciando busca minuciosa de vendas encerradas no Mercado Livre...")
            
            resultados = []
            limit = 50
            offset = 0
            
            while True:
                # Buscamos todas as ordens recentes/arquivadas para filtrar no código
                url = f"https://api.mercadolibre.com/orders/search?seller={seller_id}&limit={limit}&offset={offset}&sort=date_desc"
                
                try:
                    response = SESSION.get(url, headers=headers, timeout=15)
                    if response.status_code == 404:
                        self.logger(f"Ordem {order_id} não encontrada na API (404). Ignorando.", "AVISO")
                        continue
                    response.raise_for_status()
                    data = response.json()
                    
                    orders = data.get("results", [])
                    if not orders:
                        break
                        
                    for pedido in orders:
                        # 1. Verifica se a ordem foi explicitamente cancelada
                        is_cancelled = pedido.get("status") == "cancelled"
                        
                        # 2. Verifica as condições de envio (Crucial para os "Não Entregues" e mediações com reembolso)
                        shipping = pedido.get("shipping", {})
                        shipping_status = shipping.get("status")
                        
                        # Status de envio que determinam que a venda foi encerrada/devolvida/não entregue
                        is_delivery_failed = shipping_status in ["not_delivered", "returned", "cancelled", "rejected"]
                        
                        # 3. Verifica se existe alguma mediação com reembolso (como no seu primeiro print)
                        # Se houver uma mediação aberta/encerrada e o envio falhou ou foi cancelado
                        has_mediations = len(pedido.get("mediations", [])) > 0

                        # SE o status for cancelado OU o envio foi devolvido/não entregue, entra na lista de finalizadas
                        if is_cancelled or is_delivery_failed or (has_mediations and shipping_status in ["returned", "undelivered"]):
                            resultados.append(pedido)
                    
                    paging = data.get("paging", {})
                    total = paging.get("total", 0)
                    
                    self.logger(f"Analisados {offset + len(orders)} de {total} pedidos totais. Encontrados {len(resultados)} encerrados até aqui...")
                    
                    offset += limit
                    if offset >= total:
                        break
                        
                except requests.exceptions.RequestException as e:
                    self.logger(f"Erro ao buscar página com offset {offset}: {e}", "ERRO")
                    break
                    
            if not resultados:
                self.logger("Nenhuma venda encerrada/cancelada encontrada nos registros analisados.", "AVISO")
                return
                
            total_encontrados = len(resultados)
            self.logger(f"Busca finalizada. Total de {total_encontrados} pedidos realmente encerrados encontrados.")
            
            # Atualiza o banco de dados local
            atualizados = 0
            for pedido in resultados:
                order_id = str(pedido['id'])
                
                if order_id in db:
                    db[order_id]['encerrada'] = True
                    atualizados += 1
                    self.logger(f"Ordem {order_id} marcada como encerrada no banco.")
                    
            self.salvar_db(db)
            self.logger(f"Atualização concluída com sucesso. Total de registros alterados no DB: {atualizados}")
            
        except Exception as e:
            self.logger(f"Erro geral no processamento: {str(e)}", "ERRO")

    def get_token_ml(self, folder):
        token = self.auth_ml.renovar_access_token(folder, config=self.carregar_config_cliente(folder))
        if not token:
            self.logger("Não foi possível obter um token válido. Autorize novamente.", "ALERTA")
        return token

    def buscar_vendas_paginadas(self, seller_id, access_token, offset_inicial=0, limite_maximo=2000):
        url_base = "https://api.mercadolibre.com/orders/search"
        limit_por_request = 50
        current_offset = int(offset_inicial) # Garante que é um inteiro
        
        headers = {"Authorization": f"Bearer {access_token}"}
        todos_os_pedidos = []

        while True:
            self._check_stop()
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
                response = SESSION.get(url_base, headers=headers, params=params, timeout=15)
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
                self._check_stop()

            except requests.exceptions.RequestException as e:
                self.logger(f"Erro na requisição: {e}", "ERRO")
                break

        return todos_os_pedidos, len(todos_os_pedidos)

    def _mediacao_esta_aberta(self, access_token, mediation_id):
        """Consulta a API de reclamações e retorna True se a mediação estiver aberta."""
        headers = {"Authorization": f"Bearer {access_token}"}
        url = f"https://api.mercadolibre.com/post-purchase/v1/claims/{mediation_id}"
        try:
            res = SESSION.get(url, headers=headers, timeout=15)
            if res.status_code == 200:
                data = res.json()
                status = data.get("status")
                self.logger(f"Mediação {mediation_id}: status={status}", "INFO")
                return status == "opened"
            else:
                self.logger(
                    f"Erro ao consultar mediação {mediation_id}: {res.status_code} {res.text}",
                    "ERRO"
                )
        except requests.exceptions.RequestException as e:
            self.logger(f"Erro ao consultar mediação {mediation_id}: {e}", "ERRO")
        return False


    def buscar_vendas_por_ids(self, access_token, order_ids, offset_inicial=0):
        headers = {"Authorization": f"Bearer {access_token}"}
        pedidos = []
        ids_solicitados = []
        ids_nao_encontrados = []

        for order_id in order_ids:
            self._check_stop()
            order_id = str(order_id).strip()
            if not order_id:
                continue

            ids_solicitados.append(order_id)
            url = f"https://api.mercadolibre.com/orders/{order_id}"
            try:
                self.logger(f"Buscando ordem por ID: {order_id}...")
                res = SESSION.get(url, headers=headers, timeout=15)
                if res.status_code == 200:
                    pedido = res.json()
                    pedido["executar_reclamacao"] = False

                    mediations = pedido.get("mediations") or []
                    for mediacao in mediations:
                        self._check_stop()
                        mediation_id = mediacao.get("id")
                        if not mediation_id:
                            continue

                        if self._mediacao_esta_aberta(access_token, mediation_id):
                            pedido["executar_reclamacao"] = True
                            pedido["order_id_resolvido"] = order_id
                            pedido["claim_id"] = mediation_id
                            self.logger(
                                f"Mediação {mediation_id} aberta para o pedido {order_id}. Marcando executar_reclamacao=True.",
                                "SUCESSO"
                            )
                            break  # já achou uma aberta, não precisa checar as outras

                        time.sleep(0.3)

                    pedidos.append(pedido)
                elif res.status_code == 404:
                    ids_nao_encontrados.append(order_id)
                    self.logger(
                        f"Ordem {order_id} não encontrada na API de pedidos (404). Tentando localizar como reclamação...",
                        "AVISO"
                    )
                else:
                    self.logger(f"Erro ao buscar ordem {order_id}: {res.status_code} {res.text}", "ERRO")
            except requests.exceptions.RequestException as e:
                self.logger(f"Erro ao buscar ordem {order_id}: {e}", "ERRO")
            time.sleep(0.5)

        if ids_nao_encontrados:
            self.logger(
                f"Buscando reclamações para os IDs não encontrados: {', '.join(ids_nao_encontrados)}",
                "INFO"
            )
            reclamacoes, total_reclamacoes = self.buscar_todas_reclamacoes(
                access_token,
                offset=int(offset_inicial)
            )

            ids_nao_encontrados_set = {str(item).strip() for item in ids_nao_encontrados if str(item).strip()}
            reclamacoes_encontradas = []

            for reclamacao in reclamacoes:
                resource_id = str(reclamacao.get("resource_id") or "").strip()
                if resource_id not in ids_nao_encontrados_set:
                    continue

                reclamacao["executar_reclamacao"] = True
                if reclamacao.get("date_created"):
                    reclamacao["claim_date_created"] = reclamacao.get("date_created")
                if reclamacao.get("sale_date"):
                    reclamacao["date_created"] = reclamacao.get("sale_date")
                reclamacoes_encontradas.append(reclamacao)

            if len(reclamacoes_encontradas) != len(ids_nao_encontrados_set):
                ids_nao_localizados = [
                    item for item in ids_nao_encontrados if str(item).strip() not in {str(r.get("resource_id") or "").strip() for r in reclamacoes_encontradas}
                ]
                self.logger(
                    f"Não foi possível localizar todas as reclamações para os IDs informados: {', '.join(ids_nao_localizados)}",
                    "ERRO"
                )
                raise ValueError(
                    f"Não foi possível localizar as reclamações para os IDs: {', '.join(ids_nao_localizados)}"
                )

            pedidos.extend(reclamacoes_encontradas)
            self.logger(
                f"Reclamações encontradas: {len(reclamacoes_encontradas)} de {len(ids_nao_encontrados_set)} IDs pesquisados.",
                "SUCESSO"
            )

        return pedidos, len(pedidos)

    def _data_created_ordenacao(self, registro):
        data = registro.get("date_created") or registro.get("sale_date")
        return str(data or "9999-12-31T23:59:59.999Z")

    def _registro_eh_reclamacao(self, registro, padrao=False):
        return bool(registro.get("executar_reclamacao", padrao))

    def _resolver_order_id_reclamacao(self, reclamacao, access_token):
        resource_id = str(reclamacao.get("resource_id") or "").strip()
        if not resource_id:
            return ""

        resource_type = str(reclamacao.get("resource") or "").strip().lower()
        if resource_type == "shipment" or resource_id.startswith("47"):
            headers = {"Authorization": f"Bearer {access_token}"}
            try:
                url_shipment = f"https://api.mercadolibre.com/shipments/{resource_id}"
                response = SESSION.get(url_shipment, headers=headers, timeout=20)
                if response.status_code == 200:
                    shipment_data = response.json()
                    order_id = str(shipment_data.get("order_id") or "").strip()
                    if order_id:
                        return order_id
                self.logger(f"Nao foi possivel resolver shipment {resource_id}: {response.status_code}", "AVISO")
            except Exception as e:
                self.logger(f"Erro ao resolver shipment {resource_id}: {e}", "AVISO")

        return resource_id

    def _order_id_registro(self, registro, padrao_reclamacao=False):
        if self._registro_eh_reclamacao(registro, padrao_reclamacao):
            return str(registro.get("order_id_resolvido") or registro.get("resource_id", ""))
        return str(registro.get("id", ""))

    def buscar_vendas_e_reclamacoes(self, seller_id, access_token, offset_inicial=0):
        pedidos_comuns, total_comuns = self.buscar_vendas_paginadas(
            seller_id,
            access_token,
            offset_inicial=offset_inicial
        )
        for pedido in pedidos_comuns: 
            pedido["executar_reclamacao"] = False

        reclamacoes, total_reclamacoes = self.buscar_todas_reclamacoes(access_token, offset=offset_inicial)
        for reclamacao in reclamacoes:
            reclamacao["executar_reclamacao"] = True
            reclamacao["order_id_resolvido"] = self._resolver_order_id_reclamacao(reclamacao, access_token)
            if reclamacao.get("date_created"):
                reclamacao["claim_date_created"] = reclamacao.get("date_created")
            if reclamacao.get("sale_date"):
                reclamacao["date_created"] = reclamacao.get("sale_date")

        ids_reclamacoes = set()
        for reclamacao in reclamacoes:
            for campo in ("order_id_resolvido", "resource_id", "id"):
                valor = str(reclamacao.get(campo) or "").strip()
                if valor:
                    ids_reclamacoes.add(valor)
        pedidos_comuns = [
            pedido for pedido in pedidos_comuns
            if str(pedido.get("id") or "").strip() not in ids_reclamacoes
        ]

        chats = pedidos_comuns + reclamacoes
        chats.sort(key=self._data_created_ordenacao)
        self.logger(
            f"Busca mista finalizada. Comuns: {total_comuns}; reclamações: {total_reclamacoes}; total: {len(chats)}",
            "INFO"
        )
        return chats, len(chats)

    def iniciar_thread_processamento(self, acao="solicitar", usar_thread=True):
        """Inicia o processamento baseado no botão clicado."""
        folder = self.get_pasta_conta()
        if not folder: return
        
        token = self.get_token_ml(folder)
        if not token: return
        
        config = self.carregar_config_cliente(folder)
        if not config: return
        
        if acao == "atualizar_pagos_reembolsar":
            def _rodar_atualizar_e_reembolsar():
                self.logger("[AGENDAMENTO] Atualizando boletos pagos...", "INFO")
                self.atualizar_blt_pagos()
                self.logger("[AGENDAMENTO] Verificando reembolsos pendentes...", "INFO")
                self._perguntar_reembolso_automatico(usar_thread=usar_thread)   # << propaga aqui

            if usar_thread:
                thread = threading.Thread(target=_rodar_atualizar_e_reembolsar, daemon=True)
                thread.daemon = True
                thread.start()
                self.logger("Thread de atualizar+reembolsar iniciada...")
                return thread
            else:
                _rodar_atualizar_e_reembolsar()
                self.logger("Ação 'atualizar_pagos_reembolsar' concluída.", "SUCESSO")
                return None

        
        prazo_usuario = self.var_prazo.get()
        pagInicial = self.var_pag_inicial.get()
        
        if acao == "solicitar":
          if not prazo_usuario or not pagInicial:
            self.logger("Erro: Prazo e Página Inicial são obrigatórios.", "ERRO")
            return
        
        if acao in ["autorizar_boleto", "agradecimento", "cobrar_dobrado"]:
            if not self.var_data_entrega.get().strip():
                self.logger("Erro: Data de Entrega é obrigatória para esta ação.", "ERRO")
                return
            
        if acao == "ia":
            # Agora existe uma única IA (scriptIAcomum.txt) usada tanto para o chat
            # comum quanto para reclamações; a diferença entre os dois é só a
            # origem das mensagens e o parâmetro dinâmico conversa_com_reclamação.
            self.ia_comum_script = self.carregar_script_ia_comum(folder)
            if not self.ia_comum_script:
                return

        processarByid = self.var_ordem_ids.get().strip()
        ids_list = []
        tipo_proc = "all"
        if processarByid:
            ids_list = [oid.strip() for oid in re.split(r'[\s,;]+', processarByid) if oid.strip()]
            if not ids_list:
                messagebox.showerror("Erro", "Para processar por ID, preencha o campo 'Ordem IDs' com IDs válidos!")
                return
            tipo_proc = "by_id"
            self.logger(f"Iniciando processamento by IDs: {', '.join(ids_list)}")

        executar_reclamacao = acao == "ia_reclamacao"

        # --- BUSCA DE VENDAS/RECLAMAÇÕES RODANDO EM SEGUNDO PLANO ---
        # Essas buscas fazem várias chamadas de rede (paginação de vendas,
        # reclamações, resolução de order_id por reclamação, etc.) e antes
        # rodavam direto aqui na thread da interface, travando a janela
        # ("não está respondendo") até a rede responder. Agora a busca roda
        # numa thread separada; enquanto isso, a thread principal só fica
        # "bombeando" a fila de eventos do Tkinter (self.root.update()) pra
        # manter a janela respondendo (redesenhando, aceitando mover/minimizar
        # etc.) até a busca terminar.
        resultado_busca = {}

        def _executar_busca():
            try:
                if tipo_proc == "by_id":
                    resultado_busca['chats'], resultado_busca['total'] = self.buscar_vendas_por_ids(
                        token,
                        ids_list,
                        offset_inicial=pagInicial
                    )
                else:
                    resultado_busca['chats'], resultado_busca['total'] = self.buscar_vendas_e_reclamacoes(
                        config['ML_SELLER_ID'], token, offset_inicial=pagInicial
                    )
            except Exception as e:
                resultado_busca['erro'] = e

        if tipo_proc == "by_id":
            self.logger("Modo BY_ID ativado: buscando apenas as ordens informadas (em segundo plano)...")
        else:
            self.logger("Modo COMUM + RECLAMAÇÕES ativado: buscando em segundo plano (isso pode levar alguns segundos, a tela não vai travar)...")

        thread_busca = threading.Thread(target=_executar_busca, daemon=True)
        thread_busca.start()
        while thread_busca.is_alive():
            try:
                self.root.update()
            except Exception:
                pass
            time.sleep(0.05)

        if 'erro' in resultado_busca:
            self.logger(f"Erro ao buscar vendas/reclamações: {resultado_busca['erro']}", "ERRO")
            return

        chats = resultado_busca.get('chats', [])
        total_chats = resultado_busca.get('total', 0)

        if tipo_proc == "by_id" and total_chats == 0:
            self.logger("Nenhuma ordem encontrada para os IDs informados.", "ERRO")
            return

        self.logger(f"Busca concluída. Iniciando ação: {acao.upper()}...")
        
        
        self.progress["maximum"] = total_chats
        self.progress["value"] = 0

        # Inicializa todas as flags como False
        env_rastreio = False
        autorizar_boleto = False
        rodar_wpp = False
        lim_rastreio = 0
        tipomsgRastreio = False
        env_boleto = False
        lim_boleto = 0
        lim_atorizar = 0 
        lim_nao_autorizados = 0
        env_boleto_autorizados = False
        env_erroBoleto = False
        reenviarBoleto = False
        reenviar_boleto_atraso = False
        filtrar_reenvio_frase = False
        reenviarBoletoDobrado = False
        reenviar_boleto_dobrado_atraso = False
        filtrar_reenvio_dobro_frase = False
        solicitar = False
        env_boleto_agradecimento = False
        cobrar_dobrado = False
        cobrar_dobrado_metodo = "boleto"      
        cobrar_dobrado_pix_chave = None       
        cobrar_nao_pagos = False
        cobrar_nao_autorizados = False
        responder_ia_comum = False
        cod_rastreio = self.var_rastreio.get().strip()
        lote_filtro_numero = None
        lote_filtro_ids = None

        self.stop_event.clear()
        if hasattr(self, 'btn_stop'):
            self.btn_stop.config(state=tk.NORMAL, text="STOP URGENTE", bg="#FF0000")

        if self.rodar_wa_var.get():
            if self.wpp_ativo:
               rodar_wpp = True
               self.logger("Processamento via WhatsApp selecionado. As mensagens serão enviadas usando a API do WhatsApp.")
            else:
               self.logger("Erro: Para enviar mensagens via WhatsApp, o serviço deve estar ativo. Por favor, ative o WhatsApp antes de iniciar esta ação.", "ERRO")
               if hasattr(self, 'btn_stop'):
                   self.btn_stop.config(state=tk.DISABLED)
               return
        elif acao == "boleto":
            ok_lote, lote_filtro_numero, lote_filtro_ids = self.selecionar_filtro_lote("enviar boleto")
            if not ok_lote:
                return
            if lote_filtro_ids is not None:
                chats = [
                    pedido for pedido in chats
                    if self._order_id_registro(pedido, executar_reclamacao) in lote_filtro_ids
                ]
                total_chats = len(chats)
                if total_chats == 0:
                    self.logger(f"Nenhuma ordem encontrada para o lote {lote_filtro_numero}.", "ERRO")
                    return
                self.progress["maximum"] = total_chats
                self.progress["value"] = 0
            self.root.lift()
            self.root.focus_force()
            env_boleto_autorizados = messagebox.askyesno("Enviar apenas autorizados", "Enviar apenas para os que digitou 1?")
            if env_boleto_autorizados:
                self.logger("Verificando conversas para encontrar clientes autorizados...", "INFO")
                db = self.carregar_db()
                autorizados = 0
                pedidos_relevantes = []
                msg_liberacao_boleto = "A liberação do seu boleto já está sendo processada."

                for pedido in chats:
                    order_id = self._order_id_registro(pedido, executar_reclamacao)
                    if not order_id:
                        continue
                    if lote_filtro_ids is not None and order_id not in lote_filtro_ids:
                        continue
                    pedido_db = db.get(order_id, {})
                    # Incluir apenas pedidos autorizados que ainda não tiveram boleto enviado
                    if pedido_db.get('boleto_autorizado_msg') is True and not pedido_db.get('boleto_enviado'):
                        pedidos_relevantes.append((order_id, pedido))

                total_relevantes = len(pedidos_relevantes)
                if total_relevantes == 0:
                    self.logger("Nenhum pedido com boleto_autorizado_msg=true encontrado. A ação foi cancelada.", "ERRO")
                    return

                progress_max_before = self.progress["maximum"]
                self.progress["maximum"] = total_relevantes
                self.progress["value"] = 0

                for idx, (order_id, pedido) in enumerate(pedidos_relevantes, start=1):
                    if self.stop_event.is_set():
                        self.logger("Processamento interrompido pelo usuário.", "ERRO")
                        self.progress["maximum"] = progress_max_before
                        return

                    self.progress["value"] = idx
                    self.progress.update()

                    if idx % 10 == 0 or idx == total_relevantes:
                        self.logger(f"Carregando conversas: {idx}/{total_relevantes} pedidos verificados...", "INFO")

                    try:
                        self._check_stop()
                        conversa = self.obter_conversa_completa(order_id, order_id, config['ML_SELLER_ID'], token)

                        # obter_conversa_completa já retorna ordenado por data,
                        # mas mantemos aqui como garantia extra.
                        conversa = sorted(conversa, key=self._chave_ordenacao_data)

                        # obter_conversa_completa agora extrai sender_id/is_seller também
                        # para mensagens de Reclamação (igual já era feito no Chat Comum),
                        # então voltamos a poder filtrar quem enviou cada mensagem com
                        # segurança, mesmo dentro de uma Reclamação.
                        # Mesmo assim, seguimos identificando o prompt pelo texto completo
                        # do template (e não só "DIGITE 1"), pois é mais específico.
                        PADRAO_PROMPT_DIGITE_1 = re.compile(
                            r'digite\s*1\b.{0,150}gerar o boleto',
                            re.IGNORECASE | re.DOTALL
                        )

                        ultima_prompt_index = None
                        for msg_idx, m in enumerate(conversa):
                            texto = str(m.get('texto', '')).strip()
                            if PADRAO_PROMPT_DIGITE_1.search(texto):
                                ultima_prompt_index = msg_idx

                        if ultima_prompt_index is None:
                            continue
                        
                        PADRAO_MSG_COMPENSACAO = re.compile(
                            r'taxa de importa[çc][ãa]o'
                            r'|montagem gr[áa]tis'
                            r'|est[áa]mos te presenteando'
                            r'|precisamos da sua autoriza[çc][ãa]o para dar andamento'
                            r'|caso n[ãa]o receba a confirma[çc][ãa]o.{0,40}cancelado automaticamente',
                            re.IGNORECASE
                        )

                        def _parece_codigo_boleto(texto):
                            """
                            Linha digitável de boleto tem várias dezenas de dígitos,
                            geralmente separados por espaços (ex: '42297 11504 ... 1 15030000013880').
                            Isso faz o '1' isolado de uma dessas partes ser confundido com uma
                            resposta de autorização. Se o texto é majoritariamente dígitos/espaços
                            e tem muitos dígitos no total, tratamos como código de boleto, não resposta.
                            """
                            apenas_digitos = re.sub(r'\D', '', texto)
                            if len(apenas_digitos) < 20:
                                return False
                            # Confirma que o texto é essencialmente números e espaços (sem palavras)
                            return bool(re.fullmatch(r'[\d\s.\-]+', texto))

                        def _e_resposta_autorizacao_1(texto):
                            """
                            Considera autorização apenas quando a mensagem do cliente é,
                            em essência, só o '1' (com no máximo pontuação/espacos em volta:
                            '1', '1.', ' 1 ', '1!'). Isso evita que um '1' solto no meio de
                            uma frase qualquer ('moro no apto 1', 'chegou dia 1' etc.) seja
                            confundido com a resposta ao "digite 1".
                            """
                            return bool(re.fullmatch(r'\s*1\s*[.!]?\s*', texto))
                        
                        mensagens_cliente_para_ia = []
                        for m in conversa[ultima_prompt_index + 1:]:
                            # Ignora qualquer mensagem enviada pelo próprio vendedor
                            # (nossas próprias mensagens não contam como resposta do cliente).
                            if m.get('is_seller') and m.get('texto').strip() != msg_liberacao_boleto:
                                continue

                            texto = str(m.get('texto', '')).strip()

                            if PADRAO_MSG_COMPENSACAO.search(texto):
                               continue

                            if _parece_codigo_boleto(texto):
                                continue
                            
                            if texto and not m.get('is_seller'):
                                mensagens_cliente_para_ia.append(texto)

                            autorizou_por_numero = _e_resposta_autorizacao_1(texto)
                            autorizou_por_msg_manual = msg_liberacao_boleto.lower() in texto.lower()
                            if autorizou_por_numero or autorizou_por_msg_manual:
                                if not db[order_id].get('cliente_autorizou'):
                                    db[order_id]['cliente_autorizou'] = True
                                autorizados += 1
                                break
                        else:
                            # Loop terminou sem 'break': não achou autorização direta.
                            # Consulta a IA com as mensagens do cliente para decidir.
                            if self._verificar_autorizacao_via_ia(order_id, mensagens_cliente_para_ia):
                                if not db[order_id].get('cliente_autorizou'):
                                    db[order_id]['cliente_autorizou'] = True
                                db[order_id]['cliente_autorizou_via_ia'] = True
                                autorizados += 1
                    except Exception as e:
                        self.logger(f"Erro ao verificar autorização para {order_id}: {e}", "ERRO")

                self.progress["maximum"] = progress_max_before
                self.progress["value"] = 0
                self.progress.update()

                self.salvar_db(db)
                self.logger(f"Clientes autorizados encontrados: {autorizados}", "INFO")
                messagebox.showinfo("Autorizados", f"Total de ordens autorizadas: {autorizados}")
                if autorizados == 0:
                    self.logger("Nenhum cliente autorizado encontrado. A ação de boleto foi cancelada.", "ERRO")
                    return
            self.root.lift()
            self.root.focus_force()
            total_limite = len(lote_filtro_ids) if lote_filtro_ids is not None else total_chats
            lim_boleto = simpledialog.askinteger("Limite", f"Quantos boletos enviar? (Total: {total_limite})", minvalue=1, parent=self.root)
            if not lim_boleto: return
            env_boleto = True

        elif acao == "erro_boleto":
            env_erroBoleto = True
        elif acao == "autorizar_boleto":
            ok_lote, lote_filtro_numero, lote_filtro_ids = self.selecionar_filtro_lote("taxar e autorizar boleto")
            if not ok_lote:
                return
            if lote_filtro_ids is not None:
                chats = [
                    pedido for pedido in chats
                    if self._order_id_registro(pedido, executar_reclamacao) in lote_filtro_ids
                ]
                total_chats = len(chats)
                if total_chats == 0:
                    self.logger(f"Nenhuma ordem encontrada para o lote {lote_filtro_numero}.", "ERRO")
                    return
                self.progress["maximum"] = total_chats
                self.progress["value"] = 0
            total_limite = len(lote_filtro_ids) if lote_filtro_ids is not None else total_chats
            lim_atorizar = simpledialog.askinteger("Limite", f"Quantos pessoas enviar? (Total: {total_limite})", minvalue=1, parent=self.root)
            if not lim_atorizar: return
            autorizar_boleto = True
        elif acao == "reenviar_boleto":
            self.root.lift()
            self.root.focus_force()
            reenviar_boleto_atraso = messagebox.askyesno("Mensagem de atraso", "É msg de atraso?")
            self.root.lift()
            self.root.focus_force()
            reenviarBoleto = True
            filtrar_reenvio_frase = messagebox.askyesno(
                "Filtrar por frase",
                "Reenviar apenas para quem recebeu a mensagem:\n"
                "\"Estamos gerando seu boleto. Aguarde um momento, por favor.\"?"
            )
            if filtrar_reenvio_frase:
                self.logger("Verificando conversas para encontrar frase de reenviar...", "INFO")
                db = self.carregar_db()
                autorizados = 0
                pedidos_relevantes = []
                msg_liberacao_boleto = "Estamos gerando seu boleto. Aguarde um momento, por favor."

                for pedido in chats:
                    order_id = self._order_id_registro(pedido, pedido.get("executar_reclamacao"))
                    if not order_id:
                        continue
                    if lote_filtro_ids is not None and order_id not in lote_filtro_ids:
                        continue
                    pedido_db = db.get(order_id, {})
                    # Incluir apenas pedidos autorizados que ainda não tiveram boleto enviado
                    #if order_id == "2000017141149126":
                    #    dasdasd = "dasda"
                    if pedido_db.get('boleto_enviado') and not pedido_db.get('reenvio_confirmado') and not pedido_db.get('boleto_pago'):
                        pedidos_relevantes.append((order_id, pedido))

                total_relevantes = len(pedidos_relevantes)
                if total_relevantes == 0:
                    self.logger("Nenhum pedido com boleto_enviado=true encontrado. A ação foi cancelada.", "ERRO")
                    return

                progress_max_before = self.progress["maximum"]
                self.progress["maximum"] = total_relevantes
                self.progress["value"] = 0

                for idx, (order_id, pedido) in enumerate(pedidos_relevantes, start=1):
                    if self.stop_event.is_set():
                        self.logger("Processamento interrompido pelo usuário.", "ERRO")
                        self.progress["maximum"] = progress_max_before
                        return

                    self.progress["value"] = idx
                    self.progress.update()

                    if idx % 10 == 0 or idx == total_relevantes:
                        self.logger(f"Carregando conversas: {idx}/{total_relevantes} pedidos verificados...", "INFO")

                    try:
                        self._check_stop()
                        conversa = self.obter_conversa_completa(order_id, order_id, config['ML_SELLER_ID'], token)

                        # obter_conversa_completa já retorna ordenado por data,
                        # mas mantemos aqui como garantia extra.
                        conversa = sorted(conversa, key=self._chave_ordenacao_data)

                        for m in conversa:
                            # Ignora qualquer mensagem enviada pelo próprio vendedor
                            # (nossas próprias mensagens não contam como resposta do cliente).
                            if not m.get('is_seller'):
                               continue
                            
                            texto = str(m.get('texto', '')).strip() 
                                
                            autorizou_por_msg_manual = msg_liberacao_boleto.lower() in texto.lower()
                            if autorizou_por_msg_manual:
                                db[order_id]['cliente_autorizou_reenvio'] = True
                                autorizados += 1
                                break
                    except Exception as e:
                        self.logger(f"Erro ao verificar autorização para {order_id}: {e}", "ERRO")

                self.progress["maximum"] = progress_max_before
                self.progress["value"] = 0
                self.progress.update()

                self.salvar_db(db)
                self.logger(f"Clientes autorizados pela frase encontrados: {autorizados}", "INFO")
                messagebox.showinfo("Autorizados", f"Total de ordens autorizadas pela frase: {autorizados}")
                if autorizados == 0:
                    self.logger("Nenhum cliente autorizado encontrado. A ação de reenviar boleto foi cancelada.", "ERRO")
                    return
            else:    
                if tipo_proc == "all":
                    self.logger("Nenhum ID fornecido. A ação de reenviar boleto sem frase foi cancelada.", "ERRO")
                    return 
        elif acao == "reenviar_boleto_dobrado":
            self.root.lift()
            self.root.focus_force()
            reenviar_boleto_dobrado_atraso = messagebox.askyesno("Mensagem de atraso", "É msg de atraso?")
            self.root.lift()
            self.root.focus_force()
            reenviarBoletoDobrado = True
            filtrar_reenvio_dobro_frase = messagebox.askyesno(
                "Filtrar por frase",
                "Reenviar apenas para quem recebeu a mensagem:\n"
                "\"Estamos gerando seu Boleto do restante da taxa. Aguarde um momento, por favor.\"?"
            )
            if filtrar_reenvio_dobro_frase:
                self.logger("Verificando conversas para encontrar frase de reenviar boleto dobrado...", "INFO")
                db = self.carregar_db()
                autorizados = 0
                pedidos_relevantes = []
                msg_liberacao_boleto_dobro = "Estamos gerando seu Boleto do restante da taxa. Aguarde um momento, por favor."

                for pedido in chats:
                    order_id = self._order_id_registro(pedido, executar_reclamacao)
                    if not order_id:
                        continue
                    if lote_filtro_ids is not None and order_id not in lote_filtro_ids:
                        continue
                    pedido_db = db.get(order_id, {})
                    # Apenas pedidos com cobrança dobrada já enviada e ainda não paga
                    if pedido_db.get('cobrado_dobro') is True and pedido_db.get('reenvio_confirmado_dobro') is not True:
                        pedidos_relevantes.append((order_id, pedido))

                total_relevantes = len(pedidos_relevantes)
                if total_relevantes == 0:
                    self.logger("Nenhum pedido com cobrado_dobro=true encontrado. A ação foi cancelada.", "ERRO")
                    return

                progress_max_before = self.progress["maximum"]
                self.progress["maximum"] = total_relevantes
                self.progress["value"] = 0

                for idx, (order_id, pedido) in enumerate(pedidos_relevantes, start=1):
                    if self.stop_event.is_set():
                        self.logger("Processamento interrompido pelo usuário.", "ERRO")
                        self.progress["maximum"] = progress_max_before
                        return

                    self.progress["value"] = idx
                    self.progress.update()

                    if idx % 10 == 0 or idx == total_relevantes:
                        self.logger(f"Carregando conversas: {idx}/{total_relevantes} pedidos verificados...", "INFO")

                    try:
                        self._check_stop()
                        conversa = self.obter_conversa_completa(order_id, order_id, config['ML_SELLER_ID'], token)
                        conversa = sorted(conversa, key=self._chave_ordenacao_data)

                        for m in conversa:
                            if not m.get('is_seller'):
                                continue
                            texto = str(m.get('texto', '')).strip()
                            if msg_liberacao_boleto_dobro.lower() in texto.lower():
                                db[order_id]['cliente_autorizou_reenvio_dobro'] = True
                                autorizados += 1
                                break
                    except Exception as e:
                        self.logger(f"Erro ao verificar autorização para {order_id}: {e}", "ERRO")

                self.progress["maximum"] = progress_max_before
                self.progress["value"] = 0
                self.progress.update()

                self.salvar_db(db)
                self.logger(f"Clientes autorizados pela frase (dobro) encontrados: {autorizados}", "INFO")
                messagebox.showinfo("Autorizados", f"Total de ordens autorizadas pela frase (dobro): {autorizados}")
                if autorizados == 0:
                    self.logger("Nenhum cliente autorizado encontrado. A ação de reenviar boleto dobrado foi cancelada.", "ERRO")
                    return 
            
        elif acao == "agradecimento":
            ok_lote, lote_filtro_numero, lote_filtro_ids = self.selecionar_filtro_lote("MSG Agradecimento")
            if ok_lote:
                if lote_filtro_ids:
                    chats = [
                        pedido for pedido in chats
                        if self._order_id_registro(pedido, executar_reclamacao) in lote_filtro_ids
                    ]
                    total_chats = len(chats)
                    if total_chats == 0:
                        self.logger(f"Nenhuma ordem encontrada para o lote {lote_filtro_numero}.", "ERRO")
                        return
                    self.progress["maximum"] = total_chats
                    self.progress["value"] = 0
            env_boleto_agradecimento = True
        elif acao == "solicitar":
            solicitar = True    
        elif acao == "cobrar_dobrado":
            self.root.lift()
            self.root.focus_force()
            usar_pix = messagebox.askyesno(
                "Forma de Cobrança",
                "Cobrar via PIX?\n\nSim = PIX\nNão = Boleto"
            )
            if usar_pix:
                cobrar_dobrado_metodo = "pix"
            else:
                cobrar_dobrado_metodo = "boleto"
            cobrar_dobrado = True
        elif acao == "nao_pagos":
            cobrar_nao_pagos = True
            self.logger("Modo NAO PAGOS ativado: cobrando boletos enviados ha mais de 1 dia e ainda nao pagos.", "INFO")    
        elif acao == "nao_autorizados":
            self.root.lift()
            self.root.focus_force()
            lim_nao_autorizados = total_chats
            if not lim_nao_autorizados: return
            cobrar_nao_autorizados = True
            self.logger("Modo NAO AUTORIZADOS ativado: cobrando clientes que receberam DIGITE 1 ha mais de 1 dia e nao responderam.", "INFO")
        elif acao == "ia":
            # Botão único: o próprio loop (via _registro_eh_reclamacao) já detecta,
            # pedido a pedido, se aquela ordem tem reclamação aberta ou não, e
            # direciona para responder_reclamacao_com_ia ou responder_chat_comum_com_ia
            # automaticamente — ambos usando o mesmo cérebro de IA unificado.
            responder_ia_comum = True
        elif acao == "rastreio":
            if not pagInicial or not cod_rastreio:
                self.logger("Erro: Página Inicial e Cód. Rastreio são obrigatórios para esta ação.", "ERRO")
                return
            self.root.lift()
            self.root.focus_force()
            lim_rastreio = simpledialog.askinteger("Limite", f"Quantos rastreios enviar? (Total: {total_chats})", minvalue=1, parent=self.root)
            if not lim_rastreio: return
            self.root.lift()
            self.root.focus_force()
            tipomsgRastreio = simpledialog.askinteger("TIPO MSG", f"RASTREIO BR 1 ---- RASTREIO ALIEXPRESS 2", minvalue=1, parent=self.root)
            if tipomsgRastreio != 1 and tipomsgRastreio != 2: 
                self.logger("Erro: Tipo de mensagem de rastreio deve ser 1 ou 2.", "ERRO") 
                return
            env_rastreio = True      
            
            
        if usar_thread:
            if hasattr(self, 'btn_stop'):
                self.btn_stop.config(state=tk.NORMAL, text="STOP URGENTE", bg="#FF0000")
            thread = threading.Thread(
                target=self.passo_1_solicitar, 
                args=(token, env_rastreio, lim_rastreio, cod_rastreio, env_boleto, lim_boleto, 
                      pagInicial, prazo_usuario, chats, config, env_erroBoleto, tipo_proc, 
                      env_boleto_agradecimento, reenviarBoleto, solicitar,cobrar_dobrado,executar_reclamacao,rodar_wpp,tipomsgRastreio,autorizar_boleto, env_boleto_autorizados, lim_atorizar, responder_ia_comum,lote_filtro_numero, lote_filtro_ids, cobrar_nao_pagos, cobrar_nao_autorizados, lim_nao_autorizados, reenviar_boleto_atraso,filtrar_reenvio_frase,cobrar_dobrado_metodo,reenviarBoletoDobrado, reenviar_boleto_dobrado_atraso, filtrar_reenvio_dobro_frase )
            )
            thread.daemon = True
            thread.start()
            self.logger(f"Thread de {acao} iniciada...")
            return thread
        else:
            if hasattr(self, 'btn_stop'):
                self.btn_stop.config(state=tk.DISABLED, text="STOP URGENTE", bg="#FF0000")
            self.logger(f"Executando ação '{acao}' em modo agendamento, aguardando conclusão...", "INFO")
            self.passo_1_solicitar(
                token, env_rastreio, lim_rastreio, cod_rastreio, env_boleto, lim_boleto, 
                pagInicial, prazo_usuario, chats, config, env_erroBoleto, tipo_proc, 
                env_boleto_agradecimento, reenviarBoleto, solicitar,cobrar_dobrado,executar_reclamacao,rodar_wpp,tipomsgRastreio,autorizar_boleto, env_boleto_autorizados, lim_atorizar, responder_ia_comum ,lote_filtro_numero, lote_filtro_ids, cobrar_nao_pagos, cobrar_nao_autorizados, lim_nao_autorizados, reenviar_boleto_atraso, filtrar_reenvio_frase,  cobrar_dobrado_metodo,reenviarBoletoDobrado, reenviar_boleto_dobrado_atraso, filtrar_reenvio_dobro_frase)
            self.logger(f"Ação '{acao}' concluída com sucesso.", "SUCESSO")
            return None
        
       
        
    # --- PASSO 1: SOLICITAÇÃO --- PROCESSO PRINCIPAL
    def passo_1_solicitar(self, token, env_rastreio, lim_rastreio, cod_rastreio, env_boleto, lim_boleto, pagInicial, prazo_usuario, chats, config,env_erroBoleto, tipo,env_boleto_agradecimento,reenviarBoleto,solicitar,cobrar_dobrado,executar_reclamacao,rodar_wpp,tipomsgRastreio,autorizar_boleto, env_boleto_autorizados, lim_atorizar, responder_ia_comum ,lote_filtro_numero=None, lote_filtro_ids=None, cobrar_nao_pagos=False, cobrar_nao_autorizados = None, lim_nao_autorizados=None, reenviar_boleto_atraso=False, filtrar_reenvio_frase=False, cobrar_dobrado_metodo="boleto", reenviarBoletoDobrado=False, reenviar_boleto_dobrado_atraso=False, filtrar_reenvio_dobro_frase=False):
        folder = self.get_pasta_conta()
        if not folder: return
        
        
        email_lock = self.get_email()
        quem = "agendamento" if not threading.current_thread().daemon else "manual"
        if not adquirir_lock_conta(folder, quem=quem):
            info = ler_info_lock(folder)
            self.logger(
                f"Conta {email_lock} já está sendo processada por outra execução ({info}). "
                "Aguarde terminar antes de rodar outra ação.",
                "ERRO"
            )
            return
        
        token = self.get_token_ml(folder)
        if not token: return
        
        if self.stop_event.is_set():
            self.logger("Processamento interrompido pelo usuário antes de iniciar.", "ERRO")
            return
        
        rastreios_contagem = 0
        boletos_contagem = 0
        autorizar_contagem = 0
        nao_autorizados_contagem = 0
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
                self._check_stop()
                buyer_id = ""
                nome_prod = ""
                valor = ""
                corProduto = ""   
                claim_id = None
                executar_reclamacao = self._registro_eh_reclamacao(pedido, executar_reclamacao)

                
                
                if executar_reclamacao: 
                    tratado = self.executar_reclamacao_shipping(pedido, tipo, token)
                    
                    order_id = tratado[0]
                    claim_id = tratado[1]
                    # 1. Pegamos os dados do pedido no DB com segurança
                    info_pedido = db.get(order_id)
                    
                    if info_pedido is not None:
                        # 2. Verificamos as chaves internas usando .get() para não quebrar
                        if (info_pedido.get('produto') == "" or 
                            info_pedido.get('valor') == "" or 
                            info_pedido.get('corProduto') == ""):
                            
                            dadosProduto = self.obter_produto_ml(order_id, token, all=True)
                            
                            # 3. Verificamos se a API retornou sucesso e se tem os dados necessários
                            if dadosProduto and dadosProduto.get('status') != 404:
                                try:
                                    # Usamos .get() e verificamos listas para evitar erro de índice [0]
                                    items = dadosProduto.get('order_items', [{}])[0]
                                    variation = items.get('item', {}).get('variation_attributes', [{}])[0]
                                    payment = dadosProduto.get('payments', [{}])[0]

                                    # 4. Atualizamos o dicionário original 'db'
                                    db[order_id]['corProduto'] = str(variation.get('value_name', ""))
                                    db[order_id]['produto'] = str(payment.get('reason', ""))
                                    db[order_id]['valor'] = str(dadosProduto.get('total_amount', ""))
                                    
                                    self.salvar_db(db)
                                except (IndexError, KeyError):
                                    # Caso a estrutura da API seja muito diferente do esperado
                                    self.logger(f"Erro ao processar estrutura de dadosProduto para o order_id: {order_id}")
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
                    
                
                #if order_id != "2000017199107524":
                #    self.logger(f"Ordem {order_id} ignorada (não está na lista de IDs do teste).")
                #    continue    
                
                # APOS 2 OU 3 DIAS DO ENVIO DO CODIGO DE RASTREIO, ENVIAR MSG E BOLETO PARA PAGAMENTO DE TAXA E SALVAR NO DB QUE O BOLETO FOI ENVIADO
                #url_msg = f"https://api.mercadolibre.com/messages/packs/{order_id}/sellers/{config['ML_SELLER_ID']}?tag=post_sale"
                # Se a ordem não existe no DB, inicializamos como dicionário vazio
                if order_id not in db:
                    #self.logger(f"Ordem {order_id} ignorada (não está na lista do banco de dados).")
                    #continue
                    db[order_id] = {}
                    
                dados_pedido = db[order_id]    
                if lote_filtro_ids is not None and (env_boleto or autorizar_boleto) and order_id not in lote_filtro_ids:
                    self.logger(f"Ordem {order_id} ignorada: fora do lote {lote_filtro_numero}.", "AVISO")
                    continue
                
                if(not db[order_id].get('buyer_id')):
                        db[order_id]['buyer_id'] = buyer_id
                
                # Usamos after() para que a Main Thread faça a pintura do widget    
                self.root.after(0, lambda v=i+1: self.progress.configure(value=v))    
                
                if responder_ia_comum:
                        self.responder_chat_comum_com_ia(
                            order_id,
                            dados_pedido.get('buyer_id') or buyer_id,
                            headers,
                            config['ML_SELLER_ID'],
                            token,
                            db,
                            executar_reclamacao,
                            claim_id
                        )
                    
                    
                
                    
                
                if order_id in db and (dados_pedido.get('rastreio_enviado')):
                    #data_rastreio = dados_pedido.get('data_rastreio')
                    try:
                        #data_envio = datetime.strptime(data_rastreio, "%d/%m/%Y %H:%M")
                        #diferenca = datetime.now() - data_envio
                        if env_boleto and boletos_contagem < lim_boleto and not dados_pedido.get('boleto_enviado'):
                            if env_boleto_autorizados and not dados_pedido.get('cliente_autorizou'):
                                self.logger(f"Ordem {order_id} ignorada: cliente não autorizou com '1'.", "AVISO")
                                continue
                            self.logger(f"Enviando boleto para pagamento de taxa para a ordem {order_id}...")
                            
                            boleto_numero = None
                            indice_boleto = None
                            id_payment = None
                            boleto_info = self.buscar_proximo_boleto()
                            if boleto_info:
                                boleto_numero = boleto_info["numero"]
                                indice_boleto = boleto_info["indice"]
                                id_payment = boleto_info["id_payment"]
                                horario_boleto = boleto_info["horario_boleto"]
                            if(not boleto_numero):
                                self.logger(f"Não foi possível encontrar um boleto disponível para a ordem {order_id}. Verifique o Excel de registros.", "ERRO")
                                break       
                                # -- AVISO PRÉ BOLETO
                            if not self._garantir_planilha_disponivel(order_id):
                               break      
                                
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
                                            boletos_contagem += 1
                                            planilhaok = self.atualizar_status_boleto(indice_boleto)
                                            if planilhaok:
                                                db[order_id]['boleto_enviado'] = True
                                                db[order_id]['data_boleto'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                                                db[order_id]['codigo_boleto'] = boleto_numero
                                                db[order_id]['id_payment'] = id_payment
                                                db[order_id]['horario_boleto'] = horario_boleto
                                                self.salvar_db(db)
                                                self.logger(f"Boleto enviado com sucesso para a ordem {order_id}!")
                                                continue
                                            else:
                                                self.logger(f"Erro ao atualizar status do boleto na planilha para a ordem {order_id}. Verifique o Excel de registros. O processamento será interrompido para evitar mais envios de boletos.", "ERRO")
                                                break
                                    else:
                                        self.logger(f"Falha ao enviar mensagem de comprovante para a ordem {order_id}: {envioBoletoComprovante.text}", "ERRO")
                                else:
                                        self.logger(f"Falha ao enviar código do boleto para a ordem {order_id}: {envioBoleto.text}", "ERRO")     
                            else:
                                self.logger(f"Falha ao enviar boleto para a ordem {order_id}: {envioMsgpreBoleto.text}", "ERRO")
                        elif reenviarBoleto:
                            if filtrar_reenvio_frase and dados_pedido.get('reenvio_confirmado'):
                               self.logger(f"Ordem {order_id} ignorada: reenvio ou reenvio já foi feito.", "AVISO")
                               continue
                            if filtrar_reenvio_frase and not dados_pedido.get('cliente_autorizou_reenvio'):
                               self.logger(f"Ordem {order_id} ignorada: cliente não autorizou com a frase de reenvio.", "AVISO")
                               continue
                            self.logger(f"Enviando boleto para pagamento de taxa para a ordem {order_id}...")
                            
                            boleto_numero = None
                            indice_boleto = None
                            id_payment = None
                            boleto_info = self.buscar_proximo_boleto()
                            if boleto_info:
                                boleto_numero = boleto_info["numero"]
                                indice_boleto = boleto_info["indice"]
                                id_payment = boleto_info["id_payment"]
                                horario_boleto = boleto_info["horario_boleto"]
                            if(not boleto_numero):
                                self.logger(f"Não foi possível encontrar um boleto disponível para a ordem {order_id}. Verifique o Excel de registros.", "ERRO")
                                break       
                            
                            envioMsgAtraso = True
                            if reenviar_boleto_atraso:
                                msgAtraso = ("Olá! Passando para pedir desculpas pela demora no envio do seu boleto. Tivemos uma pequena instabilidade, mas já foi resolvido! 👍")
                                envioMsgAtraso = self.enviarMSG(order_id, buyer_id, msgAtraso, headers, config['ML_SELLER_ID'], executar_reclamacao, claim_id)
                            if envioMsgAtraso:
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
                                                boletos_contagem += 1
                                                planilhaok = self.atualizar_status_boleto(indice_boleto)
                                                if planilhaok:
                                                    if filtrar_reenvio_frase:
                                                       db[order_id]['reenvio_confirmado'] = True
                                                    db[order_id]['boleto_enviado'] = True
                                                    db[order_id]['data_boleto'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                                                    db[order_id]['codigo_boleto'] = boleto_numero
                                                    db[order_id]['id_payment'] = id_payment
                                                    db[order_id]['horario_boleto'] = horario_boleto
                                                    self.salvar_db(db)
                                                    self.logger(f"Boleto enviado com sucesso para a ordem {order_id}!")
                                                    continue
                                                else:
                                                    self.logger(f"Erro ao atualizar status do boleto na planilha para a ordem {order_id}. Verifique o Excel de registros. O processamento será interrompido para evitar mais envios de boletos.", "ERRO")
                                                    break
                                        else:
                                            self.logger(f"Falha ao enviar mensagem de comprovante para a ordem {order_id}: {envioBoletoComprovante}", "ERRO")
                                    else:
                                            self.logger(f"Falha ao enviar código do boleto para a ordem {order_id}: {envioBoleto}", "ERRO")     
                                else:
                                    self.logger(f"Falha ao enviar boleto para a ordem {order_id}: {envio}", "ERRO")  
                            else:
                                self.logger(f"Falha ao enviar mensagem de atraso para a ordem {order_id}", "ERRO")              
                        elif dados_pedido.get('boleto_enviado') and not dados_pedido.get('boleto_pago') and env_erroBoleto:
                            # --- ENVIO ATUALIZAR BOLETO 
                            text = ("Olá, tudo bem?\nPor favor, desconsidere o código de barras enviado anteriormente, pois houve um erro na atualização do sistema.\nSegue o novo código de barras para pagamento da taxa: 👇\n")
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
                                    horario_boleto = boleto_info["horario_boleto"]
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
                                        planilhaok = self.atualizar_status_boleto(indice_boleto)
                                        if planilhaok:
                                                db[order_id]['boleto_enviado'] = True
                                                db[order_id]['data_boleto'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                                                db[order_id]['codigo_boleto'] = boleto_numero
                                                db[order_id]['id_payment'] = id_payment
                                                db[order_id]['horario_boleto'] = horario_boleto
                                                self.salvar_db(db)
                                                self.logger(f"Boleto reenviado com sucesso para a ordem {order_id}!")
                                                continue
                                        else:
                                            self.logger(f"Erro ao atualizar status do boleto na planilha para a ordem {order_id}. Verifique o Excel de registros. O processamento será interrompido para evitar mais envios de boletos.", "ERRO")
                                            break    
                                    else:
                                        self.logger(f"Falha ao enviar mensagem de comprovante para a ordem {order_id}: {envioBoletoComprovante}", "ERRO")
                        elif dados_pedido.get('boleto_enviado') and dados_pedido.get('boleto_pago') and not dados_pedido.get('boleto_pago_agradecimento') and env_boleto_agradecimento:
                            # --- ENVIO AGRADECIMENTO BOLETO PAGO
                            text = (f"Obrigado, o pagamento da taxa foi realizado Vamos dar continuidade a entrega.\nO seu pedido vai chegar {self.var_data_entrega.get().strip()} no período da tarde! 😉")
                            envio = self.enviarMSG(order_id, buyer_id, text, headers, config['ML_SELLER_ID'], executar_reclamacao, claim_id)
                            if envio:
                                db[order_id]['boleto_pago_agradecimento'] = True
                                self.salvar_db(db)
                                self.logger(f"Mensagem de boleto pago enviada para a ordem {order_id}.")
                                continue           
                        elif dados_pedido.get('boleto_enviado') and not dados_pedido.get('boleto_pago') and cobrar_nao_pagos:
                            if dados_pedido.get('cobranca_nao_pago_enviada'):
                                self.logger(f"Ordem {order_id} ignorada: cobranca de nao pago ja enviada.", "AVISO")
                                continue

                            data_boleto = self._texto_para_datetime_db(dados_pedido.get('data_boleto'))
                            if not data_boleto:
                                self.logger(f"Ordem {order_id} ignorada: data_boleto ausente ou invalida.", "AVISO")
                                continue

                            if datetime.now() - data_boleto < timedelta(days=1):
                                self.logger(f"Ordem {order_id} ignorada: boleto enviado ha menos de 1 dia.", "AVISO")
                                continue

                            text = ("Olá! Identificamos que há uma taxa pendente para a liberação do seu pedido. "
                                    "Para que a transportadora possa dar continuidade à entrega, solicitamos o pagamento do valor informado. "
                                    "Caso já tenha efetuado o pagamento, por favor, desconsidere esta mensagem.")
                            envio = self.enviarMSG(order_id, buyer_id, text, headers, config['ML_SELLER_ID'], executar_reclamacao, claim_id)
                            if envio:
                                db[order_id]['cobranca_nao_pago_enviada'] = True
                                db[order_id]['data_cobranca_nao_pago'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                                self.salvar_db(db)
                                self.logger(f"Cobranca de nao pago enviada para a ordem {order_id}.")
                                continue
                            else:
                                self.logger(f"Falha ao enviar cobranca de nao pago para a ordem {order_id}.", "ERRO")
                        elif cobrar_nao_autorizados and not dados_pedido.get('avisoBrinde'):
                            if not dados_pedido.get('boleto_autorizado_msg'):
                                continue

                            if dados_pedido.get('boleto_enviado'):
                                self.logger(f"Ordem {order_id} ignorada: boleto ja enviado.", "AVISO")
                                continue

                            if dados_pedido.get('cliente_autorizou'):
                                self.logger(f"Ordem {order_id} ignorada: cliente ja autorizou com '1'.", "AVISO")
                                continue

                            data_autorizacao = self._texto_para_datetime_db(dados_pedido.get('data_enviado_msg_autorizado'))
                            if  data_autorizacao:
                                if datetime.now() - data_autorizacao < timedelta(days=1):
                                    self.logger(f"Ordem {order_id} ignorada: solicitacao DIGITE 1 enviada ha menos de 1 dia.", "AVISO")
                                    continue
                                
                            text = ("Olá! Precisamos da sua autorização para dar andamento."
                                    "Caso não receba a confirmação, o pedido sera cancelado automaticamente. "
                                    "\nPara receber o boleto da taxa, DIGITE 1.")
                            envio = self.enviarMSG(order_id, buyer_id, text, headers, config['ML_SELLER_ID'], executar_reclamacao, claim_id)
                            
                            if not dados_pedido.get('avisoBrinde'):
                                pasta_imagens_brinde = self.encontrar_pasta_imagens_brindes("Brindes")
                                
                                textoBrinde = ("Tivemos uma taxa de importação de R$ 138,98, um valor abaixo da média aplicada pela Receita Federal para esse tipo de produto.\n\n"
                                               "Para compensar o transtorno, estamos te presenteando com: montagem grátis, " 
                                               "3 vasos de cerâmica, um suporte de TV e 2 puffs para sua sala!")
                                envioBrinde = self.enviarMSG(order_id, buyer_id, textoBrinde, headers, config['ML_SELLER_ID'], executar_reclamacao, claim_id)
                                if envioBrinde:
                                    self.logger(f"Mensagem de brinde enviada para a ordem {order_id}.")
                                    if pasta_imagens_brinde:
                                        envioImagemBrinde = self.enviarImagensML(
                                            order_id, buyer_id, headers,
                                            config['ML_SELLER_ID'], executar_reclamacao, claim_id,
                                            pasta_imagens_brinde
                                        )
                                        if envioImagemBrinde:
                                            self.logger(f"Imagem(ns) de brinde enviada(s) para a ordem {order_id}.")
                                        else:
                                            self.logger(f"Falha ao enviar imagem(ns) de brinde para a ordem {order_id}.", "AVISO")
                                else:
                                    self.logger(f"Falha ao enviar mensagem de brinde para a ordem {order_id}.", "ERRO")
                                                                   
                            if envio:
                                nao_autorizados_contagem += 1
                                db[order_id]['data_enviado_msg_autorizado'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                                db[order_id]['ultima_cobranca_nao_autorizado'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                                db[order_id]['avisoBrinde'] = True
                                self.salvar_db(db)
                                self.logger(f"Mensagem de nao autorizado enviada para a ordem {order_id}.")
                                continue
                            else:
                                self.logger(f"Falha ao enviar mensagem de nao autorizado para a ordem {order_id}.", "ERRO")
                        elif dados_pedido.get('boleto_pago') and dados_pedido.get('boleto_pago_agradecimento') and not dados_pedido.get('cobrado_dobro') and cobrar_dobrado:
                            #COBRAR DOBRO
                            text = (f"Olá, tudo bem?\n\nOcorreu um erro aqui de comunicação com a transportadora e a receita\n\nA taxa era R$238,98 e passaram R$138,98, foi um erro da transportadora\n\nFalta mais R$100 pra pagar a taxa, para a transportadora entregar o seu painel que chegará na {self.var_data_entrega.get().strip()}")
                            envio = self.enviarMSG(order_id, buyer_id, text, headers, config['ML_SELLER_ID'], executar_reclamacao, claim_id)
                            if envio:
                                if cobrar_dobrado_metodo == "pix":
                                    db[order_id]['cobrado_dobro'] = True
                                    db[order_id]['data_cobro_dobro'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                                    db[order_id]['metodo_cobro_dobro'] = "pix"
                                    self.salvar_db(db)
                                    self.logger(f"Mensagem de cobrança dobrada (PIX) enviada para a ordem {order_id}.")
                                    continue
                                else:
                                   db[order_id]['cobrado_dobro'] = True
                                   db[order_id]['data_cobro_dobro'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                                   db[order_id]['metodo_cobro_dobro'] = "boleto"
                                   self.salvar_db(db)
                                   self.logger(f"Mensagem de cobrança dobrada BOLETO enviada para a ordem {order_id}.")
                                   continue         
                            else:
                                self.logger(f"Falha ao enviar mensagem de cobrança dobrada para a ordem {order_id}.", "ERRO")            
                        elif not dados_pedido.get('boleto_enviado') and not dados_pedido.get('boleto_autorizado_msg') and autorizar_boleto and autorizar_contagem < lim_atorizar:
                            # -- AVISO Q TAXOU
                            text = ("Olá, tudo bem?\nO seu painel importado chegou no Brasil. 🥳\nPorém, a Receita Federal taxou o seu produto no valor de R$ 138,98.\n\nÉ necessário realizar o pagamento desta taxa, para dar continuidade na entrega. Caso seja pago hoje, o seu pedido chegará " + self.var_data_entrega.get().strip() + " 😉\n\nO pagamento é feito exclusivamente pelo boleto do Mercado Pago que enviamos. A transportadora utiliza o sistema do Mercado Pago para garantir a segurança da plataforma. Assim que você autorizar, o boleto será gerado.")
                            envio = self.enviarMSG(order_id, buyer_id, text, headers, config['ML_SELLER_ID'], executar_reclamacao, claim_id)
                            if envio:
                                    text = ("DIGITE 1\n\nPara que possamos gerar o boleto para pagamento da taxa e dar continuidade na entrega do seu pedido. 😉")
                                    envioMsgAutorizacao = self.enviarMSG(order_id, buyer_id, text, headers, config['ML_SELLER_ID'], executar_reclamacao, claim_id)
                                    if envioMsgAutorizacao:
                                        autorizar_contagem += 1
                                        db[order_id]['boleto_autorizado_msg'] = True
                                        db[order_id]['data_enviado_msg_autorizado'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                                        self.salvar_db(db)
                                        self.logger(f"Solicitação de autorização de boleto enviada para a ordem {order_id}.")
                                        continue     
                                    else:
                                         self.logger(f"Falha ao enviar solicitação de DIGITE 1 {order_id}", "ERRO")    
                            else:
                                self.logger(f"Falha ao enviar aviso de taxa para a {order_id}", "ERRO")
                                
                        elif dados_pedido.get('cobrado_dobro') and not dados_pedido.get('boleto_pago_dobro') and reenviarBoletoDobrado:
                            metodo = dados_pedido.get('metodo_cobro_dobro', 'boleto')

                            if filtrar_reenvio_dobro_frase and not dados_pedido.get('cliente_autorizou_reenvio_dobro') and not dados_pedido.get('reenvio_confirmado_dobro'):
                                self.logger(f"Ordem {order_id} ignorada: sem frase de autorização de reenvio dobrado.", "AVISO")
                                continue

                            self.logger(f"Reenviando boleto dobrado para a ordem {order_id}...")

                            envioMsgAtraso = True
                            if reenviar_boleto_dobrado_atraso:
                                msgAtraso = ("Olá! Passando para pedir desculpas pela demora no envio do restante da taxa. Tivemos uma pequena instabilidade, mas já foi resolvido! 👍")
                                envioMsgAtraso = self.enviarMSG(order_id, buyer_id, msgAtraso, headers, config['ML_SELLER_ID'], executar_reclamacao, claim_id)

                            if envioMsgAtraso:
                                boleto_numero = None
                                indice_boleto = None
                                id_payment = None
                                boleto_info = self.buscar_proximo_boleto()
                                if boleto_info:
                                    boleto_numero = boleto_info["numero"]
                                    indice_boleto = boleto_info["indice"]
                                    id_payment = boleto_info["id_payment"]
                                    horario_boleto = boleto_info["horario_boleto"]
                                if not boleto_numero:
                                    self.logger(f"Não foi possível encontrar um boleto disponível para a ordem {order_id}. Verifique o Excel de registros.", "ERRO")
                                    break

                                text = ("Vamos gerar o boleto agora mesmo!\n\nProntinho, boleto gerado! Só copiar todo o código de barras abaixo e pagar pelo aplicativo do seu Banco: 👇")
                                envioMsgpreBoleto = self.enviarMSG(order_id, buyer_id, text, headers, config['ML_SELLER_ID'], executar_reclamacao, claim_id)
                                if envioMsgpreBoleto:
                                    text = f"{boleto_numero}"
                                    envioBoleto = self.enviarMSG(order_id, buyer_id, text, headers, config['ML_SELLER_ID'], executar_reclamacao, claim_id)
                                    if envioBoleto:
                                        text = "Esperamos o comprovante! Att, Time Living Shop"
                                        envioBoletoComprovante = self.enviarMSG(order_id, buyer_id, text, headers, config['ML_SELLER_ID'], executar_reclamacao, claim_id)
                                        if envioBoletoComprovante:
                                            planilhaok = self.atualizar_status_boleto(indice_boleto)
                                            if planilhaok:
                                                if filtrar_reenvio_dobro_frase:
                                                    db[order_id]['reenvio_confirmado_dobro'] = True
                                                db[order_id]['codigo_boleto_dobro'] = boleto_numero
                                                db[order_id]['id_payment_dobro'] = id_payment
                                                db[order_id]['horario_boleto_dobro'] = horario_boleto
                                                db[order_id]['data_reenvio_dobro'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                                                self.salvar_db(db)
                                                self.logger(f"Boleto dobrado reenviado com sucesso para a ordem {order_id}!")
                                                continue
                                            else:
                                                self.logger(f"Erro ao atualizar status do boleto na planilha para a ordem {order_id}. Verifique o Excel de registros. O processamento será interrompido para evitar mais envios de boletos.", "ERRO")
                                                break
                                        else:
                                            self.logger(f"Falha ao enviar mensagem de comprovante para a ordem {order_id}.", "ERRO")
                                    else:
                                        self.logger(f"Falha ao enviar código do boleto para a ordem {order_id}.", "ERRO")
                                else:
                                    self.logger(f"Falha ao enviar mensagem pré boleto (dobro) para a ordem {order_id}.", "ERRO")
                            else:
                                self.logger(f"Falha ao enviar mensagem de atraso (dobro) para a ordem {order_id}.", "ERRO")      
                    except Exception as e:
                        self.logger(f"Erro ao verificar data de envio do rastreio para a ordem {order_id}: {str(e)}", "ERRO")
                
                    
           
                #VERIFICAR SE A DATA INICIAL SE PASSOU 4 OU 5 DIAS ENVIAR CODIGO DE RASTREIO 
                #VERIFICAR SE A DATA INICIAL SE PASSOU 4 OU 5 DIAS ENVIAR CODIGO DE RASTREIO 
                if order_id in db and (dados_pedido.get('solicitado') and dados_pedido.get('data_solicitacao_inicial')):
                    #data_solicitacao_inicial = dados_pedido.get('data_solicitacao_inicial')
                    try:
                        self._check_stop()
                        #data_envio = datetime.strptime(data_solicitacao_inicial, "%d/%m/%Y %H:%M")
                        #diferenca = datetime.now() - data_envio
                        if env_rastreio and rastreios_contagem < lim_rastreio and not dados_pedido.get('rastreio_enviado'): 
                            self.logger(f"Enviando código de rastreio para a ordem {order_id}...")
                            # -- ENVIO RASTREIO
                            if tipomsgRastreio == 2:
                                text = textwrap.dedent(f"""\
                                            ACOMPANHE O SEU PEDIDO
                                            Seu pedido já foi postado. Segue abaixo, seu código de rastreamento:
                                            
                                            >>> {cod_rastreio} 

                                            Para rastrear, basta acessar o site da 4tracking e colar o código, só colocar no google 4tracking,é o site que faz o rastreio da transportadora.
                                            👉 https://www.4tracking.net/pt/tjax/track?nums={cod_rastreio}
                                            
                                            Lembrando que:
                                            
                                            O produto é importado e PODE SER TAXADO, mas é bem difícil! O pedido é entregue pela transportadora, os Correios apenas fazem o rastreamento e podem demorar até 3 dias para atualizar o status. Mas não se preocupe, o seu pedido já está a caminho.
                                            
                                            Dúvidas? Estamos à disposição! 😉
                                            
                                            ( Living Shop )""").strip()
                            else: 
                                text = textwrap.dedent(f"""\
                                            ACOMPANHE O SEU PEDIDO
                                            Segue abaixo o seu código de rastreamento:
                                            
                                            >>> {cod_rastreio} 

                                            Para rastrear, basta acessar o site oficial dos Correios 👇
                                            https://rastreamento.correios.com.br/app/index.php

                                            Lembrando que:

                                            O produto é importado e PODE SER TAXADO, mas é bem difícil! O pedido é entregue pela transportadora, os Correios apenas fazem o rastreamento e podem demorar até 3 dias para atualizar o status. Mas não se preocupe, o seu pedido já está a caminho.
                                            
                                            Dúvidas? Estamos à disposição! 😉
                                            
                                            ( Living Shop )""").strip()
                                   
                            
                            # --- ENVIO DA MENSAGEM (Caso não esteja no DB e não esteja no Chat) ---
                            envio = self.enviarMSG(order_id, buyer_id, text, headers, config['ML_SELLER_ID'], executar_reclamacao, claim_id)
                            if(envio):
                                db[order_id]['rastreio_enviado'] = True
                                db[order_id]['data_rastreio'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                                db[order_id]['codigo_rastreio'] = cod_rastreio
                                rastreios_contagem += 1
                                self.salvar_db(db)
                                if not executar_reclamacao and not dados_pedido.get('numero_extraido'):
                                    textencerrar = "Olá! Não recebemos seu telefone.\nA transportadora precisa para avisar as atualizações da entrega."
                                    envioComun = self.enviarMSG(order_id, buyer_id, textencerrar, headers, config['ML_SELLER_ID'], 
                                                        bool(claim_id), claim_id)
                                    if envioComun:
                                        self.logger(f"msg pedir numero apos rastreio enviada! {order_id}")
                                elif executar_reclamacao:
                                    textreclamacao = textwrap.dedent(f"""\
                                    O seu pedido já foi enviado e está a caminho.
                                        
                                    Por gentileza, pedimos que encerre a reclamação. Agradecemos pela compreensão! 📦""").strip()

                                    envioReclamacao = self.enviarMSG(order_id, buyer_id, textreclamacao, headers, config['ML_SELLER_ID'], 
                                                                bool(claim_id), claim_id)
                                    if envioReclamacao:
                                        self.logger(f"pedir para Encerrar Reclamação enviada apos rastreio para a ordem {order_id}")
                            else:
                                self.logger(f"Falha ao enviar código de rastreio para a ordem {order_id}: ", "ERRO")
                            continue
                    except Exception as e:
                        self.logger(f"Erro ao verificar data inicial da ordem {order_id}: {str(e)}", "ERRO")
                
                # --- TRATATIVA 2: Validar se a mensagem já existe no chat ---
                if solicitar:
                    if (executar_reclamacao and not dados_pedido.get('solicitado')) or executar_reclamacao == False:
                        conversaCompleta = self.obter_conversa_completa(order_id, order_id, config['ML_SELLER_ID'], token)
                        if order_id in db and (dados_pedido.get('solicitado') and not dados_pedido.get('numero_extraido')):
                            for m in conversaCompleta:
                                texto = m.get('texto', '')
                                # Regex robusto para capturar vários formatos de telefone BR
                                match = re.search(r'(?:\+?55\s?)?0?\(?(\d{2})\)?\s*(9)?\s*(\d{4,5})\s*[\s.-]?\s*(\d{4})', texto)
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
                                        elif dados_pedido.get('rastreio_enviado') and not dados_pedido.get('boleto_enviado'):
                                            text = "Olá! recebemos seu telefone. Obrigado!😉"
                                            envio = self.enviarMSG(order_id, buyer_id, text, headers, config['ML_SELLER_ID'], executar_reclamacao, claim_id)  
                                           
                                        break
                         
                        if order_id in db:
                            data_solicitacao = dados_pedido.get('data_solicitacao')
                            if data_solicitacao:
                                try:
                                    data_envio = datetime.strptime(data_solicitacao, "%d/%m/%Y %H:%M")
                                    diferenca = datetime.now() - data_envio
                                    if diferenca.days >= 1 and not dados_pedido.get('numero_extraido') and dados_pedido.get('tentativa_', 0) < 2 and not dados_pedido.get('boleto_enviado'):
                                        if(not dados_pedido.get('rastreio_enviado')):
                                            # -- COBRAR NUMERO TELEFONE
                                            text = "Olá! Não recebemos o seu telefone. \nA transportadora precisa pra preencher os seus dados de entrega e enviar o código de rastreio pra você acompanhar."
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
                            if executar_reclamacao:   
                                try:   
                                    if not dados_pedido.get('boleto_enviado') and solicitar and not dados_pedido.get('boleto_autorizado_msg'):
                                        self.enviar_msg_encerrar_reclamacao(order_id, db[order_id]['buyer_id'], headers, config['ML_SELLER_ID'], claim_id, db)
                                except Exception as e:
                                    self.logger(f"Erro ao enviar mensagem de encerramento para ordem {order_id}: {e}", "ERRO")        
                            self.logger(f"Mensagem já Enviada no chat da Ordem {order_id}...")
                            continue

                        self.logger(f"Verificando histórico de mensagens para Ordem: {order_id}")
                        
                        
                        # Verifica se algum texto no histórico contém nosso texto padrão
                        msg_padrao_parte = "Olá, tudo bem? O frete é grátis para todo Brasil"
                        ja_enviado_no_ml = self.mensagem_existe_no_historico(msg_padrao_parte, conversaCompleta)

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
                    elif executar_reclamacao:
                        self.logger(f"Modo reclamação ativado: pulando solicitação de telefone para a ordem {order_id}.")
                        
                    if executar_reclamacao:   
                        try:   
                            if not dados_pedido.get('boleto_enviado') and solicitar and not dados_pedido.get('boleto_autorizado_msg'):
                                dontuse = self.enviar_msg_encerrar_reclamacao(order_id, db[order_id]['buyer_id'], headers, config['ML_SELLER_ID'], claim_id, db)
                                # Agora a função já salva internamente, retorna apenas True/False
                        except Exception as e:
                            self.logger(f"Erro ao enviar mensagem de encerramento para ordem {order_id}: {e}", "ERRO")        

                self.logger(f"Processamento da ordem {order_id} concluído. Próxima ordem...")
                
                
            # Salva o progresso no banco de dados local
            self.salvar_db(db)
            self.logger(f"Fim da Execução. Novas solicitações enviadas: {enviados}")

        except ProcessamentoInterrompido:
            self.logger("Processamento interrompido com força pelo usuário.", "ERRO")
        except Exception as e:
            self.logger(f"Erro no Passo 1: {str(e)}", "ERRO")
        finally:
            if hasattr(self, 'btn_stop'):
                self.btn_stop.config(state=tk.DISABLED, text="STOP URGENTE", bg="#FF0000")
            self.stop_event.clear()
            
    def buscar_proximo_boleto(self):
        folder = self.get_pasta_conta()
        if not folder:
            return None
        
        caminho_excel = os.path.join(folder, "registros_pedidos.xlsx")
        
        try:
            df = pd.read_excel(caminho_excel)
            
            for index, row in df.iterrows():
                # Verifica se o boleto não foi usado
                if str(row['Boleto Usado']) == 'False':
                    return {
                        "numero": str(row['Código']),
                        "indice": index,
                        "id_payment": str(row['id_payment']),
                        "horario_boleto": str(row['Horário'])
                    }
            
            return None  # Retorna None se não encontrar nenhum disponível
            
        except Exception as e:
            self.logger(f"Erro ao ler planilha de boletos: {e}")
            return None
    def executar_reclamacao_shipping(self,pedido, tipo, ACCESS_TOKEN):
        headers = {
            "Authorization": f"Bearer {ACCESS_TOKEN}"
        }

        if tipo == "by_id":
            order_id = str(pedido['id'])
            claim_id = str(pedido['claim_id'])
        else:
            claim_id = str(pedido['id'])
            resource_type = pedido.get('resource')
            resource_id = pedido.get('resource_id')

            order_id_resolvido = str(pedido.get("order_id_resolvido") or "").strip()

            # Se o recurso for um envio (shipment), precisamos descobrir a ordem vinculada a ele
            if order_id_resolvido:
                order_id = order_id_resolvido
            elif resource_type == 'shipment' or str(resource_id).startswith('47'):
                try:
                    url_shipment = f"https://api.mercadolibre.com/shipments/{resource_id}"
                    response = SESSION.get(url_shipment, headers=headers)
                    
                    if response.status_code == 200:
                        shipment_data = response.json()
                        # Buscamos o ID da ordem de dentro do objeto do envio
                        order_id = str(shipment_data.get('order_id'))
                    else:
                        print(f"Erro ao buscar shipment {resource_id}: {response.status_code}")
                        return None
                except Exception as e:
                    print(f"Erro na requisição do shipment: {e}")
                    return None
            else:
                # Se já for 'order', o resource_id é o próprio order_id
                order_id = str(resource_id)

        # A partir daqui, você já tem o `order_id` e o `claim_id` corretos
        print(f"Claim ID: {claim_id} | Order ID final: {order_id}")
        
        # Prossiga com a sua lógica de consulta da ordem ou mediação...
        return order_id, claim_id  
        
    def atualizar_status_boleto(self, indice, status="TRUE"):
        folder = self.get_pasta_conta()
        if not folder:
            return False
        
        caminho_excel = os.path.join(folder, "registros_pedidos.xlsx")
        try:
            # Carrega a planilha atualizada
            df = pd.read_excel(caminho_excel)
            
            # Converte o valor de status para booleano
            if isinstance(status, str):
                status_bool = status.upper() == "TRUE"
            else:
                status_bool = bool(status)
            
            # Atualiza o valor no índice específico
            df.at[indice, 'Boleto Usado'] = status_bool
            
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
        self._check_stop()
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
            for _ in range(10):
                self._check_stop()
                time.sleep(0.1)
            return self.enviarMsgML(order_id, buyer_id, texto_ml, headers, seller_id, reclamacao, claim_id)     
        
    def enviarMsgML(self, order_id, buyer_id, texto, headers, ML_SELLER_ID, reclamacao, claim_id): 
        self._check_stop()
        if reclamacao:
            url_msg = f"https://api.mercadolibre.com/post-purchase/v1/claims/{claim_id}/actions/send-message"
            payload = { 
                "receiver_role": "complainant",
                "message": texto
            }
            try:
                envio = SESSION.post(url_msg, json=payload, headers=headers, timeout=15)
                if envio.status_code in [200, 201]:
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
                envio = SESSION.post(url_msg, json=payload, headers=headers, timeout=15)
                return envio.status_code in [200, 201]
            except Exception as e:
                self.logger(f"Erro ao enviar mensagem COMUM para {buyer_id}: {str(e)}", "ERRO")
                return False
    
    def enviarImagensML(self, order_id, buyer_id, headers, ML_SELLER_ID,reclamacao, claim_id, pasta_imagens, site_id="MLB"):
        """
        Envia uma mensagem contendo APENAS as imagens (sem texto),
        anexando todas as imagens encontradas na pasta.
        pasta_imagens: caminho já resolvido (ex: retorno de encontrar_pasta_imagens_brindes).
        """
        self._check_stop()

        extensoes_validas = (".jpg", ".jpeg", ".png")
        try:
            arquivos = [
                os.path.join(pasta_imagens, f)
                for f in os.listdir(pasta_imagens)
                if f.lower().endswith(extensoes_validas)
            ]
        except Exception as e:
            self.logger(f"Erro ao ler pasta de imagens '{pasta_imagens}': {str(e)}", "ERRO")
            return False

        if not arquivos:
            self.logger(f"Nenhuma imagem encontrada em '{pasta_imagens}'", "AVISO")
            return False

        if reclamacao:
            url_upload = f"https://api.mercadolibre.com/post-purchase/v1/claims/{claim_id}/attachments"
        else:
            url_upload = f"https://api.mercadolibre.com/messages/attachments?tag=post_sale&site_id={site_id}"

        headers_upload = {k: v for k, v in headers.items() if k.lower() != "content-type"}

        attachment_ids = []
        for caminho in arquivos:
            self._check_stop()
            try:
                with open(caminho, "rb") as f:
                    resp = SESSION.post(
                        url_upload,
                        headers=headers_upload,
                        files={"file": f},
                        timeout=15
                    )
                if resp.status_code in [200, 201]:
                    dados = resp.json()
                    anexo_id = dados.get("filename") or dados.get("id")
                    if anexo_id:
                        attachment_ids.append(anexo_id)
                        self.logger(f"Imagem '{os.path.basename(caminho)}' enviada com sucesso (id: {anexo_id})", "INFO")
                else:
                    self.logger(f"Falha ao subir imagem '{caminho}': {resp.status_code} - {resp.text}", "ERRO")
            except Exception as e:
                self.logger(f"Erro ao subir imagem '{caminho}': {str(e)}", "ERRO")

        if not attachment_ids:
            self.logger(f"Nenhuma imagem foi enviada com sucesso para {buyer_id}", "ERRO")
            return False

        try:
            if reclamacao:
                url_msg = f"https://api.mercadolibre.com/post-purchase/v1/claims/{claim_id}/actions/send-message"
                payload = {
                    "receiver_role": "complainant",
                    "message": "",
                    "attachments": attachment_ids
                }
            else:
                url_msg = f"https://api.mercadolibre.com/messages/packs/{order_id}/sellers/{ML_SELLER_ID}?tag=post_sale"
                payload = {
                    "from": {"user_id": ML_SELLER_ID},
                    "to": {"user_id": buyer_id},
                    "text": "",
                    "attachments": attachment_ids
                }

            envio = SESSION.post(url_msg, json=payload, headers=headers, timeout=15)
            if envio.status_code in [200, 201]:
                self.logger(f"Mensagem com {len(attachment_ids)} imagem(ns) enviada para {buyer_id}", "SUCESSO")
                return True
            else:
                self.logger(f"Falha ao enviar mensagem com imagens para {buyer_id}: {envio.status_code} - {envio.text}", "ERRO")
                return False
        except Exception as e:
            self.logger(f"Erro ao enviar mensagem com imagens para {buyer_id}: {str(e)}", "ERRO")
            return False
    
    def enviar_msg_encerrar_reclamacao(self, order_id, buyer_id, headers, ML_SELLER_ID, claim_id, db):
        """
        Envia mensagem para o cliente encerrar a reclamação.
        Máximo 2x por ordem, apenas se o boleto ainda não foi enviado.
        Retorna: True se enviou e salvou, False caso contrário
        """
        # Usa o db passado como parâmetro (não carrega novamente!)
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
        
        # Verificar se já foi enviada uma mensagem e se passou menos de 1 dia
        data_ultimo_envio_str = dados_pedido.get('data_ultimo_envio_encerrar')
        if data_ultimo_envio_str:
            data_ultimo_envio = datetime.strptime(data_ultimo_envio_str, "%d/%m/%Y %H:%M")
            diferenca = datetime.now() - data_ultimo_envio
            if diferenca.days < 1:  # CORRIGIDO: Bloqueia se MENOS de 1 dia passou
                self.logger(f"Ordem {order_id}: Última mensagem de encerramento enviada há menos de 1 dia. Aguardando para reenviar.")
                return False
        
        msg_encerramento = "Poderia encerrar a reclamação, Esse passo é necessário para que o sistema libere a continuidade da sua entrega."
        # Preparar e enviar a mensagem
        if qtd_envios >= 1:
           msg_encerramento = "Você deseja continuar ou cancelar a sua compra? Aguardamos seu retorno até amanhã para evitar o cancelamento automático."
        
        url_msg = f"https://api.mercadolibre.com/post-purchase/v1/claims/{claim_id}/actions/send-message"
        
        payload = {
            "receiver_role": "complainant",
            "message": msg_encerramento
        }
        
        try:
            envio = SESSION.post(url_msg, json=payload, headers=headers)
            self.logger(f"Ordem {order_id}: Status da API = {envio.status_code}")
            
            if envio.status_code in [200, 201]:
                # Incrementar contador e salvar AQUI MESMO
                if order_id not in db:
                    db[order_id] = {}
                
                db[order_id]['QtdenvioEncerrarReclamacao'] = qtd_envios + 1
                db[order_id]['data_ultimo_envio_encerrar'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                
                self.logger(f"Ordem {order_id}: Antes de salvar - QtdenvioEncerrarReclamacao={db[order_id].get('QtdenvioEncerrarReclamacao')}, data={db[order_id].get('data_ultimo_envio_encerrar')}")
                
                save_result = self.salvar_db(db)
                
                self.logger(f"Ordem {order_id}: Save result = {save_result}")
                self.logger(f"Ordem {order_id}: Mensagem de encerramento enviada ({qtd_envios + 1}/2).")
                return True
            else:
                self.logger(f"Erro ao enviar mensagem de encerramento para {order_id}: Status {envio.status_code}", "AVISO")
                return False
                
        except Exception as e:
            self.logger(f"Erro ao enviar mensagem de encerramento para {order_id}: {str(e)}", "ERRO")
            return False
            
    def _chave_ordenacao_data(self, msg):
        """
        Converte o campo 'data' de uma mensagem em um datetime comparável,
        independente de vir como:
          - string ISO (mensagens de Reclamação), ex: '2026-07-07T15:30:35.648-04:00'
          - dict (mensagens de Chat Comum), ex:
            {'received':..., 'available':..., 'notified':..., 'created':..., 'read':...}
        """
        data = msg.get('data') if isinstance(msg, dict) else None

        # Se for dict (Chat Comum), pega o timestamp mais representativo da criação
        if isinstance(data, dict):
            data = (
                data.get('created') or
                data.get('received') or
                data.get('notified') or
                data.get('available') or
                data.get('read')
            )

        if not data or not isinstance(data, str):
            # Sem data válida: joga para o início para não bagunçar o restante
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

    def obter_conversa_completa(self, order_id, pack_id, seller_id, token, claim_id=None):
        headers = {"Authorization": f"Bearer {token}"}
        conversa_unificada = []
        claim_ids = []

        # --- PARTE A: Chat de Pós-Venda Comum (com paginação completa) ---
        url_comum = f"https://api.mercadolibre.com/messages/packs/{pack_id}/sellers/{seller_id}"
        limit = 10
        offset = 0
        total = None

        try:
            while True:
                params = {"tag": "post_sale", "limit": limit, "offset": offset}
                res_comum = SESSION.get(url_comum, headers=headers, params=params, timeout=10)

                if res_comum.status_code != 200:
                    self.logger(
                        f"Erro ao buscar chat comum {order_id} (offset {offset}): "
                        f"Status {res_comum.status_code}",
                        "AVISO"
                    )
                    break

                dados = res_comum.json()
                msgs = dados.get('messages', []) or []

                # Extração correta dos claim_ids (atualiza a cada página, caso venha)
                status_conversa = dados.get('conversation_status', {})
                if status_conversa.get('claim_ids'):
                    claim_ids = status_conversa.get('claim_ids', [])

                for m in msgs:
                    sender_id = (
                        m.get('from', {}).get('user_id') or
                        m.get('sender', {}).get('user_id') or
                        m.get('sender_id')
                    )
                    conversa_unificada.append({
                        "origem": "Chat Comum",
                        "texto": m.get('text'),
                        "data": m.get('message_date'),
                        "sender_id": sender_id,
                        "is_seller": str(sender_id) == str(seller_id)
                    })

                # Descobre o total de mensagens a partir da paginação da API
                paging = dados.get('paging', {}) or {}
                total = paging.get('total', len(msgs) if total is None else total)

                offset += limit

                # Para quando não há mais mensagens nesta página ou já atingimos o total
                if not msgs or offset >= (total or 0):
                    break

        except Exception as e:
            self.logger(f"Erro ao buscar chat comum {order_id}: {e}")

        # --- PARTE B: Chat de Reclamação (Claim) ---
        if claim_id and str(claim_id) not in [str(cid) for cid in claim_ids]:
            claim_ids.append(claim_id)

        if(len(claim_ids) > 0):
            for claim_id in claim_ids:
                try:
                    url_msg_claim = f"https://api.mercadolibre.com/post-purchase/v1/claims/{claim_id}/messages"
                    res_msg_claim = SESSION.get(url_msg_claim, headers=headers, timeout=10)
                    
                    if res_msg_claim.status_code == 200:
                        dados_claim = res_msg_claim.json()
                        if isinstance(dados_claim, dict):
                            msgs_claim = dados_claim.get("messages") or dados_claim.get("data") or []
                        else:
                            msgs_claim = dados_claim

                        for mc in msgs_claim:
                            if not isinstance(mc, dict):
                                continue
                            sender = mc.get("sender") if isinstance(mc.get("sender"), dict) else {}
                            sender_id = sender.get("id") or sender.get("user_id") or mc.get("sender_id")
                            sender_role = mc.get("sender_role") or mc.get("role") or sender.get("role")
                            sender_role_text = str(sender_role or "").lower()
                            conversa_unificada.append({
                                "origem": f"Reclamação ({claim_id})",
                                "texto": mc.get('message') or mc.get('text'),
                                "data": mc.get('date_created') or mc.get('message_date'),
                                "sender_id": sender_id,
                                "sender_role": sender_role,
                                "is_seller": str(sender_id) == str(seller_id) or sender_role_text in ["respondent", "seller"],
                            })  
                except Exception as e:
                    self.logger(f"Erro na reclamação {claim_id}: {e}")

        conversa_unificada = sorted(conversa_unificada, key=self._chave_ordenacao_data)

        return conversa_unificada

    def _normalizar_texto(self, texto):
        if not texto:
            return ''
        if not isinstance(texto, str):
            texto = str(texto)
        texto = unicodedata.normalize('NFKC', texto)
        texto = texto.lower()
        texto = re.sub(r'\s+', ' ', texto).strip()
        return texto

    def mensagem_existe_no_historico(self, trecho, conversa):
        trecho_norm = self._normalizar_texto(trecho)
        for m in conversa:
            texto = m.get('texto') or m.get('text') or m.get('message') or ''
            if trecho_norm in self._normalizar_texto(texto):
                return True
        return False

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
            res = SESSION.post(url_wa, json=payload, headers=headers)
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
        Tenta múltiplos caminhos para funcionar tanto do VS Code quanto do APK/dist
        """
        # Lista de caminhos a tentar
        caminhos_possíveis = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config_wpp.json'),  # Script dir
            os.path.join(os.getcwd(), 'config_wpp.json'),  # Diretório de trabalho
            os.path.join(os.path.dirname(os.getcwd()), 'config_wpp.json'),  # Diretório pai
        ]
        
        config_path = None
        for caminho in caminhos_possíveis:
            if os.path.exists(caminho):
                config_path = caminho
                break
        
        if not config_path:
            self.logger(f"Arquivo config_wpp.json não encontrado em nenhum caminho esperado.", "ERRO")
            return None
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            self.logger(f"Erro ao carregar config_wpp.json: {str(e)}", "ERRO")
            return None

    def salvar_config_wpp(self, config_wpp):
        """
        Salva a configuração atualizada dos WhatsApps
        Tenta múltiplos caminhos para funcionar tanto do VS Code quanto do APK/dist
        """
        # Tenta primeiro no diretório do script
        caminhos_possíveis = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config_wpp.json'),  # Script dir
            os.path.join(os.getcwd(), 'config_wpp.json'),  # Diretório de trabalho
        ]
        
        config_path = None
        
        # Se o arquivo já existe em algum dos caminhos, salva lá
        for caminho in caminhos_possíveis:
            if os.path.exists(caminho):
                config_path = caminho
                break
        
        # Se não existe em lugar nenhum, cria no diretório do script
        if not config_path:
            config_path = caminhos_possíveis[0]
        
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config_wpp, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            self.logger(f"Erro ao salvar config_wpp.json em {config_path}: {str(e)}", "ERRO")
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
            
            response = SESSION.post(url_wa, json=payload, headers=headers, timeout=15, verify=False)
            
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
    def obter_produto_ml(self, order_id, token, all = False):
        try:
            res = SESSION.get(f"https://api.mercadolibre.com/orders/{order_id}", headers={'Authorization': f'Bearer {token}'})
            if all:
                return res.json()
            return res.json()['order_items'][0]['item']['title']
        except: return "Produto ML"

    def obter_nome_cliente(self, order_id, token):
        try:
            res = SESSION.get(f"https://api.mercadolibre.com/orders/{order_id}", headers={'Authorization': f'Bearer {token}'})
            return res.json()['buyer']['first_name']
        except: return "Cliente"

    # # ALTERAÇÃO: Ajustado para usar a pasta do e-mail
    def carregar_db(self):
        folder = self.get_pasta_conta()
        if not folder:
            # Se get_pasta_conta() falhar, tenta usar ACCOUNTS_DIR diretamente
            self.logger("Aviso: get_pasta_conta() falhou, usando ACCOUNTS_DIR como fallback.", "AVISO")
            if not ACCOUNTS_DIR or not os.path.exists(ACCOUNTS_DIR):
                return {}
            folder = ACCOUNTS_DIR
        
        db_path = os.path.join(folder, "database_vendas.json")
        
        # Se a pasta não existir, cria
        if not os.path.exists(folder):
            try:
                os.makedirs(folder, exist_ok=True)
            except Exception as e:
                self.logger(f"Erro ao criar pasta {folder}: {e}", "ERRO")
                return {}
        
        # Se o arquivo não existir, retorna dicionário vazio
        if not os.path.exists(db_path):
            return {}
        
        try:
            with open(db_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            self.logger(f"Erro ao carregar banco de dados: {e}", "ERRO")
            return {}

    # # ALTERAÇÃO: Ajustado para salvar na pasta do e-mail
    def salvar_db(self, db):
        folder = self.get_pasta_conta()
        if not folder:
            # Se get_pasta_conta() falhar, tenta usar ACCOUNTS_DIR diretamente
            self.logger("Aviso: get_pasta_conta() falhou, usando ACCOUNTS_DIR como fallback.", "AVISO")
            if not ACCOUNTS_DIR:
                self.logger("Erro: Não conseguiu determinar a pasta de contas.", "ERRO")
                return
            folder = ACCOUNTS_DIR
        
        # Se a pasta não existir, cria
        if not os.path.exists(folder):
            try:
                os.makedirs(folder, exist_ok=True)
            except Exception as e:
                self.logger(f"Erro ao criar pasta {folder}: {e}", "ERRO")
                return
        
        db_path = os.path.join(folder, "database_vendas.json")
        try:
            with open(db_path, 'w', encoding='utf-8') as f:
                json.dump(db, f, indent=4)
        except Exception as e:
            self.logger(f"Erro ao salvar banco de dados: {e}", "ERRO")
                
    def buscar_todas_reclamacoes(self, token, offset=0):
        reclamacoes_completas = []
        limit = 50
        offset = int(offset)
        
        while True:
                # Filtramos apenas pelas abertas (opened)
                url = f"https://api.mercadolibre.com/post-purchase/v1/claims/search?status=opened&limit={limit}&offset={offset}"
                headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}
                
                try:
                    self.logger(f"Buscando offset {offset}...")   
                    response = SESSION.get(url, headers=headers)
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
                
        # Preenche a data da venda original para cada reclamação e ordena
        claims_com_data_venda = []
        for claim in reclamacoes_completas:
            sale_date = "9999-12-31T23:59:59.000Z"
            if claim.get('resource') == 'order' and claim.get('resource_id'):
                order_id = claim.get('resource_id')
                try:
                    url_order = f"https://api.mercadolibre.com/orders/{order_id}"
                    response_order = SESSION.get(url_order, headers={'Authorization': f'Bearer {token}'}, timeout=10)
                    if response_order.status_code == 200:
                        order_info = response_order.json()
                        sale_date = order_info.get('date_created', sale_date)
                    else:
                        self.logger(f"Falha ao buscar ordem {order_id}: {response_order.status_code}", "AVISO")
                except Exception as e:
                    self.logger(f"Erro ao buscar data da ordem {order_id}: {e}", "AVISO")
            claim['sale_date'] = sale_date
            claims_com_data_venda.append(claim)

        claims_ordenados = sorted(claims_com_data_venda, key=lambda x: x.get('sale_date', "9999-12-31T23:59:59.000Z"))
        return claims_ordenados, len(claims_ordenados)
        
    def _texto_para_datetime_db(self, valor):
        if not valor:
            return None
        texto = str(valor).strip()
        formatos = ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d")
        for formato in formatos:
            try:
                return datetime.strptime(texto, formato)
            except ValueError:
                pass
        try:
            return datetime.fromisoformat(texto)
        except ValueError:
            return None

    def _data_rastreio_para_dia(self, valor):
        data = self._texto_para_datetime_db(valor)
        if not data:
            return None
        return data.date()

    def calcular_lotes_rastreio(self, db=None):
        if db is None:
            db = self.carregar_db()

        por_dia = {}
        for order_id, dados in db.items():
            if not isinstance(dados, dict) or not dados.get('rastreio_enviado'):
                continue
            dia = self._data_rastreio_para_dia(dados.get('data_rastreio'))
            if dia is None:
                continue
            por_dia.setdefault(dia, []).append(str(order_id))

        lotes = []
        for numero, dia in enumerate(sorted(por_dia.keys()), start=1):
            ids = sorted(por_dia[dia])
            lotes.append({
                "numero": numero,
                "data": dia,
                "data_label": dia.strftime("%d/%m/%Y"),
                "ids": ids,
                "quantidade": len(ids),
            })
        return lotes

    def selecionar_filtro_lote(self, acao_label):
        self.root.lift()
        self.root.focus_force()

        usar_lote = messagebox.askyesnocancel(
            "Modo de processamento",
            f"Deseja {acao_label} por lote?\n\nSim = escolher lote\nNao = sequencial atual\nCancelar = cancelar",
            parent=self.root
        )
        if usar_lote is None:
            return False, None, None
        if usar_lote is False:
            self.logger(f"Modo sequencial selecionado para {acao_label}.", "INFO")
            return True, None, None

        lotes = self.calcular_lotes_rastreio()
        if not lotes:
            messagebox.showinfo("Lotes", "Nenhum lote encontrado com data_rastreio.", parent=self.root)
            return False, None, None

        resumo = "\n".join(
            f"Lote {lote['numero']} - {lote['data_label']} - {lote['quantidade']} ordens"
            for lote in lotes[:20]
        )
        if len(lotes) > 20:
            resumo += f"\n... mais {len(lotes) - 20} lotes"

        lote_numero = simpledialog.askinteger(
            "Selecionar lote",
            f"Informe o numero do lote:\n\n{resumo}",
            minvalue=1,
            maxvalue=len(lotes),
            parent=self.root
        )
        if not lote_numero:
            return False, None, None

        lote = lotes[lote_numero - 1]
        self.logger(
            f"Modo por lote selecionado para {acao_label}: lote {lote_numero} ({lote['data_label']}) com {lote['quantidade']} ordens.",
            "INFO"
        )
        return True, lote_numero, set(lote["ids"])

    
    
    def abrir_dashboard_lotes(self):
        db = self.carregar_db()
        lotes = self.calcular_lotes_rastreio(db)
        if not lotes:
            messagebox.showinfo("Dashboard Lotes", "Nenhum lote encontrado com data_rastreio.")
            return

        dash_win = tk.Toplevel(self.root)
        dash_win.title("Dashboard - Lotes por Data de Rastreio")
        dash_win.geometry("1050x800")
        dash_win.minsize(900, 500)
        dash_win.resizable(True, True)
        dash_win.configure(bg="#f8f9fa")

        main_frame = tk.Frame(dash_win, bg="#f8f9fa")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # ================= FILTRO =================
        filtro_frame = tk.Frame(main_frame, bg="#f8f9fa")
        filtro_frame.pack(fill=tk.X, pady=(0, 10))

        tk.Label(filtro_frame, text="Filtrar Ordem (ID ou parte do ID):",
                 bg="#f8f9fa", font=("Arial", 9, "bold")).pack(side=tk.LEFT, padx=(0, 8))

        var_filtro = tk.StringVar()
        entry_filtro = tk.Entry(filtro_frame, textvariable=var_filtro, width=30)
        entry_filtro.pack(side=tk.LEFT, padx=(0, 8))

        def _limpar_filtro():
            var_filtro.set("")
            _redesenhar()

        tk.Button(filtro_frame, text="Filtrar", command=lambda: _redesenhar(),
                  bg="#17a2b8", fg="white", font=("Arial", 9, "bold")).pack(side=tk.LEFT, padx=(0, 5))
        tk.Button(filtro_frame, text="Limpar", command=_limpar_filtro).pack(side=tk.LEFT)

        # Filtra também ao apertar Enter
        entry_filtro.bind("<Return>", lambda e: _redesenhar())

        content_frame = tk.Frame(main_frame, bg="#f8f9fa")
        content_frame.pack(fill=tk.BOTH, expand=True)

        def _redesenhar():
            for widget in content_frame.winfo_children():
                widget.destroy()

            termo = var_filtro.get().strip().lower()

            # Recalcula os lotes considerando o filtro (só entram ordens que batem)
            lotes_filtrados = []
            for lote in lotes:
                if termo:
                    ids_filtrados = [oid for oid in lote["ids"] if termo in oid.lower()]
                else:
                    ids_filtrados = lote["ids"]

                if ids_filtrados:
                    lotes_filtrados.append({
                        **lote,
                        "ids": ids_filtrados,
                        "quantidade": len(ids_filtrados),
                    })

            if not lotes_filtrados:
                tk.Label(content_frame, text="Nenhuma ordem encontrada para o filtro informado.",
                         bg="#f8f9fa", fg="#c00", font=("Arial", 11, "bold")).pack(pady=40)
                return

            fig = Figure(figsize=(6, 5), dpi=100)
            ax = fig.add_subplot(111)
            fig.patch.set_facecolor('#f8f9fa')

            nomes = [f"Lote {lote['numero']}\n{lote['data_label']}" for lote in lotes_filtrados]
            valores = [lote["quantidade"] for lote in lotes_filtrados]
            bars = ax.bar(nomes, valores, color="#17a2b8", width=0.6)
            ax.yaxis.set_major_locator(MaxNLocator(integer=True))
            titulo_grafico = "Ordens por Lote" if not termo else f"Ordens por Lote (filtro: '{termo}')"
            ax.set_title(titulo_grafico, fontsize=12, fontweight='bold', pad=15)
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            ax.grid(axis='y', linestyle='--', alpha=0.7)
            ax.tick_params(axis='x', labelrotation=0)

            for bar in bars:
                height = bar.get_height()
                ax.annotate(f'{int(height)}',
                            xy=(bar.get_x() + bar.get_width() / 2, height),
                            xytext=(0, 3),
                            textcoords="offset points",
                            ha='center', va='bottom', fontweight='bold')

            canvas = FigureCanvasTkAgg(fig, master=content_frame)
            canvas.draw()
            canvas.get_tk_widget().pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

            list_frame = tk.Frame(content_frame, bg="white", bd=1, relief=tk.FLAT)
            list_frame.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(20, 0))

            total_ids = sum(lote["quantidade"] for lote in lotes_filtrados)
            header_txt = "LOTES DE RASTREIO" if not termo else f"LOTES DE RASTREIO ({total_ids} encontrado(s))"
            tk.Label(list_frame, text=header_txt, bg="#343a40", fg="white",
                     font=("Arial", 10, "bold"), pady=5).pack(fill=tk.X)
            text_area = scrolledtext.ScrolledText(list_frame, width=42, font=("Consolas", 10), bd=0)
            text_area.pack(fill=tk.BOTH, expand=True)

            for lote in lotes_filtrados:
                text_area.insert(tk.END, f"\n> Lote {lote['numero']} - {lote['data_label']} ({lote['quantidade']} ordens)\n", "header")
                for order_id in lote["ids"]:
                    text_area.insert(tk.END, f"  ID: {order_id}\n")

            text_area.tag_config("header", foreground="#007bff", font=("Consolas", 10, "bold"))
            text_area.configure(state=tk.DISABLED)

        _redesenhar()

    # --- NOVAS FUNCIONALIDADES: DASHBOARD E EXCEL ---
    def abrir_dashboard_vendas(self):
        db = self.carregar_db()
        if not db:
            messagebox.showinfo("Dashboard", "Banco de dados vazio.")
            return

        # 1. Adicionada a nova chave "Vendas Encerradas" no dicionário
        etapas = {
            "Solicitado": [], 
            "Rastreio": [], 
            "Boleto": [], 
            "Boleto Pago": [], 
            "Boleto Vencido": [], 
            "Cobrança Dobrada": [], 
            "Boleto Pago Dobro": [],
            "Vendas Encerradas": []
        }
        
        for oid, dados in db.items():
            
            # 2. A condição 'encerrada' vem PRIMEIRO. 
            # Se for verdadeira, ele registra aqui e pula os próximos 'elif'.
            if dados.get('encerrada'): 
                etapas["Vendas Encerradas"].append(oid)
            elif dados.get('boleto_pago_dobro'): etapas["Boleto Pago Dobro"].append(oid)
            elif dados.get('cobrado_dobro'): etapas["Cobrança Dobrada"].append(oid)
            elif dados.get('boleto_pago'): etapas["Boleto Pago"].append(oid)
            elif dados.get('boleto_vencido'): etapas["Boleto Vencido"].append(oid)
            elif dados.get('boleto_enviado'): etapas["Boleto"].append(oid)
            elif dados.get('rastreio_enviado'): etapas["Rastreio"].append(oid)
            elif dados.get('solicitado'): etapas["Solicitado"].append(oid)
            

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
        
        # 3. Adicionadas mais cores para evitar erro de 'mismatch' no matplotlib (agora temos 8 categorias)
        cores = ['#007bff', '#ffc107', '#28a745', "#6e1cbb", "#6c757d", "#dc3545", "#17a2b8", "#343a40"]

        bars = ax.bar(nomes, valores, color=cores, width=0.6)
        
        # A MÁGICA AQUI: Força apenas números inteiros no eixo Y
        from matplotlib.ticker import MaxNLocator # Certifique-se de que isso está importado no topo do seu arquivo
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        
        # Estética do gráfico
        ax.set_title("Volume de Pedidos por Etapa", fontsize=12, fontweight='bold', pad=15)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.grid(axis='y', linestyle='--', alpha=0.7)
        
        # Se os nomes ficarem muito juntos no eixo X, uma dica é rotacioná-los:
        # plt.xticks(rotation=45, ha='right') 

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

    def abrir_dashboard_boletos_pagos(self):
        """Dashboard de todos os boletos pagos de todas as contas, com filtro por conta
        (email) e por período, usando o campo 'data_solicitacao' como base do filtro."""
        VALOR_BOLETO = 138.98

        def _parse_data_solicitacao(valor):
            """Converte a string de data_solicitacao em datetime (aceita com ou sem hora)."""
            if not valor:
                return None
            valor = str(valor).strip()
            for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y"):
                try:
                    return datetime.strptime(valor, fmt)
                except ValueError:
                    continue
            return None

        # ---- Coleta bruta: para cada conta, lista os boletos pagos com sua data_solicitacao ----
        contas_raw = {}  # email completo -> lista de {'order_id':..., 'data': datetime|None}

        if os.path.exists(ACCOUNTS_DIR):
            for pasta_conta in os.listdir(ACCOUNTS_DIR):
                caminho_conta = os.path.join(ACCOUNTS_DIR, pasta_conta)
                if os.path.isdir(caminho_conta):
                    db_path = os.path.join(caminho_conta, 'database_vendas.json')
                    if os.path.exists(db_path):
                        try:
                            with open(db_path, 'r', encoding='utf-8') as f:
                                db = json.load(f)
                            registros = []
                            for oid, dados in db.items():
                                if dados.get('boleto_pago') == True:
                                    data_dt = _parse_data_solicitacao(dados.get('data_solicitacao'))
                                    registros.append({'order_id': oid, 'data': data_dt})
                            if registros:
                                contas_raw[pasta_conta] = registros
                        except Exception as e:
                            print(f"Erro ao ler {db_path}: {e}")

        if not contas_raw:
            messagebox.showinfo("Dashboard Boletos", "Nenhum boleto pago encontrado em nenhuma conta.")
            return

        # ---- Janela ----
        dash_win = tk.Toplevel(self.root)
        dash_win.title("Dashboard - Boletos Pagos por Conta")
        dash_win.geometry("1000x780")
        dash_win.configure(bg="#f8f9fa")

        main_frame = tk.Frame(dash_win, bg="#f8f9fa")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # --- TÍTULO ---
        titulo = tk.Label(main_frame, text="BOLETOS PAGOS POR CONTA",
                         font=("Arial", 16, "bold"), bg="#f8f9fa", fg="#28a745")
        titulo.pack(pady=(0, 10))

        # ================= FILTROS =================
        filtro_frame = tk.LabelFrame(main_frame, text="Filtros", bg="#f8f9fa",
                                      font=("Arial", 10, "bold"), padx=10, pady=10)
        filtro_frame.pack(fill=tk.X, pady=(0, 15))

        # --- Filtro de contas (emails) ---
        contas_filtro_frame = tk.Frame(filtro_frame, bg="#f8f9fa")
        contas_filtro_frame.grid(row=0, column=0, sticky="ns", padx=(0, 25))

        tk.Label(contas_filtro_frame, text="Contas (e-mails):", bg="#f8f9fa",
                 font=("Arial", 9, "bold")).pack(anchor="w")

        listbox_frame = tk.Frame(contas_filtro_frame)
        listbox_frame.pack()
        scrollbar_contas = tk.Scrollbar(listbox_frame, orient=tk.VERTICAL)
        lista_contas = tk.Listbox(listbox_frame, selectmode=tk.MULTIPLE, exportselection=False,
                                   height=8, width=34, yscrollcommand=scrollbar_contas.set)
        scrollbar_contas.config(command=lista_contas.yview)
        scrollbar_contas.pack(side=tk.RIGHT, fill=tk.Y)
        lista_contas.pack(side=tk.LEFT, fill=tk.BOTH)

        emails_ordenados = sorted(contas_raw.keys())
        for email in emails_ordenados:
            lista_contas.insert(tk.END, email)
        lista_contas.select_set(0, tk.END)  # todas selecionadas por padrão

        def _selecionar_todas_contas():
            lista_contas.select_set(0, tk.END)
            _redesenhar()

        def _limpar_selecao_contas():
            lista_contas.select_clear(0, tk.END)
            _redesenhar()

        botoes_contas_frame = tk.Frame(contas_filtro_frame, bg="#f8f9fa")
        botoes_contas_frame.pack(fill=tk.X, pady=(4, 0))
        tk.Button(botoes_contas_frame, text="Selecionar Todas", command=_selecionar_todas_contas,
                  font=("Arial", 8)).pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(botoes_contas_frame, text="Limpar", command=_limpar_selecao_contas,
                  font=("Arial", 8)).pack(side=tk.LEFT)

        # --- Filtro de data (baseado em data_solicitacao) ---
        data_filtro_frame = tk.Frame(filtro_frame, bg="#f8f9fa")
        data_filtro_frame.grid(row=0, column=1, sticky="nw")

        tk.Label(data_filtro_frame, text="Período (base: data_solicitacao):",
                 bg="#f8f9fa", font=("Arial", 9, "bold")).grid(row=0, column=0, columnspan=4,
                                                                 sticky="w", pady=(0, 6))

        tk.Label(data_filtro_frame, text="De:", bg="#f8f9fa").grid(row=1, column=0, sticky="e", padx=(0, 4))
        var_data_de = tk.StringVar()
        entry_de = tk.Entry(data_filtro_frame, textvariable=var_data_de, width=12)
        entry_de.grid(row=1, column=1, padx=(0, 15))
        tk.Label(data_filtro_frame, text="(dd/mm/aaaa)", bg="#f8f9fa", fg="#888",
                 font=("Arial", 7)).grid(row=2, column=1, sticky="w")

        tk.Label(data_filtro_frame, text="Até:", bg="#f8f9fa").grid(row=1, column=2, sticky="e", padx=(0, 4))
        var_data_ate = tk.StringVar()
        entry_ate = tk.Entry(data_filtro_frame, textvariable=var_data_ate, width=12)
        entry_ate.grid(row=1, column=3)
        tk.Label(data_filtro_frame, text="(dd/mm/aaaa)", bg="#f8f9fa", fg="#888",
                 font=("Arial", 7)).grid(row=2, column=3, sticky="w")
        tk.Label(data_filtro_frame, text='Dica: preencha só "De" para pegar "a partir do dia X".',
                 bg="#f8f9fa", fg="#888", font=("Arial", 7)).grid(row=2, column=0, columnspan=2, sticky="w")

        tk.Label(data_filtro_frame, text="Atalho por mês:", bg="#f8f9fa").grid(
            row=3, column=0, sticky="e", pady=(12, 0), padx=(0, 4))
        meses_nomes = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
                       "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
        var_mes_rapido = tk.StringVar(value="")
        combo_mes = ttk.Combobox(data_filtro_frame, textvariable=var_mes_rapido,
                                  values=[""] + meses_nomes, state="readonly", width=10)
        combo_mes.grid(row=3, column=1, pady=(12, 0))

        var_ano_rapido = tk.StringVar(value=str(datetime.now().year))
        tk.Entry(data_filtro_frame, textvariable=var_ano_rapido, width=6).grid(
            row=3, column=2, pady=(12, 0), sticky="w")
        tk.Label(data_filtro_frame, text="Ano", bg="#f8f9fa", fg="#888",
                 font=("Arial", 7)).grid(row=3, column=3, sticky="w", pady=(12, 0))

        def _aplicar_mes_rapido(*_):
            mes_nome = var_mes_rapido.get()
            if not mes_nome:
                return
            try:
                ano = int(var_ano_rapido.get())
            except ValueError:
                messagebox.showerror("Erro", "Ano inválido.")
                return
            mes_num = meses_nomes.index(mes_nome) + 1
            ultimo_dia = calendar.monthrange(ano, mes_num)[1]
            var_data_de.set(f"01/{mes_num:02d}/{ano}")
            var_data_ate.set(f"{ultimo_dia:02d}/{mes_num:02d}/{ano}")
            _redesenhar()

        combo_mes.bind("<<ComboboxSelected>>", _aplicar_mes_rapido)

        def _limpar_filtro_data():
            var_data_de.set("")
            var_data_ate.set("")
            var_mes_rapido.set("")
            _redesenhar()

        botoes_data_frame = tk.Frame(data_filtro_frame, bg="#f8f9fa")
        botoes_data_frame.grid(row=4, column=0, columnspan=4, sticky="w", pady=(12, 0))
        tk.Button(botoes_data_frame, text="Aplicar Filtro", command=lambda: _redesenhar(),
                  bg="#28a745", fg="white", font=("Arial", 9, "bold")).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(botoes_data_frame, text="Limpar Filtro de Data",
                  command=_limpar_filtro_data).pack(side=tk.LEFT)

        # ================= ÁREA DE CONTEÚDO (gráfico + tabela) =================
        # ================= ÁREA DE CONTEÚDO (gráfico + tabela) COM SCROLL =================
        canvas_outer = tk.Canvas(main_frame, bg="#f8f9fa", highlightthickness=0)
        scrollbar_outer = tk.Scrollbar(main_frame, orient="vertical", command=canvas_outer.yview)
        content_frame = tk.Frame(canvas_outer, bg="#f8f9fa")

        content_frame.bind(
            "<Configure>",
            lambda e: canvas_outer.configure(scrollregion=canvas_outer.bbox("all"))
        )

        canvas_outer_window = canvas_outer.create_window((0, 0), window=content_frame, anchor="nw")
        canvas_outer.configure(yscrollcommand=scrollbar_outer.set)

        # Faz o content_frame acompanhar a largura do canvas (evita cortar horizontalmente)
        def _ajustar_largura_canvas(event):
            canvas_outer.itemconfig(canvas_outer_window, width=event.width)
        canvas_outer.bind("<Configure>", _ajustar_largura_canvas)

        canvas_outer.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar_outer.pack(side=tk.RIGHT, fill=tk.Y)

        # Scroll com a roda do mouse (Windows)
        def _on_mousewheel(event):
            canvas_outer.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas_outer.bind_all("<MouseWheel>", _on_mousewheel)

        def _parse_entry_data(texto, fim_do_dia=False):
            texto = (texto or "").strip()
            if not texto:
                return None
            try:
                dt = datetime.strptime(texto, "%d/%m/%Y")
            except ValueError:
                messagebox.showerror("Data inválida", f"Data '{texto}' inválida. Use o formato dd/mm/aaaa.")
                return "ERRO"
            if fim_do_dia:
                dt = dt.replace(hour=23, minute=59, second=59)
            return dt

        def _redesenhar():
            # Limpa conteúdo anterior
            for widget in content_frame.winfo_children():
                widget.destroy()

            # Contas selecionadas no filtro
            selecionados_idx = lista_contas.curselection()
            if not selecionados_idx:
                tk.Label(content_frame,
                         text="Nenhuma conta selecionada. Selecione ao menos uma conta no filtro acima.",
                         bg="#f8f9fa", fg="#c00", font=("Arial", 11, "bold")).pack(pady=40)
                return
            emails_selecionados = [lista_contas.get(i) for i in selecionados_idx]

            # Datas do filtro (base: data_solicitacao)
            dt_inicio = _parse_entry_data(var_data_de.get(), fim_do_dia=False)
            if dt_inicio == "ERRO":
                return
            dt_fim = _parse_entry_data(var_data_ate.get(), fim_do_dia=True)
            if dt_fim == "ERRO":
                return

            # Recalcula os dados filtrados
            contas_dados = {}
            for email in emails_selecionados:
                registros = contas_raw.get(email, [])
                count_pagos = 0
                for reg in registros:
                    data_dt = reg['data']
                    if dt_inicio and (data_dt is None or data_dt < dt_inicio):
                        continue
                    if dt_fim and (data_dt is None or data_dt > dt_fim):
                        continue
                    count_pagos += 1
                if count_pagos > 0:
                    nome_curto = email.split('@')[0]
                    contas_dados[nome_curto] = {
                        'pagos': count_pagos,
                        'total': count_pagos * VALOR_BOLETO
                    }

            if not contas_dados:
                tk.Label(content_frame,
                         text="Nenhum boleto pago encontrado para o filtro selecionado.",
                         bg="#f8f9fa", fg="#c00", font=("Arial", 11, "bold")).pack(pady=40)
                return

            # --- CONFIGURAÇÃO DO GRÁFICO ---
            fig, ax = plt.subplots(figsize=(8, 5), dpi=100)
            fig.patch.set_facecolor('#f8f9fa')

            nomes = list(contas_dados.keys())
            valores = [contas_dados[n]['total'] for n in nomes]

            cores = plt.cm.Greens(np.linspace(0.4, 0.9, len(nomes)))
            bars = ax.bar(nomes, valores, color=cores, width=0.6)

            ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'R$ {x:,.2f}'))
            ax.set_title("Total Recebido por Conta (Boletos Pagos x R$ 138,98)",
                        fontsize=12, fontweight='bold', pad=15)
            ax.set_ylabel("Valor Total (R$)", fontsize=10)
            ax.set_xlabel("Conta", fontsize=10)
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            ax.grid(axis='y', linestyle='--', alpha=0.7)
            ax.set_xticks(range(len(nomes)))
            ax.set_xticklabels(nomes, rotation=0, ha='center', fontsize=10)

            for bar in bars:
                height = bar.get_height()
                ax.annotate(f'R$ {height:,.2f}',
                            xy=(bar.get_x() + bar.get_width() / 2, height),
                            xytext=(0, 3),
                            textcoords="offset points",
                            ha='center', va='bottom', fontweight='bold', fontsize=9)

            canvas = FigureCanvasTkAgg(fig, master=content_frame)
            canvas.draw()
            canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, pady=(0, 20))

            # --- TABELA DE DETALHES ---
            table_frame = tk.Frame(content_frame, bg="white", bd=1, relief=tk.FLAT)
            table_frame.pack(fill=tk.BOTH, expand=True)

            headers = ["Conta", "Boletos Pagos", "Valor Total"]
            for i, header in enumerate(headers):
                tk.Label(table_frame, text=header, bg="#343a40", fg="white",
                        font=("Arial", 10, "bold"), padx=10, pady=5).grid(row=0, column=i, sticky="ew")

            for idx, (conta, dados) in enumerate(contas_dados.items(), start=1):
                tk.Label(table_frame, text=conta, bg="white", padx=10, pady=3).grid(row=idx, column=0, sticky="ew")
                tk.Label(table_frame, text=str(dados['pagos']), bg="white", padx=10, pady=3).grid(row=idx, column=1, sticky="ew")
                tk.Label(table_frame, text=f"R$ {dados['total']:,.2f}", bg="white", padx=10, pady=3,
                         font=("Arial", 10, "bold")).grid(row=idx, column=2, sticky="ew")

            total_geral = sum(v['total'] for v in contas_dados.values())
            total_pagos = sum(v['pagos'] for v in contas_dados.values())

            tk.Label(table_frame, text="TOTAL GERAL", bg="#28a745", fg="white",
                    font=("Arial", 10, "bold"), padx=10, pady=5).grid(row=len(contas_dados)+1, column=0, sticky="ew")
            tk.Label(table_frame, text=str(total_pagos), bg="#28a745", fg="white",
                    font=("Arial", 10, "bold"), padx=10, pady=5).grid(row=len(contas_dados)+1, column=1, sticky="ew")
            tk.Label(table_frame, text=f"R$ {total_geral:,.2f}", bg="#28a745", fg="white",
                    font=("Arial", 10, "bold"), padx=10, pady=5).grid(row=len(contas_dados)+1, column=2, sticky="ew")

            table_frame.columnconfigure(0, weight=2)
            table_frame.columnconfigure(1, weight=1)
            table_frame.columnconfigure(2, weight=1)

        # Redesenha também quando a seleção de contas muda diretamente na lista
        lista_contas.bind("<<ListboxSelect>>", lambda e: _redesenhar())
        
        def _on_close():
            canvas_outer.unbind_all("<MouseWheel>")
            dash_win.destroy()
        dash_win.protocol("WM_DELETE_WINDOW", _on_close)

        # Desenho inicial (todas as contas, sem filtro de data)
        _redesenhar()

    def exportar_para_excel(self):
        # Validar que um email foi selecionado
        email = self.get_email()
        if not email:
            messagebox.showerror("Erro", "Por favor, selecione um email antes de exportar.")
            return
        
        # Obter a pasta da conta
        pasta_conta = self.get_pasta_conta()
        if not pasta_conta:
            messagebox.showerror("Erro", "Não foi possível obter a pasta da conta.")
            return
        
        # Definir caminho do arquivo Excel na pasta da conta
        caminho = os.path.join(pasta_conta, "vendas.xlsx")
        
        # Se o arquivo já existe, apagar
        if os.path.exists(caminho):
            try:
                os.remove(caminho)
            except Exception as e:
                messagebox.showerror("Erro", f"Não foi possível deletar o arquivo antigo: {e}")
                return
        
        db = self.carregar_db()
        if not db: 
            messagebox.showwarning("Aviso", "Nenhum dado de vendas para exportar.")
            return
        
        dados_excel = []
        # Mantemos a ordem das colunas
        colunas = [
            "Order ID", "Status", "Produto", "Data", 
            "Rastreio", "corProduto", "valor", "numero", "boleto_enviado", 
            "id_payment", "boleto_Pago", "Data Boleto Pago", "boleto_vencido", "horario_boleto", "Vendas Encerradas", "Data Boleto", "Cobrou Dobro", "Pago Dobro"
        ]

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
                "numero": d.get('zap_extraido', 'N/A'),
                "boleto_enviado": d.get('codigo_boleto', 'N/A'),
                "id_payment": d.get('id_payment', 'N/A'),
                "boleto_Pago": "Sim" if d.get('boleto_pago') else "Não",
                "Data Boleto Pago": d.get('data_boleto_pago', 'N/A'),
                "boleto_vencido": "Sim" if d.get('boleto_vencido') else "Não",
                "horario_boleto": d.get('horario_boleto', 'N/A'),
                "Vendas Encerradas": "Sim" if d.get('encerrada') else "Não",
                "Data Boleto": d.get('data_boleto', 'N/A'),
                "Cobrou Dobro": "Sim" if d.get('cobrado_dobro') else "Não",
                "Pago Dobro": "Sim" if d.get('boleto_pago_dobro') else "Não",
                "Data cobrou dobro": d.get('data_cobro_dobro', 'N/A'),
                "Metodo Dobro": d.get('metodo_cobro_dobro', 'N/A')
            })

        df = pd.DataFrame(dados_excel, columns=colunas)
        
        try:
            writer = pd.ExcelWriter(caminho, engine='xlsxwriter')
            df.to_excel(writer, index=False, sheet_name='Vendas')

            workbook  = writer.book
            worksheet = writer.sheets['Vendas']

            # --- DEFINIÇÃO DE FORMATOS ---
            # Formato padrão do link
            format_link = workbook.add_format({'font_color': 'blue', 'underline': 1})
            
            # Formato para a linha vermelha (Fundo vermelho claro)
            format_vermelho = workbook.add_format({'bg_color': '#FFC7CE'}) 
            
            # Formato para o link dentro de uma linha vermelha (combina os dois)
            format_link_vermelho = workbook.add_format({
                'font_color': 'blue', 
                'underline': 1, 
                'bg_color': '#FFC7CE'
            })

            col_idx_id = colunas.index("Order ID")
            base_url = "https://www.mercadolivre.com.br/vendas/{}/detalhe#source=excel"
            
            # --- APLICAÇÃO DA FORMATAÇÃO ---
            for row_num, row_data in df.iterrows():
                excel_row = row_num + 1 # +1 para pular o cabeçalho
                order_id = row_data['Order ID']
                url = base_url.format(order_id)
                
                # Verifica se a venda está encerrada
                esta_encerrada = row_data['Vendas Encerradas'] == "Sim"

                if esta_encerrada:
                    # Se encerrada, aplica o fundo vermelho em TODAS as células da linha
                    for col_num in range(len(colunas)):
                        # Se for a coluna do ID, aplica o link com fundo vermelho
                        if col_num == col_idx_id:
                            worksheet.write_url(excel_row, col_num, url, string=str(order_id), cell_format=format_link_vermelho)
                        else:
                            # Para as outras colunas, apenas reescreve o valor com o formato vermelho
                            valor = row_data[colunas[col_num]]
                            worksheet.write(excel_row, col_num, valor, format_vermelho)
                else:
                    # Se NÃO estiver encerrada, apenas garante que o link padrão seja escrito
                    worksheet.write_url(excel_row, col_idx_id, url, string=str(order_id), cell_format=format_link)

            writer.close()
            
            self.logger(f"Excel salvo em: {caminho}", "SUCESSO")
            messagebox.showinfo("Sucesso", f"Planilha exportada com sucesso em:\n{caminho}")
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao exportar Excel: {e}")
   
            
         




def executar_agendamento_direto(tarefa_id, machine_key=None):
    _registrar_log_agendamento(f"Iniciando modo direto: tarefa_id={tarefa_id}, machine={machine_key or 'preferencia'}")
    if machine_key:
        machine_key = _set_machine_override(machine_key)
        if not machine_key:
            raise ValueError("Máquina inválida. Use 'cliente' ou 'desenvolvedor'.")

    config_file = _encontrar_config_file()
    _registrar_log_agendamento(f"Config resolvido: {config_file}")
    if not config_file or not os.path.exists(config_file):
        raise FileNotFoundError(f"Arquivo de agendamentos não encontrado para '{_get_machine_key()}'")

    with open(config_file, 'r', encoding='utf-8') as f:
        agendamentos = json.load(f)

    if tarefa_id not in agendamentos:
        _registrar_log_agendamento(f"ERRO: Tarefa {tarefa_id} não encontrada em {config_file}")
        raise ValueError(f"Tarefa {tarefa_id} não encontrada")

    config = agendamentos[tarefa_id]
    if not config.get('ativo', False):
        _registrar_log_agendamento(f"AVISO: Tarefa {tarefa_id} está desativada")
        raise ValueError(f"Tarefa {tarefa_id} está desativada")

    # Regra do agendamento: nunca executar por cima de outro agendamento já em
    # andamento (neste processo ou em outro disparado pelo Windows Task
    # Scheduler). Se houver um rodando, espera terminar antes de seguir.
    _registrar_log_agendamento(f"Verificando lock de agendamento para tarefa {tarefa_id}...")
    aguardar_e_adquirir_lock_agendamento(tarefa_id, config.get('nome', ''))

    root = tk.Tk()
    root.withdraw()
    app = AppColetorPro(root, start_scheduler=False)
    app.agendamentos.config_file = config_file
    app.agendamentos.historico_file = _encontrar_historico_file(config_file)
    _registrar_log_agendamento(f"Histórico resolvido: {app.agendamentos.historico_file}")
    app.var_email.set(config.get('email', '').strip())
    app.var_prazo.set(config.get('prazo_entrega', '').strip())
    app.var_data_entrega.set(config.get('data_entrega', '').strip())
    app.var_pag_inicial.set(config.get('offset', '0'))
    app.var_ordem_ids.set(config.get('ordem_ids', '').strip())

    _registrar_log_agendamento(f"Executando task {tarefa_id}: email={config.get('email')}, acao={config.get('acao')}")
    app.logger(f"[AGENDAMENTO] Iniciando task {tarefa_id} para {config.get('email')} com ação {config.get('acao')}", "INFO")
    try:
        acao = 'solicitar' if config.get('acao') == 'reclamacao' else config.get('acao')
        
        app.iniciar_thread_processamento(acao=acao, usar_thread=False)
        _registrar_log_agendamento(f"Task {tarefa_id} finalizada com SUCESSO")
        app.agendamentos.adicionar_historico(
            tarefa_id,
            config.get('nome'),
            config.get('acao'),
            'SUCESSO',
            f"Executado automaticamente às {datetime.now().strftime('%H:%M:%S')}"
        )
    except Exception as e:
        _registrar_log_agendamento(f"ERRO ao executar task {tarefa_id}: {e}")
        app.logger(f"Erro ao executar agendamento {tarefa_id}: {e}", "ERRO")
        app.agendamentos.adicionar_historico(
            tarefa_id,
            config.get('nome'),
            config.get('acao'),
            'ERRO',
            str(e)
        )
    finally:
        root.destroy()
        liberar_lock_agendamento()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AppColetorPro - modo agendamento")
    parser.add_argument("--agendamento", help="Executar agendamento pelo ID da tarefa")
    parser.add_argument("--machine", choices=["cliente", "desenvolvedor"], help="Contexto do agendamento")
    args = parser.parse_args()

    if args.agendamento:
        try:
            executar_agendamento_direto(args.agendamento, args.machine)
            sys.exit(0)
        except Exception as e:
            _registrar_log_agendamento(f"ERRO fatal no modo direto: {e}")
            print(f"ERRO: {e}", file=sys.stderr)
            sys.exit(1)

    root = tk.Tk()
    app = AppColetorPro(root)
    root.mainloop()