#!/usr/bin/env python3
"""원문(source/*.md)이 원서의 글을 빠짐없이 담고 있는지 검사한다.

정규화기는 조용히 글을 잃는다. 머리말로 오인해 지우거나, 도판 영역에 삼켜지거나,
표로 잡혔다가 버려진다. 눈으로는 잘 보이지 않는다 — 실제로 이 검사를 만들고 나서야
원서 p.105의 용어집 표제어 'Printer' 와 p.20의 사진 캡션이 사라져 있던 것을 알았다.

방법: 원서 페이지의 텍스트 블록마다, 그 글이 해당 청크의 md 안에 있는지 본다.
비교 전에 양쪽을 같은 모양으로 만든다 — 마크다운 표시·페이지 마커·앵커를 걷어내고,
줄 끝 하이픈을 붙이고, 숫자를 뺀다(각주 위첨자 번호가 md 에서는 앵커로 바뀌므로).

시각 판독으로 통째 대체한 구간(도해·도표)은 글자가 달라지는 것이 정상이다.
source/overrides/<청크>.yaml 에 적힌 구간은 건너뛴다.

    .venv/bin/python scripts/check_coverage.py           # 전체
    .venv/bin/python scripts/check_coverage.py ch03      # 한 청크
    .venv/bin/python scripts/check_coverage.py --gate    # 누락 있으면 종료코드 1
"""
import os
import re
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glossary_io as G

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIN_LEN = 25          # 이보다 짧은 조각은 우연히 일치할 수 있어 보지 않는다


def norm(s):
    s = re.sub(r"<!--.*?-->", " ", s, flags=re.S)
    s = re.sub(r"\[원서 p\.[^\]]*\]", " ", s)
    s = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r" \1 ", s)   # 캡션·링크 문구는 살린다
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"([A-Za-z])-\s*([a-z])", r"\1\2", s)     # 줄 끝 하이픈 복원
    return re.sub(r"[^a-z]+", "", s.lower())


def replaced_pages(cid):
    """시각 판독으로 통째 대체한 쪽 — 글자가 달라지는 것이 정상이다."""
    f = os.path.join(ROOT, "source", "overrides", cid + ".yaml")
    if not os.path.exists(f):
        return set()
    try:
        d = yaml.safe_load(open(f, encoding="utf-8")) or {}
    except Exception:
        return set()
    pages = {str(r.get("page")) for r in (d.get("resolved") or [])
             if r.get("verdict") == "replace_region"}
    pages |= {str(x.get("page")) for x in (d.get("diagrams") or [])}
    return pages


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    gate = "--gate" in sys.argv
    M = yaml.safe_load(open(os.path.join(ROOT, "structure-map.yaml"), encoding="utf-8"))
    doc = G.open_source_pdf(os.path.join(ROOT, M["source"]))
    # 인쇄된 쪽번호는 PDF 페이지 라벨에서 가져온다. 산술(파일번호 - 오프셋)로 구하면
    # 앞부분의 로마숫자(i~xii)에서 어긋난다.
    def printed_of(i):
        try:
            return (doc[i].get_label() or "").strip() or str(i + 1)
        except Exception:
            return str(i + 1)
    chunks = [c for k in ("front_matter", "chapters", "back_matter")
              for c in (M.get(k) or [])]
    total = 0
    for c in chunks:
        cid = c["id"]
        if args and cid not in args:
            continue
        src = os.path.join(ROOT, "source", cid + ".md")
        if not os.path.exists(src):
            continue
        md = norm(open(src, encoding="utf-8").read())
        skip = replaced_pages(cid)
        a, b = c["file"]
        miss = []
        for i in range(a - 1, b):
            printed = printed_of(i)
            if printed in skip:
                continue
            for blk in doc[i].get_text("dict")["blocks"]:
                if blk.get("type") != 0:
                    continue
                t = " ".join("".join(s["text"] for s in l["spans"])
                             for l in blk["lines"]).strip()
                n = norm(t)
                if len(n) >= MIN_LEN and n not in md:
                    miss.append((printed, t))
        total += len(miss)
        print("%-8s %s" % (cid, "누락 없음" if not miss else "누락 의심 %d블록" % len(miss)))
        for p, t in miss[:6]:
            print("     원서 p.%-4s %r" % (p, t[:88]))
        if len(miss) > 6:
            print("     … 외 %d건" % (len(miss) - 6))
    print("\n합계 %d블록" % total)
    if gate and total:
        print("\n원서에 있는 글이 원문(source/)에서 빠졌습니다.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
