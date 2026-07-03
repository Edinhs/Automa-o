@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo Automation HUB v1.0 - Backend API
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

echo Backend em http://127.0.0.1:8000
echo Para parar, pressione CTRL+C.
echo.
if "%BACKEND_RELOAD%"=="1" (
  python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
) else (
  python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
)
