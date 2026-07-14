# Launch the TCT Setup application from the local virtual environment.
# QML cockpit chrome is the DEFAULT (Kaya, 2026-07-13: "die app soll immer
# im qml modus starten" — agents kept launching classic by accident).
#   powershell -ExecutionPolicy Bypass -File .\run.ps1            # QML shell (default)
#   powershell -ExecutionPolicy Bypass -File .\run.ps1 -Classic   # classic fallback shell
param(
    [switch]$Classic,
    [switch]$Qml   # kept for backward compatibility; QML is default anyway
)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPy = Join-Path $here ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPy)) {
    Write-Host "No .venv found. Run .\setup.ps1 first." -ForegroundColor Red
    exit 1
}
if ($Classic) { $env:TCT_QML_SHELL = "0" } else { $env:TCT_QML_SHELL = "1" }
& $venvPy (Join-Path $here "main.py") @args
