# Estudo de Viabilidade — Multiusuário com Banco Central e Automações Locais

> Documento de análise (não é implementação). Avalia disponibilizar o Automation HUB para
> **vários usuários em vários computadores**, com **banco de dados centralizado**, **cada automação
> rodando localmente** na máquina do usuário, e **código no GitHub** para que manutenções sejam
> refletidas a todos.

## 1. Cenário desejado

- Acesso a partir de **outros computadores** (não só a máquina de hoje).
- **Banco de dados centralizado** (uma fonte única de verdade compartilhada pela equipe).
- **Cada automação roda localmente** — o RPA/Playwright e a varredura de pasta acontecem na máquina
  do usuário (a pasta monitorada é local), não no servidor.
- **Manutenção via GitHub** — um repositório central; ao publicar uma correção, todas as máquinas
  passam a usá-la.

## 2. Veredito

**Viável, com esforço médio.** A arquitetura atual já foi desenhada com a maior parte dos alicerces:
o backend já é um **serviço central** com fila de tarefas, os agentes já são **clientes "magros"** que
fazem *polling* de uma API **configurável**, o banco é **plugável** (SQLite↔PostgreSQL sem mudar código),
o **login JWT por usuário já existe** (apenas desligado) e as **sessões de navegador já são por usuário**.

As lacunas reais são poucas e bem localizadas. A mais importante é o **claim atômico de tarefas** (hoje
seguro só porque o SQLite tem um único escritor). As demais são configuração/processo (Postgres, auth,
rede, deploy) e uma feature de **roteamento de tarefa para a máquina certa** (pinning).

## 3. O que já está pronto (alicerces existentes)

| Alicerce | Onde | Observação |
|---|---|---|
| Backend central com fila de tarefas + scheduler | `backend/app` | Já é o ponto único de coordenação. |
| Banco plugável | [`db/session.py`](backend/app/db/session.py), [`config.py`](backend/app/core/config.py#L136) | `database_url_for_environment` → basta `OPERATIONAL_DATABASE_URL=postgresql://…`. `session.py` já trata Postgres (`pool_pre_ping`); pragmas WAL são só para SQLite. |
| Agente "magro" e configurável | [`cli/local_agent.py:34`](backend/app/cli/local_agent.py#L34) | `AUTOMATION_HUB_API_URL` (default `127.0.0.1:8000`) aponta para qualquer backend; autentica com `X-Agent-Token`/`AGENT_SHARED_TOKEN`. |
| Heartbeat com identidade da máquina | [`local_agent.py:1203`](backend/app/cli/local_agent.py#L1203) | Já envia `machine_name` (`COMPUTERNAME`). |
| Registro de agentes/máquinas | [`models/agent.py:34`](backend/app/models/agent.py#L34) | `Agent(machine_name, status, last_heartbeat_at)`. |
| Campo de atribuição de tarefa | [`models/agent.py:15`](backend/app/models/agent.py#L15) | `AgentTask.assigned_agent_id` **já existe** (hoje só gravado, não usado para rotear). |
| Login JWT por usuário | [`routers/deps.py:58`](backend/app/routers/deps.py#L58) | `user_from_token`, `/api/auth/login`, papéis `admin/user/viewer`. Só desligado por `AUTH_DISABLED=true`. |
| Sessão de navegador por usuário | `services/playwright/` | `BROWSER_SESSION_PATH/user_{id}` — cada usuário faz seu **SSO no Chromium local**. |
| Isolamento por ambiente | [`config.py`](backend/app/core/config.py) | `operational`/`developer` já separa produção de testes (header `X-App-Environment`). |

## 4. Lacunas e trabalho necessário

### 4.1 Claim atômico de tarefas — **CRÍTICO** (concorrência)
[`routers/agents.py:281`](backend/app/routers/agents.py#L281) faz `SELECT status=pending → marca running →
commit`, **sem lock de linha**. Com SQLite (um único escritor + `busy_timeout`) é seguro. Com **PostgreSQL
e ≥2 agentes** fazendo *polling* simultâneo, dois agentes podem ler as **mesmas** tarefas pendentes antes
do commit do outro → **execução duplicada**.
- **Correção:** `SELECT … FOR UPDATE SKIP LOCKED` (no SQLAlchemy: `.with_for_update(skip_locked=True)`)
  na consulta de `pending`, com commit imediato do claim. PostgreSQL suporta `SKIP LOCKED` nativamente.
- **Esforço:** baixo. **Impacto:** alto (é bloqueador assim que houver mais de um agente).

### 4.2 Roteamento de tarefa → máquina (pinning) — **necessário** ao modelo "automação local"
Hoje o `poll` **não filtra por agente**: qualquer agente pega qualquer tarefa pendente. Mas a automação
tem `folder_path` **local** ([`models/automation.py:13`](backend/app/models/automation.py#L13)) — ela só
funciona na máquina que tem aquela pasta. Sem pinning, a tarefa pode ser reivindicada pela máquina errada.
- **O que falta:** vincular a automação a uma máquina (ex.: `Automation.assigned_agent_id`/`machine_name`,
  via migração) e **filtrar no poll** por `assigned_agent_id == agent_id` (ou tarefas sem dono). O campo
  `AgentTask.assigned_agent_id` já existe — basta **popular na criação** e **usar como filtro**.
- **Esforço:** médio (modelo + migração Alembic + ajuste do `poll` + seleção da máquina na UI).

### 4.3 Autenticação real — **necessário**
Habilitar `AUTH_DISABLED=false`, definir `SECRET_KEY` forte, criar usuários (existe
[`cli/create_admin_user.py`](backend/app/cli/create_admin_user.py)) e revisitar o `get_or_create_local_user`
(o admin local *hardcoded* é proposital para o release sem login — não some, mas deixa de ser o caminho
padrão). Definir papéis por usuário.
- **Esforço:** médio. **Risco:** baixo (o caminho JWT já está implementado e testado).

### 4.4 PostgreSQL centralizado — **necessário**
Provisionar um PostgreSQL na rede; setar `OPERATIONAL_DATABASE_URL=postgresql://…`; rodar
`alembic upgrade head` (via `AUTOMATION_HUB_MIGRATION_ENVIRONMENT`). Tipos usados (`Integer/String/Text/
Boolean/DateTime`) são portáveis. Migração do histórico atual (SQLite→Postgres) é opcional, via script ETL.
- **Esforço:** baixo-médio.

### 4.5 Exposição de rede — **necessário**
Backend escutando em `0.0.0.0:8000` na LAN/VPN corporativa; **CORS** liberando a origem do dashboard;
idealmente **HTTPS** via *reverse proxy* (Nginx/IIS), porque JWT e credenciais trafegam. Regras de firewall.
- **Esforço:** médio.

### 4.6 Deploy e manutenção via GitHub — **processo**
- **Backend central:** atualizado e reiniciado num único servidor (`restart_services.bat` / serviço),
  rodando migrações no deploy.
- **Agentes nas máquinas:** `git pull` (ou ZIP de release) + reinício do agente.
- **Versionar o protocolo agente↔backend** para manter compatibilidade durante janelas de atualização.
- **Esforço:** processo, não código (documentar o runbook).

### 4.7 Observabilidade multi-máquina — **recomendado**
Painel de **agentes online** (já há `last_heartbeat_at`), logs por máquina e por execução. Útil para
operar várias máquinas. **Esforço:** baixo-médio.

## 5. Topologia recomendada

```
                 ┌──────────────────────────────────────────────┐
                 │           SERVIDOR CENTRAL (LAN/VPN)          │
                 │  FastAPI (8000)  +  PostgreSQL  +  Dashboard  │
                 │  Auth JWT ON · HTTPS via reverse proxy        │
                 └───────────────▲───────────────▲──────────────┘
                                 │  polling / heartbeat (X-Agent-Token)
        ┌────────────────────────┼───────────────┼───────────────────────┐
        │                        │               │                       │
 ┌──────┴───────┐        ┌───────┴──────┐  ┌──────┴───────┐       ┌───────┴──────┐
 │  Máquina A   │        │  Máquina B   │  │  Máquina C   │  ...  │  Máquina N   │
 │ Agente local │        │ Agente local │  │ Agente local │       │ Agente local │
 │ Chromium SSO │        │ Chromium SSO │  │ Chromium SSO │       │ Chromium SSO │
 │ pastas locais│        │ pastas locais│  │ pastas locais│       │ pastas locais│
 └──────────────┘        └──────────────┘  └──────────────┘       └──────────────┘
```

- **Servidor central:** estado, fila, dashboard, agendador — fonte única de verdade.
- **Máquinas-usuário:** agente + Chromium offline; `AUTOMATION_HUB_API_URL` → servidor; SSO do Playground
  feito **localmente** em cada máquina; automações com pasta local **pinadas** àquela máquina.
- **GitHub:** fonte única; manutenção do backend central (deploy/restart) e atualização dos agentes (pull).

## 6. Principais riscos

1. **Execução duplicada** sem o claim atômico (§4.1) — bloqueador real a partir de 2 agentes.
2. **Tarefa na máquina errada** sem pinning (§4.2) — pasta local + frota de máquinas.
3. **Credenciais/JWT sem TLS** na rede (§4.5).
4. **Migração de histórico** SQLite→PostgreSQL (script ETL, se quiser preservar dados atuais).
5. **Desalinhamento de versão** agente↔backend durante atualizações (mitigar versionando o protocolo).

## 7. Roadmap incremental sugerido

1. **Fundação:** PostgreSQL central + `AUTH_DISABLED=false` + usuários/papéis.
2. **Concorrência:** claim atômico (`with_for_update(skip_locked=True)`) — destrava múltiplos agentes.
3. **Pinning:** vincular automação→máquina (campo + migração + filtro no `poll` + UI).
4. **Rede/Deploy:** bind público + CORS + TLS + runbook de atualização via GitHub.
5. **Operação:** painel de agentes online e observabilidade por máquina.

## 8. Como validar (provar a viabilidade na prática)

1. Subir um PostgreSQL, apontar `OPERATIONAL_DATABASE_URL`, rodar `alembic upgrade head`.
2. Rodar **dois agentes** em duas máquinas apontando para o mesmo backend; enfileirar tarefas e medir
   duplicação **antes** e **depois** de aplicar `SKIP LOCKED` (deve cair a zero).
3. Ligar a auth (`AUTH_DISABLED=false`), validar `/api/auth/login`, papéis e acesso por usuário.
4. Configurar uma automação pinada à Máquina A e confirmar que a Máquina B **não** a reivindica.
