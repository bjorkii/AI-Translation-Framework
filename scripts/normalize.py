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
# (?<![0-9]\.) : "6.5절", "2.6" 같은 절 번호 상호참조를 각주로 오인하지 않도록 막는다.
#                이 예외가 없으면 "(See 6.5 on ...)"의 5가 각주 참조로 잡혀
#                같은 번호의 각주가 본문에 두 번 생긴다.
FN_REF = re.compile(r"(?<![0-9])(?<![0-9]\.)(?<=[.,;:!?”’\)])(\d{1,2})(?=\s|$)")
# 각주 정의 블록 시작 패턴 (예: "1.본문..." / "2. AMIA grew...")
FN_DEF_HEAD = re.compile(r"^\s*(\d{1,2})\s*\.\s*(?=[A-Z“\"])")
SUP = "⁰¹²³⁴⁵⁶⁷⁸⁹"
FNREF_MARK = re.compile("\x04(\\d{1,2})\x02")

# 줄 끝 하이픈 판정용 어휘집 (책 전체에서 한 번 모은다)
LEX = set()

def build_lexicon(doc):
    """책 전체에 실제로 등장하는 낱말을 모은다.

    줄 끝 하이픈은 '분철'(insti-tution)일 수도 있고 '합성어'(black-and-white)일 수도 있다.
    둘을 규칙만으로 가르면 반드시 한쪽이 틀리므로, 같은 책 안의 다른 자리에
    어떤 형태로 쓰였는지를 근거로 삼는다."""
    global LEX
    if LEX:
        return LEX
    words = set()
    for pg in doc:
        for ln in pg.get_text().splitlines():
            ln = ln.strip()
            toks = ln.split()
            for i, t in enumerate(toks):
                # 줄 끝에 걸린 하이픈 토큰은 근거가 못 되므로 뺀다
                if i == len(toks) - 1 and t.endswith("-"):
                    continue
                w = re.sub(r"^[^A-Za-z]+|[^A-Za-z-]+$", "", t).lower().strip("-")
                if len(w) > 2:
                    words.add(w)
    LEX = words
    return LEX

def dehyphen_join(left, right):
    """줄 끝 하이픈으로 갈린 두 조각을 합친다. (합친 문자열, 하이픈제거여부)

    left 는 '...-' 로 끝나고 right 는 이어지는 조각이다.
    책 어휘집에 하이픈을 살린 형태가 있으면 살리고, 아니면 붙인다."""
    head = re.split(r"\s", right, 1)[0]
    stem = re.search(r"([A-Za-z][A-Za-z-]*)-$", left)
    if not stem:
        return left + head, False
    keep = (stem.group(1) + "-" + head).lower().strip("-")
    drop = (stem.group(1) + head).lower()
    keep = re.sub(r"[^a-z-]+$", "", keep); drop = re.sub(r"[^a-z]+$", "", drop)
    if keep in LEX and drop not in LEX:
        return left + head, False        # 합성어: 하이픈 유지
    return left[:-1] + head, True        # 분철: 하이픈 제거
TABLE_T = re.compile(r"^(TABLE|FIGURE|CHART)\s+\d+", re.I)

def is_caps_label(t):
    """전량 대문자 라벨/제목 조각 판정 (사이드바 제목, 표 제목, 캡션 헤더 등)"""
    if len(t) > 110: return False
    al = [c for c in t if c.isalpha()]
    if len(al) < 3: return False
    return sum(1 for c in al if c.isupper()) / len(al) >= 0.85

def sup(n): return "".join(SUP[int(d)] for d in str(n))

def inside(bbox, rect, pad=2):
    """블록 bbox가 사각형 rect 안에 들어가는가 (약간의 여유 허용)"""
    x0, y0, x1, y1 = bbox
    return (x0 >= rect[0]-pad and y0 >= rect[1]-pad
            and x1 <= rect[2]+pad and y1 <= rect[3]+pad)

def footnote_rule_y(page):
    """각주 구분선의 y좌표. 이 선 아래에 있는 것만 각주 정의로 본다.

    이 책은 각주 영역 위에 페이지 폭 1/4 남짓의 가는 가로선을 긋는다.
    선이 없는 페이지에는 각주가 없다는 뜻이므로, '1. …' 로 시작하는
    사진 캡션 묶음(예: 원서 p.54의 포장 절차)을 각주로 오인하지 않는다."""
    w = page.rect.width
    ys = [d["rect"].y0 for d in page.get_drawings()
          if d["type"] == "s" and d["rect"].height < 2
          and w * 0.15 < d["rect"].width < w * 0.55
          and d["rect"].y0 > page.rect.height * 0.45]
    return min(ys) if ys else None

def sidebar_rects(page):
    """회색으로 채운 상자 = 사이드바(측주). 이미지 테두리(흰 채움)와 구분한다."""
    out = []
    for d in page.get_drawings():
        f = d.get("fill")
        r = d["rect"]
        if not f or d["type"] != "f":
            continue
        if r.width < 90 or r.height < 60:
            continue
        if abs(f[0]-f[1]) < .02 and abs(f[1]-f[2]) < .02 and 0.7 < f[0] < 0.97:
            out.append((r.x0, r.y0, r.x1, r.y1))
    return out

def md_table(rows):
    """추출한 표를 마크다운 표로. 셀 안의 줄바꿈은 <br>로 살린다."""
    def cell(c):
        c = (c or "").strip()
        c = re.sub(r"([A-Za-z])-\s*\n\s*([a-z])", r"\1\2", c)   # 셀 안 줄 끝 하이픈 분철 복원
        c = re.sub(r"\s*\n\s*", " ", c)
        c = re.sub(r"([A-Za-z])-\s+([a-z]{2,})", r"\1\2", c)     # 이미 공백으로 합쳐진 경우
        c = re.sub(r"\s+", " ", c)
        return c.replace("|", "\\|")
    rows = [[cell(c) for c in r] for r in rows if any((c or "").strip() for c in r)]
    if not rows:
        return ""
    ncol = max(len(r) for r in rows)
    rows = [r + [""] * (ncol - len(r)) for r in rows]
    head, body = rows[0], rows[1:]
    out = ["| " + " | ".join(head) + " |",
           "|" + "|".join(["---"] * ncol) + "|"]
    for r in body:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out)

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

FNMARK_O, FNMARK_C = "\x04", "\x02"      # 각주 참조 자리표시

def styled_text(block, stats, mark_refs=False):
    """스팬의 이탤릭 여부를 살려 마크다운으로 옮긴다.

    원서는 작품명·서명만 이탤릭으로 조판한다. 블록 전체를 이탤릭으로 감싸면
    그 구분이 사라지므로, 이탤릭 구간만 *...* 로 표시한다.

    mark_refs=True면 '본문보다 뚜렷하게 작은 숫자 스팬'을 각주 참조로 보고
    자리표시(\x04번호\x02)를 심는다. 텍스트 정규식으로 판정하면
      · "collection?  1" 처럼 사이에 공백이 끼면 놓치고
      · "6.5절", "00:05:18:05"(타임코드) 같은 것을 각주로 오인한다.
    조판 정보(글자 크기)를 쓰면 두 문제가 함께 사라진다.
    """
    base = 0.0
    if mark_refs:
        sizes = [(len(sp["text"].strip()), sp["size"])
                 for l in block["lines"] for sp in l["spans"] if sp["text"].strip()]
        if sizes:
            base = max(sz for _, sz in sizes)
    frags = []          # (텍스트, 이탤릭여부)
    for li, line in enumerate(block["lines"]):
        parts = []
        for sp in line["spans"]:
            t = sp["text"]
            if not t.strip() and not parts:
                continue
            if (mark_refs and base and sp["size"] <= base - 1.5
                    and re.fullmatch(r"\s*\d{1,2}\s*", t)):
                parts.append((FNMARK_O + t.strip() + FNMARK_C, False))
                continue
            parts.append((t, bool(sp["flags"] & 2)))
        if not parts:
            continue
        if frags:
            prev = frags[-1][0]
            if re.search(r"[A-Za-z]-$", prev):
                nxt = parts[0][0] if parts else ""
                _, dropped = dehyphen_join(prev, nxt)
                if dropped:
                    frags[-1] = (prev[:-1], frags[-1][1]); stats["dehyphen"] += 1
                # 합성어면 하이픈을 살린 채 공백 없이 붙인다
            else:
                frags.append((" ", frags[-1][1]))
        frags.extend(parts)
    # 이탤릭 구간을 묶어 표시
    out, buf, cur = "", "", None
    for t, it in frags:
        if cur is None:
            cur = it
        if it != cur:
            out += ("*%s*" % buf.strip()) if (cur and buf.strip()) else buf
            buf, cur = "", it
        buf += t
    out += ("*%s*" % buf.strip()) if (cur and buf.strip()) else buf
    return re.sub(r"\s{2,}", " ", out).strip()

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

def detect_body_size(doc, p0, p1):
    import collections
    c = collections.Counter()
    for i in range(p0-1, p1):
        for b in doc[i].get_text("dict")["blocks"]:
            if b.get("type") != 0: continue
            for l in b["lines"]:
                for sp in l["spans"]:
                    if sp["text"].strip(): c[round(sp["size"], 1)] += len(sp["text"])
    return c.most_common(1)[0][0] if c else 11.0

def main(pdf, p0, p1, chap, outpath=None):
    doc = pymupdf.open(pdf); labels = page_labels(doc)
    build_lexicon(doc)
    BODY = detect_body_size(doc, p0, p1)
    print(f"  (본문 폰트 자동 추정: {BODY}pt)")
    stats = dict(pages=0, blocks=0, paras=0, dehyphen=0, uncertain=0, headers_removed=0,
                 layout_uncertain=0, headings=0, captions=0, fn_refs=0, fn_defs=0, labels=0,
                 tables=0, table_cells=0, sidebars=0)
    out, notes = [], []
    carry_idx = None      # out 리스트에서 직전 본문 문단의 위치
    pending = {"mark": None, "warn": None}   # 아직 배치하지 않은 페이지 마커 / 레이아웃 경고

    def flush_warn():
        """레이아웃 경고는 항상 페이지 마커 뒤에 온다"""
        if pending["warn"]:
            out.append(pending["warn"]); pending["warn"] = None

    def flush_mark():
        """문단이 이어지지 않는 경우: 마커를 독립된 줄로 배치"""
        if pending["mark"]:
            out.append("\n[원서 p.%s]\n" % pending["mark"])
            pending["mark"] = None
        flush_warn()

    for i in range(p0-1, p1):
        page = doc[i]; stats["pages"] += 1
        w, h = page.rect.width, page.rect.height
        # (1) 괘선 표: 표 영역 안의 텍스트 블록은 본문 흐름에서 제외하고 마크다운 표로 재구성
        tables = []
        try:
            for t in page.find_tables().tables:
                data = t.extract()
                if not data or len(data) < 2:
                    continue
                # 도판 캡션에 테두리가 있으면 표로 잡히기도 한다.
                # 빈 칸이 대부분이거나 실질적으로 1열뿐이면 표가 아니다.
                ncol = max(len(r) for r in data)
                filled = sum(1 for r in data for c in r if (c or "").strip())
                usedcol = sum(1 for j in range(ncol)
                              if any((r[j] if j < len(r) else "" or "").strip() for r in data))
                if usedcol < 2 or filled < len(data) * ncol * 0.35:
                    continue
                tables.append({"bbox": tuple(t.bbox), "md": md_table(data),
                               "rows": len(data), "cols": ncol})
        except Exception:
            pass
        # (2) 회색 상자 사이드바
        sboxes = sidebar_rects(page)
        # (3) 각주 구분선 — 이 선 아래만 각주 정의로 인정
        rule_y = footnote_rule_y(page)
        body, fndefs, sides = [], [], {i: [] for i in range(len(sboxes))}
        for b in page.get_text("dict")["blocks"]:
            if b.get("type") != 0: continue
            lines = ["".join(s["text"] for s in l["spans"]).strip() for l in b["lines"]]
            lines = [x for x in lines if x]
            if not lines: continue
            txt = " ".join(lines); y0, x0 = b["bbox"][1], b["bbox"][0]
            if (y0 < h*0.09 or y0 > h*0.88) and len(txt) < 60:
                stats["headers_removed"] += 1; continue
            size = max(s["size"] for l in b["lines"] for s in l["spans"])
            rec = dict(x0=x0, y0=y0, size=size, lines=lines, txt=txt, raw=b, bbox=b["bbox"])
            # 표 안의 텍스트는 본문에서 뺀다 (표는 통째로 다시 만든다)
            if any(inside(b["bbox"], t["bbox"]) for t in tables):
                stats["table_cells"] += 1; continue
            # 사이드바 상자 안의 텍스트는 따로 모은다
            si = next((i for i, r in enumerate(sboxes) if inside(b["bbox"], r)), None)
            if si is not None:
                sides[si].append(rec); continue
            # (b) 각주 정의 블록: 각주 구분선 아래 + 작은 폰트 + 번호로 시작
            if (rule_y is not None and y0 > rule_y - 6
                    and size < BODY - 0.4 and FN_DEF_HEAD.match(txt)):
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
            # 경고는 바로 내보내지 않고 대기시킨다. 직전 페이지 마커가
            # 문장 한가운데에 들어가야 하는 경우가 있어, 마커 배치가 끝난 뒤에 놓는다.
            pending["warn"] = (f"\n<!-- LAYOUT-UNCERTAIN: p.{label} "
                               f"좌{len(lefts)}/우{len(rights)} 블록 — 읽기 순서 시각 확인 필요 -->\n")

        for b in body:
            stats["blocks"] += 1
            txt = styled_text(b["raw"], stats, mark_refs=True)
            # (a) 각주 참조번호(위첨자 스팬) -> 앵커 링크
            def _ref(m):
                n = m.group(1)
                return f'<a id="back-{chap}-{int(n):03d}"></a>[{sup(n)}](#fn-{chap}-{int(n):03d})'
            txt2, cnt = FNREF_MARK.subn(_ref, txt)
            txt2 = re.sub(r"\s+(<a id=\"back-)", r"\1", txt2)   # 참조 앞 여백 제거
            stats["fn_refs"] += cnt
            txt = FNREF_MARK.sub("", txt)   # 표시용 원문(참조 제거)
            bare = txt                      # 문장 종료 판정용

            if b["size"] >= 15:
                flush_mark(); out.append(f"\n## {txt}\n"); stats["headings"] += 1; carry_idx = None; continue
            if b["size"] >= 13:
                flush_mark(); out.append(f"\n### {txt}\n"); stats["headings"] += 1; carry_idx = None; continue
            if (TABLE_T.match(txt) and len(txt) < 110) or is_caps_label(txt):
                # 표 제목 / 대문자 라벨: 본문 흐름에서 분리하고 연속 판정 대상에서 제외
                flush_mark(); out.append(f"\n**{txt}**\n"); stats["labels"] += 1; carry_idx = None; continue
            if b["size"] < BODY - 0.4:
                # 본문보다 작은 폰트 = 캡션/표/사이드바 등 구조 요소.
                # 본문 문단 흐름을 끊지 않도록 carry_idx를 유지한 채 통과시킨다.
                flush_mark(); out.append(f"\n{txt2}\n"); stats["captions"] += 1; continue

            if carry_idx is not None:
                prev = out[carry_idx].strip()
                prev_bare = FN_REF.sub("", re.sub(r"<a id=[^>]*></a>\[[^\]]*\]\([^)]*\)", "", prev))
                cont = (not END.search(prev_bare)) or bool(ABBR.search(prev_bare))
                lower = txt[:1].islower()
                if cont and lower:
                    mark = pending["mark"]; pending["mark"] = None
                    # 페이지 경계가 단어 한가운데(줄 끝 하이픈)인 경우:
                    # 하이픈을 없애 단어를 붙이고, 마커는 그 단어 뒤에 놓는다.
                    if re.search(r"[A-Za-z]-$", prev):
                        head, sep, tail = txt2.partition(" ")
                        joined, dropped = dehyphen_join(prev, head)
                        if dropped: stats["dehyphen"] += 1
                        rest = (" " + tail) if sep else ""
                        mk = (" [원서 p.%s]" % mark) if mark else ""
                        out[carry_idx] = f"\n{joined}{mk}{rest}\n"
                    else:
                        joint = (" [원서 p.%s] " % mark) if mark else " "
                        out[carry_idx] = f"\n{prev}{joint}{txt2}\n"
                    flush_warn(); continue
                if cont != lower:
                    stats["uncertain"] += 1
                    notes.append(f"p.{label}: …{prev_bare[-45:]!r} || {txt[:45]!r}")
                    flush_mark()
                    out.append(f"\n<!-- LINEBREAK-UNCERTAIN -->\n{txt2}\n")
                    carry_idx = len(out)-1; stats["paras"] += 1; continue
            flush_mark()
            out.append(f"\n{txt2}\n"); carry_idx = len(out)-1; stats["paras"] += 1

        # 표: 본문 뒤, 각주 앞에 놓는다
        for t in sorted(tables, key=lambda t: t["bbox"][1]):
            if not t["md"]:
                continue
            flush_mark()
            stats["tables"] += 1
            out.append("\n<!-- 표: %d행 %d열 · 원서 p.%s -->\n%s\n"
                       % (t["rows"], t["cols"], label, t["md"]))
        # 사이드바(측주 상자)
        for i, blocks_ in sides.items():
            if not blocks_:
                continue
            blocks_.sort(key=lambda b: b["y0"])
            stats["sidebars"] += 1
            flush_mark()
            body_md = "\n>\n".join("> " + styled_text(b["raw"], stats).replace("\n", " ")
                                   for b in blocks_)
            out.append("\n<!-- 사이드바 시작 · 원서 p.%s -->\n%s\n<!-- 사이드바 끝 -->\n"
                       % (label, body_md))

        # 각주 정의 -> 페이지 텍스트 말미 (페이지 마커 직전)
        for b in fndefs:
            for num, body_txt in split_fn_defs(styled_text(b["raw"], stats)):
                if num is None: continue
                stats["fn_defs"] += 1
                out.append(f'\n<a id="fn-{chap}-{num:03d}"></a> **[각주]** {body_txt}  [↩](#back-{chap}-{num:03d})\n')
        pending["mark"] = label      # 다음 블록이 이어지는지 보고 배치 위치를 정한다

    flush_mark(); flush_warn()
    text = re.sub(r"\n{3,}", "\n\n", "".join(out))
    if outpath: open(outpath, "w").write(text)
    print("=== 정규화 통계 (v3) ===")
    for k, v in stats.items(): print(f"  {k}: {v}")
    tot = stats["paras"] + stats["uncertain"]
    print(f"  >>> 불확실 판정 비율: {stats['uncertain']}/{tot} = {stats['uncertain']/max(tot,1)*100:.1f}%")
    for n in notes[:6]: print("  · " + n)
    return text

if __name__ == "__main__":
    t = main(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4],
             sys.argv[5] if len(sys.argv) > 5 else None)
