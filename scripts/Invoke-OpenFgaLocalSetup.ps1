param(
    [int]$OpenFgaTimeoutSeconds = 60
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $repoRoot "docker-compose.dev.yml"
$envPath = Join-Path $repoRoot ".env"
$modelPath = Join-Path $repoRoot "openfga\bigapple.authorization-model.json"

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

function Get-OpenFgaResourceError {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ResourceLabel,

        [Parameter(Mandatory = $true)]
        [string]$Url
    )

    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 5
        if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
            return ""
        }
    }
    catch {
        $statusCode = ""
        if ($null -ne $_.Exception.Response) {
            $statusCode = " HTTP $([int]$_.Exception.Response.StatusCode)."
        }
        return "$ResourceLabel is not available at $Url.$statusCode"
    }

    return "$ResourceLabel returned an unexpected response at $Url."
}

function ConvertTo-CanonicalJsonValue {
    param(
        [Parameter(Mandatory = $false)]
        [AllowNull()]
        $Value,

        [Parameter(Mandatory = $false)]
        [string]$PropertyName = ""
    )

    if ($null -eq $Value) {
        return $null
    }
    if ($Value -is [string] -or $Value -is [ValueType]) {
        return $Value
    }
    # OpenFGA adds empty optional fields when reading a model; they do not change authorization semantics.
    if ($Value -is [System.Collections.IDictionary]) {
        $orderedDictionary = [ordered]@{}
        foreach ($key in @($Value.Keys | Sort-Object)) {
            if ($null -eq $Value[$key] -or $Value[$key] -eq "") {
                continue
            }
            $orderedDictionary[$key] = ConvertTo-CanonicalJsonValue $Value[$key] "$key"
        }
        return [pscustomobject]$orderedDictionary
    }

    $properties = @($Value.PSObject.Properties | Where-Object {
        $_.MemberType -in @("NoteProperty", "Property")
    })
    if ($properties.Count -gt 0 -and -not ($Value -is [System.Collections.IEnumerable])) {
        $orderedObject = [ordered]@{}
        foreach ($property in @($properties | Sort-Object Name)) {
            if ($null -eq $property.Value -or $property.Value -eq "") {
                continue
            }
            $orderedObject[$property.Name] = ConvertTo-CanonicalJsonValue $property.Value $property.Name
        }
        return [pscustomobject]$orderedObject
    }
    if ($Value -is [System.Collections.IEnumerable]) {
        $canonicalItems = @($Value | ForEach-Object {
            ConvertTo-CanonicalJsonValue $_
        })
        if ($PropertyName -in @("type_definitions", "directly_related_user_types")) {
            $canonicalItems = @($canonicalItems | Sort-Object {
                ConvertTo-Json $_ -Depth 100 -Compress
            })
        }
        return ,$canonicalItems
    }

    return $Value
}

function ConvertTo-CanonicalAuthorizationModelJson {
    param(
        [Parameter(Mandatory = $true)]
        $Model
    )

    $conditions = [pscustomobject]@{}
    $conditionsProperty = $Model.PSObject.Properties["conditions"]
    if ($null -ne $conditionsProperty -and $null -ne $conditionsProperty.Value) {
        $conditions = $conditionsProperty.Value
    }
    $payload = [pscustomobject][ordered]@{
        schema_version = $Model.schema_version
        type_definitions = $Model.type_definitions
        conditions = $conditions
    }
    $canonicalPayload = ConvertTo-CanonicalJsonValue $payload
    return ConvertTo-Json $canonicalPayload -Depth 100 -Compress
}

function Get-StringSha256 {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
        return ([System.BitConverter]::ToString($sha256.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha256.Dispose()
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

function Get-OpenFgaConfigurationErrors {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("REAL", "SIM")]
        [string]$Prefix,

        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [string]$HostApiUrl,

        [Parameter(Mandatory = $true)]
        [string]$ExpectedModelJson,

        [Parameter(Mandatory = $true)]
        [string]$ExpectedModelContentHash
    )

    $storeId = Get-LocalEnvValue "OPENFGA_${Prefix}_STORE_ID"
    $modelId = Get-LocalEnvValue "OPENFGA_${Prefix}_AUTHORIZATION_MODEL_ID"
    $errors = @()

    if ([string]::IsNullOrWhiteSpace($storeId)) {
        $errors += "OPENFGA_${Prefix}_STORE_ID is missing."
    }
    else {
        $storeError = Get-OpenFgaResourceError `
            "$Name OpenFGA store '$storeId'" `
            "$HostApiUrl/stores/$storeId"
        if (-not [string]::IsNullOrWhiteSpace($storeError)) {
            $errors += $storeError
        }
    }

    if ([string]::IsNullOrWhiteSpace($modelId)) {
        $errors += "OPENFGA_${Prefix}_AUTHORIZATION_MODEL_ID is missing."
    }
    elseif (-not [string]::IsNullOrWhiteSpace($storeId)) {
        $modelUrl = "$HostApiUrl/stores/$storeId/authorization-models/$modelId"
        try {
            $modelResponse = Invoke-RestMethod -UseBasicParsing -Uri $modelUrl -TimeoutSec 5
            if ($null -eq $modelResponse.authorization_model) {
                $errors += "$Name OpenFGA authorization model '$modelId' returned an invalid response at $modelUrl."
            }
            else {
                $remoteModelJson = ConvertTo-CanonicalAuthorizationModelJson $modelResponse.authorization_model
                if ($remoteModelJson -ne $ExpectedModelJson) {
                    $remoteModelContentHash = Get-StringSha256 $remoteModelJson
                    $errors += (
                        "$Name OpenFGA authorization model '$modelId' does not match the current model file. " +
                        "Remote normalized SHA-256: $remoteModelContentHash. " +
                        "Expected normalized SHA-256: $ExpectedModelContentHash."
                    )
                }
            }
        }
        catch {
            $statusCode = ""
            if ($null -ne $_.Exception.Response) {
                $statusCode = " HTTP $([int]$_.Exception.Response.StatusCode)."
            }
            $errors += "$Name OpenFGA authorization model '$modelId' is not available at $modelUrl.$statusCode"
        }
    }

    return $errors
}

if (-not (Test-Path -LiteralPath $envPath)) {
    throw "Missing .env. Create it from .env.example before starting OpenFGA."
}
if (-not (Test-Path -LiteralPath $modelPath)) {
    throw "Missing OpenFGA authorization model: $modelPath"
}

Push-Location $repoRoot
try {
    Write-Host "Starting OpenFGA services..."
    Invoke-Checked "docker" @("compose", "-f", $composeFile, "up", "-d", "openfga-real", "openfga-sim")

    Wait-OpenFgaHttp "real" "http://127.0.0.1:20103"
    Wait-OpenFgaHttp "sim" "http://127.0.0.1:20106"

    $localModel = Get-Content -Raw -Encoding UTF8 -LiteralPath $modelPath | ConvertFrom-Json
    $expectedModelJson = ConvertTo-CanonicalAuthorizationModelJson $localModel
    $expectedModelContentHash = Get-StringSha256 $expectedModelJson
    $modelHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $modelPath).Hash.ToLowerInvariant()
    $configuredModelHash = Get-LocalEnvValue "OPENFGA_AUTHORIZATION_MODEL_SHA256"
    $configurationErrors = @()
    $configurationErrors += @(
        Get-OpenFgaConfigurationErrors `
            "REAL" `
            "realworld" `
            "http://127.0.0.1:20103" `
            $expectedModelJson `
            $expectedModelContentHash
    )
    $configurationErrors += @(
        Get-OpenFgaConfigurationErrors `
            "SIM" `
            "simulation0001" `
            "http://127.0.0.1:20106" `
            $expectedModelJson `
            $expectedModelContentHash
    )
    if ([string]::IsNullOrWhiteSpace($configuredModelHash)) {
        $configurationErrors += "OPENFGA_AUTHORIZATION_MODEL_SHA256 is missing."
    }
    elseif ($configuredModelHash -ne $modelHash) {
        $configurationErrors += (
            "OPENFGA_AUTHORIZATION_MODEL_SHA256 does not match the current model file. " +
            "Configured: $configuredModelHash. Expected: $modelHash."
        )
    }

    if ($configurationErrors.Count -gt 0) {
        Write-Host ""
        Write-Host "OpenFGA configuration validation failed."
        foreach ($configurationError in $configurationErrors) {
            Write-Host " - $configurationError"
        }
        Write-Host ""
        Write-Host "The startup script does not modify .env."
        Write-Host "Create or refresh the required OpenFGA models with:"
        Write-Host "docker compose -f docker-compose.dev.yml run --rm --no-deps big-apple-admin python manage.py openfga_bootstrap --world-kind real --api-url http://openfga-real:8080"
        Write-Host "docker compose -f docker-compose.dev.yml run --rm --no-deps big-apple-admin python manage.py openfga_bootstrap --world-kind sim --api-url http://openfga-sim:8082"
        Write-Host ""
        Write-Host "Review the command output, update the matching OPENFGA_* values in .env, then rerun start.bat."
        Write-Host "Deployment and troubleshooting guide:"
        Write-Host "https://bigapple-docs.vercel.app/development/setup"
        Write-Host ""
        throw "OpenFGA configuration is invalid. Update .env manually before restarting."
    }

    Write-Host "Rebuilding OpenFGA tuples from Django authority data..."
    Invoke-Checked "docker" @(
        "compose", "-f", $composeFile, "run", "--rm", "--no-deps", "big-apple-real",
        "python", "manage.py", "openfga_rebuild_tuples",
        "--settings=live_os.settings_real",
        "--world-kind", "real"
    )
    Invoke-Checked "docker" @(
        "compose", "-f", $composeFile, "run", "--rm", "--no-deps", "big-apple-sim",
        "python", "manage.py", "openfga_rebuild_tuples",
        "--settings=live_os.settings_sim",
        "--world-kind", "sim"
    )

    Write-Host "Comparing legacy Django authorization with OpenFGA..."
    Invoke-Checked "docker" @(
        "compose", "-f", $composeFile, "run", "--rm", "--no-deps", "big-apple-real",
        "python", "manage.py", "openfga_authorization_probe",
        "--settings=live_os.settings_real",
        "--world-kind", "real",
        "--fail-on-diff"
    )
    Invoke-Checked "docker" @(
        "compose", "-f", $composeFile, "run", "--rm", "--no-deps", "big-apple-sim",
        "python", "manage.py", "openfga_authorization_probe",
        "--settings=live_os.settings_sim",
        "--world-kind", "sim",
        "--fail-on-diff"
    )

    Write-Host "OpenFGA local setup completed."
}
finally {
    Pop-Location
}
