param(
    [string]$BaseUrl = $env:AP_BACKEND_URL,
    [string]$DatabaseUrl = $env:AP_TEST_POSTGRES_URL,
    [string]$SkipExternal = $env:SKIP_EXTERNAL
)

$ErrorActionPreference = "Stop"

$ScriptName = "permission-resume-smoke"

function Write-SmokeLog {
    param([string]$Message)
    Write-Host "[$ScriptName] $Message"
}

function Fail-Smoke {
    param([string]$Message)
    Write-Error "[$ScriptName] FAIL: $Message"
    exit 2
}

function Resolve-Bash {
    $gitBash = "C:\Program Files\Git\bin\bash.exe"
    if (Test-Path -LiteralPath $gitBash) {
        return $gitBash
    }
    $systemBash = "C:\Windows\System32\bash.exe"
    if (Test-Path -LiteralPath $systemBash) {
        return $systemBash
    }
    $wsl = Get-Command wsl -ErrorAction SilentlyContinue
    if ($wsl) {
        return "wsl"
    }
    return $null
}

$bash = Resolve-Bash
if (-not $bash) {
    Write-SmokeLog "SKIP: permission-resume smoke requires Git Bash, WSL, or a Bash-on-Windows shell. Bash optional on Windows; primary local workflow is PowerShell. Install Git for Windows or run from WSL to enable this smoke."
    exit 0
}

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$Script = Join-Path $RepoRoot "scripts\permission-resume-smoke.sh"
if (-not (Test-Path -LiteralPath $Script)) {
    Fail-Smoke "missing permission-resume-smoke.sh at $Script"
}

$env:API_BASE = if ($BaseUrl) { $BaseUrl } else { "http://localhost:8000" }
$env:AP_TEST_POSTGRES_URL = if ($DatabaseUrl) { $DatabaseUrl } else { $env:AP_TEST_POSTGRES_URL }
$env:AP_DATABASE_URL = if (-not $env:AP_TEST_POSTGRES_URL -and $env:AP_DATABASE_URL) { $env:AP_DATABASE_URL } else { $env:AP_TEST_POSTGRES_URL }
$env:SKIP_EXTERNAL = if ($SkipExternal) { $SkipExternal } else { "0" }
$env:SMOKE_TMP_DIR = if ($env:SMOKE_TMP_DIR) { $env:SMOKE_TMP_DIR } else { Join-Path $RepoRoot ".tmp\smokes" }

Write-SmokeLog "delegating to $Script via $bash"
if ($bash -eq "wsl") {
    & wsl -e bash -c "cd '$($RepoRoot.Path -replace '\\','/')' && API_BASE='$env:API_BASE' AP_TEST_POSTGRES_URL='$env:AP_TEST_POSTGRES_URL' AP_DATABASE_URL='$env:AP_DATABASE_URL' SKIP_EXTERNAL='$env:SKIP_EXTERNAL' SMOKE_TMP_DIR='$($env:SMOKE_TMP_DIR -replace '\\','/')' bash scripts/permission-resume-smoke.sh"
} else {
    & $bash $Script
}
if ($LASTEXITCODE -ne 0) {
    Fail-Smoke "permission-resume smoke failed with exit $LASTEXITCODE"
}

Write-SmokeLog "permission-resume smoke ok"
