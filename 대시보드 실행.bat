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
