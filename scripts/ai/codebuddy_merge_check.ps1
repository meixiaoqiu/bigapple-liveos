param(
    [Parameter(Mandatory=$true)]
    [string]$Requirement,

    [int]$TimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$taskFile = Join-Path $scriptDir "tasks\feature-merge-review.md"
$runner = Join-Path $scriptDir "Invoke-CodeBuddyTask.ps1"
$contextPaths = @("core", "simulation", "simulation_lab", "observer", "workspace", "worlds", "docs")

& $runner -TaskFile $taskFile -Requirement $Requirement -ContextPath $contextPaths -TimeoutSeconds $TimeoutSeconds
exit $LASTEXITCODE
