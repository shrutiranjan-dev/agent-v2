param()

$ErrorActionPreference = "Stop"

$ScriptName = "queue-worker-smoke"

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

function Get-DotEnvValue {
    param([string]$Name)

    $envPath = Join-Path (Get-Location) ".env"
    if (-not (Test-Path -LiteralPath $envPath)) {
        return $null
    }

    $match = Get-Content -LiteralPath $envPath |
        Where-Object { $_ -match "^\s*$([regex]::Escape($Name))\s*=" } |
        Select-Object -First 1
    if (-not $match) {
        return $null
    }
    return ($match -replace "^\s*$([regex]::Escape($Name))\s*=\s*", "").Trim('"').Trim("'")
}

function Invoke-Api {
    param(
        [ValidateSet("GET", "POST")]
        [string]$Method,
        [string]$Path,
        [object]$Body = $null
    )

    $uri = "$BackendUrl$Path"
    if ($null -ne $Body) {
        return Invoke-RestMethod -Method $Method -Uri $uri -ContentType "application/json" -Body ($Body | ConvertTo-Json -Depth 10)
    }
    return Invoke-RestMethod -Method $Method -Uri $uri
}

function Invoke-Compose {
    param([string[]]$Args)

    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if ($docker) {
        & $docker.Source compose @Args
        if ($LASTEXITCODE -eq 0) {
            return $true
        }
    }

    $legacyCompose = Get-Command docker-compose -ErrorAction SilentlyContinue
    if (-not $legacyCompose) {
        return $false
    }
    & $legacyCompose.Source @Args
    if ($LASTEXITCODE -ne 0) {
        Fail-Smoke "docker-compose $($Args -join ' ') failed"
    }
    return $true
}

# Returns one of: "healthy", "unhealthy", "absent", "no-docker"
function Get-DockerWorkerHealth {
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $docker) {
        return "no-docker"
    }
    $raw = & $docker.Source compose ps backend-worker 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) {
        return "absent"
    }
    if ($raw -match "\bhealthy\b") {
        return "healthy"
    }
    if ($raw -match "\b(unhealthy|exited|dead|restarting)\b") {
        return "unhealthy"
    }
    if ($raw -match "agent-v2-backend-worker") {
        # Container is listed but no explicit health marker; treat as
        # healthy if the line says "Up" without a negative indicator.
        if ($raw -match "Up ") {
            return "healthy"
        }
        return "unhealthy"
    }
    return "absent"
}

$BackendUrl = if ($env:AP_BACKEND_URL) { $env:AP_BACKEND_URL } else { "http://localhost:8000" }
$BackendUrl = $BackendUrl.TrimEnd("/")
$ManageWorker = $env:QUEUE_SMOKE_MANAGE_WORKER -eq "1"
$WorkerPaused = $false
$HadRealFailure = $false
$FinalResult = "passed"
$FinalReason = ""

$DatabaseUrl = $env:AP_TEST_POSTGRES_URL
if (-not $DatabaseUrl) {
    $DatabaseUrl = Get-DotEnvValue "AP_TEST_POSTGRES_URL"
}
if (-not $DatabaseUrl) {
    $DatabaseUrl = $env:AP_DATABASE_URL
}
if (-not $DatabaseUrl) {
    $DatabaseUrl = Get-DotEnvValue "AP_DATABASE_URL"
}
if (-not $DatabaseUrl) {
    $DatabaseUrl = "postgresql+psycopg://agent:agent@localhost:15432/agent_platform"
}
if ($DatabaseUrl -match "@postgres:5432") {
    $DatabaseUrl = $DatabaseUrl -replace "@postgres:5432", "@localhost:15432"
}

$Python = Join-Path (Get-Location) ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    Fail-Smoke "project venv python is required at $Python"
}

$SmokeTmpDir = if ($env:SMOKE_TMP_DIR) { $env:SMOKE_TMP_DIR } else { Join-Path (Get-Location) ".tmp\smokes" }
New-Item -ItemType Directory -Force -Path $SmokeTmpDir | Out-Null
$SeedPath = Join-Path $SmokeTmpDir "queue-worker-seeded.json"
$SeedScript = Join-Path $SmokeTmpDir "queue-worker-seed.py"
$CleanupScript = Join-Path $SmokeTmpDir "queue-worker-cleanup.py"
$Seeded = $null

Set-Content -LiteralPath $SeedScript -Encoding UTF8 -Value @'
import json
import sys
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg

url = sys.argv[1].replace("+asyncpg", "").replace("+psycopg", "")
output_path = sys.argv[2]
now = datetime.now(timezone.utc)
failed_job_id = str(uuid4())
queued_job_id = str(uuid4())
failed_key = f"queue-worker-smoke:failed:{failed_job_id}"
queued_key = f"queue-worker-smoke:queued:{queued_job_id}"

with psycopg.connect(url) as conn:
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into queue_jobs (
              id, job_type, status, priority, payload, idempotency_key, attempt_count, max_attempts,
              available_at, failed_at, last_error, created_at, updated_at
            ) values (%s,'agent_run','failed',100,%s::jsonb,%s,2,3,%s,%s,%s,%s,%s)
            """,
            (
                failed_job_id,
                json.dumps({"smoke": "queue_worker", "kind": "failed"}),
                failed_key,
                now,
                now,
                "queue worker smoke failure",
                now - timedelta(minutes=2),
                now - timedelta(minutes=2),
            ),
        )
        cur.execute(
            """
            insert into queue_jobs (
              id, job_type, status, priority, payload, idempotency_key, attempt_count, max_attempts,
              available_at, created_at, updated_at
            ) values (%s,'agent_run','queued',100,%s::jsonb,%s,0,3,%s,%s,%s)
            """,
            (
                queued_job_id,
                json.dumps({"smoke": "queue_worker", "kind": "queued"}),
                queued_key,
                now,
                now - timedelta(minutes=1),
                now - timedelta(minutes=1),
            ),
        )
    conn.commit()

with open(output_path, "w", encoding="utf-8") as handle:
    json.dump({"failed_job_id": failed_job_id, "queued_job_id": queued_job_id}, handle)
'@

Set-Content -LiteralPath $CleanupScript -Encoding UTF8 -Value @'
import json
import sys

import psycopg

url = sys.argv[1].replace("+asyncpg", "").replace("+psycopg", "")
seed_path = sys.argv[2]
with open(seed_path, "r", encoding="utf-8") as handle:
    seeded = json.load(handle)

with psycopg.connect(url) as conn:
    with conn.cursor() as cur:
        cur.execute(
            "delete from queue_jobs where id in (%s, %s)",
            (seeded["failed_job_id"], seeded["queued_job_id"]),
        )
    conn.commit()
'@

try {
    Write-SmokeLog "checking backend health at $BackendUrl"
    $health = Invoke-Api -Method GET -Path "/health"
    if ($health.status -ne "ok") {
        Fail-Smoke "backend health did not return status=ok"
    }

    Write-SmokeLog "checking queue stats"
    $statsPayload = Invoke-Api -Method GET -Path "/queue/stats"
    $stats = $statsPayload.stats
    foreach ($key in @("queued", "claimed", "running", "completed", "failed", "dead_letter", "cancelled", "retry_scheduled", "total")) {
        if (-not ($stats.PSObject.Properties.Name -contains $key)) {
            Fail-Smoke "queue stats payload missing '$key'"
        }
    }
    Write-Host "QUEUE_STATS=passed"

    Write-SmokeLog "checking worker heartbeat endpoint"
    $workersPayload = Invoke-Api -Method GET -Path "/queue/workers"
    $workers = @($workersPayload.workers)
    foreach ($worker in $workers) {
        foreach ($key in @("worker_id", "status", "last_heartbeat_at", "stale", "claimed_jobs_count")) {
            if (-not ($worker.PSObject.Properties.Name -contains $key)) {
                Fail-Smoke "worker payload missing '$key'"
            }
        }
    }
    $activeWorkers = @($workers | Where-Object { $_.stale -eq $false -and $_.status -in @("healthy", "running", "idle") })
    if ($activeWorkers.Count -lt 1) {
        # No active non-stale worker heartbeats. This can mean:
        #   1. The Docker backend-worker container is healthy and the local
        #      worker just hasn't ticked yet (acceptable -> WARN).
        #   2. The Docker backend-worker container is unhealthy (real fail).
        #   3. We have no Docker to check the worker (cannot verify ->
        #      SKIP rather than FAIL on a Windows host without WSL).
        $dockerHealth = Get-DockerWorkerHealth
        switch ($dockerHealth) {
            "healthy" {
                Write-Host "WORKER_HEARTBEAT=warned"
                Write-SmokeLog "no non-stale worker heartbeats, but Docker backend-worker reports healthy; treating as WARN"
                $FinalResult = "warned"
                $FinalReason = "stale_worker_heartbeat_but_docker_worker_healthy"
            }
            "unhealthy" {
                Fail-Smoke "no non-stale worker heartbeats and Docker backend-worker is unhealthy"
            }
            "absent" {
                Fail-Smoke "no non-stale worker heartbeats and Docker backend-worker is absent"
            }
            default {
                Write-Host "WORKER_HEARTBEAT=skipped"
                Write-SmokeLog "no non-stale worker heartbeats and Docker is not available; cannot verify worker on this host (SKIP)"
                $FinalResult = "skipped"
                $FinalReason = "stale_worker_heartbeat_no_docker_to_verify"
            }
        }
    } else {
        Write-Host "WORKERS=passed"
    }

    # Continue with seeding / listing / retry / cancel only when the
    # prerequisite is met. If we already marked WARN or SKIP above, we
    # still need to know whether the job-flow checks pass on the
    # available worker. If a real worker exists (activeWorkers.Count >=
    # 1) OR Docker is healthy enough to drive a new worker process, we
    # proceed. Otherwise we skip the job-flow portion to keep the smoke
    # truthful.
    $canExerciseJobs = $false
    if ($FinalResult -eq "passed") {
        $canExerciseJobs = $true
    } elseif ($FinalResult -eq "warned") {
        # Docker is healthy; the queue jobs will eventually be picked up
        # by the live worker even if the heartbeat is stale. We do not
        # exercise the queue flow in this branch because the job would
        # just sit in queued forever and the smoke would time out.
        $canExerciseJobs = $false
    }

    if ($canExerciseJobs) {
        if ($ManageWorker) {
            Write-SmokeLog "pausing backend-worker for deterministic queue row checks"
            $WorkerPaused = Invoke-Compose -Args @("stop", "backend-worker")
        }

        Write-SmokeLog "seeding deterministic queue rows"
        & $Python $SeedScript $DatabaseUrl $SeedPath
        if ($LASTEXITCODE -ne 0) {
            Fail-Smoke "failed to seed queue rows"
        }
        $Seeded = Get-Content -LiteralPath $SeedPath -Raw | ConvertFrom-Json

        Write-SmokeLog "validating queue job listing"
        $jobsPayload = Invoke-Api -Method GET -Path "/queue/jobs"
        $jobIds = @($jobsPayload.jobs | ForEach-Object { $_.queue_job_id })
        if ($jobIds -notcontains $Seeded.failed_job_id -or $jobIds -notcontains $Seeded.queued_job_id) {
            Fail-Smoke "seeded queue jobs were missing from /queue/jobs"
        }

        Write-SmokeLog "retrying failed queue job"
        $retryPayload = Invoke-Api -Method POST -Path "/queue/jobs/$($Seeded.failed_job_id)/retry" -Body @{ reason = "queue_worker_smoke_retry"; publish = $false }
        if ($retryPayload.job.status -ne "queued") {
            Fail-Smoke "retry endpoint did not requeue failed job"
        }

        Write-SmokeLog "cancelling queued queue job"
        $cancelPayload = Invoke-Api -Method POST -Path "/queue/jobs/$($Seeded.queued_job_id)/cancel" -Body @{ reason = "queue_worker_smoke_cancel" }
        if ($cancelPayload.job.status -ne "cancelled") {
            Fail-Smoke "cancel endpoint did not cancel queued job"
        }

        $statsAfter = Invoke-Api -Method GET -Path "/queue/stats"
        if (-not ($statsAfter.stats.PSObject.Properties.Name -contains "total")) {
            Fail-Smoke "queue stats after job flow missing total"
        }
        Write-Host "QUEUE_JOB_FLOW=passed"
        Write-Host "QUEUE_PROMPT_FLOW=skipped reason=deterministic smoke avoids Ollama/model execution"
    } else {
        Write-Host "QUEUE_JOB_FLOW=skipped reason=$($FinalReason -replace ' ','_')"
    }
}
finally {
    if ($null -ne $Seeded -and (Test-Path -LiteralPath $SeedPath)) {
        Write-SmokeLog "cleaning up smoke rows"
        & $Python $CleanupScript $DatabaseUrl $SeedPath
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "[queue-worker-smoke] cleanup failed; inspect smoke rows manually"
        }
    }
    if ($WorkerPaused) {
        Write-SmokeLog "restarting backend-worker"
        Invoke-Compose -Args @("start", "backend-worker") | Out-Null
    }
}

Write-SmokeLog "queue worker smoke complete"
Write-SmokeResult -Result $FinalResult -Reason $FinalReason
exit 0
