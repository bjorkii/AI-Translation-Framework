#!/bin/bash
# 번역 프로젝트 대시보드 — 이 파일을 더블클릭하면 실행됩니다.
# 처음 한 번은 macOS가 막을 수 있습니다.
# 그때는 이 파일을 마우스 오른쪽 버튼으로 누르고 '열기'를 고른 뒤, 다시 '열기'를 누르세요.

cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
  echo "이 대시보드를 실행하려면 Python 3가 필요합니다."
  echo "설치 창을 띄웁니다. 설치가 끝난 뒤 이 파일을 다시 더블클릭해 주세요."
  xcode-select --install 2>/dev/null
  echo
  read -n 1 -s -r -p "아무 키나 누르면 창이 닫힙니다."
  exit 1
fi

exec python3 scripts/launch.py
