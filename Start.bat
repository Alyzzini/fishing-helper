@echo off
setlocal
cd /d "%~dp0"
if exist .venv\Scripts\python.exe goto dependencies
where py >nul 2>nul
if errorlevel 1 goto python
py -3 -m venv .venv
if errorlevel 1 goto error
goto dependencies
:python
python -m venv .venv
if errorlevel 1 goto error
:dependencies
.venv\Scripts\python.exe -c "import tkinter, numpy, PIL" >nul 2>nul
if not errorlevel 1 goto run
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto error
:run
.venv\Scripts\python.exe app.py
if errorlevel 1 pause
exit /b
:error
echo Setup failed. Install Python 3.11 or newer from python.org, then try again.
pause
