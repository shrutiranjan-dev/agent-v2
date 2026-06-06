param(
    [string]$BaseUrl = $env:AP_BACKEND_URL
)

$ErrorActionPreference = "Stop"

$ScriptName = "real-mcp-smoke"

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

function Test-Prerequisites {
    param([string]$Url)

    try {
        $health = Invoke-RestMethod -Method GET -Uri "$Url/health" -TimeoutSec 10
    } catch {
        return @{ ok = $false; reason = "backend_health_unreachable: $($_.Exception.Message)" }
    }
    if ($health.status -ne "ok") {
        return @{ ok = $false; reason = "backend_health_not_ok: $($health.status)" }
    }

    try {
        $mcpHealth = Invoke-RestMethod -Method GET -Uri "$Url/health/mcp" -TimeoutSec 10
    } catch {
        return @{ ok = $false; reason = "mcp_health_unreachable: $($_.Exception.Message)" }
    }
    if (-not $mcpHealth.enabled) {
        return @{ ok = $false; reason = "mcp_disabled" }
    }
    if ($mcpHealth.sdk_status -eq "degraded" -or $mcpHealth.sdk_status -eq "missing") {
        return @{ ok = $false; reason = "mcp_sdk_status=$($mcpHealth.sdk_status)" }
    }
    if (-not $mcpHealth.stdio_transport) {
        return @{ ok = $false; reason = "mcp_stdio_transport_unavailable" }
    }

    return @{ ok = $true; reason = "prerequisites_ok" }
}

$BaseUrl = if ($BaseUrl) { $BaseUrl } else { "http://localhost:8000" }
$BaseUrl = $BaseUrl.TrimEnd("/")

$pre = Test-Prerequisites -Url $BaseUrl
if (-not $pre.ok) {
    Write-SmokeLog "skipping real MCP smoke: $($pre.reason)"
    Write-SmokeResult -Result "skipped" -Reason $pre.reason
    exit 0
}

$bash = Resolve-Bash
if (-not $bash) {
    Write-SmokeLog "Bash optional on Windows; cannot run full real MCP smoke without Bash"
    Write-SmokeResult -Result "skipped" -Reason "Bash_optional_full_real_mcp_smoke"
    exit 0
}

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$Script = Join-Path $RepoRoot "scripts\real-mcp-smoke.sh"
if (-not (Test-Path -LiteralPath $Script)) {
    Fail-Smoke "missing real-mcp-smoke.sh at $Script"
}

$env:BACKEND_URL = $BaseUrl
$env:AP_BACKEND_URL = $BaseUrl
$env:SKIP_REAL_MCP_IF_SDK_MISSING = if ($env:SKIP_REAL_MCP_IF_SDK_MISSING) { $env:SKIP_REAL_MCP_IF_SDK_MISSING } else { "0" }
$env:SKIP_RUNTIME_EXECUTE_IF_TEST_ENDPOINT_DISABLED = if ($env:SKIP_RUNTIME_EXECUTE_IF_TEST_ENDPOINT_DISABLED) { $env:SKIP_RUNTIME_EXECUTE_IF_TEST_ENDPOINT_DISABLED } else { "1" }

Write-SmokeLog "delegating to $Script via $bash"
if ($bash -eq "wsl") {
    & wsl -e bash -c "cd '$($RepoRoot.Path -replace '\\','/')' && BACKEND_URL='$env:BACKEND_URL' AP_BACKEND_URL='$env:AP_BACKEND_URL' SKIP_REAL_MCP_IF_SDK_MISSING='$env:SKIP_REAL_MCP_IF_SDK_MISSING' SKIP_RUNTIME_EXECUTE_IF_TEST_ENDPOINT_DISABLED='$env:SKIP_RUNTIME_EXECUTE_IF_TEST_ENDPOINT_DISABLED' bash scripts/real-mcp-smoke.sh"
} else {
    & $bash $Script
}
$code = $LASTEXITCODE
if ($code -ne 0) {
    Fail-Smoke "real-mcp bash smoke failed with exit $code"
}

Write-SmokeLog "real-mcp smoke ok"
Write-SmokeResult -Result "passed"
exit 0
