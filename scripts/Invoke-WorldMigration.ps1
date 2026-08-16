param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("default", "realworld", "simulation0001")]
    [string]$DatabaseAlias,

    [Parameter(Mandatory = $true)]
    [ValidateSet("big-apple-admin", "big-apple-real", "big-apple-sim")]
    [string]$Service,

    [Parameter(Mandatory = $true)]
    [ValidateSet("live_os.settings_admin", "live_os.settings_real", "live_os.settings_sim")]
    [string]$SettingsModule
)

$ErrorActionPreference = "Stop"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $utf8NoBom
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom
$legacyProposalSchemaMarker = "LEGACY_PROPOSAL_SCHEMA_DETECTED"

$allowedConfigurations = @{
    "default" = @{
        Service = "big-apple-admin"
        SettingsModule = "live_os.settings_admin"
    }
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
$schemaOutput = @(
    & docker compose -f docker-compose.dev.yml run --interactive=false --rm --no-deps `
        $Service python manage.py check_legacy_proposal_schema "--settings=$SettingsModule" 2>&1
)
$schemaExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorActionPreference

if ($schemaExitCode -ne 0) {
    $combinedSchemaOutput = $schemaOutput -join "`n"
    if ($combinedSchemaOutput.Contains($legacyProposalSchemaMarker)) {
        Write-Host ""
        Write-Host "检测到已经废止的旧提案数据库结构；干净迁移基线不能覆盖该 world。" -ForegroundColor Yellow
        Write-Host "失败数据库：$DatabaseAlias" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "本项目尚未上线。确认该 world 数据可丢弃后，可执行："
        Write-Host "docker compose -f docker-compose.dev.yml run --interactive=false --rm --no-deps big-apple-admin python manage.py reset_world_database --database=$DatabaseAlias --settings=live_os.settings_admin --confirm-reset"
        Write-Host ""
        Write-Host "警告：该命令不可恢复，会永久删除 $DatabaseAlias 中的账号、业务数据和旧数据库结构。" -ForegroundColor Red
        Write-Host "重置完成后，请重新运行 start.bat；启动脚本不会自动清空数据库。"
    }
    else {
        foreach ($line in $schemaOutput) {
            if ($line -is [System.Management.Automation.ErrorRecord]) {
                Write-Host $line.Exception.Message
            }
            else {
                Write-Host $line
            }
        }
    }
    exit $schemaExitCode
}

foreach ($line in $schemaOutput) {
    if ($line -is [System.Management.Automation.ErrorRecord]) {
        Write-Host $line.Exception.Message
    }
    else {
        Write-Host $line
    }
}

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

exit $migrationExitCode
