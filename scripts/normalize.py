#!/usr/bin/env python3
"""텍스트 레이어 정규화 (파이프라인 2.0절) — v2

v1 대비 개선:
  (a) 문장 끝에 붙은 각주 참조 번호를 인식해 문장 종료 판정에서 분리하고,
      2.3절 앵커 링크 형태로 변환
  (b) 페이지 하단 각주 정의 블록을 본문 흐름에서 분리해,
      해당 페이지 텍스트 말미(페이지 마커 직전)에 배치
사용법: normalize.py <pdf> <시작PDF쪽> <끝PDF쪽> <챕터ID> [출력.md]
"""
import sys, re, os
import pymupdf
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import figures as figmod
import layout_profile as LP

# 조판 의존 수치는 scripts/layout_profile.py 에 모아 두었다.
# 규칙 자체는 어느 책에나 통하지만 아래 값들은 원서 조판에 따라 달라진다.
# 다른 책을 시작할 때 확인할 목록이며, structure-map.yaml 의 layout: 로 덮어쓴다.

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
        prev_hyphen = False
        for ln in pg.get_text().splitlines():
            toks = ln.strip().split()
            if not toks:
                prev_hyphen = False
                continue
            for i, t in enumerate(toks):
                # 줄 끝에 걸린 하이픈 토큰은 근거가 못 되므로 뺀다
                if i == len(toks) - 1 and t.endswith("-"):
                    continue
                # 앞 줄이 하이픈으로 끝났으면 이 줄 첫 토큰은 낱말의 뒤 토막이다.
                # 이걸 어휘집에 넣으면 'nership'(partnership), 'whelmingly'(overwhelmingly)
                # 같은 토막이 낱말로 등록되어, 합성어 판정이 거꾸로 뒤집힌다.
                if i == 0 and prev_hyphen:
                    continue
                w = re.sub(r"^[^A-Za-z]+|[^A-Za-z-]+$", "", t).lower().strip("-")
                if len(w) > 2:
                    words.add(w)
            prev_hyphen = toks[-1].endswith("-")
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
    if drop in LEX:
        return left[:-1] + head, True    # 분철: 하이픈 제거
    # 어느 쪽도 어휘집에 없을 때. 양쪽 조각이 각각 낱말로 쓰이면 합성어로 본다.
    # (stage-two, film-to-video 처럼 그 자리에서만 쓰인 합성어가 여기 걸린다.
    #  이 갈래가 없으면 'stage- two' 가 'stagetwo' 로 붙어 버린다.)
    a = stem.group(1).lower().strip("-").split("-")[-1]
    b = re.sub(r"[^a-z]+$", "", head.lower())
    if len(a) > 2 and len(b) > 2 and a in LEX and b in LEX:
        return left + head, False        # 합성어: 하이픈 유지
    return left[:-1] + head, True        # 분철: 하이픈 제거
TABLE_T = re.compile(r"^(TABLE|FIGURE|CHART)\s+\d+", re.I)

def is_wordy(t):
    """글자로 이루어진 덩어리인가 — 제목 판정의 전제.

    큰 글씨라는 이유만으로 제목으로 보면, 부록A 에지코드 차트의 기호 행
    (● ▲ ■ + x)이 '## ● ● ▲ ■ …' 이라는 제목이 된다. 기호는 제목이 아니다.
    """
    core = t.strip()
    if not core:
        return False
    letters = sum(1 for c in core if c.isalpha())
    return letters >= 3 and letters / len(core) >= 0.4

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

def box_rects(page, text_blocks):
    """본문과 구분되는 상자를 찾는다.

    두 종류가 있다.
      · 회색으로 채운 상자  = 사이드바(측주)
      · 테두리만 두른 상자  = 서식·기입표 (원서 p.52 견적서, p.74 숏 리스트)
    사진 테두리도 테두리 상자지만 안에 텍스트가 없으므로 걸러진다.
    """
    cands, out = [], []
    for d in page.get_drawings():
        r = d["rect"]
        if r.width < 90 or r.height < 55:
            continue
        f = d.get("fill")
        gray = bool(f and d["type"] == "f"
                    and abs(f[0]-f[1]) < .02 and abs(f[1]-f[2]) < .02 and 0.7 < f[0] < 0.97)
        stroked = (d["type"] == "s")
        if gray or stroked:
            cands.append(((r.x0, r.y0, r.x1, r.y1), "사이드바" if gray else "상자"))
    # 같은 상자가 '회색 채움'과 '테두리 선' 두 번 그려지는 경우가 많다.
    # 거의 같은 사각형은 하나로 합치고, 회색(사이드바) 쪽 이름을 우선한다.
    merged = []
    for rect, kind in cands:
        hit = None
        for j, (r2, k2) in enumerate(merged):
            if all(abs(a - b) <= 3 for a, b in zip(rect, r2)):
                hit = j; break
        if hit is None:
            merged.append((rect, kind))
        elif kind == "사이드바":
            merged[hit] = (rect, kind)

    for rect, kind in merged:
        n = sum(1 for b in text_blocks if inside(b["bbox"], rect))
        if n < 2:                      # 사진 테두리 등 텍스트 없는 상자는 제외
            continue
        out.append((rect, kind))

    def area(r): return (r[2]-r[0]) * (r[3]-r[1])
    # 큰 상자가 작은 상자를 품는 경우, 안쪽 것만 남긴다
    out = [(r, k) for r, k in out
           if not any(area(r2) < area(r) - 1 and inside(r2, r, pad=1) for r2, _ in out)]
    return out

def box_to_markdown(blocks, stats):
    """상자 안 블록을 행·열로 되살린다.

    상자 안에는 서식(라벨:값)이나 표가 들어 있는 경우가 많다. y좌표로 행을,
    x좌표로 열을 잡으면 조판 순서와 무관하게 원래 구조를 복원할 수 있다.
    열이 하나뿐이면 그냥 문단으로 본다.
    반환: (마크다운, 표로 재구성했는가)
    """
    rows = []
    for b in sorted(blocks, key=lambda b: (round(b["y0"] / 6), b["x0"])):
        if rows and abs(rows[-1][0] - b["y0"]) <= 6:
            rows[-1][1].append(b)
        else:
            rows.append((b["y0"], [b]))
    ncol = max(len(r[1]) for r in rows) if rows else 0
    if ncol < 2:
        # 상자 제목이 두 줄로 조판되면 별개 블록으로 잡힌다 — 대문자 제목끼리는 이어붙인다
        parts = []
        for _, cells in rows:
            for b in cells:
                t = styled_text(b["raw"], stats).replace("\n", " ").strip()
                if not t:
                    continue
                if parts and is_caps_label(parts[-1]) and is_caps_label(t):
                    parts[-1] = parts[-1] + " " + t
                else:
                    parts.append(t)
        if parts and is_caps_label(parts[0].replace("**", "")):
            parts[0] = "**%s**" % parts[0].replace("**", "")
        return "\n>\n".join("> " + x for x in parts), False
    # 열 경계: 여러 칸이 있는 행들의 x 좌표를 모아 군집화
    # 열 개수는 '한 행에 들어간 칸의 최대 개수'로 정하고,
    # x 좌표를 그 개수만큼 나눈다 (간격이 가장 크게 벌어지는 곳에서 자른다).
    xs = sorted(round(b["x0"]) for _, cells in rows if len(cells) > 1 for b in cells)
    if not xs:
        return "\n\n".join(styled_text(b["raw"], stats) for _, cells in rows for b in cells), False
    gaps = sorted(range(1, len(xs)), key=lambda i: xs[i] - xs[i-1], reverse=True)
    cuts = sorted(gaps[:max(0, ncol - 1)])
    groups, start = [], 0
    for c in cuts + [len(xs)]:
        if c > start:
            groups.append(xs[start:c]); start = c
    cols = [sum(g) / len(g) for g in groups] or [xs[0]]
    def col_of(b):
        return min(range(len(cols)), key=lambda j: abs(b["x0"] - cols[j]))
    lead, table, tail = [], [], []
    for _, cells in rows:
        if len(cells) == 1 and not table:
            lead.append(cells[0]); continue
        if len(cells) == 1 and table:
            tail.append(cells[0]); continue
        line = [""] * len(cols)
        for b in cells:
            c = col_of(b)
            t = styled_text(b["raw"], stats).replace("\n", " ")
            line[c] = (line[c] + " " + t).strip()
        table.append(line)
    md = []
    for b in lead:
        md.append(styled_text(b["raw"], stats))
    if table:
        md.append(md_table(table))
    for b in tail:
        md.append(styled_text(b["raw"], stats))
    return "\n\n".join(x for x in md if x), True

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
    """페이지마다 원서에 인쇄된 쪽번호.

    PDF 가 페이지 라벨 메타데이터를 갖고 있으면 그것을 쓴다. 이 값이 곧 인쇄된
    쪽번호이고(Preview 등 뷰어도 이 값을 보여준다), 쪽번호가 쪽 위에 있든 아래에
    있든 옆에 있든 상관없이 맞다.

    메타데이터가 없는 PDF 를 위해 예전 방식(쪽 아래에서 숫자꼴 블록을 줍는 것)을
    남겨 둔다. 그 방식은 이 책의 앞부분처럼 쪽번호가 **위쪽**에 있는 조판에서는
    아무것도 찾지 못한다.
    """
    labels = {}
    for i, page in enumerate(doc):
        try:
            lab = (page.get_label() or "").strip()
        except Exception:
            lab = ""
        if lab:
            labels[i] = lab
            continue
        h = page.rect.height
        for b in page.get_text("dict")["blocks"]:
            if b.get("type") != 0 or b["bbox"][1] < h*LP.get("foot_band"): continue
            t = " ".join(s["text"] for l in b["lines"] for s in l["spans"]).strip()
            if re.fullmatch(r"\d{1,3}", t) or re.fullmatch(r"[ivxlcdm]{1,7}", t):
                labels[i] = t
    return labels

FNMARK_O, FNMARK_C = "\x04", "\x02"      # 각주 참조 자리표시

def _base_size(block, mark_refs):
    """블록의 기준 글자 크기. 각주 참조(작은 숫자 스팬)를 가려내는 잣대."""
    if not mark_refs:
        return 0.0
    sizes = [sp["size"] for l in block["lines"] for sp in l["spans"] if sp["text"].strip()]
    return max(sizes) if sizes else 0.0

def _line_frags(line, base, mark_refs):
    """한 줄의 스팬을 (텍스트, (이탤릭, 볼드)) 조각으로 만든다."""
    parts = []
    for sp in line["spans"]:
        t = sp["text"]
        if not t.strip() and not parts:
            continue
        if (mark_refs and base and sp["size"] <= base - 1.5
                and re.fullmatch(r"\s*\d{1,2}\s*", t)):
            parts.append((FNMARK_O + t.strip() + FNMARK_C, (False, False)))
            continue
        # 원서가 글자로 쓴 별표는 우리가 강조 표시로 넣는 별표와 구분해야 한다.
        # 이 책은 각주 기호로 *, **, ***, **** 를 쓰고(원서 p.47 표 아래, p.32 측주),
        # 그대로 두면 마크다운이 그 별표를 강조 표시로 읽어 뒤 문장의 서식이 뒤집힌다.
        parts.append((t.replace("*", "\\*"),
                      (bool(sp["flags"] & 2), bool(sp["flags"] & 16))))
    return parts

def styled_lines(block, stats, mark_refs=False):
    """블록을 줄 단위로 돌려준다. [{x0, y0, size, bold, text}, ...]

    산문은 조판 줄바꿈을 지워 문단으로 되돌리면 되지만, 명단·서지·색인은
    **줄 자체가 항목의 경계**다. 블록을 한 문자열로 합치면 그 경계가 사라져
    색인 한 단(段)이 통째로 한 문단이 되고, 서지 한 항목이 두 조각으로 갈린다.
    파이프라인 2.0-1절이 '항목 경계를 문장부호가 아니라 행 시작 좌표·볼드로
    잡는다'고 적어둔 신호가 바로 이 좌표다.
    """
    base = _base_size(block, mark_refs)
    out = []
    for line in block["lines"]:
        parts = _line_frags(line, base, mark_refs)
        if not parts:
            continue
        txt = _emit_frags(parts)
        if not txt:
            continue
        sizes = [sp["size"] for sp in line["spans"] if sp["text"].strip()]
        out.append({"x0": round(line["bbox"][0], 1), "y0": line["bbox"][1],
                    "y1": line["bbox"][3], "size": max(sizes) if sizes else 0.0,
                    "bold": bool(parts[0][1][1]), "text": txt, "frags": parts})
    return out

def _join_frag_lines(lineparts, stats):
    """여러 줄의 조각을 한 흐름으로 잇는다. 줄 끝 하이픈은 어휘집으로 판단해 붙인다.

    서식(*이탤릭*)을 붙이기 **전에** 이어야 한다. 마크다운을 먼저 붙이면 줄 끝이
    '-' 가 아니라 '-*' 가 되어 하이픈 판정이 빗나가고,
    *film-to-video-* *tape transfer…* 처럼 한 낱말이 두 토막으로 남는다.
    """
    frags = []
    for parts in lineparts:
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
    return frags

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
    base = _base_size(block, mark_refs)
    return _emit_frags(_join_frag_lines(
        [_line_frags(l, base, mark_refs) for l in block["lines"]], stats))

def _emit_frags(frags):
    """조각들을 마크다운 한 줄로 만든다. 같은 서식이 이어지는 구간을 묶어 표시한다."""
    def emit(buf, style):
        """style = (이탤릭, 볼드). 원서의 강조를 마크다운으로 옮긴다."""
        if not style or not any(style) or not buf.strip():
            return buf
        it, bd = style
        lead = buf[:len(buf) - len(buf.lstrip())]
        trail = buf[len(buf.rstrip()):]
        core = buf.strip()
        if bd:  core = "**%s**" % core
        if it:  core = "*%s*" % core
        return "%s%s%s" % (lead, core, trail)           # 앞뒤 공백을 표시 밖으로

    out, buf, cur = "", "", None
    for t, it in frags:
        if cur is None:
            cur = it
        if it != cur:
            out += emit(buf, cur)
            buf, cur = "", it
        buf += t
    out += emit(buf, cur)
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

def split_records(lines):
    """줄 목록을 항목 단위로 자른다. 한 단(段) 분량을 받는다.

    경계 신호는 구간마다 다르다.
      · 서지·색인 — 매달린 들여쓰기. 항목 첫 줄만 좌측 정렬선에서 시작한다
                    (서지 72pt / 이어지는 줄 99pt, 색인 54pt / 하위항목 72pt).
      · 업체 명단 — 들여쓰기가 없다. 대신 업체명이 볼드이고 항목 사이가 벌어진다
                    (부록C 항목 안 2pt / 항목 사이 11pt).
    어느 신호를 쓸지는 줄 좌표 분포를 보고 정한다. 문장부호와 대소문자는 보지 않는다 —
    레코드는 URL이나 전화번호로 끝나 문장부호가 없고, 다음 항목은 대문자로 시작하므로
    산문 규칙을 대면 경계마다 '불확실'이 찍힌다(부록C 22건이 전부 이 오탐이었다).
    """
    if not lines:
        return []
    xs = [l["x0"] for l in lines]
    flush = min(xs)
    indented = [x for x in xs if x > flush + LP.get("indent_min")]
    use_indent = len(indented) >= max(2, len(xs) * 0.15)
    gaps = [lines[i]["y0"] - lines[i-1]["y1"] for i in range(1, len(lines))]
    tight = min(gaps) if gaps else 0.0        # 항목 안 줄 간격
    recs, cur = [], []
    for i, ln in enumerate(lines):
        if not cur:
            cur = [ln]; continue
        at_flush = ln["x0"] <= flush + LP.get("indent_tol")
        if use_indent:
            new = at_flush
        else:
            new = at_flush and (ln["bold"] or (ln["y0"] - lines[i-1]["y1"]) > tight + LP.get("gap_tol"))
        if new:
            recs.append(cur); cur = [ln]
        else:
            cur.append(ln)
    if cur:
        recs.append(cur)
    return recs

def render_record(rec, mode, stats):
    """항목 하나를 마크다운으로.

    record  — 한 문단으로 잇는다 (업체 한 곳, 서지 한 건).
    rebuild — 색인. 표제어와 하위항목을 각각 제 줄에 세운다. 이 구간은 번역본 기준으로
              다시 만들 것이므로, 여기서는 표제어를 온전히 뽑아내는 것이 목적이다.
    """
    if mode != "rebuild":
        return "\n%s\n" % _emit_frags(_join_frag_lines([l["frags"] for l in rec], stats))
    head, subs = rec[0], rec[1:]
    lines = ["- %s" % head["text"]]
    lines += ["  - %s" % s["text"] for s in subs]
    return "\n%s\n" % "\n".join(lines)

def fix_glued_sentences(text):
    """마침표 뒤 공백이 빠진 자리를 되살린다.

    원본 PDF의 텍스트 레이어가 이미 붙여서 갖고 있다 — 추출 과정의 손실이 아니다
    (예: 원서 p.6 각주 3의 'Brooklyn Institute of Arts.The 35mm gauge').
    번역할 때 한 문장으로 읽히면 뜻이 어긋나므로 여기서 떼어 둔다.

    앞에 소문자·숫자가 두 자 이상 올 때만 손댄다. 그래야 이니셜(J.Smith)이나
    약어(U.S.National)를 건드리지 않는다. 뒤가 대문자일 때만이므로 URL(www.acvl.org)과
    소수점(2003.034)도 그대로 남는다.
    """
    return re.sub(r"(?<=[a-z0-9]{2})\.(?=[A-Z])", ". ", text)

# 내용 스트림에서 '기울여 그린 글'을 찾기 위한 토큰들
_CS_TOK = re.compile(
    rb"(?P<tm>[-\d.]+ [-\d.]+ (?P<c>[-\d.]+) [-\d.]+ [-\d.]+ [-\d.]+ Tm)"
    rb"|(?P<nl>T\*|[-\d.]+ [-\d.]+ T[Dd])"
    rb"|(?P<arr>\[(?:[^\[\]\\]|\\.)*\]\s*TJ)"
    rb"|(?P<str>\((?:[^()\\]|\\.)*\)\s*Tj)")
_CS_STR = re.compile(rb"\((?:[^()\\]|\\.)*\)")
_CS_MAP = {0x91: "‘", 0x92: "’", 0x93: "“", 0x94: "”", 0x96: "–", 0x97: "—",
           0x0a: "", 0x0d: ""}

def _cs_text(raw):
    b = re.sub(rb"\\([()\\])", rb"\1", raw[1:-1])
    return "".join(_CS_MAP.get(c, chr(c)) for c in b)

def italic_runs(page):
    """합성 기울임으로 그려진 글 조각을 찾는다.

    이 책의 각주·캡션 글꼴(Frutiger-LightCn)에는 이탤릭 변형이 없다. 그래서 조판기가
    글자를 기울여서(text matrix 의 skew 성분) 그렸다. PyMuPDF 의 텍스트 추출은 그것을
    스팬 속성으로 내주지 않기 때문에, 각주 안 서명·작품명의 이탤릭이 통째로 사라진다.
    (전권 33쪽 76군데. 본문은 Goudy-Italic 이라는 진짜 이탤릭 글꼴을 써서 멀쩡하다.)

    조판 정보가 스팬에 없으면 내용 스트림에서 직접 읽는 수밖에 없다.
    Tm 의 세 번째 값이 0이 아니면 기울인 것이고, 다음 Tm 이 나올 때까지가 그 구간이다.
    """
    try:
        data = page.read_contents()
    except Exception:
        return []
    cur, out = None, []
    for m in _CS_TOK.finditer(data):
        if m.group("tm"):
            if cur:
                out.append(cur)
            cur = "" if abs(float(m.group("c"))) > 0.2 else None
        elif cur is not None:
            if m.group("nl"):
                # 줄이 바뀐 자리. 줄 끝 하이픈이면 낱말을 붙이고, 아니면 띈다.
                # 그냥 띄면 'Museum Set- ting' 이 되어 본문과 글자가 달라지고,
                # 이 조각을 열쇠로 본문을 찾을 때 걸리지 않는다.
                if re.search(r"[A-Za-z]-$", cur):
                    cur = cur[:-1]
                else:
                    cur += " "
            else:
                body = m.group("arr") or m.group("str")
                cur += "".join(_cs_text(s) for s in _CS_STR.findall(body))
    if cur:
        out.append(cur)
    return [re.sub(r"\s+", " ", x).strip() for x in out if len(x.strip()) > 3]

def apply_synthetic_italics(text, runs):
    """기울여 그린 구간을 마크다운 이탤릭으로 되살린다."""
    n = 0
    for r in sorted(set(runs), key=len, reverse=True):
        if "*" in r or r not in text:
            continue
        if ("*" + r + "*") in text:           # 이미 이탤릭이면 두 번 감싸지 않는다
            continue
        text = text.replace(r, "*" + r + "*")
        n += 1
    return text, n

def bulletize(text):
    """한 문단으로 뭉친 글머리표 목록을 마크다운 목록으로 되돌린다.

    원서는 항목마다 줄을 바꾸고 글머리표를 찍는데, 조판 줄바꿈을 지우는 과정에서
    한 문단으로 붙는다. 목록이 산문처럼 보이면 읽는 사람도 번역하는 쪽도
    항목의 경계를 잃는다. 표 안의 글머리표는 칸 내용이므로 건드리지 않는다.

    어떤 기호를 쓰는지는 책마다 다르다(•, –, ▪, · 등). layout_profile 의
    bullets 값으로 정한다.
    """
    marks = LP.get("bullets")
    pat = "[" + re.escape(marks) + "]"
    out = []
    for block in text.split("\n\n"):
        s = block.strip()
        if len(re.findall(pat, s)) < 2 or s.startswith(("|", "<!--")) or "\n|" in s:
            out.append(block); continue
        quote = s.startswith(">")
        body = re.sub(r"^>\s?", "", s, flags=re.M) if quote else s
        parts = re.split(pat, body)
        head, items = parts[0], [x.strip() for x in parts[1:] if x.strip()]
        if len(items) < 2:
            out.append(block); continue
        lines = ([head.strip()] if head.strip() else []) + ["- " + x for x in items]
        if quote:
            lines = ["> " + l for l in lines]
        out.append("\n".join(lines))
    return "\n\n".join(out)

def render_toc(lines, w):
    """차례: 같은 높이에 놓인 '항목 + 쪽번호'를 한 줄로 짝지어 준다.

    차례는 산문도 명단도 아니다. 한 줄이 왼쪽의 항목과 오른쪽 끝의 쪽번호로 나뉘어
    있고, 둘은 같은 y에 있다. 들여쓰기 깊이가 곧 차례의 단계다(장 → 절 → 소절).

    쪽번호는 원서 기준이라 번역본에서는 다시 매겨야 한다. 색인과 같은 이유로,
    여기서는 항목을 온전히 뽑아 두는 것이 목적이다.
    """
    rows = {}
    for ln in lines:
        rows.setdefault(round(ln["y0"]), []).append(ln)
    if not rows:
        return ""
    base = min(min(l["x0"] for l in g) for g in rows.values())
    out = []
    for y in sorted(rows):
        g = sorted(rows[y], key=lambda l: l["x0"])
        page = ""
        if len(g) > 1 and g[-1]["x0"] > w * 0.5:
            page = g[-1]["text"]; g = g[:-1]
        text = " ".join(l["text"] for l in g).strip()
        if not text:
            continue
        d = g[0]["x0"] - base
        lvl = 2 if d > 20 else (1 if d > 6 else 0)
        out.append("%s- %s%s" % ("  " * lvl, text, (" — %s" % page) if page else ""))
    return "\n".join(out)

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

PAGE_MARK = re.compile(r"\[원서 p\.([^\]]+)\]")

def write_manifest(chap, records, text):
    """위치정보 매니페스트 조각을 남긴다 (파이프라인 2.6절).

    개별 레코드(이미지·표·각주)에 더해, 본문은 **페이지 단위 집계**만 기록한다.
    문단마다 레코드를 남기면 책 한 권에 수천 건이 되어 관리가 되지 않는다.
    번역본에서 페이지별 문단 수가 달라졌는지만 보면 누락은 대개 걸린다.
    """
    import json
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(root, "intermediate", "manifest")
    os.makedirs(d, exist_ok=True)

    # 페이지 마커를 경계로 잘라 페이지마다 문단 수와 첫 줄을 센다
    pages, cur, label = [], [], None
    for block in [b.strip() for b in text.split("\n\n")]:
        if not block:
            continue
        m = PAGE_MARK.fullmatch(block)
        if m:
            pages.append((m.group(1), cur)); cur = []; continue
        cur.append(block)
    if cur:
        pages.append((None, cur))
    summary = []
    for label, blocks in pages:
        body = [b for b in blocks if not b.startswith("<!--")]
        first = next((b for b in body if not b.startswith(("!", "|", "<a id"))), "")
        summary.append({"type": "page_summary", "chunk": chap, "source_page": label,
                        "paragraph_count": len(body),
                        "first_line": re.sub(r"\s+", " ", first)[:60]})

    with open(os.path.join(d, chap + ".json"), "w", encoding="utf-8") as f:
        json.dump({"chunk": chap, "records": records, "pages": summary},
                  f, ensure_ascii=False, indent=1)

def margin_profile(doc, p0, p1, labels):
    """이 구간에서 쪽번호와 러닝헤드가 실제로 어디에 놓이는지 재어 둔다.

    '쪽 위 9%, 아래 12%' 같은 고정 비율만으로 지우면 두 가지가 함께 틀린다.
      · 본문이 쪽 끝까지 내려온 페이지에서 마지막 줄이 사라진다
        (원서 p.105 용어집 표제어 'Printer' 가 그렇게 없어졌다)
      · 쪽번호가 위나 옆에 있는 조판은 아예 걸리지 않는다
        (이 책의 앞부분은 쪽번호가 위쪽에 있다)

    그래서 비율을 정해 놓지 않고 **문서에서 재서** 쓴다. 쪽번호는 그 쪽의 라벨과
    글자가 같으므로 확실하게 찾을 수 있고, 그 자리가 곧 쪽번호 구역이다.
    러닝헤드는 그 구역을 뺀 나머지 여백에서 되풀이되는 짧은 줄이다.

    돌려주는 값
      pno    쪽번호가 놓이는 사각형(여유 포함). 없으면 None
      slots  러닝헤드·러닝풋이 놓이는 자리 [(y, 글자크기), …]

    러닝헤드는 쪽마다 **같은 자리에 같은 크기로** 되풀이된다. 그래서 '위쪽 몇 %'
    같은 범위가 아니라 그 한 줄의 자리를 집어낸다. 이 책에서는 y≈29 · 10.0pt 이고,
    같은 언저리의 다른 것들(절 제목 y≈72 · 14pt, 표 제목 y≈75 · 9pt)과 뚜렷이 갈린다.

    범위로 잡으면 반드시 한쪽이 틀린다. 넓게 잡으면 쪽 위에 놓인 표 제목이 지워지고
    (원서 p.52 'SAMPLE LABORATORY ESTIMATE'), 좁게 잡거나 '본문보다 작은 글자'로
    거르면 본문이 러닝헤드와 같은 크기인 구간에서 러닝헤드가 살아남는다(색인의 'Index').

    둘 다 **책 전체**에서 잰다. 구간별로 재면 두 쪽짜리 부록처럼 러닝헤드가 한 번만
    나오는 구간에서 놓친다(실제로 부록 C·D의 러닝헤드가 본문으로 새어 나왔다).
    쪽번호가 생략된 쪽이 섞여 있어도(이 책은 표제지·판권·차례 첫 쪽·빈 쪽이 그렇다)
    나머지 쪽에서 잰 자리가 그대로 쓰인다.
    """
    import collections
    slots = collections.Counter()
    pno_boxes = []
    for i, page in enumerate(doc):
        h = page.rect.height
        lab = str(labels.get(i, "")).strip()
        for b in page.get_text("dict")["blocks"]:
            if b.get("type") != 0:
                continue
            t = " ".join("".join(s["text"] for s in l["spans"]) for l in b["lines"]).strip()
            if not t:
                continue
            if lab and t == lab:
                pno_boxes.append(b["bbox"])          # 쪽번호는 라벨과 글자가 같다
                continue
            y0, y1 = b["bbox"][1], b["bbox"][3]
            if len(t) < LP.get("head_maxlen") and (y0 < h*0.12 or y1 > h*0.92):
                sz = max(s["size"] for l in b["lines"] for s in l["spans"])
                slots[(round(y0), round(sz, 1))] += 1

    prof = {"pno": None, "slots": []}
    if pno_boxes:
        pad = 5
        prof["pno"] = (min(b[0] for b in pno_boxes) - pad,
                       min(b[1] for b in pno_boxes) - pad,
                       max(b[2] for b in pno_boxes) + pad,
                       max(b[3] for b in pno_boxes) + pad)
    # 몇 쪽에만 나오는 것은 러닝헤드가 아니다. 책 전체 쪽수의 10% 이상에 같은 자리로
    # 되풀이된 것만 본다.
    need = max(3, len(doc) * 0.1)
    prof["slots"] = [s for s, n in slots.items() if n >= need]
    return prof

def in_margin_slot(y0, size, slots, ytol=3.0, stol=0.6):
    return any(abs(y0 - sy) <= ytol and abs(size - ss) <= stol for sy, ss in slots)

def load_overrides(chap):
    """source/overrides/<청크>.yaml 을 읽는다. 없으면 빈 사전."""
    f = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "source", "overrides", chap + ".yaml")
    if not os.path.exists(f):
        return {}
    try:
        import yaml
        return yaml.safe_load(open(f, encoding="utf-8")) or {}
    except Exception as e:
        print("  !! 오버라이드 읽기 실패 %s: %s" % (f, e))
        return {}

def diagrams_for(ovr, label):
    """이 페이지에 선언된 도해 영역.

    흐름도·도식은 표도 사진도 사이드바도 아니다. 그런데 세 검출기가 서로 조각을
    나눠 가지면서 도해 하나가 여러 토막으로 갈린다(원서 p.47은 일곱 조각이 됐다).
    기계가 '이 회색 상자들이 한 그림'임을 알 방법이 없으므로, 시각 판독으로
    영역을 정해 여기에 적어 둔다. 재생성해도 유지된다.
    """
    return [d for d in (ovr.get("diagrams") or []) if str(d.get("page", "")) == str(label)]

def apply_overrides(text, chap):
    """시각 판독 결과(source/overrides/<청크>.yaml)를 반영한다.

    사람(또는 AI)이 원본 페이지를 직접 보고 내린 판단을 파일로 남겨두면,
    원문을 다시 생성해도 그 판단이 사라지지 않는다.

    verdict
      ok      구조에 문제 없음 — 표시만 제거
      join    앞 문단과 이어지는 한 문장 — 합치고 표시 제거
      split   별개의 문단이 맞음 — 표시만 제거
      replace text: 로 준 내용으로 해당 블록을 교체
      replace_region  from: ~ to: 사이를 text: 로 통째 교체.
                      기계가 원리상 뽑을 수 없는 조판(도표 그리드 등)에 쓴다.
    """
    import os
    f = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "source", "overrides", chap + ".yaml")
    if not os.path.exists(f):
        return text, 0
    try:
        import yaml
        d = yaml.safe_load(open(f, encoding="utf-8")) or {}
    except Exception:
        return text, 0
    rules = d.get("resolved") or []
    if not rules:
        return text, 0

    def page_at(pos):
        m = re.search(r"\[원서 p\.([^\]]+)\]", text[pos:])
        return m.group(1) if m else None

    applied = 0
    for r in rules:
        # 구간 통째로 교체. 기계가 애초에 뽑을 수 없는 조판(연도×기호 그리드 등)을
        # 시각 판독 결과로 갈아끼운다. from: 부터 to: 직전까지가 대상이다.
        if r.get("verdict") == "replace_region":
            # from: 그 문구부터 / after: 그 문구 다음부터. after 를 쓰면 앵커를 원문 문장에
            # 걸 수 있어, 정규화기를 고쳐 생성물 모양이 바뀌어도 앵커가 살아남는다.
            a, af, b = r.get("from"), r.get("after"), r.get("to")
            key = a or af
            hit = text.find(key) if key else 0
            i = hit + (len(af) if af and hit >= 0 else 0)
            j = text.find(b, i) if b else len(text)
            if hit < 0 or (b and j < 0):
                print("  !! 구간 교체 실패 (경계 문구를 찾지 못함): %r … %r" % (key, b))
                continue
            text = text[:i] + "\n\n" + (r.get("text") or "").strip() + "\n\n" + text[j:]
            applied += 1
            continue
        key = r.get("marker", "")
        pg = str(r.get("page", ""))
        verdict = r.get("verdict", "ok")
        want = r.get("match")
        nth = r.get("nth")          # 한 쪽에 같은 표시가 여럿일 때 몇 번째인가 (1부터)
        pat = re.compile(r"\n*<!-- " + re.escape(key) + r"[^>]*-->\n")
        pos, seen = 0, 0
        while True:
            m = pat.search(text, pos)
            if not m:
                break
            if page_at(m.start()) != pg:
                pos = m.end(); continue
            seen += 1
            after = text[m.end():m.end() + 120]
            if want and not after.lstrip().startswith(want):
                pos = m.end(); continue
            if nth and seen != int(nth):
                pos = m.end(); continue
            if verdict == "join":
                text = text[:m.start()] + " " + text[m.end():]
            elif verdict == "replace":
                nxt = text.find("\n\n", m.end())
                nxt = nxt if nxt > 0 else len(text)
                text = text[:m.start()] + "\n\n" + (r.get("text") or "").strip() + text[nxt:]
            else:                       # ok / split
                text = text[:m.start()] + "\n\n" + text[m.end():]
            applied += 1
            pos = m.start()
            break
    return re.sub(r"\n{3,}", "\n\n", text), applied

#   prose            산문 규칙 (문장부호 + 들여쓰기)
#   record           줄 좌표·볼드로 항목 경계를 잡는다 (명단·서지)
#   term_definition  볼드 표제어가 곧 항목 경계다. 원서 용어집은 표제어가 문단 첫머리에
#                    볼드로 오고 정의가 이어지는 꼴이라, 산문 규칙이 이미 정확히 나눈다.
#                    (전권 재생성해도 gloss 는 한 글자도 바뀌지 않는다.) 따라서 별도 조립기를
#                    두지 않고 산문 경로를 쓰되, 값은 명시해 회귀 감시 대상으로 남긴다.
#   rebuild          색인. 표제어·하위항목을 줄 단위로 뽑는다
#   toc              차례. 같은 높이의 항목과 쪽번호를 짝지어 한 줄로
PARSERS = ("prose", "record", "term_definition", "rebuild", "toc")

def main(pdf, p0, p1, chap, outpath=None, parser="prose"):
    if parser not in PARSERS:
        # 조용히 산문으로 떨어지면 전용 파서가 안 도는 것을 아무도 눈치채지 못한다.
        raise SystemExit("알 수 없는 파서: %r (가능한 값: %s)" % (parser, ", ".join(PARSERS)))
    doc = pymupdf.open(pdf); labels = page_labels(doc)
    build_lexicon(doc)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    figdir = os.path.join(root, "assets", "figures")
    os.makedirs(figdir, exist_ok=True)
    BODY = detect_body_size(doc, p0, p1)
    OVR = load_overrides(chap)          # 시각 판독 결과 (도해 영역 선언 등)
    mprof = margin_profile(doc, p0, p1, labels)
    print("  (여백 실측: 쪽번호 %s · 머리말/꼬리말 자리 %s)"
          % ([round(v) for v in mprof["pno"]] if mprof["pno"] else "없음",
             mprof["slots"] or "없음"))
    print(f"  (본문 폰트 자동 추정: {BODY}pt)")
    stats = dict(pages=0, blocks=0, paras=0, dehyphen=0, uncertain=0, headers_removed=0,
                 layout_uncertain=0, headings=0, captions=0, fn_refs=0, fn_defs=0, labels=0,
                 tables=0, table_cells=0, sidebars=0, visual_check=0,
                 figures=0, fig_labels=0)
    out, notes = [], []
    # 위치정보 매니페스트(파이프라인 2.6절) — 원본에 무엇이 어디 있었는지 기록한다.
    # 번역이 끝난 뒤 "원본의 이미지·표·각주가 최종본에 다 들어갔는가"를 사람 눈이 아니라
    # 스크립트로 확인하기 위한 것이다. 좌표는 이상이 보일 때 원본을 되짚는 데 쓴다.
    man = []
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

    ital = []
    for i in range(p0-1, p1):
        page = doc[i]; stats["pages"] += 1
        label = labels.get(i, f"?{i+1}")
        ital.extend(italic_runs(page))
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
                # 괄호 위치에 주의: 예전에는 (r[j] if j < len(r) else "" or "") 였는데
                # 이러면 else 쪽만 ("" or "") 로 묶여 r[j] 가 None 일 때 그대로 새어 나온다.
                # 그 AttributeError 를 아래 except 가 삼켜, 그 페이지의 표 검출이 통째로
                # 중단됐다 (원서 p.47 흐름도가 도판 여덟 조각으로 쪼개진 원인).
                usedcol = sum(1 for j in range(ncol)
                              if any(((r[j] or "") if j < len(r) else "").strip() for r in data))
                if usedcol < 2 or filled < len(data) * ncol * 0.35:
                    continue
                tables.append({"bbox": tuple(t.bbox), "md": md_table(data),
                               "rows": len(data), "cols": ncol})
        except Exception as e:
            # 조용히 넘기면 표가 통째로 사라진 것을 아무도 모른다. 자리는 남기되 알린다.
            print("  !! 표 검출 중단 (원서 p.%s): %s" % (labels.get(i, i+1), e))
        # (2) 상자(사이드바 / 서식 상자)
        _tb = [dict(bbox=b["bbox"]) for b in page.get_text("dict")["blocks"]
               if b.get("type") == 0]
        boxes = box_rects(page, _tb)
        sboxes = [r for r, _ in boxes]
        bkinds = [k for _, k in boxes]
        # (3) 각주 구분선 — 이 선 아래만 각주 정의로 인정
        rule_y = footnote_rule_y(page)
        # (4) 도판(사진·도해) 영역 — 표·사이드바와 겹치지 않는 것만
        figs = figmod.find_figures(page, exclude=[t["bbox"] for t in tables] + list(sboxes))
        # 본문 크기 글자를 품고 있는 영역은 사진이 아니다. 사진 안에는 작은 라벨만
        # 들어 있지 본문이 들어 있지 않다. 테두리를 두른 안내 상자가 도판으로 잡혀,
        # 같은 글이 문단으로도 이미지로도 두 번 들어가 있었다 (원서 p.ii 멜론재단 안내).
        _txtblocks = [b for b in page.get_text("dict")["blocks"] if b.get("type") == 0]
        def _has_bodytext(f):
            for b in _txtblocks:
                if not figmod.inside(tuple(b["bbox"]), f, pad=4):
                    continue
                sz = max((s["size"] for l in b["lines"] for s in l["spans"]
                          if s["text"].strip()), default=0)
                txt = " ".join("".join(s["text"] for s in l["spans"]) for l in b["lines"])
                if sz >= BODY - 0.4 and len(txt.strip()) > 60:
                    return True
            return False
        figs = [f for f in figs if not _has_bodytext(f)]

        # (4-1) 시각 판독으로 선언된 도해 영역이 있으면 그 영역은 통째로 그림 하나다.
        # 표·상자·도판 검출이 그 안을 나눠 갖지 못하게 걷어낸다.
        pagediag = diagrams_for(OVR, labels.get(i, f"?{i+1}"))
        if pagediag:
            drects = [tuple(d["rect"]) for d in pagediag]
            def _in_diag(bb):
                return any(figmod.inside(tuple(bb), r, pad=6) for r in drects)
            tables = [t for t in tables if not _in_diag(t["bbox"])]
            keepb = [(r, k) for r, k in zip(sboxes, bkinds) if not _in_diag(r)]
            sboxes = [r for r, _ in keepb]; bkinds = [k for _, k in keepb]
            figs = [f for f in figs if not _in_diag(f)] + drects
        body, fndefs, sides = [], [], {i: [] for i in range(len(sboxes))}
        for b in page.get_text("dict")["blocks"]:
            if b.get("type") != 0: continue
            lines = ["".join(s["text"] for s in l["spans"]).strip() for l in b["lines"]]
            lines = [x for x in lines if x]
            if not lines: continue
            txt = " ".join(lines); y0, x0 = b["bbox"][1], b["bbox"][0]
            # 머리말·쪽번호 제거. 자리는 margin_profile 이 문서에서 재어 둔 것을 쓴다.
            #
            # 쪽번호: 그 쪽의 라벨과 글자가 같고, 쪽번호가 놓이는 자리에 있을 것.
            #   위·아래·옆 어디에 있든 상관없다(이 책 앞부분은 위쪽에 있다).
            # 러닝헤드: 한계선 위에 있고 + 본문보다 작은 글자일 것. 두 신호가 함께
            #   맞아야 한다. 위치만 보면 본문 첫 줄이 걸리고, 반복만 보면 절이 바뀌는
            #   쪽의 러닝헤드(한 쪽에만 나온다)를 놓친다.
            if (mprof["pno"] and txt.strip() == str(label)
                    and inside(b["bbox"], mprof["pno"], pad=2)):
                stats["headers_removed"] += 1; continue
            _sz = max(s["size"] for l in b["lines"] for s in l["spans"])
            if (len(txt) < LP.get("head_maxlen")
                    and in_margin_slot(y0, _sz, mprof["slots"])):
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

        # 캡션이 도판 사이에 끼어 있으면 거기서 나눈다 (사진-캡션-사진 구조)
        split = []
        for f in figs:
            split.extend(figmod.split_by_captions(f, body, BODY))
        figs = split
        figclaim = {i: {"labels": [], "caption": None} for i in range(len(figs))}
        # 도판 안의 글자 조각은 본문에서 빼고 도판에 붙인다
        keep = []
        for b in body:
            fi = next((i for i, f in enumerate(figs)
                       if b["size"] < BODY - 0.4 and figmod.inside(b["bbox"], f, pad=4)), None)
            if fi is None:
                keep.append(b)
            else:
                # 원시 " ".join(lines) 이 아니라 산문과 같은 경로를 태운다.
                # 그래야 줄 끝 하이픈이 붙고(캡션에 몰려 있던 flexibil- ity 류)
                # 이탤릭 작품명도 살아남는다.
                figclaim[fi]["labels"].append(styled_text(b["raw"], stats))
                stats["fig_labels"] += 1
        body = keep

        # 도판 바로 아래의 작은 글씨를 캡션으로 떼어 도판에 붙인다
        capdone = {tuple(d["rect"]) for d in pagediag if d.get("caption")}
        for fi, f in enumerate(figs):
            # 캡션을 직접 적어 둔 도해는 아래 글을 가져가지 않는다.
            # 가져가면 그 글이 선언한 캡션에 덮여 원문에서 사라진다
            # (원서 p.47 도해 밑의 * ** *** **** 주석 네 줄이 그렇게 없어졌다).
            if tuple(f) in capdone:
                continue
            cap = figmod.caption_for(f, body, BODY)
            if cap is not None:
                figclaim[fi]["caption"] = styled_text(cap["raw"], stats)
                cap["is_caption_of"] = fi
        body = [b for b in body if b.get("is_caption_of") is None]

        CS, CL = LP.get("column_split"), LP.get("column_minlen")
        rights = [b for b in body if b["x0"] > w*CS and len(b["txt"]) > CL]
        lefts  = [b for b in body if b["x0"] <= w*CS and len(b["txt"]) > CL]
        multi = bool(rights and lefts)
        def order(x0, y0):
            # 같은 높이에 나란히 놓인 것은 왼쪽부터 읽는다.
            # 눈금은 1pt로 좁게 잡는다. 원서 p.22의 아래 사진 두 장은 y가 0.2pt 달라서
            # 오른쪽이 먼저 나왔는데, 이만큼은 같은 높이로 봐야 한다. 반대로 4pt로
            # 넓히면 1pt 차이로 놓인 서로 다른 단의 블록까지 같은 칸이 되어,
            # 페이지를 넘어 이어지던 문장이 표 제목 뒤로 밀려 끊겼다(p.19→p.20).
            band = round(y0)
            return ((0 if x0 <= w*CS else 1), band, x0) if multi else (0, band, x0)
        # 표·도판·상자도 본문과 같은 기준으로 줄 세운다.
        # (예전에는 페이지 끝에 몰아 넣어서 원서 p.60처럼 '표 제목 → 본문 → 표' 로 뒤집혔다)
        elems = [("body", order(b["x0"], b["y0"]), b) for b in body]
        elems += [("table", order(t["bbox"][0], t["bbox"][1]), t) for t in tables]
        def fig_y(f):
            """도판을 어느 높이로 줄 세울 것인가.

            글 옆에 놓인 도판(텍스트 랩)은 그 문단을 세로로 감싸고 있어서, 위쪽 기준으로
            세우면 문단보다 먼저 나온다. 읽는 사람은 글을 먼저 읽고 곁의 그림을 보므로
            아래쪽 기준이 맞다 (원서 p.5의 'With the passage of time…' 문단과 도판).

            반대로 사진끼리 나란히 놓인 경우에는 아래쪽 기준을 쓰면 안 된다. 두 장의
            아래쪽이 조금만 달라도 좌우 순서가 뒤집힌다 (원서 p.22 아래 두 장).
            그래서 '옆에 글이 있는 도판'일 때만 아래쪽을 쓴다.
            """
            for b in body:
                if b["bbox"][3] <= f[1] or b["bbox"][1] >= f[3]:
                    continue                          # 세로로 겹치지 않는다
                if b["bbox"][2] > f[0] and b["bbox"][0] < f[2]:
                    continue                          # 가로로 겹친다 = 옆이 아니다
                if len(b["txt"]) > LP.get("column_minlen"):
                    return f[3]
            return f[1]
        elems += [("fig", order(f[0], fig_y(f)), (fi, f)) for fi, f in enumerate(figs)]
        elems += [("box", order(min(x["x0"] for x in bl), min(x["y0"] for x in bl)), (bi, bl))
                  for bi, bl in sides.items() if bl]
        elems.sort(key=lambda e: e[1])

        # ── 명단·서지·색인: 줄 좌표로 항목을 나눈다 (파이프라인 2.0-1절 전용 파서) ──
        # 산문 경로는 블록을 한 문자열로 합쳐 버리므로 여기서 쓸 수 없다.
        recgroups, pagenotes, rec_cols = {}, [], set()
        if parser in ("record", "rebuild", "toc"):
            colbody = {}
            for b in body:
                # 제목·대문자 라벨은 산문 경로가 처리한다. 다만 차례에서는 장 제목이
                # 대문자라, 빼 놓으면 목록 끝으로 밀려 순서가 무너진다.
                if b["size"] >= LP.get("h3_pt") or (
                        parser != "toc" and is_caps_label(b["txt"].replace("**", ""))):
                    continue
                if b["size"] < BODY - 0.4 and b["y0"] > h * (LP.get("foot_band") - 0.08):
                    pagenotes.append(b)           # 쪽 아래 안내문 — 명단 사이에 끼면 안 된다
                    continue
                c = 0 if (not multi or b["x0"] <= w*CS) else 1
                colbody.setdefault(c, []).append(b)
            if parser == "toc":
                # 차례는 좌우가 한 줄의 두 부분이므로 단으로 가르지 않는다
                lns = []
                for bs in colbody.values():
                    for b in sorted(bs, key=lambda z: z["y0"]):
                        lns.extend(styled_lines(b["raw"], stats))
                lns.sort(key=lambda z: (round(z["y0"]), z["x0"]))
                recgroups[0] = [lns] if lns else []
            else:
                for c, bs in colbody.items():
                    lns = []
                    for b in sorted(bs, key=lambda z: z["y0"]):
                        lns.extend(styled_lines(b["raw"], stats))
                    lns.sort(key=lambda z: z["y0"])
                    recgroups[c] = split_records(lns)

        if multi and parser not in ("record", "rebuild", "toc"):
            stats["layout_uncertain"] += 1
            # 경고는 바로 내보내지 않고 대기시킨다. 직전 페이지 마커가
            # 문장 한가운데에 들어가야 하는 경우가 있어, 마커 배치가 끝난 뒤에 놓는다.
            pending["warn"] = (f"\n<!-- LAYOUT-UNCERTAIN: p.{label} "
                               f"좌{len(lefts)}/우{len(rights)} 블록 — 읽기 순서 시각 확인 필요 -->\n")

        def emit_nonbody(kind, item, label):
            """표·도판·상자를 읽기 순서 그 자리에 내보낸다."""
            if kind == "fig":
                fi, f = item
                flush_mark(); stats["figures"] += 1
                dg = next((d for d in pagediag if tuple(d["rect"]) == tuple(f)), None)
                name = ("%s-p%s-%s.png" % (chap, label, dg["name"])) if dg \
                       else "%s-p%s-%d.png" % (chap, label, fi + 1)
                if figdir:
                    try:
                        figmod.render(page, f, os.path.join(figdir, name))
                    except Exception as e:
                        print("  !! 도판 렌더 실패 %s: %s" % (name, e))
                cap = figclaim[fi]["caption"] or ""
                figlabels = figclaim[fi]["labels"]
                # 도판 영역이 캡션까지 감싼 경우: 라벨 중 문장꼴을 캡션으로 올린다
                if not cap and figlabels:
                    sent = [t for t in figlabels
                            if len(t) > 20 and t.rstrip().endswith((".", "?", "!"))]
                    if sent:
                        cap = max(sent, key=len)
                        figlabels = [t for t in figlabels if t != cap]
                man.append({"id": name[:-4], "type": "image", "chunk": chap,
                            "source_page": str(label), "bbox": [round(v, 1) for v in f],
                            "asset": "assets/figures/" + name,
                            "diagram": bool(dg)})
                if dg:
                    # 시각 판독을 마친 도해: 그림 한 장으로 두되, 라벨은 표로 병기한다.
                    # 이미지로만 두면 한국어판 독자가 영어 라벨을 보게 되고,
                    # 표로만 옮기면 화살표와 배치가 사라진다. 둘 다 남긴다.
                    out.append("\n![%s](assets/figures/%s)\n"
                               % ((dg.get("caption") or cap).replace("]", ")"), name))
                    if dg.get("note"):
                        out.append("\n<!-- 도해 · 원서 p.%s · %s -->\n" % (label, dg["note"]))
                    if dg.get("table"):
                        out.append("\n%s\n" % dg["table"].strip())
                    return
                out.append("\n<!-- VISUAL-CHECK 도판 · 원서 p.%s · 원본과 대조 필요 -->\n" % label)
                stats["visual_check"] += 1
                out.append("\n![%s](assets/figures/%s)\n" % (cap.replace("]", ")"), name))
                if figlabels:
                    out.append("\n<!-- 도판 라벨 · 원서 p.%s -->\n%s\n"
                               % (label, " · ".join(figlabels)))
            elif kind == "table":
                t = item
                if not t["md"]:
                    return
                flush_mark(); stats["tables"] += 1; stats["visual_check"] += 1
                man.append({"id": "%s-p%s-table%d" % (chap, label, stats["tables"]),
                            "type": "table", "chunk": chap, "source_page": str(label),
                            "bbox": [round(v, 1) for v in t["bbox"]],
                            "rows": t["rows"], "cols": t["cols"]})
                out.append("\n<!-- VISUAL-CHECK 표 %d행 %d열 · 원서 p.%s · 원본과 대조 필요 -->\n%s\n"
                           % (t["rows"], t["cols"], label, t["md"]))
            elif kind == "box":
                bi, blocks_ = item
                kindname = bkinds[bi] if bi < len(bkinds) else "상자"
                stats["sidebars"] += 1
                flush_mark()
                body_md, as_table = box_to_markdown(blocks_, stats)
                warn = ""
                if as_table:
                    stats["visual_check"] += 1
                    warn = ("\n<!-- VISUAL-CHECK 상자 속 표 · 원서 p.%s · 원본과 대조 필요 -->"
                            % label)
                out.append("\n<!-- %s 시작 · 원서 p.%s -->%s\n%s\n<!-- %s 끝 -->\n"
                           % (kindname, label, warn, body_md, kindname))

        for kind, _ord, item in elems:
            if kind != "body":
                emit_nonbody(kind, item, label)
                continue
            b = item
            stats["blocks"] += 1
            if parser in ("record", "rebuild", "toc") and b in pagenotes:
                continue                       # 쪽 아래 안내문은 페이지 끝에 따로 내보낸다
            if parser in ("record", "rebuild", "toc") and not (
                    b["size"] >= LP.get("h3_pt") or (
                        parser != "toc" and is_caps_label(b["txt"].replace("**", "")))):
                # 그 단(段)의 항목을 첫 본문 블록 자리에서 한 번에 내보낸다.
                # 항목은 블록 경계를 넘나들므로 블록마다 따로 내면 다시 쪼개진다.
                # 차례는 좌우가 한 줄의 두 부분이므로 단으로 가르지 않는다
                c = 0 if parser == "toc" else (0 if (not multi or b["x0"] <= w*CS) else 1)
                if c in rec_cols:
                    continue
                rec_cols.add(c)
                flush_mark()
                for rec in recgroups.get(c, []):
                    md = render_toc(rec, w) if parser == "toc" else render_record(rec, parser, stats)
                    out.append("\n%s\n" % md if parser == "toc" else md)
                    stats["paras"] += 1
                flush_warn()
                continue
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

            # 제목·라벨은 이미 마크다운 서식을 붙이므로 볼드 표시를 겹쳐 쓰지 않는다
            head = txt.replace("**", "")
            if b["size"] >= LP.get("h2_pt") and is_wordy(head):
                flush_mark(); out.append(f"\n## {head}\n"); stats["headings"] += 1; carry_idx = None; continue
            if b["size"] >= LP.get("h3_pt") and is_wordy(head):
                flush_mark(); out.append(f"\n### {head}\n"); stats["headings"] += 1; carry_idx = None; continue
            if (TABLE_T.match(head) and len(head) < 110) or is_caps_label(head):
                # 표 제목 / 대문자 라벨: 본문 흐름에서 분리하고 연속 판정 대상에서 제외
                flush_mark(); out.append(f"\n**{head}**\n"); stats["labels"] += 1; carry_idx = None; continue
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

        # (표·도판·상자는 위 elems 루프에서 읽기 순서대로 이미 나갔다)

        # 쪽 아래 안내문 -> 페이지 말미.
        # 명단 구간에서 이 블록은 좌우 단을 가로질러 놓여 있어, 읽기 순서대로 줄을 세우면
        # 알파벳순 명단 한가운데로 끼어든다 (부록C에서 Cinema Arts 와 CinemaLab 사이).
        for b in pagenotes:
            flush_mark()
            out.append("\n%s\n" % styled_text(b["raw"], stats))
            stats["paras"] += 1

        # 각주 정의 -> 페이지 텍스트 말미 (페이지 마커 직전)
        for b in fndefs:
            for num, body_txt in split_fn_defs(styled_text(b["raw"], stats)):
                if num is None: continue
                stats["fn_defs"] += 1
                man.append({"id": "fn-%s-%03d" % (chap, num), "type": "footnote",
                            "chunk": chap, "source_page": str(label),
                            "bbox": [round(v, 1) for v in b["bbox"]]})
                out.append(f'\n<a id="fn-{chap}-{num:03d}"></a> **[각주]** {body_txt}  [↩](#back-{chap}-{num:03d})\n')
        pending["mark"] = label      # 다음 블록이 이어지는지 보고 배치 위치를 정한다

    flush_mark(); flush_warn()
    text = re.sub(r"\n{3,}", "\n\n", "".join(out))
    text = fix_glued_sentences(text)
    text, n_it = apply_synthetic_italics(text, ital)
    stats["synthetic_italic"] = n_it
    text = bulletize(text)
    text, n_ovr = apply_overrides(text, chap)
    stats["overrides"] = n_ovr
    if outpath: open(outpath, "w").write(text)
    write_manifest(chap, man, text)
    print(f"=== 정규화 통계 (파서: {parser}) ===")
    for k, v in stats.items(): print(f"  {k}: {v}")
    # 최종 결과에서 다시 센다. 오버라이드로 해소된 표시까지 남은 것으로 세면
    # 이미 판독을 마친 구간이 계속 '재작업 필요'로 보고된다.
    left = text.count("LINEBREAK-UNCERTAIN")
    paras = max(1, len([b for b in text.split("\n\n") if b.strip()]))
    print(f"  >>> 불확실 판정 비율: {left}/{paras} = {left/paras*100:.1f}%")
    for n in notes[:6]: print("  · " + n)
    return text

if __name__ == "__main__":
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    pmode = next((a.split("=", 1)[1] for a in sys.argv[1:]
                  if a.startswith("--parser=")), "prose")
    t = main(argv[0], int(argv[1]), int(argv[2]), argv[3],
             argv[4] if len(argv) > 4 else None, parser=pmode)
