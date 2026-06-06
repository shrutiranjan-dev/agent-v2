param(
    [string]$BaseUrl = $env:AP_BACKEND_URL
)

$ErrorActionPreference = "Stop"

$ScriptName = "real-mcp-smoke"

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
    Write-SmokeLog "SKIP: real-mcp smoke requires Git Bash, WSL, or a Bash-on-Windows shell. Install Git for Windows or run from WSL."
    exit 0
}

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$Script = Join-Path $RepoRoot "scripts\real-mcp-smoke.sh"
if (-not (Test-Path -LiteralPath $Script)) {
    Fail-Smoke "missing real-mcp-smoke.sh at $Script"
}

$env:BACKEND_URL = if ($BaseUrl) { $BaseUrl } else { "http://localhost:8000" }
$env:AP_BACKEND_URL = $env:BACKEND_URL
$env:SKIP_REAL_MCP_IF_SDK_MISSING = if ($env:SKIP_REAL_MCP_IF_SDK_MISSING) { $env:SKIP_REAL_MCP_IF_SDK_MISSING } else { "0" }
$env:SKIP_RUNTIME_EXECUTE_IF_TEST_ENDPOINT_DISABLED = if ($env:SKIP_RUNTIME_EXECUTE_IF_TEST_ENDPOINT_DISABLED) { $env:SKIP_RUNTIME_EXECUTE_IF_TEST_ENDPOINT_DISABLED } else { "1" }

Write-SmokeLog "delegating to $Script via $bash"
$args = @()
if ($bash -eq "wsl") {
    $args = @("bash", "scripts/real-mcp-smoke.sh")
    & wsl -e bash -c "cd '$($RepoRoot.Path -replace '\\','/')' && BACKEND_URL='$env:BACKEND_URL' AP_BACKEND_URL='$env:AP_BACKEND_URL' SKIP_REAL_MCP_IF_SDK_MISSING='$env:SKIP_REAL_MCP_IF_SDK_MISSING' SKIP_RUNTIME_EXECUTE_IF_TEST_ENDPOINT_DISABLED='$env:SKIP_RUNTIME_EXECUTE_IF_TEST_ENDPOINT_DISABLED' bash scripts/real-mcp-smoke.sh"
} else {
    & $bash $Script
}
if ($LASTEXITCODE -ne 0) {
    Fail-Smoke "real-mcp smoke failed with exit $LASTEXITCODE"
}

Write-SmokeLog "real-mcp smoke ok"
