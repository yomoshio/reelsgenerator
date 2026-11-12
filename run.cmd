@echo off
rem reelsmith на Windows. Проект живёт в Ubuntu (WSL), куда его поставил install.cmd, и
rem каждая команда уходит туда в run.sh:
rem   run.cmd up          запустить Docker Desktop и все сервисы, открыть ComfyUI
rem   run.cmd videos      открыть папку готовых роликов
rem   run.cmd КОМАНДА     любая команда run.sh, список: run.cmd help
chcp 65001 >nul
setlocal
if "%REELSMITH_DISTRO%"=="" (set "DISTRO=Ubuntu-24.04") else (set "DISTRO=%REELSMITH_DISTRO%")
if /i "%~1"=="videos" goto videos

tasklist /fi "imagename eq Docker Desktop.exe" 2>nul | find /i "Docker Desktop.exe" >nul
if errorlevel 1 start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
wsl.exe -d %DISTRO% -e sh -c "n=0; until docker info >/dev/null 2>&1; do n=$((n+1)); [ $n -gt 60 ] && exit 1; sleep 5; done"
if errorlevel 1 (
    echo Docker не отвечает. Запустите Docker Desktop и повторите.
    exit /b 1
)
wsl.exe -d %DISTRO% --cd ~ -e bash reelsmith/run.sh %*
set "CODE=%errorlevel%"
if /i "%~1"=="up" if "%CODE%"=="0" (
    echo ComfyUI откроется через минуту-две, когда модели загрузятся.
    timeout /t 20 /nobreak >nul
    start "" http://localhost:8188
)
exit /b %CODE%

:videos
for /f "delims=" %%h in ('wsl.exe -d %DISTRO% -e sh -c "echo $HOME"') do set "LINUX_HOME=%%h"
set "FOLDER=\\wsl.localhost\%DISTRO%%LINUX_HOME:/=\%\reelsmith\studio\output\reelsmith\videos"
if not exist "%FOLDER%" mkdir "%FOLDER%"
start "" explorer.exe "%FOLDER%"
