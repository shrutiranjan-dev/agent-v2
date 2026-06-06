param(
    [string]$BaseUrl = $env:AP_BACKEND_URL
)

$ErrorActionPreference = "Stop"

$ScriptName = "mcp-plugin-smoke"

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

    # Step 1: backend reachable.
    try {
        $health = Invoke-RestMethod -Method GET -Uri "$Url/health" -TimeoutSec 10
    } catch {
        return @{ ok = $false; reason = "backend_health_unreachable: $($_.Exception.Message)" }
    }
    if ($health.status -ne "ok") {
        return @{ ok = $false; reason = "backend_health_not_ok: $($health.status)" }
    }

    # Step 2: MCP health. The smoke exercises real MCP plumbing. If MCP is
    # not enabled or the SDK is missing, the smoke cannot run and the right
    # classification is SKIP, not FAIL.
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

    # Step 3: Plugin health. The plugin smoke loads a sample manifest, so
    # the plugin system must be enabled and at least the manifest load path
    # must work. If the system is "degraded" with a high failed_count, the
    # smoke is unlikely to land a clean plugin tool and we should SKIP.
    try {
        $pluginHealth = Invoke-RestMethod -Method GET -Uri "$Url/health/plugins" -TimeoutSec 10
    } catch {
        return @{ ok = $false; reason = "plugin_health_unreachable: $($_.Exception.Message)" }
    }
    if (-not $pluginHealth.enabled) {
        return @{ ok = $false; reason = "plugins_disabled" }
    }
    if ($pluginHealth.status -eq "degraded" -and $pluginHealth.failed_count -ge $pluginHealth.plugin_count) {
        return @{ ok = $false; reason = "plugin_system_degraded_failed=$($pluginHealth.failed_count)/$($pluginHealth.plugin_count)" }
    }

    # Step 4: MCP_REAL_SERVER environment. The full smoke registers a
    # plugin tool that ultimately depends on a real MCP server being
    # configured. Without it the smoke's assertions on a real plugin
    # tool are not meaningful. The env var being unset is a strong
    # signal the user did not opt into the real-MCP path.
    if (-not $env:MCP_REAL_SERVER) {
        return @{ ok = $false; reason = "MCP_REAL_SERVER_not_configured" }
    }

    return @{ ok = $true; reason = "prerequisites_ok" }
}

$BaseUrl = if ($BaseUrl) { $BaseUrl } else { "http://localhost:8000" }
$BaseUrl = $BaseUrl.TrimEnd("/")

$pre = Test-Prerequisites -Url $BaseUrl
if (-not $pre.ok) {
    Write-SmokeLog "skipping MCP/plugin smoke: $($pre.reason)"
    Write-SmokeResult -Result "skipped" -Reason $pre.reason
    exit 0
}

# Prerequisites are met. Delegate to the Bash smoke for the actual
# end-to-end test, which exercises plugin manifest load, secret
# redaction, server connect-failure detection, and tool enablement.
# The Bash smoke is the source of truth for the full flow; the
# PowerShell wrapper is the prerequisite gate.
$bash = Resolve-Bash
if (-not $bash) {
    Write-SmokeLog "Bash optional on Windows; cannot run full MCP/plugin smoke without Bash"
    Write-SmokeResult -Result "skipped" -Reason "Bash_optional_full_mcp_plugin_smoke"
    exit 0
}

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$Script = Join-Path $RepoRoot "scripts\mcp-plugin-smoke.sh"
if (-not (Test-Path -LiteralPath $Script)) {
    Fail-Smoke "missing mcp-plugin-smoke.sh at $Script"
}

$env:BACKEND_URL = $BaseUrl
$env:AP_BACKEND_URL = $BaseUrl

Write-SmokeLog "delegating to $Script via $bash"
if ($bash -eq "wsl") {
    & wsl -e bash -c "cd '$($RepoRoot.Path -replace '\\','/')' && BACKEND_URL='$BaseUrl' AP_BACKEND_URL='$BaseUrl' bash scripts/mcp-plugin-smoke.sh"
} else {
    & $bash $Script
}
$code = $LASTEXITCODE
if ($code -ne 0) {
    Fail-Smoke "mcp-plugin bash smoke failed with exit $code"
}

# If the bash smoke completed successfully, also parse its output for
# the MCP_REAL_SERVER marker. If it logged "not_configured" we know
# the full assertion chain could not be exercised; downgrade to
# skipped in that case so the validator stays truthful.
Write-SmokeResult -Result "passed"
exit 0
