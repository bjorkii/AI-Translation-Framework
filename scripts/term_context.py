#!/usr/bin/env python3
"""용어별 실제 사용 문맥 추출 — 배치 확인 시 사용자 판단 근거로 제시."""
import pymupdf, re, sys

def sentences(doc, f0, f1):
    txt = " ".join(doc[i].get_text() for i in range(f0-1, f1))
    txt = re.sub(r"-\s+", "", txt)          # 하이픈 분철
    txt = re.sub(r"\s+", " ", txt)
    return re.split(r"(?<=[.!?])\s+(?=[A-Z])", txt)

def label_of(doc, sent, f0, f1):
    for i in range(f0-1, f1):
        if sent[:40] in re.sub(r"\s+", " ", re.sub(r"-\s+", "", doc[i].get_text())):
            return doc[i].get_label()
    return "?"

def main(terms, n=2):
    doc = pymupdf.open("intermediate/FilmPreservationGuide-EN.pdf")
    sents = sentences(doc, 13, 104)
    for t in terms:
        pat = re.compile(r"(?<![A-Za-z0-9])" + re.escape(t) + r"s?(?![A-Za-z0-9])", re.I)
        hits = [s for s in sents if pat.search(s) and 60 < len(s) < 260]
        # 정의·대조 문맥을 우선 (is/means/refers/called/unlike 포함)
        hits.sort(key=lambda s: (0 if re.search(r"\b(is|are|means|refers|called|term|unlike|whereas)\b", s, re.I) else 1, len(s)))
        print(f"\n### {t}")
        for s in hits[:n]:
            print(f"  (원서 p.{label_of(doc, s, 13, 104)}) {s.strip()}")
        if not hits: print("  (본문 용례 없음)")

if __name__ == "__main__":
    main(sys.argv[1:])
