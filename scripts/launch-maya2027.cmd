@echo off
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch-maya.ps1" -MayaVersion 2027 %*
