param(
    [string]$BaseUrl = $(if ($env:AP_BASE_URL) { $env:AP_BASE_URL } elseif ($env:API_BASE) { $env:API_BASE } else { $env:AP_BACKEND_URL }),
    [string]$StrictRealLsp = $env:STRICT_REAL_MULTI_LSP,
    [switch]$RealGo,
    [switch]$RealRust,
    [switch]$RealJava,
    [switch]$SkipRealIfMissing
)

$ErrorActionPreference = "Stop"

$ScriptName = "multi-lsp-smoke"

function Write-SmokeLog {
    param([string]$Message)
    Write-Host "[$ScriptName] $Message"
}

function Fail-Smoke {
    param([string]$Message)
    Write-Error "[$ScriptName] FAIL: $Message"
    Write-Host "MULTI_LSP=failed"
    Write-Host "MULTI_LSP_REASON=$Message"
    exit 2
}

$RealMode = [bool]$RealGo -or [bool]$RealRust -or [bool]$RealJava -or ($StrictRealLsp -eq "1")

if (-not $BaseUrl) {
    $BaseUrl = "http://localhost:8000"
}
$BaseUrl = $BaseUrl.TrimEnd("/")

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")

Write-SmokeLog "checking backend health at $BaseUrl"
$health = Invoke-RestMethod -Method GET -Uri "$BaseUrl/health"
if ($health.status -ne "ok") {
    Fail-Smoke "backend health did not return status=ok"
}

$lspHealth = Invoke-RestMethod -Method GET -Uri "$BaseUrl/health/codeintel"

$servers = $lspHealth.lsp.lsp_servers
if (-not $servers) {
    Fail-Smoke "/health/codeintel did not include lsp_servers"
}

$expectedServers = @("python", "typescript", "go", "rust", "java", "clangd", "ruby", "php", "csharp", "kotlin", "lua")
foreach ($sid in $expectedServers) {
    if (-not $servers.$sid) {
        Fail-Smoke "Missing server in /health/codeintel: $sid"
    }
    $payload = $servers.$sid
    Write-SmokeLog "server=$sid mode=$($payload.mode) enabled=$($payload.enabled) command=$($payload.command)"
}

if ($RealGo) {
    $goServer = $servers.go
    $prevPref = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $goplsCheck = & gopls --version 2>&1
    $goplsExit = $LASTEXITCODE
    $ErrorActionPreference = $prevPref
    if ($goplsExit -ne 0) {
        if ($SkipRealIfMissing) {
            Write-Host "GO_LSP=skipped_gopls_missing"
            Write-SmokeLog "go real-mode skipped: gopls not on PATH"
        } else {
            Fail-Smoke "--RealGo requires gopls on PATH"
        }
    } elseif (-not $goServer.real_lsp_enabled) {
        Write-Host "GO_LSP=skipped_gopls_disabled"
        Write-SmokeLog "go real-mode skipped: gopls present but Go LSP is not active in config"
    } else {
        Write-Host "GO_LSP=passed"
    }
}

if ($RealRust) {
    $rustServer = $servers.rust
    $prevPref = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $rustAnaCheck = & rust-analyzer --version 2>&1
    $rustAnaExit = $LASTEXITCODE
    $ErrorActionPreference = $prevPref
    if ($rustAnaExit -ne 0) {
        if ($SkipRealIfMissing) {
            Write-Host "RUST_LSP=skipped_rust_analyzer_missing"
            Write-SmokeLog "rust real-mode skipped: rust-analyzer not on PATH"
        } else {
            Fail-Smoke "--RealRust requires rust-analyzer on PATH"
        }
    } elseif (-not $rustServer.real_lsp_enabled) {
        Write-Host "RUST_LSP=skipped_rust_analyzer_disabled"
        Write-SmokeLog "rust real-mode skipped: rust-analyzer present but Rust LSP is not active in config"
    } else {
        Write-Host "RUST_LSP=passed"
    }
}

if ($RealJava) {
    $javaServer = $servers.java
    $prevPref = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $jdtlsCheck = & jdtls --version 2>&1
    $jdtlsExit = $LASTEXITCODE
    $ErrorActionPreference = $prevPref
    if ($jdtlsExit -ne 0) {
        if ($SkipRealIfMissing) {
            Write-Host "JAVA_LSP=skipped_jdtls_missing"
            Write-SmokeLog "java real-mode skipped: jdtls not on PATH"
        } else {
            Fail-Smoke "--RealJava requires jdtls on PATH"
        }
    } elseif (-not $javaServer.real_lsp_enabled) {
        Write-Host "JAVA_LSP=skipped_jdtls_disabled"
        Write-SmokeLog "java real-mode skipped: jdtls present but Java LSP is not active in config"
    } else {
        Write-Host "JAVA_LSP=passed"
    }
}

$symResp = Invoke-WebRequest -Method GET -Uri "$BaseUrl/code/symbols?file=main.go&limit=10" -UseBasicParsing
$symPayload = ($symResp.Content | ConvertFrom-Json)
$goSymSource = $symPayload.source
$goSymServer = $symPayload.lsp_server
$goSymLang = $symPayload.language
$goSymReason = $symPayload.fallback_reason
Write-SmokeLog "go symbols: source=$goSymSource server=$goSymServer language=$goSymLang reason=$goSymReason"
if ($goSymSource -ne "static_fallback") {
    Fail-Smoke "go symbols source != static_fallback (got $goSymSource)"
}
if ($goSymServer -ne "none") {
    Fail-Smoke "go symbols lsp_server != none (got $goSymServer)"
}
if ($goSymReason -ne "go_lsp_disabled") {
    Fail-Smoke "go symbols fallback_reason != go_lsp_disabled (got $goSymReason)"
}

$rustResp = Invoke-WebRequest -Method GET -Uri "$BaseUrl/code/symbols?file=main.rs&limit=10" -UseBasicParsing
$rustPayload = ($rustResp.Content | ConvertFrom-Json)
$rustSymReason = $rustPayload.fallback_reason
Write-SmokeLog "rust symbols: source=$($rustPayload.source) server=$($rustPayload.lsp_server) reason=$rustSymReason"
if ($rustSymReason -ne "rust_lsp_disabled") {
    Fail-Smoke "rust symbols fallback_reason != rust_lsp_disabled (got $rustSymReason)"
}

if ($RealMode) {
    Write-Host "MULTI_LSP=registry_validated_real_partial"
} else {
    Write-Host "MULTI_LSP=registry_validated_static_fallback"
}
Write-SmokeLog "multi-lsp smoke ok"
