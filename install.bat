@echo off
setlocal enabledelayedexpansion
REM Arize Agent Kit — Bootstrapper (Windows)
REM Finds Python 3.9+, creates a venv, installs the package, then hands off
REM all configuration to the arize-install Python CLI.
REM
REM Usage:  install.bat claude|codex|cursor|update|uninstall [options]

set "REPO_URL=https://github.com/Arize-ai/arize-agent-kit.git"
if not defined ARIZE_INSTALL_BRANCH set "ARIZE_INSTALL_BRANCH=main"
set "INSTALL_BRANCH=%ARIZE_INSTALL_BRANCH%"
set "TARBALL_URL=https://github.com/Arize-ai/arize-agent-kit/archive/refs/heads/%INSTALL_BRANCH%.tar.gz"
set "INSTALL_DIR=%USERPROFILE%\.arize\harness"
set "VENV_DIR=%INSTALL_DIR%\venv"
set "ARIZE_INSTALL=%VENV_DIR%\Scripts\arize-install.exe"

REM --- Parse command and args ---
set "COMMAND=%~1"
if "%COMMAND%"=="" goto :usage
if /i "%COMMAND%"=="-h" goto :usage
if /i "%COMMAND%"=="--help" goto :usage
if /i "%COMMAND%"=="help" goto :usage
shift

set "PASS_THROUGH="
:parse_args
if "%~1"=="" goto :done_args
if /i "%~1"=="--branch" (
    set "INSTALL_BRANCH=%~2"
    set "TARBALL_URL=https://github.com/Arize-ai/arize-agent-kit/archive/refs/heads/%~2.tar.gz"
    shift & shift & goto :parse_args
)
set "PASS_THROUGH=!PASS_THROUGH! %~1"
shift
goto :parse_args
:done_args

REM --- Fast path: hand off if arize-install exists ---
if exist "%ARIZE_INSTALL%" (
    "%ARIZE_INSTALL%" %COMMAND% %PASS_THROUGH%
    exit /b !ERRORLEVEL!
)

REM --- First-time bootstrap ---
call :install_repo || ( echo [arize] ERROR: Failed to download repository >&2 & exit /b 1 )
call :find_python  || ( echo [arize] ERROR: Python 3.9+ required. Install from https://www.python.org/downloads/ >&2 & exit /b 1 )
call :setup_venv   || ( echo [arize] ERROR: Failed to set up venv >&2 & exit /b 1 )

if not exist "%ARIZE_INSTALL%" (
    echo [arize] ERROR: arize-install not found after setup >&2
    exit /b 1
)
"%ARIZE_INSTALL%" %COMMAND% %PASS_THROUGH%
exit /b !ERRORLEVEL!

REM =========================================================================

:find_python
set "PYTHON_CMD="
for %%P in (python python3) do (
    where %%P >nul 2>&1 && (
        %%P -c "import sys; assert sys.version_info >= (3, 9)" >nul 2>&1 && (
            set "PYTHON_CMD=%%P" & goto :found_python )))
where py >nul 2>&1 && (
    py -3 -c "import sys; assert sys.version_info >= (3, 9)" >nul 2>&1 && (
        set "PYTHON_CMD=py -3" & goto :found_python ))
exit /b 1
:found_python
echo [arize] Found Python: %PYTHON_CMD%
exit /b 0

:setup_venv
if exist "%ARIZE_INSTALL%" ( echo [arize] Venv already set up & exit /b 0 )
echo [arize] Creating venv...
%PYTHON_CMD% -m venv "%VENV_DIR%" || ( echo [arize] ERROR: Failed to create venv >&2 & exit /b 1 )
echo [arize] Installing arize-agent-kit...
"%VENV_DIR%\Scripts\pip.exe" install --quiet "%INSTALL_DIR%" || ( echo [arize] ERROR: pip install failed >&2 & exit /b 1 )
echo [arize] Venv ready
exit /b 0

:install_repo
if exist "%INSTALL_DIR%\.git" (
    echo [arize] Repository exists — syncing...
    git -C "%INSTALL_DIR%" fetch --depth 1 origin %INSTALL_BRANCH% >nul 2>&1 && (
        git -C "%INSTALL_DIR%" checkout -B %INSTALL_BRANCH% FETCH_HEAD >nul 2>&1 && exit /b 0 )
    echo [arize] git update failed — re-cloning
    rmdir /s /q "%INSTALL_DIR%" >nul 2>&1
)
if exist "%INSTALL_DIR%" if not exist "%INSTALL_DIR%\.git" (
    rmdir /s /q "%INSTALL_DIR%" >nul 2>&1 )
where git >nul 2>&1 && (
    echo [arize] Cloning arize-agent-kit...
    git clone --depth 1 --branch %INSTALL_BRANCH% %REPO_URL% "%INSTALL_DIR%" >nul 2>&1 && exit /b 0
    echo [arize] git clone failed — falling back to tarball )
echo [arize] Downloading tarball...
set "TMP_TAR=%TEMP%\arize-kit.tar.gz"
set "TMP_DIR=%TEMP%\arize-kit-extract"
powershell -Command "Invoke-WebRequest -Uri '%TARBALL_URL%' -OutFile '%TMP_TAR%'" >nul 2>&1
if errorlevel 1 ( echo [arize] ERROR: Download failed >&2 & exit /b 1 )
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
powershell -Command "& { if(Test-Path '%TMP_DIR%'){Remove-Item -Recurse -Force '%TMP_DIR%'}; md '%TMP_DIR%'|Out-Null; tar xzf '%TMP_TAR%' -C '%TMP_DIR%'; $s=(gci '%TMP_DIR%'|select -First 1).FullName; cp -Recurse (Join-Path $s '*') '%INSTALL_DIR%' -Force }" >nul 2>&1
del /q "%TMP_TAR%" >nul 2>&1
rmdir /s /q "%TMP_DIR%" >nul 2>&1
exit /b 0

:usage
echo.
echo   Arize Agent Kit Installer
echo.
echo   Usage: install.bat ^<command^> [options]
echo   Commands:  claude ^| codex ^| cursor ^| update ^| uninstall
echo   Options are passed through to arize-install.
echo.
exit /b 1
