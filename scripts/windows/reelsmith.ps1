#Requires -Version 5.1
<#
Ярлыки reelsmith на рабочем столе вызывают этот файл:
  start   запустить Docker Desktop и все сервисы, открыть ComfyUI
  stop    остановить сервисы
  videos  открыть папку готовых роликов
  status  показать последние задачи
#>
param(
    [ValidateSet("start", "stop", "videos", "status")]
    [string]$Command = "start",
    [string]$Distro = "Ubuntu-24.04"
)

$env:WSL_UTF8 = "1"
$DockerExe = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"

function Invoke-Project([string]$Make) {
    & wsl.exe -d $Distro -- bash -lc "cd ~/reelsmith && $Make" | Out-Host
    return $LASTEXITCODE
}

function Wait-Docker {
    if (-not (Get-Process "Docker Desktop" -ErrorAction SilentlyContinue)) { Start-Process $DockerExe }
    foreach ($attempt in 1..60) {
        & wsl.exe -d $Distro -- bash -lc "docker info > /dev/null 2>&1" | Out-Host
        if ($LASTEXITCODE -eq 0) { return $true }
        Start-Sleep -Seconds 5
    }
    return $false
}

switch ($Command) {
    "start" {
        Write-Host "Запускаю Docker и сервисы reelsmith..."
        if (-not (Wait-Docker)) { Write-Host "Docker не запустился." -ForegroundColor Red; Read-Host | Out-Null; exit 1 }
        if ((Invoke-Project "make up") -ne 0) { Read-Host "Не запустилось, нажмите Enter" | Out-Null; exit 1 }
        Write-Host "ComfyUI откроется через минуту-две, когда модели загрузятся."
        Start-Sleep -Seconds 20
        Start-Process "http://localhost:8188"
    }
    "stop" {
        Invoke-Project "docker compose stop" | Out-Null
        Write-Host "Остановлено. Docker Desktop можно закрыть из трея."
        Start-Sleep -Seconds 3
    }
    "videos" {
        $linuxHome = (& wsl.exe -d $Distro -- bash -lc 'echo $HOME').Trim()
        $folder = "\\wsl.localhost\$Distro" + ($linuxHome -replace "/", "\") + "\reelsmith\studio\output\reelsmith\videos"
        if (-not (Test-Path $folder)) { New-Item -ItemType Directory -Force -Path $folder | Out-Null }
        Start-Process explorer.exe $folder
    }
    "status" {
        Invoke-Project "make jobs" | Out-Null
        Read-Host "`nНажмите Enter, чтобы закрыть" | Out-Null
    }
}
