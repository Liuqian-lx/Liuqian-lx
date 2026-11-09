@echo off
setlocal
set "PYTHON_EXE=C:\Users\lq\AppData\Local\Programs\Python\Python313\python.exe"

rem chcp is an external .com in System32; use its absolute path so a stripped
rem PATH cannot make this line fail.
if exist "%SystemRoot%\System32\chcp.com" "%SystemRoot%\System32\chcp.com" 65001 >nul 2>&1
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

cd /d "%~dp0"
title AnythingLLM MCP Server (HTTP 8091)

echo.
echo [MCP] Starting AnythingLLM MCP server...
echo [MCP] Working dir: %CD%
echo [MCP] Python: %PYTHON_EXE%
echo [MCP] Mode: Streamable HTTP, endpoint: /mcp (host/port from .env)
echo.

if not exist ".env" (
    echo [MCP] ERROR: .env not found.
    echo [MCP] Copy .env.example to .env and fill ANYTHINGLLM_API_KEY first.
    echo.
    pause
    exit /b 1
)

if not exist "%PYTHON_EXE%" (
    set "PYTHON_EXE=python"
    where python >nul 2>nul
    if errorlevel 1 (
        echo [MCP] ERROR: Python not found.
        echo [MCP] Expected: C:\Users\lq\AppData\Local\Programs\Python\Python313\python.exe
        echo [MCP] Install Python 3.10+ or fix the path at the top of start.bat.
        echo.
        pause
        exit /b 1
    )
)

"%PYTHON_EXE%" -u server.py
set "EXITCODE=%ERRORLEVEL%"

echo.
if not "%EXITCODE%"=="0" (
    echo [MCP] Startup failed with exit code %EXITCODE%. See errors above.
    echo [MCP] If the port is busy, stop the process using it and retry.
) else (
    echo [MCP] Server stopped.
)
echo.
pause
exit /b %EXITCODE%
