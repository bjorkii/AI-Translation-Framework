#!/usr/bin/env python3
"""번역 착수 게이트 — 청크 하나를 번역해도 되는 상태인지 한 번에 검사한다.

    python3 scripts/gate.py ch02

막는 조건:
  1) 사용자 결정 수신함에 미확인 항목이 있다        (반영 없이 진행하면 지시가 묻힌다)
  2) 각주 앵커가 어긋나 있다                        (참조·정의 불일치)
  3) 마커가 제 페이지 구간을 벗어나 있다
  4) 시각 확인이 끝나지 않은 표·도판·불확실 구간이 있다
  5) 이미 번역된 부분에서 원본의 이미지·표·각주가 빠져 있다
  6) 원문(source/)이 원서의 글을 빠뜨렸다
  7) 용어가 바뀐 뒤 앞 청크에 반영되지 않았다 (6-1절 소급 반영)

5번은 번역을 마친 청크에만 걸린다. 다음 청크로 넘어가기 전에 앞 청크의 누락을
잡아내려는 것이다 — 이미지 한 장이 조용히 빠진 것은 눈으로는 잘 보이지 않는다.
"""
import subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable

def run(name, args, label):
    r = subprocess.run([PY, str(ROOT / name)] + args, capture_output=True, text=True)
    ok = r.returncode == 0
    print("[%s] %s" % ("통과" if ok else "막힘", label))
    if not ok:
        tail = [l for l in (r.stdout or "").splitlines() if l.strip()][-14:]
        for l in tail:
            print("    " + l)
    return ok

def main():
    cid = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else None
    if not cid:
        print("사용법: python3 scripts/gate.py <청크ID>"); sys.exit(2)
    print("=== 번역 착수 검사 · %s ===" % cid)
    results = [
        run("check_inbox.py", ["--gate"], "사용자 결정 수신함"),
        run("check_footnotes.py", [cid], "각주 앵커 무결성"),
        run("check_markers.py", [], "페이지 마커 위치"),
        run("check_visual.py", [cid, "--gate"], "표·도판 시각 확인"),
        run("check_manifest.py", ["--gate"], "번역본 누락 검증(2.6절)"),
        run("check_coverage.py", [cid, "--gate"], "원문 완전성(원서 대조)"),
        run("check_retrofit.py", [], "소급 반영(6-1절)"),
    ]
    if all(results):
        print("\n%s 번역을 시작해도 됩니다." % cid)
        sys.exit(0)
    print("\n막힌 항목을 해소한 뒤 다시 실행해 주세요.")
    sys.exit(1)

main()
