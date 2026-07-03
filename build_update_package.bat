@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo Automation HUB - Build Pacote de Atualizacao (overlay)
echo ============================================================
echo Este pacote NAO inclui o banco de dados; aplicar preserva os dados.
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo ERRO: Python nao encontrado no PATH.
  if /I not "%AUTOMATION_HUB_NO_PAUSE%"=="1" pause
  exit /b 1
)

python scripts\build_update_package.py
if errorlevel 1 (
  echo ERRO: Pacote contem arquivos proibidos, incluiu banco de dados ou falhou.
  if /I not "%AUTOMATION_HUB_NO_PAUSE%"=="1" pause
  exit /b 1
)

echo.
echo Pacote de atualizacao gerado com sucesso em releases.
if /I not "%AUTOMATION_HUB_NO_PAUSE%"=="1" pause
