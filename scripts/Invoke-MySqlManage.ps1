param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ManageArgs
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$envConfigPath = Join-Path $repoRoot ".env"
$databaseUrlReaderPath = Join-Path $repoRoot "scripts\Get-DatabaseUrl.ps1"
$pythonPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
$managePath = Join-Path $repoRoot "manage.py"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Project virtual environment Python was not found: $pythonPath"
}

if (-not (Test-Path -LiteralPath $envConfigPath)) {
    throw "Missing database config. Create .env from .env.example and fill in DATABASE_URL."
}

$databaseUrl = [string](& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $databaseUrlReaderPath -ConfigPath $envConfigPath -Raw)
if ([string]::IsNullOrWhiteSpace($databaseUrl) -or -not $databaseUrl.StartsWith("mysql://")) {
    throw "DATABASE_URL in .env must be a valid mysql:// URL."
}
if ($databaseUrl.Contains("CHANGE_ME")) {
    throw "Replace CHANGE_ME in .env before running this command."
}

$env:DATABASE_URL = $databaseUrl
$env:DJANGO_DEBUG = "true"
if (-not $env:BIG_APPLE_CONTRACTS_ROOT) {
    $env:BIG_APPLE_CONTRACTS_ROOT = Join-Path $repoRoot "..\bigapple-docs\technical-contracts"
}

if (-not $ManageArgs -or $ManageArgs.Count -eq 0) {
    $ManageArgs = @("check_mysql_readiness")
}

Push-Location $repoRoot
try {
    & $pythonPath $managePath @ManageArgs
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
