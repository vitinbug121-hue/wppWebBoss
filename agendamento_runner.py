#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script auxiliar para executar agendamentos via Windows Task Scheduler.
Este script e chamado pelo Task Scheduler e executa a acao especificada.
"""

import sys
import os
import json
import subprocess
from datetime import datetime

VALID_MACHINE_KEYS = {'cliente', 'desenvolvedor'}


def _base_dir():
    try:
        if getattr(sys, 'frozen', False):
            exe_dir = os.path.dirname(sys.executable)
            return os.path.dirname(exe_dir) if os.path.basename(exe_dir).lower() == 'dist' else exe_dir
        return os.path.dirname(os.path.abspath(__file__))
    except Exception:
        return os.getcwd()


def _normalizar_machine_key(machine_key):
    if not machine_key:
        return None
    machine_key = str(machine_key).strip().lower()
    return machine_key if machine_key in VALID_MACHINE_KEYS else None


def _get_machine_key(cli_machine=None):
    cli_machine = _normalizar_machine_key(cli_machine)
    if cli_machine:
        return cli_machine

    pref_file = os.path.join(_base_dir(), '.machine_preference')
    try:
        if os.path.exists(pref_file):
            with open(pref_file, 'r', encoding='utf-8') as f:
                pref_machine = _normalizar_machine_key(f.read())
                if pref_machine:
                    return pref_machine
    except Exception:
        pass

    return 'cliente'


def encontrar_config_file(machine_key=None):
    """Encontra o arquivo de configuracao de agendamentos do contexto atual."""
    machine_key = _get_machine_key(machine_key)
    machine_filename = f'agendamentos_config_{machine_key}.json'
    legacy_filename = 'agendamentos_config.json'

    candidates = []
    base_dir = _base_dir()
    candidates.extend([
        os.path.join(base_dir, machine_filename),
        os.path.join(base_dir, legacy_filename),
    ])

    cwd_machine = os.path.join(os.getcwd(), machine_filename)
    cwd_legacy = os.path.join(os.getcwd(), legacy_filename)
    candidates.extend([cwd_machine, cwd_legacy])

    try:
        appdata = os.environ.get('APPDATA') or os.path.expanduser('~')
        user_dir = os.path.join(appdata, 'Sistema Captura WPP')
        candidates.extend([
            os.path.join(user_dir, machine_filename),
            os.path.join(user_dir, legacy_filename),
        ])
    except Exception:
        pass

    for config_path in candidates:
        if config_path and os.path.exists(config_path):
            return config_path

    return os.path.join(base_dir, machine_filename)


def registrar_log(mensagem):
    """Registra mensagens em arquivo de log."""
    log_dir = os.path.join(_base_dir(), 'logs_agendamentos')

    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    log_file = os.path.join(log_dir, f'agendador_{datetime.now().strftime("%Y-%m-%d")}.log')

    try:
        with open(log_file, 'a', encoding='utf-8') as f:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{timestamp}] {mensagem}\n")
    except Exception:
        pass


def main():
    """Funcao principal."""
    try:
        if len(sys.argv) < 4:
            registrar_log("ERRO: Argumentos insuficientes")
            sys.exit(1)

        tarefa_id = sys.argv[1]
        email = sys.argv[2]
        acao = sys.argv[3]
        machine_key = _get_machine_key(sys.argv[4] if len(sys.argv) >= 5 else None)

        registrar_log(f"Iniciando agendamento: tarefa_id={tarefa_id}, email={email}, acao={acao}, machine={machine_key}")

        config_file = encontrar_config_file(machine_key)
        registrar_log(f"Config usado: {config_file}")
        if not config_file or not os.path.exists(config_file):
            registrar_log(f"ERRO: Arquivo de agendamentos nao encontrado para {machine_key}")
            sys.exit(1)

        with open(config_file, 'r', encoding='utf-8') as f:
            agendamentos = json.load(f)

        if tarefa_id not in agendamentos:
            registrar_log(f"ERRO: Tarefa {tarefa_id} nao encontrada em {config_file}")
            sys.exit(1)

        config = agendamentos[tarefa_id]
        if not config.get('ativo', False):
            registrar_log(f"AVISO: Tarefa {tarefa_id} esta desativada")
            sys.exit(0)

        main_py = os.path.join(_base_dir(), 'main.py')
        if not os.path.exists(main_py):
            registrar_log(f"ERRO: main.py nao encontrado em {_base_dir()}")
            sys.exit(1)

        comando = [sys.executable, main_py, '--agendamento', tarefa_id, '--machine', machine_key]
        registrar_log(f"Executando: {' '.join(comando)}")

        resultado = subprocess.run(
            comando,
            cwd=_base_dir(),
            capture_output=True,
            text=True
        )

        registrar_log(f"STDOUT: {resultado.stdout.strip()}")
        registrar_log(f"STDERR: {resultado.stderr.strip()}")

        if resultado.returncode != 0:
            registrar_log(f"ERRO: main.py retornou codigo {resultado.returncode}")
            sys.exit(resultado.returncode)

        registrar_log("Agendamento executado com sucesso")
        print(f"[TASK SCHEDULER] Tarefa {tarefa_id} para {email} executada as {datetime.now().strftime('%H:%M:%S')}")
        sys.exit(0)

    except Exception as e:
        registrar_log(f"ERRO: {str(e)}")
        print(f"[ERRO] {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
