@echo off
chcp 65001 >nul
title 번역 프로젝트 대시보드
cd /d "%~dp0"

set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"

if not defined PY (
  echo.
  echo   이 대시보드를 실행하려면 Python 3가 필요합니다.
  echo.

  rem winget 은 윈도우 10(1809 이상)과 11 에 기본으로 들어 있다. 따로 설치할 것이 없다.
  rem 있으면 여기서 바로 깔아 준다. 없으면 아래 안내로 넘어간다.
  where winget >nul 2>&1
  if errorlevel 1 goto MANUAL

  echo   이 컴퓨터에서 자동 설치가 가능합니다.
  set /p ANS="  지금 설치할까요? (Y/N) "
  if /i not "%ANS%"=="Y" goto MANUAL

  echo.
  echo   설치 중입니다. 몇 분 걸릴 수 있습니다...
  rem --scope user 로 관리자 권한 없이, 사용자 계정에만 설치한다.
  winget install --exact --id Python.Python.3.12 --scope user ^
    --accept-package-agreements --accept-source-agreements
  echo.
  echo   설치가 끝났습니다.
  echo.
  echo   이 창을 닫고 이 파일을 다시 더블클릭해 주세요.
  echo   (새 창이어야 방금 설치한 Python 을 찾을 수 있습니다.)
  echo.
  pause
  exit /b 0

  :MANUAL
  echo   https://www.python.org/downloads/ 에서 내려받아 설치해 주세요.
  echo   설치 화면 첫 페이지의 "Add python.exe to PATH" 를 꼭 체크하셔야 합니다.
  echo.
  pause
  exit /b 1
)

rem 프로젝트 전용 파이썬 환경(.venv)을 준비한다.
rem 컴퓨터에 파이썬이 여러 개 깔려 있어도 늘 같은 환경으로 돌게 하려는 것이다.
%PY% scripts\bootstrap.py --quiet
if errorlevel 1 (
  echo.
  pause
  exit /b 1
)

.venv\Scripts\python.exe scripts\launch.py
