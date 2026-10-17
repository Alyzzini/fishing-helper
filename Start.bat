@echo off
cd /d "%~dp0"
if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" goto bundled
if exist .venv\Scripts\python.exe goto run
py -3 -m venv .venv
if errorlevel 1 goto error
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto error
:run
.venv\Scripts\python.exe app.py
if errorlevel 1 pause
exit /b
:bundled
"%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" app.py
if errorlevel 1 pause
exit /b
:error
echo Install Python 3 from python.org with the Python launcher enabled, then try again.
pause
