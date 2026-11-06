@echo off
setlocal

where python >nul 2>nul
if not errorlevel 1 goto run_python

where python3 >nul 2>nul
if not errorlevel 1 goto run_python3

echo FAKE_AGY_PYTHON_NOT_FOUND 1>&2
exit /b 127

:run_python
python "%~dp0fake_agy.py" %*
exit /b %ERRORLEVEL%

:run_python3
python3 "%~dp0fake_agy.py" %*
exit /b %ERRORLEVEL%
