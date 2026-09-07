#!/usr/bin/env python3
"""번역본이 원본의 요소를 다 담고 있는지 검사한다 (파이프라인 2.6절 누락 검증).

번역 도중 이미지 한 장이나 표 하나가 조용히 빠지는 일은 눈으로는 잘 잡히지 않는다.
문단이 통째로 사라진 것도 마찬가지다. 원본을 만들 때 기록해 둔 매니페스트와
번역본을 대조해 기계적으로 뽑아낸다.

    .venv/bin/python scripts/check_manifest.py            # 번역이 있는 청크 전부
    .venv/bin/python scripts/check_manifest.py ch01       # 한 청크
    .venv/bin/python scripts/check_manifest.py --gate     # 누락 있으면 종료코드 1
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAN = os.path.join(ROOT, "intermediate", "manifest")
PAGE_MARK = re.compile(r"\[원서 p\.([^\]]+)\]")


def strip_frontmatter(text):
    """번역본 머리의 YAML frontmatter 를 뗀다 (파이프라인 2.7절).

    원문에는 없고 번역본에만 있으므로, 그냥 세면 첫 쪽 문단 수가 늘 하나 더 나온다.
    """
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    return text[end + 4:] if end > 0 else text


def page_blocks(text):
    """번역본을 페이지 마커로 잘라 {쪽: [문단…]} 으로."""
    text = strip_frontmatter(text)
    pages, cur = {}, []
    for block in [b.strip() for b in text.split("\n\n")]:
        if not block:
            continue
        m = PAGE_MARK.fullmatch(block)
        if m:
            pages[m.group(1)] = cur; cur = []; continue
        cur.append(block)
    return pages


def preview_files(cid):
    """사람이 미리보기로 여는 md 전부.

    번역본 하나만 보면 안 된다. 대조 화면은 단계 스냅샷을 나란히 펼쳐 보여주므로,
    그 파일들에도 도판이 있어야 한다. 그림은 AI 번역에만이 아니라 **사람이 감수할 때도
    판단 재료**다 — 사진이 빠진 화면만 보고 캡션의 옳고 그름을 판단할 수는 없다.
    """
    out = [os.path.join(ROOT, "chapters", cid + ".md")]
    out += sorted(glob.glob(os.path.join(ROOT, "stages", cid, "*.md")))
    return [p for p in out if os.path.exists(p)]


def check(cid):
    f = os.path.join(MAN, cid + ".json")
    tgt = os.path.join(ROOT, "chapters", cid + ".md")
    if not os.path.exists(f) or not os.path.exists(tgt):
        return None
    d = json.load(open(f, encoding="utf-8"))
    text = open(tgt, encoding="utf-8").read()
    miss = []

    # 도판은 미리보기로 열리는 모든 md 에 들어 있어야 한다
    for p in preview_files(cid)[1:]:
        st = open(p, encoding="utf-8").read()
        for r in d["records"]:
            if r["type"] == "image" and os.path.basename(r["asset"]) not in st:
                miss.append(("이미지", r["id"],
                             "%s 에 없음" % os.path.relpath(p, ROOT)))

    for r in d["records"]:
        if r["type"] == "image":
            if os.path.basename(r["asset"]) not in text:
                miss.append(("이미지", r["id"], "원서 p.%s" % r["source_page"]))
        elif r["type"] == "footnote":
            if ('id="%s"' % r["id"]) not in text:
                miss.append(("각주", r["id"], "원서 p.%s" % r["source_page"]))

    # 표는 개별 식별자가 없으므로 쪽 단위 개수로 본다
    want = {}
    for r in d["records"]:
        if r["type"] == "table":
            want[r["source_page"]] = want.get(r["source_page"], 0) + 1
    got = {p: sum(1 for b in bs if b.lstrip().startswith("|"))
           for p, bs in page_blocks(text).items()}
    for p, n in want.items():
        if got.get(p, 0) < n:
            miss.append(("표", "원서 p.%s" % p, "원본 %d개 / 번역본 %d개" % (n, got.get(p, 0))))

    # 페이지별 문단 수 (파이프라인 6절의 문단 1:1 유지가 지켜졌는가)
    tp = page_blocks(text)
    gaps = []
    for p in d["pages"]:
        if not p["source_page"]:
            continue
        cnt = len([b for b in tp.get(p["source_page"], []) if not b.startswith("<!--")])
        if cnt != p["paragraph_count"]:
            gaps.append((p["source_page"], p["paragraph_count"], cnt))
    return miss, gaps


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    gate = "--gate" in sys.argv
    cids = args or sorted(os.path.basename(p)[:-5]
                          for p in glob.glob(os.path.join(MAN, "*.json")))
    total = 0
    checked = 0
    for cid in cids:
        r = check(cid)
        if r is None:
            continue
        checked += 1
        miss, gaps = r
        total += len(miss) + len(gaps)
        if not miss and not gaps:
            print("%-8s 누락 없음" % cid)
            continue
        print("%-8s 누락 %d건 · 문단 수 어긋남 %d쪽" % (cid, len(miss), len(gaps)))
        for kind, what, where in miss[:10]:
            print("    · [%s] %s — %s" % (kind, what, where))
        for p, a, b in gaps[:10]:
            print("    · [문단수] 원서 p.%s — 원본 %d개 / 번역본 %d개" % (p, a, b))

    if not checked:
        print("번역본(chapters/*.md)이 아직 없습니다.")
        return 0
    print("\n합계 %d건" % total)
    if gate and total:
        print("\n원본에 있던 요소가 번역본에서 빠졌습니다. 확인해 주세요.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
