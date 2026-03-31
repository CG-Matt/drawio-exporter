@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "ROOT_DIR=%~dp0"
if "%ROOT_DIR:~-1%"=="\" set "ROOT_DIR=%ROOT_DIR:~0,-1%"
set "MODE="

:parse_args
if "%~1"=="" goto args_done
if /I "%~1"=="--mode" (
  if "%~2"=="" (
    echo Missing value for --mode 1>&2
    exit /b 1
  )
  set "MODE=%~2"
  shift
  shift
  goto parse_args
)
if /I "%~1"=="-h" goto help
if /I "%~1"=="--help" goto help
echo Unknown argument: %~1 1>&2
goto help_error

:args_done
if not defined MODE (
  set /p CHOICE=Select setup mode [1=venv ^(recommended^), 2=global]: 
  if "%CHOICE%"=="" set "MODE=venv"
  if "%CHOICE%"=="1" set "MODE=venv"
  if "%CHOICE%"=="2" set "MODE=global"
)

if /I not "%MODE%"=="venv" if /I not "%MODE%"=="global" (
  echo Invalid mode: %MODE% ^(expected venv or global^) 1>&2
  exit /b 1
)

where py >nul 2>&1
if not errorlevel 1 (
  set "PY=py -3"
) else (
  where python >nul 2>&1
  if not errorlevel 1 (
    set "PY=python"
  ) else (
    echo Python 3 is required. Install Python and ensure py or python is on PATH. 1>&2
    exit /b 1
  )
)

if /I "%MODE%"=="venv" goto mode_venv
if /I "%MODE%"=="global" goto mode_global
exit /b 1

:mode_venv
echo [setup] Creating/updating .venv
%PY% -m venv "%ROOT_DIR%\.venv"
if errorlevel 1 exit /b 1

set "VENV_PY=%ROOT_DIR%\.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
  echo Expected venv python not found at %VENV_PY% 1>&2
  exit /b 1
)

echo [setup] Installing Playwright into .venv
"%VENV_PY%" -m pip install --upgrade pip
if errorlevel 1 exit /b 1
"%VENV_PY%" -m pip install playwright
if errorlevel 1 exit /b 1
"%VENV_PY%" -m playwright install chromium
if errorlevel 1 exit /b 1
goto done

:mode_global
echo [setup] Installing Playwright into global python ^(user site^)
%PY% -m pip install --user --upgrade pip
if errorlevel 1 exit /b 1
%PY% -m pip install --user playwright
if errorlevel 1 exit /b 1
%PY% -m playwright install chromium
if errorlevel 1 exit /b 1

echo [setup] Creating .venv python shim for relative shebang compatibility
if not exist "%ROOT_DIR%\.venv\Scripts" mkdir "%ROOT_DIR%\.venv\Scripts"

if "%PY%"=="py -3" (
  >"%ROOT_DIR%\.venv\Scripts\python.cmd" echo @echo off
  >>"%ROOT_DIR%\.venv\Scripts\python.cmd" echo py -3 %%*
  >"%ROOT_DIR%\.venv\Scripts\python3.cmd" echo @echo off
  >>"%ROOT_DIR%\.venv\Scripts\python3.cmd" echo py -3 %%*
) else (
  >"%ROOT_DIR%\.venv\Scripts\python.cmd" echo @echo off
  >>"%ROOT_DIR%\.venv\Scripts\python.cmd" echo python %%*
  >"%ROOT_DIR%\.venv\Scripts\python3.cmd" echo @echo off
  >>"%ROOT_DIR%\.venv\Scripts\python3.cmd" echo python %%*
)
goto done

:help
echo Usage:
echo   setup.bat [--mode venv^|global]
echo.
echo Options:
echo   --mode ^<venv^|global^>  Choose installation mode.
echo   -h, --help               Show this help.
echo.
echo Modes:
echo   venv    Create/use .venv and install playwright + chromium there.
echo   global  Install playwright for global python ^(user site^) and create
echo           .venv\Scripts\python*.cmd shims for compatibility.
exit /b 0

:help_error
call :help
exit /b 1

:done
echo [setup] Done
exit /b 0
