@echo off
rem Copia los FUNDAMENTALES de MegaCap/ y LargeCap/ al dashboard y los publica en GitHub.
rem Antes: correr MegaCap\Actualizar_Financieros.bat y LargeCap\Actualizar_Financieros_LargeCap.bat
rem (los precios NO se tocan: los actualiza la GitHub Action cada hora).
cd /d "%~dp0"
echo === 1/3 Copiando fundamentales al dashboard ===
python update_data.py
if errorlevel 1 (
    echo ERROR en update_data.py. No se publica nada.
    pause
    exit /b 1
)
echo.
echo === 2/3 Commit ===
git add data/fundamentales_variacion data/company_info.json
git diff --cached --quiet
if not errorlevel 1 (
    echo No hay cambios en los fundamentales: nada que publicar.
    pause
    exit /b 0
)
git commit -m "Actualizar fundamentales"
echo.
echo === 3/3 Publicando en GitHub ===
git pull --rebase origin main
git push origin main
echo.
echo Listo. Streamlit Cloud se actualiza solo en 1-2 minutos.
pause
