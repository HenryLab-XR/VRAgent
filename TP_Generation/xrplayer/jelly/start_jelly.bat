@echo off
REM ============================================================
REM  XRPlayer Jelly Server — 自动启动入口
REM  被 Windows 任务计划程序调用，不应手动双击运行
REM ============================================================

set "PYTHON=E:\--SoftWare\python.exe"
set "WORK_DIR=D:\--UnityProject\HenryLabXR\VRAgent2.0-PVEO_core\TP_Generation"
set "RESULTS=D:\--UnityProject\HenryLabXR\VRAgent2.0-PVEO_core\TP_Generation"
set "LOG_DIR=D:\--UnityProject\HenryLabXR\VRAgent2.0-PVEO_core\_log"
set "LOG=%LOG_DIR%\jelly.log"
set "PORT=2000"

REM ── 确保日志目录存在 ─────────────────────────────────────
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

REM ── 检查端口是否已被占用（防止重复启动）───────────────
netstat -ano | findstr ":%PORT%.*LISTENING" >nul 2>&1
if %ERRORLEVEL%==0 (
    echo %DATE% %TIME% [jelly] port %PORT% already in use, skip. >> "%LOG%"
    exit /b 0
)

REM ── 启动 Jelly，输出追加到 jelly.log ────────────────────
echo %DATE% %TIME% [jelly] starting on port %PORT% >> "%LOG%"
cd /d "%WORK_DIR%"
"%PYTHON%" -m xrplayer.jelly --port %PORT% --results-dir "%RESULTS%" >> "%LOG%" 2>&1
echo %DATE% %TIME% [jelly] process exited with code %ERRORLEVEL% >> "%LOG%"
