@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>&1
if errorlevel 1 (
  echo 이 대시보드를 실행하려면 Python 3가 필요합니다.
  echo https://www.python.org/downloads/ 에서 설치한 뒤 다시 실행해 주세요.
  pause
  exit /b 1
)
start "" http://127.0.0.1:8765/
echo 브라우저가 열립니다. 이 창을 닫으면 대시보드가 종료됩니다.
python scripts\dashboard.py
pause
