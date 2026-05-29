@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo Automation HUB v1.0 - Setup Backend
echo ============================================================

if not exist "backend" (
  echo ERRO: Pasta backend nao encontrada.
  pause
  exit /b 1
)

cd backend

where python >nul 2>nul
if errorlevel 1 (
  echo ERRO: Python nao encontrado no PATH.
  pause
  exit /b 1
)

if not exist ".venv" (
  echo Criando ambiente virtual...
  python -m venv .venv
  if errorlevel 1 (
    echo ERRO: Falha ao criar ambiente virtual.
    pause
    exit /b 1
  )
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 (
  echo ERRO: Falha ao ativar .venv.
  pause
  exit /b 1
)

if exist "%~dp0backend\ms-playwright\chromium-1217" (
  set "PLAYWRIGHT_BROWSERS_PATH=%~dp0backend\ms-playwright"
  echo Chromium offline encontrado em: %PLAYWRIGHT_BROWSERS_PATH%
)

echo Atualizando pip...
python -m pip install --upgrade pip
if errorlevel 1 (
  echo ERRO: Falha ao atualizar pip.
  pause
  exit /b 1
)

echo Instalando dependencias...
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo ERRO: Falha ao instalar requirements.txt.
  pause
  exit /b 1
)

if "%INSTALL_PLAYWRIGHT_BROWSER%"=="1" (
  if defined PLAYWRIGHT_BROWSERS_PATH (
    echo Chromium offline ja esta incluido no pacote. Download ignorado.
  ) else (
    echo Instalando Chromium do Playwright...
    python -m playwright install chromium
    if errorlevel 1 (
      echo ERRO: Falha ao instalar Chromium do Playwright.
      echo Execute manualmente: cd backend ^&^& .venv\Scripts\activate ^&^& python -m playwright install chromium
      pause
      exit /b 1
    )
  )
) else (
  if defined PLAYWRIGHT_BROWSERS_PATH (
    echo Chromium do Playwright sera usado a partir do cache offline incluido.
  ) else (
    echo Chromium do Playwright nao sera instalado agora.
    echo Para instalar depois, execute: set INSTALL_PLAYWRIGHT_BROWSER=1 ^& setup_backend.bat
  )
)

echo Aplicando migrations do ambiente Operacional...
set "AUTOMATION_HUB_MIGRATION_ENVIRONMENT=operational"
python -m alembic upgrade head
if errorlevel 1 (
  echo ERRO: Falha ao aplicar migrations do ambiente Operacional.
  pause
  exit /b 1
)

echo Aplicando migrations do ambiente Desenvolvedor...
set "AUTOMATION_HUB_MIGRATION_ENVIRONMENT=developer"
python -m alembic upgrade head
if errorlevel 1 (
  echo ERRO: Falha ao aplicar migrations do ambiente Desenvolvedor.
  pause
  exit /b 1
)
set "AUTOMATION_HUB_MIGRATION_ENVIRONMENT="

if /I "%RUN_DEV_SEED%"=="1" (
  if not exist "app\cli\seed_dev_data.py" (
    echo ERRO: seed_dev_data.py nao esta disponivel neste pacote.
    pause
    exit /b 1
  )
  echo Executando seed de desenvolvimento...
  python -m app.cli.seed_dev_data
  if errorlevel 1 (
    echo ERRO: Falha ao executar seed.
    pause
    exit /b 1
  )
) else (
  echo Seed de desenvolvimento desativado. Banco inicia vazio.
  echo Login do dashboard desativado por padrao. Admin inicial nao e necessario.
  if /I "%CREATE_INITIAL_ADMIN%"=="1" (
    echo Criando admin inicial opcional...
    python -m app.cli.create_admin_user
    if errorlevel 1 (
      echo ERRO: Falha ao criar admin inicial.
      pause
      exit /b 1
    )
  ) else (
    echo Para reativar login futuramente, defina AUTH_DISABLED=false no backend\.env e execute:
    echo cd backend ^&^& .venv\Scripts\activate ^&^& python -m app.cli.create_admin_user
  )
)

echo.
echo Setup backend concluido com sucesso.
pause
