#!/usr/bin/env python3
"""소급 반영 대상 찾기 (파이프라인 6-1절).

장기 번역에서 가장 흔한 실패는 이것이다 — 9장에서 새로 정한 용어가 2장에는 반영되지
않은 채 남는다. 용어를 확정하거나 바꿀 때마다 사람이 앞 장을 다시 뒤질 수는 없다.

그래서 기계가 찾는다. 이미 번역한 청크에서
  · 그 원어가 원문에 나오는데 번역본에는 확정 번역어가 없거나
  · 예전 번역어로 보이는 낱말이 아직 남아 있으면
'재검토 필요'로 뽑아낸다.

**고치지는 않는다.** 용어집의 번역어는 '이 원어를 이렇게 옮긴다'이지 '이 한국어
낱말을 저 낱말로 바꾼다'가 아니다. 낱말만 갈아끼우면 조사가 어긋나고(언론이 →
매체이), 원문이 다른 낱말인데 우연히 같은 번역어를 쓴 자리까지 함께 바뀐다.
자리를 찾아 주는 데까지가 기계의 몫이고, 무엇으로 바꿀지는 사람이 정한다.

    .venv/bin/python scripts/check_retrofit.py            # 전부
    .venv/bin/python scripts/check_retrofit.py ch01       # 한 청크
    .venv/bin/python scripts/check_retrofit.py --json     # 화면용
"""
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glossary_io as G

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def strip_front(t):
    if not t.startswith("---"):
        return t
    e = t.find("\n---", 3)
    return t[e + 4:] if e > 0 else t


def occurrences(term, text):
    core = re.escape(term).replace(r"\ ", r"\s+")
    pat = r"(?<![A-Za-z0-9])" + core + r"(?:e?s)?(?![A-Za-z0-9])"
    return len(re.findall(pat, text, 0 if term.isupper() else re.I))


def check(cid, entries):
    src = os.path.join(ROOT, "source", cid + ".md")
    tgt = os.path.join(ROOT, "chapters", cid + ".md")
    if not (os.path.exists(src) and os.path.exists(tgt)):
        return []
    s = open(src, encoding="utf-8").read()
    t = strip_front(open(tgt, encoding="utf-8").read())
    out = []
    for e in entries:
        n = occurrences(e["term"], G.strip_nomatch(s, e))
        if not n:
            continue
        allowed = [re.split(r"[(（]", x)[0].strip() for x in G.translations(e)]
        allowed = [x for x in allowed if x]
        if not allowed:
            continue                       # 아직 정하지 않은 용어는 여기 대상이 아니다
        if any(a in t for a in allowed):
            continue                       # 확정 번역어 중 하나가 이미 쓰였다
        out.append({"chunk": cid, "term": e["term"], "hits": n,
                    "expect": allowed, "note": e.get("notation") or ""})
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    entries = [e for e in G.load() if e["translation"] and not e["tbd"]]
    cids = args or sorted(
        os.path.basename(p)[:-3] for p in glob.glob(os.path.join(ROOT, "chapters", "*.md")))
    rows = []
    for cid in cids:
        rows += check(cid, entries)
    if "--json" in sys.argv:
        print(json.dumps(rows, ensure_ascii=False))
        return 0
    if not rows:
        print("소급 반영 대상 없음 — 번역을 마친 청크가 용어집을 모두 지키고 있습니다.")
        return 0
    print("재검토 필요 %d건 (원문에 있는데 번역본에 확정 번역어가 없음)\n" % len(rows))
    for r in rows:
        print("  %-8s %-24s → %-20s 원문 %d회%s"
              % (r["chunk"], r["term"], " / ".join(r["expect"]), r["hits"],
                 ("  ※ " + r["note"][:40]) if r["note"] else ""))
    print("\n낱말만 갈아끼우지 마세요. 조사가 어긋나고(언론이 → 매체이), 원문이 다른")
    print("낱말인데 같은 번역어를 쓴 자리까지 바뀝니다. 자리마다 문장을 보고 고칩니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
