#!/usr/bin/env python3
"""단계 전환 전 사용자 결정 수신함 확인 (강제).

파이프라인 10절 체크리스트 2번을 규칙이 아니라 장치로 만든다.
미확인 결정이 남아 있으면 감수·스냅샷 스크립트가 진행을 멈춘다.

    python3 scripts/check_inbox.py          # 확인만
    python3 scripts/check_inbox.py --gate   # 미확인이 있으면 종료코드 1
"""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "glossary" / "decision-log.jsonl"

def unacked():
    if not LOG.exists():
        return []
    out = []
    for line in LOG.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if not r.get("ack"):
            out.append(r)
    return out

def main():
    pend = unacked()
    if not pend:
        print("수신함 확인: 미확인 결정 없음")
        return 0
    print("!" * 62)
    print("미확인 사용자 결정 %d건 — 반영하기 전에는 다음 단계로 넘어가지 않습니다." % len(pend))
    for r in pend:
        print("  · [%s] %s → %s%s" % (r["ts"][5:16].replace("T", " "), r["term"], r["choice"],
                                      ("  메모: " + r["note"][:70]) if r.get("note") else ""))
    print("반영을 마친 뒤: python3 scripts/ack_decisions.py --ack \"<무엇에 반영했는지>\"")
    print("!" * 62)
    return 1

code = main()
if "--gate" in sys.argv:
    sys.exit(code)
