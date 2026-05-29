@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo Automation HUB - Build Release Empty DB
echo ============================================================

where python >nul 2>nul
if errorlevel 1 (
  echo ERRO: Python nao encontrado no PATH.
  pause
  exit /b 1
)

python scripts\build_release_empty_db.py
if errorlevel 1 (
  echo ERRO: Release contem arquivos proibidos ou falhou.
  pause
  exit /b 1
)

echo.
echo Release gerada com sucesso em releases.
pause
