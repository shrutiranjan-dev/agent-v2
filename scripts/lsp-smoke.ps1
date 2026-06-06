param(
    [string]$BaseUrl = $env:AP_BACKEND_URL,
    [string]$WorkspacePath = $env:LSP_SMOKE_WORKSPACE_PATH,
    [string]$LspFile = $env:LSP_SMOKE_FILE,
    [string]$StrictRealLsp = $env:STRICT_REAL_LSP
)

$ErrorActionPreference = "Stop"

$ScriptName = "lsp-smoke"

function Write-SmokeLog {
    param([string]$Message)
    Write-Host "[$ScriptName] $Message"
}

function Fail-Smoke {
    param([string]$Message)
    Write-Error "[$ScriptName] FAIL: $Message"
    exit 2
}

if (-not $BaseUrl) {
    $BaseUrl = "http://localhost:8000"
}
$BaseUrl = $BaseUrl.TrimEnd("/")

if (-not $WorkspacePath) {
    $WorkspacePath = "backend/app/codeintel"
}
if (-not $LspFile) {
    $LspFile = "backend/app/codeintel/lsp_client.py"
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

$lspHealth = Invoke-RestMethod -Method GET -Uri "$BaseUrl/health/codeintel"
[System.IO.File]::WriteAllText((Join-Path $SmokeTmpDir "lsp-health.json"), (ConvertTo-Json -InputObject $lspHealth -Depth 10))

$lsp = $lspHealth.lsp
if (-not $lsp) {
    Fail-Smoke "/health/codeintel did not include an lsp block"
}
$mode = $lsp.mode
$real = [bool]$lsp.real_lsp_enabled
$status = $lsp.status
if ($status -ne "ok" -and $status -ne "degraded") {
    Fail-Smoke "unexpected LSP health status: $status"
}
if ($StrictRealLsp -eq "1" -and -not $real) {
    Fail-Smoke "STRICT_REAL_LSP=1 but real LSP is not active"
}
Write-SmokeLog "lsp health: mode=$mode real_lsp_enabled=$real command=$($lsp.command) reason=$($lsp.reason)"

Write-SmokeLog "indexing workspace $WorkspacePath for LSP queries"
$indexBody = @{ workspace_path = $WorkspacePath; force = $true } | ConvertTo-Json -Compress
try {
    Invoke-WebRequest -Method POST -Uri "$BaseUrl/code/index" -UseBasicParsing -ContentType "application/json; charset=utf-8" -Body ([System.Text.Encoding]::UTF8.GetBytes($indexBody)) -TimeoutSec 120 | Out-Null
} catch {
    $statusCode = $_.Exception.Response.StatusCode.value__
    $stream = $_.Exception.Response.GetResponseStream()
    $reader = New-Object System.IO.StreamReader($stream)
    $body = $reader.ReadToEnd()
    $reader.Close()
    Fail-Smoke ("lsp code index failed with HTTP {0}: {1}" -f $statusCode, $body)
}
[System.IO.File]::WriteAllText((Join-Path $SmokeTmpDir "lsp-index.json"), "")

$symResp = Invoke-WebRequest -Method GET -Uri "$BaseUrl/code/symbols?file=$([uri]::EscapeDataString($LspFile))&limit=50" -UseBasicParsing
[System.IO.File]::WriteAllText((Join-Path $SmokeTmpDir "lsp-symbols.json"), $symResp.Content)
$symbols = ($symResp.Content | ConvertFrom-Json).symbols
if (-not $symbols -or @($symbols).Count -le 0) {
    Fail-Smoke "LSP smoke did not return any symbols for the target file"
}
Write-SmokeLog "lsp symbols: count=$(@($symbols).Count) first=$($symbols[0].name)"

$diagResp = Invoke-WebRequest -Method GET -Uri "$BaseUrl/code/diagnostics?file=$([uri]::EscapeDataString($LspFile))&limit=50" -UseBasicParsing
[System.IO.File]::WriteAllText((Join-Path $SmokeTmpDir "lsp-diagnostics.json"), $diagResp.Content)
$diagnostics = ($diagResp.Content | ConvertFrom-Json).diagnostics
Write-SmokeLog "lsp diagnostics: count=$(@($diagnostics).Count)"

Write-SmokeLog "resolving LspClient definition"
$defUrl = "$BaseUrl/code/definition?name=LspClient"
$defResp = Invoke-WebRequest -Method GET -Uri $defUrl -UseBasicParsing
[System.IO.File]::WriteAllText((Join-Path $SmokeTmpDir "lsp-definition.json"), $defResp.Content)
$definition = ($defResp.Content | ConvertFrom-Json).definition
if (-not $definition) {
    Fail-Smoke "LSP smoke could not resolve a definition"
}
Write-SmokeLog "lsp definition: name=$($definition.name) file_path=$($definition.file_path) start_line=$($definition.start_line)"

Write-SmokeLog "lsp smoke ok"
