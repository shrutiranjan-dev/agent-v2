param(
    [switch]$WithDocker,
    [switch]$WithSmokes,
    [switch]$SkipFrontend,
    [switch]$SkipTests,
    [string]$BaseUrl = "http://localhost:8000"
)

$ErrorActionPreference = "Stop"

$ScriptName = "validate-local"

function Write-Step {
    param([string]$Message)
    Write-Host "[$ScriptName] $Message"
}

function Fail-Step {
    param([string]$Message)
    Write-Error "[$ScriptName] FAIL: $Message"
    exit 1
}

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location -LiteralPath $RepoRoot

$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    Fail-Step "project venv python is required at $Python. Run scripts\dev-up.sh or create a venv first."
}

$env:AP_BASE_URL = $BaseUrl
$env:AP_CLI_BASE_URL = $BaseUrl
$env:AP_CLI_WS_URL = ($BaseUrl -replace "^http", "ws")
$env:AP_CLI_TIMEOUT_SECONDS = "30"
$env:AP_BACKEND_URL = $BaseUrl

# --- Compile ----------------------------------------------------------------
Write-Step "compileall backend/app"
& $Python -m compileall -q (Join-Path $RepoRoot "backend\app")
if ($LASTEXITCODE -ne 0) {
    Fail-Step "compileall failed"
}

# --- Ruff -------------------------------------------------------------------
Write-Step "ruff check backend/app backend/tests"
& $Python -m ruff check (Join-Path $RepoRoot "backend\app") (Join-Path $RepoRoot "backend\tests")
if ($LASTEXITCODE -ne 0) {
    Fail-Step "ruff check failed"
}

# --- Pytest -----------------------------------------------------------------
if (-not $SkipTests) {
    Write-Step "pytest backend/tests"
    $tmp = Join-Path $RepoRoot ".tmp\pytest"
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    $absoluteTmp = [System.IO.Path]::GetFullPath($tmp)
    # Only override TEMP/TMP if the host default is unwritable (rare on
    # Windows when the user profile is on a restricted share). Most local
    # runs use the system temp, which is what pytest expects.
    try {
        $testFile = Join-Path $absoluteTmp ".validate-local-write-test"
        [System.IO.File]::WriteAllText($testFile, "ok")
        Remove-Item -LiteralPath $testFile -Force
    } catch {
        Write-Step "using absolute temp override at $absoluteTmp"
        $env:TEMP = $absoluteTmp
        $env:TMP = $absoluteTmp
    }
    & $Python -m pytest (Join-Path $RepoRoot "backend\tests")
    if ($LASTEXITCODE -ne 0) {
        Fail-Step "pytest failed"
    }
}

# --- Frontend build ---------------------------------------------------------
if (-not $SkipFrontend) {
    Write-Step "npm run build (frontend)"
    Push-Location (Join-Path $RepoRoot "frontend")
    try {
        npm.cmd run build | Out-Null
    } finally {
        Pop-Location
    }
    if ($LASTEXITCODE -ne 0) {
        Fail-Step "frontend build failed"
    }
}

# --- Docker Compose config --------------------------------------------------
Write-Step "docker compose config"
$docker = Get-Command docker -ErrorAction SilentlyContinue
if ($docker) {
    & $docker.Source compose config | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Fail-Step "docker compose config failed"
    }
} else {
    Write-Step "SKIP: docker not on PATH; skipping docker compose config"
}

# --- CLI/TUI smoke ----------------------------------------------------------
Write-Step "CLI/TUI smoke (scripts/cli-tui-smoke.ps1)"
& (Join-Path $RepoRoot "scripts\cli-tui-smoke.ps1")
if ($LASTEXITCODE -ne 0) {
    Fail-Step "CLI/TUI smoke failed"
}

# --- WithDocker -------------------------------------------------------------
if ($WithDocker) {
    Write-Step "WithDocker: docker compose ps"
    if ($docker) {
        & $docker.Source compose ps
    } else {
        Write-Step "SKIP: docker not on PATH"
    }
    Write-Step "WithDocker: docker compose config backend backend-worker"
    if ($docker) {
        & $docker.Source compose config backend backend-worker | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Fail-Step "docker compose config (services) failed"
        }
    }
} else {
    Write-Step "WithDocker not requested; skipping docker service checks"
}

# --- WithSmokes -------------------------------------------------------------
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
    foreach ($smoke in $smokeScripts) {
        $path = Join-Path $RepoRoot "scripts\$smoke"
        if (-not (Test-Path -LiteralPath $path)) {
            Write-Step "SKIP: $smoke not found"
            $smokeSkips += $smoke
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
        if ($code -ne 0) {
            Write-Step "--- $smoke output (exit $code) ---"
            $output | ForEach-Object { Write-Host $_ }
            Write-Step "--- end $smoke output ---"
            $smokeFailures += $smoke
        } else {
            Write-Step "$smoke passed"
        }
        Remove-Item -LiteralPath $stdoutFile, $stderrFile -ErrorAction SilentlyContinue
    }
    Write-Step "smoke summary: passed=$($smokeScripts.Count - $smokeFailures.Count - $smokeSkips.Count) failed=$($smokeFailures.Count) skipped=$($smokeSkips.Count)"
    if ($smokeFailures.Count -gt 0) {
        Fail-Step "the following smokes failed: $($smokeFailures -join ', ')"
    }
} else {
    Write-Step "WithSmokes not requested; pass -WithSmokes to run available PowerShell smokes"
}

Write-Step "ok"
