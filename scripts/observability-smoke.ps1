param()

$ErrorActionPreference = "Stop"

function Write-SmokeLog {
    param([string]$Message)
    Write-Host "[observability-smoke] $Message"
}

function Fail-Smoke {
    param([string]$Message)
    Write-Error "[observability-smoke] FAIL: $Message"
    exit 2
}

function Invoke-Api {
    param([string]$Path)
    return Invoke-RestMethod -Method GET -Uri "$BackendUrl$Path"
}

function Assert-NoStorageInternals {
    param(
        [object]$Artifact,
        [string]$Context
    )
    if ($Artifact.PSObject.Properties.Name -contains "object_key") {
        Fail-Smoke "$Context exposed object_key"
    }
    if ($Artifact.PSObject.Properties.Name -contains "bucket") {
        Fail-Smoke "$Context exposed bucket"
    }
}

$BackendUrl = if ($env:AP_BACKEND_URL) { $env:AP_BACKEND_URL } else { "http://localhost:8000" }
$BackendUrl = $BackendUrl.TrimEnd("/")

Write-SmokeLog "checking backend health at $BackendUrl"
$health = Invoke-Api -Path "/health"
if ($health.status -ne "ok") {
    Fail-Smoke "backend health did not return status=ok"
}

Write-SmokeLog "checking worker endpoints"
$workers = Invoke-Api -Path "/workers"
if (-not ($workers.PSObject.Properties.Name -contains "workers")) {
    Fail-Smoke "/workers payload missing workers"
}
$workerStats = Invoke-Api -Path "/workers/stats"
foreach ($key in @("total", "active", "stale", "claimed_jobs_count", "completed_jobs_count", "failed_jobs_count")) {
    if (-not ($workerStats.stats.PSObject.Properties.Name -contains $key)) {
        Fail-Smoke "/workers/stats missing $key"
    }
}
Write-Host "WORKER_OBSERVABILITY=passed"

Write-SmokeLog "checking artifact list safety"
$artifacts = Invoke-Api -Path "/artifacts?limit=25"
if (-not ($artifacts.PSObject.Properties.Name -contains "artifacts")) {
    Fail-Smoke "/artifacts payload missing artifacts"
}
foreach ($artifact in @($artifacts.artifacts)) {
    Assert-NoStorageInternals -Artifact $artifact -Context "/artifacts"
}

$firstArtifact = @($artifacts.artifacts | Select-Object -First 1)
if ($firstArtifact.Count -gt 0) {
    Write-SmokeLog "checking artifact detail safety"
    $detail = Invoke-Api -Path "/artifacts/$($firstArtifact[0].id)"
    Assert-NoStorageInternals -Artifact $detail.artifact -Context "/artifacts/{id}"
    Write-Host "ARTIFACT_DETAIL=passed"
} else {
    Write-Host "ARTIFACT_DETAIL=skipped reason=no_artifacts"
}

Write-SmokeLog "checking session artifact endpoint"
$sessions = Invoke-Api -Path "/sessions"
$firstSession = @($sessions.sessions | Select-Object -First 1)
if ($firstSession.Count -gt 0) {
    $sessionArtifacts = Invoke-Api -Path "/sessions/$($firstSession[0].id)/artifacts"
    foreach ($artifact in @($sessionArtifacts.artifacts)) {
        Assert-NoStorageInternals -Artifact $artifact -Context "/sessions/{id}/artifacts"
    }
    Write-Host "SESSION_ARTIFACTS=passed"
} else {
    Write-Host "SESSION_ARTIFACTS=skipped reason=no_sessions"
}

Write-SmokeLog "observability smoke ok"
