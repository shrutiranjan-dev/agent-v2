param(
    [string]$BaseUrl = $env:AP_BACKEND_URL
)

$ErrorActionPreference = "Stop"

$ScriptName = "mcp-plugin-smoke"

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
    Write-SmokeLog "SKIP: mcp-plugin smoke requires Git Bash, WSL, or a Bash-on-Windows shell. Install Git for Windows or run from WSL."
    exit 0
}

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$Script = Join-Path $RepoRoot "scripts\mcp-plugin-smoke.sh"
if (-not (Test-Path -LiteralPath $Script)) {
    Fail-Smoke "missing mcp-plugin-smoke.sh at $Script"
}

$env:BACKEND_URL = if ($BaseUrl) { $BaseUrl } else { "http://localhost:8000" }
$env:AP_BACKEND_URL = $env:BACKEND_URL
$env:MCP_PLUGIN_SMOKE_MANIFEST_PATH = if ($env:MCP_PLUGIN_SMOKE_MANIFEST_PATH) { $env:MCP_PLUGIN_SMOKE_MANIFEST_PATH } else { (Join-Path $RepoRoot "plugins\.smoke-sample-plugin.json") }

Write-SmokeLog "delegating to $Script via $bash"
if ($bash -eq "wsl") {
    & wsl -e bash -c "cd '$($RepoRoot.Path -replace '\\','/')' && BACKEND_URL='$env:BACKEND_URL' AP_BACKEND_URL='$env:AP_BACKEND_URL' MCP_PLUGIN_SMOKE_MANIFEST_PATH='$env:MCP_PLUGIN_SMOKE_MANIFEST_PATH' bash scripts/mcp-plugin-smoke.sh"
} else {
    & $bash $Script
}
if ($LASTEXITCODE -ne 0) {
    Fail-Smoke "mcp-plugin smoke failed with exit $LASTEXITCODE"
}

Write-SmokeLog "mcp-plugin smoke ok"
