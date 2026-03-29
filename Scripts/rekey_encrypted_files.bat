@echo off
REM !!! EXPERIMENTAL !!!
REM
REM Re-keys or decrypts WilmerAI encrypted discussion files.
REM
REM Usage:
REM   Re-key:   rekey_encrypted_files.bat --user myuser --api-key OLD_KEY --new-api-key NEW_KEY
REM   Decrypt:  rekey_encrypted_files.bat --user myuser --api-key OLD_KEY
REM
REM This script activates the project's virtual environment so that the
REM cryptography library (and all other dependencies) are available without
REM a separate install.

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."

REM Locate the virtual environment
if exist "%PROJECT_ROOT%\venv\Scripts\activate.bat" (
    set "VENV_DIR=%PROJECT_ROOT%\venv"
) else if exist "%PROJECT_ROOT%\.venv\Scripts\activate.bat" (
    set "VENV_DIR=%PROJECT_ROOT%\.venv"
) else if exist "%PROJECT_ROOT%\.venv1\Scripts\activate.bat" (
    set "VENV_DIR=%PROJECT_ROOT%\.venv1"
) else (
    echo Error: No virtual environment found (checked venv, .venv, .venv1).
    echo Run the main WilmerAI setup script first to create the virtual environment.
    exit /b 1
)

echo Using virtual environment: %VENV_DIR%
call "%VENV_DIR%\Scripts\activate.bat"

python "%SCRIPT_DIR%rekey_encrypted_files.py" %*
