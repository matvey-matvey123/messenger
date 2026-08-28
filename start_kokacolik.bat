@echo off
chcp 65001 >nul
setlocal
set "PYW="
for /f "delims=" %%i in ('python -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))" 2^>nul') do set "PYW=%%i"
if not defined PYW goto nopython
if not exist "%~dp0desktop_app.py" goto nofile
"%PYW%" -c "import pywebview" >nul 2>nul
if errorlevel 1 goto install
goto run

:install
"%PYW%" -m pip install pywebview -q

:run
start "" "%PYW%" "%~dp0desktop_app.py"
exit /b 0

:nopython
echo Python not found
pause
exit /b 1

:nofile
echo desktop_app.py not found
pause
exit /b 1