# Deploy do Pacote de Atualizacao - Automation HUB

**Pacote:** `releases\hub_update_COMPLETO_20260721_131649.zip` (~0,81 MB, overlay incremental)
**Data de geracao:** 2026-07-21
**Tipo:** atualizacao por sobreposicao (overlay) - **PRESERVA banco de dados, runtime, .venv e o Chromium offline**.

Este pacote NAO contem banco (`*.db`), `backend\data`, `.venv`, `node_modules` nem `backend\ms-playwright`. Ao extrair por cima da instalacao, ele sobrescreve apenas: `backend\app`, `backend\alembic`, `dist`, `public`, `scripts` da raiz, os `.bat` de operacao e a documentacao. Seus dados reais e o Chromium embarcado permanecem intactos.

**Sem migracao de banco nesta versao** (nenhuma alteracao em `backend\alembic`; head continua `0013` / `a9c2e4f6b731`).

---

## Correcoes e novidades entregues neste pacote

### 1) Anexo real no envio de PNG/arquivo para o Teams (fix de QA)

O envio automatico do card-imagem/arquivo para o Teams (`services/playwright/teams_delivery.py`)
dependia de um `input[type="file"]` que **nem sempre existe no DOM** do Teams Web antes de o usuario
interagir com o menu de anexo. Quando o elemento nao era encontrado, o codigo antigo **enviava so o
texto da mensagem e seguia em frente silenciosamente** (log de aviso, sem falhar a tarefa) —
mascarando o problema: o arquivo simplesmente nao chegava no Teams.

Calibrado ao vivo em 20/07: o fluxo real do Teams Web e clicar no botao **"Anexar arquivos"**
(`data-tid="sendMessageCommands-FilePicker"`), abrir o menu e escolher **"Carregar deste
dispositivo"**, o que dispara o dialogo nativo do Windows — interceptado via
`page.expect_file_chooser()`. A nova funcao `attach_files_via_picker(...)`:

- Reproduz esse fluxo completo (botao → menu → `expect_file_chooser` → `set_files(...)`).
- **Confirma que o anexo apareceu no preview da composicao** antes de considerar sucesso (evita
  "sucesso" falso quando o Teams ignora o anexo silenciosamente).
- **Levanta `TeamsDeliveryError`** se o botao/menu nao forem encontrados ou o preview nao aparecer —
  a tarefa passa a **falhar de verdade** nesse cenario, em vez de mandar so o texto e reportar sucesso.

> Consistente com a regra do projeto de nao mascarar falha de RPA para parecer sucesso.

Arquivo alterado: `backend/app/services/playwright/teams_delivery.py`.

### 2) Card semanal do Teams (imagem) maior e mais legivel

O PNG gerado para o card de adocao (`services/report_image.py`) foi ampliado para melhorar a leitura
no Teams (zoom/DPI de celular e desktop):

- Largura do card: `1496px` → **`2400px`** (viewport `2500x1900`, `DEVICE_SCALE=2`).
- Fontes, paddings, gaps e icones de todos os blocos (manchete, horas economizadas, adocao, saude,
  rodape) aumentados proporcionalmente (ex.: titulo `30px`→`46px`, numero de horas `46px`→`70px`,
  chip de geracao, grafico SVG com fonte de eixo `11px`→`16px`).
- O `.card` nao tem altura fixa (o screenshot usa `elementHandle.screenshot()`, que captura o tamanho
  real do conteudo) — aumentar fonte/padding/gap/largura ja resulta numa imagem maior
  automaticamente, sem necessidade de recalcular a altura manualmente.
- **Sem mudanca de dados/logica** — os mesmos campos (horas semana/acumulado, adocao, saude) sao
  renderizados, so em escala maior. Nenhum contrato de API alterado.

Arquivo alterado: `backend/app/services/report_image.py`.

### 3) Documentacao

- **Novo `ENVIO_AUTOMATICO_RELATORIO.md`** — guia consolidado, passo a passo, de como o envio
  automatico do relatorio funciona hoje: agendamento + entrega por pasta + Power Automate (Caminho A)
  e o PNG automatico direto pro Teams via Playwright (Caminho B), com secao de verificacao/diagnostico.

> Observacao (achado de auditoria, nao bloqueante): a revisao desta sessao encontrou referencias
> desatualizadas em `CLAUDE.md`/`BACKEND_START.md`/`ANTIGRAVITY.MD` (citam `backend/tests` + `pytest` +
> `requirements-dev.txt`, que nao existem no working copy — os testes reais vivem em
> `backend/scripts/test_*.py`) e o head de migracao desatualizado em `SPECS.md`/`Briefing.md` (`0012`
> em vez do real `0013`). Essas correcoes de documentacao **nao entraram neste pacote** (ficaram
> pendentes por um bloqueio de permissao de escrita na sessao anterior) — recomenda-se aplica-las na
> proxima sessao de manutencao de docs.

---

## Pre-requisitos

- Executar todos os passos na **pasta de instalacao de PRODUCAO** do dono (a que tem os dados reais e o Chromium offline em `backend\ms-playwright`).
- Ter o ZIP `hub_update_COMPLETO_20260721_131649.zip` copiado para essa maquina.

---

## Passo a passo

### a) Parar todos os servicos

Na pasta de producao, execute:

```
stop_all.bat
```

Isso encerra backend, dashboard e agente, e mata processos HUB soltos nas portas **8000/5173**.

### b) BACKUP do banco de producao (recomendado)

Nao ha migracao nesta versao, mas o backup e sempre uma boa pratica antes de sobrescrever arquivos. Em PowerShell, dentro da pasta de producao:

```powershell
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
New-Item -ItemType Directory -Force ".\backup_db_$stamp" | Out-Null
Copy-Item ".\backend\data\*.db" ".\backup_db_$stamp\" -Force
Get-ChildItem ".\backup_db_$stamp\"
```

### c) Extrair o ZIP por cima da instalacao

Extraia `hub_update_COMPLETO_20260721_131649.zip` **na raiz da pasta de instalacao**, mantendo a estrutura de pastas e **sobrescrevendo** quando perguntado:

```powershell
Expand-Archive -Path ".\hub_update_COMPLETO_20260721_131649.zip" -DestinationPath "." -Force
```

Isso sobrescreve `backend\app`, `backend\alembic`, `dist`, `public`, `scripts`, docs e os `.bat`. **Preserva** `backend\data` (banco), `.venv` e `backend\ms-playwright` (Chromium).

### d) Nenhuma migracao a aplicar

Esta versao nao adiciona colunas/tabelas novas. Nao e necessario rodar `alembic upgrade head` (mas rodar nao faz mal - ficara no mesmo head atual, `0013`).

### e) Subir os servicos (backend + dashboard + AGENTE)

```
start_all.bat
```

### f) Hard-refresh no dashboard

Nao ha mudanca de frontend/bundle nesta versao — hard-refresh nao e obrigatorio, mas nao faz mal.

### g) Verificacao pos-deploy

1. **Diagnostics / heartbeat:** abra `GET http://127.0.0.1:8000/api/diagnostics` e confirme `agent.status` OK com heartbeat fresco.
2. **Anexo no Teams (fix 1):** dispare um envio de PNG/arquivo para o Teams (card semanal com `MS_GRAPH`/pasta configurado, ou a feature de PNG automatico de `PNG_TEAMS_AUTO_DELIVERY.md`) e confirme que o arquivo realmente aparece anexado na mensagem — nao so o texto. Se o anexo falhar, a tarefa deve aparecer como **falha** (nao mais "sucesso" com so o texto enviado).
3. **Card-imagem maior (fix 2):** gere um relatorio com o card-imagem (Relatorio Simplificado) e confirme visualmente que o PNG esta maior/mais legivel, com os mesmos dados de sempre (horas, adocao, saude).

---

## Rollback (se necessario)

1. `stop_all.bat`.
2. Restaurar os `.db` a partir de `backup_db_<stamp>\` para `backend\data\` (se algo tiver sido alterado).
3. Restaurar a versao anterior do codigo/bundle (reaplicar o pacote de update anterior, `hub_update_COMPLETO_20260717_172619.zip`).
4. `start_all.bat`.

---

## Notas de integridade do pacote (validacao ja executada nesta geracao)

- `forbidden_entries = 0` (sem `.db`/`.sqlite`, logs, `__pycache__`, `.venv`, `browser_session`, `ms-playwright`/Chromium, `.bak`, `backend\tests`, `requirements-dev.txt`).
- `contains_database_file = False`, `entry_count = 114`, `removed_bak_backups = 0`.
- `has_stop_all = True`, `has_restart_services = True`, `has_dist_index = True`, `has_backend_app = True`.
- Gate `python -m compileall backend\app` -> exit 0.
- `backend\scripts\` (scripts de debug/exploracao de QA gerados durante a calibracao do anexo do Teams, ex.: `check_sharepoint_list*.py`, `confirm_teams_screenshot.py`, `inspect_teams_attach.py`) **nao entram no pacote** (excluidos por politica — testes/dumps de desenvolvimento).
