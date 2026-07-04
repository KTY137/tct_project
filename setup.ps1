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

# 4. (Optional) Install the vendored FLIR PySpin / Spinnaker wheel into the venv.
#    PySpin is not on PyPI, so a matching wheel is shipped in vendor\spinnaker.
#    It is Python/OS-specific (e.g. cp310 / win_amd64) and needs numpy (already
#    installed above via requirements.txt).  This whole step is best-effort: a
#    version/arch mismatch or ABI error must NOT abort setup, because the camera
#    driver falls back to simulation when PySpin is unavailable.
$spinDir = Join-Path $here "vendor\spinnaker"
$wheel = Get-ChildItem -Path $spinDir -Filter "spinnaker_python-*.whl" -ErrorAction SilentlyContinue |
         Select-Object -First 1
if (-not $wheel) {
    Write-Host "No vendored PySpin wheel in vendor\spinnaker - skipping (camera runs in simulation)." -ForegroundColor Yellow
} else {
    # Interpreter tag, e.g. "cp310" + bit-width, to pre-check wheel compatibility.
    $pyTag  = (& $venvPy -c "import sys;print(f'cp{sys.version_info.major}{sys.version_info.minor}')").Trim()
    $pyBits = (& $venvPy -c "import struct;print(struct.calcsize('P')*8)").Trim()
    $name   = $wheel.Name
    $needs64 = $name -match "win_amd64|amd64|win64"
    if (($name -notmatch $pyTag) -or ($needs64 -and $pyBits -ne "64")) {
        Write-Host "PySpin wheel '$name' does not match this interpreter ($pyTag, $pyBits-bit)." -ForegroundColor Yellow
        Write-Host "  This wheel needs 64-bit CPython 3.10 - skipping install (camera runs in simulation)." -ForegroundColor Yellow
    } else {
        Write-Host "Installing vendored PySpin wheel: $name ..." -ForegroundColor Cyan
        & $venvPy -m pip install --upgrade "$($wheel.FullName)"
        if ($LASTEXITCODE -ne 0) {
            Write-Host "WARNING: PySpin wheel install failed - camera will run in simulation mode." -ForegroundColor Yellow
        } else {
            # Verify the binding actually imports.  Only check the import itself: PySpin has
            # no __version__ attribute, and the proper version query (System.GetInstance())
            # needs the Spinnaker SDK runtime (SpinnakerSDK_FULL_*.exe: drivers + VS
            # redistributables), which the pip wheel does NOT provide, so we don't call it here.
            & $venvPy -c "import PySpin; print('PySpin import OK')"
            if ($LASTEXITCODE -ne 0) {
                Write-Host "WARNING: PySpin installed but failed to import." -ForegroundColor Yellow
                Write-Host "  Common causes: numpy 2.x ABI mismatch (PySpin 3.2 is built against numpy 1.x)," -ForegroundColor Yellow
                Write-Host "  or the Spinnaker SDK runtime is not installed. Camera runs in simulation until fixed." -ForegroundColor Yellow
            }
        }
    }
}

Write-Host ""
Write-Host "Done. Launch the app with:  .\run.ps1" -ForegroundColor Green
Write-Host ""
Write-Host "NOTE: The PySpin camera binding is installed automatically from vendor\spinnaker" -ForegroundColor Yellow
Write-Host "      when the interpreter is 64-bit CPython 3.10. For REAL hardware you still need:" -ForegroundColor Yellow
Write-Host "  - FLIR Spinnaker SDK runtime installer  (camera drivers + VS redistributables)"
Write-Host "  - PSI DRS4 board driver                 (drs4 oscilloscope backend)"
Write-Host "The app runs fully in simulation mode without them."
