#!/usr/bin/env python3
"""사용자 결정 수신함의 미확인 항목을 '확인 완료'로 표시합니다.

AI가 사용자 결정을 실제로 반영한 뒤 실행합니다.
    python3 scripts/ack_decisions.py            # 미확인 항목 보기
    python3 scripts/ack_decisions.py --ack "1차 번역에 반영"
"""
import json, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "glossary" / "decision-log.jsonl"

def load():
    if not LOG.exists():
        return []
    return [json.loads(l) for l in LOG.read_text(encoding="utf-8").splitlines() if l.strip()]

def main():
    recs = load()
    pend = [r for r in recs if not r.get("ack")]
    if "--ack" not in sys.argv:
        print("미확인 결정 %d건 / 전체 %d건" % (len(pend), len(recs)))
        for r in pend:
            print("  · [%s] %s → %s%s" % (r["ts"][:16], r["term"], r["choice"],
                                          ("  (메모: %s)" % r["note"]) if r.get("note") else ""))
        if not pend:
            print("  (모두 확인 완료)")
        return
    note = sys.argv[sys.argv.index("--ack") + 1] if len(sys.argv) > sys.argv.index("--ack") + 1 else ""
    now = datetime.now().isoformat(timespec="seconds")
    for r in recs:
        if not r.get("ack"):
            r["ack"] = True; r["ack_at"] = now; r["ack_note"] = note
    LOG.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + "\n", encoding="utf-8")
    print("확인 완료 표시: %d건%s" % (len(pend), ("  · " + note) if note else ""))

main()
