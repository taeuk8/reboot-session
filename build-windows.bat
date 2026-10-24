@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 -m venv .venv
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m pip install -r requirements-build.txt
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m unittest discover -s tests -v
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --name RebootSession app.py
if errorlevel 1 goto fail
echo.
echo Built: dist\RebootSession.exe
pause
exit /b 0
:fail
echo Build failed. Review the error above.
pause
exit /b 1
