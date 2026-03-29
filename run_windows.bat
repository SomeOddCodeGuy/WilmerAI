@echo off

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

REM Pass all arguments directly to run_waitress.py
python run_waitress.py %*

if %ERRORLEVEL% NEQ 0 (
    echo Failed to start the application.
    exit /b %ERRORLEVEL%
)
