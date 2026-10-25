@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 퍼플루 시작

rem 처음이면 install&check.bat 을 먼저 (설치·점검은 거기서만)
if not exist .venv\Scripts\pythonw.exe (
  echo [퍼플루] 아직 설치가 안 됐어요. install^&check.bat 을 먼저 두 번 눌러 주세요.
  pause & exit /b 1
)

rem 업데이트로 requirements.txt 가 바뀌었을 때만 조용히 맞추기
fc /b requirements.txt data\requirements.installed >nul 2>&1 || (
  echo [퍼플루] 새 버전에 필요한 프로그램을 맞추는 중...
  .venv\Scripts\python -m pip install -r requirements.txt -q && copy /y requirements.txt data\requirements.installed >nul
)

rem 이미 켜져 있으면 끄고 새로 켜기
wmic process where "CommandLine like '%%purplu.keeper%%'" call terminate >nul 2>&1
wmic process where "name='pythonw.exe' and CommandLine like '%%-m purplu%%'" call terminate >nul 2>&1
if exist data\quit.flag del data\quit.flag
timeout /t 1 >nul
start "" .venv\Scripts\pythonw.exe -m purplu.keeper
echo [퍼플루] 켰어요! 작업 표시줄 오른쪽 아래 트레이의 퍼플루 아이콘을 확인하세요.
timeout /t 2 >nul
