param(
    [string]$BaseUrl = $(if ($env:AP_BASE_URL) { $env:AP_BASE_URL } elseif ($env:API_BASE) { $env:API_BASE } else { $env:AP_BACKEND_URL })
)

$ErrorActionPreference = "Stop"

$ScriptName = "file-change-smoke"

function Write-SmokeLog {
    param([string]$Message)
    Write-Host "[$ScriptName] $Message"
}

function Fail-Smoke {
    param([string]$Message)
    Write-Error "[$ScriptName] FAIL: $Message"
    Write-Host "FILE_CHANGES=failed"
    Write-Host "FILE_CHANGES_REASON=$Message"
    exit 2
}

if (-not $BaseUrl) {
    $BaseUrl = "http://localhost:8000"
}
$BaseUrl = $BaseUrl.TrimEnd("/")

Write-SmokeLog "checking backend health at $BaseUrl"
$health = Invoke-RestMethod -Method GET -Uri "$BaseUrl/health"
if ($health.status -ne "ok") {
    Fail-Smoke "backend health did not return status=ok"
}

Write-SmokeLog "validating /file-changes route registration"
$openapi = Invoke-RestMethod -Method GET -Uri "$BaseUrl/openapi.json"
$fcPaths = $openapi.paths.PSObject.Properties | Where-Object { $_.Name -like "/file-changes*" } | Select-Object -ExpandProperty Name
if (-not $fcPaths -or $fcPaths.Count -lt 1) {
    Fail-Smoke "no /file-changes routes registered in OpenAPI"
}
foreach ($p in $fcPaths) {
    Write-SmokeLog "registered path: $p"
}

$listPath = $fcPaths | Where-Object { $_ -eq "/file-changes" } | Select-Object -First 1
if (-not $listPath) {
    Fail-Smoke "/file-changes list path missing"
}
$detailPath = $fcPaths | Where-Object { $_ -match "^/file-changes/\{[^/]+\}$" } | Select-Object -First 1
if (-not $detailPath) {
    Fail-Smoke "/file-changes/{id} detail path missing"
}
$revertPath = $fcPaths | Where-Object { $_ -match "^/file-changes/\{[^/]+\}/revert$" } | Select-Object -First 1
if (-not $revertPath) {
    Fail-Smoke "/file-changes/{id}/revert path missing"
}

Write-SmokeLog "exercising GET /file-changes (metadata-only)"
$listResp = Invoke-WebRequest -Method GET -Uri "$BaseUrl/file-changes?limit=1" -UseBasicParsing
if ($listResp.StatusCode -ne 200) {
    Fail-Smoke "GET /file-changes returned status $($listResp.StatusCode)"
}
$listJson = ($listResp.Content | ConvertFrom-Json)
if ($null -eq $listJson.file_changes) {
    Fail-Smoke "GET /file-changes response missing 'file_changes' key"
}
if ($null -eq $listJson.count) {
    Fail-Smoke "GET /file-changes response missing 'count' key"
}
Write-SmokeLog "list ok: count=$($listJson.count)"

Write-SmokeLog "exercising GET /file-changes/{id} with unknown id (expect 404)"
$unknown = Invoke-WebRequest -Method GET -Uri "$BaseUrl/file-changes/00000000-0000-0000-0000-000000000000" -UseBasicParsing -ErrorAction SilentlyContinue -StatusCodeVariable statusCode
if ($statusCode -ne 404) {
    Fail-Smoke "GET /file-changes/{unknown} expected 404 got $statusCode"
}

Write-SmokeLog "exercising POST /file-changes/{id}/revert with unknown id (expect 404)"
$revertBody = @{ force = $false } | ConvertTo-Json
$unknownRevert = Invoke-WebRequest -Method POST -Uri "$BaseUrl/file-changes/00000000-0000-0000-0000-000000000000/revert" -UseBasicParsing -Body $revertBody -ContentType "application/json" -ErrorAction SilentlyContinue -StatusCodeVariable statusRevert
if ($statusRevert -ne 404) {
    Fail-Smoke "POST /file-changes/{unknown}/revert expected 404 got $statusRevert"
}

Write-Host "FILE_CHANGES=endpoint_validated"
Write-SmokeLog "file-change smoke ok"
