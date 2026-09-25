@echo off
rem Sube a GitHub los commits locales (trae primero lo que hayan subido las Actions).
cd /d "%~dp0"
echo === git pull --rebase === > _publicar_log.txt
git pull --rebase origin main >> _publicar_log.txt 2>&1
echo === git push === >> _publicar_log.txt
git push origin main >> _publicar_log.txt 2>&1
echo === estado === >> _publicar_log.txt
git status -sb >> _publicar_log.txt 2>&1
type _publicar_log.txt
timeout /t 8
