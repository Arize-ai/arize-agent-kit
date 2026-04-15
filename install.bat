@echo off
setlocal enabledelayedexpansion
REM Arize Agent Kit — Cross-platform installer (native batch/PowerShell)
REM
REM Usage:
REM   install.bat claude       Install Claude Code harness
REM   install.bat codex        Install Codex CLI harness
REM   install.bat cursor       Install Cursor IDE harness
REM   install.bat update       Update existing installation
REM   install.bat uninstall    Uninstall
REM
REM Installs the arize-agent-kit repo, sets up the shared background
REM collector/exporter, and configures tracing for the specified harness.
REM Idempotent — safe to run multiple times.

REM --- Constants ---
set "REPO_URL=https://github.com/Arize-ai/arize-agent-kit.git"
if not defined ARIZE_INSTALL_BRANCH set "ARIZE_INSTALL_BRANCH=main"
set "INSTALL_BRANCH=%ARIZE_INSTALL_BRANCH%"
set "TARBALL_URL=https://github.com/Arize-ai/arize-agent-kit/archive/refs/heads/%INSTALL_BRANCH%.tar.gz"
set "INSTALL_DIR=%USERPROFILE%\.arize\harness"
set "CONFIG_FILE=%INSTALL_DIR%\config.yaml"
set "BIN_DIR=%INSTALL_DIR%\bin"
set "COLLECTOR_BIN=%BIN_DIR%\arize-collector.cmd"
set "PID_DIR=%INSTALL_DIR%\run"
set "PID_FILE=%PID_DIR%\collector.pid"
set "LOG_DIR=%INSTALL_DIR%\logs"
set "COLLECTOR_LOG_FILE=%LOG_DIR%\collector.log"
set "VENV_DIR=%INSTALL_DIR%\venv"
set "STATE_BASE_DIR=%INSTALL_DIR%\state"

REM --- Parse arguments ---
set "COMMAND="
set "WITH_SKILLS=0"
set "BRANCH="

:parse_args
if "%~1"=="" goto :done_args
if /i "%~1"=="claude"    ( set "COMMAND=claude"    & shift & goto :parse_args )
if /i "%~1"=="codex"     ( set "COMMAND=codex"     & shift & goto :parse_args )
if /i "%~1"=="cursor"    ( set "COMMAND=cursor"    & shift & goto :parse_args )
if /i "%~1"=="update"    ( set "COMMAND=update"    & shift & goto :parse_args )
if /i "%~1"=="uninstall" ( set "COMMAND=uninstall" & shift & goto :parse_args )
if /i "%~1"=="--with-skills" ( set "WITH_SKILLS=1" & shift & goto :parse_args )
if /i "%~1"=="--branch"  ( set "INSTALL_BRANCH=%~2" & set "TARBALL_URL=https://github.com/Arize-ai/arize-agent-kit/archive/refs/heads/%~2.tar.gz" & shift & shift & goto :parse_args )
if /i "%~1"=="-h"        goto :usage
if /i "%~1"=="--help"    goto :usage
if /i "%~1"=="help"      goto :usage
echo [arize] Unknown argument: %~1 >&2
goto :usage
:done_args

if "%COMMAND%"=="" (
    echo [arize] No command specified >&2
    goto :usage
)

REM --- Dispatch ---
if "%COMMAND%"=="claude"    goto :cmd_claude
if "%COMMAND%"=="codex"     goto :cmd_codex
if "%COMMAND%"=="cursor"    goto :cmd_cursor
if "%COMMAND%"=="update"    goto :cmd_update
if "%COMMAND%"=="uninstall" goto :cmd_uninstall

:cmd_claude
call :install_repo
call :setup_shared_collector "claude-code"
call :setup_claude
if "%WITH_SKILLS%"=="1" call :install_skills "claude-code"
goto :eof

:cmd_codex
call :install_repo
call :setup_shared_collector "codex"
call :setup_codex
if "%WITH_SKILLS%"=="1" call :install_skills "codex"
goto :eof

:cmd_cursor
call :install_repo
call :setup_shared_collector "cursor"
call :setup_cursor
if "%WITH_SKILLS%"=="1" call :install_skills "cursor"
goto :eof

:cmd_update
call :update_install
goto :eof

:cmd_uninstall
call :do_uninstall
goto :eof

REM ===================================================================
REM  Functions
REM ===================================================================

REM --- find_python: locate Python >= 3.9 ---
:find_python
set "FOUND_PYTHON="
for %%P in (python3 python) do (
    where %%P >nul 2>&1 && (
        %%P -c "import sys; assert sys.version_info >= (3, 9)" >nul 2>&1 && (
            set "FOUND_PYTHON=%%P"
            goto :eof
        )
    )
)
REM Check common locations
for %%P in (
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python39\python.exe"
    "C:\Python313\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
    "C:\Python310\python.exe"
    "C:\Python39\python.exe"
) do (
    if exist %%~P (
        %%~P -c "import sys; assert sys.version_info >= (3, 9)" >nul 2>&1 && (
            set "FOUND_PYTHON=%%~P"
            goto :eof
        )
    )
)
goto :eof

REM --- venv_python: return venv python path ---
:venv_python
set "VENV_PYTHON="
if exist "%VENV_DIR%\Scripts\python.exe" (
    set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
) else if exist "%VENV_DIR%\bin\python" (
    set "VENV_PYTHON=%VENV_DIR%\bin\python"
)
goto :eof

REM --- venv_pip: return venv pip path ---
:venv_pip
set "VENV_PIP="
if exist "%VENV_DIR%\Scripts\pip.exe" (
    set "VENV_PIP=%VENV_DIR%\Scripts\pip.exe"
) else if exist "%VENV_DIR%\bin\pip" (
    set "VENV_PIP=%VENV_DIR%\bin\pip"
)
goto :eof

REM --- venv_bin: return path to entry point ---
:venv_bin
set "VENV_BIN_RESULT=%VENV_DIR%\Scripts\%~1.exe"
goto :eof

REM --- cfg_get: read config value ---
:cfg_get
set "CFG_RESULT="
call :venv_python
if "%VENV_PYTHON%"=="" goto :eof
if not exist "%CONFIG_FILE%" goto :eof
for /f "usebackq delims=" %%V in (`"%VENV_PYTHON%" "%INSTALL_DIR%\core\config.py" get "%~1" 2^>nul`) do set "CFG_RESULT=%%V"
goto :eof

REM --- cfg_set: write config value ---
:cfg_set
call :venv_python
if "%VENV_PYTHON%"=="" goto :eof
"%VENV_PYTHON%" "%INSTALL_DIR%\core\config.py" set "%~1" "%~2" >nul 2>&1
goto :eof

REM --- cfg_delete: delete config key ---
:cfg_delete
call :venv_python
if "%VENV_PYTHON%"=="" goto :eof
"%VENV_PYTHON%" "%INSTALL_DIR%\core\config.py" delete "%~1" >nul 2>&1
goto :eof

REM --- resolve_setup_python: find python for config manipulation ---
:resolve_setup_python
set "SETUP_PYTHON="
call :venv_python
if not "%VENV_PYTHON%"=="" (
    set "SETUP_PYTHON=%VENV_PYTHON%"
) else (
    call :find_python
    set "SETUP_PYTHON=%FOUND_PYTHON%"
)
goto :eof

REM --- update_codex_config: replace notify + [otel] blocks safely ---
:update_codex_config
set "_UCC_PY=%~1"
set "_UCC_CONFIG=%~2"
set "_UCC_NOTIFY=%~3"
set "_UCC_PORT=%~4"
set "_UCC_SCRIPT=%TEMP%\arize-update-codex-config-%RANDOM%.py"
(
    echo from pathlib import Path
    echo config_path = Path(r"%_UCC_CONFIG%")
    echo config_path.parent.mkdir(parents=True, exist_ok=True)
    echo lines = config_path.read_text().splitlines() if config_path.exists() else []
    echo filtered = []
    echo in_otel = False
    echo for line in lines:
    echo.    stripped = line.strip()
    echo.    if stripped.startswith("notify") and "=" in stripped:
    echo.        continue
    echo.    if stripped == "[otel]" or stripped.startswith("[otel."):
    echo.        in_otel = True
    echo.        continue
    echo.    if in_otel and stripped.startswith("[") and stripped != "[otel]" and not stripped.startswith("[otel."):
    echo.        in_otel = False
    echo.    if not in_otel:
    echo.        filtered.append(line)
    echo while filtered and not filtered[-1].strip():
    echo.    filtered.pop()
    echo filtered.extend([
    echo.    "",
    echo.    "# Arize tracing -- OpenInference spans per turn",
    echo.    "notify = [\"%_UCC_NOTIFY%\"]",
    echo.    "",
    echo.    "# Arize shared collector -- captures Codex events for rich span trees",
    echo.    "[otel]",
    echo.    "[otel.exporter.otlp-http]",
    echo.    "endpoint = \"http://127.0.0.1:%_UCC_PORT%/v1/logs\"",
    echo.    "protocol = \"json\"",
    echo ])
    echo config_path.write_text("\n".join(filtered) + "\n")
) > "%_UCC_SCRIPT%"
"%_UCC_PY%" "%_UCC_SCRIPT%" >nul 2>&1
set "_UCC_RC=%ERRORLEVEL%"
del "%_UCC_SCRIPT%" 2>nul
exit /b %_UCC_RC%

REM --- normalize_codex_env_file: create or convert env file to proxy format ---
:normalize_codex_env_file
set "_NCEF_PY=%~1"
set "_NCEF_ENV=%~2"
set "_NCEF_SCRIPT=%TEMP%\arize-normalize-codex-env-%RANDOM%.py"
(
    echo from pathlib import Path
    echo env_path = Path(r"%_NCEF_ENV%")
    echo env_path.parent.mkdir(parents=True, exist_ok=True)
    echo if env_path.exists():
    echo.    lines = env_path.read_text().splitlines()
    echo.    out = []
    echo.    changed = False
    echo.    for line in lines:
    echo.        stripped = line.lstrip()
    echo.        prefix = line[:len(line) - len(stripped)]
    echo.        if stripped.lower().startswith("set ") and "=" in stripped[4:]:
    echo.            out.append(prefix + "export " + stripped[4:])
    echo.            changed = True
    echo.        else:
    echo.            out.append(line)
    echo.    if changed:
    echo.        env_path.write_text("\n".join(out) + "\n")
    echo else:
    echo.    env_path.write_text("\n".join([
    echo.        "# Arize Codex tracing environment",
    echo.        "# Set the variables for your backend:",
    echo.        "",
    echo.        "# Common",
    echo.        "export ARIZE_TRACE_ENABLED=true",
    echo.        "# export ARIZE_PROJECT_NAME=codex",
    echo.        "",
    echo.        "# Phoenix (self-hosted)",
    echo.        "# export PHOENIX_ENDPOINT=http://localhost:6006",
    echo.        "",
    echo.        "# Arize AX (cloud)",
    echo.        "# export ARIZE_API_KEY=",
    echo.        "# export ARIZE_SPACE_ID=",
    echo.    ]) + "\n")
) > "%_NCEF_SCRIPT%"
"%_NCEF_PY%" "%_NCEF_SCRIPT%" >nul 2>&1
set "_NCEF_RC=%ERRORLEVEL%"
del "%_NCEF_SCRIPT%" 2>nul
exit /b %_NCEF_RC%

REM --- install_repo ---
:install_repo
if exist "%INSTALL_DIR%\.git" (
    echo [arize] Repository already installed at %INSTALL_DIR%
    echo [arize] Syncing with origin/%INSTALL_BRANCH%...
    git -C "%INSTALL_DIR%" fetch --depth 1 origin "%INSTALL_BRANCH%" >nul 2>&1
    if !ERRORLEVEL! equ 0 (
        git -C "%INSTALL_DIR%" checkout -B "%INSTALL_BRANCH%" FETCH_HEAD >nul 2>&1
        if !ERRORLEVEL! equ 0 goto :eof
    )
    git -C "%INSTALL_DIR%" fetch origin "%INSTALL_BRANCH%" >nul 2>&1
    if !ERRORLEVEL! equ 0 (
        git -C "%INSTALL_DIR%" checkout -B "%INSTALL_BRANCH%" FETCH_HEAD >nul 2>&1
        if !ERRORLEVEL! equ 0 goto :eof
    )
    echo [arize] git fetch/checkout failed — trying pull --ff-only
    git -C "%INSTALL_DIR%" pull --ff-only origin "%INSTALL_BRANCH%" >nul 2>&1 && goto :eof
    git -C "%INSTALL_DIR%" pull --ff-only >nul 2>&1 && goto :eof
    echo [arize] git update failed — re-cloning
    rmdir /s /q "%INSTALL_DIR%" 2>nul
)

if exist "%INSTALL_DIR%" if not exist "%INSTALL_DIR%\.git" (
    echo [arize] Existing non-git install found — removing for fresh clone
    rmdir /s /q "%INSTALL_DIR%" 2>nul
)

where git >nul 2>&1 && (
    echo [arize] Cloning arize-agent-kit...
    git clone --depth 1 --branch "%INSTALL_BRANCH%" "%REPO_URL%" "%INSTALL_DIR%" >nul 2>&1 && goto :eof
    echo [arize] git clone failed — falling back to tarball
)

call :install_repo_tarball
goto :eof

REM --- install_repo_tarball ---
:install_repo_tarball
echo [arize] Downloading arize-agent-kit tarball...
set "TMPZIP=%TEMP%\arize-install-%RANDOM%.tar.gz"
set "TMPDIR=%TEMP%\arize-extract-%RANDOM%"

REM Try PowerShell, then curl
powershell -NoProfile -Command "Invoke-WebRequest -Uri '%TARBALL_URL%' -OutFile '%TMPZIP%'" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    curl -sSfL "%TARBALL_URL%" -o "%TMPZIP%" 2>nul
    if %ERRORLEVEL% neq 0 (
        echo [arize] Failed to download tarball >&2
        exit /b 1
    )
)

if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
REM Extract using tar (available on Windows 10+)
tar xzf "%TMPZIP%" --strip-components=1 -C "%INSTALL_DIR%" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    REM Fallback: use PowerShell to extract
    mkdir "%TMPDIR%" 2>nul
    powershell -NoProfile -Command "& { $gz = [System.IO.File]::OpenRead('%TMPZIP%'); $dec = New-Object System.IO.Compression.GZipStream($gz, [System.IO.Compression.CompressionMode]::Decompress); $tar = '%TMPDIR%\archive.tar'; $fs = [System.IO.File]::Create($tar); $dec.CopyTo($fs); $fs.Close(); $dec.Close(); $gz.Close() }" >nul 2>&1
    tar xf "%TMPDIR%\archive.tar" --strip-components=1 -C "%INSTALL_DIR%" >nul 2>&1
    rmdir /s /q "%TMPDIR%" 2>nul
)
del "%TMPZIP%" 2>nul
echo [arize] Extracted to %INSTALL_DIR%
goto :eof

REM --- setup_venv ---
:setup_venv
set "_SV_PYTHON=%~1"
set "_SV_BACKEND=%~2"

call :venv_python
if not "%VENV_PYTHON%"=="" (
    set "_CHECK=import yaml"
    if "%_SV_BACKEND%"=="arize" set "_CHECK=import yaml; import grpc; import opentelemetry"
    "%VENV_PYTHON%" -c "!_CHECK!" >nul 2>&1
    if !ERRORLEVEL! neq 0 goto :setup_venv_create
    "%VENV_PYTHON%" -c "import core" >nul 2>&1
    if !ERRORLEVEL! neq 0 goto :setup_venv_create
    if not exist "%VENV_DIR%\Scripts\arize-collector-ctl.exe" goto :setup_venv_create
    echo [arize] Collector venv already has required packages
    goto :eof
)
:setup_venv_create

echo [arize] Creating collector venv...
"%_SV_PYTHON%" -m venv "%VENV_DIR%" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [arize] Failed to create venv with %_SV_PYTHON% >&2
    exit /b 1
)

call :venv_pip
if "%VENV_PIP%"=="" (
    echo [arize] pip not found in venv >&2
    exit /b 1
)

echo [arize] Installing arize-agent-kit into collector venv...
"%VENV_PIP%" install --quiet "%INSTALL_DIR%" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [arize] Failed to install arize-agent-kit package >&2
    exit /b 1
)

if "%_SV_BACKEND%"=="arize" (
    echo [arize] Installing Arize AX dependencies...
    "%VENV_PIP%" install --quiet opentelemetry-proto grpcio >nul 2>&1
    if %ERRORLEVEL% neq 0 (
        echo [arize] Warning: Failed to install Arize AX dependencies
    )
)

echo [arize] Collector venv ready at %VENV_DIR%
goto :eof

REM --- write_config ---
:write_config
set "_WC_BACKEND=%~1"
set "_WC_HARNESS=%~2"
set "_WC_PORT=%~3"
set "_WC_PHX_EP=%~4"
set "_WC_PHX_KEY=%~5"
set "_WC_AZ_KEY=%~6"
set "_WC_AZ_SID=%~7"
set "_WC_AZ_EP=%~8"

REM Try adding harness to existing config via Python
call :venv_python
if not "%VENV_PYTHON%"=="" if exist "%CONFIG_FILE%" if not "%_WC_HARNESS%"=="" (
    "%VENV_PYTHON%" -c "import yaml, os; f=open('%CONFIG_FILE%'); c=yaml.safe_load(f) or {}; f.close(); c.setdefault('harnesses',{})['%_WC_HARNESS%']={'project_name':'%_WC_HARNESS%'}; fd=os.open('%CONFIG_FILE%',os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600); fw=os.fdopen(fd,'w'); yaml.safe_dump(c,fw,default_flow_style=False,sort_keys=False); fw.close()" >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        echo [arize] Added harness '%_WC_HARNESS%' to %CONFIG_FILE%
        goto :eof
    )
)

REM Write fresh config
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
(
    echo collector:
    echo   host: "127.0.0.1"
    echo   port: %_WC_PORT%
    echo backend:
    echo   target: "%_WC_BACKEND%"
    echo   phoenix:
    echo     endpoint: "%_WC_PHX_EP%"
    echo     api_key: "%_WC_PHX_KEY%"
    echo   arize:
    echo     endpoint: "%_WC_AZ_EP%"
    echo     api_key: "%_WC_AZ_KEY%"
    echo     space_id: "%_WC_AZ_SID%"
    if not "%_WC_HARNESS%"=="" (
        echo harnesses:
        echo   %_WC_HARNESS%:
        echo     project_name: "%_WC_HARNESS%"
    ) else (
        echo harnesses: {}
    )
) > "%CONFIG_FILE%"
echo [arize] Wrote shared config to %CONFIG_FILE%
goto :eof

REM --- health_check ---
:health_check
set "HC_PORT=%~1"
if "%HC_PORT%"=="" set "HC_PORT=4318"
set "HC_OK=0"
curl -sf --max-time 2 "http://127.0.0.1:%HC_PORT%/health" >nul 2>&1 && set "HC_OK=1"
if "%HC_OK%"=="0" (
    powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:%HC_PORT%/health' -TimeoutSec 2 -UseBasicParsing; exit 0 } catch { exit 1 }" >nul 2>&1 && set "HC_OK=1"
)
goto :eof

REM --- stop_collector ---
:stop_collector
if not exist "%PID_FILE%" goto :eof
set /p _SC_PID=<"%PID_FILE%"
if "%_SC_PID%"=="" ( del "%PID_FILE%" 2>nul & goto :eof )
tasklist /fi "PID eq %_SC_PID%" 2>nul | find "%_SC_PID%" >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [arize] Stopping shared collector ^(PID %_SC_PID%^)...
    taskkill /PID %_SC_PID% >nul 2>&1
    timeout /t 3 /nobreak >nul 2>&1
)
del "%PID_FILE%" 2>nul
goto :eof

REM --- start_collector ---
:start_collector
call :cfg_get "collector.port"
set "_COLL_PORT=%CFG_RESULT%"
if "%_COLL_PORT%"=="" set "_COLL_PORT=4318"

call :health_check "%_COLL_PORT%"
if "%HC_OK%"=="1" (
    echo [arize] Shared collector is already running
    goto :eof
)

REM Clean stale PID file
if exist "%PID_FILE%" (
    set /p _OLD_PID=<"%PID_FILE%"
    tasklist /fi "PID eq !_OLD_PID!" 2>nul | find "!_OLD_PID!" >nul 2>&1
    if %ERRORLEVEL% neq 0 del "%PID_FILE%" 2>nul
)

REM Try venv entry point
call :venv_bin "arize-collector-ctl"
if exist "%VENV_BIN_RESULT%" (
    "%VENV_BIN_RESULT%" start >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        echo [arize] Shared collector started ^(listening on 127.0.0.1:%_COLL_PORT%^)
        goto :eof
    )
)

REM Fallback: launch collector.py directly
set "_COLL_PY=%INSTALL_DIR%\core\collector.py"
call :venv_python
if "%VENV_PYTHON%"=="" ( echo [arize] Warning: Could not find collector runtime & goto :eof )
if not exist "%_COLL_PY%" ( echo [arize] Warning: Collector source not found & goto :eof )

if not exist "%PID_DIR%" mkdir "%PID_DIR%"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo [arize] Starting shared collector...
start /b "" "%VENV_PYTHON%" "%_COLL_PY%" >>"%COLLECTOR_LOG_FILE%" 2>&1

REM Wait for health (up to 3 seconds)
set "_ATTEMPTS=0"
:start_collector_wait
if %_ATTEMPTS% geq 30 goto :start_collector_timeout
call :health_check "%_COLL_PORT%"
if "%HC_OK%"=="1" (
    echo [arize] Shared collector started ^(listening on 127.0.0.1:%_COLL_PORT%^)
    goto :eof
)
timeout /t 1 /nobreak >nul 2>&1
set /a "_ATTEMPTS+=10"
goto :start_collector_wait
:start_collector_timeout
echo [arize] Warning: Collector did not become healthy within 3 seconds
echo [arize] Check logs at %COLLECTOR_LOG_FILE%
goto :eof

REM --- write_collector_launcher ---
:write_collector_launcher
set "_WCL_PYTHON=%~1"
if not exist "%BIN_DIR%" mkdir "%BIN_DIR%"
call :venv_python
if not "%VENV_PYTHON%"=="" set "_WCL_PYTHON=%VENV_PYTHON%"
set "_WCL_SRC=%INSTALL_DIR%\core\collector.py"

(
    echo @echo off
    echo "%_WCL_PYTHON%" "%_WCL_SRC%" %%*
) > "%COLLECTOR_BIN%"
echo [arize] Installed collector launcher at %COLLECTOR_BIN%
goto :eof

REM --- collect_backend_credentials ---
:collect_backend_credentials
set "CRED_PHOENIX_ENDPOINT=http://localhost:6006"
set "CRED_PHOENIX_API_KEY="
set "CRED_ARIZE_API_KEY="
set "CRED_ARIZE_SPACE_ID="
set "CRED_ARIZE_ENDPOINT=otlp.arize.com:443"
set "CRED_COLLECTOR_PORT=4318"
set "CRED_BACKEND_TARGET="

REM Detect from environment
if defined ARIZE_API_KEY if defined ARIZE_SPACE_ID (
    set "CRED_BACKEND_TARGET=arize"
    set "CRED_ARIZE_API_KEY=%ARIZE_API_KEY%"
    set "CRED_ARIZE_SPACE_ID=%ARIZE_SPACE_ID%"
    if defined ARIZE_OTLP_ENDPOINT set "CRED_ARIZE_ENDPOINT=%ARIZE_OTLP_ENDPOINT%"
    goto :eof
)
if defined PHOENIX_ENDPOINT (
    set "CRED_BACKEND_TARGET=phoenix"
    set "CRED_PHOENIX_ENDPOINT=%PHOENIX_ENDPOINT%"
    if defined PHOENIX_API_KEY set "CRED_PHOENIX_API_KEY=%PHOENIX_API_KEY%"
    goto :eof
)

REM Interactive prompt
echo.
echo   Choose a tracing backend:
echo.
echo     1^) Phoenix ^(self-hosted^)
echo     2^) Arize AX ^(cloud^)
echo.
set /p "_CHOICE=  Backend [1/2]: "
if "%_CHOICE%"=="1" goto :cred_phoenix
if /i "%_CHOICE%"=="phoenix" goto :cred_phoenix
if "%_CHOICE%"=="2" goto :cred_arize
if /i "%_CHOICE%"=="arize" goto :cred_arize
echo [arize] Invalid choice: %_CHOICE% >&2
exit /b 1

:cred_phoenix
set "CRED_BACKEND_TARGET=phoenix"
set /p "_EP=  Phoenix endpoint [%CRED_PHOENIX_ENDPOINT%]: "
if not "%_EP%"=="" set "CRED_PHOENIX_ENDPOINT=%_EP%"
set /p "CRED_PHOENIX_API_KEY=  Phoenix API key (blank if none): "
goto :cred_port

:cred_arize
set "CRED_BACKEND_TARGET=arize"
set /p "CRED_ARIZE_API_KEY=  Arize API key: "
if "%CRED_ARIZE_API_KEY%"=="" (
    echo [arize] Arize API key is required >&2
    exit /b 1
)
set /p "CRED_ARIZE_SPACE_ID=  Arize space ID: "
if "%CRED_ARIZE_SPACE_ID%"=="" (
    echo [arize] Arize space ID is required >&2
    exit /b 1
)
set /p "_EP=  Arize OTLP endpoint [%CRED_ARIZE_ENDPOINT%]: "
if not "%_EP%"=="" set "CRED_ARIZE_ENDPOINT=%_EP%"
goto :cred_port

:cred_port
echo.
set /p "_PORT=  Collector port [%CRED_COLLECTOR_PORT%]: "
if not "%_PORT%"=="" set "CRED_COLLECTOR_PORT=%_PORT%"
goto :eof

REM --- setup_shared_collector ---
:setup_shared_collector
set "_SSC_HARNESS=%~1"
echo.
echo [arize] Setting up shared background collector
echo.

if not exist "%BIN_DIR%" mkdir "%BIN_DIR%"
if not exist "%PID_DIR%" mkdir "%PID_DIR%"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

REM Check for existing backend config
set "_EXISTING_BACKEND="
if exist "%CONFIG_FILE%" (
    call :cfg_get "backend.target"
    set "_EXISTING_BACKEND=%CFG_RESULT%"
    if "%_EXISTING_BACKEND%"=="" (
        for /f "tokens=2 delims=: " %%V in ('findstr /r "target:" "%CONFIG_FILE%" 2^>nul') do (
            set "_EXISTING_BACKEND=%%V"
            set "_EXISTING_BACKEND=!_EXISTING_BACKEND:"=!"
        )
    )
)

if not "%_EXISTING_BACKEND%"=="" (
    set "CRED_BACKEND_TARGET=%_EXISTING_BACKEND%"
    echo [arize] Existing backend config found ^(%_EXISTING_BACKEND%^) — adding harness entry
) else (
    call :collect_backend_credentials
)

REM Find Python
call :find_python
if "%FOUND_PYTHON%"=="" (
    echo [arize] Warning: No Python 3.9+ interpreter found
    echo [arize] Install Python 3 and re-run the installer to start the collector
    if "%_EXISTING_BACKEND%"=="" (
        call :write_config "%CRED_BACKEND_TARGET%" "%_SSC_HARNESS%" "%CRED_COLLECTOR_PORT%" "%CRED_PHOENIX_ENDPOINT%" "%CRED_PHOENIX_API_KEY%" "%CRED_ARIZE_API_KEY%" "%CRED_ARIZE_SPACE_ID%" "%CRED_ARIZE_ENDPOINT%"
    )
    goto :eof
)
echo [arize] Found Python: %FOUND_PYTHON%

REM Venv is required for hooks even when core/collector.py is missing from this checkout.
if exist "%INSTALL_DIR%\pyproject.toml" (
    call :setup_venv "%FOUND_PYTHON%" "%CRED_BACKEND_TARGET%"
) else (
    echo [arize] Warning: No pyproject.toml — cannot install Python hook entry points
    echo [arize] Use a full repo checkout, or install.bat claude --branch ^<branch^> ^(or ARIZE_INSTALL_BRANCH^)
)

REM Write/update config
if not "%_EXISTING_BACKEND%"=="" (
    if not "%_SSC_HARNESS%"=="" (
        call :cfg_set "harnesses.%_SSC_HARNESS%.project_name" "%_SSC_HARNESS%"
        echo [arize] Added harness '%_SSC_HARNESS%' to %CONFIG_FILE%
    )
) else (
    call :write_config "%CRED_BACKEND_TARGET%" "%_SSC_HARNESS%" "%CRED_COLLECTOR_PORT%" "%CRED_PHOENIX_ENDPOINT%" "%CRED_PHOENIX_API_KEY%" "%CRED_ARIZE_API_KEY%" "%CRED_ARIZE_SPACE_ID%" "%CRED_ARIZE_ENDPOINT%"
)

if exist "%INSTALL_DIR%\core\collector.py" (
    call :write_collector_launcher "%FOUND_PYTHON%"
    call :start_collector
) else (
    echo [arize] Warning: Collector source not found — collector will not start
    echo [arize] Tip: use a checkout that includes core\collector.py, or set ARIZE_INSTALL_BRANCH when installing
)
goto :eof

REM --- setup_claude ---
:setup_claude
echo.
echo [arize] Setting up Arize tracing for Claude Code
echo.

set "_PLUGIN_DIR=%INSTALL_DIR%\claude-code-tracing"
if not exist "%_PLUGIN_DIR%" set "_PLUGIN_DIR=%INSTALL_DIR%\plugins\claude-code-tracing"
if not exist "%_PLUGIN_DIR%" (
    echo [arize] Claude Code tracing plugin not found in %INSTALL_DIR% >&2
    exit /b 1
)
echo [arize] Plugin installed at: %_PLUGIN_DIR%

set "_SETTINGS_FILE=%USERPROFILE%\.claude\settings.json"
if not exist "%USERPROFILE%\.claude" mkdir "%USERPROFILE%\.claude"

REM Use Python for JSON manipulation
call :venv_python
set "_PY=%VENV_PYTHON%"
if "%_PY%"=="" (
    call :find_python
    set "_PY=%FOUND_PYTHON%"
)
if "%_PY%"=="" (
    echo [arize] Python is required for JSON manipulation but was not found >&2
    exit /b 1
)

if not exist "%VENV_DIR%\Scripts\arize-hook-session-start.exe" (
    echo [arize] Cannot register Claude hooks — missing %VENV_DIR%\Scripts\arize-hook-session-start.exe >&2
    echo [arize] Run: "%VENV_DIR%\Scripts\pip.exe" install "%INSTALL_DIR%" >&2
    echo [arize] Or reinstall after updating the checkout ^(see install.bat --help for --branch^) >&2
    exit /b 1
)

"%_PY%" -c "import json, os, sys; plugin_dir=r'%_PLUGIN_DIR%'; settings_file=r'%_SETTINGS_FILE%'; venv_scripts=r'%VENV_DIR%\Scripts'; HOOKS={'SessionStart':'arize-hook-session-start','UserPromptSubmit':'arize-hook-user-prompt-submit','PreToolUse':'arize-hook-pre-tool-use','PostToolUse':'arize-hook-post-tool-use','Stop':'arize-hook-stop','SubagentStop':'arize-hook-subagent-stop','Notification':'arize-hook-notification','PermissionRequest':'arize-hook-permission-request','SessionEnd':'arize-hook-session-end'}; settings=json.loads(open(settings_file).read()) if os.path.isfile(settings_file) else {}; plugins=settings.setdefault('plugins',[]); hp=any((isinstance(p,str) and p==plugin_dir) or (isinstance(p,dict) and p.get('path')==plugin_dir) for p in plugins); (not hp) and plugins.append({'type':'local','path':plugin_dir}); hooks=settings.setdefault('hooks',{}); [hooks.setdefault(evt,[]).append({'hooks':[{'type':'command','command':os.path.join(venv_scripts,ep+'.exe')}]}) for evt,ep in HOOKS.items() if not any(h.get('command','')==os.path.join(venv_scripts,ep+'.exe') for entry in hooks.get(evt,[]) for h in entry.get('hooks',[]))]; f=open(settings_file,'w'); json.dump(settings,f,indent=2); f.write('\n'); f.close()"

echo [arize] Registered tracing hooks in %_SETTINGS_FILE%
echo.
echo   Tracing:
echo.
if exist "%INSTALL_DIR%\core\collector.py" (
    echo     The shared background collector was started ^(or is already running^) and
    echo     will export spans to your configured backend.
) else (
    echo     Collector source was not in this checkout — start it after a full install:
    echo       arize-collector-ctl start
    echo     ^(Hooks still send spans if the collector is running.^)
)
echo.
echo     View collector logs:     type %COLLECTOR_LOG_FILE%
echo.
echo [arize] Setup complete! Test with: set ARIZE_DRY_RUN=true ^& claude
goto :eof

REM --- setup_cursor ---
:setup_cursor
echo.
echo [arize] Setting up Arize tracing for Cursor IDE
echo.

set "_PLUGIN_DIR=%INSTALL_DIR%\cursor-tracing"
if not exist "%_PLUGIN_DIR%" set "_PLUGIN_DIR=%INSTALL_DIR%\plugins\cursor-tracing"
if not exist "%_PLUGIN_DIR%" (
    echo [arize] Cursor tracing plugin not found in %INSTALL_DIR% >&2
    exit /b 1
)
echo [arize] Plugin installed at: %_PLUGIN_DIR%

if not exist "%USERPROFILE%\.cursor" mkdir "%USERPROFILE%\.cursor"
set "_STATE_DIR=%STATE_BASE_DIR%\cursor"
if not exist "%_STATE_DIR%" mkdir "%_STATE_DIR%"

set "_HOOKS_FILE=%USERPROFILE%\.cursor\hooks.json"
call :venv_bin "arize-hook-cursor"
set "_HOOK_CMD=%VENV_BIN_RESULT%"

call :venv_python
set "_PY=%VENV_PYTHON%"
if "%_PY%"=="" (
    call :find_python
    set "_PY=%FOUND_PYTHON%"
)
if "%_PY%"=="" (
    echo [arize] Python is required for JSON manipulation but was not found >&2
    exit /b 1
)

"%_PY%" -c "import json,os,shutil; hooks_file=r'%_HOOKS_FILE%'; hook_cmd=r'%_HOOK_CMD%'; events=['beforeSubmitPrompt','afterAgentResponse','afterAgentThought','beforeShellExecution','afterShellExecution','beforeMCPExecution','afterMCPExecution','beforeReadFile','afterFileEdit','stop','beforeTabFileRead','afterTabFileEdit']; hd=json.loads(open(hooks_file).read()) if os.path.isfile(hooks_file) else {'version':1,'hooks':{}}; os.path.isfile(hooks_file) and shutil.copy2(hooks_file,hooks_file+'.bak'); h=hd.setdefault('hooks',{}); [h.setdefault(e,[]).append({'command':hook_cmd}) for e in events if not any(x.get('command')==hook_cmd for x in h.get(e,[]))]; f=open(hooks_file,'w'); json.dump(hd,f,indent=2); f.write('\n'); f.close()"

echo [arize] Registered Arize hooks in %_HOOKS_FILE%
echo.
echo   Cursor tracing setup complete!
echo.
echo   Next steps:
echo     1. Restart Cursor IDE to pick up the new hooks
echo     2. Start a conversation — spans will appear in your configured backend
echo.
echo [arize] Setup complete!
goto :eof

REM --- setup_codex ---
:setup_codex
echo.
echo [arize] Setting up Arize tracing for Codex CLI
echo.

set "_PLUGIN_DIR=%INSTALL_DIR%\codex-tracing"
if not exist "%_PLUGIN_DIR%" set "_PLUGIN_DIR=%INSTALL_DIR%\plugins\codex-tracing"
if not exist "%_PLUGIN_DIR%" (
    echo [arize] Codex tracing plugin not found in %INSTALL_DIR% >&2
    exit /b 1
)
echo [arize] Plugin installed at: %_PLUGIN_DIR%

set "_CODEX_CONFIG_DIR=%USERPROFILE%\.codex"
set "_CODEX_CONFIG=%_CODEX_CONFIG_DIR%\config.toml"
set "_ENV_FILE=%_CODEX_CONFIG_DIR%\arize-env.sh"
call :venv_bin "arize-hook-codex-notify"
set "_NOTIFY_CMD=%VENV_BIN_RESULT%"
call :resolve_setup_python
set "_PY=%SETUP_PYTHON%"

if "%_PY%"=="" (
    echo [arize] Python is required for Codex config manipulation but was not found >&2
    exit /b 1
)

call :normalize_codex_env_file "%_PY%" "%_ENV_FILE%"
if %ERRORLEVEL% neq 0 (
    echo [arize] Failed to write Codex env file at %_ENV_FILE% >&2
    exit /b 1
)
echo [arize] Ensured Codex env file uses export syntax at %_ENV_FILE%

REM Add [otel] exporter
call :cfg_get "collector.port"
set "_COLL_PORT=%CFG_RESULT%"
if "%_COLL_PORT%"=="" set "_COLL_PORT=4318"

call :update_codex_config "%_PY%" "%_CODEX_CONFIG%" "%_NOTIFY_CMD%" "%_COLL_PORT%"
if %ERRORLEVEL% neq 0 (
    echo [arize] Failed to update Codex config.toml at %_CODEX_CONFIG% >&2
    exit /b 1
)
echo [arize] Updated notify hook and [otel] exporter in config.toml

echo.
echo   Codex tracing setup complete!
echo.
echo     - Notify hook in %_CODEX_CONFIG%
echo     - OTLP exporter in %_CODEX_CONFIG% (port %_COLL_PORT%)
echo     - Env file template at %_ENV_FILE%
echo.
echo [arize] Setup complete! Test with: set ARIZE_DRY_RUN=true ^& codex
goto :eof

REM --- install_skills ---
:install_skills
set "_IS_HARNESS=%~1"
set "_SKILLS_SRC=%INSTALL_DIR%\%_IS_HARNESS%-tracing\skills"
if not exist "%_SKILLS_SRC%" (
    echo [arize] No skills found for %_IS_HARNESS% at %_SKILLS_SRC%
    goto :eof
)
set "_TARGET_DIR=.agents\skills"
if not exist "%_TARGET_DIR%" mkdir "%_TARGET_DIR%"
for /d %%D in ("%_SKILLS_SRC%\*") do (
    set "_SKILL_NAME=%%~nxD"
    set "_LINK=%_TARGET_DIR%\!_SKILL_NAME!"
    if exist "!_LINK!" (
        echo [arize] Skipping !_SKILL_NAME!: already exists
    ) else (
        REM Use mklink for directory junction (no admin required)
        mklink /j "!_LINK!" "%%D" >nul 2>&1
        echo [arize] Linked skill: !_LINK! -^> %%D
    )
)
goto :eof

REM --- update_install ---
:update_install
echo.
echo [arize] Updating arize-agent-kit
echo.

if not exist "%INSTALL_DIR%" (
    echo [arize] arize-agent-kit is not installed at %INSTALL_DIR% >&2
    echo [arize] Run install first: install.bat claude, install.bat codex, or install.bat cursor >&2
    exit /b 1
)

call :stop_collector

if exist "%INSTALL_DIR%\.git" (
    echo [arize] Pulling latest changes...
    git -C "%INSTALL_DIR%" pull --ff-only >nul 2>&1
    if %ERRORLEVEL% neq 0 (
        echo [arize] Fast-forward pull failed — re-cloning
        rmdir /s /q "%INSTALL_DIR%" 2>nul
        call :install_repo
    )
) else (
    echo [arize] No git repo found — re-downloading
    rmdir /s /q "%INSTALL_DIR%" 2>nul
    call :install_repo
)

if exist "%INSTALL_DIR%\core\collector.py" (
    call :venv_python
    set "_UPD_PY=%VENV_PYTHON%"
    if "%_UPD_PY%"=="" (
        call :find_python
        set "_UPD_PY=%FOUND_PYTHON%"
    )
    if not "%_UPD_PY%"=="" (
        call :venv_pip
        if not "%VENV_PIP%"=="" (
            echo [arize] Reinstalling package...
            "%VENV_PIP%" install --quiet "%INSTALL_DIR%" >nul 2>&1
        )
        call :write_collector_launcher "%_UPD_PY%"
    ) else (
        echo [arize] No Python found — collector will not start
        goto :eof
    )
)

call :start_collector
echo [arize] Update complete! Re-run install.bat to reconfigure harness settings.
goto :eof

REM --- do_uninstall ---
:do_uninstall
echo.
echo [arize] Uninstalling arize-agent-kit
echo.

echo [arize] Stopping shared collector...
call :stop_collector

REM Clean up Claude settings
set "_SETTINGS_FILE=%USERPROFILE%\.claude\settings.json"
if exist "%_SETTINGS_FILE%" (
    call :venv_python
    set "_PY=%VENV_PYTHON%"
    if "%_PY%"=="" (
        call :find_python
        set "_PY=%FOUND_PYTHON%"
    )
    if not "%_PY%"=="" (
        "%_PY%" -c "import json,os; sf=r'%_SETTINGS_FILE%'; s=json.loads(open(sf).read()); pd=r'%INSTALL_DIR%\claude-code-tracing'; lp=r'%INSTALL_DIR%\plugins\claude-code-tracing'; s['plugins']=[p for p in s.get('plugins',[]) if not((isinstance(p,str) and p in(pd,lp))or(isinstance(p,dict) and p.get('path') in(pd,lp)))]; nh={}; [nh.update({e:[en for en in ents if [h for h in en.get('hooks',[]) if 'arize' not in h.get('command','') and 'claude-code-tracing' not in h.get('command','')]]}) for e,ents in s.get('hooks',{}).items()]; nh={k:v for k,v in nh.items() if v}; s['hooks']=nh if nh else s.pop('hooks',None); ek=['ARIZE_TRACE_ENABLED','PHOENIX_ENDPOINT','PHOENIX_API_KEY','ARIZE_API_KEY','ARIZE_SPACE_ID','ARIZE_OTLP_ENDPOINT','ARIZE_PROJECT_NAME','ARIZE_USER_ID','ARIZE_DRY_RUN','ARIZE_VERBOSE','ARIZE_LOG_FILE']; [s.get('env',{}).pop(k,None) for k in ek]; f=open(sf,'w'); json.dump(s,f,indent=2); f.write('\n'); f.close()" >nul 2>&1
        echo [arize] Cleaned up Claude settings.json
    )
)

REM Remove Cursor hooks
if exist "%USERPROFILE%\.cursor\hooks.json" (
    if not "%_PY%"=="" (
        "%_PY%" -c "import json,os; hf=r'%USERPROFILE%\.cursor\hooks.json'; hd=json.loads(open(hf).read()); h=hd.get('hooks',{}); nh={e:[x for x in ents if 'arize' not in x.get('command','').lower()] for e,ents in h.items()}; nh={k:v for k,v in nh.items() if v}; (not nh) and os.unlink(hf) or (hd.update({'hooks':nh}), open(hf,'w').write(json.dumps(hd,indent=2)+'\n'))" >nul 2>&1
        echo [arize] Cleaned up Cursor hooks.json
    )
)

REM Remove shared runtime
echo [arize] Removing shared collector runtime...
if exist "%COLLECTOR_BIN%" del "%COLLECTOR_BIN%" 2>nul
if exist "%PID_FILE%" del "%PID_FILE%" 2>nul
if exist "%COLLECTOR_LOG_FILE%" del "%COLLECTOR_LOG_FILE%" 2>nul
if exist "%VENV_DIR%" ( rmdir /s /q "%VENV_DIR%" 2>nul & echo [arize] Removed collector venv )

REM Remove config and install directory
if exist "%CONFIG_FILE%" ( del "%CONFIG_FILE%" 2>nul & echo [arize] Removed %CONFIG_FILE% )
if exist "%INSTALL_DIR%" (
    rmdir /s /q "%INSTALL_DIR%" 2>nul
    echo [arize] Removed %INSTALL_DIR%
) else (
    echo [arize] Repository checkout already absent at %INSTALL_DIR%
)

echo.
echo   The following may need manual cleanup:
echo.
echo   - Claude Agent SDK: remove any hardcoded local plugin path from your application code
echo   - Claude Code marketplace installs are managed separately by Claude
echo.
echo [arize] Uninstall complete.
goto :eof

REM --- Usage ---
:usage
echo.
echo   Arize Agent Kit Installer
echo.
echo   Usage: install.bat ^<command^> [flags]
echo.
echo   Commands:
echo     claude      Install and configure tracing for Claude Code / Agent SDK
echo     codex       Install and configure tracing for OpenAI Codex CLI
echo     cursor      Install and configure tracing for Cursor IDE
echo     update      Update the installed arize-agent-kit to latest
echo     uninstall   Remove arize-agent-kit and print cleanup reminders
echo.
echo   Flags:
echo     --with-skills   Symlink harness skills into .agents\skills\ in the current directory
echo     --branch NAME   Install from a specific git branch (default: main)
echo.
echo   Examples:
echo     install.bat claude
echo     install.bat codex --with-skills
echo     install.bat cursor --branch dev
echo     install.bat update
echo     install.bat uninstall
echo.
exit /b 1
