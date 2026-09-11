# ⚙️ SEPARAÇÃO DE AGENDAMENTOS POR MÁQUINA

## 📋 Problema Resolvido

Anteriormente, quando o projeto era compartilhado via Google Drive entre máquinas diferentes (h:/ e g:/), os agendamentos se cruzavam. Ao executar `main.exe` em uma máquina, ela carregava os agendamentos da outra máquina.

**Solução:** Cada máquina agora tem seus próprios arquivos de agendamento.

---

## 🎯 Como Funciona

### Arquivos de Agendamento

Cada máquina cria seu próprio arquivo:
- **Cliente**: `agendamentos_config_cliente.json` e `agendamentos_historico_cliente.json`
- **Desenvolvedor**: `agendamentos_config_desenvolvedor.json` e `agendamentos_historico_desenvolvedor.json`

### Identificação de Máquina

A máquina é identificada pelo arquivo `.machine_preference` no diretório raiz do projeto:
```
Sistema Captura WPP/
├── .machine_preference      ← Identifica qual máquina está usando
├── agendamentos_config_cliente.json
├── agendamentos_config_desenvolvedor.json
├── main.py
├── dist/main.exe
└── ...
```

---

## 🚀 PRIMEIRA VEZ (SETUP INICIAL)

### Opção 1: Usar o Script de Configuração (Recomendado)

```bash
python setup_machine_preference.py
```

O script irá:
1. Perguntar qual máquina você está usando (Cliente ou Desenvolvedor)
2. Salvar a preferência em `.machine_preference`
3. Perguntar se deseja remover arquivos genéricos antigos

### Opção 2: Fazer Manualmente

1. Abra o VS Code e execute `main.py`
2. No painel, você verá dois botões no topo:
   - **🔧 Cliente** → Seleciona contexto de cliente
   - **⚙️ Desenvolvedor** → Seleciona contexto de desenvolvedor
3. Clique no botão correspondente à sua máquina

---

## 🔧 USANDO A APLICAÇÃO

### Na Interface Principal

O header da aplicação mostra qual máquina está selecionada:

```
PAINEL DE CONTROLE DE LEADS | Contexto: cliente
[🔧 Cliente] [⚙️ Desenvolvedor]
```

### Criando um Novo Agendamento

Quando você cria um agendamento, ele é salvo APENAS na máquina selecionada:

- **Máquina: Cliente**
  - Arquivo: `agendamentos_config_cliente.json`
  - Acesso: apenas quando `.machine_preference = cliente`

- **Máquina: Desenvolvedor**
  - Arquivo: `agendamentos_config_desenvolvedor.json`
  - Acesso: apenas quando `.machine_preference = desenvolvedor`

### Alternando de Máquina

Se precisar usar a outra máquina:

1. **Via Interface:**
   - Clique no botão da máquina desejada
   - Confirme a mensagem
   - **Reinicie a aplicação** para aplicar completamente

2. **Via Terminal:**
   ```bash
   python setup_machine_preference.py
   ```

3. **Manual (Avançado):**
   - Edite o arquivo `.machine_preference` e coloque `cliente` ou `desenvolvedor`

---

## 📂 Estrutura de Arquivos

### ANTES (Problema)
```
Sistema Captura WPP/
├── agendamentos_config.json              ← Genérico (PROBLEMA!)
├── agendamentos_historico.json           ← Genérico (PROBLEMA!)
└── agendamentos_config_DESKTOP-ABC.json  ← Máquina 1
```
Resultado: Máquina 2 carregava `agendamentos_config.json` de Máquina 1 ❌

### DEPOIS (Solução)
```
Sistema Captura WPP/
├── .machine_preference                   ← cliente (ou desenvolvedor)
├── agendamentos_config_cliente.json      ← Máquina 1 (isolado)
├── agendamentos_historico_cliente.json   ← Máquina 1 (isolado)
├── agendamentos_config_desenvolvedor.json    ← Máquina 2 (isolado)
├── agendamentos_historico_desenvolvedor.json ← Máquina 2 (isolado)
└── agendamentos_config.json              ← Removido (legado)
```
Resultado: Cada máquina carrega apenas seus agendamentos ✓

---

## 🧹 Limpeza de Arquivos Antigos

Se você tiver arquivos genéricos antigos, remova-os:

```bash
# Remover arquivo genérico de config
del agendamentos_config.json

# Remover arquivo genérico de histórico
del agendamentos_historico.json
```

Ou execute o script de setup que oferece remover automaticamente.

---

## 🐛 Troubleshooting

### "Meu agendamento desapareceu!"

Você provavelmente mudou de máquina. Os agendamentos são separados por máquina:

- Verifique qual máquina o `.machine_preference` está configurado
- Se estiver `cliente`, veja os agendamentos em `agendamentos_config_cliente.json`
- Se estiver `desenvolvedor`, veja os agendamentos em `agendamentos_config_desenvolvedor.json`

### "Não consegui salvar arquivo genérico antigo"

Execute como administrador:

```bash
python setup_machine_preference.py
```

### "Arquivo `.machine_preference` não existe"

Execute o script de setup:

```bash
python setup_machine_preference.py
```

Ele criará o arquivo automaticamente.

---

## 📝 Logs de Inicialização

Quando a aplicação inicia, você verá logs como:

```
[DEBUG] Base dir detectado: h:\Meu Drive\Sistema Captura WPP
[CONFIG] ✓ Novo arquivo será criado em: h:\Meu Drive\Sistema Captura WPP\agendamentos_config_cliente.json

[INICIALIZAÇÃO] GerenciadorAgendamentos
  Config file: h:\Meu Drive\Sistema Captura WPP\agendamentos_config_cliente.json
  Histórico file: h:\Meu Drive\Sistema Captura WPP\agendamentos_historico_cliente.json
```

Isso confirma que está usando o arquivo correto.

---

## ✅ Resumo

| Aspecto | Antes | Depois |
|--------|-------|--------|
| **Isolamento** | ❌ Dados cruzados | ✓ Dados isolados |
| **Arquivo Config** | `agendamentos_config.json` | `agendamentos_config_{machine}.json` |
| **Seleção** | Automática (hostname) | Manual (cliente/desenvolvedor) |
| **Google Drive** | Conflitos | ✓ Sem conflitos |
| **VSCode + dist/main.exe** | ❌ Carrega genérico | ✓ Carrega correto |

---

## 🎓 Exemplos de Uso

### Cenário 1: Duas máquinas via Google Drive

**Máquina 1 (h:/):**
1. Execute: `python setup_machine_preference.py`
2. Selecione: `1 (Cliente)`
3. Cria: `agendamentos_config_cliente.json`

**Máquina 2 (g:/):**
1. Execute: `python setup_machine_preference.py`
2. Selecione: `2 (Desenvolvedor)`
3. Cria: `agendamentos_config_desenvolvedor.json`

Resultado: Agendamentos separados, sem conflitos! ✓

### Cenário 2: Executável vs VSCode

**VSCode (Desenvolvimento):**
```bash
python main.py
# Usa: agendamentos_config_cliente.json (se .machine_preference = cliente)
```

**dist/main.exe (Produção):**
```cmd
dist\main.exe
# Usa: agendamentos_config_desenvolvedor.json (se .machine_preference = desenvolvedor)
```

Resultado: Cada ambiente tem seus agendamentos ✓

---

## 📞 Suporte

Se tiver problemas:
1. Verifique o conteúdo do arquivo `.machine_preference`
2. Verifique os logs de inicialização
3. Certifique-se de reiniciar a aplicação após mudar de máquina
