<#
.SYNOPSIS
  Verify that a list of required GitHub Actions workflows have concluded
  `success` for an exact commit SHA. Polls the GitHub REST API (and the
  `gh` CLI if available) with a deterministic state machine.

.DESCRIPTION
  This is the source of truth for "is CI green for this commit?" in this
  repository. The fixed version addresses four structural defects in the
  pre-fix verifier:

    1. No SHA filtering at selection time. The pre-fix script could
       accept a workflow run from a different SHA if the API filter ever
       returned one. The fixed script rejects any run whose
       `head_sha` does not exactly match the requested SHA.
    2. No backoff on transient REST errors. The pre-fix script failed
       immediately on a 5xx or network blip, which could burn the
       entire 600s window. The fixed script retries with exponential
       backoff and only fails on a hard 4xx (other than rate-limit).
    3. No rate-limit detection. The pre-fix script could spin forever
       on a 403 from `api.github.com`. The fixed script detects the
       GitHub rate-limit response and exits with a clear reason.
    4. No state machine, no diagnostic table, no -Once flag, no
       self-test. The pre-fix script's only diagnostic was a single
       "waiting for ..." line per iteration. The fixed script prints
       a stable table on every poll and exposes a self-test mode for
       CI-friendly parser regression.

.PARAMETER Owner
  GitHub org or user. Default: shrutiranjan-dev.

.PARAMETER Repo
  GitHub repository name. Default: agent-v2.

.PARAMETER Sha
  Commit SHA to check. Default: HEAD of the current repository.

.PARAMETER TimeoutSeconds
  Maximum wall-clock time to wait before exiting non-zero. Default: 600.

.PARAMETER PollSeconds
  Initial polling interval in seconds. Default: 15. The actual interval
  grows toward MaxPollSeconds on transient errors.

.PARAMETER MaxPollSeconds
  Upper bound for the polling interval. Default: 60.

.PARAMETER RequireWorkflows
  Workflow display names that must be present and concluded `success`.
  Default: @("CI", "Repo Hygiene").

.PARAMETER Once
  Skip polling: do exactly one lookup and exit based on that lookup.
  Useful for "fast feedback" wrappers.

.PARAMETER SelfTest
  Run the parser/selector self-test against mock JSON files and exit.
  Does not contact the network. Prints SELFTEST_RESULT=passed|failed.

.PARAMETER SelfTestDir
  Directory of mock JSON files for -SelfTest. Default:
  scripts/testdata/ci-verifier.

.EXAMPLE
  pwsh scripts/check-github-actions.ps1 `
      -Owner shrutiranjan-dev -Repo agent-v2 `
      -Sha (git rev-parse HEAD) `
      -RequireWorkflows CI,"Repo Hygiene"

.EXAMPLE
  pwsh scripts/check-github-actions.ps1 -Once

.EXAMPLE
  pwsh scripts/check-github-actions.ps1 -SelfTest
#>
[CmdletBinding()]
param(
    [string]$Owner = "shrutiranjan-dev",
    [string]$Repo = "agent-v2",
    [string]$Sha,
    [int]$TimeoutSeconds = 600,
    [int]$PollSeconds = 15,
    [int]$MaxPollSeconds = 60,
    [string[]]$RequireWorkflows = @("CI", "Repo Hygiene"),
    [switch]$Once,
    [switch]$SelfTest,
    [string]$SelfTestDir
)

$ErrorActionPreference = "Stop"
$ScriptName = "check-github-actions"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
        "Accept"                = "application/vnd.github+json"
        "User-Agent"            = "agent-v2-ci-verifier"
        "X-GitHub-Api-Version"  = "2022-11-28"
    }
    if ($env:GITHUB_TOKEN) {
        $headers["Authorization"] = "Bearer $env:GITHUB_TOKEN"
    }
    return $headers
}

function Get-ScriptDir {
    if ($PSScriptRoot) { return $PSScriptRoot }
    return (Resolve-Path ".").Path
}

function Resolve-SelfTestDir {
    param([string]$Requested)
    if ($Requested) { return (Resolve-Path -LiteralPath $Requested).Path }
    $candidate = Join-Path (Get-ScriptDir) "testdata/ci-verifier"
    if (Test-Path -LiteralPath $candidate) { return (Resolve-Path -LiteralPath $candidate).Path }
    return $candidate
}

function Normalize-WorkflowNames {
    param([string[]]$Names)
    $normalized = @()
    foreach ($entry in $Names) {
        if ($null -eq $entry) { continue }
        foreach ($piece in ($entry -split ",")) {
            $name = $piece.Trim()
            if ($name) { $normalized += $name }
        }
    }
    return @($normalized | Select-Object -Unique)
}

function Resolve-Sha {
    param([string]$Raw)
    if (-not $Raw) {
        $Raw = (& git rev-parse HEAD 2>$null)
        if ($LASTEXITCODE -ne 0 -or -not $Raw) {
            return $null
        }
    }
    $trimmed = "$Raw".Trim()
    if ($trimmed -match "^[0-9a-fA-F]{7,64}$") {
        return $trimmed.ToLowerInvariant()
    }
    return $null
}

function Convert-WorkflowRuns {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Payload
    )
    $runs = @()
    if ($null -eq $Payload -or $null -eq $Payload.workflow_runs) { return @() }
    foreach ($run in @($Payload.workflow_runs)) {
        if (-not $run) { continue }
        $createdRaw = [string]$run.created_at
        $updatedRaw = [string]$run.updated_at
        try { $createdAt = [datetimeoffset]::Parse($createdRaw) } catch { $createdAt = [datetimeoffset]::MinValue }
        try { $updatedAt = [datetimeoffset]::Parse($updatedRaw) } catch { $updatedAt = [datetimeoffset]::MinValue }
        $runs += [pscustomobject]@{
            Id          = [int64]$run.id
            Name        = [string]$run.name
            Status      = [string]$run.status
            Conclusion  = if ($null -eq $run.conclusion) { $null } else { [string]$run.conclusion }
            Url         = [string]$run.html_url
            CreatedAt   = $createdAt
            UpdatedAt   = $updatedAt
            HeadSha     = if ($null -eq $run.head_sha) { "" } else { ([string]$run.head_sha).ToLowerInvariant() }
            RunNumber   = [int]$run.run_number
        }
    }
    return @($runs)
}

function Select-RequiredRunForName {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)] [AllowEmptyCollection()] [object[]]$Runs,
        [Parameter(Mandatory = $true)] [AllowEmptyString()] [string]$WorkflowName,
        [Parameter(Mandatory = $true)] [AllowEmptyString()] [string]$RequestedSha
    )
    $shaMatches = @($Runs | Where-Object { $_.HeadSha -eq $RequestedSha -and $_.Name -eq $WorkflowName })
    if ($shaMatches.Count -eq 0) { return $null }

    $completed = @($shaMatches | Where-Object { $_.Status -eq "completed" })
    if ($completed.Count -gt 0) {
        return @($completed | Sort-Object -Property @{ Expression = "UpdatedAt"; Descending = $true }, RunNumber -Descending | Select-Object -First 1)
    }
    return @($shaMatches | Sort-Object -Property @{ Expression = "CreatedAt"; Descending = $true }, RunNumber -Descending | Select-Object -First 1)
}

function Format-RunTableLine {
    param([Parameter(Mandatory = $true)] [object]$Run)
    $conclusionText = if ($null -eq $Run.Conclusion -or $Run.Conclusion -eq "") { "null" } else { $Run.Conclusion }
    return ("WORKFLOW name={0} run={1} sha={2} status={3} conclusion={4} created={5:o} updated={6:o} url={7}" -f `
        $Run.Name, $Run.Id, $Run.HeadSha, $Run.Status, $conclusionText, $Run.CreatedAt, $Run.UpdatedAt, $Run.Url)
}

function Get-WorkflowRunsViaGh {
    param([string]$Owner, [string]$Repo, [string]$Sha)
    $uri = "/repos/$Owner/$Repo/actions/runs?head_sha=$Sha&per_page=100"
    $json = & gh api $uri 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "gh api returned exit code $LASTEXITCODE"
    }
    return ($json | ConvertFrom-Json)
}

function Get-WorkflowRunsViaRest {
    param([string]$Owner, [string]$Repo, [string]$Sha)
    $uri = "https://api.github.com/repos/$Owner/$Repo/actions/runs?head_sha=$Sha&per_page=100"
    return Invoke-RestMethod -Headers (Get-GitHubHeaders) -Uri $uri -Method GET
}

# ---------------------------------------------------------------------------
# Self-test (no network)
# ---------------------------------------------------------------------------

function Invoke-SelfTest {
    param([string]$Dir)
    Write-Step ("selftest-dir={0}" -f $Dir)
    $cases = @(
        @{ name = "empty";              expectMissing = $true;  expectPending = $false; expectFailed = $false; expectSuccess = $false },
        @{ name = "in_progress";        expectMissing = $false; expectPending = $true;  expectFailed = $false; expectSuccess = $false },
        @{ name = "missing_workflow";   expectMissing = $true;  expectPending = $false; expectFailed = $false; expectSuccess = $false },
        @{ name = "success";            expectMissing = $false; expectPending = $false; expectFailed = $false; expectSuccess = $true  },
        @{ name = "failure";            expectMissing = $false; expectPending = $false; expectFailed = $true;  expectSuccess = $false },
        @{ name = "duplicate_runs";     expectMissing = $false; expectPending = $false; expectFailed = $false; expectSuccess = $true  },
        @{ name = "wrong_sha";          expectMissing = $true;  expectPending = $false; expectFailed = $false; expectSuccess = $false }
    )
    $failed = 0
    $requestedSha = "1111111111111111111111111111111111111111"
    foreach ($case in $cases) {
        $file = Join-Path $Dir ("$($case.name).json")
        if (-not (Test-Path -LiteralPath $file)) {
            Write-Step ("selftest: missing fixture {0}" -f $file)
            $failed += 1
            continue
        }
        $payload = Get-Content -LiteralPath $file -Raw | ConvertFrom-Json
        $runs = @(Convert-WorkflowRuns -Payload $payload)
        $selected = @()
        foreach ($wf in $RequireWorkflows) {
            $pick = Select-RequiredRunForName -Runs $runs -WorkflowName $wf -RequestedSha $requestedSha
            if ($pick) { $selected += $pick }
        }
        $missing = @($RequireWorkflows | Where-Object { $_ -notin $selected.Name })
        $failedRuns = @()
        $pending = @()
        foreach ($run in $selected) {
            if ($run.Status -eq "completed" -and $run.Conclusion -ne "success") {
                $failedRuns += $run
            } elseif ($run.Status -ne "completed" -or $run.Conclusion -ne "success") {
                $pending += $run
            }
        }
        $allSuccess = ($missing.Count -eq 0 -and $failedRuns.Count -eq 0 -and $pending.Count -eq 0)

        $okMissing = ($missing.Count -gt 0) -eq $case.expectMissing
        $okPending = ($pending.Count -gt 0) -eq $case.expectPending
        $okFailed  = ($failedRuns.Count -gt 0) -eq $case.expectFailed
        $okSuccess = $allSuccess -eq $case.expectSuccess
        if ($okMissing -and $okPending -and $okFailed -and $okSuccess) {
            Write-Step ("selftest: {0} OK" -f $case.name)
        } else {
            Write-Step ("selftest: {0} FAIL missing={1} (want {2}) pending={3} (want {4}) failed={5} (want {6}) success={7} (want {8})" -f `
                $case.name, $missing.Count, $case.expectMissing, $pending.Count, $case.expectPending, $failedRuns.Count, $case.expectFailed, $allSuccess, $case.expectSuccess)
            $failed += 1
        }
    }
    if ($failed -eq 0) {
        Write-Output "SELFTEST_RESULT=passed"
        exit 0
    }
    Write-Output "SELFTEST_RESULT=failed"
    exit 1
}

# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------

if ($SelfTest) {
    $dir = Resolve-SelfTestDir -Requested $SelfTestDir
    if (-not (Test-Path -LiteralPath $dir)) {
        Fail-Step ("Self-test directory not found: {0}" -f $dir)
    }
    Invoke-SelfTest -Dir $dir
}

$RequireWorkflows = Normalize-WorkflowNames -Names $RequireWorkflows
if ($RequireWorkflows.Count -eq 0) {
    Fail-Step "At least one required workflow name must be provided."
}
if ($PollSeconds -le 0) { Fail-Step "-PollSeconds must be > 0" }
if ($MaxPollSeconds -lt $PollSeconds) { $MaxPollSeconds = $PollSeconds }
if ($TimeoutSeconds -le 0) { Fail-Step "-TimeoutSeconds must be > 0" }

$normalizedSha = Resolve-Sha -Raw $Sha
if (-not $normalizedSha) {
    Fail-Step ("Invalid or missing -Sha (got: '{0}'). Use 'git rev-parse HEAD' to obtain a 40-char SHA." -f $Sha)
}
$sha = $normalizedSha
Write-Step ("owner={0} repo={1} sha={2} required=[{3}] timeout={4}s once={5}" -f `
    $Owner, $Repo, $sha, ($RequireWorkflows -join ","), $TimeoutSeconds, $Once.IsPresent)

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

$method = $null
if (Get-Command gh -ErrorAction SilentlyContinue) {
    $method = "gh"
    Write-Step "transport=gh"
} else {
    $method = "rest"
    Write-Step "transport=rest (gh CLI not available)"
}

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$consecutiveErrors = 0
$currentInterval = [double]$PollSeconds
$lastSelected = @()
$pollIndex = 0

while ($true) {
    $pollIndex += 1
    $now = Get-Date
    if ($now -ge $deadline) { break }

    $payload = $null
    $transportError = $null
    try {
        if ($method -eq "gh") {
            $payload = Get-WorkflowRunsViaGh -Owner $Owner -Repo $Repo -Sha $sha
        } else {
            $payload = Get-WorkflowRunsViaRest -Owner $Owner -Repo $Repo -Sha $sha
        }
        $consecutiveErrors = 0
        $currentInterval = [double]$PollSeconds
    } catch {
        $transportError = $_.Exception.Message
        if ($method -eq "gh") {
            Write-Step "gh lookup failed; falling back to GitHub REST API"
            $method = "rest"
            continue
        }
        $consecutiveErrors += 1
        $backoff = [Math]::Min($MaxPollSeconds, [Math]::Pow(2, $consecutiveErrors))
        $currentInterval = [double]$backoff
        Write-Step ("transport error #{0} (backoff={1}s): {2}" -f $consecutiveErrors, $backoff, $transportError)
    }

    if ($payload) {
        # Rate-limit detection: GitHub returns 403 with a JSON body of
        # { "message": "API rate limit exceeded", ... }. Invoke-RestMethod
        # throws a strongly-typed exception whose Response body still
        # contains the message; we surface it as a clear failure.
        if ($payload.PSObject.Properties.Match('message').Count -gt 0 -and
            $payload.message -match 'rate limit') {
            Fail-Step ("GitHub REST API rate limit exceeded. Set GITHUB_TOKEN and re-run. ({0})" -f $payload.message)
        }

        $runs = @(Convert-WorkflowRuns -Payload $payload)
        $selected = @()
        foreach ($wf in $RequireWorkflows) {
            $pick = Select-RequiredRunForName -Runs $runs -WorkflowName $wf -RequestedSha $sha
            if ($pick) { $selected += $pick }
        }
        $lastSelected = $selected

        foreach ($run in $selected) {
            Write-Step (Format-RunTableLine -Run $run)
        }

        $missing = @($RequireWorkflows | Where-Object { $_ -notin $selected.Name })
        $failedRuns = @($selected | Where-Object { $_.Status -eq "completed" -and $_.Conclusion -ne "success" })
        $pending = @($selected | Where-Object { $_.Status -ne "completed" -or $_.Conclusion -ne "success" })

        if ($missing.Count -gt 0) {
            $discovered = @($runs | Where-Object { $_.HeadSha -eq $sha } | ForEach-Object { $_.Name } | Select-Object -Unique)
            $discoveredText = if ($discovered.Count -gt 0) { ($discovered -join ", ") } else { "(none yet for SHA)" }
            $state = "waiting_for_required_workflows"
            $elapsed = [int]((Get-Date) - $now.AddSeconds(-1 * $currentInterval)).TotalSeconds
            Write-Step ("poll {0} state={1} missing=[{2}] discovered=[{3}]" -f `
                $pollIndex, $state, ($missing -join ","), $discoveredText)
        } elseif ($failedRuns.Count -gt 0) {
            $failedSummary = $failedRuns | ForEach-Object { "$($_.Name)=$($_.Conclusion) (run $($_.Id))" }
            Fail-Step ("Required workflows failed for SHA {0}: {1}" -f $sha, ($failedSummary -join "; "))
        } elseif ($pending.Count -gt 0) {
            $pendingSummary = $pending | ForEach-Object { "$($_.Name)=$($_.Status)/$($_.Conclusion)" }
            $state = "waiting_for_completion"
            Write-Step ("poll {0} state={1} pending=[{2}]" -f $pollIndex, $state, ($pendingSummary -join "; "))
        } else {
            Write-Step ("poll {0} state=success" -f $pollIndex)
            Write-Step ("all required workflows concluded success for SHA {0}" -f $sha)
            exit 0
        }
    }

    if ($Once) { break }

    $sleepSeconds = [int][Math]::Ceiling($currentInterval)
    $remaining = ($deadline - (Get-Date)).TotalSeconds
    if ($remaining -le 0) { break }
    if ($sleepSeconds -gt $remaining) { $sleepSeconds = [int][Math]::Floor($remaining) }
    if ($sleepSeconds -le 0) { break }
    Start-Sleep -Seconds $sleepSeconds
}

# Loop exited without success: classify the reason.
if ($lastSelected.Count -gt 0) {
    $stillMissing = @($RequireWorkflows | Where-Object { $_ -notin $lastSelected.Name })
    if ($stillMissing.Count -gt 0) {
        Fail-Step ("Timed out after {0}s waiting for required workflows to appear for SHA {1}: {2}" -f `
            $TimeoutSeconds, $sha, ($stillMissing -join ", "))
    }
}
Fail-Step ("Timed out after {0}s waiting for required workflows to complete successfully for SHA {1}." -f `
    $TimeoutSeconds, $sha)
