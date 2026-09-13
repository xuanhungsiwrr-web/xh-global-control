param(
    [Parameter(Mandatory = $true)]
    [string]$UserId,
    [string]$ChatId = "",
    [string]$TaskName = "XH Global Control Telegram"
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $PSScriptRoot "run_telegram_control.ps1"
if (-not (Test-Path -LiteralPath $runner)) {
    throw "Telegram control launcher is missing: $runner"
}

$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$runner`" -UserId `"$UserId`""
if ($ChatId) {
    $arguments += " -ChatId `"$ChatId`""
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument $arguments `
    -WorkingDirectory $repositoryRoot
$logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$watchdog = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 1) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -DontStopOnIdleEnd `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal `
    -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger @($logon, $watchdog) `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Output "Installed and started: $TaskName"
