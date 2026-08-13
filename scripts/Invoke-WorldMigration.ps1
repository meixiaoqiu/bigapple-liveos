param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("realworld", "simulation0001")]
    [string]$DatabaseAlias,

    [Parameter(Mandatory = $true)]
    [ValidateSet("big-apple-real", "big-apple-sim")]
    [string]$Service,

    [Parameter(Mandatory = $true)]
    [ValidateSet("live_os.settings_real", "live_os.settings_sim")]
    [string]$SettingsModule
)

$ErrorActionPreference = "Stop"
$legacyAuthorityError = "检测到旧管理员角色或提案语义"

$allowedConfigurations = @{
    "realworld" = @{
        Service = "big-apple-real"
        SettingsModule = "live_os.settings_real"
    }
    "simulation0001" = @{
        Service = "big-apple-sim"
        SettingsModule = "live_os.settings_sim"
    }
}

$expectedConfiguration = $allowedConfigurations[$DatabaseAlias]
if (
    $Service -ne $expectedConfiguration.Service -or
    $SettingsModule -ne $expectedConfiguration.SettingsModule
) {
    $configurationError = (
        "参数组合无效：DatabaseAlias={0} 必须搭配 Service={1} 和 SettingsModule={2}。" -f `
        $DatabaseAlias,
        $expectedConfiguration.Service,
        $expectedConfiguration.SettingsModule
    )
    [Console]::Error.WriteLine($configurationError)
    exit 2
}

$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$migrationOutput = @(
    & docker compose -f docker-compose.dev.yml run --interactive=false --rm --no-deps `
        $Service python manage.py migrate --noinput "--settings=$SettingsModule" 2>&1
)
$migrationExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorActionPreference

foreach ($line in $migrationOutput) {
    if ($line -is [System.Management.Automation.ErrorRecord]) {
        Write-Host $line.Exception.Message
    }
    else {
        Write-Host $line
    }
}

if ($migrationExitCode -eq 0) {
    exit 0
}

$combinedOutput = $migrationOutput -join "`n"
if ($combinedOutput.Contains($legacyAuthorityError)) {
    Write-Host ""
    Write-Host "检测到未上线旧角色或提案数据，新的管理员语义迁移已安全停止。" -ForegroundColor Yellow
    Write-Host "失败数据库：$DatabaseAlias" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "如果该 world 只包含可丢弃的本地开发数据，可执行以下命令："
    Write-Host "docker compose -f docker-compose.dev.yml run --interactive=false --rm --no-deps big-apple-admin python manage.py flush --database=$DatabaseAlias --noinput --settings=live_os.settings_admin"
    Write-Host ""
    Write-Host "警告：该命令不可恢复，会永久删除 $DatabaseAlias 中的账号和全部业务数据。" -ForegroundColor Red
    Write-Host "它不会删除数据库结构、Django 迁移记录或 admin/control 数据。"
    Write-Host "清空完成后，请重新运行 start.bat。"
    Write-Host "启动脚本不会自动执行清空操作。"
}

exit $migrationExitCode
