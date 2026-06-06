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

function Write-SmokeResult {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("passed", "failed", "skipped", "warned")]
        [string]$Result,
        [string]$Reason = ""
    )
    Write-Host "SMOKE_RESULT=$Result"
    if ($Reason) {
        Write-Host "SMOKE_REASON=$Reason"
    }
    Write-Host "SMOKE_CATEGORY=optional"
}

function Fail-Smoke {
    param([string]$Message)
    Write-Error "[$ScriptName] FAIL: $Message"
    Write-SmokeResult -Result "failed" -Reason $Message
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

# Returns @{ ok = $bool; reason = $string; detail = $object }
function Test-Prerequisites {
    param([string]$Url)

    # Backend health
    try {
        $health = Invoke-RestMethod -Method GET -Uri "$Url/health" -TimeoutSec 10
    } catch {
        return @{ ok = $false; reason = "backend_health_unreachable: $($_.Exception.Message)" }
    }
    if ($health.status -ne "ok") {
        return @{ ok = $false; reason = "backend_health_not_ok: $($health.status)" }
    }

    # Worker dependencies: postgres + redis must be ok
    try {
        $deps = Invoke-RestMethod -Method GET -Uri "$Url/health/dependencies" -TimeoutSec 10
    } catch {
        return @{ ok = $false; reason = "dependencies_unreachable: $($_.Exception.Message)" }
    }
    $pg = $deps.dependencies.postgres.status
    $redis = $deps.dependencies.redis.status
    if ($pg -ne "ok" -or $redis -ne "ok") {
        return @{ ok = $false; reason = "postgres_or_redis_not_ok pg=$pg redis=$redis" }
    }

    # Ollama model availability. The smoke needs a working model to drive
    # an agent run that will be paused and resumed.
    try {
        $modelsResp = Invoke-RestMethod -Method GET -Uri "$Url/models" -TimeoutSec 10
    } catch {
        return @{ ok = $false; reason = "models_unreachable: $($_.Exception.Message)" }
    }
    $models = @($modelsResp.models)
    $modelName = $null
    foreach ($m in $models) {
        $name = $m.name
        if (-not $name) { continue }
        if ($name -match "cloud") { continue }
        if ($modelName) { continue }
        $modelName = $name
    }
    if (-not $modelName) {
        return @{ ok = $false; reason = "no_ollama_model_available" }
    }

    # Test endpoint gate. The full flow seeds a permission request via the
    # DB and approves it via the API. The API works in production, but the
    # smoke bypasses Ollama rate limits / model behaviour by relying on a
    # deterministic, time-bounded flow. Without the test-endpoint gate
    # enabled, the smoke is unsafe to run in non-test environments.
    $enableTestEndpoints = $env:AP_ENABLE_TEST_ENDPOINTS
    if ($enableTestEndpoints -ne "true") {
        return @{ ok = $false; reason = "AP_ENABLE_TEST_ENDPOINTS_not_true" }
    }

    # Worker heartbeats. The smoke waits for the worker to actually
    # execute the approved tool call. If all workers are stale, the
    # smoke will time out waiting and is not a useful check.
    try {
        $workers = Invoke-RestMethod -Method GET -Uri "$Url/queue/workers" -TimeoutSec 10
    } catch {
        return @{ ok = $false; reason = "workers_unreachable: $($_.Exception.Message)" }
    }
    $active = @($workers.workers | Where-Object { $_.stale -eq $false })
    if ($active.Count -lt 1) {
        return @{ ok = $false; reason = "no_active_workers_heartbeats" }
    }

    return @{
        ok = $true
        reason = "prerequisites_ok"
        detail = @{ model = $modelName }
    }
}

$BaseUrl = if ($BaseUrl) { $BaseUrl } else { "http://localhost:8000" }
$BaseUrl = $BaseUrl.TrimEnd("/")
$DatabaseUrl = if ($DatabaseUrl) { $DatabaseUrl } else { "postgresql+psycopg://agent:agent@localhost:15432/agent_platform" }
if ($DatabaseUrl -match "@postgres:5432") {
    $DatabaseUrl = $DatabaseUrl -replace "@postgres:5432", "@localhost:15432"
}
$env:AP_TEST_POSTGRES_URL = $DatabaseUrl
$env:AP_DATABASE_URL = $DatabaseUrl
$env:API_BASE = $BaseUrl
$env:SKIP_EXTERNAL = if ($SkipExternal) { $SkipExternal } else { "0" }
$env:SMOKE_TMP_DIR = if ($env:SMOKE_TMP_DIR) { $env:SMOKE_TMP_DIR } else { Join-Path (Get-Location) ".tmp\smokes" }
New-Item -ItemType Directory -Force -Path $env:SMOKE_TMP_DIR | Out-Null

$pre = Test-Prerequisites -Url $BaseUrl
if (-not $pre.ok) {
    Write-SmokeLog "skipping permission resume smoke: $($pre.reason)"
    Write-SmokeResult -Result "skipped" -Reason $pre.reason
    exit 0
}

# Prerequisites are met. Delegate to the Bash smoke for the full
# end-to-end flow (session creation, permission seeding via raw DB,
# approve, wait for worker, verify file, verify events). The Bash
# implementation is the source of truth; the PowerShell wrapper is
# the prerequisite gate. If no Bash is installed, the user can still
# see the prerequisites were met and decide to install Bash for the
# full check.
$bash = Resolve-Bash
if (-not $bash) {
    Write-SmokeLog "prerequisites met, but full permission-resume smoke needs Bash; Bash optional on Windows"
    Write-SmokeResult -Result "skipped" -Reason "Bash_optional_full_permission_resume"
    exit 0
}

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$Script = Join-Path $RepoRoot "scripts\permission-resume-smoke.sh"
if (-not (Test-Path -LiteralPath $Script)) {
    Fail-Smoke "missing permission-resume-smoke.sh at $Script"
}

Write-SmokeLog "delegating to $Script via $bash"
$smokeTmpWin = ($env:SMOKE_TMP_DIR -replace '\\','/')
if ($bash -eq "wsl") {
    & wsl -e bash -c "cd '$($RepoRoot.Path -replace '\\','/')' && API_BASE='$BaseUrl' AP_TEST_POSTGRES_URL='$DatabaseUrl' AP_DATABASE_URL='$DatabaseUrl' SKIP_EXTERNAL='$env:SKIP_EXTERNAL' SMOKE_TMP_DIR='$smokeTmpWin' SMOKE_TMP_DIR_PY='$smokeTmpWin' bash scripts/permission-resume-smoke.sh"
} else {
    & $bash $Script
}
$code = $LASTEXITCODE
if ($code -ne 0) {
    Fail-Smoke "permission-resume bash smoke failed with exit $code"
}

Write-SmokeResult -Result "passed"
exit 0
