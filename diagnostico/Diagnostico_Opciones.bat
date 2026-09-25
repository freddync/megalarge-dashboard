@echo off
cd /d "%~dp0"
echo Consultando opciones en Yahoo (NVDA, AAPL, MSFT)...
python diagnostico_opciones.py NVDA AAPL MSFT
echo.
echo Listo. Avisale a Claude para que lea diagnostico_opciones.txt
pause
