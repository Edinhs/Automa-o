# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**Stellantis Automation HUB** is a Windows-targeted RPA platform that ingests files from a monitored local folder and drives the **Playground** web app (`https://genai.stellantis.com/`) via Playwright. Three cooperating processes:

1. **Backend** (`backend/app`) — FastAPI + SQLAlchemy. Central state, task queue, REST API for the dashboard, embedded scheduler.
2. **Local agent** (`backend/app/cli/local_agent.py`) — long-running Python CLI. Polls the backend task queue, scans the monitored folder, hashes files (SHA256) for dedup, stages uploads, and reports back.
3. **Playwright RPA** (`backend/app/services/playwright/`) — drives Chromium against Playground for login, workspace sync, batched upload, and processing monitoring.

The frontend is a pre-built React/Vite bundle served statically from `dist/` (source is not in this repo / release). Most existing docs are in Portuguese — see `ANTIGRAVITY.MD` (deep architecture/runbook), `BACKEND_START.md` (backend contract & data tables), `Briefing.md`, `RELEASE_POLICY.md`, and `AGENTES_E_SKILLS.md` (catalog of the specialized Claude Code subagents in `.claude/agents/`).

## Commands

Everything runs from the repo root on Windows. The Python venv lives at `backend\.venv`.

```powershell
.\setup_backend.bat        # once: create .venv, install backend\requirements.txt, run migrations for BOTH envs
.\start_all.bat            # start backend (8000), dashboard (5173, python http.server), agent — hidden windows
.\restart_services.bat     # kill only HUB-owned processes, then restart
.\start_backend.bat        # individual services; each sets PLAYWRIGHT_BROWSERS_PATH to offline Chromium
.\start_dashboard.bat
.\start_agent.bat
.\build_release_empty_db.bat   # build the offline corporate release ZIP (scripts\build_release_empty_db.py)
```

Dev / validation (tests and `requirements-dev.txt` are **not** in the strict release):

```powershell
cd backend
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest tests -q                 # run tests
.\.venv\Scripts\python.exe -m pytest tests/path::test_name -q # single test
.\.venv\Scripts\python.exe -m alembic current                 # check migration head
cd ..
.\backend\.venv\Scripts\python.exe -m compileall backend\app  # static compile check
```

## Architecture — the non-obvious parts

### Dual-environment isolation (operational vs. developer)
This is the central design constraint. Every request carries an `X-App-Environment` header (`operational` default, or `developer`/`dev`). `backend/app/main.py` middleware sets a `ContextVar` (`backend/app/core/config.py`) for the request's lifetime; the agent and scheduler set it per loop via `environment_scope(...)`.

- DB engines and session factories are **per-environment and cached** (`backend/app/db/session.py` — `engine_for_environment` / `session_for_environment`). `get_db()` resolves the engine from the current ContextVar, so the same code path hits different databases depending on the header. Never assume a single global engine.
- Runtime paths (browser session, logs, reports, temp, screenshots, profile photos) resolve through `runtime_path(name)` / `runtime_setting(name)`, which pick `OPERATIONAL_*` or `DEVELOPER_*` env vars by environment. Operational mode falls back to the legacy unprefixed vars (`DATABASE_URL`, `BROWSER_SESSION_PATH`, …) to protect existing installs; developer mode lives entirely under `./data/developer/`.
- When adding a feature that writes files or queries the DB, route it through these helpers — do not hardcode paths or `SessionLocal`.

### Migrations target one environment at a time
Alembic (`backend/alembic/env.py`) reads `AUTOMATION_HUB_MIGRATION_ENVIRONMENT` (default `operational`) and resolves the URL via `database_url_for_environment`. `setup_backend.bat` runs `alembic upgrade head` once per environment by setting that var. The `sqlalchemy.url` in `alembic.ini` is effectively ignored at runtime.

### Auth model
`AUTH_DISABLED=true` is the release default. Auth dependencies live in `backend/app/routers/deps.py`:
- `get_current_user` — when auth is disabled, returns/creates a single local admin (`get_or_create_local_user`) instead of validating a JWT. The full JWT login path is preserved for `AUTH_DISABLED=false`.
- `require_agent_or_user` (used by `/api/automations`, `/api/files`, `/api/agents`) — accepts the agent's `X-Agent-Token` header (constant-time `compare_digest` against `AGENT_SHARED_TOKEN`) **or** a user. The same token value must match on backend and agent.
- Routers are registered in `main.py` with either `protected` (`get_current_user`) or `agent_protected` (`require_agent_or_user`) dependencies.
- **Gotcha:** `deps.py` hardcodes the local admin's real identity and a bcrypt password hash (`LOCAL_USER_*` constants) — this is intentional for the no-login release, *not* a placeholder. `get_or_create_local_user` returns the first active admin (lowest id) and backfills those canonical values; don't "clean it up" without asking.

### Agent ↔ backend protocol
The agent loops over **both** environments each cycle: heartbeat, `POST /api/agents/poll` (claims up to 5 pending tasks, `connect_playground_session` prioritized), then drives each task through `start` → (`complete` | `fail` | `manual-review` | `cancel`), streaming `/log`. Six official task types: `connect_playground_session`, `create_playground_workspace`, `add_playground_user_to_workspace`, `upload_files_to_workspace`, `monitor_workspace_files_status`, `convert_and_retry_file`. Every Playwright task **requires a `user_id`** (sessions are per-user); a task without one is failed. Endpoints and canonical table names are in `BACKEND_START.md` — there is no `automation_executions` table, history derives from `agent_tasks`.

Non-obvious flow mechanics (`cli/local_agent.py` + `routers/agents.py`):
- **The folder scan runs agent-side, not at request time.** `create_upload_task_for_automation` enqueues an `upload_files_to_workspace` task with `files: []`; the agent scans, hashes, and fills the payload via `PUT /api/agents/tasks/{id}/payload`.
- **Persistent SHA256 dedup across runs.** The agent pulls `GET /api/files/upload-baseline/{automation_id}` and skips unchanged files (exact sha256 match; `mtime <= last_ts` fallback for legacy rows without a hash). Each file is classified `new` / `updated` / `audit_duplicate`. `full_execution=true` resends everything.
- **Per-batch checkpoints.** Each uploaded batch is confirmed via `POST /api/agents/tasks/{id}/batch-complete` (idempotent; marks files `uploaded`/`Pending`). A failed checkpoint raises `ManualReviewRequired` — no later batch is sent blind.
- **Monitoring is a single pass.** On upload `complete` the backend enqueues exactly one `monitor_workspace_files_status` task; it waits the configured time **with no browser open**, then opens Chromium once and reads status across all pages. `monitor_interval_seconds` is effectively legacy.
  - **Execução Completa:** Se `full_execution` for `True` no payload da tarefa de upload, o monitoramento subsequente incluirá todos os arquivos ativos da automação (`WorkspaceFile.automation_id == automation_id`).
  - **Apenas Monitoramento de Pasta:** Se `monitor_only` for `True` no payload da tarefa de upload, nenhuma tarefa de monitoramento web subsequente será criada, completando a execução sem abrir o navegador web.
- **Automatic folder-monitoring reports are disabled** (`should_generate_folder_report` → `False`; the `/folder-monitoring-report` endpoint returns a stub). Manual XLSX/PDF/CSV report generation still works.
- **Status do arquivo convertido:** Quando um lote de upload é confirmado (`batch-complete`) ou quando a tarefa de upload é completada (`complete`), se o arquivo tiver `converted_to_pdf == True` (indicando que foi convertido e enviado), seu status é imediatamente atualizado para `ready` (e playground_status `Ready`), uma vez que reenvios de PDF desativam o monitoramento subsequente.
- `maybe_finalize_automation` sets the automation's terminal status (`manual_review` / `failed` / `completed`) from its related tasks and files.

### Playwright RPA invariants (`backend/app/services/playwright/`)
RPA here is fragile by nature — edit surgically and preserve the resilience heuristics:
- **Per-user persistent Chromium context.** `open_persistent_chromium` uses `user_data_dir = BROWSER_SESSION_PATH/user_{id}` (resolved per environment). Offline Chromium 1217 via `PLAYWRIGHT_BROWSERS_PATH`; `PLAYWRIGHT_HEADLESS=false` for manual SSO. Open a workspace by its saved `workspace_playground_url` first, fall back to search-by-name.
- **Upload confirmation is the most delicate logic.** A batch counts as sent only on a *real* signal: a 2xx network response on an upload URL whose request actually carries a file (multipart / octet-stream / file mime), captured by `_NetworkCapture` started *before* the click — OR a green "Uploading Files" that *appears after* the click. Never confirm on completion text alone or pre-existing green (this caused a historical false positive). Do not weaken it.
- **Deletes in the monitor are F5-verified.** A row counts as deleted only after it disappears on reload; an unconfirmed delete becomes manual review, never a resend (prevents duplicates in the workspace).
- **PDF conversion** tries MS Office via COM/PowerShell (offline, `-EncodedCommand`), then falls back to LibreOffice headless with a dedicated profile.
- **Selectors are multilingual lists** (PT/EN, including Playground typos like "Creat Workspace") in `selectors.py` — extend them, don't replace. Prefer `get_by_role`/label/text over brittle CSS.
- **Staging temp is never auto-deleted** (preserved for audit/reprocessing); cleanup is manual.
- Errors have a hierarchy in `errors.py` (`UIChangedError`, `RecoverableUploadUiError`, `ManualReviewRequired`, …); raise the right type — the agent maps each to a different outcome.
- **Login headless → retry visível (não finalizar a task).** Se uma tarefa roda headless (`payload["headless"]`, derivado de `playwright_mode == "headless"`) e o Playground exige login, `ensure_logged_in` e o login inline de `connect_playground_session` (em `playground_login.py`) levantam `PlaygroundLoginRequired` **em vez de** esperar numa janela invisível até `MANUAL_LOGIN_TIMEOUT_MINUTES`. O dispatcher `process_task` (via `_dispatch_task_body`, em `cli/local_agent.py`) intercepta esse sinal e **reexecuta a tarefa uma única vez com `headless=False`** (navegador visível), aguardando o login manual sem marcar a task como falha. O `except` de `process_upload` re-levanta `PlaygroundLoginRequired` **antes** de marcar arquivos, para não poluir estado. Cobre upload, monitor, workspace, users e connect e — transitivamente — `convert_and_retry_file` (a task-filha `upload_files_to_workspace` herda o payload). Como a checagem de login ocorre antes de qualquer envio e a sessão persiste em disco (`user_data_dir` por usuário), o retry é seguro (dedup SHA256 + checkpoints por lote) e, após o 1º login, as execuções seguintes voltam a rodar headless. *(Lacuna conhecida: se a sessão expirar exatamente durante a recuperação de UI mid-lote em `recover_upload_area_in_same_session`, o sinal é absorvido pelo `except` de resiliência — caso raro, deixado fora de escopo para não enfraquecer a heurística.)*

### Embedded scheduler
`services/schedule_runner.py` runs an asyncio loop started in `main.py`'s startup event. Each tick calls `run_due_schedules_for_all_environments`, iterating **both** environments under `environment_scope`. Times are São Paulo local (`core/timezone.py`); frequencies are `once` / `interval` / `daily` / `weekly` / `monthly`. A due schedule for automations calls `create_upload_task_for_automation` (manual path). If a due schedule is for reports (`report_type` is set), it calls `run_due_report_schedule(...)` which automatically queries audit data of the last 30 days and generates the report file under the `agendados/` subfolder in `REPORTS_PATH` (`backend/data/reports`). Copying the report to the delivery folder (`REPORT_DELIVERY_PATH`, for Power Automate/Teams) is **opt-in per schedule** via `schedules.deliver_to_folder` (toggle in the "Agendar Relatório" modal) — `persist_report(..., deliver_to_folder=...)` only writes to the delivery folder when that flag is on; otherwise the report stays only in `REPORTS_PATH`.

### Integrations (MS Graph) & report delivery
`routers/integrations.py` + `services/integrations/graph_client.py` send mail, Teams messages and calendar events via Microsoft Graph (app-only, MSAL client-credentials), recording each send as an `IntegrationDelivery` (`pending → sent | failed | not_configured`) shown at `GET /api/integrations/deliveries`. Secrets are stripped (`sanitize_for_storage`) before any request/response JSON is persisted.
- **Report delivery:** `POST /api/integrations/reports/{report_id}/email` (attaches the report file as a Graph `fileAttachment`; body `{to_recipients, subject?, body?}`) and `POST /api/integrations/reports/{report_id}/teams` (posts the report summary + download link). Both load the report via `report_delivery_bundle` in `routers/reports.py`. The dashboard triggers these from per-report **E-mail**/**Teams** buttons (`ReportSendActions`, injected in the bundle).
- **Config is off by default.** Set `MS_GRAPH_TENANT_ID/CLIENT_ID/CLIENT_SECRET/SENDER_USER` (+ `MS_GRAPH_TEAMS_WEBHOOK_URL` **or** `MS_GRAPH_TEAMS_TEAM_ID`+`MS_GRAPH_TEAMS_CHANNEL_ID`) in `backend/.env`. Without them every send returns `not_configured` gracefully (no crash). Caveats: inline attachment ≈3 MB max; app-only Teams channel posts are a Graph *protected API* (often 403 — webhook/email are more reliable); the Teams download link uses the request host (local-only unless overridden).
- **No-registration delivery (when MS Graph is unavailable — see `GUIA_POWER_AUTOMATE.md`).** (1) **Folder pickup:** if `REPORT_DELIVERY_PATH` is set (per-env helper `report_delivery_dir` in `config.py`), `persist_report` auto-copies each generated report + a `.json` sidecar into that folder; `POST /api/integrations/reports/{id}/deliver-folder` does it on demand (tracked, provider `PowerAutomate`). Point it at a OneDrive/SharePoint-synced folder and a Power Automate flow delivers it (Teams/email). (2) **Teams deep link:** the dashboard's per-report **Teams** button downloads the report and `window.open`s `hub_settings.teamsDeepLink` (configurable in Settings) — manual attach, no backend.

### Frontend & operational gotchas
- **The frontend has no source in this repo** — `dist/` is a *hand-edited* minified bundle (`dist/assets/index-*.js`, with timestamped `.bak*` backups). To change UI behavior you edit the bundle directly: back it up, make the change self-contained, and validate by copying to a `.mjs` and running `node --check`. Injected UI **must** use the bundle's `Oe`/`kt` fetch helpers so the `X-App-Environment` header is sent (raw `fetch` would hit the wrong-environment DB). The per-automation create defaults (read from `localStorage.hub_settings`) and the report send buttons were added this way.
- **Recent Hand-Edits to the Frontend Bundle (June 2026):**
  - **Monitored File Types (`pW` component):** Converted the file types selection grid into a modal pop-up (`fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4`). It handles visibility using local state `[o, c] = x.useState(!1)`. The confirm button uses `bg-blue-600 hover:bg-blue-700 text-white`.
  - **Autobutton/Filter Clean (`lW` search bar):** Removed the redundant gray secondary button `"Filtros"`. Now, only `children: r` (dynamic filters dropdowns) are rendered alongside the search bar, yielding a cleaner look.
  - **Playground Status Button (`qW` Profile component):** Overhauled to support both adapted camelCase and raw snake_case API data: checks `(e.playgroundConnected || e.playground_connected)`. Upgraded to solid status colors (Green `bg-emerald-600 hover:bg-emerald-700` when logged in, Red `bg-rose-600 hover:bg-rose-700` when login is required) and added a white status LED indicator with pulsing shadow (`animate-ping bg-white` + `bg-white`) on the right side of the button.
  - **Erros Resolvidos Pizza Chart (`DP` Home overview component):** Fixed the successful errors count rendering. The `yX_ErrorsPie` component now consumes `U_final.errorsResolved` instead of the undefined `U.errorsResolved`.
  - **File Audit Actions & Mapping (`xW` & `CP` components):**
    - Added `"resolved": "Resolvido"` to the `CP` status mapper so that resolved files display properly in Portuguese.
    - Updated the file delete action to invoke `kt("DELETE", {})` instead of `{ method: "DELETE" }` to ensure proper header/payload encoding.
    - Adjusted the `isError` check inside `xW` to exclude `"resolved"` and `"pending_retry"` files, thereby dynamically hiding action buttons ("Resolvido" / "Reprocessar") once the action is triggered.
  - **Dynamic Workspace Counters (Backend & Frontend):**
    - Modified the `GET /api/workspaces` route and `workspace_out` function in the backend (`backend/app/routers/workspaces.py`) to query the `workspace_files` table and calculate the exact counts of files (`files_count`) and errors (`errors_count` for status `error`/`failed`) dynamically for each workspace.
    - Modified the mapping inside the frontend bundle `dist/assets/index-BBcj3Zw-.js` to consume these dynamic counters: `files: e.files_count || 0` and `errors: e.errors_count || 0` instead of static/placeholders.
  - **Relatórios Gerados e Agendamentos (Backend e Frontend):**
    - **Caminho dos Relatórios:** `REPORTS_PATH` = `./data/reports` e `DEVELOPER_REPORTS_PATH` = `./data/developer/reports` em `backend/app/core/config.py` (relativo a `backend/`). Relatórios automáticos de agendamentos são gravados sob a subpasta `agendados/`. A cópia para a pasta de entrega (`REPORT_DELIVERY_PATH`) deixou de ser automática: virou **opt-in por agendamento** (`schedules.deliver_to_folder`, botão no modal "Agendar Relatório"). *(Antes: `../relatorios/` na raiz, jun/2026 — revertido a pedido para `backend/data/reports`.)*
    - **Ação de E-mail por relatório:** O botão **E-mail** existe na lista de relatórios (componente `ReportSendActions`, ao lado de **Teams** e **Download**): abre um modal que envia o relatório via `POST /api/integrations/reports/{id}/email` (MS Graph). *(Correção 2026-07-04: uma nota anterior afirmava que este botão fora "removido completamente" — não confere com o bundle atual, que o renderiza e funciona; ver a seção "Integrations" acima, que também o documenta como recurso.)*
    - **Botão e Modal de Agendamento:** Adicionou o botão "Agendar Relatório" na aba Relatórios que renderiza um modal no frontend permitindo configurar o Tipo do Relatório, Formato do Arquivo (XLSX, PDF, CSV), Frequência e Data/Hora inicial, persistindo no banco de dados SQLite sem necessidade de `automation_id`.
  - **Exclusão de Execução no Histórico (Backend e Frontend):**
    - **Ação de Exclusão no Frontend:** Adicionou um botão "Excluir" em vermelho na tabela do Histórico de Execuções (`jW` component) que, sob confirmação, efetua uma requisição DELETE para `/api/executions/{id}` e atualiza a lista de imediato usando o estado `refreshVersion`.
    - **Limpeza de Dados no Backend:** Atualizou o endpoint `delete_execution` em `backend/app/routers/executions.py` para apagar logicamente os arquivos e relatórios daquela execução no banco, e fisicamente todos os logs da execução na tabela `execution_logs` (liberando espaço e garantindo integridade de exclusão de dados).
  - **Ação "Pasta" na Auditoria de Arquivos — abrir a pasta no Explorer (Backend e Frontend, 2026-07-10):**
    - **Frontend (`xW` + handler de `onAction` da Auditoria de Arquivos):** Adicionou uma nova ação "Pasta" (label `isEn ? "Folder" : "Pasta"`) ao lado de Detalhes/Logs em cada arquivo. O botão dispara `t("folder")`; o handler ganhou um branch `type === "folder"` que chama `await Oe(`/api/files/${P.id}/open-folder`, kt("POST", {}))` (helpers `Oe`/`kt`, para enviar `X-App-Environment`). O branch explícito é obrigatório, senão "folder" cairia no `else` final e abriria um modal inexistente. Backup do bundle: `index-BBcj3Zw-.js.bak_pasta_action_20260710_180547`.
    - **Backend (`backend/app/routers/files.py`, após `get_file`):** Novo endpoint `POST /api/files/{id}/open-folder`. Abre a pasta do arquivo no Windows Explorer do host local onde o backend roda: prioriza `original_path` via `subprocess.Popen('explorer /select,"<path>"')` (abre a pasta e seleciona o arquivo) e faz fallback para o `folder_path` da automação vinculada (só abre a pasta, via `os.startfile`). Guard `sys.platform == "win32"`; `explorer.exe` é chamado fire-and-forget pois retorna código != 0 mesmo em sucesso; caminho sempre vem do banco (nunca input arbitrário). Erros 404/400/500 com `detail` legível.
- **Restart the backend after editing `backend/app`.** A long-running backend (from `start_all.bat`) keeps serving the old code until restarted; `restart_services.bat` kills only HUB-owned processes on 8000/5173 and relaunches hidden. A stale process — or a stale `__pycache__` — makes new routes return 404.


### SQLite specifics
SQLite connections set `journal_mode=WAL` and `busy_timeout=5000` (session.py). `DATABASE_URL` can point at PostgreSQL without code changes.

## Release policy (critical)

The corporate release is offline and tightly sanitized — see `RELEASE_POLICY.md`. **Never** package: `*.db`, logs, `__pycache__`, browser sessions, `backend/tests`, `requirements-dev.txt`, frontend `src`, `.venv`, `node_modules`. **Do** include the built `dist/`, `backend/app`, `backend/alembic`, and `backend/ms-playwright` (offline Chromium 1217, set via `PLAYWRIGHT_BROWSERS_PATH` to bypass corporate proxy/cert blocks). `PLAYWRIGHT_HEADLESS=false` so the user can do manual SSO login in the visible browser.

## Layout

- `backend/app/routers/` — REST endpoints (one file per resource) + `deps.py` (auth)
- `backend/app/models/` — SQLAlchemy models; `backend/app/schemas/` — Pydantic schemas
- `backend/app/services/` — `agent_tasks.py`, `automation_staging.py`, `schedule_runner.py`, `audit.py`, `playwright/`, `integrations/graph_client.py` (MS Graph / Teams)
- `backend/app/core/` — `config.py` (settings + environment ContextVar), `security.py`, `timezone.py`
- `backend/app/cli/` — `local_agent.py`, `create_admin_user.py`, `purge_legacy_reports.py`
- `scripts/` — `start_hidden_service.ps1` (hides windows, redirects logs), `build_release_empty_db.py`
- `.claude/agents/` — specialized Claude Code subagents (`db-expert`, `local-agent-expert`, `playwright-rpa-expert`, `fastapi-expert`, `release-integrity-expert`); catalog + orchestration model in `AGENTES_E_SKILLS.md`
