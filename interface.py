"""
Interface gráfica (tkinter) para o processo de atendimento com IA (boletos).

Fluxo:
1. O usuário cola/digita a mensagem do cliente na caixa de entrada.
2. Ao clicar em "Processar", o sistema chama `precisa_responder_groq` para
   decidir se a mensagem exige resposta.
3. - Se NÃO precisar responder (need_response == False): a caixa de saída
     mostra um aviso informando isso.
   - Se precisar responder: o sistema monta o prompt com o script da IA
     (scriptIAboletos.txt) + a mensagem do cliente, chama `gerar_resposta_groq`
     e exibe a resposta gerada na caixa de saída.

Requisitos:
- Os arquivos `main.py` (com a função `gerar_resposta_groq`) e
  `scriptIAboletos.txt` devem estar na mesma pasta deste script
  (mesma estrutura do script original).
"""

import os
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import re

GROQ_MODEL = "openai/gpt-oss-120b"

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
                max_tokens=700,
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

    raise RuntimeError(
        f"Todas as {total_chaves} chaves GROQ atingiram o limite de uso (erro 429). "
        f"Último erro: {erro_final}"
    )

# ------------------------------------------------------------------
# Carrega o script da IA usado no prompt
# ------------------------------------------------------------------
def carregar_script_ia(caminho: str = "scriptIAboletos.txt") -> str:
    with open(caminho, "r", encoding="utf-8") as arquivo:
        return arquivo.read()


# ------------------------------------------------------------------
# Lógica original (mantida igual ao script de referência)
# ------------------------------------------------------------------
def precisa_responder_groq(mensagem_cliente: str) -> bool:
    system_text = (
        "Você é um classificador de mensagens de atendimento ao cliente.\n"
        "Analise a mensagem enviada pelo cliente e determine se ela necessita de uma resposta.\n\n"
        "Regras:\n"
        "1. Retorne TRUE se a mensagem for uma dúvida, pergunta, solicitação, reclamação ou exigir continuidade.\n"
        "2. Retorne FALSE se for apenas um agradecimento, confirmação ou despedida (ex: 'ok', 'obrigado', 'valeu', 'entendi', 'perfeito').\n\n"
        "Sua resposta deve conter EXCLUSIVAMENTE a palavra TRUE ou FALSE."
    )

    resposta_raw = gerar_resposta_groq(system_text, mensagem_cliente)
    resposta_limpa = resposta_raw.strip().upper()
    return "TRUE" in resposta_limpa


def gerar_resposta_para_cliente(mensagem_cliente: str, script_ia: str) -> str:
    prompt_usuario = (
        f"{script_ia}\n"
        "Mensagem do cliente:\n"
        f"{mensagem_cliente}"
    )
    resposta_ia = gerar_resposta_groq(script_ia, prompt_usuario).strip('"')
    return resposta_ia


# ------------------------------------------------------------------
# Interface gráfica
# ------------------------------------------------------------------
class InterfaceBoletos(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Atendimento IA - Boletos")
        self.geometry("760x600")
        self.minsize(600, 500)

        self.script_ia = None
        self._carregar_script_ia_inicial()

        self._montar_layout()

    # ------------------------------------------------------------------
    def _carregar_script_ia_inicial(self):
        try:
            self.script_ia = carregar_script_ia()
        except FileNotFoundError:
            self.script_ia = None  # avisado ao processar

    # ------------------------------------------------------------------
    def _montar_layout(self):
        padding = {"padx": 12, "pady": 8}

        # --- Entrada da mensagem do cliente ---
        lbl_entrada = ttk.Label(self, text="Mensagem do cliente:", font=("Segoe UI", 10, "bold"))
        lbl_entrada.pack(anchor="w", **padding)

        self.txt_entrada = tk.Text(self, height=10, wrap="word", font=("Segoe UI", 10))
        self.txt_entrada.pack(fill="both", expand=True, padx=12)
        self.txt_entrada.insert(
            "1.0",
            "[CLIENTE] Oi\n[CLIENTE] Tem como eu receber antes\n"
            "[CLIENTE] Estou precisando muito\n[CLIENTE] quando chega\n"
            "[CLIENTE] Tô precisando muito\n[CLIENTE] Qual o código de rastreio\n"
            "[CLIENTE] ?\n[CLIENTE] Responde moço\n[CLIENTE] Cadê o código de rastreio",
        )

        # --- Botão processar ---
        frame_botoes = ttk.Frame(self)
        frame_botoes.pack(fill="x", **padding)

        self.btn_processar = ttk.Button(frame_botoes, text="Processar", command=self._on_processar_click)
        self.btn_processar.pack(side="left")

        self.btn_limpar = ttk.Button(frame_botoes, text="Limpar", command=self._limpar_campos)
        self.btn_limpar.pack(side="left", padx=8)

        self.lbl_status = ttk.Label(frame_botoes, text="", foreground="gray")
        self.lbl_status.pack(side="left", padx=8)

        # --- Saída ---
        lbl_saida = ttk.Label(self, text="Resultado:", font=("Segoe UI", 10, "bold"))
        lbl_saida.pack(anchor="w", **padding)

        self.txt_saida = tk.Text(self, height=12, wrap="word", font=("Segoe UI", 10), state="disabled",
                                  background="#f5f5f5")
        self.txt_saida.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    # ------------------------------------------------------------------
    def _limpar_campos(self):
        self.txt_entrada.delete("1.0", "end")
        self._escrever_saida("")

    # ------------------------------------------------------------------
    def _escrever_saida(self, texto: str):
        self.txt_saida.config(state="normal")
        self.txt_saida.delete("1.0", "end")
        self.txt_saida.insert("1.0", texto)
        self.txt_saida.config(state="disabled")

    # ------------------------------------------------------------------
    def _on_processar_click(self):
        mensagem_cliente = self.txt_entrada.get("1.0", "end").strip()

        if not mensagem_cliente:
            messagebox.showwarning("Atenção", "Digite ou cole a mensagem do cliente antes de processar.")
            return

        if self.script_ia is None:
            messagebox.showerror(
                "Arquivo não encontrado",
                "Não foi possível carregar 'scriptIAboletos.txt'. "
                "Verifique se o arquivo está na mesma pasta deste programa.",
            )
            return

        self.btn_processar.config(state="disabled")
        self.lbl_status.config(text="Processando...")
        self._escrever_saida("")

        # Roda em thread separada para não travar a interface enquanto espera a API
        thread = threading.Thread(target=self._processar_em_thread, args=(mensagem_cliente,), daemon=True)
        thread.start()

    # ------------------------------------------------------------------
    def _processar_em_thread(self, mensagem_cliente: str):
        try:
            need_response = precisa_responder_groq(mensagem_cliente)

            if not need_response:
                resultado = (
                    "⚠ Esta mensagem NÃO precisa de resposta.\n\n"
                    "(O classificador identificou que é apenas um agradecimento, "
                    "confirmação ou despedida.)"
                )
            else:
                resposta_ia = gerar_resposta_para_cliente(mensagem_cliente, self.script_ia)
                resultado = "Resposta da IA:\n" + resposta_ia

        except Exception as e:
            resultado = f"Ocorreu um erro ao processar a mensagem:\n{e}"

        # Volta para a thread principal do tkinter para atualizar a UI
        self.after(0, self._finalizar_processamento, resultado)

    # ------------------------------------------------------------------
    def _finalizar_processamento(self, resultado: str):
        self._escrever_saida(resultado)
        self.btn_processar.config(state="normal")
        self.lbl_status.config(text="")


if __name__ == "__main__":
    app = InterfaceBoletos()
    app.mainloop()
