#Requires -Version 5.1
<#
Ставит reelsmith на Windows: WSL2 с Ubuntu 24.04 и Docker Desktop с видеокартой, копирует
проект в Ubuntu и запускает там install.sh: образы, веса моделей, голос диктора, запуск.
Запуск: двойной клик по install.cmd. Установщик можно запускать повторно: сделанные шаги
пропускаются, проект обновляется из папки, где лежит этот файл, и пересобирается.
Потом всё делает run.cmd рядом: run.cmd up, run.cmd add "идея", run.cmd help.
#>
param(
    [string]$Distro = "Ubuntu-24.04",
    [string]$Voice = "A gripping storyteller in his forties, low warm voice, lively intonation, dramatic pauses, building tension, never monotone",
    [double]$HourPrice = 0,
    [switch]$SkipModels,
    [switch]$NoSleep
)

$ErrorActionPreference = "Stop"
$env:WSL_UTF8 = "1"
$Here = Split-Path -Parent $PSCommandPath
$DockerExe = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"

function Say([string]$Text) { Write-Host "`n== $Text" -ForegroundColor Cyan }
function Note([string]$Text) { Write-Host "   $Text" -ForegroundColor Yellow }
function Stop-Here([string]$Text) {
    Write-Host "`n$Text" -ForegroundColor Red
    Read-Host "Нажмите Enter, чтобы закрыть" | Out-Null
    exit 1
}

# One command in Ubuntu through bash, its output on the screen, its exit code returned.
# Commands use single quotes only: Windows PowerShell drops double quotes inside arguments
# it passes to wsl.exe.
function Invoke-Linux([string]$Command, [switch]$Root, [switch]$Quiet) {
    $user = @()
    if ($Root) { $user = @("-u", "root") }
    & wsl.exe -d $Distro @user -- bash -lc $Command | Out-Host
    $code = $LASTEXITCODE
    if ($code -ne 0 -and -not $Quiet) { Stop-Here "Не прошла команда в Ubuntu: $Command" }
    return $code
}

function Get-Distros {
    $list = & wsl.exe -l -q 2>$null
    if ($LASTEXITCODE -ne 0) { return @() }
    return @($list | ForEach-Object { ($_ -replace "`0", "").Trim() } | Where-Object { $_ })
}

# --- Права администратора ----------------------------------------------------------------
$identity = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    $arguments = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-NoExit", "-File", "`"$PSCommandPath`"")
    Start-Process powershell.exe -Verb RunAs -ArgumentList $arguments
    exit 0
}

# --- Компьютер --------------------------------------------------------------------------
Say "Проверяю компьютер"
$build = [Environment]::OSVersion.Version.Build
if ($build -lt 19044) { Stop-Here "Нужна Windows 10 21H2 или Windows 11, а здесь сборка $build." }

$smi = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
if (-not $smi) {
    Stop-Here "Не найден драйвер NVIDIA. Поставьте свежий с nvidia.com/drivers и запустите установщик снова."
}
$card = (& nvidia-smi.exe --query-gpu=name,memory.total --format=csv,noheader,nounits | Select-Object -First 1).Split(",")
$vram = [int]$card[1].Trim()
Note "Видеокарта: $($card[0].Trim()), $([math]::Round($vram / 1024)) ГБ"
if ($vram -lt 23000) { Note "Меньше 24 ГБ видеопамяти: Wan будет очень медленным или не поместится." }

$ram = [math]::Floor((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
Note "Оперативная память: $ram ГБ"
if ($ram -lt 60) { Note "Меньше 64 ГБ памяти: клипы Wan могут не поместиться." }

$systemDrive = $env:SystemDrive.TrimEnd(":")
$free = [math]::Floor((Get-PSDrive $systemDrive).Free / 1GB)
Note "Свободно на диске ${systemDrive}: $free ГБ"
if ($free -lt 250) { Note "Меньше 250 ГБ: веса и образы могут не поместиться. Освободите место." }

# --- WSL ----------------------------------------------------------------------------------
Say "WSL2"
& wsl.exe --status *> $null
if ($LASTEXITCODE -ne 0) {
    & wsl.exe --install --no-distribution
    Stop-Here "WSL установлен. Перезагрузите компьютер и снова запустите install.cmd."
}
& wsl.exe --update *> $null

$config = Join-Path $env:USERPROFILE ".wslconfig"
$memory = [math]::Max(8, $ram - 8)
if (-not (Test-Path $config) -or -not (Select-String -Path $config -Pattern "^\s*memory\s*=" -Quiet)) {
    # By default WSL2 gets half the RAM; Wan offloads to RAM and needs more than that.
    Set-Content -Path $config -Encoding ASCII -Value "[wsl2]`r`nmemory=${memory}GB`r`nswap=16GB`r`n"
    Note "Записан ${config}, Linux получит $memory ГБ памяти."
    & wsl.exe --shutdown
} else {
    Note "$config уже есть, память в нём не трогаю."
}

if ((Get-Distros) -notcontains $Distro) {
    Say "Ставлю $Distro"
    Note "Сейчас Ubuntu попросит придумать имя пользователя и пароль. Потом введите exit."
    & wsl.exe --install -d $Distro
    if ((Get-Distros) -notcontains $Distro) { Stop-Here "Ubuntu не установилась. Перезагрузите компьютер и запустите install.cmd снова." }
}
& wsl.exe --set-default $Distro

# --- Docker Desktop -----------------------------------------------------------------------
Say "Docker Desktop"
if (-not (Test-Path $DockerExe)) {
    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
        Stop-Here "Нет winget. Поставьте Docker Desktop с docker.com вручную и запустите install.cmd снова."
    }
    & winget.exe install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
    if (-not (Test-Path $DockerExe)) { Stop-Here "Docker Desktop не установился." }
    Note "Если Docker попросит выйти из системы или перезагрузиться, сделайте это и запустите install.cmd снова."
}
if (-not (Get-Process "Docker Desktop" -ErrorAction SilentlyContinue)) { Start-Process $DockerExe }
Note "Жду Docker. При первом запуске примите соглашение в его окне."
$ready = $false
foreach ($attempt in 1..60) {
    if ((Invoke-Linux "docker info > /dev/null 2>&1" -Quiet) -eq 0) { $ready = $true; break }
    Start-Sleep -Seconds 5
}
if (-not $ready) {
    Stop-Here "Docker не отвечает в Ubuntu. В Docker Desktop: Settings, Resources, WSL integration, включите $Distro, затем запустите install.cmd снова."
}
Invoke-Linux "docker run --rm --gpus all nvidia/cuda:12.8.1-base-ubuntu24.04 nvidia-smi -L" | Out-Null
Note "Docker видит видеокарту."

# --- Проект -------------------------------------------------------------------------------
Say "Проект"
Invoke-Linux "apt-get update -qq && apt-get install -y -qq git rsync python3 > /dev/null" -Root | Out-Null
$linuxSource = (& wsl.exe -d $Distro -- wslpath -a "$Here").Trim()
# Code, styles, graphs and series go in; what the machine made itself stays.
$keep = @(".git", ".env", ".venv", "models", "hf", "voices", "outbox", "review", "backups",
    "studio/output", "studio/input", "studio/user", "studio/inbox", "studio/status.txt")
$excludes = ($keep | ForEach-Object { "--exclude '$_'" }) -join " "
Invoke-Linux "mkdir -p ~/reelsmith && rsync -a $excludes '$linuxSource/' ~/reelsmith/" | Out-Null
$fresh = (Invoke-Linux "test -f ~/reelsmith/.env" -Quiet) -ne 0
Invoke-Linux "cd ~/reelsmith && bash run.sh setup" | Out-Null
if ($fresh) {
    $price = $HourPrice.ToString([Globalization.CultureInfo]::InvariantCulture)
    Invoke-Linux "cd ~/reelsmith && sed -i 's/^REELSMITH_GPU_HOUR_USD=.*/REELSMITH_GPU_HOUR_USD=$price/' .env" | Out-Null
}
Note "Проект в Ubuntu: ~/reelsmith. Настройки: ~/reelsmith/.env"

$flags = "--voice '$Voice'"
if ($SkipModels) { $flags = "--no-models" }
Say "Сборка, веса моделей и запуск: от получаса до нескольких часов"
Invoke-Linux "cd ~/reelsmith && bash install.sh $flags" | Out-Null

# --- Ярлыки -------------------------------------------------------------------------------
Say "Ярлыки на рабочем столе"
$run = Join-Path $Here "run.cmd"
$shell = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath("Desktop")
foreach ($pair in @(@("запустить", "up"), @("остановить", "down"), @("ролики", "videos"), @("статус", "jobs"))) {
    $link = $shell.CreateShortcut((Join-Path $desktop "Reelsmith - $($pair[0]).lnk"))
    $link.TargetPath = "cmd.exe"
    $link.Arguments = "/k `"`"$run`" $($pair[1])`""
    $link.WorkingDirectory = $Here
    $link.Save()
}

if ($NoSleep) {
    & powercfg.exe /change standby-timeout-ac 0
    Note "Сон при питании от сети выключен."
} else {
    Note "Совет: выключите сон при питании от сети, иначе долгий рендер оборвётся."
}

Say "Готово"
Note "ComfyUI: http://localhost:8188, схемы в папке reelsmith панели Рабочие процессы."
Note "Ярлыки на рабочем столе: Reelsmith - запустить, остановить, ролики, статус."
Note "Все команды: run.cmd help в этой папке."
Start-Process "http://localhost:8188"
Read-Host "Нажмите Enter, чтобы закрыть" | Out-Null
