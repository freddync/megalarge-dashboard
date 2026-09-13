@echo off
cd /d "%~dp0"
echo Reconstruyendo /data desde MegaCap y LargeCap...
python update_data.py
if errorlevel 1 py update_data.py
echo.
echo Si todo salio bien, ahora sube los cambios a GitHub:
echo   git add -A
echo   git commit -m "actualizar datos"
echo   git push
pause
