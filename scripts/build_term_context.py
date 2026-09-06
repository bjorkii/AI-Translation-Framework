#!/usr/bin/env python3
"""용어별 본문 용례를 정규화된 원문(source/*.md)에서 뽑아 term-context.json에 채운다.

원서 PDF가 아니라 source/*.md를 읽는 이유:
  - 조판 줄바꿈이 이미 병합돼 문장이 온전하다
  - 하이픈 분철이 복원돼 있다
  - 페이지 마커로 원서 쪽번호를, 파일명으로 청크를 함께 붙일 수 있다

기존 파일의 손으로 다듬은 options/quotes는 덮어쓰지 않는다(--force 제외).
    python3 scripts/build_term_context.py
    python3 scripts/build_term_context.py --force      # 전부 다시
    python3 scripts/build_term_context.py --quotes 3   # 용어당 인용 수
"""
import io, json, re, sys, yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "glossary" / "term-context.json"
NQ = 2
DEFN = re.compile(r"\b(is|are|means|refers to|called|known as|term|unlike|whereas|consists|defined)\b", re.I)
MARK = re.compile(r"\[원서 p\.([^\]]+)\]")
SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z“\"(])")

def clean(s):
    s = re.sub(r"<a id=\"[^\"]*\"></a>", "", s)          # 각주 앵커
    s = re.sub(r"\[[¹²³⁴⁵⁶⁷⁸⁹⁰]+\]\([^)]*\)", "", s)      # 각주 참조 링크
    s = re.sub(r"\[↩\]\([^)]*\)", "", s)
    s = re.sub(r"\*\*\[각주\]\*\*", "", s)
    s = MARK.sub("", s)
    s = re.sub(r"<!--.*?-->", "", s)
    s = re.sub(r"^\s*[>|]+\s*", "", s)
    # **굵게** / *기울임* 은 그대로 둔다 — 용례를 볼 때 원서의 강조가 보여야
    # 'one-light print' 처럼 소제목인지 본문인지 헷갈리지 않는다.
    s = re.sub(r"[`#]", "", s)
    return re.sub(r"\s+", " ", s).strip()

def sentences_with_pages():
    """(문장, 원서쪽, 청크id) 목록. 페이지 마커는 '여기까지가 p.N' 의미이므로
    뒤따라 나오는 첫 마커의 쪽번호를 그 문장의 쪽으로 본다."""
    out, skipped = [], []
    for f in sorted((ROOT / "source").glob("*.md")):
        cid = f.stem
        raw = io.open(f, encoding="utf-8").read()
        # 정규화가 아직 거친 구간(색인·명단·서지)은 문장이 성립하지 않아 용례로 못 쓴다.
        # 대시보드의 '정규화 재작업 필요' 배지와 같은 기준(불확실 15%)을 쓴다.
        blocks = max(1, len([b for b in raw.split("\n\n") if b.strip()]))
        if raw.count("LINEBREAK-UNCERTAIN") / blocks >= 0.15:
            skipped.append(cid); continue
        # 마커를 분리자로 삼아 (본문덩어리, 쪽번호) 쌍을 만든다
        parts = MARK.split(raw)
        chunks = [(parts[i], parts[i + 1] if i + 1 < len(parts) else "?")
                  for i in range(0, len(parts), 2)]
        for body, page in chunks:
            for s in SPLIT.split(clean(body)):
                s = s.strip()
                if 20 < len(s) < 400:
                    out.append((s, page, cid))
    if skipped:
        print("용례 수집 제외(정규화 재작업 필요): " + ", ".join(skipped))
    return out

def main():
    global NQ
    force = "--force" in sys.argv
    if "--quotes" in sys.argv:
        NQ = int(sys.argv[sys.argv.index("--quotes") + 1])

    gl = yaml.safe_load(io.open(ROOT / "glossary" / "glossary.yaml", encoding="utf-8"))
    terms = [e["term"] for e in gl["entries"]]
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    sents = sentences_with_pages()
    print("문장 %d개 · 용어 %d개" % (len(sents), len(terms)))

    new, filled, kept, empty = {}, 0, 0, []
    for t in terms:
        prev = old.get(t) or {}
        pat = re.compile(r"(?<![A-Za-z0-9])" + re.escape(t).replace(r"\ ", r"\s+") + r"e?s?(?![A-Za-z0-9])", re.I)
        hits = [(s, p, c) for s, p, c in sents if pat.search(s)]
        if prev.get("quotes") and not force:
            # 손으로 다듬어 둔 인용은 그대로 두되, 출처 청크와 등장 횟수만 채운다
            byfirst = {s[:40]: (p, c) for s, p, c in hits}
            for q in prev["quotes"]:
                if not q.get("chunk"):
                    m = byfirst.get(q.get("text", "")[:40])
                    if m: q["page"], q["chunk"] = m
                    else: q["chunk"] = q.get("chunk") or "?"
            prev["hits"] = len(hits)
            prev["chunks"] = sorted({c for _, _, c in hits})
            new[t] = prev; kept += 1; continue
        # 정의문 우선 → 짧은 것 우선 (읽기 부담이 적도록)
        hits.sort(key=lambda h: (0 if len(h[0]) >= 55 else 1,          # 너무 짧은 조각은 뒤로
                                 0 if DEFN.search(h[0]) else 1,
                                 len(h[0])))
        # 같은 청크에서만 뽑히지 않도록 청크를 분산
        picked, seen = [], set()
        for s, p, c in hits:
            if c in seen and len(picked) < NQ and len(hits) > NQ:
                continue
            picked.append({"page": p, "chunk": c, "text": s}); seen.add(c)
            if len(picked) >= NQ: break
        if not picked:
            picked = [{"page": p, "chunk": c, "text": s} for s, p, c in hits[:NQ]]
        rec = dict(prev)
        rec["quotes"] = picked
        rec["hits"] = len(hits)
        rec["chunks"] = sorted({c for _, _, c in hits})
        new[t] = rec
        if picked: filled += 1
        else: empty.append(t)

    OUT.write_text(json.dumps(new, ensure_ascii=False, indent=1), encoding="utf-8")
    print("용례 채움 %d · 기존 유지 %d · 용례 없음 %d" % (filled, kept, len(empty)))
    if empty:
        print("  용례 없음: " + ", ".join(empty[:25]) + (" …" if len(empty) > 25 else ""))

main()
