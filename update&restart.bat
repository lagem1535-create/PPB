@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 퍼플루 업데이트 후 다시 켜기
rem GitHub에서 최신 코드를 받고, 필요한 프로그램을 맞춘 뒤 퍼플루를 다시 켜요. 내 data 폴더는 그대로예요.
where git >nul 2>&1 || (echo [퍼플루] Git이 없어요. https://git-scm.com 에서 설치해 주세요. & pause & exit /b 1)
echo [퍼플루] 최신 버전 받는 중...
git pull --ff-only || (
  echo [퍼플루] 받기 실패. 이 폴더에서 직접 고친 파일이 있으면 충돌할 수 있어요.
  pause & exit /b 1
)
call "%~dp0run.bat"
