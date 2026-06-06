param(
    [switch]$WithDocker,
    [switch]$WithSmokes,
    [switch]$SkipFrontend,
    [switch]$SkipTests,
    [string]$BaseUrl = "http://localhost:8000"
)

$ErrorActionPreference = "Stop"

$ScriptName = "validate-local"

# Counters for the final passed/failed/skipped summary. Required steps use
# `pass` / `fail`; optional steps that are explicitly turned off or that
# short-circuit because of a missing tool use `skip`. The script only exits
# non-zero on a real `fail` of a required step, never on a `skip`, and never
# on an optional step failure.
$script:StepsPassed = 0
$script:StepsFailed = 0
$script:StepsSkipped = 0
$script:RequiredStepsFailed = 0
$script:StepRecords = @()

function Write-Step {
    param([string]$Message)
    Write-Host "[$ScriptName] $Message"
}

function Record-Step {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [ValidateSet("required", "optional")]
        [string]$Category,
        [Parameter(Mandatory = $true)]
        [ValidateSet("pass", "fail", "skip")]
        [string]$Result,
        [string]$Detail = ""
    )
    $script:StepRecords += [pscustomobject]@{
        name = $Name
        category = $Category
        result = $Result
        detail = $Detail
    }
    switch ($Result) {
        "pass" { $script:StepsPassed += 1 }
        "fail" {
            $script:StepsFailed += 1
            if ($Category -eq "required") {
                $script:RequiredStepsFailed += 1
            }
        }
        "skip" { $script:StepsSkipped += 1 }
    }
}

function Fail-Step {
    param(
        [string]$Name = "step",
        [string]$Message
    )
    Record-Step -Name $Name -Category "required" -Result "fail" -Detail $Message
    Write-Error "[$ScriptName] FAIL: $Message"
    Write-Summary -ForceFailure
    exit 1
}

function Write-Summary {
    param([switch]$ForceFailure)
    Write-Step "---- validation summary ----"
    foreach ($record in $script:StepRecords) {
        $marker = switch ($record.result) {
            "pass" { "PASS" }
            "fail" { "FAIL" }
            "skip" { "SKIP" }
        }
        $line = "[$ScriptName] $marker $($record.name)"
        if ($record.category -eq "optional") {
            $line += " (optional)"
        }
        if ($record.detail) {
            $line += " - $($record.detail)"
        }
        Write-Host $line
    }
    Write-Step "summary: passed=$script:StepsPassed failed=$script:StepsFailed skipped=$script:StepsSkipped"
}

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location -LiteralPath $RepoRoot

$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    Fail-Step -Name "venv" -Message "project venv python is required at $Python. Run scripts\dev-up.ps1 or create a venv first."
}

$env:AP_BASE_URL = $BaseUrl
$env:AP_CLI_BASE_URL = $BaseUrl
$env:AP_CLI_WS_URL = ($BaseUrl -replace "^http", "ws")
$env:AP_CLI_TIMEOUT_SECONDS = "30"
$env:AP_BACKEND_URL = $BaseUrl

# Default AP_TEST_POSTGRES_URL to the docker compose Postgres URL when the
# caller did not supply one. This lets the migration / permission-resume
# smokes run out of the box; if Postgres is not actually up, the smoke will
# fail with a real network error (more honest than "missing env").
if (-not $env:AP_TEST_POSTGRES_URL -and -not $env:AP_DATABASE_URL) {
    $env:AP_TEST_POSTGRES_URL = "postgresql+psycopg://agent:agent@localhost:15432/agent_platform"
}

# --- Compile ----------------------------------------------------------------
$stepName = "compile backend/app"
Write-Step $stepName
& $Python -m compileall -q (Join-Path $RepoRoot "backend\app")
if ($LASTEXITCODE -ne 0) {
    Fail-Step -Name $stepName -Message "compileall failed"
}
Record-Step -Name $stepName -Category "required" -Result "pass"

# --- Ruff -------------------------------------------------------------------
$stepName = "ruff check"
Write-Step "$stepName backend/app backend/tests"
& $Python -m ruff check (Join-Path $RepoRoot "backend\app") (Join-Path $RepoRoot "backend\tests")
if ($LASTEXITCODE -ne 0) {
    Fail-Step -Name $stepName -Message "ruff check failed"
}
Record-Step -Name $stepName -Category "required" -Result "pass"

# --- Pytest -----------------------------------------------------------------
$stepName = "pytest backend/tests"
if (-not $SkipTests) {
    Write-Step $stepName
    # By default, use the host's TEMP/TMP (the path pytest discovers through
    # `tempdir`/tmp_path). Only redirect to a project-local subdir when the
    # host default is genuinely unwritable, which is rare on Windows. We test
    # the system default rather than the project subdir so the override only
    # triggers when the system default itself is broken.
    $systemTmp = [System.IO.Path]::GetTempPath()
    $systemTmpWritable = $false
    try {
        $systemProbe = Join-Path $systemTmp ("validate-local-probe-" + [Guid]::NewGuid().ToString("N") + ".tmp")
        [System.IO.File]::WriteAllText($systemProbe, "ok")
        Remove-Item -LiteralPath $systemProbe -Force
        $systemTmpWritable = $true
    } catch {
        $systemTmpWritable = $false
    }
    if (-not $systemTmpWritable) {
        $projectTmp = Join-Path $RepoRoot ".tmp\pytest"
        New-Item -ItemType Directory -Force -Path $projectTmp | Out-Null
        $absoluteProjectTmp = [System.IO.Path]::GetFullPath($projectTmp)
        Write-Step "system TEMP unwritable; redirecting pytest temp to $absoluteProjectTmp"
        $env:TEMP = $absoluteProjectTmp
        $env:TMP = $absoluteProjectTmp
    } else {
        $env:TEMP = $systemTmp
        $env:TMP = $systemTmp
    }
    & $Python -m pytest (Join-Path $RepoRoot "backend\tests")
    if ($LASTEXITCODE -ne 0) {
        Fail-Step -Name $stepName -Message "pytest failed"
    }
    Record-Step -Name $stepName -Category "required" -Result "pass"
} else {
    Write-Step "$stepName skipped (-SkipTests)"
    Record-Step -Name $stepName -Category "required" -Result "skip" -Detail "SkipTests"
}

# --- Frontend build ---------------------------------------------------------
$stepName = "npm run build (frontend)"
if (-not $SkipFrontend) {
    Write-Step $stepName
    Push-Location (Join-Path $RepoRoot "frontend")
    try {
        npm.cmd run build | Out-Null
    } finally {
        Pop-Location
    }
    if ($LASTEXITCODE -ne 0) {
        Fail-Step -Name $stepName -Message "frontend build failed"
    }
    Record-Step -Name $stepName -Category "required" -Result "pass"
} else {
    Write-Step "$stepName skipped (-SkipFrontend)"
    Record-Step -Name $stepName -Category "required" -Result "skip" -Detail "SkipFrontend"
}

# --- Docker Compose config --------------------------------------------------
$stepName = "docker compose config"
Write-Step $stepName
$docker = Get-Command docker -ErrorAction SilentlyContinue
if ($docker) {
    & $docker.Source compose config | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Fail-Step -Name $stepName -Message "docker compose config failed"
    }
    Record-Step -Name $stepName -Category "required" -Result "pass"
} else {
    Write-Step "SKIP: docker not on PATH; skipping docker compose config"
    Record-Step -Name $stepName -Category "required" -Result "skip" -Detail "docker not on PATH"
}

# --- CLI/TUI smoke ----------------------------------------------------------
$stepName = "CLI/TUI smoke (scripts/cli-tui-smoke.ps1)"
Write-Step $stepName
& (Join-Path $RepoRoot "scripts\cli-tui-smoke.ps1")
if ($LASTEXITCODE -ne 0) {
    Fail-Step -Name $stepName -Message "CLI/TUI smoke failed"
}
Record-Step -Name $stepName -Category "required" -Result "pass"

# --- WithDocker -------------------------------------------------------------
$stepName = "WithDocker: docker compose ps"
if ($WithDocker) {
    Write-Step $stepName
    if ($docker) {
        & $docker.Source compose ps
        Record-Step -Name $stepName -Category "optional" -Result "pass"
    } else {
        Write-Step "SKIP: docker not on PATH"
        Record-Step -Name $stepName -Category "optional" -Result "skip" -Detail "docker not on PATH"
    }
    $stepName = "WithDocker: docker compose config backend backend-worker"
    Write-Step $stepName
    if ($docker) {
        & $docker.Source compose config backend backend-worker | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Fail-Step -Name $stepName -Message "docker compose config (services) failed"
        }
        Record-Step -Name $stepName -Category "optional" -Result "pass"
    } else {
        Record-Step -Name $stepName -Category "optional" -Result "skip" -Detail "docker not on PATH"
    }
} else {
    Write-Step "WithDocker not requested; skipping docker service checks"
    Record-Step -Name $stepName -Category "optional" -Result "skip" -Detail "WithDocker not requested"
    Record-Step -Name "WithDocker: docker compose config backend backend-worker" -Category "optional" -Result "skip" -Detail "WithDocker not requested"
}

# --- WithSmokes -------------------------------------------------------------
$stepName = "WithSmokes"
if ($WithSmokes) {
    Write-Step "WithSmokes: running available PowerShell-native smokes"
    $smokeScripts = @(
        "observability-smoke.ps1",
        "queue-worker-smoke.ps1",
        "codeintel-smoke.ps1",
        "lsp-smoke.ps1",
        "db-migration-smoke.ps1",
        "mcp-plugin-smoke.ps1",
        "real-mcp-smoke.ps1",
        "permission-resume-smoke.ps1"
    )
    $smokeFailures = @()
    $smokeSkips = @()
    $smokePasses = @()
    foreach ($smoke in $smokeScripts) {
        $smokeStep = "smoke: $smoke"
        $path = Join-Path $RepoRoot "scripts\$smoke"
        if (-not (Test-Path -LiteralPath $path)) {
            Write-Step "SKIP: $smoke not found"
            $smokeSkips += $smoke
            Record-Step -Name $smokeStep -Category "optional" -Result "skip" -Detail "script not found"
            continue
        }
        Write-Step "running $smoke"
        # Run each smoke in a fresh PowerShell process so the child script's
        # $ErrorActionPreference = "Stop" doesn't surface its terminating
        # Write-Error in the parent host. Capture stdout+stderr into a temp
        # file and read it back.
        $stdoutFile = Join-Path $env:TEMP "validate-local-$smoke-stdout.txt"
        $stderrFile = Join-Path $env:TEMP "validate-local-$smoke-stderr.txt"
        Remove-Item -LiteralPath $stdoutFile, $stderrFile -ErrorAction SilentlyContinue
        $quotedPath = '"' + $path + '"'
        $proc = Start-Process -FilePath "powershell.exe" `
            -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $quotedPath `
            -NoNewWindow `
            -Wait `
            -PassThru `
            -RedirectStandardOutput $stdoutFile `
            -RedirectStandardError $stderrFile
        $code = $proc.ExitCode
        $output = @()
        if (Test-Path -LiteralPath $stdoutFile) { $output += Get-Content -LiteralPath $stdoutFile }
        if (Test-Path -LiteralPath $stderrFile) { $output += Get-Content -LiteralPath $stderrFile }
        $skippedByMessage = $false
        foreach ($line in $output) {
            if ($line -match "Bash optional") {
                $skippedByMessage = $true
                break
            }
        }
        if ($code -ne 0) {
            Write-Step "--- $smoke output (exit $code) ---"
            $output | ForEach-Object { Write-Host $_ }
            Write-Step "--- end $smoke output ---"
            $smokeFailures += $smoke
            Record-Step -Name $smokeStep -Category "optional" -Result "fail" -Detail "exit=$code"
        } elseif ($skippedByMessage) {
            $smokeSkips += $smoke
            Record-Step -Name $smokeStep -Category "optional" -Result "skip" -Detail "Bash optional (no Bash on host)"
        } else {
            $smokePasses += $smoke
            Record-Step -Name $smokeStep -Category "optional" -Result "pass"
        }
        Remove-Item -LiteralPath $stdoutFile, $stderrFile -ErrorAction SilentlyContinue
    }
    Write-Step "smoke summary: passed=$($smokePasses.Count) failed=$($smokeFailures.Count) skipped=$($smokeSkips.Count)"
    if ($smokeFailures.Count -gt 0) {
        # Optional smoke failures do not fail the overall validation; they
        # are reported in the summary so the user can see what was attempted
        # and what did not pass. Required-step failures (compile, ruff,
        # pytest, frontend, docker config, CLI/TUI smoke) still exit 1.
        Write-Step "WARN: optional smoke failures do not fail validation: $($smokeFailures -join ', ')"
    }
} else {
    Write-Step "WithSmokes not requested; pass -WithSmokes to run available PowerShell smokes"
    foreach ($smoke in @(
        "observability-smoke.ps1",
        "queue-worker-smoke.ps1",
        "codeintel-smoke.ps1",
        "lsp-smoke.ps1",
        "db-migration-smoke.ps1",
        "mcp-plugin-smoke.ps1",
        "real-mcp-smoke.ps1",
        "permission-resume-smoke.ps1"
    )) {
        Record-Step -Name "smoke: $smoke" -Category "optional" -Result "skip" -Detail "WithSmokes not requested"
    }
}

Write-Summary
if ($script:RequiredStepsFailed -gt 0) {
    Write-Error "[$ScriptName] FAIL: $script:RequiredStepsFailed required step(s) failed"
    exit 1
}
Write-Step "ok"
