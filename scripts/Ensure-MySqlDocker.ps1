param(
    [int]$DockerTimeoutSeconds = 300,
    [int]$MysqlTimeoutSeconds = 60
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
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

function Get-ConfigValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Key
    )

    $environmentValue = [Environment]::GetEnvironmentVariable($Key)
    if (-not [string]::IsNullOrWhiteSpace($environmentValue)) {
        return $environmentValue
    }
    return Get-LocalEnvValue $Key
}

function Test-Truthy {
    param([string]$Value)
    return $Value -and $Value.ToLowerInvariant() -in @("1", "true", "yes")
}

function Test-DockerReady {
    try {
        $output = docker info 2>&1
        if ($LASTEXITCODE -ne 0) {
            $text = [string]::Join([Environment]::NewLine, @($output))
            if ($text -match "permission denied") {
                Write-Error "Docker engine is running but access was denied. Open Docker Desktop, finish startup/login if prompted, and make sure this Windows user can access Docker."
                exit 1
            }
            return $false
        }
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

function Wait-Until {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Condition,
        [Parameter(Mandatory = $true)]
        [int]$TimeoutSeconds,
        [int]$DelaySeconds = 2
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        if (& $Condition) {
            return $true
        }
        Start-Sleep -Seconds $DelaySeconds
    } while ((Get-Date) -lt $deadline)
    return $false
}

function Test-TcpPortOpen {
    param(
        [Parameter(Mandatory = $true)]
        [string]$HostName,
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $connect = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $connect.AsyncWaitHandle.WaitOne(1000, $false)) {
            return $false
        }
        $client.EndConnect($connect)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $client.Close()
    }
}

$skipDockerMySqlStart = Get-ConfigValue "SKIP_DOCKER_MYSQL_START"
if (Test-Truthy $skipDockerMySqlStart) {
    Write-Host "Skipping Docker MySQL auto-start because SKIP_DOCKER_MYSQL_START is set."
    exit 0
}

$databaseUrl = Get-ConfigValue "DATABASE_URL"
if ([string]::IsNullOrWhiteSpace($databaseUrl)) {
    Write-Error "DATABASE_URL is missing; cannot inspect MySQL host."
    exit 1
}

$databaseUri = [System.Uri]$databaseUrl
if ($databaseUri.Scheme -ne "mysql") {
    Write-Host "DATABASE_URL is not mysql://; skipping Docker MySQL auto-start."
    exit 0
}

$mysqlHost = $databaseUri.Host
$mysqlPort = if ($databaseUri.Port -gt 0) { $databaseUri.Port } else { 3306 }
$isLocalMySql = $mysqlHost -in @("localhost", "127.0.0.1", "::1")
if (-not $isLocalMySql) {
    Write-Host "MySQL host is $mysqlHost, not local Docker. Skipping Docker MySQL auto-start."
    exit 0
}

if (Test-TcpPortOpen -HostName $mysqlHost -Port $mysqlPort) {
    Write-Host "MySQL port is already reachable: $mysqlHost`:$mysqlPort"
    exit 0
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "Docker CLI was not found. Install Docker Desktop or set SKIP_DOCKER_MYSQL_START=true."
    exit 1
}

if (-not (Test-DockerReady)) {
    Write-Host "Docker engine is not running. Starting Docker Desktop..."
    $dockerDesktopPath = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
    if (Test-Path -LiteralPath $dockerDesktopPath) {
        Start-Process -FilePath $dockerDesktopPath
    }
    else {
        Start-Process "Docker Desktop"
    }

    $dockerReady = Wait-Until -TimeoutSeconds $DockerTimeoutSeconds -DelaySeconds 3 -Condition {
        Test-DockerReady
    }
    if (-not $dockerReady) {
        Write-Error "Docker Desktop did not become ready within $DockerTimeoutSeconds seconds."
        exit 1
    }
}

$containerName = Get-ConfigValue "MYSQL_DOCKER_CONTAINER"
if ([string]::IsNullOrWhiteSpace($containerName)) {
    $containers = docker ps -a --filter "publish=$mysqlPort" --format "{{.Names}}"
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to list Docker containers."
        exit 1
    }
    $containerCandidates = @($containers | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    if ($containerCandidates.Count -eq 1) {
        $containerName = $containerCandidates[0]
    }
    elseif ($containerCandidates.Count -gt 1) {
        Write-Error "Multiple Docker containers publish port $mysqlPort. Set MYSQL_DOCKER_CONTAINER in .env."
        exit 1
    }
    else {
        Write-Host "No existing Docker container publishes MySQL port $mysqlPort. Looking for existing MySQL containers by image/name..."
        $mysqlContainers = docker ps -a --filter "ancestor=mysql" --format "{{.Names}}"
        $mariadbContainers = docker ps -a --filter "ancestor=mariadb" --format "{{.Names}}"
        $namedContainers = docker ps -a --format "{{.Names}}" | Where-Object {
            $_ -match "(?i)(mysql|mariadb)"
        }
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Failed to list Docker containers."
            exit 1
        }

        $containerCandidates = @(
            $mysqlContainers
            $mariadbContainers
            $namedContainers
        ) | Where-Object {
            -not [string]::IsNullOrWhiteSpace($_)
        } | Sort-Object -Unique

        if ($containerCandidates.Count -eq 1) {
            $containerName = $containerCandidates[0]
            Write-Host "Using existing MySQL-like Docker container: $containerName"
        }
        elseif ($containerCandidates.Count -gt 1) {
            Write-Error "Multiple existing MySQL-like containers found: $($containerCandidates -join ', '). Set MYSQL_DOCKER_CONTAINER in .env."
            exit 1
        }
        else {
            Write-Error "No existing MySQL Docker container was found. start.bat will not create database containers automatically. Create the container manually or set MYSQL_DOCKER_CONTAINER to an existing container name."
            exit 1
        }
    }
}

$containerExists = docker ps -a --format "{{.Names}}" | Where-Object { $_ -eq $containerName }
if (-not $containerExists) {
    Write-Error "Docker container '$containerName' was not found. start.bat will not create database containers automatically."
    exit 1
}

$isRunning = [string](docker inspect -f "{{.State.Running}}" $containerName)
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to inspect Docker container '$containerName'."
    exit 1
}

if ($isRunning.Trim().ToLowerInvariant() -ne "true") {
    Write-Host "Starting MySQL Docker container: $containerName"
    docker start $containerName *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to start MySQL Docker container '$containerName'."
        exit 1
    }
}
else {
    Write-Host "MySQL Docker container is already running: $containerName"
}

$mysqlReady = Wait-Until -TimeoutSeconds $MysqlTimeoutSeconds -DelaySeconds 2 -Condition {
    Test-TcpPortOpen -HostName $mysqlHost -Port $mysqlPort
}
if (-not $mysqlReady) {
    Write-Error "Container '$containerName' was started, but MySQL port $mysqlHost`:$mysqlPort did not become reachable within $MysqlTimeoutSeconds seconds. Check that DATABASE_URL uses the host port published by this existing container."
    exit 1
}

Write-Host "MySQL port is reachable: $mysqlHost`:$mysqlPort"
exit 0
