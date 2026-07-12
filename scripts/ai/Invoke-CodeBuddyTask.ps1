param(
    [Parameter(Mandatory=$true)]
    [string]$TaskFile,

    [string]$Requirement = "",

    [string[]]$ContextPath = @(),

    [switch]$IncludeGitDiff,

    [string]$LogFile = "",

    [int]$TailLines = 500,

    [string]$OutputRoot = "",

    [string]$Model = "",

    [string]$Tools = "",

    [int]$MaxInputChars = 32000,

    [int]$MaxReportOutputChars = 12000,

    [switch]$NoExit,

    [string]$MetadataPathFile = ""
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$configPath = Join-Path $scriptDir "codebuddy.config.json"

function Get-CodeBuddyConfig {
    if (Test-Path -LiteralPath $configPath) {
        return Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    return [pscustomobject]@{
        default_model = "glm-5.2"
        default_tools = ""
        output_root = "var\ai_runs"
        exhaustion_exit_code = 42
        credit_exhaustion_patterns = @(
            "(?i)insufficient\s+credits?",
            "(?i)not\s+enough\s+credits?",
            "(?i)credits?\s+(exhausted|insufficient|used\s+up)",
            "quota"
        )
    }
}

$config = Get-CodeBuddyConfig
if ([string]::IsNullOrWhiteSpace($Model) -and $config.default_model) {
    $Model = [string]$config.default_model
}
if ([string]::IsNullOrWhiteSpace($Tools) -and $null -ne $config.default_tools) {
    $Tools = [string]$config.default_tools
}
if ([string]::IsNullOrWhiteSpace($OutputRoot) -and $config.output_root) {
    $OutputRoot = [string]$config.output_root
}

function Limit-Text {
    param(
        [Parameter(Mandatory=$true)]
        [string]$Text,
        [int]$MaxChars = 32000,
        [switch]$Tail
    )

    if ($Text.Length -le $MaxChars) {
        return $Text
    }

    if ($Tail) {
        return $Text.Substring($Text.Length - $MaxChars) + "`n...[truncated to tail]"
    }
    return $Text.Substring(0, $MaxChars) + "`n...[truncated]"
}

function Protect-Secrets {
    param(
        [Parameter(Mandatory=$true)]
        [string]$Text
    )

    $safe = $Text
    $safe = $safe -replace '(?i)(DATABASE_URL\s*=\s*)\S+', '$1[REDACTED]'
    $safe = $safe -replace '(?i)((?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|PASS|COOKIE|SESSION)[A-Z0-9_-]*\s*[:=]\s*)\S+', '$1[REDACTED]'
    $safe = $safe -replace '(?i)(mysql|postgres(?:ql)?|redis)://([^:\s/@]+):([^@\s]+)@', '$1://$2:[REDACTED]@'
    $safe = $safe -replace '(?i)(password\s*[:=]\s*)\S+', '$1[REDACTED]'
    return $safe
}

function Approx-TokenCount {
    param([string]$Text)
    return [math]::Ceiling(($Text.Length) / 4)
}

function Add-Section {
    param(
        [System.Text.StringBuilder]$Builder,
        [string]$Title,
        [string]$Body
    )

    [void]$Builder.AppendLine("")
    [void]$Builder.AppendLine("## $Title")
    [void]$Builder.AppendLine("")
    [void]$Builder.AppendLine($Body.Trim())
}

function Read-ContextPath {
    param([string]$Path)

    if (!(Test-Path -LiteralPath $Path)) {
        return "Context path not found: $Path"
    }

    $item = Get-Item -LiteralPath $Path
    if (-not $item.PSIsContainer) {
        $raw = Get-Content -LiteralPath $item.FullName -Raw -ErrorAction Stop
        return "### File: $Path`n~~~text`n$(Protect-Secrets (Limit-Text $raw -MaxChars 12000))`n~~~"
    }

    $tracked = @(git ls-files -- $Path 2>$null | Select-Object -First 250)
    if ($tracked.Count -eq 0) {
        $tracked = @(Get-ChildItem -LiteralPath $item.FullName -Recurse -File | Select-Object -First 250 | ForEach-Object { $_.FullName })
    }
    $trackedText = $tracked -join "`n"
    return "### Directory: $Path`nTracked files sample:`n$trackedText"
}

function Get-SafeGitDiff {
    $diff = git diff -- . `
        ":(exclude).env" `
        ":(exclude).env.*" `
        ":(exclude)*secret*" `
        ":(exclude)*password*" `
        ":(exclude)*.pem" `
        ":(exclude)*.key" `
        ":(exclude)start.bat"
    $diffText = $diff -join "`n"
    $untrackedBlocks = @()
    $safeExtensions = @(".ps1", ".md", ".py", ".html", ".txt", ".json", ".toml", ".yml", ".yaml", ".css", ".js")
    $untrackedFiles = @(git ls-files --others --exclude-standard 2>$null)
    foreach ($file in $untrackedFiles) {
        if ($file -match '(?i)(^|/)\.env|secret|password|\.pem$|\.key$|start\.bat$') {
            continue
        }
        $extension = [IO.Path]::GetExtension($file).ToLowerInvariant()
        if ($safeExtensions -notcontains $extension) {
            continue
        }
        if (!(Test-Path -LiteralPath $file)) {
            continue
        }
        $content = Get-Content -LiteralPath $file -Raw
        $untrackedBlocks += "diff --git a/$file b/$file`nnew file mode 100644`n--- /dev/null`n+++ b/$file`n@@ untracked file content @@`n$(Limit-Text (Protect-Secrets $content) -MaxChars 8000)"
    }
    if ($untrackedBlocks.Count -gt 0) {
        $diffText = (($untrackedBlocks -join "`n`n"), $diffText) -join "`n`n"
    }
    return Protect-Secrets $diffText
}

function Invoke-CodeBuddy {
    param(
        [string]$Prompt,
        [string]$StdoutFile,
        [string]$StderrFile,
        [string]$Model,
        [string]$Tools
    )

    $args = @(
        "--print",
        "--output-format",
        "text",
        "--max-turns",
        "1",
        "--append-system-prompt",
        "You are a text-only review assistant. Do not use tools. Do not ask to inspect files. Use only the supplied prompt and return the requested review directly."
    )
    if ([string]::IsNullOrEmpty($Tools)) {
        $args += "--tools="
    } else {
        $args += @("--tools", $Tools)
    }
    if (-not [string]::IsNullOrWhiteSpace($Model)) {
        $args += @("--model", $Model)
    }

    $combined = $Prompt | & codebuddy @args 2>&1
    $exitCode = $LASTEXITCODE
    $combinedText = ($combined | Out-String)
    Set-Content -LiteralPath $StdoutFile -Value $combinedText -Encoding UTF8
    Set-Content -LiteralPath $StderrFile -Value "" -Encoding UTF8
    return $exitCode
}

function Test-CodeBuddyCreditExhausted {
    param([string]$Text)

    foreach ($pattern in @($config.credit_exhaustion_patterns)) {
        if ([string]::IsNullOrWhiteSpace([string]$pattern)) {
            continue
        }
        if ($Text -match [string]$pattern) {
            return $true
        }
    }
    return $false
}

if (!(Test-Path -LiteralPath $TaskFile)) {
    Write-Error "Task file not found: $TaskFile"
    exit 1
}

$taskPath = (Resolve-Path -LiteralPath $TaskFile).Path
$taskName = [IO.Path]::GetFileNameWithoutExtension($taskPath)
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$shortGuid = ([guid]::NewGuid().ToString("N")).Substring(0, 8)
$runId = "$timestamp-$taskName-$shortGuid"
$runDir = Join-Path $OutputRoot $runId
New-Item -ItemType Directory -Force -Path $runDir | Out-Null

$builder = [System.Text.StringBuilder]::new()
$taskText = Get-Content -LiteralPath $taskPath -Raw
Add-Section -Builder $builder -Title "Task Instructions" -Body $taskText

if (-not [string]::IsNullOrWhiteSpace($Requirement)) {
    Add-Section -Builder $builder -Title "Requirement" -Body $Requirement
}

if ($ContextPath.Count -gt 0) {
    $contextBlocks = foreach ($path in $ContextPath) {
        Read-ContextPath -Path $path
    }
    Add-Section -Builder $builder -Title "Context" -Body ($contextBlocks -join "`n`n")
}

if ($IncludeGitDiff) {
    $diffText = Get-SafeGitDiff
    if ([string]::IsNullOrWhiteSpace($diffText)) {
        $diffText = "No uncommitted diff found."
    }
    Add-Section -Builder $builder -Title "Git Diff" -Body "~~~diff`n$(Limit-Text $diffText -MaxChars 24000)`n~~~"
}

if (-not [string]::IsNullOrWhiteSpace($LogFile)) {
    if (!(Test-Path -LiteralPath $LogFile)) {
        Write-Error "Log file not found: $LogFile"
        exit 1
    }
    $log = Get-Content -LiteralPath $LogFile -Tail $TailLines
    $logText = Protect-Secrets (($log -join "`n"))
    Add-Section -Builder $builder -Title "Test Log" -Body "~~~text`n$(Limit-Text $logText -MaxChars 20000 -Tail)`n~~~"
}

$prompt = Limit-Text (Protect-Secrets $builder.ToString()) -MaxChars $MaxInputChars
$promptFile = Join-Path $runDir "prompt.txt"
$stdoutFile = Join-Path $runDir "stdout.txt"
$stderrFile = Join-Path $runDir "stderr.txt"
$metaFile = Join-Path $runDir "metadata.json"
$reportFile = Join-Path $runDir "report.md"

Set-Content -LiteralPath $promptFile -Value $prompt -Encoding UTF8
$startedAt = Get-Date
$exitCode = 999
try {
    $exitCode = Invoke-CodeBuddy -Prompt $prompt -StdoutFile $stdoutFile -StderrFile $stderrFile -Model $Model -Tools $Tools
} catch {
    $exitCode = 998
    Set-Content -LiteralPath $stdoutFile -Value "" -Encoding UTF8
    Set-Content -LiteralPath $stderrFile -Value ($_ | Out-String) -Encoding UTF8
}
$endedAt = Get-Date

$stdoutText = Get-Content -LiteralPath $stdoutFile -Raw
$stderrText = Get-Content -LiteralPath $stderrFile -Raw
$rawExitCode = $exitCode
$creditExhausted = ($rawExitCode -ne 0) -and (Test-CodeBuddyCreditExhausted "$stdoutText`n$stderrText")
if ($creditExhausted) {
    $configuredExitCode = 42
    if ($config.exhaustion_exit_code) {
        $configuredExitCode = [int]$config.exhaustion_exit_code
    }
    $exitCode = $configuredExitCode
}
$metadata = [ordered]@{
    run_id = $runId
    task_file = $taskPath
    requirement_present = -not [string]::IsNullOrWhiteSpace($Requirement)
    context_paths = $ContextPath
    include_git_diff = [bool]$IncludeGitDiff
    log_file = $LogFile
    model = $Model
    tools = $Tools
    run_dir = $runDir
    prompt_file = $promptFile
    stdout_file = $stdoutFile
    stderr_file = $stderrFile
    metadata_file = $metaFile
    report_file = $reportFile
    raw_exit_code = $rawExitCode
    exit_code = $exitCode
    started_at = $startedAt.ToString("o")
    ended_at = $endedAt.ToString("o")
    duration_seconds = [math]::Round(($endedAt - $startedAt).TotalSeconds, 3)
    prompt_chars = $prompt.Length
    stdout_chars = $stdoutText.Length
    stderr_chars = $stderrText.Length
    credit_exhausted = [bool]$creditExhausted
    approx_input_tokens = Approx-TokenCount $prompt
    approx_output_tokens = Approx-TokenCount $stdoutText
}
$metadata | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $metaFile -Encoding UTF8
if (-not [string]::IsNullOrWhiteSpace($MetadataPathFile)) {
    $metadataPathParent = Split-Path -Parent $MetadataPathFile
    if (-not [string]::IsNullOrWhiteSpace($metadataPathParent)) {
        New-Item -ItemType Directory -Force -Path $metadataPathParent | Out-Null
    }
    Set-Content -LiteralPath $MetadataPathFile -Value $metaFile -Encoding UTF8
}

$reportBuilder = [System.Text.StringBuilder]::new()
[void]$reportBuilder.AppendLine("# CodeBuddy Task Report")
[void]$reportBuilder.AppendLine("")
[void]$reportBuilder.AppendLine("- Run: $runId")
[void]$reportBuilder.AppendLine("- Task: $taskName")
[void]$reportBuilder.AppendLine("- Exit code: $exitCode")
[void]$reportBuilder.AppendLine("- Approx input tokens: $(Approx-TokenCount $prompt)")
[void]$reportBuilder.AppendLine("- Approx output tokens: $(Approx-TokenCount $stdoutText)")
[void]$reportBuilder.AppendLine("- Prompt: $promptFile")
[void]$reportBuilder.AppendLine("- Stdout: $stdoutFile")
[void]$reportBuilder.AppendLine("- Stderr: $stderrFile")
[void]$reportBuilder.AppendLine("")
[void]$reportBuilder.AppendLine("## Stdout")
[void]$reportBuilder.AppendLine("")
[void]$reportBuilder.AppendLine("~~~text")
[void]$reportBuilder.AppendLine((Limit-Text $stdoutText -MaxChars $MaxReportOutputChars))
[void]$reportBuilder.AppendLine("~~~")
[void]$reportBuilder.AppendLine("")
[void]$reportBuilder.AppendLine("## Stderr")
[void]$reportBuilder.AppendLine("")
[void]$reportBuilder.AppendLine("~~~text")
[void]$reportBuilder.AppendLine((Limit-Text $stderrText -MaxChars 4000 -Tail))
[void]$reportBuilder.AppendLine("~~~")
Set-Content -LiteralPath $reportFile -Value $reportBuilder.ToString() -Encoding UTF8

Write-Output "CodeBuddy task finished: run=$runId exit=$exitCode input_tokens~$(Approx-TokenCount $prompt) output_tokens~$(Approx-TokenCount $stdoutText)"
Write-Output "Report: $reportFile"
if ($creditExhausted) {
    Write-Output "CodeBuddy credit appears exhausted. Switch CodeBuddy account before continuing; no fallback model was selected."
}
if ([string]::IsNullOrWhiteSpace($stdoutText)) {
    Write-Output "Warning: CodeBuddy returned empty stdout. Check stderr and CodeBuddy local logs if needed."
}
if ($NoExit) {
    return
}
exit $exitCode
