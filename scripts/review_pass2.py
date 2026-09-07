#!/usr/bin/env python3
"""AI 감수 2차 — 용어집 준수 + 문체 기계 검사 (파이프라인 6절 3단계).

    python3 scripts/review_pass2.py ch01
"""
import re
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glossary_io as G, sys
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent.parent

def load_glossary():
    """확정된 용어만. all_ko 에는 맥락별 대체 번역어까지 담는다."""
    out = []
    for e in G.load():
        if e["translation"] and not e["tbd"]:
            out.append({"term": e["term"], "ko": e["translation"],
                        "all_ko": G.translations(e),
                        "notation": e["notation"],
                        "nomatch": [x.strip() for x in (e.get("nomatch") or "").split("|")
                                    if x.strip()]})
    return out

def main(cid):
    src = (ROOT / "source" / (cid + ".md")).read_text(encoding="utf-8")
    tgt = re.sub(r"^---\n.*?\n---\n", "",
                 (ROOT / "chapters" / (cid + ".md")).read_text(encoding="utf-8"), flags=re.S)
    res, notes = [], []

    # 1) 용어집 준수 + 표기 규칙(첫 등장 병기)
    viol, notation_miss = [], []
    for e in load_glossary():
        hay = src
        for bad in e["nomatch"]:
            hay = re.sub(r"(?<![A-Za-z0-9])" + re.escape(bad) + r"(?![A-Za-z0-9])", " ", hay, flags=re.I)
        core = re.escape(e["term"]).replace(r"\ ", r"\s+")
        pat = r"(?<![A-Za-z0-9])" + core + r"(?:s|es)?(?![A-Za-z0-9])"
        if not re.search(pat, hay, 0 if e["term"].isupper() else re.I):
            continue
        # 맥락에 따라 갈리는 번역어(alternates)도 지킨 것으로 본다.
        # 기본값만 보면 'Storage → 스토리지' 처럼 맥락에 맞게 고른 올바른 번역이
        # 위반으로 잡힌다.
        cands = [re.split(r"[(（]", c)[0].strip() for c in e.get("all_ko") or [e["ko"]]]
        cands = [c for c in cands if c]
        if cands and not any(c in tgt for c in cands):
            viol.append("%s → %s" % (e["term"], " / ".join(cands)))
            continue
        # 표기 규칙: '첫 등장' 병기가 지시된 용어는 원문 표기가 한 번은 나와야 함
        if e["notation"] and "첫 등장" in e["notation"] and "병기" in e["notation"]:
            if e["term"] not in tgt and e["term"].lower() not in tgt.lower():
                notation_miss.append("%s (%s)" % (e["term"], e["notation"][:34]))
    res.append(("용어집 준수", not viol, ("미반영: " + "; ".join(viol)) if viol else "적중 용어 모두 반영"))
    res.append(("표기 규칙(첫 등장 병기)", not notation_miss,
                ("병기 누락: " + "; ".join(notation_miss)) if notation_miss else "규칙 있는 용어 모두 병기됨"))

    # 2) 문장 종결체
    body = re.sub(r"<[^>]+>", "", tgt)
    body = re.sub(r"\[[^\]]*\]\([^)]*\)", "", body)
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n", body) if s.strip()]
    honor = [s for s in sents if re.search(r"(습니다|합니다|입니다|세요)\s*\.?$", s)]
    res.append(("종결체 ~다 일관", not honor,
                ("존댓말 종결 %d곳: %s" % (len(honor), honor[0][:40])) if honor else "존댓말 종결 없음"))

    # 3) 인용부호 일관
    # 표기 방침: 영문 제목은 괄호 없는 이탤릭, 영문이 아닌 제목은 낫표.
    # 따라서 낫표 안에 로마자 제목이 들어간 경우만 위반으로 본다.
    bad_marks = [m for m in re.findall(r"[「『]([^」』]{2,60})[」』]", tgt)
                 if re.search(r"[A-Za-z]{3}", m)]
    res.append(("제목 표기 방침", not bad_marks,
                ("영문 제목에 낫표 사용: %s" % ", ".join(bad_marks)) if bad_marks
                else "영문은 이탤릭, 국문은 낫표로 일관"))

    # 4) 숫자·단위 표기
    cand = re.findall(r"(?<![\d,])\d{4,}(?![\d,])(?!mm|피트)", tgt)
    no_comma = [n for n in cand if not (len(n) == 4 and 1000 <= int(n) <= 2999)]   # 연도 제외
    res.append(("천 단위 쉼표", not no_comma,
                ("쉼표 없는 4자리 이상: %s" % ", ".join(sorted(set(no_comma))[:6])) if no_comma else "일관"))

    # 5) 문장 길이 (참고)
    ko_sents = [s for s in sents if re.search(r"[가-힣]", s) and len(s) > 10]
    if ko_sents:
        lens = sorted(len(s) for s in ko_sents)
        long_ones = [s for s in ko_sents if len(s) > 150]
        notes.append("한국어 문장 %d개 · 중앙값 %d자 · 최장 %d자 · 150자 초과 %d개"
                     % (len(ko_sents), lens[len(lens)//2], lens[-1], len(long_ones)))
        for s in long_ones[:3]:
            notes.append("  긴 문장: %s…" % s[:60])

    # 6) 반복 표현 (참고)
    words = re.findall(r"[가-힣]{2,}", body)
    common = [w for w, c in Counter(words).most_common(12) if c >= 12
              and w not in ("보존", "필름", "영화", "아카이브", "복제", "복원", "이용")]
    if common:
        notes.append("자주 반복되는 표현: " + ", ".join("%s(%d)" % (w, Counter(words)[w]) for w in common[:6]))

    print("=== AI 감수 2차 · 기계 검사 · %s ===" % cid)
    fails = 0
    for name, ok, detail in res:
        if not ok: fails += 1
        print("  [%s] %-22s %s" % ("통과" if ok else "확인", name, detail))
    if notes:
        print("\n  참고")
        for n in notes: print("   ", n)
    print("\n  %d개 항목 중 %d개 확인 필요" % (len(res), fails))

def _inbox_gate():
    """미확인 사용자 결정이 있으면 진행을 멈춘다 (--force로 우회)."""
    import subprocess, sys
    if "--force" in sys.argv:
        return
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_inbox.py"), "--gate"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout)
        print("중단했습니다. 반영 후 다시 실행하거나 --force로 건너뛸 수 있습니다.")
        sys.exit(1)

_inbox_gate()
main(sys.argv[1])
