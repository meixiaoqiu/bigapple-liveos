param(
    [Parameter(Mandatory=$true)]
    [string]$LogFile,

    [int]$TailLines = 500,

    [int]$TimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$taskFile = Join-Path $scriptDir "tasks\test-log-triage.md"
$runner = Join-Path $scriptDir "Invoke-CodeBuddyTask.ps1"

& $runner -TaskFile $taskFile -LogFile $LogFile -TailLines $TailLines -TimeoutSeconds $TimeoutSeconds
exit $LASTEXITCODE
