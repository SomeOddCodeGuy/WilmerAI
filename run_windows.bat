@echo off
:: Step 1: Create a virtual environment
echo Creating virtual environment...
python -m venv venv
if %ERRORLEVEL% NEQ 0 (
    echo Failed to create virtual environment.
    exit /b %ERRORLEVEL%
)
echo Virtual environment created successfully.

:: Step 2: Activate the virtual environment
echo Activating virtual environment...
call venv\Scripts\activate
if %ERRORLEVEL% NEQ 0 (
    echo Failed to activate virtual environment.
    exit /b %ERRORLEVEL%
)
echo Virtual environment activated.

:: Step 3: Install the required packages
echo Installing dependencies from requirements.txt...
pip install -r requirements.txt
if %ERRORLEVEL% NEQ 0 (
    echo Failed to install dependencies.
    exit /b %ERRORLEVEL%
)
echo Dependencies installed successfully.

:: Step 4: Run the application
echo Starting the application...
python server.py
if %ERRORLEVEL% NEQ 0 (
    echo Failed to start the application.
    exit /b %ERRORLEVEL%
)
echo Application started successfully.
