@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion
title Common Agent - Dev Server
cd /d "%~dp0..\.."
set PYTHONUTF8=1

echo.
echo  =============================================
echo   Common Agent - Dev Server
echo  =============================================
echo.

echo [1/3] Checking Python...
set "PY="
set "BUNDLED=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%BUNDLED%" set PY="%BUNDLED%"
if not defined PY (
  where py >nul 2>&1
  if not errorlevel 1 set "PY=py"
)
if not defined PY (
  where python >nul 2>&1
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo [ERROR] Python 3 not found.
  pause & exit /b 1
)
%PY% --version

echo [2/3] Checking .env...
if not exist ".env" (
  echo [WARN] .env not found. Copying .env.example. Put OPENROUTER_API_KEY in it ^(not needed for Ollama only^).
  copy /y ".env.example" ".env" >nul
)

echo [3/3] Checking ports 8770 / 8771 / 8772...
rem Windows lets two processes bind the same port, so an old server can silently keep the traffic.
for %%P in (8770 8771 8772) do (
  netstat -ano | findstr /r /c:":%%P .*LISTENING" >nul 2>&1
  if not errorlevel 1 (
    echo [ERROR] Port %%P is already in use. Stop the previous instance first.
    pause & exit /b 1
  )
)

echo.
echo Open http://127.0.0.1:8770/  ^(Ctrl+C to stop^)
%PY% -u app.py
pause
