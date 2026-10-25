@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 퍼플루 다시 켜기
rem 켜져 있는 퍼플루(와 지킴이)를 끄고 바로 다시 켜요. 설치 확인은 건너뛰어서 빨라요.
echo [퍼플루] 끄는 중...
rem 지킴이를 먼저 꺼야 퍼플루를 끌 때 지킴이가 다시 켜지 않아요
wmic process where "CommandLine like '%%purplu.keeper%%'" call terminate >nul 2>&1
wmic process where "CommandLine like '%%-m purplu%%' and (name='pythonw.exe' or name='python.exe')" call terminate >nul 2>&1
if exist data\quit.flag del data\quit.flag
timeout /t 1 >nul
echo [퍼플루] 켜는 중...
start "" .venv\Scripts\pythonw.exe -m purplu.keeper
echo [퍼플루] 다시 켰어요!
timeout /t 2 >nul
