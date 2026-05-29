# Politica de Release - Automation HUB

Este computador e o ambiente de desenvolvimento e teste local do projeto. A release final deve ser um pacote runtime limpo para iniciar no notebook da empresa com banco vazio.

## Regra principal

- A release nao deve carregar banco de teste, historico, logs, screenshots, sessoes de navegador, arquivos temporarios, testes, seeds ou mocks de desenvolvimento.
- O frontend entregue na release e o `dist` ja buildado; a pasta `src` nao entra no ZIP estrito.
- O banco deve iniciar vazio. Seeds de desenvolvimento ficam fora do pacote e nao rodam por padrao.
- A release atual deve iniciar sem tela de login. `AUTH_DISABLED=true` fica como padrao e o backend usa/cria um usuario local administrador automaticamente.
- A release offline inclui o Chromium do Playwright em `backend\ms-playwright` para nao depender de download no notebook corporativo.
- O pacote final deve ser um ZIP criado a partir de uma pasta limpa em `releases`.

## Conteudo permitido

- `dist`
- `public`, quando necessario para assets estaticos
- `backend\app`
- `backend\alembic`
- `backend\requirements.txt`
- `backend\.env.example`
- `backend\alembic.ini`
- `backend\ms-playwright`, contendo somente o runtime Chromium offline necessario
- `backend\wheels`, quando existir
- scripts `.bat` de setup/inicializacao
- `scripts\build_release_empty_db.py`
- documentacao de operacao e release

## Conteudo proibido

- `src`
- `backend\tests`
- `backend\requirements-dev.txt`
- `backend\app\cli\seed_dev_data.py`
- `backend\app\cli\smoke_schedule_runner.py`
- `src\constants\mockData.js`
- `.env`
- `backend\.env`
- `backend\data\*.db`
- `backend\data\*.sqlite`
- `backend\data\*.sqlite3`
- `backend\data\temp`
- `backend\data\logs`
- `backend\data\screenshots`
- `backend\data\browser_session`
- `backend\data\reports`
- `.venv`
- `node_modules`
- `.idea`
- caches `__pycache__`, `.pytest_cache`
- arquivos `.pyc`, `.zip`, `.rar`, `.7z`

## Geracao

```powershell
.\build_release_empty_db.bat
```

O script cria uma pasta limpa e um ZIP com nome `Automation_HUB_company_notebook_chromium_no_login_empty_db_YYYYMMDD_HHMMSS.zip`.

## Inicializacao no notebook

1. Execute `setup_backend.bat` uma vez para criar `.venv`, instalar `backend\requirements.txt` e aplicar migrations.
2. Nao e necessario criar usuario admin inicial. O dashboard inicia sem login; para reativar autenticacao no futuro, defina `AUTH_DISABLED=false` no `backend\.env` e execute `python -m app.cli.create_admin_user`.
3. Execute `start_all.bat` para abrir backend e dashboard.
4. O dashboard usa `dist` via Python em `http://127.0.0.1:5173`; Node/npm nao sao necessarios para iniciar a release.
5. O Chromium do Playwright ja vem incluido na release offline. `INSTALL_PLAYWRIGHT_BROWSER=1` e apenas fallback para maquinas sem bloqueio de download.
6. Seed de desenvolvimento so roda se `RUN_DEV_SEED=1` estiver definido e o arquivo de seed existir, o que nao ocorre na release estrita.

## Validacao esperada

O arquivo `RELEASE_VALIDATION.txt` dentro da pasta limpa registra:

- se `dist` existe;
- se `src` esta ausente;
- se `backend\app` existe;
- se `backend\tests`, `requirements-dev.txt` e seeds estao ausentes;
- se o pacote esta sem banco SQLite;
- se `.env`, `.venv`, `node_modules`, logs e dados runtime foram excluidos;
- se `backend\ms-playwright\chromium-1217` esta presente;
- quantidade de entradas e tamanho do ZIP.
