# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**Stellantis Automation HUB** is a Windows-targeted RPA platform that ingests files from a monitored local folder and drives the **Playground** web app (`https://genai.stellantis.com/`) via Playwright. Three cooperating processes:

1. **Backend** (`backend/app`) — FastAPI + SQLAlchemy. Central state, task queue, REST API for the dashboard, embedded scheduler.
2. **Local agent** (`backend/app/cli/local_agent.py`) — long-running Python CLI. Polls the backend task queue, scans the monitored folder, hashes files (SHA256) for dedup, stages uploads, and reports back.
3. **Playwright RPA** (`backend/app/services/playwright/`) — drives Chromium against Playground for login, workspace sync, batched upload, and processing monitoring.

The frontend is a pre-built React/Vite bundle served statically from `dist/` (source is not in this repo / release). Most existing docs are in Portuguese — see `ANTIGRAVITY.MD` (deep architecture/runbook), `BACKEND_START.md` (backend contract & data tables), `Briefing.md`, and `RELEASE_POLICY.md`.

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

### Agent ↔ backend protocol
The agent loops over **both** environments each cycle, heartbeating and polling `/api/agents/poll`, then driving each task through `start` → (`complete` | `fail` | `manual-review` | `cancel`), streaming `/log`, and posting folder-monitoring reports. Endpoint list and the canonical DB table names are documented in `BACKEND_START.md` (note: there is no `automation_executions` table — execution history is derived from `agent_tasks`).

### SQLite specifics
SQLite connections set `journal_mode=WAL` and `busy_timeout=5000` (session.py). `DATABASE_URL` can point at PostgreSQL without code changes.

## Release policy (critical)

The corporate release is offline and tightly sanitized — see `RELEASE_POLICY.md`. **Never** package: `*.db`, logs, `__pycache__`, browser sessions, `backend/tests`, `requirements-dev.txt`, frontend `src`, `.venv`, `node_modules`. **Do** include the built `dist/`, `backend/app`, `backend/alembic`, and `backend/ms-playwright` (offline Chromium 1217, set via `PLAYWRIGHT_BROWSERS_PATH` to bypass corporate proxy/cert blocks). `PLAYWRIGHT_HEADLESS=false` so the user can do manual SSO login in the visible browser.

## Layout

- `backend/app/routers/` — REST endpoints (one file per resource) + `deps.py` (auth)
- `backend/app/models/` — SQLAlchemy models; `backend/app/schemas/` — Pydantic schemas
- `backend/app/services/` — `agent_tasks.py`, `automation_staging.py`, `schedule_runner.py`, `audit.py`, `playwright/`, `integrations/graph_client.py` (MS Graph / Teams)
- `backend/app/core/` — `config.py` (settings + environment ContextVar), `security.py`, `timezone.py`
- `backend/app/cli/` — `local_agent.py`, `create_admin_user.py`, `purge_legacy_reports.py`, `purge_staging.py` (retenção opt-in de staging via `STAGING_RETENTION_DAYS`)
- `scripts/` — `start_hidden_service.ps1` (hides windows, redirects logs), `build_release_empty_db.py`
- `.agy/` — Antigravity agent/skill definitions (reference docs, not executable)
