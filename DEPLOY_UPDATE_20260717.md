# Deploy do Pacote de Atualizacao - Automation HUB

**Pacote:** `releases\hub_update_COMPLETO_20260717_172619.zip` (~0,80 MB, overlay incremental)
**Data de geracao:** 2026-07-17
**Tipo:** atualizacao por sobreposicao (overlay) - **PRESERVA banco de dados, runtime, .venv e o Chromium offline**.

Este pacote NAO contem banco (`*.db`), `backend\data`, `.venv`, `node_modules` nem `backend\ms-playwright`. Ao extrair por cima da instalacao, ele sobrescreve apenas: `backend\app`, `backend\alembic`, `dist`, `public`, `scripts` da raiz, os `.bat` de operacao e a documentacao. Seus dados reais e o Chromium embarcado permanecem intactos.

**Sem migracao de banco nesta versao** (nenhuma alteracao em `backend\alembic`).

---

## Novidades entregues neste pacote

### 1) Entrega automatica de PNG avulso para o Teams (feature nova)

O HUB pode monitorar uma pasta e, ao detectar um PNG **novo** (por hash sha256,
nunca reenvia o mesmo arquivo), enviar automaticamente esse arquivo para um
chat/canal do Teams via Playwright. Nao depende de o relatorio ter sido gerado
pelo proprio HUB. Dois modos de deteccao, ambos configuraveis via `.env`:

- `schedule` - so verifica no dia/hora fixos (ex.: toda segunda as 09:00).
- `continuous` - monitoramento continuo, verifica a cada N segundos.

**Desligada por padrao** (`TEAMS_PNG_DELIVERY_ENABLED=false`). Ver
`PNG_TEAMS_AUTO_DELIVERY.md` para o guia completo de configuracao
(variaveis, exemplos, como ativar, como funciona o dedup e o estado).

Arquivos novos/alterados: `app/services/teams_png_watch.py` (novo),
`app/services/playwright/teams_delivery.py` (refatorado + `deliver_file_teams_playwright`),
`app/services/schedule_runner.py`, `app/cli/local_agent.py`, `app/routers/agents.py`,
`app/core/config.py`, `backend\.env.example`.

### 2) Correcoes de QA no upload do Playground (encontradas via agente Sicky)

- **Arquivos ocultos no upload:** quando o Playground esconde arquivos atras
  do link "Show more files (+N)", o HUB agora expande essa lista antes de
  conferir os nomes anexados - evitava timeout de upload em lotes de 4+
  arquivos. (`app/services/playwright/selectors.py`, `playground_upload.py`)
- **Botao final de upload demorando a habilitar:** o botao "Upload Files"
  pode ficar desabilitado por mais tempo que o esperado (validacao
  assincrona da UI). O HUB agora espera com paciencia estendida (~55s) sem
  recarregar a pagina nesse caso especifico, evitando que o recarregamento
  apague os arquivos ja anexados. A logica antiga de recuperacao (reload +
  escape) continua intacta para o caso de o botao realmente nao ser
  encontrado. (`app/services/playwright/playground_upload.py`)

> Ambas as correcoes sao **aditivas**: so estendem a paciencia/checagem em
> cenarios que antes falhavam; nenhuma validacao existente foi removida ou
> enfraquecida (regra do `CLAUDE.md` do projeto).

---

## Pre-requisitos

- Executar todos os passos na **pasta de instalacao de PRODUCAO** do dono (a que tem os dados reais e o Chromium offline em `backend\ms-playwright`).
- Ter o ZIP `hub_update_COMPLETO_20260717_172619.zip` copiado para essa maquina.

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

Extraia `hub_update_COMPLETO_20260717_172619.zip` **na raiz da pasta de instalacao**, mantendo a estrutura de pastas e **sobrescrevendo** quando perguntado:

```powershell
Expand-Archive -Path ".\hub_update_COMPLETO_20260717_172619.zip" -DestinationPath "." -Force
```

Isso sobrescreve `backend\app`, `backend\alembic`, `dist`, `public`, `scripts`, docs e os `.bat`. **Preserva** `backend\data` (banco), `.venv` e `backend\ms-playwright` (Chromium).

### d) Nenhuma migracao a aplicar

Esta versao nao adiciona colunas/tabelas novas. Nao e necessario rodar `alembic upgrade head` (mas rodar nao faz mal - ficara no mesmo head atual).

### e) (Opcional) Ativar a entrega automatica de PNG para o Teams

Se quiser usar a nova feature, edite `backend\.env` e preencha o bloco
`TEAMS_PNG_*` (ja adicionado, comentado, no final do arquivo). Veja
`PNG_TEAMS_AUTO_DELIVERY.md` para o passo a passo completo. Pode pular esta
etapa e ativar depois - a feature vem desligada por padrao e nao afeta nada
existente.

### f) Subir os servicos (backend + dashboard + AGENTE)

```
start_all.bat
```

### g) Hard-refresh no dashboard

No navegador do dashboard, force **Ctrl+F5** (hard-refresh) para garantir que o bundle novo seja carregado.

### h) Verificacao pos-deploy

1. **Diagnostics / heartbeat:** abra `GET http://127.0.0.1:8000/api/diagnostics` e confirme `agent.status` OK com heartbeat fresco.
2. **Upload no Playground:** dispare uma tarefa de upload com 4+ arquivos e confirme que ela completa sem travar (valida as duas correcoes de QA).
3. **PNG -> Teams (se ativado):** com `TEAMS_PNG_DELIVERY_ENABLED=true` e a pasta/chat configurados, deposite um PNG na pasta monitorada e confirme que uma tarefa `deliver_png_teams_playwright` e criada e entregue com sucesso; depositar o mesmo arquivo de novo NAO deve reenviar.

---

## Rollback (se necessario)

1. `stop_all.bat`.
2. Restaurar os `.db` a partir de `backup_db_<stamp>\` para `backend\data\` (se algo tiver sido alterado).
3. Restaurar a versao anterior do codigo/bundle (reaplicar o pacote de update anterior, `hub_update_COMPLETO_20260716_164243.zip`).
4. `start_all.bat`.

---

## Notas de integridade do pacote (validacao ja executada nesta geracao)

- `forbidden_entries = 0` (sem `.db`/`.sqlite`, logs, `__pycache__`, `.venv`, `browser_session`, `ms-playwright`/Chromium, `.bak`, `backend\tests`, `requirements-dev.txt`).
- `contains_database_file = False`, `entry_count = 114`.
- `has_stop_all = True`, `has_restart_services = True`, `has_dist_index = True`, `has_backend_app = True`.
- Contem todos os arquivos-chave da sessao (novo modulo `teams_png_watch.py`, `teams_delivery.py` refatorado, correcoes de `playground_upload.py`/`selectors.py`, doc `PNG_TEAMS_AUTO_DELIVERY.md`).
- Gate `python -m compileall backend\app` -> exit 0.
