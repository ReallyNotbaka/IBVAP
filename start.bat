@echo off
setlocal enabledelayedexpansion

title IBVAP - Intelligent Border Video Analytics Platform

echo ==================================================================
echo Starting IBVAP Platform...
echo ==================================================================

where uv >nul 2>nul
if !ERRORLEVEL! equ 0 (
    uv run --no-sync python run.py %*
    goto :done
)

where python >nul 2>nul
if !ERRORLEVEL! equ 0 (
    python run.py %*
    goto :done
)

echo [ERROR] Neither uv nor python was found on your system PATH.
echo Please install uv from https://astral.sh/uv or Python 3.12+.
pause
exit /b 1

:done
if !ERRORLEVEL! neq 0 (
    echo.
    echo [ERROR] Application exited with code !ERRORLEVEL!.
    pause
)
