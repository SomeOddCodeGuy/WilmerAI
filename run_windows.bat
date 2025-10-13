@echo off
set "CONFIG_DIR="
set "USER= "

:parse_args
if "%~1"=="" goto :done
if /i "%~1"=="--ConfigDirectory" (
    set "CONFIG_DIR=%~2"
    shift
)
if /i "%~1"=="--User" (
    set "USER=%~2"
    shift
)
shift
goto :parse_args

:done

echo Creating virtual environment...
python -m venv venv
if %ERRORLEVEL% NEQ 0 (
    echo Failed to create virtual environment.
    exit /b %ERRORLEVEL%
)
echo Virtual environment created successfully.

echo Activating virtual environment...
call venv\Scripts\activate
if %ERRORLEVEL% NEQ 0 (
    echo Failed to activate virtual environment.
    exit /b %ERRORLEVEL%
)
echo Virtual environment activated.

echo Installing dependencies from requirements.txt...
pip install -r requirements.txt
if %ERRORLEVEL% NEQ 0 (
    echo Failed to install dependencies.
    exit /b %ERRORLEVEL%
)
echo Dependencies installed successfully.

echo.
echo ========================================
echo Starting WilmerAI with Waitress
echo (Production WSGI server for Windows)
echo ========================================
echo.

REM Pass arguments to run_waitress.py to maintain WilmerAI's config system
if not "%CONFIG_DIR%"=="" (
    if not "%USER%"=="" (
        python run_waitress.py --ConfigDirectory "%CONFIG_DIR%" --User "%USER%"
    ) else (
        python run_waitress.py --ConfigDirectory "%CONFIG_DIR%"
    )
) else if not "%USER%"=="" (
    python run_waitress.py --User "%USER%"
) else (
    python run_waitress.py
)

if %ERRORLEVEL% NEQ 0 (
    echo Failed to start the application.
    exit /b %ERRORLEVEL%
)
