@echo off
cd /d "%~dp0"
python --version
if errorlevel 1 (
 echo Install Python 3.11 or later and select Add Python to PATH.
 pause
 exit /b 1
)
if not exist .env copy .env.example .env >nul
python app.py
pause
