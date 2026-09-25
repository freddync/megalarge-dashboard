@echo off
rem Toma a mano la foto diaria de Open Interest de las Megacap (lo mismo que hace
rem la Action "Foto diaria de Open Interest" despues del cierre). Correrlo
rem despues de las 16:00 hora de Nueva York. Luego: git add / commit / push.
cd /d "%~dp0"
python scripts\snapshot_oi.py > scripts\_foto_oi_log.txt 2>&1
type scripts\_foto_oi_log.txt | more
echo.
echo Listo. Log en scripts\_foto_oi_log.txt
pause
