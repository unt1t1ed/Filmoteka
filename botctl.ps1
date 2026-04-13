param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("start", "stop", "restart", "status")]
    [string]$Action
)

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$BotFile = Join-Path $ProjectDir "bot.py"
$LogsDir = Join-Path $ProjectDir "logs"
$PidFile = Join-Path $ProjectDir "bot.pid"
$OutLog = Join-Path $LogsDir "bot.out.log"
$ErrLog = Join-Path $LogsDir "bot.err.log"

function Get-BotProcess {
    if (-not (Test-Path $PidFile)) {
        return $null
    }

    $PidValue = (Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()

    if (-not ($PidValue -match '^\d+$')) {
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
        return $null
    }

    return Get-Process -Id $PidValue -ErrorAction SilentlyContinue
}

function Start-Bot {
    if (-not (Test-Path $PythonExe)) {
        Write-Host "Python not found: $PythonExe"
        exit 1
    }

    if (-not (Test-Path $BotFile)) {
        Write-Host "bot.py not found: $BotFile"
        exit 1
    }

    if (-not (Test-Path $LogsDir)) {
        New-Item -ItemType Directory -Path $LogsDir | Out-Null
    }

    $RunningProcess = Get-BotProcess
    if ($RunningProcess) {
        Write-Host "Bot is already running. PID: $($RunningProcess.Id)"
        return
    }

    if (Test-Path $PidFile) {
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    }

    $Process = Start-Process `
        -FilePath $PythonExe `
        -ArgumentList $BotFile `
        -WorkingDirectory $ProjectDir `
        -RedirectStandardOutput $OutLog `
        -RedirectStandardError $ErrLog `
        -WindowStyle Hidden `
        -PassThru

    $Process.Id | Set-Content $PidFile -Encoding ascii

    Write-Host "Bot started."
    Write-Host "PID: $($Process.Id)"
}

function Stop-Bot {
    $RunningProcess = Get-BotProcess

    if (-not $RunningProcess) {
        Write-Host "Bot is already stopped."
        if (Test-Path $PidFile) {
            Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
        }
        return
    }

    Stop-Process -Id $RunningProcess.Id -Force
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    Write-Host "Bot stopped. PID: $($RunningProcess.Id)"
}

function Show-Status {
    $RunningProcess = Get-BotProcess

    if ($RunningProcess) {
        Write-Host "Status: bot is running."
        Write-Host "PID: $($RunningProcess.Id)"
        Write-Host "Stdout log: $OutLog"
        Write-Host "Stderr log: $ErrLog"
    } else {
        Write-Host "Status: bot is not running."
    }
}

switch ($Action) {
    "start"   { Start-Bot }
    "stop"    { Stop-Bot }
    "restart" { Stop-Bot; Start-Sleep -Seconds 1; Start-Bot }
    "status"  { Show-Status }
}