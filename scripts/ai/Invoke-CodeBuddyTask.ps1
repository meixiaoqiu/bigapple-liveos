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

    [int]$MaxContextFileChars = 16000,

    [int]$MaxContextDirectoryChars = 60000,

    [int]$MaxContextDirectoryFileChars = 12000,

    [int]$MaxReportOutputChars = 12000,

    [switch]$NoExit,

    [string]$MetadataPathFile = ""
)

$ErrorActionPreference = "Stop"
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $utf8NoBom
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom
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

$repoRoot = ""
try {
    $repoRoot = ((git rev-parse --show-toplevel 2>$null) | Select-Object -First 1).Trim()
} catch {
    $repoRoot = ""
}

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

function Limit-Text {
    param(
        [Parameter(Mandatory=$true)]
        [AllowEmptyString()]
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
        [AllowEmptyString()]
        [string]$Text
    )

    $safe = $Text
    $secretKeyPattern = '(?:[A-Z0-9]+[_-])*(?:API[_-]?KEY|TOKEN|SECRET|COOKIE|SESSION|PASSWORD|PASS)(?:[_-][A-Z0-9]+)*'
    # Public template placeholders stay visible so CodeBuddy can review docs; real secrets must not use these values.
    $placeholderValuePattern = '(?:CHANGE_ME|\[REDACTED\]|REDACTED|<REDACTED>|your-[^\s;``]+|test-password|simulation-admin)'
    $safe = $safe -replace '(?i)(DATABASE_URL\s*=\s*)\S+', '$1[REDACTED]'
    $safe = $safe -replace '(?i)(Set-Cookie:\s*[^=;\s]+)=([^;\s]+)', '$1=[REDACTED]'
    $safe = $safe -replace "(?im)^(\s*$secretKeyPattern\s*[:=]\s*)(?!$placeholderValuePattern(?:\s|$|;|``))\S+", '$1[REDACTED]'
    $safe = $safe -replace "(?i)(?<![-A-Z0-9_])((?!Set-Cookie\b)$secretKeyPattern\s*[:=]\s*)(?!$placeholderValuePattern(?:\s|$|;|``))(""[^""\r\n]*""|''[^''\r\n]*''|[^\s;``]+)", '$1[REDACTED]'
    $safe = $safe -replace '(?i)(mysql|postgres(?:ql)?|redis)://([^:\s/@]+):([^@\s]+)@', '$1://$2:[REDACTED]@'
    return $safe
}

function Protect-CodeTextSecrets {
    param(
        [Parameter(Mandatory=$true)]
        [AllowEmptyString()]
        [string]$Text
    )

    $safe = $Text
    $placeholderValuePattern = '(?:CHANGE_ME|\[REDACTED\]|REDACTED|<REDACTED>|your-[^\s;``]+|test-password|simulation-admin)'
    $safe = $safe -replace '(?i)(mysql|postgres(?:ql)?|redis)://([^:\s/@]+):([^@\s]+)@', '$1://$2:[REDACTED]@'
    $safe = $safe -replace "(?m)^([+-]?[A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD|PASS|COOKIE|SESSION)[A-Z0-9_]*=)(?!$placeholderValuePattern(?:\s|$|;|``)).+", '$1[REDACTED]'
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

function ConvertTo-RepoRelativePath {
    param([Parameter(Mandatory=$true)][string]$Path)

    $resolved = $Path
    try {
        $resolved = (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
    } catch {
        $resolved = $Path
    }

    if (-not [string]::IsNullOrWhiteSpace($repoRoot)) {
        $pathSeparators = [char[]]@("\", "/")
        $root = (Resolve-Path -LiteralPath $repoRoot).Path.TrimEnd($pathSeparators)
        if ($resolved.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) {
            return ($resolved.Substring($root.Length).TrimStart($pathSeparators) -replace "\\", "/")
        }
    }
    return ($resolved -replace "\\", "/")
}

function Test-ContextFileSafe {
    param([Parameter(Mandatory=$true)][string]$Path)

    $normalized = ConvertTo-RepoRelativePath -Path $Path
    $fileName = [IO.Path]::GetFileName($normalized)
    if ($fileName -eq ".env.example") {
        return $true
    }
    if ($normalized -match '(?i)(^|/)(\.git|\.venv|node_modules|vendor|__pycache__|\.pytest_cache|staticfiles|media|logs|uploads|output|temp|var/ai_runs)(/|$)') {
        return $false
    }
    if ($normalized -match '(?i)(^|/)\.env($|\.)|(^|/)start\.bat$|\.pem$|\.key$') {
        return $false
    }
    if ($fileName -match '(?i)^(secrets?|passwords?)(\.[^.]*)?$|secret[_-]?key') {
        return $false
    }

    $safeExtensions = @(".ps1", ".md", ".py", ".html", ".txt", ".json", ".toml", ".yml", ".yaml", ".css", ".js")
    $extension = [IO.Path]::GetExtension($normalized).ToLowerInvariant()
    return ($safeExtensions -contains $extension)
}

function Test-DiffFileSafe {
    param([Parameter(Mandatory=$true)][string]$Path)

    $normalized = ($Path -replace "\\", "/")
    $fileName = [IO.Path]::GetFileName($normalized)
    if ($fileName -eq ".env.example") {
        return $true
    }
    if ($normalized -match '(?i)(^|/)(\.git|\.venv|node_modules|vendor|__pycache__|\.pytest_cache|staticfiles|media|logs|uploads|output|temp|var/ai_runs)(/|$)') {
        return $false
    }
    if ($normalized -match '(?i)(^|/)\.env($|\.)|(^|/)start\.bat$|\.pem$|\.key$') {
        return $false
    }
    if ($fileName -match '(?i)^(secrets?|passwords?)(\.[^.]*)?$|secret[_-]?key') {
        return $false
    }

    $safeExtensions = @(".ps1", ".md", ".py", ".html", ".txt", ".json", ".toml", ".yml", ".yaml", ".css", ".js")
    $safeFilenames = @(".env.example", ".gitignore", "Dockerfile", "Makefile")
    $extension = [IO.Path]::GetExtension($normalized).ToLowerInvariant()
    return (($safeExtensions -contains $extension) -or ($safeFilenames -contains $fileName))
}

function Read-ContextFileBlock {
    param(
        [Parameter(Mandatory=$true)][string]$Path,
        [int]$MaxChars = 16000
    )

    $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 -ErrorAction Stop
    $normalized = ($raw -replace "`r`n", "`n") -replace "`r", "`n"
    $hasFinalNewline = $normalized.EndsWith("`n")
    $displayText = $normalized
    if ($hasFinalNewline -and $displayText.Length -gt 0) {
        $displayText = $displayText.Substring(0, $displayText.Length - 1)
    }
    $eofNote = "EOF newline: " + $(if ($hasFinalNewline) { "yes" } else { "no" })
    $displayPath = ConvertTo-RepoRelativePath -Path $Path
    return "### File: $displayPath`n$eofNote`n~~~text`n$(Protect-CodeTextSecrets (Limit-Text $displayText -MaxChars $MaxChars))`n~~~"
}

function Read-ContextPath {
    param(
        [string]$Path,
        [int]$MaxFileChars = 16000,
        [int]$MaxDirectoryChars = 60000,
        [int]$MaxDirectoryFileChars = 12000
    )

    if (!(Test-Path -LiteralPath $Path)) {
        return "Context path not found: $Path"
    }

    $item = Get-Item -LiteralPath $Path
    if (-not $item.PSIsContainer) {
        if (-not (Test-ContextFileSafe -Path $item.FullName)) {
            return "### File skipped: $(ConvertTo-RepoRelativePath -Path $item.FullName)`nReason: path is excluded from CodeBuddy context for secret or generated-file safety."
        }
        return Read-ContextFileBlock -Path $item.FullName -MaxChars $MaxFileChars
    }

    $tracked = @(git ls-files -- $Path 2>$null | Select-Object -First 250)
    if ($tracked.Count -eq 0) {
        $tracked = @(Get-ChildItem -LiteralPath $item.FullName -Recurse -File | Select-Object -First 250 | ForEach-Object { $_.FullName })
    }
    $safeFiles = @()
    foreach ($trackedPath in $tracked) {
        $candidatePath = $trackedPath
        if (-not [IO.Path]::IsPathRooted($candidatePath) -and -not [string]::IsNullOrWhiteSpace($repoRoot)) {
            $candidatePath = Join-Path $repoRoot $candidatePath
        }
        if (!(Test-Path -LiteralPath $candidatePath)) {
            continue
        }
        $candidate = Get-Item -LiteralPath $candidatePath
        if ($candidate.PSIsContainer) {
            continue
        }
        if (Test-ContextFileSafe -Path $candidate.FullName) {
            $safeFiles += $candidate
        }
    }
    $safeFiles = @($safeFiles | Sort-Object FullName)
    $trackedText = ($safeFiles | ForEach-Object { ConvertTo-RepoRelativePath -Path $_.FullName }) -join "`n"
    if ([string]::IsNullOrWhiteSpace($trackedText)) {
        return "### Directory: $Path`nNo safe text files were available for CodeBuddy context."
    }

    $builder = [System.Text.StringBuilder]::new()
    [void]$builder.AppendLine("### Directory: $Path")
    [void]$builder.AppendLine("")
    [void]$builder.AppendLine("Safe files available:")
    [void]$builder.AppendLine($trackedText)
    [void]$builder.AppendLine("")
    [void]$builder.AppendLine("Selected file contents:")

    $remaining = $MaxDirectoryChars
    foreach ($file in $safeFiles) {
        $block = Read-ContextFileBlock -Path $file.FullName -MaxChars $MaxDirectoryFileChars
        if ($block.Length -gt $remaining) {
            [void]$builder.AppendLine("")
            [void]$builder.AppendLine("...[directory context truncated before $(ConvertTo-RepoRelativePath -Path $file.FullName)]")
            break
        }
        [void]$builder.AppendLine("")
        [void]$builder.AppendLine($block)
        $remaining -= $block.Length
        if ($remaining -le 1000) {
            [void]$builder.AppendLine("")
            [void]$builder.AppendLine("...[directory context budget exhausted]")
            break
        }
    }
    return $builder.ToString()
}

function Get-SafeGitDiff {
    $changedFiles = @(git diff --name-only -- . 2>$null)
    $safeChangedFiles = @($changedFiles | Where-Object { Test-DiffFileSafe -Path $_ })
    $diffText = ""
    if ($safeChangedFiles.Count -gt 0) {
        $diff = git diff -- $safeChangedFiles
        $changedFileList = $safeChangedFiles -join "`n"
        $diffText = "Safe changed files:`n$changedFileList`n`n" + ($diff -join "`n")
    }
    $untrackedBlocks = @()
    $untrackedFiles = @(git ls-files --others --exclude-standard 2>$null)
    foreach ($file in $untrackedFiles) {
        if (-not (Test-DiffFileSafe -Path $file)) {
            continue
        }
        if (!(Test-Path -LiteralPath $file)) {
            continue
        }
        $content = Get-Content -LiteralPath $file -Raw -Encoding UTF8
        $untrackedBlocks += "diff --git a/$file b/$file`nnew file mode 100644`n--- /dev/null`n+++ b/$file`n@@ untracked file content @@`n$(Limit-Text (Protect-CodeTextSecrets $content) -MaxChars 8000)"
    }
    if ($untrackedBlocks.Count -gt 0) {
        $diffText = (($untrackedBlocks -join "`n`n"), $diffText) -join "`n`n"
    }
    return Protect-CodeTextSecrets $diffText
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
    Write-Utf8NoBom -Path $StdoutFile -Text $combinedText
    Write-Utf8NoBom -Path $StderrFile -Text ""
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
$taskText = Get-Content -LiteralPath $taskPath -Raw -Encoding UTF8
Add-Section -Builder $builder -Title "Task Instructions" -Body $taskText

if (-not [string]::IsNullOrWhiteSpace($Requirement)) {
    Add-Section -Builder $builder -Title "Requirement" -Body (Protect-Secrets $Requirement)
}

if ($ContextPath.Count -gt 0) {
    $contextCount = [math]::Max(1, $ContextPath.Count)
    $perDirectoryBudget = [int][math]::Min($MaxContextDirectoryChars, [math]::Max(4000, [math]::Floor(($MaxInputChars * 0.65) / $contextCount)))
    $perDirectoryFileBudget = [int][math]::Min($MaxContextDirectoryFileChars, [math]::Max(2000, [math]::Floor($perDirectoryBudget / 4)))
    $contextBlocks = foreach ($path in $ContextPath) {
        Read-ContextPath -Path $path -MaxFileChars $MaxContextFileChars -MaxDirectoryChars $perDirectoryBudget -MaxDirectoryFileChars $perDirectoryFileBudget
    }
    Add-Section -Builder $builder -Title "Context" -Body ($contextBlocks -join "`n`n")
}

if ($IncludeGitDiff) {
    $diffText = Get-SafeGitDiff
    if ([string]::IsNullOrWhiteSpace($diffText)) {
        $diffText = "No uncommitted diff found."
    }
    $gitDiffBudget = [int][math]::Min(80000, [math]::Max(24000, [math]::Floor($MaxInputChars * 0.8)))
    Add-Section -Builder $builder -Title "Git Diff" -Body "~~~diff`n$(Limit-Text $diffText -MaxChars $gitDiffBudget)`n~~~"
}

if (-not [string]::IsNullOrWhiteSpace($LogFile)) {
    if (!(Test-Path -LiteralPath $LogFile)) {
        Write-Error "Log file not found: $LogFile"
        exit 1
    }
    $log = Get-Content -LiteralPath $LogFile -Tail $TailLines -Encoding UTF8
    $logText = Protect-Secrets (($log -join "`n"))
    Add-Section -Builder $builder -Title "Test Log" -Body "~~~text`n$(Limit-Text $logText -MaxChars 20000 -Tail)`n~~~"
}

$prompt = Limit-Text $builder.ToString() -MaxChars $MaxInputChars
$promptFile = Join-Path $runDir "prompt.txt"
$stdoutFile = Join-Path $runDir "stdout.txt"
$stderrFile = Join-Path $runDir "stderr.txt"
$metaFile = Join-Path $runDir "metadata.json"
$reportFile = Join-Path $runDir "report.md"

Write-Utf8NoBom -Path $promptFile -Text $prompt
$startedAt = Get-Date
$exitCode = 999
try {
    $exitCode = Invoke-CodeBuddy -Prompt $prompt -StdoutFile $stdoutFile -StderrFile $stderrFile -Model $Model -Tools $Tools
} catch {
    $exitCode = 998
    Write-Utf8NoBom -Path $stdoutFile -Text ""
    Write-Utf8NoBom -Path $stderrFile -Text ($_ | Out-String)
}
$endedAt = Get-Date

$stdoutText = Get-Content -LiteralPath $stdoutFile -Raw -Encoding UTF8
$stderrText = Get-Content -LiteralPath $stderrFile -Raw -Encoding UTF8
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
    max_context_file_chars = $MaxContextFileChars
    max_context_directory_chars = $MaxContextDirectoryChars
    max_context_directory_file_chars = $MaxContextDirectoryFileChars
}
Write-Utf8NoBom -Path $metaFile -Text ($metadata | ConvertTo-Json -Depth 6)
if (-not [string]::IsNullOrWhiteSpace($MetadataPathFile)) {
    $metadataPathParent = Split-Path -Parent $MetadataPathFile
    if (-not [string]::IsNullOrWhiteSpace($metadataPathParent)) {
        New-Item -ItemType Directory -Force -Path $metadataPathParent | Out-Null
    }
    Write-Utf8NoBom -Path $MetadataPathFile -Text $metaFile
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
Write-Utf8NoBom -Path $reportFile -Text $reportBuilder.ToString()

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
