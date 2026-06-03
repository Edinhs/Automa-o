# Backend Start - Automation HUB

Este documento descreve o estado atual do backend FastAPI usado pelo dashboard React/Vite.

## Stack atual

- Python 3.11+ recomendado para entrega corporativa.
- FastAPI, SQLAlchemy, Alembic e SQLite local por padrao.
- `DATABASE_URL` permite trocar o banco para PostgreSQL/servidor sem alterar codigo.
- `AUTH_DISABLED=true` e o padrao da release: o dashboard abre direto, sem tela de login e sem usuario/senha.
- Playwright usa Chromium por padrao, com navegador visivel e login manual do usuario.
- A release offline inclui `backend\ms-playwright\chromium-1217` e os scripts definem `PLAYWRIGHT_BROWSERS_PATH` para evitar download bloqueado por proxy/certificado corporativo.

## Setup da release no notebook

```powershell
.\setup_backend.bat
.\start_all.bat
```

Na release estrita, `setup_backend.bat` instala somente `backend\requirements.txt`, aplica migrations e mantem o banco vazio. Nao e necessario criar usuario admin inicial: quando `AUTH_DISABLED=true`, o backend usa/cria automaticamente um usuario local administrador para operar o dashboard. O dashboard abre a partir de `dist` usando Python em `http://127.0.0.1:5173`, sem depender de Node/npm.

Para reiniciar backend, dashboard e agente local apos o setup, utilize somente:

```powershell
.\restart_services.bat
```

`restart_services.bat` encerra apenas processos reconhecidos como pertencentes a este pacote e chama a inicializacao central, que mantem os servicos em janelas ocultas. Se as portas da aplicacao estiverem ocupadas por um processo externo, o reinicio e cancelado sem encerra-lo. Os demais `.bat` permanecem no pacote como dependencias internas de instalacao e inicializacao.

Para iniciar processos separados:

```powershell
.\start_backend.bat
.\start_dashboard.bat
```

`start_backend.bat` inicia a API com `python -m uvicorn`, evitando depender de `uvicorn.exe` no PATH do Windows. Quando o Chromium offline existe, `start_backend.bat`, `start_agent.bat` e `setup_backend.bat` apontam o Playwright para `backend\ms-playwright`.

Para o agente local:

```powershell
.\start_agent.bat
```

O agente usa `AGENT_SHARED_TOKEN` para acessar `/api/agents/*`. O mesmo valor deve existir no backend e no processo do agente.

## Variaveis principais

- `DATABASE_URL=sqlite:///./data/automation_hub_dev.db`
- `OPERATIONAL_DATABASE_URL=` vazio mantem o banco legado configurado em `DATABASE_URL`
- `DEVELOPER_DATABASE_URL=sqlite:///./data/developer/automation_hub_dev.db`
- `AUTH_DISABLED=true`
- `SECRET_KEY=change-me-in-production`
- `AGENT_SHARED_TOKEN=local-dev-agent-token`
- `PLAYGROUND_URL=https://genai.stellantis.com/`
- `PLAYGROUND_BROWSER_CHANNEL=chromium`
- `PLAYWRIGHT_BROWSERS_PATH=backend\ms-playwright` definido automaticamente pelos `.bat` quando o navegador offline esta incluido
- `PLAYWRIGHT_HEADLESS=false`
- `BROWSER_SESSION_PATH=./data/browser_session`
- `DEVELOPER_BROWSER_SESSION_PATH=./data/developer/browser_session`
- `REPORTS_PATH=./data/reports`
- `DEVELOPER_REPORTS_PATH=./data/developer/reports`
- `PROFILE_PHOTOS_PATH=./data/profile_photos`
- `DEVELOPER_PROFILE_PHOTOS_PATH=./data/developer/profile_photos`
- `SQLITE_BUSY_TIMEOUT_MS=15000` tempo de espera por lock antes de "database is locked"
- `STAGING_RETENTION_DAYS=0` retencao opt-in das pastas de staging (0 = desativado)

### Integracao Microsoft Teams (opcional, opt-in)

Vazias por padrao — a integracao so liga quando preenchidas:

- `MS_GRAPH_TENANT_ID=`
- `MS_GRAPH_CLIENT_ID=`
- `MS_GRAPH_CLIENT_SECRET=`
- `MS_GRAPH_SCOPE=https://graph.microsoft.com/.default`
- `MS_GRAPH_SENDER_USER=`
- `MS_GRAPH_TEAMS_TEAM_ID=`
- `MS_GRAPH_TEAMS_CHANNEL_ID=`
- `MS_GRAPH_TEAMS_WEBHOOK_URL=`
- `MS_GRAPH_TIMEOUT_SECONDS=20`

Tabelas: `teams_channels` (webhooks/destinos) e `teams_report_schedules` (agendamento de envio de relatorios). Codigo em `app/routers/teams.py`, `app/models/teams.py` e `app/services/integrations/graph_client.py`.

## Separacao entre modos

Os ambientes `Desenvolvedor` e `Operacional` possuem bancos e diretorios de runtime separados. Todas as chamadas do dashboard informam o modo selecionado ao backend; o agente local e o scheduler tambem processam as filas de cada ambiente separadamente.

Por compatibilidade e protecao do historico existente, o modo `Operacional` continua usando os valores legados configurados em `DATABASE_URL`, `BROWSER_SESSION_PATH`, `TEMP_PATH`, `REPORTS_PATH`, `LOGS_PATH` e `PROFILE_PHOTOS_PATH`. O modo `Desenvolvedor` usa exclusivamente os caminhos `DEVELOPER_*` sob `./data/developer/` por padrao.

## Contrato real de dados

As tabelas centrais atuais sao:

- `users`
- `workspaces`
- `workspace_external_users`
- `automations`
- `workspace_files`
- `agent_tasks`
- `local_agents`
- `execution_logs`
- `execution_reports`
- `schedules`
- `integration_connections`
- `integration_deliveries`
- `teams_channels`
- `teams_report_schedules`

Historico de execucoes e derivado de `agent_tasks.started_at`, com apoio de `workspace_files` e `execution_logs`. Nao existe uma tabela separada `automation_executions` nesta versao.

## Relatorios de monitoramento de pasta

Os relatorios `Relatorio Geral`, `Relatorio Arquivos` e `Relatorio Erros Locais` usam exclusivamente deteccoes e falhas locais registradas durante a varredura/staging da pasta monitorada, antes da automacao WEB. Eventos de upload, sessao, workspace ou monitoramento no Playground nao entram nesses artefatos.

O agente gera automaticamente um `Relatorio Geral` em XLSX para cada ciclo que detectar arquivo novo, atualizado, duplicado de auditoria ou erro local reportavel. A geracao manual continua disponivel em XLSX, PDF e CSV.

Ao atualizar uma instalacao que ja possua relatorios antigos, execute a limpeza uma unica vez, depois de aplicar as migrations:

```powershell
cd backend
.\.venv\Scripts\python.exe -m app.cli.purge_legacy_reports
.\.venv\Scripts\python.exe -m app.cli.purge_legacy_reports --apply
```

O primeiro comando apenas confere quantidades; `--apply` exclui registros antigos de `execution_reports` e arquivos em `REPORTS_PATH`, registrando a remocao no log administrativo. Essa rotina nao e executada na inicializacao normal.

## Endpoints

Publicos:

- `GET /health`
- `GET /api/health`
- `POST /api/auth/login`

Autenticados por Bearer JWT:

- `/api/auth/me`
- `/api/users`
- `/api/workspaces`
- `/api/logs`
- `/api/reports`
- `/api/schedules`
- `/api/integrations`
- `/api/executions`
- `/api/teams`

Autenticados por Bearer JWT ou `X-Agent-Token` interno:

- `/api/automations`
- `/api/files`
- `/api/agents`
- `/api/agents/heartbeat`
- `/api/agents/poll`
- `/api/agents/tasks`
- `/api/agents/tasks/{id}/start`
- `/api/agents/tasks/{id}/complete`
- `/api/agents/tasks/{id}/fail`
- `/api/agents/tasks/{id}/manual-review`
- `/api/agents/tasks/{id}/cancel`
- `/api/agents/tasks/{id}/log`
- `/api/agents/tasks/{id}/folder-monitoring-report`

Esses endpoints aceitam `X-Agent-Token` ou Bearer JWT quando acionados pelo dashboard.

Com `AUTH_DISABLED=true`, os endpoints acima tambem aceitam chamadas do dashboard sem Bearer JWT. O fluxo antigo de login fica preservado no codigo para reativacao futura com `AUTH_DISABLED=false`.

## Validacao local de desenvolvimento

As dependencias de teste e a pasta `backend\tests` nao entram na release estrita. Use os comandos abaixo somente neste ambiente de desenvolvimento:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Comandos de validacao:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m alembic current
cd ..
.\backend\.venv\Scripts\python.exe -m compileall backend\app
npm run build
```
