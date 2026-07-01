@echo off
setlocal enabledelayedexpansion

REM Script de execucao facil para o Script de Atualizacao Automatica de Workspace - IPC

set PROJECT=%1
set MODE=%2
set WORKSPACE_ID=%3

if "%PROJECT%"=="" (
    echo Erro: Projeto e obrigatorio.
    goto :usage
)

if "%MODE%"=="" (
    echo Erro: Modo (CREATE ou UPDATE) e obrigatorio.
    goto :usage
)

if /i "%MODE%"=="UPDATE" (
    if "%WORKSPACE_ID%"=="" (
        echo Erro: ID do Workspace e obrigatorio no modo UPDATE.
        goto :usage
    )
)

REM Define caminhos
set REPO_ROOT=%~dp0
set VENV_PATH=%REPO_ROOT%backend\.venv
set SCRIPT_PATH=%REPO_ROOT%custom_automations\ipc_workspace_updater\run_updater.py

REM Verifica o ambiente virtual (venv)
if not exist "%VENV_PATH%\Scripts\python.exe" (
    echo Erro: Ambiente virtual do backend nao encontrado em %VENV_PATH%.
    echo Execute primeiro o setup_backend.bat para preparar o ambiente.
    exit /b 1
)

REM Verifica se as dependencias adicionais estao instaladas, caso contrario instala
echo [INFO] Verificando dependencias da automacao personalizada...
"%VENV_PATH%\Scripts\python.exe" -c "import docx, yaml" 2>nul
if errorlevel 1 (
    echo [INFO] Instalando dependencias requeridas (python-docx, pyyaml)...
    "%VENV_PATH%\Scripts\python.exe" -m pip install -r "%REPO_ROOT%custom_automations\ipc_workspace_updater\requirements.txt"
)

REM Executa a automacao
echo [INFO] Executando atualizador de workspace para o projeto %PROJECT% (%MODE%)...
if /i "%MODE%"=="CREATE" (
    "%VENV_PATH%\Scripts\python.exe" "%SCRIPT_PATH%" --project "%PROJECT%" --mode "%MODE%"
) else (
    "%VENV_PATH%\Scripts\python.exe" "%SCRIPT_PATH%" --project "%PROJECT%" --mode "%MODE%" --workspace-id "%WORKSPACE_ID%"
)

exit /b %errorlevel%

:usage
echo.
echo Uso: %~nx0 ^<PROJETO^> ^<MODO^> [WORKSPACE_ID]
echo.
echo Parametros:
echo   PROJETO       Nome do projeto configurado (ex: J3U)
echo   MODO          CREATE (novo workspace) ou UPDATE (workspace existente)
echo   WORKSPACE_ID  ID do workspace local (obrigatorio se MODO for UPDATE)
echo.
echo Exemplos:
echo   %~nx0 J3U CREATE
echo   %~nx0 J3U UPDATE 1
exit /b 1
