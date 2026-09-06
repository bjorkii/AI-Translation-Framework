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

%PY% scripts\launch.py
