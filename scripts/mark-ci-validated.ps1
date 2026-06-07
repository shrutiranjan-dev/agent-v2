<#
.SYNOPSIS
  Run the GitHub Actions verifier, and only flip the docs from
  `REAL_LSP_CI_VALIDATED` -> `REAL_LSP_CI_VALIDATED` if the verifier exits 0.

.DESCRIPTION
  This script is the only sanctioned path to update the CI-validated
  markers in the docs. It refuses to edit any file unless the fixed
  check-github-actions.ps1 verifier proves all required workflows
  concluded `success` for the requested SHA on the public GitHub
  REST API.

  The verifier is the source of truth. This script is just a guarded
  doc-edit pass on top of it.

  After a successful verifier run, the script prints:

      CI_STATUS_VERIFIED=true

  and updates the configured docs in place. The marker is intentionally
  the string the rest of the docs / matrix already grep for, so that
  any future CI evidence flip in this script stays grep-stable.
#>
[CmdletBinding()]
param(
    [string]$Owner = "shrutiranjan-dev",
    [string]$Repo = "agent-v2",
    [string]$Sha,
    [int]$TimeoutSeconds = 600,
    [int]$PollSeconds = 15,
    [string[]]$RequireWorkflows = @("CI", "Repo Hygiene"),
    [switch]$Once
)

$ErrorActionPreference = "Continue"
$ScriptName = "mark-ci-validated"

function Write-Step {
    param([string]$Message)
    Write-Host "[$ScriptName] $Message"
}

function Fail-Step {
    param([string]$Message)
    Write-Error "[$ScriptName] FAIL: $Message"
    exit 1
}

if (-not $Sha) {
    $Sha = (git rev-parse HEAD).Trim()
}
if (-not $Sha) {
    Fail-Step "Sha is required."
}

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$checkScript = Join-Path $PSScriptRoot "check-github-actions.ps1"
if (-not (Test-Path -LiteralPath $checkScript)) {
    Fail-Step "Missing verifier script at $checkScript"
}

Write-Step ("verifier: owner={0} repo={1} sha={2} required=[{3}] timeout={4}s once={5}" -f `
    $Owner, $Repo, $Sha, ($RequireWorkflows -join ","), $TimeoutSeconds, $Once.IsPresent)

# Invoke the verifier via [System.Diagnostics.Process] so the child's
# non-zero exit and stderr stream do not interact with the parent's
# $ErrorActionPreference. The verifier's own Write-Error calls must
# not be allowed to terminate mark-ci-validated; we only care about
# the exit code.
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = (Get-Command powershell).Source
$argList = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $checkScript,
    "-Owner", $Owner,
    "-Repo", $Repo,
    "-Sha", $Sha,
    "-TimeoutSeconds", "$TimeoutSeconds",
    "-PollSeconds", "$PollSeconds"
)
if ($RequireWorkflows.Count -gt 0) {
    $argList += @("-RequireWorkflows", ($RequireWorkflows -join ","))
}
if ($Once) { $argList += "-Once" }
$psi.Arguments = [string]::Join(" ", ($argList | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }))
$psi.UseShellExecute = $false
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
$psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8

$proc = [System.Diagnostics.Process]::Start($psi)
$verifierOut = $proc.StandardOutput.ReadToEnd()
$verifierErr = $proc.StandardError.ReadToEnd()
$proc.WaitForExit()
$verifierExit = $proc.ExitCode
if ($verifierOut) { Write-Output $verifierOut }
if ($verifierErr) { [Console]::Error.WriteLine($verifierErr) }
Write-Step ("verifier exit={0}" -f $verifierExit)
if ($verifierExit -ne 0) {
    Fail-Step "CI status was not proven green; refusing to modify docs."
}

# At this point the verifier has exited 0 with the required workflows
# concluded success. The marker flip is the only thing left to do, and
# it is what the rest of the repo greps for.
$targets = @(
    "README.md",
    "docs/ci.md",
    "docs/opencode-study/flow-parity-matrix-verified.json",
    "docs/opencode-study/verified-gap-list.md",
    "docs/opencode-study/next-implementation-priorities.md",
    "docs/opencode-study/implementation-roadmap.md",
    "docs/opencode-study/polish-needed.md"
)

$updated = 0
foreach ($relative in $targets) {
    $path = Join-Path $RepoRoot $relative
    if (-not (Test-Path -LiteralPath $path)) {
        continue
    }
    $content = Get-Content -LiteralPath $path -Raw
    $next = $content -replace "REAL_LSP_CI_JOB_ADDED_PENDING_REMOTE_VALIDATION", "REAL_LSP_CI_VALIDATED"
    if ($next -ne $content) {
        [System.IO.File]::WriteAllText($path, $next, (New-Object System.Text.UTF8Encoding($false)))
        $updated += 1
        Write-Step "updated $relative"
    }
}

Write-Output "CI_STATUS_VERIFIED=true"
Write-Step ("updated_files={0}" -f $updated)
