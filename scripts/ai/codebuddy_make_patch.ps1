param(
    [Parameter(Mandatory=$true)]
    [string]$Requirement,

    [string[]]$ContextPath = @(),

    [switch]$IncludeGitDiff,

    [int]$MaxInputChars = 32000,

    [int]$MaxReportOutputChars = 12000
)

$ErrorActionPreference = "Stop"

function Extract-UnifiedDiff {
    param([Parameter(Mandatory=$true)][string]$Text)

    $fenced = [regex]::Match($Text, '(?s)```(?:diff|patch)?\s*(diff --git .+?)```')
    if ($fenced.Success) {
        return $fenced.Groups[1].Value.Trim()
    }

    $lines = $Text -split "`r?`n"
    $startIndex = -1
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^diff --git ') {
            $startIndex = $i
            break
        }
    }
    if ($startIndex -lt 0) {
        return ""
    }
    return (($lines[$startIndex..($lines.Count - 1)]) -join "`n").Trim()
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$runner = Join-Path $scriptDir "Invoke-CodeBuddyTask.ps1"
$taskFile = Join-Path $scriptDir "tasks\patch-generation.md"
$metadataPathFile = Join-Path ([IO.Path]::GetTempPath()) ("codebuddy-metadata-{0}.txt" -f ([guid]::NewGuid().ToString("N")))

$runnerArgs = @{
    TaskFile = $taskFile
    Requirement = $Requirement
    ContextPath = $ContextPath
    MaxInputChars = $MaxInputChars
    MaxReportOutputChars = $MaxReportOutputChars
    NoExit = $true
    MetadataPathFile = $metadataPathFile
}
if ($IncludeGitDiff) {
    $runnerArgs.IncludeGitDiff = $true
}

$runnerOutput = & $runner @runnerArgs
$runnerOutput | ForEach-Object { Write-Output $_ }

if (!(Test-Path -LiteralPath $metadataPathFile)) {
    Write-Error "Cannot locate CodeBuddy metadata path file: $metadataPathFile"
    exit 1
}
$metaFile = (Get-Content -LiteralPath $metadataPathFile -Raw -Encoding UTF8).Trim()
if (!(Test-Path -LiteralPath $metaFile)) {
    Write-Error "CodeBuddy metadata file not found: $metaFile"
    exit 1
}
$metadata = Get-Content -LiteralPath $metaFile -Raw -Encoding UTF8 | ConvertFrom-Json
$runDir = [string]$metadata.run_dir
$stdoutFile = [string]$metadata.stdout_file
$patchFile = Join-Path $runDir "proposal.patch"

if (!(Test-Path -LiteralPath $stdoutFile)) {
    Write-Error "CodeBuddy stdout file not found: $stdoutFile"
    exit 1
}

$stdoutText = Get-Content -LiteralPath $stdoutFile -Raw
$runnerExitCode = [int]$metadata.exit_code
if ($runnerExitCode -ne 0) {
    Write-Output "Patch proposal not trusted because CodeBuddy runner failed: exit=$runnerExitCode"
    Write-Output "Patch proposal was not created."
    exit $runnerExitCode
}

$patchText = Extract-UnifiedDiff $stdoutText
Set-Content -LiteralPath $patchFile -Value $patchText -Encoding UTF8

if ([string]::IsNullOrWhiteSpace($patchText)) {
    Write-Output "CodeBuddy did not produce a unified diff."
    Write-Output "Patch proposal: $patchFile"
    exit 1
}

Write-Output "Patch proposal: $patchFile"
Write-Output "Next: run scripts\ai\codebuddy_apply_patch_guard.ps1 -PatchFile `"$patchFile`" before applying."
exit 0
