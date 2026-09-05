#!/bin/bash
# 번역 프로젝트 대시보드 — 더블클릭으로 실행합니다.
cd "$(dirname "$0")" || exit 1
PORT=8765

if ! command -v python3 >/dev/null 2>&1; then
  echo "이 대시보드를 실행하려면 Python 3가 필요합니다."
  echo "설치 창을 띄웁니다. 설치가 끝난 뒤 이 파일을 다시 더블클릭해 주세요."
  xcode-select --install 2>/dev/null
  echo; read -n 1 -s -r -p "아무 키나 누르면 창이 닫힙니다."
  exit 1
fi

# 이미 떠 있으면 브라우저만 다시 엽니다.
if curl -s -o /dev/null "http://127.0.0.1:$PORT/" 2>/dev/null; then
  echo "대시보드가 이미 실행 중입니다. 브라우저를 엽니다."
  open "http://127.0.0.1:$PORT/"
  echo; read -n 1 -s -r -p "아무 키나 누르면 창이 닫힙니다."
  exit 0
fi

echo "대시보드를 시작합니다…"
( sleep 1; open "http://127.0.0.1:$PORT/" ) &
echo "브라우저가 열립니다. 이 창을 닫으면 대시보드가 종료됩니다."
echo
exec python3 scripts/dashboard.py
