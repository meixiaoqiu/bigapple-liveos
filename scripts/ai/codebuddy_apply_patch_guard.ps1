param(
    [Parameter(Mandatory=$true)]
    [string]$PatchFile,

    [switch]$Apply
)

$ErrorActionPreference = "Stop"
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $utf8NoBom
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom

function Get-RepoRoot {
    $root = git rev-parse --show-toplevel
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($root)) {
        throw "Not inside a git repository."
    }
    return $root.Trim()
}

function Get-CodeBuddyConfig {
    param([string]$ScriptDir)

    $configPath = Join-Path $ScriptDir "codebuddy.config.json"
    if (Test-Path -LiteralPath $configPath) {
        return Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    return [pscustomobject]@{
        patch_guard = [pscustomobject]@{
            allowed_extensions = @(".css", ".html", ".js", ".json", ".md", ".ps1", ".py", ".toml", ".txt", ".yaml", ".yml")
            allowed_filenames = @(".env.example")
            forbidden_path_patterns = @(
                "(^|/)\.env($|\.(?!example$))",
                "(^|/)start\.bat$",
                "(^|/)[^/]+/migrations/",
                "(?i)(^|/)(secrets?|passwords?)(\.[^/]+)?$",
                "(?i)(^|/).*secret[_-]?key.*",
                "(?i)\.pem$",
                "(?i)\.key$"
            )
        }
    }
}

function Normalize-PatchPath {
    param([string]$Path)

    $normalized = $Path.Trim()
    if ($normalized -eq "/dev/null") {
        return $normalized
    }
    $normalized = $normalized -replace '\\', '/'
    $normalized = $normalized -replace '^[ab]/', ''
    if ([string]::IsNullOrWhiteSpace($normalized)) {
        throw "Patch contains an empty file path."
    }
    if ([IO.Path]::IsPathRooted($normalized) -or $normalized.Contains("..")) {
        throw "Patch path is not repository-relative: $Path"
    }
    return $normalized
}

function Get-PatchTouchedPaths {
    param([string[]]$Lines)

    $paths = [System.Collections.Generic.HashSet[string]]::new()
    foreach ($line in $Lines) {
        if ($line -match '^diff --git\s+a/(.+?)\s+b/(.+)$') {
            [void]$paths.Add((Normalize-PatchPath $Matches[1]))
            [void]$paths.Add((Normalize-PatchPath $Matches[2]))
            continue
        }
        if ($line -match '^(---|\+\+\+)\s+(.+)$') {
            $path = ($Matches[2] -split "`t")[0]
            $normalized = Normalize-PatchPath $path
            if ($normalized -ne "/dev/null") {
                [void]$paths.Add($normalized)
            }
        }
    }
    return @($paths | Where-Object { $_ -ne "/dev/null" } | Sort-Object)
}

function Assert-PatchPathAllowed {
    param(
        [string]$Path,
        [object]$Config
    )

    $extension = [IO.Path]::GetExtension($Path).ToLowerInvariant()
    $allowedExtensions = @($Config.patch_guard.allowed_extensions)
    $allowedFilenames = @()
    if ($Config.patch_guard.PSObject.Properties.Name -contains "allowed_filenames") {
        $allowedFilenames = @($Config.patch_guard.allowed_filenames)
    }
    $fileName = [IO.Path]::GetFileName($Path)
    if (($allowedExtensions -notcontains $extension) -and ($allowedFilenames -notcontains $fileName)) {
        throw "Patch touches a file extension that is not allowed: $Path"
    }

    foreach ($pattern in @($Config.patch_guard.forbidden_path_patterns)) {
        if ([string]::IsNullOrWhiteSpace([string]$pattern)) {
            continue
        }
        if ($Path -match [string]$pattern) {
            throw "Patch touches a forbidden path: $Path (pattern: $pattern)"
        }
    }
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$config = Get-CodeBuddyConfig -ScriptDir $scriptDir
$repoRoot = Get-RepoRoot
$resolvedPatch = (Resolve-Path -LiteralPath $PatchFile).Path
$patchText = Get-Content -LiteralPath $resolvedPatch -Raw -Encoding UTF8
$patchText = ($patchText.TrimStart([char]0xFEFF) -replace "`r`n", "`n") -replace "`r", "`n"
$patchText = $patchText.TrimEnd() + "`n"
if ([string]::IsNullOrWhiteSpace($patchText)) {
    throw "Patch file is empty: $PatchFile"
}
if ($patchText -notmatch '(?m)^diff --git ') {
    throw "Patch file does not look like a unified git diff: $PatchFile"
}

$lines = $patchText -split "`r?`n"
$paths = Get-PatchTouchedPaths -Lines $lines
if ($paths.Count -eq 0) {
    throw "Patch does not contain changed paths."
}
foreach ($path in $paths) {
    Assert-PatchPathAllowed -Path $path -Config $config
}

$normalizedPatchFile = Join-Path ([IO.Path]::GetTempPath()) ("codebuddy-guard-{0}.patch" -f ([guid]::NewGuid().ToString("N")))
[IO.File]::WriteAllText($normalizedPatchFile, $patchText, $utf8NoBom)

Push-Location $repoRoot
try {
    git apply --check -- $normalizedPatchFile
    if ($LASTEXITCODE -ne 0) {
        throw "git apply --check failed for patch: $PatchFile"
    }

    Write-Output "Patch guard passed."
    Write-Output "Touched paths:"
    $paths | ForEach-Object { Write-Output " - $_" }

    if ($Apply) {
        git apply -- $normalizedPatchFile
        if ($LASTEXITCODE -ne 0) {
            throw "git apply failed for patch: $PatchFile"
        }
        Write-Output "Patch applied."
    } else {
        Write-Output "Dry run only. Re-run with -Apply to apply after Codex/human review."
    }
} finally {
    Pop-Location
    if (Test-Path -LiteralPath $normalizedPatchFile) {
        Remove-Item -LiteralPath $normalizedPatchFile -Force
    }
}
