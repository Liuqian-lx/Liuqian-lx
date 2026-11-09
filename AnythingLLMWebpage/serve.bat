@echo off
setlocal
cd /d "%~dp0"

if not exist "index.html" (
    echo [Webpage] index.html not found.
    echo [Webpage] Run this script from the AnythingLLMWebpage folder.
    pause
    exit /b 1
)

echo [Webpage] Serving %CD% on http://127.0.0.1:8092
echo [Webpage] Press Ctrl+C to stop.
start "" http://127.0.0.1:8092/index.html
python -m http.server 8092 --bind 127.0.0.1
pause
