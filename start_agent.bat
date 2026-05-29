@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo Automation HUB v1.0 - Local Agent
echo ============================================================

if not exist "backend" (
  echo ERRO: Pasta backend nao encontrada.
  if /I not "%AUTOMATION_HUB_NO_PAUSE%"=="1" pause
  exit /b 1
)

cd backend

if not exist ".venv\Scripts\activate.bat" (
  echo ERRO: Ambiente virtual nao encontrado.
  echo Execute primeiro: setup_backend.bat
  if /I not "%AUTOMATION_HUB_NO_PAUSE%"=="1" pause
  exit /b 1
)

call ".venv\Scripts\activate.bat"

if exist "%~dp0backend\ms-playwright\chromium-1217" (
  set "PLAYWRIGHT_BROWSERS_PATH=%~dp0backend\ms-playwright"
  echo Chromium offline: %PLAYWRIGHT_BROWSERS_PATH%
)

echo Iniciando agente local.
echo Para parar, pressione CTRL+C.
echo.
set "PYTHONUNBUFFERED=1"
python -m app.cli.local_agent
