import os
import json
import re
# Importa a sua função do seu arquivo existente principal
from main import gerar_resposta_groq 

# Configurações de Arquivos de Dados
ARQUIVO_HISTORICO = "historico_conversas.json"
ARQUIVO_LOTE_ENTRADA = "mensagens_teste.json"
ARQUIVO_PONTUACAO = "log_pontuacao_ia.json"

# ==========================================
# 1. GERENCIAMENTO DE HISTÓRICO MANUAL
# ==========================================

def carregar_historico_cliente(cliente_id: str) -> list:
    """Carrega o histórico de mensagens do cliente do arquivo JSON local."""
    if not os.path.exists(ARQUIVO_HISTORICO):
        return []
    try:
        with open(ARQUIVO_HISTORICO, "r", encoding="utf-8") as f:
            dados = json.load(f)
        return dados.get(cliente_id, [])
    except Exception:
        return []

def salvar_historico_cliente(cliente_id: str, historico_atualizado: list):
    """Salva o histórico de mensagens atualizado do cliente no arquivo JSON local."""
    dados = {}
    if os.path.exists(ARQUIVO_HISTORICO):
        try:
            with open(ARQUIVO_HISTORICO, "r", encoding="utf-8") as f:
                dados = json.load(f)
        except Exception:
            dados = {}
            
    dados[cliente_id] = historico_atualizado
    
    with open(ARQUIVO_HISTORICO, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)

# ==========================================
# 2. PROCESSAMENTO DE MENSAGENS COM A GROQ
# ==========================================

def processar_mensagem_groq(cliente_id: str, nova_pergunta: str, prompt_sistema_base: str):
    historico_previo = carregar_historico_cliente(cliente_id)
    
    # (Mantenha o bloco que reconstrói o histórico e o prompt_usuario igual)
    historico_formatado = ""
    for msg in historico_previo:
        origem = "Cliente" if msg["role"] == "user" else "IA"
        historico_formatado += f"{origem}: {msg['content']}\n"
    
    prompt_usuario = (
        f"Histórico anterior da conversa:\n{historico_formatado}\n"
        f"Mensagem atual do cliente:\n\"{nova_pergunta}\""
    )
    
    resposta_bruta_groq = ""
    
    try:
        # Chama a sua função original
        resposta_bruta_groq = gerar_resposta_groq(prompt_sistema_base, prompt_usuario).strip()
        
        # FILTRO DE SEGURANÇA AGRESSIVO (REGULAR EXPRESSION):
        # Encontra o primeiro '{' e o último '}' ignorando qualquer texto, tags ou rascunhos em volta
        match = re.search(r'\{.*\}', resposta_bruta_groq, re.DOTALL)
        
        if match:
            resposta_bruta_groq = match.group(0)
        else:
            raise ValueError("Nenhum objeto JSON válido foi localizado na resposta da IA.")
        
        # Transforma o texto limpo em dicionário Python
        dados_ia = json.loads(resposta_bruta_groq.strip())
        
    except Exception as e:
        print(f"   [ERRO ao processar JSON da Groq]: {e}.\nResposta bruta recebida:\n{resposta_bruta_groq}")
        return

    # --- VERIFICAÇÃO DE TRIAGEM ---
    if not dados_ia.get("necessita_resposta", True):
        classificacao = dados_ia.get("classificacao", "CONFIRMACAO")
        print(f"   [TRIAGEM]: Mensagem ignorada ({classificacao}). Nenhuma resposta necessária.")
        
        # Apenas salva a confirmação do cliente no histórico manual para manter o contexto vivo
        historico_previo.append({"role": "user", "content": nova_pergunta})
        salvar_historico_cliente(cliente_id, historico_previo)
        return

    # Extrai as 3 opções geradas pela IA mapeadas pelo prompt estruturado
    op1 = dados_ia.get('opcao_1', 'Opção não gerada pela IA.')
    op2 = dados_ia.get('opcao_2', 'Opção não gerada pela IA.')
    op3 = dados_ia.get('opcao_3', 'Opção não gerada pela IA.')

    # --- EXIBIÇÃO DO PAINEL DE TREINAMENTO ---
    print("\n" + "="*60)
    print(f" PAINEL DE AVALIAÇÃO (GROQ) | CLIENTE: {cliente_id}")
    print(f" PERGUNTA: '{nova_pergunta}'")
    print("="*60)
    print(f" [1 - Técnico ]: {op1}")
    print(f" [2 - Vendas  ]: {op2}")
    print(f" [3 - Empático]: {op3}")
    print("="*60)
    
    escolha = input(" Escolha a melhor resposta (1, 2, 3) ou '0' para pular: ").strip()
    
    # Mapeamento do tipo de abordagem pontuada no treinamento
    resposta_escolhida = ""
    abordagem_vencedora = ""
    
    if escolha == "1":
        resposta_escolhida = op1
        abordagem_vencedora = "Tecnico"
    elif escolha == "2":
        resposta_escolhida = op2
        abordagem_vencedora = "Vendas"
    elif escolha == "3":
        resposta_escolhida = op3
        abordagem_vencedora = "Empatico"
    else:
        print(" -> Item do lote pulado sem salvar e sem pontuar.")
        return

    # --- GRAVAÇÃO DA PONTUAÇÃO DO TREINAMENTO ---
    registro_pontuacao = {
        "cliente_id": cliente_id,
        "pergunta_cliente": nova_pergunta,
        "voto_escolhido": escolha,
        "abordagem_ganhadora": abordagem_vencedora
    }
    
    dados_pontuacao = []
    if os.path.exists(ARQUIVO_PONTUACAO):
        try:
            with open(ARQUIVO_PONTUACAO, "r", encoding="utf-8") as f:
                dados_pontuacao = json.load(f)
        except Exception:
            dados_pontuacao = []
            
    dados_pontuacao.append(registro_pontuacao)
    
    with open(ARQUIVO_PONTUACAO, "w", encoding="utf-8") as f:
        json.dump(dados_pontuacao, f, ensure_ascii=False, indent=2)
        
    print(f" -> Pontuação registrada com sucesso para a abordagem: [{abordagem_vencedora}]")

    # --- ATUALIZAÇÃO DO HISTÓRICO DE CONVERSA ---
    historico_previo.append({"role": "user", "content": nova_pergunta})
    historico_previo.append({"role": "assistant", "content": resposta_escolhida})
    salvar_historico_cliente(cliente_id, historico_previo)
    print(f" -> Histórico de {cliente_id} atualizado fisicamente.")

# ==========================================
# 3. EXECUTOR DO LOTE E EXIBIÇÃO DE RELATÓRIO
# ==========================================

def exibir_relatorio_estatistico():
    """Lê as pontuações salvas e monta o placar estatístico do treinamento."""
    if not os.path.exists(ARQUIVO_PONTUACAO):
        print("\nNenhuma pontuação foi registrada ainda nesta rodada.")
        return
        
    try:
        with open(ARQUIVO_PONTUACAO, "r", encoding="utf-8") as f:
            votos = json.load(f)
    except Exception:
        return

    total_votos = len(votos)
    if total_votos == 0:
        return

    contagem = {"Tecnico": 0, "Vendas": 0, "Empatico": 0}
    for v in votos:
        ab = v.get("abordagem_ganhadora")
        if ab in contagem:
            contagem[ab] += 1

    print("\n" + "📊" + " ="*15 + " PLACAR DO TREINAMENTO " + "= "*15)
    print(f" Total de interações avaliadas e validadas: {total_votos}")
    print("-" * 65)
    for abordagem, total in contagem.items():
        porcentagem = (total / total_votos) * 100
        print(f" * Abordagem [{abordagem:8}]: {total} votos ({porcentagem:.1f}%)")
    print("=" * 65 + "\n")

def rodar_lote_completo():
    """Carrega as mensagens de lote em fila e aciona o motor de testes."""
    if not os.path.exists(ARQUIVO_LOTE_ENTRADA):
        print(f"Erro Crítico: Crie o arquivo '{ARQUIVO_LOTE_ENTRADA}' antes de prosseguir.")
        return

    # Lê o prompt de contexto
    with open("scriptIABoletos.txt", "r", encoding="utf-8") as arquivo:
        prompt_sistema_base = arquivo.read()

    # Carrega a fila do lote
    with open(ARQUIVO_LOTE_ENTRADA, "r", encoding="utf-8") as f:
        lista_mensagens = json.load(f)

    total = len(lista_mensagens)
    print(f"=== Iniciando Lote de Treinamento: {total} mensagens em fila ===\n")

    for index, item in enumerate(lista_mensagens, 1):
        cliente_id = item.get("cliente_id")
        mensagem_texto = item.get("mensagem")
        
        print(f"\n[{index}/{total}] Processando a entrada de: {cliente_id}...")
        processar_mensagem_groq(cliente_id, mensagem_texto, prompt_sistema_base)

    print("\n✓ Processamento das mensagens do lote encerrado!")
    # Exibe o placar de desempenho após terminar as mensagens
    exibir_relatorio_estatistico()

if __name__ == "__main__":
    rodar_lote_completo()
