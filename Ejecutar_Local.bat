@echo off
cd /d "%~dp0"
REM Borra el bytecode cacheado: si queda un .pyc viejo (por ejemplo despues de
REM sincronizar cambios via OneDrive), Python puede cargar la version antigua
REM del modulo y fallar con errores tipo "module has no attribute ...".
if exist "__pycache__" rd /s /q "__pycache__"
echo Instalando dependencias (solo la primera vez puede tardar)...
pip install -r requirements.txt >nul 2>&1
echo Abriendo el dashboard en tu navegador (localhost)...
streamlit run app.py
pause
