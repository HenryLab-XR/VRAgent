@echo off
setlocal

REM Portable Jelly launcher used by scheduled tasks and manual debugging.
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "TP_GENERATION=%%~fI"
for %%I in ("%TP_GENERATION%\..") do set "REPO_ROOT=%%~fI"
set "PORT=2000"
set "LOG_DIR=%TP_GENERATION%"
set "LOG=%LOG_DIR%\.jelly.log"

if not "%XRPLAYER_JELLY_PYTHON%"=="" (
  set "PYTHON=%XRPLAYER_JELLY_PYTHON%"
) else if exist "%REPO_ROOT%\.venv\Scripts\python.exe" (
  set "PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"
) else (
  set "PYTHON=python"
)

netstat -ano | findstr ":%PORT%.*LISTENING" >nul 2>&1
if %ERRORLEVEL%==0 (
    echo %DATE% %TIME% [jelly] port %PORT% already in use, skip. >> "%LOG%"
    exit /b 0
)

echo %DATE% %TIME% [jelly] using python: %PYTHON% >> "%LOG%"
echo %DATE% %TIME% [jelly] starting on port %PORT% >> "%LOG%"
cd /d "%TP_GENERATION%"
"%PYTHON%" -m xrplayer.jelly --port %PORT% --results-dir "%TP_GENERATION%" >> "%LOG%" 2>&1
echo %DATE% %TIME% [jelly] process exited with code %ERRORLEVEL% >> "%LOG%"
