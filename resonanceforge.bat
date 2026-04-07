@echo off
REM ============================================================
REM  ResonanceForge - Master Control Script
REM  Setup / Install / Run (CLI+GUI) / Update / Uninstall
REM ============================================================
setlocal EnableExtensions EnableDelayedExpansion

set "REPO_URL=https://github.com/1samadams/ResonanceForge.git"
set "BRANCH=claude/suno-dsp-pipeline-JUghn"
set "PROJECT_DIR=%~dp0"
set "VENV_DIR=%PROJECT_DIR%.venv"
set "PY=%VENV_DIR%\Scripts\python.exe"

if not "%~1"=="" goto :dispatch

:menu
cls
echo ============================================================
echo   ResonanceForge - Master Control
echo ============================================================
echo   Project: %PROJECT_DIR%
echo   Branch : %BRANCH%
echo ------------------------------------------------------------
echo   1. Setup (clone/init + venv + install everything)
echo   2. Install / Reinstall dependencies
echo   3. Run GUI
echo   4. Run CLI   (prompts for input/output)
echo   5. Update    (git pull + reinstall)
echo   6. Doctor    (check Python, venv, packages)
echo   7. Uninstall (remove .venv)
echo   0. Exit
echo ============================================================
set /p "CHOICE=Select an option: "
if "%CHOICE%"=="1" goto :setup
if "%CHOICE%"=="2" goto :install
if "%CHOICE%"=="3" goto :run_gui
if "%CHOICE%"=="4" goto :run_cli
if "%CHOICE%"=="5" goto :update
if "%CHOICE%"=="6" goto :doctor
if "%CHOICE%"=="7" goto :uninstall
if "%CHOICE%"=="0" goto :eof
goto :menu

:dispatch
if /I "%~1"=="setup"     goto :setup
if /I "%~1"=="install"   goto :install
if /I "%~1"=="gui"       goto :run_gui
if /I "%~1"=="cli"       goto :run_cli
if /I "%~1"=="update"    goto :update
if /I "%~1"=="doctor"    goto :doctor
if /I "%~1"=="uninstall" goto :uninstall
REM Drag-and-drop / one-shot master: any .wav/.flac/.mp3 path as arg1
if exist "%~1" goto :one_shot
echo Unknown command: %~1
echo Usage: resonanceforge.bat [setup^|install^|gui^|cli^|update^|doctor^|uninstall]
exit /b 1

REM ------------------------------------------------------------
:check_python
where py >nul 2>nul
if %ERRORLEVEL%==0 (
    set "PY_LAUNCHER=py -3"
    goto :eof
)
where python >nul 2>nul
if %ERRORLEVEL%==0 (
    set "PY_LAUNCHER=python"
    goto :eof
)
echo [ERROR] Python 3.10+ not found. Install from https://www.python.org/downloads/
exit /b 1

REM ------------------------------------------------------------
:setup
call :check_python || exit /b 1
echo.
echo [1/4] Ensuring repository is present...
if not exist "%PROJECT_DIR%pyproject.toml" (
    where git >nul 2>nul || (echo [ERROR] git not found. & exit /b 1)
    git clone --branch %BRANCH% %REPO_URL% "%PROJECT_DIR%" || exit /b 1
) else (
    echo     repo already present.
)
echo.
echo [2/4] Creating virtual environment...
if not exist "%VENV_DIR%" (
    %PY_LAUNCHER% -m venv "%VENV_DIR%" || exit /b 1
) else (
    echo     venv already exists.
)
echo.
echo [3/4] Upgrading pip...
"%PY%" -m pip install --upgrade pip wheel setuptools || exit /b 1
echo.
echo [4/4] Installing ResonanceForge (+ GUI extras)...
"%PY%" -m pip install -e "%PROJECT_DIR%[gui]" || exit /b 1
echo.
echo Setup complete. Use option 3 to launch the GUI.
pause
if "%~1"=="" goto :menu
goto :eof

REM ------------------------------------------------------------
:install
if not exist "%PY%" ( echo [ERROR] venv missing. Run Setup first. & pause & goto :menu )
"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install -e "%PROJECT_DIR%[gui]"
pause
if "%~1"=="" goto :menu
goto :eof

REM ------------------------------------------------------------
:run_gui
if not exist "%PY%" ( echo [ERROR] venv missing. Run Setup first. & pause & goto :menu )
"%PY%" -m resonanceforge.gui
if "%~1"=="" goto :menu
goto :eof

REM ------------------------------------------------------------
:run_cli
if not exist "%PY%" ( echo [ERROR] venv missing. Run Setup first. & pause & goto :menu )
set /p "INPUT_PATH=Input file or folder: "
set /p "OUTPUT_PATH=Output file or folder: "
"%PY%" -m resonanceforge.cli "%INPUT_PATH%" "%OUTPUT_PATH%"
pause
if "%~1"=="" goto :menu
goto :eof

REM ------------------------------------------------------------
:update
where git >nul 2>nul || (echo [ERROR] git not found. & pause & goto :menu)
pushd "%PROJECT_DIR%"
git fetch origin %BRANCH% || (popd & pause & goto :menu)
git pull origin %BRANCH% || (popd & pause & goto :menu)
popd
if exist "%PY%" (
    "%PY%" -m pip install -e "%PROJECT_DIR%[gui]"
) else (
    echo [WARN] venv missing; run Setup.
)
pause
if "%~1"=="" goto :menu
goto :eof

REM ------------------------------------------------------------
:doctor
echo --- Python ---
where py 2>nul && py -3 --version
where python 2>nul && python --version
echo.
echo --- Venv ---
if exist "%PY%" (
    "%PY%" --version
    "%PY%" -m pip show resonanceforge 2>nul | findstr /I "Name Version Location"
    "%PY%" -c "import pedalboard, pyloudnorm, soundfile, numpy; print('core deps: OK')" 2>nul || echo [WARN] core deps missing
    "%PY%" -c "import tkinterdnd2; print('tkinterdnd2: OK')" 2>nul || echo [INFO] tkinterdnd2 not installed (drag-drop disabled)
) else (
    echo [INFO] venv not created yet.
)
echo.
echo --- Git ---
where git 2>nul && git -C "%PROJECT_DIR%" rev-parse --abbrev-ref HEAD 2>nul
pause
if "%~1"=="" goto :menu
goto :eof

REM ------------------------------------------------------------
:one_shot
if not exist "%PY%" ( echo [ERROR] venv missing. Run Setup first. & exit /b 1 )
set "IN=%~1"
set "OUTDIR=%~dp1mastered"
if not exist "%OUTDIR%" mkdir "%OUTDIR%"
echo Mastering "%IN%" with default preset...
"%PY%" -m resonanceforge.cli "%IN%" "%OUTDIR%" --preset "%PROJECT_DIR%resonanceforge\presets\streaming_-14.json"
pause
goto :eof

REM ------------------------------------------------------------
:uninstall
if exist "%VENV_DIR%" (
    echo Removing %VENV_DIR% ...
    rmdir /S /Q "%VENV_DIR%"
    echo Done.
) else (
    echo Nothing to remove.
)
pause
if "%~1"=="" goto :menu
goto :eof
