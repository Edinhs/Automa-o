@echo off
setlocal
cd /d "%~dp0"
set "AUTOMATION_HUB_ROOT=%~dp0"

echo ============================================================
echo Automation HUB v1.0 - Reinicio de servicos
echo ============================================================
echo Encerrando somente servicos iniciados por este pacote.
echo.

if not exist "%AUTOMATION_HUB_ROOT%start_all.bat" (
    echo ERRO: start_all.bat nao encontrado.
    if /I not "%AUTOMATION_HUB_NO_PAUSE%"=="1" pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $root=[System.IO.Path]::GetFullPath($env:AUTOMATION_HUB_ROOT).TrimEnd('\'); $validateOnly=$env:AUTOMATION_HUB_RESTART_VALIDATE_ONLY -eq '1'; $all=@(Get-CimInstance Win32_Process); function Test-FromPackage([object]$process) { for ($level=0; $level -lt 6 -and $null -ne $process; $level++) { if ([string]$process.CommandLine -like ('*' + $root + '*')) { return $true }; $parentId=$process.ParentProcessId; $process=$all | Where-Object { $_.ProcessId -eq $parentId } | Select-Object -First 1 }; return $false }; $targets=@(); foreach ($port in @(8000,5173)) { foreach ($connection in @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)) { $process=$all | Where-Object { $_.ProcessId -eq $connection.OwningProcess } | Select-Object -First 1; if ($null -eq $process) { continue }; if (-not (Test-FromPackage $process)) { throw ('Porta ' + $port + ' ocupada por processo externo ao pacote. PID: ' + $process.ProcessId) }; $targets += $process } }; $patterns=@(@{Name='^python(w)?\.exe$'; Command='*-m uvicorn app.main:app*'}, @{Name='^python(w)?\.exe$'; Command='*-m http.server*5173*'}, @{Name='^python(w)?\.exe$'; Command='*-m app.cli.local_agent*'}, @{Name='^node\.exe$'; Command='*vite*5173*'}); foreach ($process in $all) { foreach ($pattern in $patterns) { if ($process.Name -match $pattern.Name -and [string]$process.CommandLine -like $pattern.Command -and (Test-FromPackage $process)) { $targets += $process; break } } }; $targets=@($targets | Sort-Object ProcessId -Unique); if (-not $validateOnly) { foreach ($process in $targets) { Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop } }; if ($validateOnly) { Write-Host ('Servicos identificados: ' + $targets.Count) } else { Write-Host ('Processos encerrados: ' + $targets.Count) }"
if errorlevel 1 (
    echo ERRO: Reinicio cancelado. Revise a mensagem acima.
    if /I not "%AUTOMATION_HUB_NO_PAUSE%"=="1" pause
    exit /b 1
)

if /I "%AUTOMATION_HUB_RESTART_VALIDATE_ONLY%"=="1" (
    echo Validacao do reinicio concluida. Inicializacao nao executada.
    exit /b 0
)

timeout /t 2 /nobreak >nul
echo Iniciando backend, dashboard e agente...
call "%AUTOMATION_HUB_ROOT%start_all.bat"
exit /b %errorlevel%
