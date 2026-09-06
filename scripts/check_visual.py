#!/usr/bin/env python3
"""시각 판독 관문 — 불확실 표시가 남은 청크는 번역을 시작하지 않는다.

원문 구조가 불확실한 채로 번역하면 그 오류가 모든 후속 단계로 번진다.
따라서 번역 착수 전에 반드시 통과해야 한다.

    python3 scripts/check_visual.py ch02          # 상태 보기
    python3 scripts/check_visual.py ch02 --gate   # 남아 있으면 종료코드 1
"""
import io, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKS = ("LINEBREAK-UNCERTAIN", "LAYOUT-UNCERTAIN", "VISUAL-CHECK")

def count(cid):
    f = ROOT / "source" / (cid + ".md")
    if not f.exists():
        return None
    t = io.open(f, encoding="utf-8").read()
    return {m: len(re.findall(m, t)) for m in MARKS}

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    gate = "--gate" in sys.argv
    if not args:
        print("청크 id를 지정해 주세요."); sys.exit(2)
    bad = 0
    for cid in args:
        c = count(cid)
        if c is None:
            print("원문이 없습니다: source/%s.md" % cid); bad += 1; continue
        n = sum(c.values())
        if n:
            bad += 1
            print("!" * 62)
            print("%s: 원문 구조 미확인 %d건 — 번역을 시작할 수 없습니다." % (cid, n))
            for k, v in c.items():
                if v: print("   %-20s %d건" % (k, v))
            print("  1) python3 scripts/visual_queue.py %s     # 볼 페이지를 렌더" % cid)
            print("  2) 페이지 이미지를 직접 확인")
            print("  3) source/overrides/%s.yaml 에 판단을 기록" % cid)
            print("  4) python3 scripts/normalize_all.py --force %s" % cid)
            print("!" * 62)
        else:
            print("%s: 원문 구조 확인 완료 (불확실 표시 0건)" % cid)
    sys.exit(1 if (gate and bad) else 0)

main()
