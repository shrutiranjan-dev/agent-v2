param(
    [string]$BaseUrl = $(if ($env:AP_BASE_URL) { $env:AP_BASE_URL } elseif ($env:API_BASE) { $env:API_BASE } else { $env:AP_BACKEND_URL }),
    [string]$WorkspacePath = $env:TS_LSP_SMOKE_WORKSPACE_PATH,
    [string]$LspFile = $env:TS_LSP_SMOKE_FILE,
    [string]$StrictRealLsp = $env:STRICT_REAL_TS_LSP,
    [switch]$Real,
    [switch]$SkipRealIfMissing
)

$ErrorActionPreference = "Stop"

$ScriptName = "ts-lsp-smoke"

function Write-SmokeLog {
    param([string]$Message)
    Write-Host "[$ScriptName] $Message"
}

function Fail-Smoke {
    param([string]$Message)
    Write-Error "[$ScriptName] FAIL: $Message"
    Write-Host "TS_LSP=failed"
    Write-Host "TS_LSP_REASON=$Message"
    exit 2
}

$RealMode = [bool]$Real -or ($StrictRealLsp -eq "1")
if ($Real -and (-not $StrictRealLsp -or $StrictRealLsp -eq "")) {
    $StrictRealLsp = "1"
}

if (-not $BaseUrl) {
    $BaseUrl = "http://localhost:8000"
}
$BaseUrl = $BaseUrl.TrimEnd("/")

if (-not $WorkspacePath) {
    $WorkspacePath = "frontend/src"
}
if (-not $LspFile) {
    $LspFile = "frontend/src/App.tsx"
}
if (-not $StrictRealLsp) {
    $StrictRealLsp = "0"
}

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    Fail-Smoke "project venv python is required at $Python"
}

$SmokeTmpDir = if ($env:SMOKE_TMP_DIR) { $env:SMOKE_TMP_DIR } else { Join-Path $RepoRoot ".tmp\smokes" }
New-Item -ItemType Directory -Force -Path $SmokeTmpDir | Out-Null

Write-SmokeLog "checking backend health at $BaseUrl"
$health = Invoke-RestMethod -Method GET -Uri "$BaseUrl/health"
if ($health.status -ne "ok") {
    Fail-Smoke "backend health did not return status=ok"
}

if ($RealMode) {
    Write-SmokeLog "real-mode: verifying node and typescript-language-server availability"

    $prevPref = $ErrorActionPreference
    $ErrorActionPreference = "Continue"

    $nodeOutput = & node --version 2>&1
    $nodeExit = $LASTEXITCODE
    if ($nodeExit -ne 0) {
        if ($SkipRealIfMissing) {
            Write-Host "TS_LSP=skipped_ts_server_missing"
            Write-SmokeLog "ts-lsp smoke ok (skipped: node not found)"
            exit 0
        }
        Fail-Smoke "--Real mode requires 'node' on PATH"
    }
    Write-SmokeLog "node version: $nodeOutput"

    $npmOutput = & npm.cmd --version 2>&1
    $npmExit = $LASTEXITCODE
    if ($npmExit -ne 0) {
        if ($SkipRealIfMissing) {
            Write-Host "TS_LSP=skipped_ts_server_missing"
            Write-SmokeLog "ts-lsp smoke ok (skipped: npm not found)"
            exit 0
        }
        Fail-Smoke "--Real mode requires 'npm' on PATH"
    }
    Write-SmokeLog "npm version: $npmOutput"

    $tslsPath = Join-Path $RepoRoot "frontend\node_modules\.bin\typescript-language-server.cmd"
    if (-not (Test-Path -LiteralPath $tslsPath)) {
        if ($SkipRealIfMissing) {
            Write-Host "TS_LSP=skipped_ts_server_missing"
            Write-SmokeLog "ts-lsp smoke ok (skipped: typescript-language-server not found at $tslsPath)"
            exit 0
        }
        Fail-Smoke "--Real mode requires typescript-language-server in frontend/node_modules"
    }
    Write-SmokeLog "typescript-language-server found at $tslsPath"
    Write-Host "TS_LSP=checking"
    $ErrorActionPreference = $prevPref
}

$lspHealth = Invoke-RestMethod -Method GET -Uri "$BaseUrl/health/codeintel"
[System.IO.File]::WriteAllText((Join-Path $SmokeTmpDir "ts-lsp-health.json"), (ConvertTo-Json -InputObject $lspHealth -Depth 10))

$lsp = $lspHealth.lsp
if (-not $lsp) {
    Fail-Smoke "/health/codeintel did not include an lsp block"
}

$tsServer = $lsp.lsp_servers.typescript
if (-not $tsServer) {
    $tsServer = $lsp.lsp_servers.typescriptreact
}
Write-SmokeLog "ts lsp server status: mode=$($tsServer.mode) enabled=$($tsServer.enabled)"

if ($RealMode) {
    if (-not $tsServer.real_lsp_enabled) {
        Fail-Smoke "TS_LSP real mode but typescript LSP is not active"
    }
}

Write-SmokeLog "checking symbols for $LspFile via /code/symbols"

$symResp = Invoke-WebRequest -Method GET -Uri "$BaseUrl/code/symbols?file=$([uri]::EscapeDataString($LspFile))&limit=50" -UseBasicParsing
[System.IO.File]::WriteAllText((Join-Path $SmokeTmpDir "ts-lsp-symbols.json"), $symResp.Content)
$symPayload = ($symResp.Content | ConvertFrom-Json)
$symbols = $symPayload.symbols
$symSource = $symPayload.source
$symLanguage = $symPayload.language
$symLspServer = $symPayload.lsp_server

Write-SmokeLog "lsp symbols: count=$(@($symbols).Count) source=$symSource language=$symLanguage lsp_server=$symLspServer"

if ($RealMode) {
    if ($symSource -ne "real_lsp") {
        Fail-Smoke "TS_LSP real mode but /code/symbols source != real_lsp (source=$symSource reason=$($symPayload.fallback_reason))"
    }
    if ($symLspServer -notin @("typescript", "typescriptreact", "javascript", "javascriptreact")) {
        Fail-Smoke "TS_LSP real mode but lsp_server is not a TS/JS language (got $symLspServer)"
    }
    Write-Host "TS_LSP=passed"
} else {
    if ($symSource -ne "static_fallback") {
        Write-SmokeLog "TS LSP disabled but source=$symSource (non-static-fallback); still not a failure without --Real"
    }
    Write-Host "TS_LSP=disabled_static_fallback"
}

Write-SmokeLog "ts-lsp smoke ok"
