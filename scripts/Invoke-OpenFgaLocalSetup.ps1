param(
    [int]$OpenFgaTimeoutSeconds = 60
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $repoRoot "docker-compose.dev.yml"
$envPath = Join-Path $repoRoot ".env"

function Convert-EnvValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    $trimmed = $Value.Trim()
    if ($trimmed.Length -ge 2) {
        $first = $trimmed.Substring(0, 1)
        $last = $trimmed.Substring($trimmed.Length - 1, 1)
        if (($first -eq "'" -and $last -eq "'") -or ($first -eq '"' -and $last -eq '"')) {
            return $trimmed.Substring(1, $trimmed.Length - 2).Trim()
        }
    }
    return $trimmed
}

function Get-LocalEnvValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Key
    )

    if (-not (Test-Path -LiteralPath $envPath)) {
        return ""
    }

    foreach ($line in Get-Content -Encoding UTF8 -LiteralPath $envPath) {
        $trimmed = $line.Trim()
        if ([string]::IsNullOrWhiteSpace($trimmed) -or $trimmed.StartsWith("#")) {
            continue
        }

        $separatorIndex = $trimmed.IndexOf("=")
        if ($separatorIndex -lt 1) {
            continue
        }

        $name = $trimmed.Substring(0, $separatorIndex).Trim()
        if ($name.StartsWith("export ")) {
            $name = $name.Substring(7).Trim()
        }

        if ($name -eq $Key) {
            return Convert-EnvValue $trimmed.Substring($separatorIndex + 1)
        }
    }

    return ""
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Command,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $Command $($Arguments -join ' ')"
    }
}

function Wait-OpenFgaHttp {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [string]$Url
    )

    $deadline = (Get-Date).AddSeconds($OpenFgaTimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri "$Url/stores" -TimeoutSec 3
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
                Write-Host "$Name OpenFGA API is ready: $Url"
                return
            }
        }
        catch {
            Start-Sleep -Seconds 2
        }
    } while ((Get-Date) -lt $deadline)

    throw "$Name OpenFGA API did not become ready within $OpenFgaTimeoutSeconds seconds: $Url"
}

function Test-OpenFgaConfigComplete {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Prefix
    )

    $storeId = Get-LocalEnvValue "OPENFGA_${Prefix}_STORE_ID"
    $modelId = Get-LocalEnvValue "OPENFGA_${Prefix}_AUTHORIZATION_MODEL_ID"
    return -not [string]::IsNullOrWhiteSpace($storeId) -and -not [string]::IsNullOrWhiteSpace($modelId)
}

if (-not (Test-Path -LiteralPath $envPath)) {
    throw "Missing .env. Create it from .env.example before starting OpenFGA."
}

Push-Location $repoRoot
try {
    Write-Host "Starting OpenFGA services..."
    Invoke-Checked "docker" @("compose", "-f", $composeFile, "up", "-d", "openfga-real", "openfga-sim")

    Wait-OpenFgaHttp "real" "http://127.0.0.1:20103"
    Wait-OpenFgaHttp "sim" "http://127.0.0.1:20106"

    $realConfigComplete = Test-OpenFgaConfigComplete "REAL"
    $simConfigComplete = Test-OpenFgaConfigComplete "SIM"

    if (-not $realConfigComplete -or -not $simConfigComplete) {
        Write-Host ""
        Write-Host "OpenFGA store/model IDs are missing from .env."
        Write-Host "Bootstrap output follows. Add the OPENFGA_* values to .env, then rerun start.bat."
        Write-Host ""

        if (-not $realConfigComplete) {
            Invoke-Checked "docker" @(
                "compose", "-f", $composeFile, "run", "--rm", "--no-deps", "big-apple-admin",
                "python", "manage.py", "openfga_bootstrap",
                "--world-kind", "real",
                "--api-url", "http://openfga-real:8080"
            )
        }

        if (-not $simConfigComplete) {
            Invoke-Checked "docker" @(
                "compose", "-f", $composeFile, "run", "--rm", "--no-deps", "big-apple-admin",
                "python", "manage.py", "openfga_bootstrap",
                "--world-kind", "sim",
                "--api-url", "http://openfga-sim:8082"
            )
        }

        exit 1
    }

    Write-Host "Rebuilding OpenFGA tuples from Django authority data..."
    Invoke-Checked "docker" @(
        "compose", "-f", $composeFile, "run", "--rm", "--no-deps", "big-apple-admin",
        "python", "manage.py", "openfga_rebuild_tuples",
        "--world-id", "realworld",
        "--world-kind", "real"
    )
    Invoke-Checked "docker" @(
        "compose", "-f", $composeFile, "run", "--rm", "--no-deps", "big-apple-admin",
        "python", "manage.py", "openfga_rebuild_tuples",
        "--world-id", "simulation0001",
        "--world-kind", "sim"
    )

    Write-Host "Comparing legacy Django authorization with OpenFGA..."
    Invoke-Checked "docker" @(
        "compose", "-f", $composeFile, "run", "--rm", "--no-deps", "big-apple-admin",
        "python", "manage.py", "openfga_authorization_probe",
        "--world-id", "realworld",
        "--world-kind", "real",
        "--fail-on-diff"
    )
    Invoke-Checked "docker" @(
        "compose", "-f", $composeFile, "run", "--rm", "--no-deps", "big-apple-admin",
        "python", "manage.py", "openfga_authorization_probe",
        "--world-id", "simulation0001",
        "--world-kind", "sim",
        "--fail-on-diff"
    )

    Write-Host "OpenFGA local setup completed."
}
finally {
    Pop-Location
}
