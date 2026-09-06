#!/usr/bin/env python3
"""Translation Memory 적재 (파이프라인 4절).

보완이 끝난 청크의 원문·번역문을 문단 단위로 짝지어 tm/approved.jsonl에 쌓는다.
사용자가 직접 확인한 문단(승인/메모)은 confirmed=true로 표시해, 다음 챕터의
컨텍스트에서 우선 인용되도록 한다.

    python3 scripts/build_tm.py ch01
"""
import io, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tm" / "approved.jsonl"
MARKER = re.compile(r"^\[원서 p\.[^\]]+\]$")

def blocks(p):
    t = io.open(p, encoding="utf-8").read()
    t = re.sub(r"^---\n.*?\n---\n", "", t, flags=re.S)          # frontmatter 제거
    return [b.strip() for b in t.split("\n\n") if b.strip()]

def skip(b):
    return (MARKER.match(b) or b.startswith("<!--") or b.startswith("#")
            or "**[각주]**" in b or len(b) < 40)

def main(cid):
    src, tgt = ROOT / "source" / (cid + ".md"), ROOT / "chapters" / (cid + ".md")
    if not (src.exists() and tgt.exists()):
        print("원문 또는 번역본이 없습니다."); return
    A, B = blocks(src), blocks(tgt)
    if len(A) != len(B):
        print("문단 수가 다릅니다 (원문 %d / 번역본 %d). 대응이 깨졌을 수 있습니다." % (len(A), len(B)))
    apr = {}
    f = ROOT / "reviews" / ("%s-approvals.json" % cid)
    if f.exists():
        for k, v in json.loads(f.read_text(encoding="utf-8")).items():
            cur = v.get("current") or (v if v.get("status") else None)
            if cur and cur.get("status") in ("approved", "note"):
                apr[int(k)] = cur["status"]

    OUT.parent.mkdir(exist_ok=True)
    keep = [json.loads(l) for l in OUT.read_text(encoding="utf-8").splitlines()
            if l.strip()] if OUT.exists() else []
    keep = [r for r in keep if r.get("chunk") != cid]           # 같은 청크는 갱신

    rows = []
    for i, (a, b) in enumerate(zip(A, B)):
        if skip(a) or skip(b):
            continue
        rows.append({"chunk": cid, "block": i, "en": a, "ko": b,
                     "confirmed": i in apr, "status": apr.get(i, "")})
    # 사용자가 확인한 문단을 앞으로
    rows.sort(key=lambda r: (0 if r["confirmed"] else 1, r["block"]))
    out = keep + rows
    OUT.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in out) + "\n",
                   encoding="utf-8")
    print("TM 적재: %s 문단 %d쌍 (사용자 확인 %d) · 전체 %d쌍"
          % (cid, len(rows), sum(1 for r in rows if r["confirmed"]), len(out)))

main(sys.argv[1])
