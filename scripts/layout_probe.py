#!/usr/bin/env python3
"""단 구성 / 머리말·꼬리말 / 제목 패턴 조사 (파이프라인 2.0절 규칙 수립용)."""
import sys, re
from collections import Counter, defaultdict
import pymupdf

def main(path):
    doc = pymupdf.open(path)
    n = len(doc)

    # 1) 페이지 상·하단 반복 텍스트(러닝헤드/쪽번호) 탐지
    top, bot = Counter(), Counter()
    for page in doc:
        h = page.rect.height
        for b in page.get_text("dict")["blocks"]:
            if b.get("type") != 0: continue
            txt = " ".join(s["text"] for l in b["lines"] for s in l["spans"]).strip()
            if not txt: continue
            y0 = b["bbox"][1]
            if y0 < h * 0.10: top[re.sub(r"\d+", "#", txt)[:50]] += 1
            elif y0 > h * 0.90: bot[re.sub(r"\d+", "#", txt)[:50]] += 1
    print("[페이지 상단 반복 텍스트 (러닝헤드 후보)]")
    for t, c in top.most_common(8):
        print(f"  {c:>4}회  {t!r}")
    print("\n[페이지 하단 반복 텍스트 (쪽번호/꼬리말 후보)]")
    for t, c in bot.most_common(8):
        print(f"  {c:>4}회  {t!r}")

    # 2) 본문 페이지 단 구성: 블록 좌측 x0 히스토그램 + 페이지별 컬럼 판정
    print("\n[단 구성 판정]")
    col_votes = Counter()
    for i, page in enumerate(doc):
        w = page.rect.width
        xs = []
        for b in page.get_text("dict")["blocks"]:
            if b.get("type") != 0: continue
            txt = " ".join(s["text"] for l in b["lines"] for s in l["spans"]).strip()
            if len(txt) < 40: continue          # 짧은 조각(캡션/제목) 제외
            xs.append(b["bbox"][0])
        if not xs: continue
        right = sum(1 for x in xs if x > w * 0.45)
        left  = sum(1 for x in xs if x <= w * 0.45)
        col_votes["2단 후보" if right >= 1 and left >= 1 else "1단"] += 1
    print(f"  페이지 판정: {dict(col_votes)}")
    print(f"  (페이지 폭 {doc[0].rect.width:.0f}pt, 높이 {doc[0].rect.height:.0f}pt)")

    # 3) 제목 패턴: 큰 폰트 사이즈 상위 스팬 수집
    print("\n[제목 후보 — 폰트 크기 상위]")
    size_map = defaultdict(list)
    for i, page in enumerate(doc):
        for b in page.get_text("dict")["blocks"]:
            if b.get("type") != 0: continue
            for l in b["lines"]:
                for s in l["spans"]:
                    t = s["text"].strip()
                    if t and len(t) > 2:
                        size_map[round(s["size"])].append((i+1, t[:60]))
    for size in sorted(size_map, reverse=True)[:6]:
        items = size_map[size]
        print(f"  {size}pt — {len(items)}개 스팬, 예: ", end="")
        print(" | ".join(f"p.{p} {t}" for p, t in items[:3]))

    # 4) 번호 매겨진 장/절 패턴
    print("\n[장·절 번호 패턴 탐지 (본문 기준)]")
    chap = re.compile(r"^\s*(\d{1,2})\.\s+([A-Z][A-Z \-,’']{6,})\s*$")
    sec  = re.compile(r"^\s*(\d{1,2}\.\d{1,2})\s+(.+)$")
    found_c, found_s = [], []
    for i, page in enumerate(doc):
        for line in page.get_text().splitlines():
            m = chap.match(line)
            if m: found_c.append((i+1, line.strip()[:60]))
            m2 = sec.match(line)
            if m2 and len(line) < 70: found_s.append((i+1, line.strip()[:60]))
    print(f"  대문자 장 제목 패턴: {len(found_c)}건")
    for p, t in found_c[:15]: print(f"    p.{p:>3}  {t}")
    print(f"  절 번호(N.N) 패턴: {len(found_s)}건 (앞 8건)")
    for p, t in found_s[:8]: print(f"    p.{p:>3}  {t}")
    doc.close()

main(sys.argv[1])
