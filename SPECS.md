# 📐 SPECS — Especificação Técnica do Stellantis Automation HUB

> **Versão:** 1.0 · **Data:** 2026-07-15 · **Autor:** Claude Code (Opus 4.8)
> **Escopo:** contrato técnico do sistema tal como implementado hoje no branch de trabalho.
> Complementa: [`CLAUDE.md`](./CLAUDE.md) (runbook profundo), [`BACKEND_START.md`](./BACKEND_START.md)
> (endpoints e tabelas), [`Briefing.md`](./Briefing.md) (visão executiva) e
> [`PDR.md`](./PDR.md) (requisitos de produto).

---

## 1. Visão geral

O **Automation HUB** é uma plataforma de RPA para Windows que ingere arquivos de uma pasta
local monitorada e dirige a aplicação web **Playground** (`https://genai.stellantis.com/`) via
Playwright/Chromium. O objetivo de negócio é **eliminar o trabalho manual de subir SPECs/documentos
a workspaces seguros**, com rastreabilidade total e recuperação automática de erros.

O sistema é composto por **três processos cooperantes** que compartilham um único backend/estado:

| Processo | Módulo | Responsabilidade |
| :--- | :--- | :--- |
| **Backend** | `backend/app` (FastAPI + SQLAlchemy) | Estado central, fila de tarefas, API REST do dashboard, scheduler embutido, integrações MS Graph. |
| **Agente Local** | `backend/app/cli/local_agent.py` | Loop de polling; scan/hash de pasta; staging; dirige as tarefas Playwright; reporta de volta. |
| **RPA Playwright** | `backend/app/services/playwright/` | Login, criação de workspace, upload em lotes, monitoramento de status, conversão/reenvio PDF. |

O **frontend** é um bundle React/Vite **pré-compilado e servido estaticamente** de `dist/`. Não há
código-fonte do frontend no repositório; alterações de UI são feitas **editando o bundle minificado**
(ver §10).

---

## 2. Stack e dependências

- **Linguagem:** Python 3.x · **Framework:** FastAPI · **ASGI:** uvicorn
- **ORM/Migrações:** SQLAlchemy + Alembic
- **Banco:** SQLite (padrão, WAL) — trocável por PostgreSQL apenas via `DATABASE_URL`, sem mudança de código
- **RPA:** Playwright `1.59.0` (Chromium 1217 offline via `PLAYWRIGHT_BROWSERS_PATH`)
- **Documentos:** conversão PDF por MS Office (COM/PowerShell) → fallback LibreOffice headless
- **Relatórios:** `openpyxl` (XLSX), `reportlab` (PDF), `csv` (CSV) — imagem do card via Chromium
- **Auth/Cripto:** `python-jose` (JWT), `passlib[bcrypt]`, `secrets.compare_digest`
- **Integrações:** `msal` + Microsoft Graph (app-only, client-credentials)

Dependências completas em `backend/requirements.txt`. **Não há `requirements-dev.txt` no working copy**
(ver §12, item de dívida). Testes existem como scripts em `backend/scripts/test_*.py`.

---

## 3. Arquitetura de execução

### 3.1 Isolamento por ambiente (operacional × desenvolvedor) — restrição central

Toda requisição carrega o header **`X-App-Environment`** (`operational` default, ou `developer`/`dev`).

- `main.py` tem um middleware HTTP que chama `set_current_environment(...)` e grava um **`ContextVar`**
  (`core/config.py`) pelo tempo de vida da requisição; o agente e o scheduler fazem o mesmo por
  iteração via `environment_scope(...)`.
- **Engines e session factories são por-ambiente e cacheados** (`db/session.py`:
  `engine_for_environment` / `session_factory_for_environment`). `get_db()` resolve o engine a partir
  do ContextVar corrente → **o mesmo código atinge bancos diferentes conforme o header**. Nunca assumir
  um engine global único.
- Caminhos de runtime (browser session, logs, reports, temp, screenshots, fotos de perfil) resolvem via
  `runtime_path(name)` / `runtime_setting(name)`, que escolhem as variáveis `OPERATIONAL_*` ou
  `DEVELOPER_*`. Operacional cai no legado sem prefixo (`DATABASE_URL`, `BROWSER_SESSION_PATH`, …) para
  proteger instalações existentes; developer vive todo sob `./data/developer/`.
- **Regra de implementação:** toda feature nova que grava arquivo ou consulta banco **deve** passar por
  esses helpers — nunca hardcodar caminho ou `SessionLocal`.

### 3.2 Migrações — um ambiente por vez

Alembic (`backend/alembic/env.py`) lê `AUTOMATION_HUB_MIGRATION_ENVIRONMENT` (default `operational`) e
resolve a URL via `database_url_for_environment`. `setup_backend.bat` roda `alembic upgrade head` **uma
vez por ambiente**. O `sqlalchemy.url` do `alembic.ini` é ignorado em runtime.

**Head atual:** `0012` (`f1a2b3c4d5e6_0012_soft_delete_not_null`). Migrações-chave: `0007` (fingerprint
SHA256), `0010` (índices de performance), `0011` (`schedules.deliver_to_folder`), `0012` (soft-delete
`NOT NULL`).

### 3.3 Ciclo de vida do backend

`main.py` registra routers com dependência `protected` (`get_current_user`) ou `agent_protected`
(`require_agent_or_user`). No `startup` roda `migrate_schedules.run_migrations()` (migração leve
idempotente) e `start_schedule_runner()`; no `shutdown`, `stop_schedule_runner()`.

---

## 4. Modelo de dados

Tabelas (SQLAlchemy em `backend/app/models/`). Todas usam **soft-delete** (`is_deleted`, `deleted_at`)
e timestamps `created_at`/`updated_at`.

| Tabela | Modelo | Papel |
| :--- | :--- | :--- |
| `users` | `User` | Usuários (admin/user/viewer); estado de sessão Playground por usuário (`playground_connected`, `playground_session_path`). `email`/`network_id` únicos. |
| `automations` | `Automation` | Configuração de automação: `folder_path`, `workspace_id`, `batch_size`, timeouts, `full_execution`, `convert_to_pdf_on_error`, `config_json`. Status: `active/completed/failed/manual_review/stopped/paused/archived`. |
| `workspaces` | `Workspace` | Workspace do Playground: `playground_workspace_id`, `playground_url`, `embedding_model`, `data_languages`. |
| `workspace_files` | `WorkspaceFile` | 1 linha por arquivo detectado. `content_sha256` (dedup), `detection_task_id`, `status` (`pending/uploaded/ready/failed/manual_review/pending_retry/resolved/error`), `playground_status`, `converted_to_pdf`, marcos temporais. |
| `agent_tasks` | `AgentTask` | Fila de trabalho. `task_type`, `status`, `payload_json`, `result_json`, `attempts`/`max_attempts`. **`automation_id` NÃO é coluna — vive dentro de `payload_json`** (ver §12). |
| `local_agents` | `LocalAgent` | Registro/heartbeat dos agentes. |
| `schedules` | `Schedule` | Agendador. `frequency_type` (`once/interval/daily/weekly/monthly`), `next_run_at`, opcional `report_type`/`report_format`/`deliver_to_folder`. |
| `execution_logs` | `ExecutionLog` | Log estruturado (nível, entidade, `automation_id`, `task_id`, `file_id`, `metadata_json`). Sem tabela `automation_executions` — histórico deriva de `agent_tasks`. |
| `execution_reports` | `ExecutionReport` | Relatórios gerados: `file_path`, `generation_trigger` (`manual/automatic`), `period_start/end`, `source_task_id`. |
| `integration_connections` / `integration_deliveries` | `IntegrationConnection` / `IntegrationDelivery` | Conexões MS Graph e rastro de cada envio (`pending → sent/failed/not_configured`). Segredos removidos antes de persistir. |
| `workspace_external_users` | `WorkspaceExternalUser` | Usuários externos convidados a workspaces. |

**Diagrama de relacionamento (lógico):**

```
User 1─* Automation *─1 Workspace 1─* WorkspaceFile
                │                          │
                └── (via payload_json) ── AgentTask *─* ExecutionLog
Schedule *─1 Automation                 ExecutionReport ─ (source_task_id) ─ AgentTask
```

---

## 5. Protocolo Agente ↔ Backend

O agente itera **sobre ambos os ambientes** a cada ciclo (`SUPPORTED_ENVIRONMENTS`). Por ambiente:
`POST /heartbeat` → `POST /poll` → dirige cada tarefa por `start` → (`complete` | `fail` |
`manual-review` | `cancel`), fazendo streaming de `/log`.

### 5.1 Tipos oficiais de tarefa (6)

`connect_playground_session`, `create_playground_workspace`, `add_playground_user_to_workspace`,
`upload_files_to_workspace`, `monitor_workspace_files_status`, `convert_and_retry_file`.

**Invariante:** toda tarefa Playwright **exige `user_id`** (sessões são por-usuário); tarefa sem
`user_id` é falhada imediatamente (`local_agent.process_task`).

### 5.2 Claim atômico (poll)

`POST /api/agents/poll` seleciona até 5 tarefas `pending` (prioriza `connect_playground_session`) e
faz **UPDATE condicional** (`WHERE id=? AND status='pending'`). Só um poller vence o `rowcount==1` →
**nunca há dupla-execução** (seguro também em Postgres READ COMMITTED).

### 5.3 Mecânica de fluxo não óbvia

- **Scan roda no agente, não no request.** `create_upload_task_for_automation` enfileira um
  `upload_files_to_workspace` com `files: []`; o agente escaneia, deduplica e preenche via
  `PUT /api/agents/tasks/{id}/payload`.
- **Dedup por mtime + SHA256 (baseline persistente).** O agente puxa
  `GET /api/files/upload-baseline/{automation_id}` e pula arquivos inalterados (match exato de
  `content_sha256`; fallback `mtime <= last_ts` para registros legados). Classifica cada arquivo como
  `new` / `updated` / `audit_duplicate`. `full_execution=true` reenvia tudo.
- **Checkpoints por lote.** Cada lote enviado é confirmado por `POST /api/agents/tasks/{id}/batch-complete`
  (idempotente). Um checkpoint que falha 3× levanta `ManualReviewRequired` — **nenhum lote posterior
  é enviado às cegas**.
- **Monitoramento é um passo único.** No `complete` do upload, o backend enfileira exatamente **um**
  `monitor_workspace_files_status`; ele espera o tempo configurado **sem navegador aberto**, depois abre
  o Chromium uma vez e lê o status de todas as páginas.
  - `full_execution=True` → o monitor cobre **todos** os arquivos ativos da automação.
  - `monitor_only=True` → **nenhum** monitor web é criado (encerra sem abrir o navegador).
- **Reenvio de PDF desativa monitoramento subsequente:** arquivo com `converted_to_pdf==True` é marcado
  `ready`/`Ready` no `batch-complete`/`complete`.
- **Relatórios automáticos de monitoramento de pasta estão desativados**
  (`should_generate_folder_report → False`; endpoint retorna stub). Geração manual XLSX/PDF/CSV segue ativa.

### 5.4 Recuperação de login (headless → visível)

Se a tarefa roda headless (`payload["headless"]`, derivado de `playwright_mode == "headless"`) e o
Playground exige login, `ensure_logged_in` levanta `PlaygroundLoginRequired` em vez de esperar numa
janela invisível. `process_task` intercepta o sinal e **reexecuta a tarefa uma única vez com
`headless=False`** (navegador visível), aguardando login manual **sem** marcar a task como falha. O
`except` de `process_upload` **re-levanta** `PlaygroundLoginRequired` **antes** de marcar arquivos, para
não poluir o estado. Após o 1º login, a sessão persiste em disco (`user_data_dir` por usuário) e as
execuções seguintes voltam a rodar headless.

### 5.5 Máquina de estados (arquivo → automação)

```
WorkspaceFile: pending → uploaded → ready
                     ↘ pending_retry → (convert_and_retry → upload) → ready
                     ↘ manual_review / failed / error → (ação "Resolvido") → resolved
```

`recalculate_automation_status` (`services/agent_tasks.py`) é a **fonte única** que deriva o status da
automação a partir das tasks e arquivos relacionados (prioridade: `manual_review` > `failed` >
todos-sucesso→`completed` > limpeza de erro resolvido→`active`). É chamada no ciclo do agente
(`maybe_finalize_automation`) e em mudanças de arquivo pelo dashboard (`PUT /api/files/{id}`).

---

## 6. Invariantes do RPA Playwright (não enfraquecer)

Localização: `backend/app/services/playwright/`. Edite **cirurgicamente**.

- **Contexto Chromium persistente por usuário.** `open_persistent_chromium` usa
  `user_data_dir = BROWSER_SESSION_PATH/user_{id}`. Abre o workspace pela `workspace_playground_url`
  salva primeiro, com fallback para busca por nome.
- **Confirmação de upload é a lógica mais delicada.** Um lote conta como enviado **somente** com sinal
  real: resposta 2xx de rede numa URL de upload cujo request de fato carrega arquivo (multipart /
  octet-stream / mime de arquivo), capturada por `_NetworkCapture` iniciada **antes** do clique — **OU**
  um "Uploading Files" verde que **aparece depois** do clique. **Nunca** confirmar por texto de conclusão
  sozinho nem por verde pré-existente (causou falso-positivo histórico).
- **Deletes no monitor são verificados por F5.** Uma linha só conta como deletada após sumir no reload;
  delete não confirmado vira revisão manual, **nunca** reenvio (evita duplicatas no workspace).
- **Conversão PDF** tenta MS Office via COM/PowerShell (offline, `-EncodedCommand`), com fallback para
  LibreOffice headless com perfil dedicado. **Correção do Office órfão (T-014):** a conversão rastreia
  **só o PID que ela criou** (`HUB_PIDFILE` + snapshot `$before`) e mata apenas esse — **nunca** encerra
  o Word/Excel aberto pelo usuário.
- **Seletores são listas multilíngues** (PT/EN, incluindo typos do Playground como "Creat Workspace") em
  `selectors.py` — estenda, não substitua. Prefira `get_by_role`/label/text a CSS frágil.
- **Staging temp nunca é auto-deletado** (preservado para auditoria/reprocessamento); limpeza é manual.
- **Hierarquia de erros** em `errors.py` (`UIChangedError`, `RecoverableUploadUiError`,
  `ManualReviewRequired`, `PlaygroundLoginRequired`, …); levante o tipo certo — o agente mapeia cada um
  a um desfecho diferente.

---

## 7. API REST (superfície)

Prefixo comum: `/api`. Todos os routers em `backend/app/routers/`. Proteção conforme registro em
`main.py`:

| Grupo | Prefixo | Proteção | Notas |
| :--- | :--- | :--- | :--- |
| Health | `/api/health`, `/api/diagnostics` | pública | Diagnóstico. |
| Auth | `/api/auth` | pública | Login JWT (usado só se `AUTH_DISABLED=false`). |
| Users | `/api/users` | usuário | CRUD, foto de perfil, tema. |
| Automations | `/api/automations` | **agente ou usuário** | CRUD, `/status`, `/resolve-errors`. |
| Executions | `/api/executions` | usuário | Histórico (1 run = 1 linha, ver §8). |
| Workspaces | `/api/workspaces` | usuário | Contadores dinâmicos de arquivos/erros. |
| Files | `/api/files` | **agente ou usuário** | Registro, `/upload-baseline/{id}`, `/resolve`, `/open-folder`. |
| Logs | `/api/logs` | usuário | Consulta de `execution_logs`. |
| Reports | `/api/reports` | usuário | Geração, download, `/image`, envio E-mail/Teams. |
| Schedules | `/api/schedules` | usuário | CRUD de agendamentos. |
| Agents | `/api/agents` | **agente ou usuário** | Protocolo da §5. |
| Integrations | `/api/integrations` | usuário | MS Graph, `/deliveries`, `reports/{id}/email|teams|deliver-folder`. |
| Trash / Overview | `/api/trash`, `/api/overview` | usuário | Lixeira e visão geral da Home. |

### 7.1 Autenticação

`AUTH_DISABLED=true` é o **default de release** (deploy offline sem login):

- `get_current_user` — com auth desabilitada, retorna/cria um admin local único
  (`get_or_create_local_user`, o primeiro admin ativo por `id`; faz backfill dos valores canônicos
  `LOCAL_ADMIN_*`). O caminho JWT completo é preservado para `AUTH_DISABLED=false`.
- `require_agent_or_user` — aceita `X-Agent-Token` (comparação constante `compare_digest` contra
  `AGENT_SHARED_TOKEN`) **ou** um usuário. O mesmo token deve bater em backend e agente.

---

## 8. Scheduler embutido

`services/schedule_runner.py` roda um loop asyncio iniciado no `startup`. Cada tick chama
`run_due_schedules_for_all_environments`, iterando **ambos** os ambientes sob `environment_scope`.
Horários em São Paulo local (`core/timezone.py`). Frequências: `once` / `interval` / `daily` /
`weekly` / `monthly`.

- Agendamento **de automação** chama `create_upload_task_for_automation` (caminho manual).
- Agendamento **de relatório** (`report_type` setado) chama `run_due_report_schedule(...)`: consulta
  automaticamente os dados de auditoria dos **últimos 30 dias** e grava o relatório sob a subpasta
  `agendados/` de `REPORTS_PATH`.
- **Entrega na pasta (`REPORT_DELIVERY_PATH`, Power Automate/Teams) é opt-in por agendamento** via
  `schedules.deliver_to_folder`. `persist_report(..., deliver_to_folder=...)` só grava na pasta de
  entrega para o **"Relatório Simplificado"** quando a flag está ligada (ou na geração **manual** desse
  tipo). Qualquer outro tipo fica só em `REPORTS_PATH`.

**Contagem de execuções (auditoria T-012):** tanto o Histórico ao vivo (`list_executions`) quanto o
relatório (`block_executions`) agrupam as tasks satélites (reenvio de PDF pós-monitoramento, que também
é `upload_files_to_workspace` e carrega `origin_task_id`) na **task raiz** → **1 run = 1 execução**.

---

## 9. Integrações (MS Graph) e entrega de relatórios

`routers/integrations.py` + `services/integrations/graph_client.py` enviam e-mail, mensagens no Teams e
eventos de calendário via Microsoft Graph (app-only, MSAL client-credentials), registrando cada envio
como `IntegrationDelivery`. Segredos são removidos (`sanitize_for_storage`) antes de qualquer JSON
persistido.

- **Config desligada por padrão.** Sem `MS_GRAPH_*` no `.env`, todo envio retorna `not_configured`
  graciosamente (sem crash). Ressalvas: anexo inline ≈3 MB máx; post app-only em canal do Teams é
  *protected API* (frequente 403 — webhook/e-mail são mais confiáveis).
- **Card semanal do Teams como IMAGEM (T-009):** o HUB gera um **PNG** fiel ao mockup (HTML+SVG 100%
  offline → screenshot com Chromium 1217, renderizado em thread) — `services/report_image.py` +
  `compute_card_image_data`/`build_report_image_card` em `reports.py`. **Fallback** automático para o
  card-texto de adoção quando o PNG não gera. Botões: **Abrir Playground / Solicitar Acesso / Baixar PDF**.
- **Entrega sem registro (MS Graph indisponível):** (1) **pasta de pickup** — `REPORT_DELIVERY_PATH`
  recebe o relatório + sidecar `.json`; aponte para pasta sincronizada OneDrive/SharePoint e um fluxo do
  Power Automate entrega (ver `GUIA_POWER_AUTOMATE.md`). (2) **Teams deep link** — botão no dashboard.

---

## 10. Frontend (bundle pré-compilado)

- **Sem fonte no repo** — `dist/assets/index-*.js` é um bundle **minificado editado à mão** (com backups
  `.bak*` timestampados). Alterações de UI = edição direta do bundle: faça backup, mudança
  auto-contida, valide copiando para `.mjs` e rodando `node --check`.
- **UI injetada DEVE usar os helpers `Oe`/`kt`** do bundle (para enviar o header `X-App-Environment`);
  `fetch` cru atingiria o banco do ambiente errado.
- Defaults de criação por automação vêm de `localStorage.hub_settings`; botões de envio de relatório
  (`ReportSendActions`), ação "Pasta" (Explorer), status Playground colorido e contadores dinâmicos de
  workspace foram adicionados desse jeito (histórico em `CLAUDE.md`).

---

## 11. Configuração (settings principais)

Fonte: `backend/app/core/config.py` (Pydantic `Settings`, `.env`). Destaques:

| Chave | Default | Papel |
| :--- | :--- | :--- |
| `AUTH_DISABLED` | `true` | Deploy offline sem login. |
| `AGENT_SHARED_TOKEN` | `local-dev-agent-token` | Token do agente (deve bater nos dois lados). |
| `PLAYWRIGHT_HEADLESS` | `false` | `false` permite SSO manual na janela visível. |
| `UPLOAD_BATCH_SIZE` | `5` | Tamanho do lote de upload. |
| `UPLOAD_COMPLETE_STABLE_SECONDS` / `BATCH_SENT_TIMEOUT_SECONDS` / … | — | SLAs de confirmação de upload (externalizados; **não enfraquecer** a heurística). |
| `MANUAL_LOGIN_TIMEOUT_MINUTES` | `10` | Espera do login manual. |
| `REPORT_DELIVERY_PATH` | `""` | Pasta de pickup do Power Automate (por ambiente). |
| `REPORT_MINUTES_PER_FILE` | `4.0` | Minutos poupados por arquivo → "horas economizadas" no card. |
| `MS_GRAPH_*` | `""` | Credenciais Graph (desligado se vazio). |
| `REPORT_BACKEND_BASE_URL` | `""` | Base HTTP alcançável pelo Teams para links diretos de imagem/PDF. |

Caminhos de runtime têm variantes `OPERATIONAL_*` / `DEVELOPER_*` (ver §3.1).

---

## 12. Revisão de código — achados e dívida técnica

Revisão estática realizada em 2026-07-15 (compileall limpo, exit 0). Pontos fortes: isolamento por
ambiente consistente; claim atômico de tarefa; heurística de confirmação de upload defensiva; dedup +
checkpoints por lote impedem duplicatas; `get_db` faz rollback-on-exception (evita
`PendingRollbackError` em cascata); correção do Office órfão é cuidadosa.

**Achados priorizados** (nenhum bloqueante hoje; sem alteração de comportamento nesta entrega):

| # | Sev. | Local | Descrição | Recomendação |
| :--- | :--- | :--- | :--- | :--- |
| 1 | **Média** | `services/agent_tasks.py` (`recalculate_automation_status`), `routers/agents.py` (`related_automation_tasks`), `routers/reports.py` (`block_executions`) | `automation_id` vive dentro de `agent_tasks.payload_json`, não em coluna → não dá para filtrar em SQL. Essas rotinas carregam **todas** as tasks dos tipos de automação e filtram em Python parseando JSON. Custo O(N) sobre todo o histórico a cada finalização/poll. | Promover `automation_id` (e talvez `workspace_id`, `origin_task_id`) a colunas indexadas em `agent_tasks`, com migração de backfill. |
| 2 | Baixa-Média | `routers/agents.py:182-185` (`update_files_from_result`) | Quando falta `file_id`, o match de arquivo é por `file_name` **global** (só `is_deleted==False`), não escopado à automação/workspace da task. Dois arquivos homônimos em automações distintas poderiam cruzar. | Escopar o fallback por nome ao `automation_id` da task. |
| 3 | Baixa | `routers/agents.py:210` (`update_files_from_result`) | Ramo `elif playground_status == "Pending" and file_name in retry_names:` é **código morto** — o `if file_name in retry_names` no topo do mesmo bloco já trata o caso. | Remover o ramo inalcançável. |
| 4 | Baixa | `main.py:21,28` | `@app.on_event("startup"/"shutdown")` está **deprecado** no FastAPI/Starlette (migração para `lifespan`). Funciona hoje. | Migrar para o handler `lifespan` quando conveniente. |
| 5 | Baixa | `heartbeat` (`routers/agents.py`) | Upsert de `LocalAgent` por `name` sem filtro `is_deleted` e sem unicidade; heartbeats concorrentes poderiam duplicar linha. Baixo risco (deploy de 1 agente). | Filtrar `is_deleted==False` e/ou unique constraint em `name`. |
| 6 | Baixa | Documentação | `CLAUDE.md`/comandos citam `backend/tests` + pytest e `requirements-dev.txt`, mas o working copy **não tem** `tests/` nem `requirements-dev.txt` — testes vivem como scripts em `backend/scripts/test_*.py`. `CLAUDE.md` também ainda referencia a feature **IPC removida (T-013)** na seção de builders de release. | Reconciliar `CLAUDE.md`/`RELEASE_POLICY.md` com o estado atual (remover menções a IPC e ao layout de tests). |

Detalhe do achado #1 é a dívida arquitetural mais relevante: torna o custo de finalização proporcional
ao histórico total, não ao tamanho do run.

---

## 13. Política de release (resumo)

Release corporativa é **offline e sanitizada** (`RELEASE_POLICY.md`). **Nunca** empacotar: `*.db`, logs,
`__pycache__`, browser sessions, `backend/tests`, `requirements-dev.txt`, `src` do frontend, `.venv`,
`node_modules`, backups `.bak`. **Incluir:** `dist/` compilado, `backend/app`, `backend/alembic`,
`backend/ms-playwright` (Chromium 1217 offline). `PLAYWRIGHT_HEADLESS=false` para SSO manual.

Builders: `scripts/build_release_empty_db.py` (release completa, DB vazio) e
`scripts/build_update_package.py` (pacote incremental). Ambos filtram `.bak` via `".bak" in name`.

> **Nota:** a feature IPC (`custom_automations/`) foi **removida** em 2026-07-07 (T-013); menções a ela
> em `CLAUDE.md` e nos builders são dívida de documentação (achado #6).
