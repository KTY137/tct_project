# beat_status.ps1 -- the pre-commit reality check for the orchestrator.
#
# Adam's most dangerous failure mode is not bad code: it is committing a file
# that another in-flight agent is still writing. That knowledge lives in
# working memory, which a context compaction silently corrupts.
#
# This script replaces that memory with disk truth: it prints HEAD, every
# dirty path, and cross-references each one against the file locks declared in
# .claude/session_state.md. Run it BEFORE every commit.
#
#   powershell -ExecutionPolicy Bypass -File .claude\beat_status.ps1
#
# It never blocks and never writes -- it only tells you what you are about to
# touch and who else claims it.  ASCII only: PS 5.1 reads BOM-less scripts as
# ANSI, so a stray em dash can break the parser.

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$stateFile = Join-Path $PSScriptRoot "session_state.md"
$BT = [string][char]96   # backtick, kept out of the source as a literal

Write-Host ""
Write-Host "HEAD  " -NoNewline -ForegroundColor DarkGray
git -C $repo log --oneline -1

# Parse the "IN FLIGHT" lock table:  | Beat | Agent | Locked paths |
$locks = @()
if (Test-Path $stateFile) {
    $inSection = $false
    foreach ($line in Get-Content $stateFile) {
        if ($line -match '^##\s+IN FLIGHT') { $inSection = $true; continue }
        if ($inSection -and $line -match '^##\s') { break }
        if (-not $inSection) { continue }
        if ($line -notmatch '^\|') { continue }
        if ($line -match '^\|\s*Beat') { continue }
        if ($line -match '^\|\s*-') { continue }
        $cells = @(($line -split '\|') | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" })
        if ($cells.Count -ge 3) {
            $paths = $cells[2].Replace($BT, "").Replace("*", "")
            $locks += [pscustomobject]@{ Agent = $cells[1]; Paths = $paths }
        }
    }
} else {
    Write-Host "  (no session_state.md - locks unknown)" -ForegroundColor Yellow
}

if ($locks.Count -gt 0) {
    Write-Host ""
    Write-Host "IN FLIGHT (do not stage these):" -ForegroundColor Yellow
    foreach ($l in $locks) {
        Write-Host ("  {0,-10} {1}" -f $l.Agent, $l.Paths) -ForegroundColor Yellow
    }
}

$dirty = @(git -C $repo status --porcelain)
if ($dirty.Count -eq 0) {
    Write-Host ""
    Write-Host "Working tree clean - safe to switch sessions." -ForegroundColor Green
    Write-Host ""
    exit 0
}

Write-Host ""
Write-Host "DIRTY PATHS:" -ForegroundColor Cyan
foreach ($line in $dirty) {
    $status = $line.Substring(0, 2).Trim()
    $path = $line.Substring(3).Trim().Trim('"')

    # A dirty path is "claimed" if any lock's path list mentions a directory or
    # filename that matches it. Deliberately fuzzy: a false warning is cheap, a
    # missed collision costs another agent's work.
    $owner = $null
    foreach ($l in $locks) {
        $needles = @(($l.Paths -split '[,;]') | ForEach-Object { $_.Trim().TrimEnd("/") } | Where-Object { $_.Length -ge 4 })
        foreach ($n in $needles) {
            if ($path -like "*$n*") { $owner = $l.Agent; break }
        }
        if ($owner) { break }
    }

    if ($owner) {
        Write-Host ("  [{0}] {1}" -f $status, $path) -NoNewline -ForegroundColor Red
        Write-Host ("   <-- CLAIMED by {0} (in flight)" -f $owner) -ForegroundColor Red
    } else {
        Write-Host ("  [{0}] {1}" -f $status, $path) -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "Rules: stage explicit paths only. Never 'git commit -am'. Never stage a CLAIMED path." -ForegroundColor DarkGray
Write-Host "Roadmap-stage commit? Run .claude\check_bucket_a.ps1 first -- Bucket-A test files must be byte-unchanged ([A-green] gate)." -ForegroundColor DarkGray
Write-Host ""
