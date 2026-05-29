@echo off
setlocal
cd /d "%~dp0"

set "ROOT=%~dp0"
set "ROOT_DIR=%ROOT:~0,-1%"
set "DASHBOARD_URL=http://127.0.0.1:5173"
set "LOG_DIR=%ROOT%backend\data\logs"
set "HIDDEN_STARTER=%ROOT%scripts\start_hidden_service.ps1"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo ============================================================
echo Automation HUB v1.0 - Inicializacao
echo ============================================================
echo Backend, dashboard e agente local serao iniciados em modo oculto.
echo Logs em: %LOG_DIR%
echo.

if not exist "%ROOT%start_backend.bat" (
  echo ERRO: start_backend.bat nao encontrado.
  pause
  exit /b 1
)

if not exist "%ROOT%start_dashboard.bat" (
  echo ERRO: start_dashboard.bat nao encontrado.
  pause
  exit /b 1
)

if not exist "%ROOT%start_agent.bat" (
  echo ERRO: start_agent.bat nao encontrado.
  pause
  exit /b 1
)

if not exist "%HIDDEN_STARTER%" (
  echo ERRO: Helper de inicializacao oculta nao encontrado: %HIDDEN_STARTER%
  pause
  exit /b 1
)

call :ensure_port_service 8000 "backend" "%ROOT%start_backend.bat" "%LOG_DIR%\backend_runtime.out.log" "%LOG_DIR%\backend_runtime.err.log"
call :wait_port 8000 45
if errorlevel 1 (
  echo AVISO: backend nao respondeu na porta 8000 dentro do tempo esperado.
  echo Consulte: %LOG_DIR%\backend_runtime.err.log
) else (
  echo Backend pronto em http://127.0.0.1:8000
)

call :ensure_port_service 5173 "dashboard" "%ROOT%start_dashboard.bat" "%LOG_DIR%\dashboard_runtime.out.log" "%LOG_DIR%\dashboard_runtime.err.log"
call :wait_port 5173 45
if errorlevel 1 (
  echo AVISO: dashboard nao respondeu na porta 5173 dentro do tempo esperado.
  echo Consulte: %LOG_DIR%\dashboard_runtime.err.log
) else (
  echo Dashboard pronto em %DASHBOARD_URL%
)

call :ensure_agent

call :port_listening 5173
if not errorlevel 1 (
  if /I not "%START_ALL_OPEN_BROWSER%"=="0" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process '%DASHBOARD_URL%'" >nul 2>nul
    echo Dashboard aberto no navegador padrao.
  )
)

echo.
echo Inicializacao solicitada. Esta janela pode ser fechada.
exit /b 0

:ensure_port_service
set "SERVICE_PORT=%~1"
set "SERVICE_NAME=%~2"
set "SERVICE_SCRIPT=%~3"
set "SERVICE_OUT=%~4"
set "SERVICE_ERR=%~5"
call :port_listening %SERVICE_PORT%
if errorlevel 1 (
  echo Iniciando %SERVICE_NAME% em modo oculto...
  call :launch_hidden "%SERVICE_SCRIPT%" "%SERVICE_OUT%" "%SERVICE_ERR%"
) else (
  echo %SERVICE_NAME% ja parece estar ativo na porta %SERVICE_PORT%.
)
exit /b 0

:ensure_agent
call :agent_running
if errorlevel 1 (
  echo Iniciando agente local em modo oculto...
  call :launch_hidden "%ROOT%start_agent.bat" "%LOG_DIR%\local_agent_runtime.out.log" "%LOG_DIR%\local_agent_runtime.err.log"
) else (
  echo Agente local ja parece estar ativo.
)
exit /b 0

:launch_hidden
powershell -NoProfile -ExecutionPolicy Bypass -File "%HIDDEN_STARTER%" -Script "%~1" -OutLog "%~2" -ErrLog "%~3" -WorkingDirectory "%ROOT_DIR%"
exit /b %errorlevel%

:port_listening
powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Get-NetTCPConnection -LocalPort %~1 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>nul
exit /b %errorlevel%

:wait_port
set "WAIT_PORT=%~1"
set "WAIT_SECONDS=%~2"
set /a WAIT_ELAPSED=0
:wait_port_loop
call :port_listening %WAIT_PORT%
if not errorlevel 1 exit /b 0
if %WAIT_ELAPSED% GEQ %WAIT_SECONDS% exit /b 1
timeout /t 1 /nobreak >nul
set /a WAIT_ELAPSED+=1
goto wait_port_loop

:agent_running
powershell -NoProfile -ExecutionPolicy Bypass -Command "$found = Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and ($_.CommandLine -like '*python -m app.cli.local_agent*' -or $_.CommandLine -like '*start_agent.bat*') }; if ($found) { exit 0 } else { exit 1 }" >nul 2>nul
exit /b %errorlevel%
