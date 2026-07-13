param(
    [Parameter(Mandatory=$true)]
    [string]$Requirement,

    [string[]]$ContextPath = @(),

    [switch]$IncludeGitDiff,

    [int]$MaxInputChars = 90000,

    [int]$MaxReportOutputChars = 12000,

    [int]$TimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $utf8NoBom
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory=$true)][string]$Path,
        [AllowNull()][string]$Text
    )

    $resolvedPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Path)
    $parent = Split-Path -Parent $resolvedPath
    if (-not [string]::IsNullOrWhiteSpace($parent)) {
        [IO.Directory]::CreateDirectory($parent) | Out-Null
    }
    [IO.File]::WriteAllText($resolvedPath, [string]$Text, $utf8NoBom)
}

function Extract-UnifiedDiff {
    param([Parameter(Mandatory=$true)][string]$Text)

    $fenced = [regex]::Match($Text, '(?s)```[^\r\n]*\s*((?:diff --git|---\s+a/).+?)```')
    if ($fenced.Success) {
        return $fenced.Groups[1].Value.Trim()
    }

    $lines = $Text -split "`r?`n"
    $startIndex = -1
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^(diff --git |---\s+a/)') {
            $startIndex = $i
            break
        }
    }
    if ($startIndex -lt 0) {
        return ""
    }
    $endIndex = $lines.Count - 1
    for ($i = $startIndex + 1; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^```') {
            $endIndex = $i - 1
            break
        }
    }
    return (($lines[$startIndex..$endIndex]) -join "`n").Trim()
}

function ConvertTo-GitUnifiedDiff {
    param([AllowEmptyString()][string]$PatchText)

    $normalized = ($PatchText.TrimStart([char]0xFEFF) -replace "`r`n", "`n") -replace "`r", "`n"
    if ([string]::IsNullOrWhiteSpace($normalized) -or $normalized -match '(?m)^diff --git ') {
        return $normalized.TrimEnd()
    }

    $lines = $normalized -split "`n"
    $output = [System.Collections.Generic.List[string]]::new()
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^---\s+a/(.+)$' -and ($i + 1) -lt $lines.Count -and $lines[$i + 1] -match '^\+\+\+\s+b/(.+)$') {
            $oldPath = (($lines[$i] -replace '^---\s+a/', '') -split "`t")[0]
            $newPath = (($lines[$i + 1] -replace '^\+\+\+\s+b/', '') -split "`t")[0]
            $output.Add("diff --git a/$oldPath b/$newPath")
        }
        $output.Add($lines[$i])
    }
    return (($output.ToArray()) -join "`n").TrimEnd()
}

function Repair-HunkLineCounts {
    param([AllowEmptyString()][string]$PatchText)

    if ([string]::IsNullOrWhiteSpace($PatchText)) {
        return $PatchText
    }

    $lines = $PatchText -split "`n"
    $output = [System.Collections.Generic.List[string]]::new()
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$') {
            $oldStart = $Matches[1]
            $newStart = $Matches[2]
            $suffix = $Matches[3]
            $hunkHeaderIndex = $output.Count
            $output.Add($lines[$i])
            $oldCount = 0
            $newCount = 0
            $j = $i + 1
            while ($j -lt $lines.Count -and $lines[$j] -notmatch '^(diff --git |@@ )') {
                $line = $lines[$j]
                if ($line.StartsWith(" ")) {
                    $oldCount++
                    $newCount++
                } elseif ($line.StartsWith("-")) {
                    $oldCount++
                } elseif ($line.StartsWith("+")) {
                    $newCount++
                }
                $output.Add($line)
                $j++
            }
            $output[$hunkHeaderIndex] = "@@ -$oldStart,$oldCount +$newStart,$newCount @@$suffix"
            $i = $j - 1
            continue
        }
        $output.Add($lines[$i])
    }
    return (($output.ToArray()) -join "`n").TrimEnd()
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$runner = Join-Path $scriptDir "Invoke-CodeBuddyTask.ps1"
$guard = Join-Path $scriptDir "codebuddy_apply_patch_guard.ps1"
$taskFile = Join-Path $scriptDir "tasks\patch-generation.md"
$metadataPathFile = Join-Path ([IO.Path]::GetTempPath()) ("codebuddy-metadata-{0}.txt" -f ([guid]::NewGuid().ToString("N")))

if ($ContextPath.Count -eq 0 -and -not $IncludeGitDiff) {
    Write-Error "Patch generation requires -ContextPath and/or -IncludeGitDiff so CodeBuddy can see real source context."
    exit 1
}

$existingContextPaths = @($ContextPath | Where-Object { Test-Path -LiteralPath $_ })
if ($ContextPath.Count -gt 0 -and $existingContextPaths.Count -eq 0) {
    Write-Error "None of the supplied -ContextPath entries exist after normalization: $($ContextPath -join ', ')"
    exit 1
}

$runnerArgs = @{
    TaskFile = $taskFile
    Requirement = $Requirement
    ContextPath = $ContextPath
    MaxInputChars = $MaxInputChars
    MaxContextFileChars = 24000
    MaxContextDirectoryChars = 70000
    MaxContextDirectoryFileChars = 16000
    MaxReportOutputChars = $MaxReportOutputChars
    TimeoutSeconds = $TimeoutSeconds
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
$rawPatchFile = Join-Path $runDir "proposal.raw.patch"

if (!(Test-Path -LiteralPath $stdoutFile)) {
    Write-Error "CodeBuddy stdout file not found: $stdoutFile"
    exit 1
}

$stdoutText = Get-Content -LiteralPath $stdoutFile -Raw -Encoding UTF8
$runnerExitCode = [int]$metadata.exit_code
if ($runnerExitCode -ne 0) {
    Write-Output "Patch proposal not trusted because CodeBuddy runner failed: exit=$runnerExitCode"
    Write-Output "Patch proposal was not created."
    exit $runnerExitCode
}

$rawPatchText = Extract-UnifiedDiff $stdoutText
Write-Utf8NoBom -Path $rawPatchFile -Text $rawPatchText
$patchText = Repair-HunkLineCounts (ConvertTo-GitUnifiedDiff $rawPatchText)
if (-not [string]::IsNullOrWhiteSpace($patchText)) {
    $patchText = $patchText.TrimEnd() + "`n"
}
Write-Utf8NoBom -Path $patchFile -Text $patchText

if ([string]::IsNullOrWhiteSpace($patchText)) {
    Write-Output "CodeBuddy did not produce a unified diff."
    Write-Output "Patch proposal: $patchFile"
    Write-Output "This is not a completed CodeBuddy development pass. Re-run with narrower -ContextPath files or include the relevant git diff."
    exit 1
}

Write-Output "Patch proposal: $patchFile"
Write-Output "Running patch guard dry run..."
$guardExitCode = 0
try {
    $guardOutput = & $guard -PatchFile $patchFile 2>&1
    $guardExitCode = $LASTEXITCODE
    $guardOutput | ForEach-Object { Write-Output $_ }
} catch {
    $guardExitCode = 1
    Write-Output ($_ | Out-String)
}
if ($guardExitCode -ne 0) {
    Write-Output "Patch proposal failed guard and must not be applied."
    exit $guardExitCode
}
Write-Output "Patch proposal passed guard. Codex/human review is still required before applying."
exit 0
