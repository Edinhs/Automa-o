@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo Automation HUB v1.0 - Dashboard
echo ============================================================

if exist "dist\index.html" if /I not "%DASHBOARD_DEV%"=="1" (
  where python >nul 2>nul
  if errorlevel 1 (
    echo ERRO: Python nao encontrado no PATH para servir o dashboard buildado.
    if /I not "%AUTOMATION_HUB_NO_PAUSE%"=="1" pause
    exit /b 1
  )
  echo Dashboard buildado em http://127.0.0.1:5173
  echo Para parar, pressione CTRL+C.
  echo.
  cd dist
  python -m http.server 5173 --bind 127.0.0.1
  exit /b %errorlevel%
)

if not exist "package.json" (
  echo ERRO: package.json nao encontrado na raiz do projeto.
  if /I not "%AUTOMATION_HUB_NO_PAUSE%"=="1" pause
  exit /b 1
)

where npm >nul 2>nul
if errorlevel 1 (
  echo ERRO: npm nao encontrado no PATH.
  echo Instale/ative o Node.js no computador pessoal.
  if /I not "%AUTOMATION_HUB_NO_PAUSE%"=="1" pause
  exit /b 1
)

if not exist "node_modules" (
  echo ERRO: node_modules nao encontrado.
  echo Execute npm install na raiz do projeto antes de iniciar o dashboard.
  if /I not "%AUTOMATION_HUB_NO_PAUSE%"=="1" pause
  exit /b 1
)

echo Dashboard em http://127.0.0.1:5173
echo Se aparecer erro de vite nao encontrado, execute npm install na raiz do projeto.
echo Para parar, pressione CTRL+C.
echo.
npm run dev -- --host 127.0.0.1 --port 5173
