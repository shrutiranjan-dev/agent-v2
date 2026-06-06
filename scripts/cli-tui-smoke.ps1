param(
  [string]$Python = ".\.venv\Scripts\python",
  [string]$BaseUrl = "http://localhost:8000",
  [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = "Stop"
$env:AP_CLI_BASE_URL = $BaseUrl
$env:AP_CLI_WS_URL = $BaseUrl -replace "^http", "ws"
$env:AP_CLI_TIMEOUT_SECONDS = "$TimeoutSeconds"

function Invoke-Cli {
  param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
  & $Python -m backend.app.cli.main @Args | Out-Null
  return $LASTEXITCODE
}

function Invoke-Cli-Capture {
  param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
  $output = & $Python -m backend.app.cli.main @Args
  return @{
    ExitCode = $LASTEXITCODE
    Output   = ($output -join "`n")
  }
}

function Assert-Exit {
  param([int]$Code, [string]$What)
  if ($Code -ne 0) {
    throw "[cli-tui-smoke] $What exited with code $Code"
  }
}

function Wait-ForBackend {
  param([int]$MaxAttempts = 30)
  for ($i = 0; $i -lt $MaxAttempts; $i++) {
    try {
      $null = Invoke-RestMethod -Method Get -Uri "$BaseUrl/health" -TimeoutSec 5
      return $true
    } catch {
      Start-Sleep -Seconds 1
    }
  }
  return $false
}

Write-Host "[cli-tui-smoke] checking backend availability"
if (-not (Wait-ForBackend)) {
  throw "[cli-tui-smoke] backend not reachable at $BaseUrl/health"
}

Write-Host "[cli-tui-smoke] health"
Assert-Exit (Invoke-Cli health) "health"

Write-Host "[cli-tui-smoke] agents"
Assert-Exit (Invoke-Cli agents) "agents"

Write-Host "[cli-tui-smoke] sessions create"
$title = "CLI smoke $(Get-Date -Format o)"
$createResult = Invoke-Cli-Capture sessions create --title $title --agent build
Assert-Exit $createResult.ExitCode "sessions create"
$createOutput = $createResult.Output
if ($createOutput -notmatch "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}") {
  throw "[cli-tui-smoke] could not extract session id from create output"
}
$sessionId = ($createOutput | Select-String -Pattern "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}").Matches[0].Value

Write-Host "[cli-tui-smoke] sessions list"
Assert-Exit (Invoke-Cli sessions list) "sessions list"

Write-Host "[cli-tui-smoke] events --session $sessionId"
Assert-Exit (Invoke-Cli events --session $sessionId) "events"

Write-Host "[cli-tui-smoke] permissions --session $sessionId"
Assert-Exit (Invoke-Cli permissions --session $sessionId) "permissions"

Write-Host "[cli-tui-smoke] questions --session $sessionId"
Assert-Exit (Invoke-Cli questions --session $sessionId) "questions"

Write-Host "[cli-tui-smoke] diff --session $sessionId (no diff expected)"
Assert-Exit (Invoke-Cli diff --session $sessionId) "diff"

Write-Host "[cli-tui-smoke] queue status"
Assert-Exit (Invoke-Cli queue status) "queue status"

Write-Host "[cli-tui-smoke] queue retry help"
Assert-Exit (Invoke-Cli queue retry --help) "queue retry help"

Write-Host "[cli-tui-smoke] queue show help"
Assert-Exit (Invoke-Cli queue show --help) "queue show help"

Write-Host "[cli-tui-smoke] artifacts list"
Assert-Exit (Invoke-Cli artifacts list) "artifacts list"

Write-Host "[cli-tui-smoke] tui help"
Assert-Exit (Invoke-Cli tui --help) "tui help"

Write-Host "[cli-tui-smoke] import smoke (no manual input required)"
$importSmoke = & $Python -c "from backend.app.cli.tui_app import run_tui; from backend.app.cli.tui_modals import PermissionModal, HumanInputModal, DiffModal; print('tui import smoke ok')"
if ($LASTEXITCODE -ne 0) {
  throw "[cli-tui-smoke] tui import smoke failed"
}
if ($importSmoke -notmatch "tui import smoke ok") {
  throw "[cli-tui-smoke] tui import smoke did not print expected marker"
}

Write-Host "[cli-tui-smoke] ok"
