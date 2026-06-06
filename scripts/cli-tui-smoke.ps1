param(
  [string]$Python = ".\.venv\Scripts\python",
  [string]$BaseUrl = "http://localhost:8000"
)

$ErrorActionPreference = "Stop"
$env:AP_CLI_BASE_URL = $BaseUrl
$env:AP_CLI_WS_URL = $BaseUrl -replace "^http", "ws"

function Invoke-Cli {
  param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
  & $Python -m backend.app.cli.main @Args
}

Write-Host "[cli-tui-smoke] health"
Invoke-Cli health

Write-Host "[cli-tui-smoke] agents"
Invoke-Cli agents

Write-Host "[cli-tui-smoke] create session"
$title = "CLI smoke $(Get-Date -Format o)"
Invoke-Cli sessions create --title $title --agent build

Write-Host "[cli-tui-smoke] sessions list"
Invoke-Cli sessions list

Write-Host "[cli-tui-smoke] queue status"
Invoke-Cli queue status

Write-Host "[cli-tui-smoke] artifacts list"
Invoke-Cli artifacts list

Write-Host "[cli-tui-smoke] tui help"
& $Python -m backend.app.cli.main tui --help | Out-Host

Write-Host "[cli-tui-smoke] ok"
