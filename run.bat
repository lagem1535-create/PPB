@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 퍼플루 시작

rem ---- 1. 파이썬 가상환경 (처음 한 번) ----
if not exist .venv\Scripts\python.exe (
  echo [퍼플루] 처음 설치 중이에요. 몇 분 걸려요...
  python -m venv .venv || (
    echo [퍼플루] 파이썬을 못 찾았어요. https://www.python.org/downloads/ 에서 설치하고
    echo          설치할 때 "Add python.exe to PATH"를 체크해 주세요.
    pause & exit /b 1
  )
)

rem ---- 2. 필요한 패키지: requirements.txt가 바뀌었을 때만 설치·업데이트 ----
if not exist data mkdir data
set "REQ_OK="
if exist data\requirements.installed (
  fc /b requirements.txt data\requirements.installed >nul 2>&1 && set "REQ_OK=1"
)
if not defined REQ_OK (
  echo [퍼플루] 필요한 프로그램을 설치·업데이트하는 중이에요...
  .venv\Scripts\python -m pip install --upgrade pip -q
  .venv\Scripts\python -m pip install -r requirements.txt -q || (
    echo [퍼플루] 설치에 실패했어요. 인터넷 연결과 디스크 공간을 확인해 주세요.
    pause & exit /b 1
  )
  copy /y requirements.txt data\requirements.installed >nul
)

rem ---- 3. Firebase 주소 (설정·대화 저장소) ----
if not exist data\firebase_url.txt (
  echo.
  echo [퍼플루] Firebase Realtime Database 주소가 필요해요.
  echo          예: https://내프로젝트-default-rtdb.asia-southeast1.firebasedatabase.app
  set /p FBURL="주소를 붙여넣고 Enter: "
  call echo %%FBURL%%> data\firebase_url.txt
)

rem ---- 4. 이미 켜져 있으면 끄고 새로 켜기 (업데이트한 코드가 적용되게) ----
wmic process where "name='pythonw.exe' and CommandLine like '%%-m purplu%%'" call terminate >nul 2>&1
timeout /t 1 >nul

rem ---- 5. 켜기 ----
rem 지킴이가 퍼플루를 켜고, 갑자기 꺼지면 다시 켜요 (트레이 "종료"로 끈 건 그대로)
start "" .venv\Scripts\pythonw.exe -m purplu.keeper
echo [퍼플루] 켰어요! 작업 표시줄 트레이의 퍼플루 아이콘을 확인하세요.
timeout /t 2 >nul
