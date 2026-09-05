#!/usr/bin/env python3
"""원서 용어집(Glossary) 추출 -> glossary.yaml 초기값 생성.

원서에 용어집이 있으면 본문보다 먼저 처리해 용어 대응을 확정한다(파이프라인 3절).
표제어는 볼드체, 정의는 이어지는 본문으로 구성된 구조를 이용한다.
사용법: extract_glossary.py <pdf> <시작쪽> <끝쪽> [출력.yaml]
"""
import sys, re, json
import pymupdf

def main(pdf, p0, p1, out=None):
    doc = pymupdf.open(pdf)
    entries, cur = [], None
    for i in range(p0-1, p1):
        page = doc[i]; h = page.rect.height
        for b in page.get_text("dict")["blocks"]:
            if b.get("type") != 0: continue
            y0 = b["bbox"][1]
            if y0 < h*0.09 or y0 > h*0.88: continue      # 러닝헤드/쪽번호
            term_parts, def_parts, in_term = [], [], True
            for l in b["lines"]:
                for s in l["spans"]:
                    t = s["text"]
                    if not t.strip(): continue
                    bold = bool(s["flags"] & 16)
                    if in_term and bold:
                        term_parts.append(t)
                    else:
                        in_term = False
                        def_parts.append(t)
            term = re.sub(r"\s+", " ", "".join(term_parts)).strip()
            body = re.sub(r"\s+", " ", "".join(def_parts)).strip()
            body = re.sub(r"(?<=[A-Za-z])- (?=[a-z])", "", body)   # 하이픈 분철 재결합
            if term and body:
                entries.append(dict(term=term, definition=body, page=i+1))
                cur = entries[-1]
            elif cur and body:                                     # 앞 항목의 이어지는 정의
                cur["definition"] = (cur["definition"] + " " + body).strip()
    print(f"추출된 용어 항목: {len(entries)}개 (PDF p.{p0}-{p1})")
    if out:
        with open(out, "w") as f:
            f.write("# 용어집 — 원서 Glossary에서 자동 추출한 초기값\n")
            f.write("# term/definition_en: 원서 원문 (수정 금지)\n")
            f.write("# translation/definition_ko: 번역 단계에서 채움\n")
            f.write("# locked: true = 표기 잠금 (변경 시 사용자 승인 필요)\n\nentries:\n")
            for e in entries:
                d = e["definition"].replace('"', '\\"')
                f.write(f'  - term: "{e["term"]}"\n')
                f.write(f'    translation: null\n')
                f.write(f'    definition_en: "{d}"\n')
                f.write(f'    definition_ko: null\n')
                f.write(f'    source: "원서 Glossary p.{e["page"]}"\n')
                f.write(f'    principle_form: null\n    adopted_form: null\n    basis: null\n')
                f.write(f'    first_chapter: glossary\n    locked: false\n')
    return entries

if __name__ == "__main__":
    es = main(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4] if len(sys.argv)>4 else None)
    print("\n표제어 목록 (앞 30개):")
    print("  " + ", ".join(e["term"] for e in es[:30]))
    long_defs = [e for e in es if len(e["definition"]) > 300]
    print(f"\n정의가 300자 넘는 항목: {len(long_defs)}개  (병합 오류 점검 대상)")
