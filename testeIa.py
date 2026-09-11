import re
from main import gerar_resposta_groq 
with open("scriptIAboletos.txt", "r", encoding="utf-8") as arquivo:
    script_ia = arquivo.read()
    
mensagem_cliente = """[CLIENTE] Oi
[CLIENTE] Tem como eu receber antes
[CLIENTE] Estou precisando muito
[CLIENTE] quando chega
[CLIENTE] Tô precisando muito
[CLIENTE] Qual o código de rastreio
[CLIENTE] ?
[CLIENTE] Responde moço
[CLIENTE] Cadê o código de rastreio"""   
    
def precisa_responder_groq(mensagem_cliente: str) -> bool:
    system_text = (
        "Você é um classificador de mensagens de atendimento ao cliente.\n"
        "Analise a mensagem enviada pelo cliente e determine se ela necessita de uma resposta.\n\n"
        "Regras:\n"
        "1. Retorne TRUE se a mensagem for uma dúvida, pergunta, solicitação, reclamação ou exigir continuidade.\n"
        "2. Retorne FALSE se for apenas um agradecimento, confirmação ou despedida (ex: 'ok', 'obrigado', 'valeu', 'entendi', 'perfeito').\n\n"
        "Sua resposta deve conter EXCLUSIVAMENTE a palavra TRUE ou FALSE."
    )

    # Reutiliza a estrutura do carrossel de chaves
    resposta_raw = gerar_resposta_groq(system_text, mensagem_cliente)
    
    # Limpa a resposta e converte para booleano
    resposta_limpa = resposta_raw.strip().upper()
    return "TRUE" in resposta_limpa    
    
    
need_response = precisa_responder_groq(mensagem_cliente)

if need_response:
    prompt_usuario = (
                f"{script_ia}\n"
                "Mensagem do cliente:\n"
                f"""{mensagem_cliente}"""
            )

    script_ia2 = (
                "Você está analisando uma conversa de atendimento ao cliente de uma loja. "
                "O vendedor pediu para o cliente digitar '1' para autorizar a geração de um boleto "
                "de pagamento de taxa. porém alguns cliente digita outra coisa que também siginifica o envio do boleto Com base apenas nas mensagens do cliente abaixo, responda "
                "SOMENTE com a palavra 'true' se, em algum momento, o cliente demonstrou que deseja "
                "receber o boleto e seguir com o pagamento da taxa, ou 'false' caso ele esteja "
                "recusando, pedindo cancelamento, ou as mensagens não deixem isso claro. "
                "Responda apenas 'true' ou 'false', sem explicações."
                
            )

    prompt_usuario2 = (
                "Mensagens do cliente após a solicitação:"
                "\nestou aguardando boleto"
                )

    resposta_ia = gerar_resposta_groq(script_ia, prompt_usuario).strip('"')

    adasda = "Resposta da IA:\n" + resposta_ia



    