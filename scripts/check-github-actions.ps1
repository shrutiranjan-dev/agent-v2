param(
    [string]$Owner = "shrutiranjan-dev",
    [string]$Repo = "agent-v2",
    [string]$Sha,
    [int]$TimeoutSeconds = 600,
    [int]$PollSeconds = 15,
    [string[]]$RequireWorkflows = @("CI", "Repo Hygiene")
)

$ErrorActionPreference = "Stop"
$ScriptName = "check-github-actions"

function Write-Step {
    param([string]$Message)
    Write-Host "[$ScriptName] $Message"
}

function Fail-Step {
    param([string]$Message)
    Write-Error "[$ScriptName] FAIL: $Message"
    exit 1
}

function Get-GitHubHeaders {
    $headers = @{
        "Accept" = "application/vnd.github+json"
        "User-Agent" = "agent-v2-ci-verifier"
    }
    if ($env:GITHUB_TOKEN) {
        $headers["Authorization"] = "Bearer $env:GITHUB_TOKEN"
    }
    return $headers
}

function Normalize-WorkflowNames {
    param([string[]]$Names)

    $normalized = @()
    foreach ($entry in $Names) {
        if ($null -eq $entry) {
            continue
        }
        foreach ($piece in ($entry -split ",")) {
            $name = $piece.Trim()
            if ($name) {
                $normalized += $name
            }
        }
    }
    return $normalized
}

function Convert-WorkflowRuns {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Payload
    )

    $runs = @()
    $items = @($Payload.workflow_runs)
    foreach ($run in $items) {
        if (-not $run) {
            continue
        }
        $runs += [pscustomobject]@{
            Name       = [string]$run.name
            Status     = [string]$run.status
            Conclusion = if ($null -eq $run.conclusion) { $null } else { [string]$run.conclusion }
            Url        = [string]$run.html_url
            CreatedAt  = if ($run.created_at) { [datetimeoffset]::Parse([string]$run.created_at) } else { [datetimeoffset]::MinValue }
            HeadSha    = [string]$run.head_sha
        }
    }
    return @($runs)
}

function Get-WorkflowRunsViaGh {
    param(
        [string]$Owner,
        [string]$Repo,
        [string]$Sha
    )

    $json = & gh api "/repos/$Owner/$Repo/actions/runs?head_sha=$Sha&per_page=100"
    if ($LASTEXITCODE -ne 0) {
        throw "gh api returned exit code $LASTEXITCODE"
    }
    return $json | ConvertFrom-Json
}

function Get-WorkflowRunsViaRest {
    param(
        [string]$Owner,
        [string]$Repo,
        [string]$Sha
    )

    $uri = "https://api.github.com/repos/$Owner/$Repo/actions/runs?head_sha=$Sha&per_page=100"
    return Invoke-RestMethod -Headers (Get-GitHubHeaders) -Uri $uri -Method GET
}

function Select-LatestRequiredRuns {
    param(
        [AllowEmptyCollection()]
        [object[]]$Runs,
        [Parameter(Mandatory = $true)]
        [string[]]$RequireWorkflows
    )

    $selected = @()
    foreach ($workflowName in $RequireWorkflows) {
        $latest = $Runs |
            Where-Object { $_.Name -eq $workflowName } |
            Sort-Object CreatedAt -Descending |
            Select-Object -First 1
        if ($latest) {
            $selected += $latest
        }
    }
    return $selected
}

if (-not $Sha) {
    $Sha = (git rev-parse HEAD).Trim()
}
if (-not $Sha) {
    Fail-Step "Sha is required."
}
$RequireWorkflows = Normalize-WorkflowNames -Names $RequireWorkflows
if ($RequireWorkflows.Count -eq 0) {
    Fail-Step "At least one required workflow name must be provided."
}

$method = $null
if (Get-Command gh -ErrorAction SilentlyContinue) {
    $method = "gh"
    Write-Step "using GitHub CLI"
} else {
    $method = "rest"
    Write-Step "GitHub CLI unavailable; using GitHub REST API"
}

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$lastRequiredRuns = @()

while ((Get-Date) -lt $deadline) {
    try {
        $payload = if ($method -eq "gh") {
            Get-WorkflowRunsViaGh -Owner $Owner -Repo $Repo -Sha $Sha
        } else {
            Get-WorkflowRunsViaRest -Owner $Owner -Repo $Repo -Sha $Sha
        }
    } catch {
        if ($method -eq "gh") {
            Write-Step "gh lookup failed; falling back to GitHub REST API"
            $method = "rest"
            continue
        }
        Fail-Step "Unable to query GitHub Actions. Install 'gh' or allow GitHub REST API access. Error: $($_.Exception.Message)"
    }

    $allRuns = @(Convert-WorkflowRuns -Payload $payload)
    $lastRequiredRuns = Select-LatestRequiredRuns -Runs $allRuns -RequireWorkflows $RequireWorkflows

    foreach ($run in $lastRequiredRuns) {
        $conclusionText = if ($null -eq $run.Conclusion -or $run.Conclusion -eq "") { "null" } else { $run.Conclusion }
        Write-Host ("WORKFLOW name={0} status={1} conclusion={2} url={3}" -f $run.Name, $run.Status, $conclusionText, $run.Url)
    }

    $missing = @($RequireWorkflows | Where-Object { $_ -notin $lastRequiredRuns.Name })
    if ($missing.Count -gt 0) {
        Write-Step ("waiting for workflows to appear: {0}" -f ($missing -join ", "))
        Start-Sleep -Seconds $PollSeconds
        continue
    }

    $failed = @(
        $lastRequiredRuns | Where-Object {
            $_.Status -eq "completed" -and $_.Conclusion -ne "success"
        }
    )
    if ($failed.Count -gt 0) {
        $failedSummary = $failed | ForEach-Object { "$($_.Name)=$($_.Conclusion)" }
        Fail-Step ("Required workflows failed: {0}" -f ($failedSummary -join ", "))
    }

    $pending = @(
        $lastRequiredRuns | Where-Object {
            $_.Status -ne "completed" -or $_.Conclusion -ne "success"
        }
    )
    if ($pending.Count -eq 0) {
        Write-Step ("method={0}" -f $method)
        Write-Step "all required workflows succeeded"
        exit 0
    }

    Write-Step ("waiting for workflows to complete: {0}" -f (($pending | ForEach-Object { $_.Name }) -join ", "))
    Start-Sleep -Seconds $PollSeconds
}

$missingAtTimeout = @($RequireWorkflows | Where-Object { $_ -notin $lastRequiredRuns.Name })
if ($missingAtTimeout.Count -gt 0) {
    Fail-Step ("Timed out waiting for required workflows to appear: {0}" -f ($missingAtTimeout -join ", "))
}
Fail-Step "Timed out waiting for required workflows to complete successfully."
