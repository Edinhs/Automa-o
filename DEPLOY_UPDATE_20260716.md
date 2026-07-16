# Deploy do Pacote de Atualizacao - Automation HUB

**Pacote:** `releases\hub_update_COMPLETO_20260716_164243.zip` (~0,79 MB, overlay incremental)
**Data de geracao:** 2026-07-16
**Tipo:** atualizacao por sobreposicao (overlay) - **PRESERVA banco de dados, runtime, .venv e o Chromium offline**.

Este pacote NAO contem banco (`*.db`), `backend\data`, `.venv`, `node_modules` nem `backend\ms-playwright`. Ao extrair por cima da instalacao, ele sobrescreve apenas: `backend\app`, `backend\alembic`, `dist`, `public`, `scripts` da raiz, os `.bat` de operacao e a documentacao. Seus dados reais e o Chromium embarcado permanecem intactos.

---

## Correcoes entregues neste pacote (T-019 a T-027)

- **T-019** - Status da aba Automacoes agora exibe rotulos pt-BR legiveis (badge + filtro) em vez das chaves cruas do backend. (frontend)
- **T-020** - Seletor de idioma do relatorio (Portugues / Ingles) na geracao manual e no modal "Agendar Relatorio". (frontend + backend + migracao 0013)
- **T-021** - Criacao de usuario normaliza role/status e passa a salvar corretamente o `network_id`. (backend `routers/users.py`)
- **T-022** - Modal da Lixeira (Configuracoes) menor e com rolagem interna preservada. (frontend)
- **T-024** - Card "Resumo de Erros" da Home reflete os erros EXISTENTES e diminui ao resolver; contadores autoritativos por COUNT no backend. (backend `routers/overview.py` + frontend)
- **T-025** - Overflow horizontal corrigido no modal "Detalhes do Arquivo" (SHA-256 e caminhos longos quebram linha). (frontend)
- **T-026** - Pagina "Sobre & Diagnosticos": removida a camada pontilhada e adicionada uma "janela" de infos legivel (Nome / Versao / Autor) no hero. (frontend)
- **T-027** - Login manual do Playground sem timeout: aguarda o login na janela visivel sem falhar a tarefa. (backend `services/playwright/playground_login.py`)

> Aviso sobre a migracao **0013** (`a9c2e4f6b731`): ela adiciona as colunas `execution_reports.language` e `schedules.report_language`, ambas com `server_default = "pt"`. E **aditiva e nao-destrutiva** - nenhum dado existente e alterado ou removido.

---

## Pre-requisitos

- Executar todos os passos na **pasta de instalacao de PRODUCAO** do dono (a que tem ~1981 arquivos reais e o Chromium offline em `backend\ms-playwright`).
- Ter o ZIP `hub_update_COMPLETO_20260716_164243.zip` copiado para essa maquina.

---

## Passo a passo

### a) Parar todos os servicos

Na pasta de producao, execute:

```
stop_all.bat
```

Isso encerra backend, dashboard e agente, e mata processos HUB soltos nas portas **8000/5173**. Importante porque houve backends de desenvolvimento rodando na `:8000` - garanta que nada sobrou (o backend antigo continua servindo o codigo velho ate ser encerrado).

### b) BACKUP do banco de producao (OBRIGATORIO)

Antes de qualquer coisa, copie os bancos reais. A migracao e aditiva e segura, mas o backup e obrigatorio. Em PowerShell, dentro da pasta de producao:

```powershell
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
New-Item -ItemType Directory -Force ".\backup_db_$stamp" | Out-Null
Copy-Item ".\backend\data\*.db" ".\backup_db_$stamp\" -Force
Get-ChildItem ".\backup_db_$stamp\"
```

Confirme que os arquivos `.db` foram copiados antes de prosseguir.

### c) Extrair o ZIP por cima da instalacao

Extraia `hub_update_COMPLETO_20260716_164243.zip` **na raiz da pasta de instalacao**, mantendo a estrutura de pastas e **sobrescrevendo** quando perguntado. As entradas do ZIP ja estao na raiz (sem pasta-envelope), entao ele sobrepoe os arquivos no lugar. Em PowerShell:

```powershell
Expand-Archive -Path ".\hub_update_COMPLETO_20260716_164243.zip" -DestinationPath "." -Force
```

Isso sobrescreve `backend\app`, `backend\alembic`, `dist`, `public`, `scripts`, docs e os `.bat`. **Preserva** `backend\data` (banco), `.venv` e `backend\ms-playwright` (Chromium).

### d) Aplicar a migracao 0013 nos DOIS ambientes

A migracao precisa rodar tanto no ambiente **operational** quanto no **developer**. Em PowerShell, dentro de `...\backend`:

```powershell
cd .\backend

$env:AUTOMATION_HUB_MIGRATION_ENVIRONMENT = "operational"
.\.venv\Scripts\python.exe -m alembic upgrade head

$env:AUTOMATION_HUB_MIGRATION_ENVIRONMENT = "developer"
.\.venv\Scripts\python.exe -m alembic upgrade head
```

**Alternativa:** rodar `setup_backend.bat` na raiz - ele ja executa `alembic upgrade head` uma vez por ambiente (operational e developer), sem apagar dados.

Confirme que ficou no head correto em cada ambiente:

```powershell
$env:AUTOMATION_HUB_MIGRATION_ENVIRONMENT = "operational"
.\.venv\Scripts\python.exe -m alembic current
# esperado: a9c2e4f6b731 (head)

$env:AUTOMATION_HUB_MIGRATION_ENVIRONMENT = "developer"
.\.venv\Scripts\python.exe -m alembic current
# esperado: a9c2e4f6b731 (head)

cd ..
```

### e) Subir os servicos (backend + dashboard + AGENTE)

```
start_all.bat
```

Use `start_all.bat` (e nao apenas o backend) porque ele sobe tambem o **AGENTE** - o que resolve o heartbeat parado. Alternativa equivalente: `restart_services.bat`.

### f) Hard-refresh no dashboard

No navegador do dashboard, force **Ctrl+F5** (hard-refresh). O nome do bundle nao mudou (`index-BBcj3Zw-.js`), entao sem o hard-refresh o navegador serve o JS antigo do cache e as correcoes de frontend (T-019, T-020, T-022, T-024, T-025, T-026) nao aparecem.

### g) Verificacao pos-deploy

1. **Diagnostics / heartbeat:** abra `GET http://127.0.0.1:8000/api/diagnostics` e confirme `agent.status` OK com heartbeat fresco (o agente subiu no passo e).
2. **Criar usuario (T-021):** crie um usuario com `network_id` e confirme que ele e salvo corretamente.
3. **Resumo de Erros (T-024):** na Home, verifique que o card mostra os erros existentes e que resolver um erro faz o contador **descer** (apos hard-refresh, sem trocar de aba manualmente).
4. **Detalhes / Sobre (T-025 / T-026):** abra o modal "Detalhes do Arquivo" (SHA-256/caminho longo nao deve estourar na horizontal) e a pagina "Sobre & Diagnosticos" (janela de infos legivel, sem a camada pontilhada).
5. **Idioma do relatorio (T-020):** gere um relatorio escolhendo "Ingles" e confirme o conteudo traduzido; teste tambem o `<select>` de idioma no modal "Agendar Relatorio".
6. **Login manual sem timeout (T-027):** dispare uma tarefa do Playground que exija login; confirme que o navegador visivel aguarda o login manual sem marcar a tarefa como falha.

---

## Rollback (se necessario)

1. `stop_all.bat`.
2. Restaurar os `.db` a partir de `backup_db_<stamp>\` para `backend\data\`.
3. Reverter a migracao (opcional, a coluna e inofensiva): em cada ambiente, `alembic downgrade -1`.
4. Restaurar a versao anterior do codigo/bundle (ou reaplicar o pacote de update anterior).

---

## Notas de integridade do pacote (validacao ja executada nesta geracao)

- `forbidden_entries = 0` (sem `.db`/`.sqlite`, logs, `__pycache__`, `.venv`, `browser_session`, `ms-playwright`/Chromium, `.bak`, `backend\tests`, `requirements-dev.txt`).
- `contains_database_file = False`, `entry_count = 112`.
- Contem todos os arquivos-chave da sessao (backend + migracao 0013 + `report_i18n.py` + bundle novo `dist\assets\index-BBcj3Zw-.js`).
- Bundle confirmado como o novo (contem os marcadores `statusLabel` do T-019 e `report_language` do T-020).
- Migracao 0013 (`a9c2e4f6b731`) e o head; parent 0012 (`f1a2b3c4d5e6`) presente.
- Gate `python -m compileall backend\app` -> exit 0.
