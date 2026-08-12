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
        $errors += ".env 缺少 OPENFGA_${Prefix}_STORE_ID。"
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
        $errors += ".env 缺少 OPENFGA_${Prefix}_AUTHORIZATION_MODEL_ID。"
    }
    elseif (-not [string]::IsNullOrWhiteSpace($storeId)) {
        $modelUrl = "$HostApiUrl/stores/$storeId/authorization-models/$modelId"
        try {
            $modelResponse = Invoke-RestMethod -UseBasicParsing -Uri $modelUrl -TimeoutSec 5
            if ($null -eq $modelResponse.authorization_model) {
                $errors += "$Name OpenFGA 授权模型 '$modelId' 返回了无效响应：$modelUrl。"
            }
            else {
                $remoteModelJson = ConvertTo-CanonicalAuthorizationModelJson $modelResponse.authorization_model
                if ($remoteModelJson -ne $ExpectedModelJson) {
                    $remoteModelContentHash = Get-StringSha256 $remoteModelJson
                    $errors += (
                        "$Name OpenFGA 授权模型 '$modelId' 与当前模型文件不一致。" +
                        "远端规范化 SHA-256：$remoteModelContentHash；" +
                        "当前文件规范化 SHA-256：$ExpectedModelContentHash。"
                    )
                }
            }
        }
        catch {
            $statusCode = ""
            if ($null -ne $_.Exception.Response) {
                $statusCode = " HTTP $([int]$_.Exception.Response.StatusCode)."
            }
            $errors += "$Name OpenFGA 授权模型 '$modelId' 无法访问：$modelUrl。$statusCode"
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

$legacyBootstrapRoleToken = "MAIN" + "TAINER"
$legacyBootstrapKeys = @()
foreach ($line in Get-Content -Encoding UTF8 -LiteralPath $envPath) {
    $trimmed = $line.Trim()
    if ($trimmed.StartsWith("BIG_APPLE_SIMULATION_BOOTSTRAP_") -and $trimmed.Contains($legacyBootstrapRoleToken)) {
        $separatorIndex = $trimmed.IndexOf("=")
        if ($separatorIndex -gt 0) {
            $legacyBootstrapKeys += $trimmed.Substring(0, $separatorIndex)
        }
    }
}
if ($legacyBootstrapKeys.Count -gt 0) {
    throw (
        "检测到旧仿真管理员环境变量：" +
        ($legacyBootstrapKeys -join "、") +
        "。请改用 BIG_APPLE_SIMULATION_BOOTSTRAP_ADMINISTRATOR_*。"
    )
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
        $configurationErrors += ".env 缺少 OPENFGA_AUTHORIZATION_MODEL_SHA256。"
    }
    elseif ($configuredModelHash -ne $modelHash) {
        $configurationErrors += (
            ".env 中的 OPENFGA_AUTHORIZATION_MODEL_SHA256 与当前模型文件不一致。" +
            "当前配置：$configuredModelHash；应为：$modelHash。"
        )
    }

    if ($configurationErrors.Count -gt 0) {
        Write-Host ""
        Write-Host "OpenFGA 配置校验失败，启动已停止。"
        foreach ($configurationError in $configurationErrors) {
            Write-Host " - $configurationError"
        }
        Write-Host ""
        Write-Host "这是本机 .env 与当前 OpenFGA 模型不一致导致的配置问题；启动脚本不会自动修改 .env。"
        Write-Host "请按以下步骤处理："
        Write-Host "1. 依次运行下面两条命令，为真实世界和仿真世界创建或刷新授权模型："
        Write-Host "docker compose -f docker-compose.dev.yml run --interactive=false --rm --no-deps big-apple-admin python manage.py openfga_bootstrap --world-kind real --api-url http://openfga-real:8080"
        Write-Host "docker compose -f docker-compose.dev.yml run --interactive=false --rm --no-deps big-apple-admin python manage.py openfga_bootstrap --world-kind sim --api-url http://openfga-sim:8082"
        Write-Host ""
        Write-Host "2. 将命令输出中的以下配置复制到项目根目录的 .env，并替换对应旧值："
        Write-Host "   OPENFGA_REAL_STORE_ID"
        Write-Host "   OPENFGA_REAL_AUTHORIZATION_MODEL_ID"
        Write-Host "   OPENFGA_SIM_STORE_ID"
        Write-Host "   OPENFGA_SIM_AUTHORIZATION_MODEL_ID"
        Write-Host "   OPENFGA_AUTHORIZATION_MODEL_SHA256"
        Write-Host "3. 保存 .env 后重新运行 start.bat。"
        Write-Host ""
        Write-Host "部署与故障排查文档："
        Write-Host "https://bigapple-docs.vercel.app/development/setup"
        Write-Host ""
        throw "OpenFGA 配置无效。请按上方步骤更新 .env 后重新启动。"
    }

    Write-Host "Rebuilding OpenFGA tuples from Django authority data..."
    Invoke-Checked "docker" @(
        "compose", "-f", $composeFile, "run", "--interactive=false", "--rm", "--no-deps", "big-apple-real",
        "python", "manage.py", "openfga_rebuild_tuples",
        "--settings=live_os.settings_real",
        "--world-kind", "real"
    )
    Invoke-Checked "docker" @(
        "compose", "-f", $composeFile, "run", "--interactive=false", "--rm", "--no-deps", "big-apple-sim",
        "python", "manage.py", "openfga_rebuild_tuples",
        "--settings=live_os.settings_sim",
        "--world-kind", "sim"
    )

    Write-Host "Probing current OpenFGA authorization..."
    Invoke-Checked "docker" @(
        "compose", "-f", $composeFile, "run", "--interactive=false", "--rm", "--no-deps", "big-apple-real",
        "python", "manage.py", "openfga_authorization_probe",
        "--settings=live_os.settings_real",
        "--world-kind", "real"
    )
    Invoke-Checked "docker" @(
        "compose", "-f", $composeFile, "run", "--interactive=false", "--rm", "--no-deps", "big-apple-sim",
        "python", "manage.py", "openfga_authorization_probe",
        "--settings=live_os.settings_sim",
        "--world-kind", "sim"
    )

    Write-Host "OpenFGA local setup completed."
}
finally {
    Pop-Location
}
