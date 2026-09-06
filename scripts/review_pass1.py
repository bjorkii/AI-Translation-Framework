#!/usr/bin/env python3
"""AI 감수 1차 — 기계 검증 (파이프라인 6절 2단계).

원문 대조에서 기계가 확실히 잡을 수 있는 것만 먼저 걸러낸다.
의미·뉘앙스 판단은 이 다음의 독립 컨텍스트 감수가 맡는다.

    python3 scripts/review_pass1.py ch01
"""
import json, re, sys
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent.parent

def blocks(md, drop_front=False):
    if drop_front:
        md = re.sub(r"^---\n.*?\n---\n", "", md, flags=re.S)
    return [b.strip() for b in md.split("\n\n") if b.strip()]

def numbers(s):
    """숫자 비교용: 자릿수 구분 쉼표 제거 후 숫자열만 추출"""
    s = re.sub(r"(?<=\d),(?=\d{3})", "", s)
    return Counter(re.findall(r"\d+(?:\.\d+)?", s))

def proper_nouns(s):
    """대문자로 시작하는 고유명사 후보 (문장 첫 단어·전량 대문자 제외)"""
    out = set()
    for m in re.finditer(r"(?<![.!?]\s)(?<!^)\b([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]+)*)\b", s, re.M):
        t = re.sub(r"^(See|Edited|Report|Also)\s+", "", m.group(1))
        if t.split()[0] in ("The", "This", "That", "These", "Those", "In", "It", "As", "By",
                            "For", "From", "Many", "More", "Most", "Not", "Now", "Over",
                            "Since", "Some", "Their", "They", "When", "With", "Like", "Given",
                            "Central", "Community", "Depending", "Even", "Film", "Generally",
                            "Ideally", "Multimedia", "Orphan", "Preservationists", "Today"):
            continue
        out.add(t)
    return out

def main(cid):
    src = (ROOT / "source" / (cid + ".md")).read_text(encoding="utf-8")
    tgt_raw = (ROOT / "chapters" / (cid + ".md")).read_text(encoding="utf-8")
    tgt = re.sub(r"^---\n.*?\n---\n", "", tgt_raw, flags=re.S)   # 서지 정보(frontmatter) 제외
    A, B = blocks(src), blocks(tgt_raw, True)
    res = []

    # 1) 문단 1:1
    res.append(("문단 1:1 대응", len(A) == len(B),
                "원문 %d블록 / 번역본 %d블록" % (len(A), len(B))))

    # 2) 각주 참조·정의·역링크
    def anch(s, pat): return sorted(set(re.findall(pat, s)))
    ok = (anch(src, r"#fn-%s-(\d+)\)" % cid) == anch(tgt, r"#fn-%s-(\d+)\)" % cid)
          and anch(src, r'id="fn-%s-(\d+)"' % cid) == anch(tgt, r'id="fn-%s-(\d+)"' % cid)
          and anch(src, r'id="back-%s-(\d+)"' % cid) == anch(tgt, r'id="back-%s-(\d+)"' % cid))
    res.append(("각주 참조·정의·역링크 보존", ok,
                "참조 %s / 정의 %s" % (anch(tgt, r"#fn-%s-(\d+)\)" % cid), anch(tgt, r'id="fn-%s-(\d+)"' % cid))))

    # 3) 페이지 마커
    pa, pb = re.findall(r"\[원서 (p\.[^\]]+)\]", src), re.findall(r"\[원서 (p\.[^\]]+)\]", tgt)
    res.append(("페이지 마커 보존", pa == pb, "원문 %s / 번역본 %s" % (pa, pb)))

    # 4) 숫자 대조
    na, nb = numbers(src), numbers(tgt)
    only_src = {k: v for k, v in (na - nb).items()}
    only_tgt = {k: v for k, v in (nb - na).items()}
    # 영문 철자 수사(five decades, Ninety percent)가 한국어에서 숫자로 바뀌는 것은 정상이므로
    # 원문에만 있는 숫자(=누락 의심)만 실패로 본다
    res.append(("숫자 보존(누락 의심)", not only_src,
                ("원문에만 있는 숫자 %s" % only_src) if only_src
                else ("없음" + (" · 번역본에서 숫자로 표기된 항목 %s (철자 수사 변환 가능성, 참고)" % only_tgt if only_tgt else ""))))

    # 5) 고유명사 누락
    pn = proper_nouns(src)
    missing = sorted(p for p in pn if p not in tgt)
    # 한국어로 옮겨진 고유명사(Hollywood->할리우드)는 원문 문자열이 남지 않는 것이 정상이므로
    # 실패로 단정하지 않고, 다음 단계(독립 컨텍스트 대조 감수)의 확인 대상으로 넘긴다
    res.append(("고유명사 대조 대상", True,
                ("원문 표기가 남지 않은 %d개 — 한국어 표기 여부를 의미 감수에서 확인: %s"
                 % (len(missing), ", ".join(missing[:12]))) if missing else "모두 원문 표기 유지"))

    # 6) 용어집 준수
    g = (ROOT / "glossary/glossary.yaml").read_text(encoding="utf-8")
    terms = []
    for m in re.finditer(r'  - term: "(.*?)"\n(.*?)(?=\n  - term: |\Z)', g, re.S):
        tr = re.search(r'^\s{4}translation:\s*"(.*?)"', m.group(2), re.M)
        nm = re.search(r'^\s{4}nomatch:\s*"(.*?)"', m.group(2), re.M)
        if tr and 'tbd:' not in m.group(2):
            terms.append((m.group(1), tr.group(1),
                          [x.strip() for x in nm.group(1).split("|")] if nm else []))
    viol = []
    for term, ko, nomatch in terms:
        core = re.escape(term).replace(r"\ ", r"\s+")
        pat = r"(?<![A-Za-z0-9])" + core + r"(?:s|es)?(?![A-Za-z0-9])"
        hay = src
        for bad in nomatch:            # 같은 철자 다른 뜻(예: leaders=지도자)은 제외
            hay = re.sub(r"(?<![A-Za-z0-9])" + re.escape(bad) + r"(?![A-Za-z0-9])", " ", hay, flags=re.I)
        if re.search(pat, hay, 0 if term.isupper() else re.I):
            base = re.split(r"[(（]", ko)[0].strip()
            if base and base not in tgt:
                viol.append("%s → %s" % (term, ko))
    res.append(("용어집 준수", not viol,
                ("미반영 %d건: %s" % (len(viol), "; ".join(viol))) if viol else "적중 용어 모두 반영"))

    # 7) 종결체·미해결 표시
    res.append(("종결체(~다) 일관", "습니다" not in tgt,
                "'습니다' %d회" % tgt.count("습니다")))
    tbd = len(re.findall(r"\[TBD:", tgt)) + len(re.findall(r"LINEBREAK-UNCERTAIN", tgt))
    res.append(("미해결 표시 없음", tbd == 0, "TBD·불확실 표시 %d건" % tbd))

    print("=== AI 감수 1차 · 기계 검증 · %s ===" % cid)
    fails = 0
    for name, ok, detail in res:
        mark = "통과" if ok else "확인"
        if not ok: fails += 1
        print("  [%s] %-22s %s" % (mark, name, detail))
    print("\n  %d개 항목 중 %d개 확인 필요" % (len(res), fails))
    return res

if __name__ == "__main__":
    main(sys.argv[1])
