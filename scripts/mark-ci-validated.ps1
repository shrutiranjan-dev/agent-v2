param(
    [string]$Owner = "shrutiranjan-dev",
    [string]$Repo = "agent-v2",
    [string]$Sha,
    [int]$TimeoutSeconds = 600,
    [int]$PollSeconds = 15,
    [string[]]$RequireWorkflows = @("CI", "Repo Hygiene")
)

$ErrorActionPreference = "Stop"
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

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$checkScript = Join-Path $PSScriptRoot "check-github-actions.ps1"
if (-not (Test-Path -LiteralPath $checkScript)) {
    Fail-Step "Missing verifier script at $checkScript"
}

& $checkScript -Owner $Owner -Repo $Repo -Sha $Sha -TimeoutSeconds $TimeoutSeconds -PollSeconds $PollSeconds -RequireWorkflows $RequireWorkflows
if ($LASTEXITCODE -ne 0) {
    Fail-Step "CI status was not proven green; refusing to modify docs."
}

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
