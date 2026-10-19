@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 퍼플루 업데이트

rem GitHub(lagem1535-create/PPB)에서 최신 코드를 받아 오고, 퍼플루를 다시 켠다.
rem 내 데이터(data 폴더)는 GitHub에 없으니 그대로 남아요.
where git >nul 2>&1 || (echo [퍼플루] Git이 없어요. https://git-scm.com 에서 설치해 주세요. & pause & exit /b 1)
echo [퍼플루] 최신 버전 받는 중...
git pull --ff-only || (
  echo [퍼플루] 받기 실패. 이 폴더에서 직접 고친 파일이 있으면 충돌할 수 있어요.
  pause & exit /b 1
)
call run.bat
