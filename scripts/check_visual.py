#!/usr/bin/env python3
"""시각 확인 게이트 — 표·도판·불확실 구간을 사람(또는 AI)이 원본과 대조했는지 검사.

정규화기는 표·도판을 만들 때마다 VISUAL-CHECK 표시를 남긴다. 기계가 만든 표와
잘라낸 그림은 원본과 어긋날 수 있고, 어긋난 원문으로 번역을 시작하면 되돌리기 어렵다.
그래서 번역 착수 전에 이 표시가 모두 해소되어야 한다.

해소 방법: reviews/<청크>-visual.json 에 확인 기록을 남긴다.
    { "p.60 표": {"ok": true, "note": "IPI 표 5열 그대로", "at": "2026-09-06T…"} }

    python3 scripts/check_visual.py            # 전체 현황
    python3 scripts/check_visual.py ch02       # 한 청크
    python3 scripts/check_visual.py ch02 --gate   # 미확인 있으면 종료코드 1
"""
import glob, io, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAT = re.compile(r"<!--\s*(VISUAL-CHECK[^>]*?)\s*-->")
UNC = re.compile(r"<!--\s*(LINEBREAK-UNCERTAIN|LAYOUT-UNCERTAIN[^>]*?)\s*-->")

def items(cid):
    f = ROOT / "source" / (cid + ".md")
    if not f.exists():
        return []
    t = f.read_text(encoding="utf-8")
    out = [("표·도판", m.group(1)) for m in PAT.finditer(t)]
    out += [("불확실", m.group(1)) for m in UNC.finditer(t)]
    return out

def record(cid):
    f = ROOT / "reviews" / ("%s-visual.json" % cid)
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    gate = "--gate" in sys.argv
    cids = args or sorted(Path(p).stem for p in glob.glob(str(ROOT / "source" / "*.md")))
    total_open = 0
    for cid in cids:
        its = items(cid)
        if not its:
            continue
        done = record(cid)
        openi = [x for x in its if not (done.get(x[1]) or {}).get("ok")]
        total_open += len(openi)
        mark = "확인 완료" if not openi else "미확인 %d/%d" % (len(openi), len(its))
        print("%-8s %-14s (표·도판 %d · 불확실 %d)"
              % (cid, mark,
                 sum(1 for k, _ in its if k == "표·도판"),
                 sum(1 for k, _ in its if k == "불확실")))
        for k, v in openi[:6]:
            print("    · [%s] %s" % (k, v[:90]))
        if len(openi) > 6:
            print("    · … 외 %d건" % (len(openi) - 6))
    print("\n미확인 합계: %d건" % total_open)
    if gate and total_open:
        print("\n" + "!" * 60)
        print("원본과 대조하지 않은 표·도판·불확실 구간이 있습니다.")
        print("구조가 어긋난 원문으로 번역을 시작하면 되돌리기 어렵습니다.")
        print("해당 페이지를 눈으로 확인하고 reviews/<청크>-visual.json 에 기록해 주세요.")
        print("!" * 60)
        sys.exit(1)

main()
