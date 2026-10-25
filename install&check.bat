@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 퍼플루 설치와 점검
echo.
echo  ==========================================
echo    퍼플루 설치와 점검 (처음 한 번)
echo  ==========================================
echo.

rem ---- 1. 파이썬 찾기 (python 또는 py) ----
set "PY="
python --version >nul 2>&1 && set "PY=python"
if not defined PY ( py -3 --version >nul 2>&1 && set "PY=py -3" )
if not defined PY (
  echo [1/5] 파이썬이 없어요.
  where winget >nul 2>&1 && (
    choice /c YN /m "      파이썬을 지금 설치할까요 (winget, 몇 분 걸려요)"
    if not errorlevel 2 (
      winget install -e --id Python.Python.3.13 --accept-package-agreements --accept-source-agreements
      echo.
      echo      설치가 끝났어요. 이 창을 닫고 install^&check.bat 을 다시 두 번 눌러 주세요.
      pause & exit /b 0
    )
  )
  echo      https://www.python.org/downloads/ 에서 설치하고,
  echo      설치 첫 화면에서 "Add python.exe to PATH" 를 꼭 체크해 주세요.
  pause & exit /b 1
)
for /f "tokens=2" %%v in ('%PY% --version 2^>^&1') do echo [1/5] 파이썬 %%v  OK

rem ---- 2. 퍼플루 전용 파이썬 공간 (.venv) ----
if not exist .venv\Scripts\python.exe (
  echo [2/5] 퍼플루 전용 공간을 만드는 중...
  %PY% -m venv .venv || ( echo      만들지 못했어요. & pause & exit /b 1 )
)
echo [2/5] 전용 공간 (.venv)  OK

rem ---- 3. 필요한 프로그램 설치 ----
if not exist data mkdir data
echo [3/5] 필요한 프로그램을 설치·확인하는 중... (처음엔 5~10분)
.venv\Scripts\python -m pip install --upgrade pip -q
.venv\Scripts\python -m pip install -r requirements.txt -q || (
  echo      설치에 실패했어요. 인터넷 연결과 디스크 공간을 확인하고 다시 해 주세요.
  pause & exit /b 1
)
copy /y requirements.txt data\requirements.installed >nul
echo [3/5] 프로그램  OK

rem ---- 4. 있으면 좋은 것 (없어도 퍼플루는 돼요) ----
echo [4/5] 있으면 좋은 것:
where node >nul 2>&1 && ( echo       Node.js  OK  - 예시 MCP, 터미널 에이전트에 써요 ) || ( echo       Node.js  없음  - 예시 MCP, 터미널 에이전트를 쓰려면 nodejs.org 에서 설치 )
where git >nul 2>&1 && ( echo       Git  OK  - update^&restart.bat 으로 최신 버전 받기 ) || ( echo       Git  없음  - 업데이트는 깃허브에서 ZIP 을 다시 받으면 돼요 )
.venv\Scripts\python -c "import PySide6, google.genai, anthropic, openai; print('      프로그램 불러오기  OK')" || ( echo      불러오기 실패 - 이 창을 캡처해서 알려 주세요 & pause & exit /b 1 )

rem ---- 5. 켜기 (처음이면 '퍼플루 시작하기' 창이 떠요) ----
echo [5/5] 퍼플루를 켜요. 처음이면 '퍼플루 시작하기' 창에서 AI 를 고르고 키를 넣어 주세요.
if exist data\quit.flag del data\quit.flag
start "" .venv\Scripts\pythonw.exe -m purplu.keeper
echo.
echo  다 됐어요!  다음부터는 바탕화면의 '퍼플루' 나 run.bat 으로 켜요.
echo  모르는 게 있으면 USE.md 를 열어 보세요.
echo.
pause
