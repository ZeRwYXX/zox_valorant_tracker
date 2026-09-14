. (Join-Path $PSScriptRoot "common.ps1")










$Script:PhaseTotal = 4
function Show-Phase([int]$step, [string]$text) {
    $width = 22
    $filled = [int][Math]::Round($width * ($step / $Script:PhaseTotal))
    if ($filled -gt $width) { $filled = $width }
    $bar = ("$([char]0x2588)" * $filled) + ("$([char]0x2591)" * ($width - $filled))
    $line = "  [$bar]  $text"

    Write-Host ("`r" + $line.PadRight(70)) -NoNewline -ForegroundColor Gray
}
function Finish-Progress([string]$text) {
    Show-Phase $Script:PhaseTotal $text
    Write-Host ""
}

Write-Host ""
Write-Host "  VALORANT " -ForegroundColor Red -NoNewline
Write-Host "ZeRwYX Tracker" -ForegroundColor White
Write-Host ""

Write-ScoutLog -Log launcher -Message "startup requested (v$(Get-LocalVersion))"


$markerPath = Join-Path $ScoutDir "installed.json"
if (Test-Path $markerPath) {
    try {
        $markerVersion = [string]((Get-Content $markerPath -Raw -Encoding UTF8 | ConvertFrom-Json).version)
        if ($markerVersion -and (Compare-ScoutVersion $markerVersion (Get-LocalVersion)) -gt 0) {
            Write-Host "  Installation incomplete (v$markerVersion marker / v$(Get-LocalVersion) files); retrying the update..." -ForegroundColor Yellow
            Write-ScoutLog -Log launcher -Level WARN -Code VS-UPDATE-003 -Message "marker version $markerVersion is ahead of app version $(Get-LocalVersion); retrying update before startup"
            & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "update.ps1")
            if ($LASTEXITCODE -ne 0) {
                Write-ScoutLog -Log launcher -Level ERROR -Code VS-UPDATE-003 -Message "incomplete-update recovery failed (rc=$LASTEXITCODE)"
            }
        }
    } catch {
        Write-ScoutLog -Log launcher -Level WARN -Code VS-UPDATE-003 -Message "could not inspect installation marker: $($_.Exception.Message)"
    }
}


Show-Phase 1 "Checking your installation..."
$markers = Test-Markers
if (-not $markers.Ok) {
    Write-Host ""
    Write-ScoutLog -Log launcher -Level ERROR -Code VS-DEPS-001 -Message "startup blocked: $($markers.Reason)"
    Show-FatalDialog "ZeRwYX Tracker can't start: $($markers.Reason).`n`nRun install.bat to repair (your settings and data are kept)." "launcher"
    exit 1
}
$venv = Test-Venv -Quick
if (-not $venv.Ok) {
    Write-Host ""
    $code = "VS-DEPS-001"
    foreach ($r in $venv.Reasons) {
        if ($r -match 'python|venv') { $code = "VS-PY-001" }
        Write-ScoutLog -Log launcher -Level ERROR -Code $code -Message "startup blocked: $r"
    }
    Show-FatalDialog "ZeRwYX Tracker can't start: $($venv.Reasons[0]).`n`nRun install.bat to repair (your settings and data are kept)." "launcher"
    exit 1
}






Show-Phase 2 "Checking for updates..."
$updateArgs = @()
if (Test-Path (Join-Path $Root ".git")) {
    $updateArgs += "-DevOverride"
    Note "Developer checkout detected - automatic update is enabled."
}
try {
        $tag = Test-UpdateAvailable
        if ($tag) {
            Write-Host ""
            Write-Host ""
            Write-Host "  A new version ($tag) is available - updating now." -ForegroundColor Cyan
            Write-Host "  This takes a minute; your settings and match data are kept." -ForegroundColor DarkGray
            Write-Host ""
            Write-ScoutLog -Log launcher -Message "update $tag available - applying before launch"
            & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "update.ps1") @updateArgs
            if ($LASTEXITCODE -eq 0) {
                Write-ScoutLog -Log launcher -Message "auto-update finished - now on v$(Get-LocalVersion)"
                Write-Host "  Updated to v$(Get-LocalVersion)." -ForegroundColor Green
                Write-Host ""
            } else {

                $env:VS_UPDATE_AVAILABLE = $tag
                Write-ScoutLog -Log launcher -Level WARN -Message "auto-update to $tag failed (rc=$LASTEXITCODE); launching current version"
                Write-Host "  Couldn't install the update - starting your current version." -ForegroundColor Yellow
                Write-Host ""
            }
        }
} catch {
    Write-ScoutLog -Log launcher -Message "update check/apply skipped: $($_.Exception.Message)"
}


Show-Phase 3 "Starting ZeRwYX Tracker..."
Stop-RunningApp "launcher" | Out-Null







Finish-Progress "Opening the scoreboard..."
$env:VS_PREVALIDATED = "1"
$env:VS_ATTACHED_CLI = "1"
Write-ScoutLog -Log launcher -Message "handing this console to run.py (attached single-window mode)"
& $VenvPy (Join-Path $Root "run.py") --prod
$code = $LASTEXITCODE
Write-ScoutLog -Log launcher -Message "run.py exited with code $code"
exit $code
