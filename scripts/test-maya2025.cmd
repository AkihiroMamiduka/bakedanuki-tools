@echo off
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0test-maya.ps1" -MayaVersion 2025 %*
