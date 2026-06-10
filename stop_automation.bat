@echo off
setlocal
cd /d "%~dp0"
set "AUTOMATION_HUB_ROOT=%~dp0"

echo ============================================================
echo Automation HUB v1.0 - Parar TODAS as execucoes da automacao
echo ============================================================
echo Encerrando navegadores da automacao, agente local, backend e dashboard
echo deste pacote (Chrome/Edge/Chromium, python e node). Processos externos
echo (seu Chrome/Edge pessoal) NAO sao tocados.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $root=[System.IO.Path]::GetFullPath($env:AUTOMATION_HUB_ROOT).TrimEnd('\'); $all=@(Get-CimInstance Win32_Process); function Test-FromPackage([object]$process) { for ($level=0; $level -lt 6 -and $null -ne $process; $level++) { if ([string]$process.CommandLine -like ('*' + $root + '*')) { return $true }; $parentId=$process.ParentProcessId; $process=$all | Where-Object { $_.ProcessId -eq $parentId } | Select-Object -First 1 }; return $false }; $targets=@(); foreach ($port in @(8000,5173)) { foreach ($connection in @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)) { $process=$all | Where-Object { $_.ProcessId -eq $connection.OwningProcess } | Select-Object -First 1; if ($null -eq $process) { continue }; if (Test-FromPackage $process) { $targets += $process } } }; $patterns=@(@{Name='^python(w)?\.exe$'; Command='*-m uvicorn app.main:app*'}, @{Name='^python(w)?\.exe$'; Command='*-m http.server*5173*'}, @{Name='^python(w)?\.exe$'; Command='*-m app.cli.local_agent*'}, @{Name='^node\.exe$'; Command='*vite*5173*'}, @{Name='^node\.exe$'; Command='*playwright*'}, @{Name='^(chrome|msedge|headless_shell|chrome_headless_shell)\.exe$'; Command='*'}); foreach ($process in $all) { foreach ($pattern in $patterns) { if ($process.Name -match $pattern.Name -and [string]$process.CommandLine -like $pattern.Command -and (Test-FromPackage $process)) { $targets += $process; break } } }; $targets=@($targets | Sort-Object ProcessId -Unique); foreach ($process in $targets) { Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue }; Write-Host ('Processos encerrados: ' + $targets.Count)"
if errorlevel 1 (
    echo ERRO: Falha ao parar as execucoes. Revise a mensagem acima.
    if /I not "%AUTOMATION_HUB_NO_PAUSE%"=="1" pause
    exit /b 1
)

echo.
echo Todas as execucoes da automacao foram encerradas.
if /I not "%AUTOMATION_HUB_NO_PAUSE%"=="1" pause
exit /b 0
