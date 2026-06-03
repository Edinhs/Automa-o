# Relatório de Estudo — Melhorias do Automation HUB

> Estudo conduzido em 2026-06 com 3 agentes de exploração (backend/API/DB, RPA/Playwright/agente,
> arquitetura/testes/release/docs) e **verificação manual** dos achados críticos. Documento de trabalho —
> **não** faz parte do pacote de release (ver §6).

---

## 1. Sumário executivo

O **Stellantis Automation HUB** é uma plataforma RPA Windows, **offline e single-user** (notebook
corporativo), que ingere arquivos de uma pasta monitorada e dirige o Playground GenAI
(`https://genai.stellantis.com/`) via Playwright. Três processos cooperam: backend FastAPI, agente local
CLI e a automação Playwright.

**Estado geral: sólido na arquitetura, frágil em testes e observabilidade.**

Pontos fortes confirmados:
- **Isolamento dual-environment** (operational vs developer) bem implementado via `ContextVar` +
  engines/paths por ambiente (`config.py`, `session.py`).
- **Higiene de release** automatizada e sanitizada (`scripts/build_release_empty_db.py` +
  `RELEASE_POLICY.md`).
- **Chromium offline embutido** (`backend/ms-playwright`) contorna proxy/cert corporativos.
- **Scheduler embutido** in-process (asyncio), sem fila externa.

Fragilidades principais:
- **Cobertura de testes mínima**: 1 arquivo de teste para ~68 arquivos Python.
- **Confiabilidade do RPA**: timeouts mágicos hardcoded, seletores por texto literal, retry sem backoff.
- **Integração Teams nova e fora do controle de versão** (models/router/migration untracked, sem docs).
- **Observabilidade**: export de logs sem paginação (risco de OOM), sem rotação.

---

## 2. Metodologia e transparência

A investigação combinou exploração automatizada (3 agentes) com **leitura direta** dos arquivos para
confirmar os achados. Vários achados dos agentes foram **exagerados** e ficam aqui corrigidos para evitar
trabalho desnecessário:

| Achado do agente | Veredito | Evidência |
|---|---|---|
| `ast.literal_eval` = "RCE" em `agents.py:94` | ❌ **Falso** | `literal_eval` só avalia literais (dict/list/str/num); `__import__(...)` lança `ValueError`. No máximo *code smell*; payload é controlado pelo backend. |
| "AUTH_DISABLED bypassa token do agente" | ❌ **Por design** | `require_agent_or_user` (deps.py:116-131) valida `X-Agent-Token` com `compare_digest` **antes**; `AUTH_DISABLED=true` é o padrão intencional do release offline. |
| Path traversal apaga arquivos arbitrários via foto | ❌ **Mitigado** | `delete_existing_profile_photo` (auth.py:69-78) já valida `relative_to(photo_root)` e aborta se fora. |
| Credenciais hardcoded (`deps.py:15-21`) | ✅ **Verdadeiro** | `network_id "TA25413"` e hash bcrypt de "98Edinho" estão no git. |
| `busy_timeout=5000` baixo p/ concorrência | ✅ **Verdadeiro** | `session.py:32`; agente + scheduler + UI competem no mesmo SQLite. |
| Staging temp acumula → disco cheio | ⚠️ **Decisão deliberada** | `local_agent.py:808-810`: cleanup desativado **de propósito**. Não reverter. |

---

## 3. Achados por eixo (severidade × esforço)

Severidade: 🔴 alta · 🟡 média · 🟢 baixa. Esforço: P (pequeno) · M (médio) · G (grande).

### 3.1 Confiabilidade do RPA
| # | Achado | Sev | Esf | Local |
|---|---|---|---|---|
| R1 | Timeouts de lote hardcoded, sem override por workspace/payload | 🟡 | M | `playground_upload.py:48,54` |
| R2 | Retry de checkpoint com `sleep(1)` fixo (sem backoff) | 🟡 | P | `local_agent.py:291` |
| R3 | Falha de tarefa inteira se arquivo some antes do SHA256 | 🟡 | P | `local_agent.py` (loop SHA256) |
| R4 | Seletores por texto literal (`UPLOAD_FILES_TEXTS`) frágeis a mudança de UI | 🟡 | M | `selectors.py` |
| R5 | Confirmação de upload recém-estabilizada (5 commits) sem testes de regressão | 🟡 | M | `playground_upload.py` |

### 3.2 Robustez operacional
| # | Achado | Sev | Esf | Local |
|---|---|---|---|---|
| O1 | `busy_timeout=5000` baixo p/ concorrência | 🟡 | P | `session.py:32` |
| O2 | Export de logs sem paginação/limite → OOM | 🟡 | P | `routers/logs.py` |
| O3 | Staging acumula em disco (retenção opt-in, sem reverter no-delete) | 🟢 | M | `local_agent.py:808-810` |
| O4 | CORS hardcoded (quebra se portas/hosts mudarem) | 🟢 | P | `main.py` |

### 3.3 Qualidade & Testes
| # | Achado | Sev | Esf | Local |
|---|---|---|---|---|
| Q1 | Cobertura ~0% (1 teste p/ ~68 arquivos) | 🔴 | G | `backend/tests/` |
| Q2 | `parse_payload`/`parse_json_object` duplicado em 3 routers | 🟡 | P | `agents.py`, `executions.py`, `reports.py` |
| Q3 | Sem `requirements-dev.txt` / config pytest / CI | 🟡 | M | raiz/backend |
| Q4 | Fallback `ast.literal_eval` inútil/confuso | 🟢 | P | `agents.py:94` |

### 3.4 Segurança & Dados (calibrado ao modelo offline single-user)
| # | Achado | Sev | Esf | Local |
|---|---|---|---|---|
| S1 | Hash de senha do admin local no git | 🟡 | P | `deps.py:15-21` |
| S2 | Webhook Teams sem validação de scheme/host (SSRF p/ IP interno) | 🟡 | P | `routers/teams.py` |
| S3 | Rotas retornam dicts ad-hoc sem `response_model` | 🟢 | M | `users.py`, `agents.py`, … |
| S4 | `stored_photo_path` aceita path absoluto na escrita | 🟢 | P | `auth.py:56-59` |

---

## 4. Roadmap priorizado

Implementação em **fases**, cada uma com sua validação. Testes (Fase 3) **antes** de mexer em seletores
RPA (Fase 2 final).

- **Fase 0 — Higiene imediata**: commitar Teams (untracked); remover `*.formatted.js` e ignorá-lo;
  documentar Teams (CLAUDE.md, BACKEND_START.md, env vars `MS_GRAPH_*`).
- **Fase 1 — Robustez operacional**: `busy_timeout` configurável (O1); paginação no export de logs (O2);
  CLI opt-in `purge_staging` com `STAGING_RETENTION_DAYS` default 0 (O3).
- **Fase 2 — Confiabilidade do RPA**: timeouts configuráveis (R1); backoff exponencial (R2);
  pré-checagem de existência antes do SHA256 (R3); seletores resilientes via `aria-label`/`role` (R4) —
  **só após Fase 3**.
- **Fase 3 — Qualidade & Testes**: infra pytest (Q3); alvos prioritários (ContextVar dual-env, `deps.py`,
  `parse_payload`, `schedule_runner` next_run_at) (Q1); dedup util e remoção do `ast.literal_eval` (Q2/Q4).
- **Fase 4 — Segurança & Dados**: credenciais via env var (S1); validação webhook Teams (S2);
  `response_model` Pydantic (S3); reforço de `stored_photo_path` na escrita (S4).

---

## 5. Itens explicitamente NÃO recomendados

- **Não reverter** o cleanup desativado de staging (`local_agent.py:808-810`) — decisão deliberada do
  usuário. A melhoria é uma retenção *opt-in*, não a remoção automática padrão.
- **Não "corrigir"** `AUTH_DISABLED=true` — é o padrão intencional do release offline single-user.
- **Não mexer** na lógica de confirmação de upload em lote sem antes ter testes de regressão — foi
  estabilizada nos últimos 5 commits e é o núcleo de valor do produto.

---

## 6. Nota de release

Este relatório (`RELATORIO_MELHORIAS.md`), `backend/tests/`, `requirements-dev.txt` e quaisquer
`*.formatted.js` **não** devem entrar no pacote offline (ver `RELEASE_POLICY.md`). Após mudanças, validar
com `scripts/build_release_empty_db.py` e inspecionar `RELEASE_VALIDATION.txt`.
