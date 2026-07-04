# =====================================================================
# TCT Setup - one-shot environment bootstrap (Windows / PowerShell)
#
#   Creates a local .venv inside this folder and installs all pip
#   dependencies. Run once after copying the TCT_app folder:
#
#       powershell -ExecutionPolicy Bypass -File .\setup.ps1
#
#   Then launch with .\run.ps1
# =====================================================================
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$venv = Join-Path $here ".venv"
$venvPy = Join-Path $venv "Scripts\python.exe"

Write-Host "TCT Setup - environment bootstrap" -ForegroundColor Cyan
Write-Host "Folder: $here"

# 1. Locate a Python interpreter to build the venv from.
$bootPy = $null
foreach ($cand in @("py", "python", "python3")) {
    $cmd = Get-Command $cand -ErrorAction SilentlyContinue
    if ($cmd) { $bootPy = $cand; break }
}
if (-not $bootPy) {
    Write-Host "ERROR: No Python interpreter found on PATH. Install Python 3.10+ first." -ForegroundColor Red
    exit 1
}
Write-Host "Using bootstrap interpreter: $bootPy"

# 2. Create the venv (idempotent).
if (-not (Test-Path $venvPy)) {
    Write-Host "Creating virtual environment in .venv ..."
    if ($bootPy -eq "py") { & py -3 -m venv $venv } else { & $bootPy -m venv $venv }
} else {
    Write-Host ".venv already exists - reusing it."
}

# 3. Upgrade pip and install requirements.
Write-Host "Upgrading pip ..."
& $venvPy -m pip install --upgrade pip
Write-Host "Installing requirements ..."
& $venvPy -m pip install -r (Join-Path $here "requirements.txt")

Write-Host ""
Write-Host "Done. Launch the app with:  .\run.ps1" -ForegroundColor Green
Write-Host ""
Write-Host "NOTE: For REAL hardware you also need vendor SDKs not on PyPI:" -ForegroundColor Yellow
Write-Host "  - FLIR Spinnaker SDK + PySpin   (camera)"
Write-Host "  - PSI DRS4 board driver         (drs4 oscilloscope backend)"
Write-Host "The app runs fully in simulation mode without them."
