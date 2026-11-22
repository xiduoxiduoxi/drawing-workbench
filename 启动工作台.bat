@echo off
chcp 65001 >nul
title AI Prompt Workbench
cd /d "%~dp0"
set "PY=F://ComfyUI-aki-v3//python//python.exe"
if not exist "%PY%" set "PY=python"
echo.
echo   AI Prompt Workbench    http://127.0.0.1:8199/
echo   Proxy target           http://127.0.0.1:8188
echo   Keep this window open; close it to stop.
echo.
"%PY%" "%~dp0tools\cors_proxy.py" 8199 --open
echo.
echo   [stopped]  If this window closed instantly, the reason is printed above.
pause
