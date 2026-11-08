# ============================== SETTINGS ==============================
# Edit the defaults here, or override on the command line, e.g.:
#   .\scripts\tools\fix_low_integrity.ps1 -Paths C:\AI              (quick check of all of C:\AI)
#   .\scripts\tools\fix_low_integrity.ps1 -Paths C:\AI -Mode Fix    (fix it)
param(
    [ValidateSet("Check","Fix")]
    [string]  $Mode     = "Check",                  # Check = report only | Fix = set Medium
    [string[]]$Paths    = @("C:\AI\frameworks"),    # folders to scan
    [string[]]$Patterns = @("*.exe"),               # @("*") = everything (slow, finds folders too)
    [bool]    $Recurse  = $true,                    # include subfolders
    [string[]]$Exclude  = @()                       # skip results, e.g. @("*\node_modules\*")
)
# ======================================================================
# Fixes Electron apps crashing at launch (exit -2147483645 / 0x80000003)
# caused by a Low mandatory integrity label. See .agents/ELECTRON-LOW-INTEGRITY-CRASH.md

# icacls prints "<path> <first ACE>" for each item, then indented ACE lines.
# The path may contain spaces, so resolve it by finding the longest existing prefix.
function Resolve-IcaclsPath($line) {
    $tok = $line -split ' '
    for ($i = $tok.Count; $i -ge 1; $i--) {
        $cand = ($tok[0..($i - 1)] -join ' ')
        if (Test-Path -LiteralPath $cand) { return $cand }
    }
    return $line
}

$sw   = [Diagnostics.Stopwatch]::StartNew()
$hits = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)

foreach ($root in $Paths) {
    if (-not (Test-Path -LiteralPath $root)) { Write-Warning "Not found: $root"; continue }
    foreach ($pat in $Patterns) {
        Write-Host "Scanning $root  [$pat] ..." -ForegroundColor Cyan
        $icaclsArgs = @((Join-Path $root $pat), '/C')
        if ($Recurse) { $icaclsArgs += '/T' }
        $header = $null
        & icacls @icaclsArgs 2>$null | ForEach-Object {
            if ($_ -match '^[A-Za-z]:\\') { $header = $_ }
            if ($header -and $_ -match 'Mandatory Label\\Low') { [void]$hits.Add((Resolve-IcaclsPath $header)) }
        }
    }
}

$found = @($hits | Where-Object { $p = $_; -not ($Exclude | Where-Object { $p -like $_ }) } | Sort-Object)

if ($found.Count -eq 0) {
    Write-Host "`nNo Low-integrity items found. ($([int]$sw.Elapsed.TotalSeconds)s)" -ForegroundColor Green
    return
}

if ($Mode -ne "Fix") {
    $found | ForEach-Object { Write-Host "LOW  $_" -ForegroundColor Yellow }
    Write-Host "`n$($found.Count) Low-integrity item(s). Run with -Mode Fix to repair. ($([int]$sw.Elapsed.TotalSeconds)s)" -ForegroundColor Yellow
    return
}

$fixed = 0; $failed = 0
foreach ($p in $found) {
    if (Test-Path -LiteralPath $p -PathType Container) { $out = & icacls $p /setintegritylevel "(OI)(CI)M" /T /C /Q 2>&1 }
    else                                              { $out = & icacls $p /setintegritylevel M 2>&1 }
    if ($LASTEXITCODE -eq 0) { $fixed++; Write-Host "FIXED  $p" -ForegroundColor Green }
    else { $failed++; Write-Host "FAILED $p : $out" -ForegroundColor Red }
}
Write-Host "`nFixed $fixed, failed $failed. ($([int]$sw.Elapsed.TotalSeconds)s)" -ForegroundColor Cyan
