#!/usr/bin/env python3
"""불확실 표시가 남은 지점을 모아 '눈으로 볼 페이지 목록'을 만든다 (파이프라인 2.0 에스컬레이션).

정규화가 규칙만으로 판단하지 못한 지점에는 표시가 남는다.
  LINEBREAK-UNCERTAIN  문단이 이어지는지 끊기는지 판단 못 함
  LAYOUT-UNCERTAIN     읽기 순서(다단/이미지 옆 텍스트)가 불확실
  VISUAL-CHECK         표·상자를 행·열로 되살렸으나 원본 대조 필요

이 스크립트는 해당 페이지를 이미지로 렌더링하고 대기열을 만든다.
AI가 그 이미지를 직접 보고 판단한 결과를 source/overrides/<청크>.yaml에 적으면
normalize.py가 다음 생성 때 그대로 반영한다. 즉 시각 판독 결과가 보존된다.

    python3 scripts/visual_queue.py            # 전체
    python3 scripts/visual_queue.py ch02       # 특정 청크
"""
import io, json, re, sys, yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN = ROOT / "intermediate" / "pagescan"
MARKERS = {
    "LINEBREAK-UNCERTAIN": "문단이 이어지는지 판단 필요",
    "LAYOUT-UNCERTAIN": "읽기 순서 확인 필요",
    "VISUAL-CHECK": "표·상자 구조 대조 필요",
}
PAGE_IN_MARKER = re.compile(r"p\.([0-9ivxlcdm]+)")

def structure():
    m = yaml.safe_load(io.open(ROOT / "structure-map.yaml", encoding="utf-8"))
    out = {}
    for k in ("front_matter", "chapters", "back_matter"):
        for c in m.get(k) or []:
            out[c["id"]] = c
    return m, out

def overrides(cid):
    f = ROOT / "source" / "overrides" / (cid + ".yaml")
    if not f.exists():
        return []
    d = yaml.safe_load(io.open(f, encoding="utf-8")) or {}
    return d.get("resolved") or []

def scan_chunk(cid):
    f = ROOT / "source" / (cid + ".md")
    if not f.exists():
        return []
    lines = io.open(f, encoding="utf-8").read().splitlines()
    items, page = [], None
    for i, ln in enumerate(lines):
        pm = re.search(r"^\[원서 (p\.[^\]]+)\]$", ln.strip())
        if pm:
            page = pm.group(1)[2:]
        for key in MARKERS:
            if key in ln:
                mp = PAGE_IN_MARKER.search(ln)
                # 마커에 쪽번호가 없으면(LINEBREAK) 뒤따르는 첫 페이지 마커를 쓴다.
                # normalize.apply_overrides 의 판정과 같은 규칙이라야 짝이 맞는다.
                pg = mp.group(1) if mp else next(
                    (m2.group(1) for x in lines[i:]
                     for m2 in [re.search(r"\[원서 p\.([^\]]+)\]", x)] if m2), page)
                ctx = " / ".join(x.strip() for x in lines[max(0,i-2):i+4] if x.strip())
                items.append({"chunk": cid, "line": i + 1, "marker": key,
                              "page": pg or "?", "why": MARKERS[key], "context": ctx[:400]})
    return items

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    _, chunks = structure()
    SCAN.mkdir(parents=True, exist_ok=True)
    todo, resolved_n = [], 0
    for cid in chunks:
        if args and cid not in args:
            continue
        done = {(str(r.get("page")), r.get("marker")) for r in overrides(cid)}
        for it in scan_chunk(cid):
            if (str(it["page"]), it["marker"]) in done:
                resolved_n += 1; continue
            todo.append(it)

    pages = sorted({(t["chunk"], t["page"]) for t in todo})
    if pages:
        import pymupdf
        doc = pymupdf.open(ROOT / "intermediate" / "FilmPreservationGuide-EN.pdf")
        off = yaml.safe_load(io.open(ROOT / "structure-map.yaml", encoding="utf-8"))["page_label_offset"]
        for cid, pg in pages:
            try:
                i = int(pg) + off - 1
            except ValueError:
                continue
            dest = SCAN / ("p%s.png" % pg)
            if not dest.exists():
                doc[i].get_pixmap(dpi=125).save(str(dest))

    (ROOT / "intermediate" / "visual-queue.json").write_text(
        json.dumps({"todo": todo, "resolved": resolved_n}, ensure_ascii=False, indent=1),
        encoding="utf-8")

    print("=== 시각 판독 대기열 ===")
    print("미해결 %d건 · 해결 완료 %d건" % (len(todo), resolved_n))
    bychunk = {}
    for t in todo:
        bychunk.setdefault(t["chunk"], []).append(t)
    for cid, items in bychunk.items():
        pgs = sorted({i["page"] for i in items}, key=lambda x: (len(x), x))
        print("\n  %s — %d건 · 원서 p.%s" % (cid, len(items), ", p.".join(pgs)))
        for i in items:
            print("     %-20s p.%-4s %s" % (i["marker"], i["page"], i["why"]))
    if pages:
        print("\n렌더한 페이지 이미지: %s" % SCAN)
        print("판단 결과는 source/overrides/<청크>.yaml 에 적는다.")

main()
