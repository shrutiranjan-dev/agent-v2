param(
    [string]$BaseUrl = $env:AP_BACKEND_URL,
    [string]$WorkspacePath = $env:CODEINTEL_SMOKE_WORKSPACE_PATH
)

$ErrorActionPreference = "Stop"

$ScriptName = "codeintel-smoke"

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

$ciHealth = Invoke-WebRequest -Method GET -Uri "$BaseUrl/health/codeintel" -UseBasicParsing
if ($ciHealth.StatusCode -eq 404) {
    Fail-Smoke "${BaseUrl}/health/codeintel returned 404; rebuild/restart backend before running this smoke."
}
if ($ciHealth.StatusCode -ne 200) {
    Fail-Smoke "codeintel health failed with HTTP $($ciHealth.StatusCode)"
}

Write-SmokeLog "indexing workspace $WorkspacePath"
$indexBody = @{ workspace_path = $WorkspacePath; force = $true } | ConvertTo-Json -Compress
try {
    $indexResponse = Invoke-WebRequest -Method POST -Uri "$BaseUrl/code/index" -UseBasicParsing -ContentType "application/json; charset=utf-8" -Body ([System.Text.Encoding]::UTF8.GetBytes($indexBody)) -TimeoutSec 120
    $indexContent = $indexResponse.Content.Trim([char]0).Trim()
} catch {
    $statusCode = $_.Exception.Response.StatusCode.value__
    $stream = $_.Exception.Response.GetResponseStream()
    $reader = New-Object System.IO.StreamReader($stream)
    $body = $reader.ReadToEnd()
    $reader.Close()
    Fail-Smoke ("code index failed with HTTP {0}: {1}" -f $statusCode, $body)
}
if (-not $indexContent) {
    Fail-Smoke "code index returned an empty response"
}
try {
    $indexData = $indexContent | ConvertFrom-Json
} catch {
    Fail-Smoke ("code index returned invalid JSON: {0}" -f $_.Exception.Message)
}
Write-SmokeLog ("parsed index: files_indexed={0} files_skipped={1}" -f $indexData.files_indexed, $indexData.files_skipped)
$indexFile = Join-Path $SmokeTmpDir "codeintel-index.json"
[System.IO.File]::WriteAllText($indexFile, $indexContent)
$filesIndexed = [int]$indexData.files_indexed
$filesSkipped = [int]$indexData.files_skipped
if ($filesIndexed -le 0 -and $filesSkipped -le 0) {
    Fail-Smoke ("code index did not process any files: {0}" -f $indexContent)
}
Write-SmokeLog ("code index: files_indexed={0} files_skipped={1}" -f $indexData.files_indexed, $indexData.files_skipped)

Write-SmokeLog "fetching code map, symbols, diagnostics"
$mapResp = Invoke-WebRequest -Method GET -Uri "$BaseUrl/code/map?depth=2&include_symbols=true" -UseBasicParsing
$mapContent = $mapResp.Content.Trim([char]0).Trim()
$mapFile = Join-Path $SmokeTmpDir "codeintel-map.json"
[System.IO.File]::WriteAllText($mapFile, $mapContent)
$mapData = ($mapContent | ConvertFrom-Json).code_map
$fileCount = [int]$mapData.file_count
if ($fileCount -le 0) {
    Fail-Smoke ("code map has no files: {0}" -f $mapContent)
}
Write-SmokeLog ("code map: files={0} symbols={1} languages={2}" -f $mapData.file_count, $mapData.symbol_count, ($mapData.languages -join ','))

$symResp = Invoke-WebRequest -Method GET -Uri "$BaseUrl/code/symbols?limit=20" -UseBasicParsing
[System.IO.File]::WriteAllText((Join-Path $SmokeTmpDir "codeintel-symbols.json"), $symResp.Content)

$diagResp = Invoke-WebRequest -Method GET -Uri "$BaseUrl/code/diagnostics?limit=20" -UseBasicParsing
[System.IO.File]::WriteAllText((Join-Path $SmokeTmpDir "codeintel-diagnostics.json"), $diagResp.Content)

Write-SmokeLog "verifying outside-workspace index attempt is rejected with 403"
$outsideBody = @{ workspace_path = ".."; force = $false } | ConvertTo-Json -Compress
try {
    $outsideResp = Invoke-WebRequest -Method POST -Uri "$BaseUrl/code/index" -UseBasicParsing -ContentType "application/json; charset=utf-8" -Body ([System.Text.Encoding]::UTF8.GetBytes($outsideBody))
    Fail-Smoke "expected 403 for outside-workspace index, got HTTP $($outsideResp.StatusCode)"
} catch {
    $statusCode = $_.Exception.Response.StatusCode.value__
    if ($statusCode -ne 403) {
        Fail-Smoke "expected 403 for outside-workspace index, got HTTP $statusCode"
    }
}

Write-SmokeLog "codeintel smoke ok"
