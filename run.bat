@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
title Common Agent

if not exist ".env" (
  echo.
  echo   [ERROR] .env file not found.
  echo   Copy .env.example to .env and put your OPENROUTER_API_KEY in it.
  echo.
  pause
  exit /b 1
)

rem Opens Tools, MCP, and Agents tabs.
set "BUNDLED_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%BUNDLED_PYTHON%" (
  "%BUNDLED_PYTHON%" -u app.py
) else (
  py app.py
)
pause
