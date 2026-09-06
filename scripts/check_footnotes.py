#!/usr/bin/env python3
"""각주 앵커 무결성 검사 — 정규화 결과 전체를 훑는다.

  참조중복    같은 번호의 본문 참조가 두 번 이상 (절 번호 오인 등)
  정의중복    같은 번호의 각주 정의가 두 번 이상 (번호 목록 오인 등)
  정의없는참조 본문에 참조는 있는데 각주 본문이 없음
  참조없는정의 각주 본문은 있는데 본문 참조가 없음

    python3 scripts/check_footnotes.py            # source/ 전체
    python3 scripts/check_footnotes.py ch02       # 특정 청크
    python3 scripts/check_footnotes.py --targets  # chapters/ (번역본)도 함께
"""
import collections, glob, io, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def scan(path):
    t = io.open(path, encoding="utf-8").read()
    back = re.findall(r'id="back-([^"]+)"', t)
    defs = re.findall(r'id="fn-([^"]+)"', t)
    return {
        "참조중복": [k for k, v in collections.Counter(back).items() if v > 1],
        "정의중복": [k for k, v in collections.Counter(defs).items() if v > 1],
        "정의없는참조": sorted(set(back) - set(defs)),
        "참조없는정의": sorted(set(defs) - set(back)),
        "n": len(set(back)),
    }

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    folders = ["source"] + (["chapters"] if "--targets" in sys.argv else [])
    bad = 0
    for folder in folders:
        for f in sorted(glob.glob(str(ROOT / folder / "*.md"))):
            cid = Path(f).stem
            if args and cid not in args:
                continue
            r = scan(f)
            probs = {k: v for k, v in r.items() if k != "n" and v}
            if probs:
                bad += 1
                print("[문제] %s/%s.md  각주 %d개" % (folder, cid, r["n"]))
                for k, v in probs.items():
                    print("   %s: %s" % (k, ", ".join(v)))
            else:
                print("[정상] %s/%s.md  각주 %d개" % (folder, cid, r["n"]))
    print("\n문제 있는 파일 %d개" % bad)
    sys.exit(1 if bad else 0)

main()
