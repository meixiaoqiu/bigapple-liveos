param(
    [int]$MaxInputChars = 90000,
    [int]$MaxReportOutputChars = 12000
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$taskFile = Join-Path $scriptDir "tasks\diff-review.md"
$runner = Join-Path $scriptDir "Invoke-CodeBuddyTask.ps1"

& $runner -TaskFile $taskFile -IncludeGitDiff -MaxInputChars $MaxInputChars -MaxReportOutputChars $MaxReportOutputChars
exit $LASTEXITCODE
