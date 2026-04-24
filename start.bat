@echo off
chcp 65001 >nul

:: Check if venv exists
if not exist "env313\Scripts\activate.bat" (
    echo [ERROR] Entorno virtual no encontrado. Ejecuta install.bat primero.
    pause & exit /b 1
)

call env313\Scripts\activate.bat

:: Optional: change model with   set WHISPER_MODEL=medium
:: Available: tiny, base, small, medium, large-v2, large-v3 (default)

:: Open browser after 3 seconds in background
start "" /b cmd /c "timeout /t 3 >nul && start http://localhost:8000"

python server.py
pause
