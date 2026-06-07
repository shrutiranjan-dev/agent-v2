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
    Write-Host "SMOKE_RESULT=failed"
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
$batchPath = $fcPaths | Where-Object { $_ -eq "/file-changes/revert-batch" } | Select-Object -First 1
if (-not $batchPath) {
    Fail-Smoke "/file-changes/revert-batch path missing"
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

# -----------------------------------------------------------------------------
# Real E2E: only run when AP_ENABLE_TEST_ENDPOINTS is true.
# -----------------------------------------------------------------------------
$testEndpointsEnabled = $env:AP_ENABLE_TEST_ENDPOINTS
if ($testEndpointsEnabled -ne "true") {
    Write-SmokeLog "test endpoints disabled (set AP_ENABLE_TEST_ENDPOINTS=true to enable full smoke)"
    Write-Host "FILE_CHANGES=skipped_test_endpoint_disabled"
    Write-Host "SMOKE_RESULT=skipped"
    exit 0
}

# Look up the test endpoint in OpenAPI to confirm it's registered when enabled.
$testPath = $openapi.paths.PSObject.Properties | Where-Object { $_.Name -eq "/test-endpoints/file-change-write" } | Select-Object -ExpandProperty Name
if (-not $testPath) {
    Fail-Smoke "test-endpoints not registered despite AP_ENABLE_TEST_ENDPOINTS=true"
}

Write-SmokeLog "running real end-to-end file-change smoke (AP_ENABLE_TEST_ENDPOINTS=true)"

# Step 1: pick a unique relative path under the workspace.
$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddHHmmssfff")
$relPath = "smoke/file-change-smoke-$stamp.txt"
$original = "original-$stamp"
$modified = "modified-$stamp"

# Step 2: write the original content via the test endpoint (so a baseline
# exists; this is the pre-image the revert should restore).
$writeBody = @{
    path = $relPath
    content = $modified
    before_content = $original
    tool_name = "write.file"
} | ConvertTo-Json
$writeResp = Invoke-WebRequest -Method POST -Uri "$BaseUrl/test-endpoints/file-change-write" -UseBasicParsing -Body $writeBody -ContentType "application/json"
if ($writeResp.StatusCode -ne 200) {
    Fail-Smoke "test write endpoint returned status $($writeResp.StatusCode)"
}
$writeJson = ($writeResp.Content | ConvertFrom-Json)
$changeId = $writeJson.file_change_id
if (-not $changeId) {
    Fail-Smoke "test write response missing file_change_id"
}
Write-SmokeLog "captured file_change_id=$changeId for $relPath"

# Step 3: list the change to confirm it is visible via the regular API.
$listResp2 = Invoke-WebRequest -Method GET -Uri "$BaseUrl/file-changes?limit=200" -UseBasicParsing
$listJson2 = ($listResp2.Content | ConvertFrom-Json)
$found = $listJson2.file_changes | Where-Object { $_.id -eq $changeId } | Select-Object -First 1
if (-not $found) {
    Fail-Smoke "captured change_id $changeId not visible in /file-changes listing"
}
if ($found.revert_status -ne "not_reverted") {
    Fail-Smoke "expected revert_status=not_reverted, got $($found.revert_status)"
}
if (-not $found.revertible) {
    Fail-Smoke "expected revertible=true, got revertible=$($found.revertible)"
}
Write-SmokeLog "list ok: change visible revertible=true revert_status=not_reverted"

# Step 4: detail view should show the diff.
$detailResp = Invoke-WebRequest -Method GET -Uri "$BaseUrl/file-changes/$changeId`?include_content=true" -UseBasicParsing
if ($detailResp.StatusCode -ne 200) {
    Fail-Smoke "GET /file-changes/$changeId returned status $($detailResp.StatusCode)"
}
$detailJson = ($detailResp.Content | ConvertFrom-Json)
if (-not $detailJson.file_change.diff -or $detailJson.file_change.diff -notmatch "modified-$stamp") {
    Fail-Smoke "expected diff containing '$modified', got '$($detailJson.file_change.diff)'"
}
Write-SmokeLog "detail ok: diff present"

# Step 5: re-read the file on disk; it should match the modified content.
$workspaceRoot = $env:AP_WORKSPACE_ROOT
if (-not $workspaceRoot) {
    $workspaceRoot = "/workspace"
}
$onDiskPath = Join-Path $workspaceRoot ($relPath -replace "/", [IO.Path]::DirectorySeparatorChar)
$onDisk = Get-Content -LiteralPath $onDiskPath -Raw -ErrorAction SilentlyContinue
if ($onDisk -ne $modified) {
    Fail-Smoke "on-disk file content does not match modified; got '$onDisk' expected '$modified'"
}
Write-SmokeLog "on-disk file matches modified content"

# Step 6: revert without approval may yield 202 (waiting_permission) or 200.
# When the default requires_approval is true, we need to approve the
# permission request before reverting. When the operator opted out
# (AP_FILE_CHANGE_REVERT_REQUIRES_APPROVAL=false), the revert is
# immediate and returns 200.
$requiresApproval = $env:AP_FILE_CHANGE_REVERT_REQUIRES_APPROVAL
if (-not $requiresApproval) {
    $requiresApproval = "true"
}
$revertPayload = @{ force = $false } | ConvertTo-Json
$revertResp = Invoke-WebRequest -Method POST -Uri "$BaseUrl/file-changes/$changeId/revert" -UseBasicParsing -Body $revertPayload -ContentType "application/json" -ErrorAction SilentlyContinue -StatusCodeVariable revertStatus
if ($revertStatus -eq 202 -and $requiresApproval -eq "true") {
    $revertJson = ($revertResp.Content | ConvertFrom-Json)
    $permissionRequestId = $revertJson.detail.permission_request_id
    if (-not $permissionRequestId) {
        Fail-Smoke "202 response missing permission_request_id"
    }
    Write-SmokeLog "revert waiting_permission: permission_request_id=$permissionRequestId"
    $approveBody = @{ message = "smoke_approval" } | ConvertTo-Json
    $approveResp = Invoke-WebRequest -Method POST -Uri "$BaseUrl/permissions/$permissionRequestId/approve" -UseBasicParsing -Body $approveBody -ContentType "application/json" -ErrorAction SilentlyContinue -StatusCodeVariable approveStatus
    if ($approveStatus -ne 200) {
        Fail-Smoke "permission approve returned status $approveStatus"
    }
    Write-SmokeLog "permission approved"
    $revertPayload2 = @{ force = $false; permission_request_id = $permissionRequestId } | ConvertTo-Json
    $revertResp = Invoke-WebRequest -Method POST -Uri "$BaseUrl/file-changes/$changeId/revert" -UseBasicParsing -Body $revertPayload2 -ContentType "application/json" -ErrorAction SilentlyContinue -StatusCodeVariable revertStatus
}
if ($revertStatus -ne 200) {
    Fail-Smoke "POST /file-changes/$changeId/revert returned status $revertStatus"
}
$revertJson = ($revertResp.Content | ConvertFrom-Json)
if ($revertJson.file_change.revert_status -ne "reverted") {
    Fail-Smoke "expected revert_status=reverted, got $($revertJson.file_change.revert_status)"
}
Write-SmokeLog "revert ok: revert_status=reverted restore_source=$($revertJson.restore_source)"

# Step 7: re-read the file; it should be byte-for-byte the original.
$onDisk2 = Get-Content -LiteralPath $onDiskPath -Raw
if ($onDisk2 -ne $original) {
    Fail-Smoke "on-disk file content was not restored; got '$onDisk2' expected '$original'"
}
Write-SmokeLog "on-disk file restored byte-for-byte to original"

# Step 8: re-revert should yield 409.
$revertResp2 = Invoke-WebRequest -Method POST -Uri "$BaseUrl/file-changes/$changeId/revert" -UseBasicParsing -Body $revertPayload -ContentType "application/json" -ErrorAction SilentlyContinue -StatusCodeVariable revertStatus2
if ($revertStatus2 -ne 409) {
    Fail-Smoke "re-revert expected 409, got $revertStatus2"
}
Write-SmokeLog "re-revert correctly returned 409 already_reverted"

Write-Host "FILE_CHANGES=passed"
Write-Host "SMOKE_RESULT=passed"
Write-SmokeLog "file-change e2e smoke ok"
