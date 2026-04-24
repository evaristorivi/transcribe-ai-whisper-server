@echo off
chcp 65001 >nul
echo.
echo ============================================================
echo   TranscribeAI - Instalacion (primera vez)
echo ============================================================
echo.

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python no encontrado.
    echo         Descarga Python 3.10+ desde https://www.python.org
    pause & exit /b 1
)
for /f "tokens=2" %%v in ('python --version') do set PYVER=%%v
echo [OK] Python %PYVER%

:: Check ffmpeg
ffmpeg -version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [AVISO] ffmpeg no encontrado. Intentando instalar con winget...
    winget install --id Gyan.FFmpeg -e --silent >nul 2>&1
    if %errorlevel% neq 0 (
        echo [AVISO] No se pudo instalar ffmpeg automaticamente.
        echo         Instala manualmente: https://ffmpeg.org/download.html
        echo         O ejecuta en PowerShell:  winget install Gyan.FFmpeg
        echo         Luego vuelve a ejecutar este script.
        echo.
        pause
    ) else (
        echo [OK] ffmpeg instalado
    )
) else (
    echo [OK] ffmpeg detectado
)

:: Create venv
echo.
echo [1/4] Creando entorno virtual Python...
python -m venv venv
if %errorlevel% neq 0 ( echo [ERROR] Fallo al crear venv & pause & exit /b 1 )
echo [OK] Entorno virtual creado

:: Activate
call venv\Scripts\activate.bat

:: Upgrade pip
echo.
echo [2/4] Actualizando pip...
python -m pip install --upgrade pip --quiet

:: PyTorch con CUDA 12.1 (compatible RTX 2080)
echo.
echo [3/4] Instalando PyTorch con CUDA 12.1 (puede tardar unos minutos)...
pip install torch --index-url https://download.pytorch.org/whl/cu121 --quiet
if %errorlevel% neq 0 (
    echo [AVISO] Fallo con CUDA 12.1, intentando CUDA 11.8...
    pip install torch --index-url https://download.pytorch.org/whl/cu118 --quiet
)
echo [OK] PyTorch instalado

:: App dependencies
echo.
echo [4/4] Instalando dependencias de la app...
pip install faster-whisper fastapi "uvicorn[standard]" python-multipart --quiet
if %errorlevel% neq 0 ( echo [ERROR] Fallo al instalar dependencias & pause & exit /b 1 )
echo [OK] Dependencias instaladas

echo.
echo ============================================================
echo   Instalacion completada con exito!
echo.
echo   El modelo Whisper se descargara la primera vez que
echo   inicies el servidor (~1.6 GB para large-v3).
echo.
echo   Para iniciar el servidor ejecuta:  start.bat
echo ============================================================
echo.
pause
