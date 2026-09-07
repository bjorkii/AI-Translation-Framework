#!/usr/bin/env python3
"""번역 컨텍스트 패키징 (파이프라인 3·4절).

청크에 실제로 등장하는 용어만 골라내고, TM 유사 문장과 톤 앵커를 함께 묶어
1차 번역 단계에 넘길 컨텍스트를 만든다. 용어집 전체를 프롬프트에 넣지 않기 위함.

    python3 scripts/build_context.py ch01
    python3 scripts/build_context.py ch01 --json     # 기계 판독용
"""
import json, os, re, sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glossary_io as G

ROOT = Path(__file__).resolve().parent.parent

def parse_glossary():
    return G.load()

def find_terms(text, entries):
    """청크 본문에 실제로 등장하는 용어만 (단어 경계 · 복수형 허용)"""
    body = re.sub(r"\s+", " ", text)
    hits = []
    for e in entries:
        core = re.escape(e["term"]).replace(r"\ ", r"\s+")
        pat = r"(?<![A-Za-z0-9])" + core + r"(?:s|es)?(?![A-Za-z0-9])"
        flags = 0 if e["term"].isupper() else re.I
        n = len(re.findall(pat, body, flags))
        if n:
            hits.append(dict(e, count=n))
    return sorted(hits, key=lambda x: -x["count"])

def tm_examples(limit=5):
    """승인된 챕터의 원문-번역문 쌍 (아직 없으면 빈 목록)"""
    f = ROOT / "tm" / "approved.jsonl"
    if not f.exists():
        return []
    rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
    return rows[:limit]

def tone_anchor():
    """톤 앵커로 지정된 챕터 (guide/tone-and-decision.md의 anchor 표시)"""
    g = (ROOT / "guide/tone-and-decision.md").read_text(encoding="utf-8")
    m = re.search(r"^-\s*\*\*\[톤 앵커\]\*\*\s*(\S+)", g, re.M)
    return m.group(1) if m else None

def visual_gate(cid):
    """원문 구조가 확인되지 않은 청크는 번역 컨텍스트를 내주지 않는다."""
    import subprocess, sys
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_visual.py"), cid, "--gate"],
                       capture_output=True, text=True)
    if r.returncode:
        print(r.stdout.rstrip())
        print("\n중단했습니다. 시각 판독을 마친 뒤 다시 실행해 주세요.")
        sys.exit(1)

def main(cid, as_json=False):
    src = ROOT / "source" / (cid + ".md")
    if not src.exists():
        print("정규화된 원문이 없습니다: source/%s.md" % cid); return
    visual_gate(cid)
    text = src.read_text(encoding="utf-8")
    entries = parse_glossary()
    hits = find_terms(text, entries)
    decided = [h for h in hits if h["translation"] and not h["tbd"]]
    pending = [h for h in hits if h["tbd"]]
    unknown = [h for h in hits if not h["translation"] and not h["tbd"]]

    ctx = {"chunk": cid, "chars": len(text),
           "glossary_hits": len(hits), "decided": decided,
           "pending": pending, "unknown": unknown,
           "tm": tm_examples(), "tone_anchor": tone_anchor()}
    if as_json:
        print(json.dumps(ctx, ensure_ascii=False, indent=1)); return

    print("=== %s 번역 컨텍스트 ===" % cid)
    print("원문 %d자 · 용어집에서 %d개 적중 (전체 %d개 중)" % (len(text), len(hits), len(entries)))
    print("\n[확정 용어 %d개 — 이대로 사용]" % len(decided))
    for h in decided:
        note = ("  ※ " + h["notation"]) if h["notation"] else ""
        # 맥락에 따라 번역어가 갈리는 용어는 조건까지 함께 싣는다.
        # 이것이 없으면 번역하는 쪽이 기본값 하나만 보고 맥락 구분을 잃는다.
        print("  %-22s → %-14s (%d회)%s" % (h["term"], G.describe(h), h["count"], note))
    if pending:
        print("\n[결정 대기 %d개 — [TBD] 표시하고 넘어갈 것]" % len(pending))
        for h in pending:
            print("  %-22s   후보: %s (%d회)" % (h["term"], h["tbd"], h["count"]))
    if unknown:
        print("\n[미검토 %d개 — 번역하며 판단하고 용어집에 올릴 것]" % len(unknown))
        for h in unknown:
            print("  %-22s (%d회)%s" % (h["term"], h["count"],
                  ("  " + (h["definition_en"] or "")[:60]) if h["definition_en"] else ""))
    print("\n[TM 유사 문장] %s" % (("%d건" % len(ctx["tm"])) if ctx["tm"] else "없음 (첫 챕터)"))
    print("[톤 앵커] %s" % (ctx["tone_anchor"] or "없음 (첫 챕터)"))

if __name__ == "__main__":
    main(sys.argv[1], "--json" in sys.argv)
