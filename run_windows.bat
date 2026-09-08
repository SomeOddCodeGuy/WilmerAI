@echo off
setlocal DisableDelayedExpansion
python -I "%~dp0Scripts\launch.py" run_waitress.py %*
exit /b %ERRORLEVEL%
