param(
    [Parameter(Mandatory = $true)]
    [string]$Script,

    [Parameter(Mandatory = $true)]
    [string]$OutLog,

    [Parameter(Mandatory = $true)]
    [string]$ErrLog,

    [Parameter(Mandatory = $true)]
    [string]$WorkingDirectory
)

$ErrorActionPreference = "Stop"

$scriptPath = (Resolve-Path -LiteralPath $Script).Path
$workDir = (Resolve-Path -LiteralPath $WorkingDirectory).Path
$outDir = Split-Path -Parent $OutLog
$errDir = Split-Path -Parent $ErrLog
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
New-Item -ItemType Directory -Force -Path $errDir | Out-Null

$command = 'set "AUTOMATION_HUB_NO_PAUSE=1" && call "' + $scriptPath + '" 1> "' + $OutLog + '" 2> "' + $ErrLog + '"'

Start-Process `
    -FilePath "cmd.exe" `
    -ArgumentList @("/d", "/c", $command) `
    -WorkingDirectory $workDir `
    -WindowStyle Hidden
