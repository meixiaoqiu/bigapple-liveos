param(
    [Parameter(Mandatory = $true)]
    [string]$ConfigPath,

    [switch]$Raw
)

$ErrorActionPreference = "Stop"

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

function ConvertTo-SafeDatabaseUrl {
    param(
        [Parameter(Mandatory = $true)]
        [string]$DatabaseUrl
    )

    $safeUrl = $DatabaseUrl.Trim()
    $schemeIndex = $safeUrl.IndexOf("://")
    if ($schemeIndex -lt 0) {
        return "[REDACTED]"
    }

    $authorityStart = $schemeIndex + 3
    $atIndex = $safeUrl.IndexOf("@", $authorityStart)
    if ($atIndex -lt 0) {
        return $safeUrl
    }

    $authority = $safeUrl.Substring($authorityStart, $atIndex - $authorityStart)
    $passwordSeparator = $authority.IndexOf(":")
    if ($passwordSeparator -lt 0) {
        return $safeUrl
    }

    $safeAuthority = $authority.Substring(0, $passwordSeparator + 1) + "***"
    return $safeUrl.Substring(0, $authorityStart) + $safeAuthority + $safeUrl.Substring($atIndex)
}

if (-not (Test-Path -LiteralPath $ConfigPath)) {
    exit 0
}

$extension = [System.IO.Path]::GetExtension($ConfigPath).ToLowerInvariant()
$databaseUrl = ""

if ($extension -eq ".psd1") {
    $config = Import-PowerShellDataFile -LiteralPath $ConfigPath
    $databaseUrl = [string]$config.DatabaseUrl
}
else {
    foreach ($line in Get-Content -Encoding UTF8 -LiteralPath $ConfigPath) {
        $trimmed = $line.Trim()
        if ([string]::IsNullOrWhiteSpace($trimmed) -or $trimmed.StartsWith("#")) {
            continue
        }
        $separatorIndex = $trimmed.IndexOf("=")
        if ($separatorIndex -lt 1) {
            continue
        }
        $key = $trimmed.Substring(0, $separatorIndex).Trim()
        if ($key.StartsWith("export ")) {
            $key = $key.Substring(7).Trim()
        }
        if ($key -ne "DATABASE_URL") {
            continue
        }
        $databaseUrl = Convert-EnvValue $trimmed.Substring($separatorIndex + 1)
        break
    }
}

if (-not [string]::IsNullOrWhiteSpace($databaseUrl)) {
    if ($Raw) {
        [Console]::Out.WriteLine($databaseUrl.Trim())
    }
    else {
        [Console]::Out.WriteLine((ConvertTo-SafeDatabaseUrl $databaseUrl))
    }
}
