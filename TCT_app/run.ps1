# Launch the TCT Setup application from the local virtual environment.
#   powershell -ExecutionPolicy Bypass -File .\run.ps1          # classic shell
#   powershell -ExecutionPolicy Bypass -File .\run.ps1 -Qml     # QML cockpit chrome
param(
    [switch]$Qml
)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPy = Join-Path $here ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPy)) {
    Write-Host "No .venv found. Run .\setup.ps1 first." -ForegroundColor Red
    exit 1
}
if ($Qml) { $env:TCT_QML_SHELL = "1" }
& $venvPy (Join-Path $here "main.py") @args
