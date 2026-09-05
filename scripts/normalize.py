#!/usr/bin/env python3
"""텍스트 레이어 정규화 (파이프라인 2.0절) — v2

v1 대비 개선:
  (a) 문장 끝에 붙은 각주 참조 번호를 인식해 문장 종료 판정에서 분리하고,
      2.3절 앵커 링크 형태로 변환
  (b) 페이지 하단 각주 정의 블록을 본문 흐름에서 분리해,
      해당 페이지 텍스트 말미(페이지 마커 직전)에 배치
사용법: normalize.py <pdf> <시작PDF쪽> <끝PDF쪽> <챕터ID> [출력.md]
"""
import sys, re
import pymupdf

ABBR = re.compile(r"\b(Mr|Mrs|Ms|Dr|Prof|St|Jr|Sr|vs|etc|cf|approx|ca|No|Vol|pp|Fig|ed|eds|Inc|Co)\.$", re.I)
END  = re.compile(r"[.!?:;”\"’')\]]\s*$")
# 문장부호 뒤에 붙은 1~2자리 각주 참조번호
FN_REF = re.compile(r"(?<![0-9])(?<=[.!?”’\)])(\d{1,2})(?=\s|$)")
# 각주 정의 블록 시작 패턴 (예: "1.본문..." / "2. AMIA grew...")
FN_DEF_HEAD = re.compile(r"^\s*(\d{1,2})\s*\.\s*(?=[A-Z“\"])")
SUP = "⁰¹²³⁴⁵⁶⁷⁸⁹"
TABLE_T = re.compile(r"^(TABLE|FIGURE|CHART)\s+\d+", re.I)

def is_caps_label(t):
    """전량 대문자 라벨/제목 조각 판정 (사이드바 제목, 표 제목, 캡션 헤더 등)"""
    if len(t) > 110: return False
    al = [c for c in t if c.isalpha()]
    if len(al) < 3: return False
    return sum(1 for c in al if c.isupper()) / len(al) >= 0.85

def sup(n): return "".join(SUP[int(d)] for d in str(n))

def page_labels(doc):
    labels = {}
    for i, page in enumerate(doc):
        h = page.rect.height
        for b in page.get_text("dict")["blocks"]:
            if b.get("type") != 0 or b["bbox"][1] < h*0.88: continue
            t = " ".join(s["text"] for l in b["lines"] for s in l["spans"]).strip()
            if re.fullmatch(r"\d{1,3}", t) or re.fullmatch(r"[ivxlcdm]{1,7}", t):
                labels[i] = t
    return labels

def join_lines(lines, stats):
    out = ""
    for ln in lines:
        if not out: out = ln; continue
        if re.search(r"[A-Za-z]-$", out):
            out = out[:-1] + ln; stats["dehyphen"] += 1
        else:
            out += " " + ln
    return re.sub(r"\s{2,}", " ", out).strip()

def split_fn_defs(txt):
    """한 블록에 여러 각주가 뭉쳐 있는 경우 번호 기준으로 분리"""
    parts = re.split(r"(?<=[.\"”’])\s+(?=\d{1,2}\.\s*[A-Z“\"])", txt)
    outs = []
    for p in parts:
        m = re.match(r"^\s*(\d{1,2})\s*\.\s*(.+)$", p, re.S)
        if m: outs.append((int(m.group(1)), m.group(2).strip()))
        else: outs.append((None, p.strip()))
    return outs

def main(pdf, p0, p1, chap, outpath=None):
    doc = pymupdf.open(pdf); labels = page_labels(doc)
    stats = dict(pages=0, blocks=0, paras=0, dehyphen=0, uncertain=0, headers_removed=0,
                 layout_uncertain=0, headings=0, captions=0, fn_refs=0, fn_defs=0, labels=0)
    out, notes = [], []
    carry_idx = None      # out 리스트에서 직전 본문 문단의 위치

    for i in range(p0-1, p1):
        page = doc[i]; stats["pages"] += 1
        w, h = page.rect.width, page.rect.height
        body, fndefs = [], []
        for b in page.get_text("dict")["blocks"]:
            if b.get("type") != 0: continue
            lines = ["".join(s["text"] for s in l["spans"]).strip() for l in b["lines"]]
            lines = [x for x in lines if x]
            if not lines: continue
            txt = " ".join(lines); y0, x0 = b["bbox"][1], b["bbox"][0]
            if (y0 < h*0.09 or y0 > h*0.88) and len(txt) < 60:
                stats["headers_removed"] += 1; continue
            size = max(s["size"] for l in b["lines"] for s in l["spans"])
            rec = dict(x0=x0, y0=y0, size=size, lines=lines, txt=txt)
            # (b) 각주 정의 블록: 작은 폰트 + 페이지 하단부 + 번호로 시작
            if size <= 10.4 and y0 > h*0.45 and FN_DEF_HEAD.match(txt):
                fndefs.append(rec)
            else:
                body.append(rec)

        rights = [b for b in body if b["x0"] > w*0.45 and len(b["txt"]) > 40]
        lefts  = [b for b in body if b["x0"] <= w*0.45 and len(b["txt"]) > 40]
        multi = bool(rights and lefts)
        body.sort(key=lambda b: ((0 if b["x0"] <= w*0.45 else 1), b["y0"]) if multi else (0, b["y0"]))
        label = labels.get(i, f"?{i+1}")
        if multi:
            stats["layout_uncertain"] += 1
            out.append(f"\n<!-- LAYOUT-UNCERTAIN: p.{label} 좌{len(lefts)}/우{len(rights)} 블록 — 2단 본문/사이드바 시각 확인 필요 -->\n")

        for b in body:
            stats["blocks"] += 1
            txt = join_lines(b["lines"], stats)
            # (a) 각주 참조번호 -> 앵커 링크
            def _ref(m):
                n = m.group(1)
                return f'<a id="back-{chap}-{int(n):03d}"></a>[{sup(n)}](#fn-{chap}-{int(n):03d})'
            txt2, cnt = FN_REF.subn(_ref, txt)
            stats["fn_refs"] += cnt
            bare = FN_REF.sub("", txt)      # 문장 종료 판정용(참조번호 제거)

            if b["size"] >= 15:
                out.append(f"\n## {txt}\n"); stats["headings"] += 1; carry_idx = None; continue
            if b["size"] >= 13:
                out.append(f"\n### {txt}\n"); stats["headings"] += 1; carry_idx = None; continue
            if TABLE_T.match(txt) or is_caps_label(txt):
                # 표 제목 / 대문자 라벨: 본문 흐름에서 분리하고 연속 판정 대상에서 제외
                out.append(f"\n**{txt}**\n"); stats["labels"] += 1; carry_idx = None; continue
            if b["size"] <= 10.4 and len(txt) < 200:
                out.append(f"\n*{txt2}*\n"); stats["captions"] += 1; continue

            if carry_idx is not None:
                prev = out[carry_idx].strip()
                prev_bare = FN_REF.sub("", re.sub(r"<a id=[^>]*></a>\[[^\]]*\]\([^)]*\)", "", prev))
                cont = (not END.search(prev_bare)) or bool(ABBR.search(prev_bare))
                lower = txt[:1].islower()
                if cont and lower:
                    out[carry_idx] = f"\n{prev} {txt2}\n"; continue
                if cont != lower:
                    stats["uncertain"] += 1
                    notes.append(f"p.{label}: …{prev_bare[-45:]!r} || {txt[:45]!r}")
                    out.append(f"\n<!-- LINEBREAK-UNCERTAIN -->\n{txt2}\n")
                    carry_idx = len(out)-1; stats["paras"] += 1; continue
            out.append(f"\n{txt2}\n"); carry_idx = len(out)-1; stats["paras"] += 1

        # 각주 정의 -> 페이지 텍스트 말미 (페이지 마커 직전)
        for b in fndefs:
            for num, body_txt in split_fn_defs(join_lines(b["lines"], stats)):
                if num is None: continue
                stats["fn_defs"] += 1
                out.append(f'\n<a id="fn-{chap}-{num:03d}"></a> **[각주]** {body_txt}  [↩](#back-{chap}-{num:03d})\n')
        out.append(f"\n[원서 p.{label}]\n")

    text = re.sub(r"\n{3,}", "\n\n", "".join(out))
    if outpath: open(outpath, "w").write(text)
    print("=== 정규화 통계 (v2) ===")
    for k, v in stats.items(): print(f"  {k}: {v}")
    tot = stats["paras"] + stats["uncertain"]
    print(f"  >>> 불확실 판정 비율: {stats['uncertain']}/{tot} = {stats['uncertain']/max(tot,1)*100:.1f}%")
    for n in notes[:6]: print("  · " + n)
    return text

if __name__ == "__main__":
    t = main(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4],
             sys.argv[5] if len(sys.argv) > 5 else None)
