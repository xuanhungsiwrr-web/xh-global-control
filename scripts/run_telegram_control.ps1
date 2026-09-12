param(
    [Parameter(Mandatory = $true)]
    [string]$UserId,
    [string]$ChatId = "",
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8765
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$xhctl = Join-Path $repositoryRoot ".venv\Scripts\xhctl.exe"
if (-not (Test-Path -LiteralPath $xhctl)) {
    throw "Global Control virtual environment is missing: $xhctl"
}

if (-not $env:XH_CONTROL_RUNTIME_ROOT) {
    $env:XH_CONTROL_RUNTIME_ROOT = Join-Path $env:LOCALAPPDATA "xh-global-control\runtime"
}
New-Item -ItemType Directory -Force -Path $env:XH_CONTROL_RUNTIME_ROOT | Out-Null

$arguments = @(
    "telegram-serve",
    "--user-id", $UserId,
    "--host", $HostAddress,
    "--port", $Port
)
if ($ChatId) {
    $arguments += @("--chat-id", $ChatId)
}

Set-Location -LiteralPath $repositoryRoot
& $xhctl @arguments
exit $LASTEXITCODE

