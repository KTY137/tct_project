param(
    [string]$PdfPath = "artifacts_codex\tct_camera_metrology_target_v1.pdf"
)

$ErrorActionPreference = "Stop"
$culture = [System.Globalization.CultureInfo]::InvariantCulture
$enc = [System.Text.Encoding]::ASCII

$PageWmm = 297.0
$PageHmm = 210.0
$PtPerMm = 72.0 / 25.4

function Pt([double]$mm) { return $mm * $script:PtPerMm }
function F([double]$v) { return $v.ToString("0.###", $script:culture) }

$sb = [System.Text.StringBuilder]::new()
function Add([string]$s) { [void]$script:sb.AppendLine($s) }

function PdfY([double]$yTopMm, [double]$hMm = 0.0) {
    return Pt ($script:PageHmm - $yTopMm - $hMm)
}

function SetGray([double]$g) {
    Add ("{0} g {0} G" -f (F $g))
}

function RectMM([double]$x, [double]$y, [double]$w, [double]$h, [string]$mode = "f") {
    Add ("{0} {1} {2} {3} re {4}" -f (F (Pt $x)), (F (PdfY $y $h)), (F (Pt $w)), (F (Pt $h)), $mode)
}

function LineMM([double]$x1, [double]$y1, [double]$x2, [double]$y2) {
    Add ("{0} {1} m {2} {3} l S" -f (F (Pt $x1)), (F (PdfY $y1)), (F (Pt $x2)), (F (PdfY $y2)))
}

function TextMM([double]$x, [double]$y, [string]$text, [double]$size = 7.0) {
    $safe = $text.Replace("\", "\\").Replace("(", "\(").Replace(")", "\)")
    Add ("BT /F1 {0} Tf {1} {2} Td ({3}) Tj ET" -f (F $size), (F (Pt $x)), (F (PdfY $y)), $safe)
}

function PolyMM([double[][]]$pts) {
    if ($pts.Count -lt 3) { return }
    Add ("{0} {1} m" -f (F (Pt $pts[0][0])), (F (PdfY $pts[0][1])))
    for ($i = 1; $i -lt $pts.Count; $i++) {
        Add ("{0} {1} l" -f (F (Pt $pts[$i][0])), (F (PdfY $pts[$i][1])))
    }
    Add "h f"
}

function Checker([double]$x, [double]$y, [double]$w, [double]$h, [double]$pitch) {
    $cols = [int][Math]::Floor($w / $pitch)
    $rows = [int][Math]::Floor($h / $pitch)
    for ($r = 0; $r -lt $rows; $r++) {
        for ($c = 0; $c -lt $cols; $c++) {
            if ((($r + $c) % 2) -eq 0) {
                RectMM ($x + $c * $pitch) ($y + $r * $pitch) $pitch $pitch
            }
        }
    }
}

function RandomPatch([double]$x, [double]$y, [double]$w, [double]$h, [double]$cell, [uint32]$seed) {
    $state = $seed
    $cols = [int][Math]::Floor($w / $cell)
    $rows = [int][Math]::Floor($h / $cell)
    for ($r = 0; $r -lt $rows; $r++) {
        for ($c = 0; $c -lt $cols; $c++) {
            $state = [uint32]((([uint64]1664525 * [uint64]$state + [uint64]1013904223) % [uint64]4294967296))
            $bit = (($state -shr 29) -bxor ($r * 3) -bxor ($c * 5)) -band 1
            if ($bit -eq 1) {
                RectMM ($x + $c * $cell) ($y + $r * $cell) $cell $cell
            }
        }
    }
}

function LinePairs([double]$x, [double]$y, [double]$w, [double]$h, [double]$bar, [string]$orientation) {
    if ($orientation -eq "vertical") {
        $n = [int][Math]::Floor($w / (2.0 * $bar))
        for ($i = 0; $i -lt $n; $i++) {
            RectMM ($x + 2.0 * $bar * $i) $y $bar $h
        }
    } else {
        $n = [int][Math]::Floor($h / (2.0 * $bar))
        for ($i = 0; $i -lt $n; $i++) {
            RectMM $x ($y + 2.0 * $bar * $i) $w $bar
        }
    }
}

function Cross([double]$x, [double]$y, [double]$s = 1.6) {
    LineMM ($x - $s) $y ($x + $s) $y
    LineMM $x ($y - $s) $x ($y + $s)
    RectMM ($x - 0.25) ($y - 0.25) 0.5 0.5
}

function Marker([double]$x, [double]$y, [int]$id) {
    $cell = 1.5
    RectMM $x $y (7 * $cell) (7 * $cell)
    SetGray 1.0
    RectMM ($x + $cell) ($y + $cell) (5 * $cell) (5 * $cell)
    SetGray 0.0
    for ($r = 0; $r -lt 5; $r++) {
        for ($c = 0; $c -lt 5; $c++) {
            $v = (($id * 17 + $r * 7 + $c * 11 + ($r * $c)) -band 3)
            if ($v -eq 0 -or $v -eq 3) {
                RectMM ($x + ($c + 1) * $cell) ($y + ($r + 1) * $cell) $cell $cell
            }
        }
    }
}

Add "q"
SetGray 1.0
RectMM 0 0 $PageWmm $PageHmm
SetGray 0.0
Add "0.35 w"

TextMM 10 9 "TCT CAMERA METROLOGY TARGET v1 - PRINT AT 100%, DO NOT FIT / DO NOT SCALE" 8
TextMM 10 14 "Use linear capture: gamma off, auto exposure/gain off, no saturation. Units on page are millimetres." 6.5

RectMM 8 18 281 181 "S"

# Rulers and scale checks.
Add "0.2 w"
for ($i = 0; $i -le 280; $i += 5) {
    $tick = if (($i % 10) -eq 0) { 4.0 } else { 2.0 }
    LineMM (8 + $i) 18 (8 + $i) (18 + $tick)
    if (($i % 50) -eq 0) { TextMM (7.5 + $i) 25 "$i" 5.5 }
}
for ($i = 0; $i -le 180; $i += 5) {
    $tick = if (($i % 10) -eq 0) { 4.0 } else { 2.0 }
    LineMM 8 (18 + $i) (8 + $tick) (18 + $i)
    if (($i % 50) -eq 0) { TextMM 13 (20 + $i) "$i" 5.5 }
}

TextMM 15 204 "100 mm scale bar:" 6.5
RectMM 50 199 100 3 "S"
for ($i = 0; $i -lt 100; $i++) {
    if (($i % 2) -eq 0) { RectMM (50 + $i) 199 1 3 }
}

# Corner fiducials.
Add "0.5 w"
Cross 20 30 4
Cross 277 30 4
Cross 20 188 4
Cross 277 188 4
TextMM 24 31 "A" 8
TextMM 266 31 "B" 8
TextMM 24 189 "C" 8
TextMM 266 189 "D" 8

# Checkerboards at multiple scales.
Add "0.15 w"
TextMM 16 42 "checker 2.0 mm" 6
Checker 16 45 30 30 2.0
RectMM 16 45 30 30 "S"
TextMM 16 84 "checker 1.0 mm" 6
Checker 16 87 30 30 1.0
RectMM 16 87 30 30 "S"
TextMM 54 42 "checker 0.5 mm" 6
Checker 54 45 25 25 0.5
RectMM 54 45 25 25 "S"
TextMM 54 84 "checker 0.25 mm" 6
Checker 54 87 25 25 0.25
RectMM 54 87 25 25 "S"

# Main phase-correlation patches.
TextMM 98 42 "random ROI 1.0 mm cells - primary PPC patch" 6
RandomPatch 98 45 92 58 1.0 137
RectMM 98 45 92 58 "S"
TextMM 113 110 "fine random 0.5 mm cells - subpixel/noise stress" 6
RandomPatch 113 113 62 32 0.5 987654321
RectMM 113 113 62 32 "S"
TextMM 181 110 "micro random 0.25 mm" 6
RandomPatch 181 113 24 24 0.25 424242
RectMM 181 113 24 24 "S"

# Slanted edges and line pairs.
TextMM 204 42 "slanted edges 5 deg / focus" 6
PolyMM @(@(204,47), @(276,53.3), @(276,72), @(204,65.7))
RectMM 204 47 72 25 "S"
SetGray 1.0
PolyMM @(@(213,49), @(230,50.5), @(230,69), @(213,67.5))
SetGray 0.0
TextMM 204 82 "line pairs: bar width" 6
LinePairs 204 86 22 38 1.0 "vertical"
TextMM 204 127 "1.0" 5
LinePairs 232 86 18 38 0.5 "vertical"
TextMM 232 127 "0.5" 5
LinePairs 256 86 14 38 0.25 "vertical"
TextMM 256 127 "0.25" 5
RectMM 204 86 22 38 "S"
RectMM 232 86 18 38 "S"
RectMM 256 86 14 38 "S"

# Affine calibration grid.
TextMM 16 131 "5 mm fiducial grid - fit scale, rotation, shear, residuals" 6
Add "0.25 w"
for ($gy = 140; $gy -le 185; $gy += 5) {
    for ($gx = 25; $gx -le 190; $gx += 5) {
        Cross $gx $gy 0.9
    }
}
RectMM 22 137 171 51 "S"

# ID markers around useful ROIs.
Marker 84 45 1
Marker 192 45 2
Marker 84 134 3
Marker 192 134 4
TextMM 84 58 "ID1" 5
TextMM 192 58 "ID2" 5
TextMM 84 147 "ID3" 5
TextMM 192 147 "ID4" 5

# No-move ROI suggestion box.
Add "0.6 w"
RectMM 121 59 46 30 "S"
TextMM 121 57 "suggested ROI for first tests" 5.5

Add "Q"

$content = $sb.ToString()
$pageWpt = F (Pt $PageWmm)
$pageHpt = F (Pt $PageHmm)
$contentBytes = $enc.GetBytes($content)

$objects = @(
    "1 0 obj`n<< /Type /Catalog /Pages 2 0 R >>`nendobj`n",
    "2 0 obj`n<< /Type /Pages /Kids [3 0 R] /Count 1 >>`nendobj`n",
    "3 0 obj`n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 $pageWpt $pageHpt] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>`nendobj`n",
    "4 0 obj`n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>`nendobj`n",
    "5 0 obj`n<< /Length $($contentBytes.Length) >>`nstream`n$content`nendstream`nendobj`n"
)

$pdf = [System.Collections.Generic.List[byte]]::new()
function AddBytes([string]$s) {
    $b = $script:enc.GetBytes($s)
    $script:pdf.AddRange($b)
}

AddBytes "%PDF-1.4`n% TCT camera metrology target`n"
$offsets = @()
foreach ($obj in $objects) {
    $offsets += $pdf.Count
    AddBytes $obj
}
$xrefStart = $pdf.Count
AddBytes "xref`n0 6`n"
AddBytes "0000000000 65535 f `n"
foreach ($off in $offsets) {
    AddBytes ($off.ToString("0000000000") + " 00000 n `n")
}
AddBytes "trailer`n<< /Size 6 /Root 1 0 R >>`nstartxref`n$xrefStart`n%%EOF`n"

$fullPdf = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $PdfPath))
[System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($fullPdf)) | Out-Null
[System.IO.File]::WriteAllBytes($fullPdf, $pdf.ToArray())

Write-Host "Wrote $fullPdf"
