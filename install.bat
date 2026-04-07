@echo off
REM Arize Agent Kit installer wrapper
REM Usage: install.bat claude

where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo Error: Python 3 is required but not found in PATH. >&2
    echo Install Python 3.9+ from https://python.org and try again. >&2
    exit /b 1
)

REM Verify it's Python 3
python -c "import sys; assert sys.version_info[0] >= 3" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo Error: Python 3 is required. Found Python 2. >&2
    exit /b 1
)

REM Download and run install.py
set "TMPFILE=%TEMP%\arize-install-%RANDOM%.py"
if defined ARIZE_INSTALL_URL (
    set "INSTALL_URL=%ARIZE_INSTALL_URL%"
) else (
    set "INSTALL_URL=https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.py"
)

powershell -Command "Invoke-WebRequest -Uri '%INSTALL_URL%' -OutFile '%TMPFILE%'" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    curl -sSfL "%INSTALL_URL%" -o "%TMPFILE%" 2>nul
    if %ERRORLEVEL% neq 0 (
        echo Error: Failed to download installer. Check your internet connection. >&2
        exit /b 1
    )
)

python "%TMPFILE%" %*
set "EXIT_CODE=%ERRORLEVEL%"
del "%TMPFILE%" >nul 2>&1
exit /b %EXIT_CODE%
