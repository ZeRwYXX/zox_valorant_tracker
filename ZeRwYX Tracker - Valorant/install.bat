@echo off
title ZeRwYX Tracker - Setup
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install.ps1" %*
set "VS_EXIT=%ERRORLEVEL%"
echo.
pause
exit /b %VS_EXIT%
