# check_bucket_a.ps1 -- the machine-checkable [A-green] gate.
#
# The roadmap's capability/QML migration promises that the 47 CORE-PURE test
# files survive every stage BYTE-IDENTICAL. This script enforces that promise:
# it asserts no Bucket-A test file changed between a base ref and HEAD, exiting 1
# (with the offending files) if any did.
#
#   powershell -ExecutionPolicy Bypass -File .claude\check_bucket_a.ps1 [-BaseRef <ref>]
#
# The Bucket-A file list is NOT duplicated here: it is parsed from the single
# source of truth, docs\test_bucket_map.md, between the BUCKET_A_START /
# BUCKET_A_END markers. A vacuous pass (zero files parsed) is forbidden.
#
# Base ref default: the last recorded green bench SHA from
# .claude\session_state.md, else HEAD~1. Roadmap-stage gates should pass the
# explicit pre-stage base ref (-BaseRef <sha>).
#
# ASCII only: PS 5.1 reads BOM-less scripts as ANSI, so a stray non-ASCII
# character can break the parser.

param(
    [string]$BaseRef = ""
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$mapFile = Join-Path $repo "docs\test_bucket_map.md"
$stateFile = Join-Path $PSScriptRoot "session_state.md"
$BT = [string][char]96   # backtick, kept out of the source as a literal

if (-not (Test-Path $mapFile)) {
    Write-Host "ERROR: docs\test_bucket_map.md not found -- cannot resolve Bucket A." -ForegroundColor Red
    exit 2
}

# --- Parse the Bucket A file list from the map (single source of truth) -------
$content = Get-Content $mapFile -Raw
$rx = [regex]'(?s)<!--\s*BUCKET_A_START\s*-->(.*?)<!--\s*BUCKET_A_END\s*-->'
$m = $rx.Match($content)
if (-not $m.Success) {
    Write-Host "ERROR: BUCKET_A_START/END markers not found in test_bucket_map.md." -ForegroundColor Red
    exit 2
}
$region = $m.Groups[1].Value
$names = @([regex]::Matches($region, 'test_[A-Za-z0-9_]+\.py') |
    ForEach-Object { $_.Value } | Select-Object -Unique)

if ($names.Count -eq 0) {
    Write-Host "ERROR: parsed 0 Bucket-A files from the map (vacuous pass forbidden)." -ForegroundColor Red
    exit 2
}

$paths = @($names | ForEach-Object { "TCT_app/tests/$_" })

# --- Resolve the base ref -----------------------------------------------------
$autoDerived = $false
if ([string]::IsNullOrWhiteSpace($BaseRef)) {
    $autoDerived = $true
    $green = $null
    if (Test-Path $stateFile) {
        foreach ($line in Get-Content $stateFile) {
            if ($line -match 'Last green bench set') {
                $stripped = $line.Replace($BT, "")
                $hm = [regex]::Match($stripped, '\b([0-9a-f]{7,40})\b')
                if ($hm.Success) { $green = $hm.Groups[1].Value; break }
            }
        }
    }
    if ($green) { $BaseRef = $green } else { $BaseRef = "HEAD~1" }
}

# Verify the base ref resolves to a commit. If an auto-derived green SHA is not
# reachable (e.g. stale ledger), fall back to HEAD~1; if the user passed a bad
# ref explicitly, fail loudly.
& git -C $repo rev-parse --verify --quiet "$BaseRef^{commit}" > $null 2>&1
if ($LASTEXITCODE -ne 0) {
    if ($autoDerived) {
        Write-Host ("NOTE: base ref '{0}' does not resolve; falling back to HEAD~1." -f $BaseRef) -ForegroundColor Yellow
        $BaseRef = "HEAD~1"
        & git -C $repo rev-parse --verify --quiet "$BaseRef^{commit}" > $null 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Host "ERROR: HEAD~1 does not resolve either -- shallow history?" -ForegroundColor Red
            exit 2
        }
    } else {
        Write-Host ("ERROR: base ref '{0}' does not resolve to a commit." -f $BaseRef) -ForegroundColor Red
        exit 2
    }
}

# --- The gate: git diff of the Bucket-A paths must be EMPTY --------------------
$range = "$BaseRef..HEAD"
$changed = @(& git -C $repo diff --name-only $range -- @paths 2>$null |
    Where-Object { $_ -and $_.Trim() -ne "" })

Write-Host ""
Write-Host ("[A-green] check  base={0}  files={1}" -f $BaseRef, $paths.Count) -ForegroundColor DarkGray

if ($changed.Count -eq 0) {
    Write-Host ("PASS: 0 Bucket-A files changed in {0}." -f $range) -ForegroundColor Green
    Write-Host ""
    exit 0
}

Write-Host ("FAIL: [A-green] BROKEN -- {0} Bucket-A file(s) changed in {1}:" -f $changed.Count, $range) -ForegroundColor Red
foreach ($c in $changed) { Write-Host ("    {0}" -f $c) -ForegroundColor Red }
Write-Host ""
Write-Host "Bucket-A test files must survive the migration byte-identical. Revert" -ForegroundColor Red
Write-Host "the change or, if intentional, re-ratify the bucket map with Kaya first." -ForegroundColor Red
Write-Host ""
exit 1
