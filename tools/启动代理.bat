@echo off
chcp 65001 >nul
title AI Prompt Workbench (compat)
cd /d "%~dp0.."
set "PY=F://ComfyUI-aki-v3//python//python.exe"
if not exist "%PY%" set "PY=python"
echo.
echo   Same as the root launcher: workbench + ComfyUI proxy on 8199
echo.
"%PY%" "%~dp0cors_proxy.py" 8199 --open
echo.
echo   [stopped]
pause
