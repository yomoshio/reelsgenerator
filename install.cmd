@echo off
rem Double-click to install or update reelsmith. It asks for administrator rights itself.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
