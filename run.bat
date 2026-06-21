@echo off
chcp 65001 >nul
title JARVIS Command Deck
cd /d "%~dp0"

set "PY=python"
where python >nul 2>nul
if errorlevel 1 set "PY=py"

echo.
echo  J.A.R.V.I.S Command Deck
echo  [1] Main HUD
echo  [2] Command catalog
echo  [3] Jarvis Graph
echo.
set /p choice="  Select [1/2/3]: "

if "%choice%"=="2" (
    "%PY%" "%~dp0jarvis_settings.py"
) else if "%choice%"=="3" (
    "%PY%" "%~dp0jarvis_graph.py"
) else (
    "%PY%" "%~dp0jarvis_hud.py"
)

if errorlevel 1 (
    echo.
    echo  [ERROR] Jarvis stopped with an error.
    pause
)
