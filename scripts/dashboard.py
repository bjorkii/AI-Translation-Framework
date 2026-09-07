#!/usr/bin/env python3
"""번역 프로젝트 로컬 대시보드.

    python3 scripts/dashboard.py        ->  http://127.0.0.1:8765

표준 라이브러리만 사용합니다(별도 설치 불필요). 파일을 요청마다 새로 읽으므로
AI가 파일을 고치든 사용자가 화면에서 고치든 양쪽이 곧바로 반영됩니다.
"""
import json, re, subprocess, os, html as _html
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = int(os.environ.get("PORT", "8765"))

# 청크가 거쳐야 하는 단계(진행율 계산 기준)
STAGES = ["pending", "normalized", "draft", "ai_review_1", "ai_review_2",
          "human_review", "ai_revise", "final"]
STAGE_LABEL = {"pending": "대기", "normalized": "정규화", "draft": "AI 1차 번역",
               "ai_review_1": "AI 1차 감수", "ai_review_2": "AI 2차 감수",
               "human_review": "사람 감수", "ai_revise": "AI 보완", "final": "완료"}
TRACK_STAGES = ["draft", "ai_review_1", "ai_review_2", "ai_revise", "final"]
STATUS_KO = {"approved": "승인", "rejected": "반려", "note": "메모", "withdrawn": "철회"}

# 서버 재실행 요청 깃발.
# 이 파일은 자기를 어떻게 띄웠는지 모른다(직접 실행일 수도, launch.py 를 거쳤을 수도).
# 그래서 여기서는 깃발만 세우고, 실제로 다시 띄우는 일은 launch.py 의 감시 스레드가 한다.
RESTART = {"want": False, "quit": False}

# ---------------------------------------------------------------- 파일 읽기

def read(p, default=""):
    f = ROOT / p
    return f.read_text(encoding="utf-8") if f.exists() else default

def parse_structure():
    out, section = [], None
    for line in read("structure-map.yaml").splitlines():
        if re.match(r"^(chapters|back_matter|front_matter):", line):
            section = line.split(":")[0]; continue
        m = re.match(r"^\s*-\s*\{(.+)\}\s*$", line)
        if not m or section not in ("front_matter", "chapters", "back_matter"):
            continue
        body = m.group(1)
        def g(key, pat=r'([^,}]+)'):
            mm = re.search(key + r":\s*" + pat, body)
            return mm.group(1).strip().strip('"') if mm else None
        pr = re.search(r'printed:\s*\[([^\]]+)\]', body)
        out.append({
            "id": g("id"), "title": g("title", r'"([^"]*)"'),
            "printed": [x.strip().strip('"') for x in pr.group(1).split(",")] if pr else [],
            "pages": g("pages"), "section": section,
            "parser": g("parser"), "split": g("split") == "true",
        })
    return out

def parse_glossary():
    txt = read("glossary/glossary.yaml")
    entries = []
    for m in re.finditer(r'  - term: "(.*?)"\n(.*?)(?=\n  - term: |\Z)', txt, re.S):
        term, body = m.group(1), m.group(2)
        def f(k):
            mm = re.search(r'^\s{4}' + k + r':\s*(?:"(.*?)"|(null))\s*$', body, re.M)
            return mm.group(1) if (mm and mm.group(1) is not None) else None
        entries.append({
            "term": term, "translation": f("translation"), "tbd": f("tbd"),
            "notation": f("notation"), "context": f("context"), "full": f("full"),
            "definition_en": f("definition_en"), "source": f("source"),
        })
    return entries

def source_quality(cid):
    """원문 정규화 결과의 불확실 표시 비율. 높으면 전용 파서가 필요하다는 뜻."""
    f = ROOT / "source" / (cid + ".md")
    if not f.exists():
        return None
    t = f.read_text(encoding="utf-8")
    unc = t.count("LINEBREAK-UNCERTAIN")
    paras = max(1, len([b for b in t.split("\n\n") if b.strip()]))
    return {"uncertain": unc, "paras": paras, "ratio": round(unc / paras * 100, 1)}

VIS_PAT = re.compile(r"<!--\s*(VISUAL-CHECK[^>]*?)\s*-->")
VIS_UNC = re.compile(r"<!--\s*(LINEBREAK-UNCERTAIN|LAYOUT-UNCERTAIN[^>]*?)\s*-->")

def visual_open(cid):
    """원본과 대조하지 않고 남아 있는 표·도판·불확실 구간의 수.

    scripts/check_visual.py 와 같은 규약(reviews/<청크>-visual.json 의 ok:true 로 해소)을 쓴다.
    그 검사는 명령줄에서만 볼 수 있어, 화면에서는 몇 건이 밀려 있는지 알 수가 없었다.
    """
    f = ROOT / "source" / (cid + ".md")
    if not f.exists():
        return None
    t = f.read_text(encoding="utf-8")
    its = [m.group(1) for m in VIS_PAT.finditer(t)] + [m.group(1) for m in VIS_UNC.finditer(t)]
    if not its:
        return None
    rf = ROOT / "reviews" / ("%s-visual.json" % cid)
    try:
        done = json.loads(rf.read_text(encoding="utf-8")) if rf.exists() else {}
    except Exception:
        done = {}
    openi = [x for x in its if not (done.get(x) or {}).get("ok")]
    return {"open": len(openi), "total": len(its)}

def chunk_stage(cid):
    src = (ROOT / "source" / (cid + ".md")).exists()
    tgt = ROOT / "chapters" / (cid + ".md")
    if tgt.exists():
        m = re.search(r"^stage:\s*(\S+)", tgt.read_text(encoding="utf-8"), re.M)
        return (m.group(1) if m else "draft"), src, True
    return ("normalized" if src else "pending"), src, False

def git_log(n=8):
    try:
        r = subprocess.run(["git", "log", "--oneline", "-%d" % n],
                           cwd=ROOT, capture_output=True, text=True, timeout=5)
        return [l for l in r.stdout.splitlines() if l.strip()]
    except Exception:
        return []

def started_date():
    """번역 시작일: project-info.json의 started, 없으면 첫 커밋 날짜."""
    info = json.loads(read("project-info.json", "{}") or "{}")
    if info.get("started"):
        return info["started"]
    try:
        r = subprocess.run(["git", "log", "--reverse", "--format=%cs"],
                           cwd=ROOT, capture_output=True, text=True, timeout=5)
        lines = [l for l in r.stdout.splitlines() if l.strip()]
        return lines[0] if lines else date.today().isoformat()
    except Exception:
        return date.today().isoformat()

def build_state():
    info = json.loads(read("project-info.json", "{}") or "{}")
    ctx = json.loads(read("glossary/term-context.json", "{}") or "{}")

    chunks, steps_done = [], 0
    for c in parse_structure():
        stage, has_src, has_tgt = chunk_stage(c["id"])
        idx = STAGES.index(stage) if stage in STAGES else 0
        steps_done += idx
        q = source_quality(c["id"])
        c.update(stage=stage, stage_label=STAGE_LABEL.get(stage, stage),
                 stage_index=idx, has_source=has_src, has_target=has_tgt,
                 src_quality=q, visual=visual_open(c["id"]),
                 src_needs_parser=bool(q and q["ratio"] >= 15))
        chunks.append(c)
    visual_open_total = sum((c.get("visual") or {}).get("open", 0) for c in chunks)
    per_chunk = len(STAGES) - 1
    total_steps = len(chunks) * per_chunk
    percent = round(steps_done / total_steps * 100, 1) if total_steps else 0.0

    start = started_date()
    try:
        elapsed = (date.today() - datetime.strptime(start, "%Y-%m-%d").date()).days + 1
    except Exception:
        elapsed = 1

    gl = parse_glossary()
    def enrich(e):
        c = ctx.get(e["term"], {}) or {}
        return {"term": e["term"], "translation": e["translation"], "tbd": e["tbd"],
                "notation": e["notation"], "context": e["context"], "full": e["full"],
                "definition_en": e["definition_en"],
                "quotes": c.get("quotes", []),
                "hits": c.get("hits"), "in_chunks": c.get("chunks", []),
                "options": c.get("options", []) or ([o.strip() for o in e["tbd"].split("|")] if e["tbd"] else [])}
    all_items = [enrich(e) for e in gl]
    pending = [dict(x, current=x["translation"]) for x in all_items if x["tbd"]]
    decided = [x for x in all_items if x["translation"] and not x["tbd"]]

    log = read_log()
    unacked = [r for r in log if not r.get("ack")]
    return {
        "inbox": {"unacked": len(unacked), "total": len(log),
                  "items": unacked[-30:]},
        "info": info, "chunks": chunks, "status_md": read("status.md"),
        "commits": git_log(),
        "visual": {"open": visual_open_total},
        "progress": {"started": start, "elapsed_days": elapsed, "percent": percent,
                     "steps_done": steps_done, "steps_total": total_steps,
                     "per_chunk": per_chunk, "stages": STAGES,
                     "stage_labels": [STAGE_LABEL[s] for s in STAGES]},
        "glossary": {
            "total": len(gl), "decided": len(decided), "pending": len(pending),
            "untouched": len([e for e in all_items if not e["translation"] and not e["tbd"]]),
            "pending_items": pending, "decided_items": decided, "all_items": all_items,
        },
    }

LOG = "glossary/decision-log.jsonl"

def log_decision(kind, term, choice, note, actor="user"):
    """결정을 수신함에 기록합니다.

    actor="user" (화면에서 사람이 내린 결정) -> 미확인 상태로 쌓이고,
    AI는 작업을 시작할 때 이 목록을 먼저 확인합니다.
    actor="ai"   (대화로 받은 결정을 AI가 대신 입력) -> 이미 반영한 것이므로
    확인 완료로 기록해 수신함에 불필요하게 쌓이지 않게 합니다."""
    by_ai = (actor == "ai")
    rec = {"ts": datetime.now().isoformat(timespec="seconds"), "actor": actor,
           "type": kind, "term": term, "choice": choice, "note": note or "",
           "ack": by_ai}
    if by_ai:
        rec["ack_at"] = rec["ts"]
        rec["ack_note"] = "대화로 받은 결정을 AI가 대신 입력"
    with (ROOT / LOG).open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

def read_log():
    out = []
    f = ROOT / LOG
    if not f.exists():
        return out
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


# ---------------------------------------------------------------- 파일 쓰기

def apply_decision(term, choice, note, full=None, actor="user"):
    if len(choice) > 60:
        return False, ("번역어가 너무 깁니다(%d자). 본문에 들어갈 표기만 남기고, "
                       "약어의 정식 명칭은 '풀어쓴 이름' 칸에, 사용 규칙은 메모 칸에 넣어 주세요." % len(choice))
    if '"' in choice:
        return False, "번역어에 큰따옴표는 넣을 수 없습니다. 작은따옴표를 써 주세요."
    path = ROOT / "glossary" / "glossary.yaml"
    txt = path.read_text(encoding="utf-8")
    pat = re.compile(r'(  - term: "' + re.escape(term) + r'"\n)(.*?)(?=\n  - term: |\Z)', re.S)
    m = pat.search(txt)
    if not m:
        return False, "용어집에서 항목을 찾지 못했습니다: " + term
    head, body = m.group(1), m.group(2)
    body = re.sub(r'^\s{4}translation:.*$', '    translation: "%s"' % choice, body, count=1, flags=re.M)
    body = re.sub(r'^\s{4}tbd:.*\n', '', body, flags=re.M)
    body = re.sub(r'^\s{4}notation:.*\n', '', body, flags=re.M)
    body = re.sub(r'^\s{4}full:.*\n', '', body, flags=re.M)
    if note:
        body = body.rstrip("\n") + '\n    notation: "%s"\n' % note.replace('"', "'")
    if full:
        body = body.rstrip("\n") + '\n    full: "%s"\n' % full.replace('"', "'")
    path.write_text(txt[:m.start()] + head + body + txt[m.end():], encoding="utf-8")
    log_decision("decide", term, choice, note, actor)
    return True, "확정: %s → %s" % (term, choice)

def add_term(term, translation, note, actor="user"):
    path = ROOT / "glossary" / "glossary.yaml"
    txt = path.read_text(encoding="utf-8")
    if re.search(r'  - term: "' + re.escape(term) + r'"', txt):
        return False, "이미 있는 용어입니다: " + term
    block = '  - term: "%s"\n    translation: "%s"\n' % (term, translation)
    if note:
        block += '    notation: "%s"\n' % note.replace('"', "'")
    block += ('    definition_en: null\n    definition_ko: null\n'
              '    source: "대시보드에서 추가"\n    principle_form: null\n'
              '    adopted_form: null\n    basis: null\n'
              '    first_chapter: null\n    locked: false\n')
    path.write_text(txt.rstrip("\n") + "\n" + block, encoding="utf-8")
    log_decision("add", term, translation, note, actor)
    return True, "추가: %s → %s" % (term, translation)

def delete_term(term, actor="user"):
    path = ROOT / "glossary" / "glossary.yaml"
    txt = path.read_text(encoding="utf-8")
    pat = re.compile(r'(  - term: "' + re.escape(term) + r'"\n)(.*?)(?=\n  - term: |\Z)', re.S)
    m = pat.search(txt)
    if not m:
        return False, "용어집에서 항목을 찾지 못했습니다: " + term
    prev = re.search(r'^\s{4}translation:\s*"(.*?)"', m.group(2), re.M)
    path.write_text((txt[:m.start()] + txt[m.end():]).replace("\n\n\n", "\n\n"), encoding="utf-8")
    log_decision("delete", term, prev.group(1) if prev else "", "", actor)
    return True, "삭제: " + term

def rename_term(term, new_term, actor="user"):
    if not new_term:
        return False, "새 원어를 입력해 주세요."
    path = ROOT / "glossary" / "glossary.yaml"
    txt = path.read_text(encoding="utf-8")
    if not re.search(r'  - term: "' + re.escape(term) + r'"', txt):
        return False, "용어집에서 항목을 찾지 못했습니다: " + term
    if re.search(r'  - term: "' + re.escape(new_term) + r'"', txt):
        return False, "이미 있는 용어입니다: " + new_term
    txt = txt.replace('  - term: "%s"\n' % term, '  - term: "%s"\n' % new_term, 1)
    path.write_text(txt, encoding="utf-8")
    log_decision("rename", term, new_term, "", actor)
    return True, "원어 수정: %s → %s" % (term, new_term)


# ------------------------------------------------------- 마크다운 렌더링

# 강조(*, **, ***) — 여는 표시와 닫는 표시가 실제로 짝을 이룰 때만 서식으로 본다.
#
# 별표를 앞에서부터 순서대로 치환하면 두 가지가 함께 깨진다.
#   · ***작품명*** 이 '여는 ** + 남는 *' 로 쪼개져 <strong><em>…</strong></em> 라는
#     서로 침범한 태그가 나온다 (원문 12건).
#   · 원서가 각주 기호로 쓰는 *, **, ***, **** 가 (원서 p.47 표 아래처럼 짝이 없는데도)
#     강조로 잡혀 그 뒤 문장 전체의 서식이 뒤집힌다.
#
# CommonMark 의 좌/우 인접 규칙을 그대로 쓴다.
#   여는 표시: 바로 뒤가 공백이 아니어야 한다
#   닫는 표시: 바로 앞이 공백이 아니어야 한다
# 각주 기호는 모두 '공백 + 별표 + 글자' 꼴이라 여는 쪽 조건만 만족하고 닫는 쪽이 없다.
# 따라서 짝을 찾지 못해 글자 그대로 남는다 — 이것이 올바른 결과다.
_EM = re.compile(r"(?<!\*)(\*{1,3})(?!\*)(?!\s)(.+?)(?<![\s*])\1(?!\*)", re.S)

def _em_sub(m):
    d, body = m.group(1), _EM.sub(_em_sub, m.group(2))   # 안쪽 강조를 먼저 푼다
    if len(d) == 3: return "<strong><em>%s</em></strong>" % body
    if len(d) == 2: return "<strong>%s</strong>" % body
    return "<em>%s</em>" % body

# 역슬래시로 막아 둔 글자를 잠시 치워 둔다.
# 원서가 각주 기호로 쓴 별표(*, **, ***, ****)는 정규화기가 \* 로 적어 보낸다.
# 그대로 두면 강조 표시로 읽혀 뒤 문장의 서식이 통째로 뒤집힌다.
_ESC = re.compile(r"\\([*_`\[\]\\])")
_UNESC = re.compile("\ue000([0-9]+)\ue001")

def md_inline(s):
    s = _ESC.sub(lambda m: "\ue000%d\ue001" % ord(m.group(1)), s)
    s = _html.escape(s, quote=False)
    s = re.sub(r"&lt;(/?(?:a|b|i|em|strong|br|span|sup|sub)\b[^&]*?)&gt;", r"<\1>", s)  # 앵커 등 통과
    # 페이지 마커를 링크보다 먼저 치환한다.
    # 나중에 하면 링크 정규식이 '[원서 p.42] … [⁵](#fn-…)' 를 하나의 링크로 잘못 묶어
    # 그 사이 문장이 통째로 링크 안에 삼켜진다.
    s = re.sub(r"\[원서 (p\.[^\]]+)\]",
               r'<span class="pagemark" title="원서 \1이 여기서 끝납니다">원서 \1 여기까지<span class="tick">⇥</span></span>', s)
    # 링크 텍스트·주소에 대괄호/괄호가 다시 나오지 않도록 막아 범위가 번지지 않게 한다
    def _img(m):
        alt, src = m.group(1), m.group(2)
        if not src.startswith(("http", "/", "data:")):
            src = "/" + src.lstrip("./")          # assets/figures/x.png -> /assets/figures/x.png
        cap = ('<figcaption>%s</figcaption>' % alt) if alt.strip() else ""
        return '<figure><img src="%s" alt="%s" loading="lazy">%s</figure>' % (src, alt, cap)
    s = re.sub(r"!\[([^\]\[]*)\]\(([^()\s]*)\)", _img, s)
    s = re.sub(r"\[([^\]\[]*)\]\(([^()\s]*)\)", r'<a href="\2">\1</a>', s)
    s = _EM.sub(_em_sub, s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return _UNESC.sub(lambda m: _html.escape(chr(int(m.group(1))), quote=False), s)

def _marker_style(tag):
    """정규화기가 남긴 표시를 종류별로 갈라 색과 문구를 준다.

    셋은 사람이 해야 할 일이 서로 다르다. 같은 옅은 배지로 뭉뚱그리면
    '원본을 열어봐야 하는 것'과 '규칙이 판단을 못 한 것'이 구분되지 않는다.
    """
    if tag.startswith("VISUAL-CHECK"):
        return "marker vcheck", tag.replace("VISUAL-CHECK", "원본 대조 필요 ·", 1)
    if tag.startswith("LINEBREAK-UNCERTAIN"):
        return "marker unc-line", "문단 경계 불확실 — 이어지는 문장인지 원본 확인 필요"
    if tag.startswith("LAYOUT-UNCERTAIN"):
        return "marker unc-layout", tag.replace("LAYOUT-UNCERTAIN:", "읽기 순서 불확실 ·", 1)
    return "marker", tag

FN_DEF = re.compile(r'^\s*<a id="(fn-[\w.-]+?-(\d+))"></a>\s*(?:\*\*)?\[각주\](?:\*\*)?\s*(.*)$')

TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
TABLE_SEP = re.compile(r"^\s*\|[\s:|-]+\|\s*$")

def _cells(line):
    body = TABLE_ROW.match(line).group(1)
    # 셀 안의 이스케이프된 파이프(\|)는 자르지 않는다
    parts, buf, esc = [], "", False
    for ch in body:
        if esc:
            buf += ch if ch == "|" else "\\" + ch
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == "|":
            parts.append(buf); buf = ""
        else:
            buf += ch
    parts.append(buf)
    return [c.strip() for c in parts]

def md_table_html(rows):
    """마크다운 표 -> HTML 표. 첫 줄은 머리행, 둘째 줄은 구분선."""
    head = _cells(rows[0])
    body = [_cells(r) for r in rows[2:]]
    n = max([len(head)] + [len(r) for r in body]) if body else len(head)
    def pad(r): return r + [""] * (n - len(r))
    h = ["<div class='tablewrap'><table><thead><tr>"]
    h += ["<th>%s</th>" % md_inline(c) for c in pad(head)]
    h.append("</tr></thead><tbody>")
    for r in body:
        h.append("<tr>" + "".join("<td>%s</td>" % md_inline(c) for c in pad(r)) + "</tr>")
    h.append("</tbody></table></div>")
    return "".join(h)

def md_to_html(md):
    out, in_code, in_ul, in_ol = [], False, False, False
    in_box = 0          # 열려 있는 상자 수 — 짝이 어긋나도 문서가 상자에 갇히지 않게 한다
    sub_ul = False      # 들여쓴 목록(색인의 하위항목)이 열려 있는가
    def close():
        nonlocal in_ul, in_ol, sub_ul
        if sub_ul: out.append("</ul></li>"); sub_ul = False
        if in_ul: out.append("</ul>"); in_ul = False
        if in_ol: out.append("</ol>"); in_ol = False
    lines = md.split("\n")
    # YAML frontmatter -> 메타 상자
    if lines and lines[0].strip() == "---":
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
        if end:
            meta = "\n".join(lines[1:end])
            out.append('<div class="meta"><pre>' + _html.escape(meta) + "</pre></div>")
            lines = lines[end + 1:]
    pend = list(lines)
    while pend:
        raw = pend.pop(0)
        line = raw.rstrip()
        if line.strip().startswith("```"):
            close(); out.append("</pre>" if in_code else "<pre class='code'>"); in_code = not in_code; continue
        if in_code:
            out.append(_html.escape(raw)); continue
        m = re.match(r"^\s*<!--\s*(.*?)\s*-->\s*$", line)
        if m:
            close()
            tag = m.group(1)
            mb = re.match(r"^(사이드바|상자) 시작(?: · (.+))?$", tag)
            if mb:
                out.append('<aside class="box"><div class="boxhead">%s%s</div>'
                           % (_html.escape(mb.group(1)),
                              (' <span>%s</span>' % _html.escape(mb.group(2))) if mb.group(2) else ""))
                in_box += 1
                continue
            if re.match(r"^(사이드바|상자) 끝$", tag):
                # 여는 표시 없이 닫는 표시만 온 경우 </aside> 를 내보내면 바깥 구조가 깨진다
                if in_box:
                    out.append("</aside>"); in_box -= 1
                continue
            cls, label = _marker_style(tag)
            out.append('<div class="%s">%s</div>' % (cls, _html.escape(label)))
            continue
        if not line.strip():
            close(); continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            close(); n = len(m.group(1))
            out.append("<h%d>%s</h%d>" % (n, md_inline(m.group(2)), n)); continue
        if re.match(r"^\s*(-{3,}|\*{3,})\s*$", line):
            close(); out.append("<hr>"); continue
        if TABLE_ROW.match(line) and not TABLE_SEP.match(line):
            # 표는 여러 줄이 모여야 하나이므로 뒤따르는 표 줄을 모두 모은다
            close()
            rows = [line]
            while pend and TABLE_ROW.match(pend[0].rstrip()):
                rows.append(pend.pop(0).rstrip())
            if len(rows) >= 2 and TABLE_SEP.match(rows[1]):
                out.append(md_table_html(rows))
            else:
                for r in rows:
                    out.append("<p>%s</p>" % md_inline(r))
            continue
        m = re.match(r"^\s*>\s?(.*)$", line)
        if m:
            close(); out.append("<blockquote>%s</blockquote>" % md_inline(m.group(1))); continue
        m = re.match(r"^(\s*)[-*+]\s+(.*)$", line)
        if m:
            if in_ol: out.append("</ol>"); in_ol = False
            deep = len(m.group(1)) >= 2      # 색인의 하위항목
            if not in_ul:
                out.append("<ul>"); in_ul = True
            if deep and not sub_ul and out and out[-1].endswith("</li>"):
                # 직전 표제어 항목 안으로 하위 목록을 넣는다
                out[-1] = out[-1][:-len("</li>")]
                out.append("<ul class='sub'>"); sub_ul = True
            elif not deep and sub_ul:
                out.append("</ul></li>"); sub_ul = False
            out.append("<li>%s</li>" % md_inline(m.group(2))); continue
        m = re.match(r"^\s*\d+[.)]\s+(.*)$", line)
        if m:
            if in_ul: out.append("</ul>"); in_ul = False
            if not in_ol: out.append("<ol>"); in_ol = True
            out.append("<li>%s</li>" % md_inline(m.group(1))); continue
        m = FN_DEF.match(line)
        if m:
            close()
            out.append('<div class="fn" id="%s"><span class="fnno">%s</span>'
                       '<div class="fnbody">%s</div></div>' % (m.group(1), str(int(m.group(2))), md_inline(m.group(3))))
            continue
        if line.lstrip().startswith("<"):
            close(); out.append("<p>%s</p>" % md_inline(line)); continue
        close(); out.append("<p>%s</p>" % md_inline(line))
    if in_code: out.append("</pre>")
    close()
    while in_box:       # 청크 경계에서 상자가 잘려도 뒤 문서가 상자 안에 갇히지 않게 닫는다
        out.append("</aside>"); in_box -= 1
    return "\n".join(out)

VIEW_CSS = """
:root{--ground:#EDEFEE;--surface:#fff;--ink:#12171A;--muted:#5A6668;--faint:#8A9698;
--accent:#0F6E73;--border:#D2D9D8;--mark:#A85F22;--mark-soft:#F6E8DA}
@media(prefers-color-scheme:dark){:root{--ground:#0E1414;--surface:#161F1E;--ink:#E6EDEC;
--muted:#93A2A2;--faint:#71807F;--accent:#57C3C7;--border:#26302F;--mark:#DB9752;--mark-soft:#2A2118}}
body{margin:0;background:var(--ground);color:var(--ink);
font:16px/1.75 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Noto Sans KR",system-ui,sans-serif}
.page{max-width:760px;margin:0 auto;padding:36px 24px 96px}
.crumb{font-size:13px;color:var(--muted);margin-bottom:18px}
h1{font-size:27px;margin:0 0 20px;letter-spacing:-.015em}
h2{font-size:22px;margin:34px 0 10px}h3{font-size:18px;margin:26px 0 8px}
p{margin:0 0 15px}
.meta{background:var(--surface);border:1px solid var(--border);border-radius:9px;
padding:10px 14px;margin-bottom:24px}
.meta pre{margin:0;font-size:12.5px;color:var(--muted);white-space:pre-wrap}
.marker{font-size:12px;color:var(--mark);background:var(--mark-soft);border-radius:6px;
padding:3px 9px;display:inline-block;margin:8px 0}
.pagemark{font-size:11.5px;color:var(--muted);background:var(--surface);border:1px solid var(--border);
border-radius:5px;padding:1px 6px 1px 7px;white-space:nowrap;letter-spacing:.02em}
.pagemark .tick{color:var(--accent);margin-left:5px;font-weight:600}
.fn{display:grid;grid-template-columns:24px minmax(0,1fr);gap:12px;align-items:start;
background:var(--surface);border-left:3px solid var(--accent);border-radius:0 8px 8px 0;
padding:11px 14px;margin:10px 0;font-size:14px;line-height:1.6}
.fnno{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;
border-radius:50%;background:var(--accent);color:var(--ground);font-size:12px;font-weight:700}
.fnbody{color:var(--muted);min-width:0}
.fnbody a{text-decoration:none;font-size:15px}
.fnbody em{font-style:italic}
a{color:var(--accent)}
figure{margin:20px 0;text-align:center}
figure img{max-width:100%;border:1px solid var(--border);border-radius:6px}
figcaption{font-size:13px;color:var(--muted);margin-top:6px}
blockquote{margin:0 0 15px;padding-left:14px;border-left:3px solid var(--border);color:var(--muted)}
pre.code{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:12px;
overflow-x:auto;font-size:13px}
hr{border:0;border-top:1px solid var(--border);margin:28px 0}
.box{background:var(--surface);border:1px solid var(--border);border-radius:10px;
padding:14px 18px 4px;margin:22px 0}
.box .boxhead{font-size:11px;letter-spacing:.09em;text-transform:uppercase;color:var(--faint);
margin-bottom:8px}
.box .boxhead span{text-transform:none;letter-spacing:0;opacity:.8}
.box blockquote{margin:0 0 12px;padding:0;border:0;color:var(--ink)}
.box p{margin:0 0 12px}
.marker.vcheck{color:#fff;background:#B3261E}
.marker.unc-line{color:#fff;background:#8A5A00}
.marker.unc-layout{color:#fff;background:#5B4B8A}
ul.sub{margin:2px 0 6px;padding-left:20px}
ul.sub li{color:var(--muted);font-size:15px}
.tablewrap{overflow-x:auto;margin:16px 0;border:1px solid var(--border);border-radius:8px;
background:var(--surface)}
table{border-collapse:collapse;width:100%;font-size:14px;line-height:1.55}
th,td{padding:8px 12px;text-align:left;vertical-align:top;border-bottom:1px solid var(--border)}
th{background:var(--ground);font-weight:600;font-size:13px;white-space:nowrap}
tbody tr:last-child td{border-bottom:0}
td{color:var(--muted)}
td:first-child{color:var(--ink);font-weight:500}
"""

COMPARE_CSS = """
.pair{margin:0 0 30px;border-bottom:1px solid var(--border);padding-bottom:22px}
.pair:last-child{border-bottom:0}
.side{border-radius:0 8px 8px 0;padding:10px 16px;margin-bottom:8px}
.side .tag{display:block;font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;
color:var(--faint);margin-bottom:4px}
.side.src{border-left:3px solid var(--faint)}
.side.src p,.side.src li{font-family:Georgia,"Times New Roman",serif;color:var(--muted)}
.side.draft{border-left:3px solid var(--accent);background:var(--surface)}
.side.review{border-left:3px solid #7a9e3a;background:var(--surface)}
.side.revise{border-left:3px solid #9a7ac0;background:var(--surface)}
.side p:last-child{margin-bottom:0}
.side h1,.side h2,.side h3{margin:2px 0 6px}
ins{background:rgba(90,170,100,.22);text-decoration:none;border-radius:3px;padding:0 2px}
del{background:rgba(200,90,80,.20);border-radius:3px;padding:0 2px}
.note{margin:6px 0 0 16px;font-size:13px;color:var(--muted);border-left:2px solid var(--border);
padding:4px 12px}
.note b{color:var(--ink);font-weight:600}
.ok{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:10px;padding:10px 16px;
border-left:3px solid var(--border);border-radius:0 8px 8px 0;background:var(--surface)}
.ok button{font:inherit;font-size:13px;border:1px solid var(--border);border-radius:7px;
padding:6px 14px;cursor:pointer;background:var(--surface);color:var(--ink)}
.ok button.yes.on{background:#2f6b4f;border-color:#2f6b4f;color:#fff}
.ok button.no.on{background:#a8443a;border-color:#a8443a;color:#fff}
.ok textarea{flex:1 1 320px;font:inherit;font-size:13px;line-height:1.6;background:var(--ground);
color:var(--ink);border:1px solid var(--border);border-radius:7px;padding:7px 10px;
min-height:34px;min-width:220px;max-width:100%;resize:both;overflow:auto}
.ok textarea:focus{outline:0;border-color:var(--accent)}
.ok textarea:disabled{opacity:.75}
.ok .state{font-size:12px;color:var(--faint)}
.warn{background:var(--mark-soft);color:var(--mark);border-radius:8px;padding:10px 14px;
margin-bottom:20px;font-size:13.5px}
.bar{position:sticky;top:0;z-index:5;background:var(--ground);padding:10px 0 12px;
display:flex;gap:14px;align-items:center;flex-wrap:wrap;border-bottom:1px solid var(--border);
margin-bottom:20px;font-size:13px}
.bar .cnt{font-variant-numeric:tabular-nums;color:var(--muted)}
.bar button{font:inherit;font-size:12.5px;border:1px solid var(--border);border-radius:7px;
padding:5px 12px;background:var(--surface);color:var(--ink);cursor:pointer}
.bar button.on{background:var(--accent);border-color:var(--accent);color:var(--ground)}
.pair{position:relative;padding-left:10px}
.pair::before{content:"";position:absolute;left:0;top:2px;bottom:22px;width:3px;border-radius:2px;
background:transparent}
.pair.st-approved::before{background:#2f6b4f}
.pair.st-rejected::before{background:#a8443a}
.pair.st-note::before{background:var(--border2)}
.pair.st-none::before{background:repeating-linear-gradient(180deg,var(--border) 0 4px,transparent 4px 9px)}
.phead{display:flex;align-items:center;gap:10px;margin-bottom:6px}
.phead .no{font-size:11px;color:var(--faint);font-variant-numeric:tabular-nums}
.hist{font:inherit;font-size:11.5px;border:1px solid var(--border);border-radius:99px;
padding:1px 9px;background:var(--surface);color:var(--muted);cursor:pointer}
.hist:hover{border-color:var(--accent);color:var(--ink)}
.pair .side.quiet,.pair .histlog{display:none}
.pair.open .side.quiet,.pair.open .histlog{display:block}
.histlog{margin:6px 0 0 16px;font-size:12px;color:var(--muted);border-left:2px dashed var(--border);
padding:4px 12px}
.histlog div{margin:2px 0;font-variant-numeric:tabular-nums;white-space:pre-wrap}
.ok.folded .body{display:none}
.ok{background:none;border:0;border-radius:0;padding:6px 0 0;display:block}
.ok .toggle{font:inherit;font-size:12.5px;border:1px solid var(--border);border-radius:7px;
background:var(--ground);color:var(--muted);cursor:pointer;padding:4px 12px}
.ok .toggle:hover{border-color:var(--accent);color:var(--ink)}
.ok .body{display:flex;gap:8px;align-items:center;flex-wrap:wrap;width:100%;margin-top:8px}
/* 대조 화면에서는 각주의 세로 막대를 없앤다 — 단계 막대 안에 또 막대가 생겨 중첩돼 보임 */
.side .fn{border-left:0;border-radius:8px;background:var(--ground);margin:10px 0 10px 6px;
padding:10px 14px;grid-template-columns:22px minmax(0,1fr)}
.side .fnno{width:20px;height:20px;font-size:11px}
.side .pagemark{background:var(--ground)}
.mk{margin:4px 0 0 16px;font-size:11.5px;color:var(--faint)}
.mk span{border:1px solid var(--border);border-radius:5px;padding:1px 7px}
.sx{border-radius:3px;transition:background .08s ease}
.sx.hl{background:rgba(96,165,205,.22);box-shadow:0 0 0 2px rgba(96,165,205,.22)}
.sx.hl.pin{background:rgba(96,165,205,.34);box-shadow:0 0 0 2px rgba(96,165,205,.45)}
.pair .sx{cursor:pointer}
.pair.pinned .phead .no::after{content:" · 문장 고정 (다시 클릭하면 해제)";color:var(--accent)}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--muted);margin-bottom:22px}
.legend span{display:inline-flex;align-items:center;gap:6px}
.legend i{width:12px;height:12px;border-radius:3px;display:inline-block}
"""

def split_blocks(md):
    md = re.sub(r"^---\n.*?\n---\n", "", md, flags=re.S)
    return [b.strip() for b in md.split("\n\n") if b.strip()]

INS_O, INS_C, DEL_O, DEL_C = "\x01i\x02", "\x01/i\x02", "\x01d\x02", "\x01/d\x02"
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")

def mark_sentences(text):
    """문장마다 번호를 심어 단계 간 같은 문장을 짚을 수 있게 한다."""
    parts = SENT_SPLIT.split(text)
    if len(parts) < 2:
        return text
    return " ".join("\x03%d\x02%s\x03e\x02" % (i, p) for i, p in enumerate(parts) if p)

def diff_marked(prev, cur):
    """이전 단계 대비 바뀐 부분에 표시를 심는다(마크다운 변환 뒤 태그로 치환)."""
    import difflib
    a, b = prev.split(), cur.split()
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    out = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            out.append(" ".join(b[j1:j2]))
        elif op == "insert":
            out.append(INS_O + " ".join(b[j1:j2]) + INS_C)
        elif op == "delete":
            out.append(DEL_O + " ".join(a[i1:i2]) + DEL_C)
        else:
            out.append(DEL_O + " ".join(a[i1:i2]) + DEL_C + " " + INS_O + " ".join(b[j1:j2]) + INS_C)
    return " ".join(x for x in out if x)

def to_html(md_text, sentences=False):
    h = md_to_html(mark_sentences(md_text) if sentences else md_text)
    h = (h.replace(INS_O, "<ins>").replace(INS_C, "</ins>")
          .replace(DEL_O, "<del>").replace(DEL_C, "</del>"))
    h = re.sub(r"\x03(\d+)\x02", r'<span class="sx" data-si="\1">', h)
    return h.replace("\x03e\x02", "</span>")

def load_json(path, default):
    f = ROOT / path
    if not f.exists():
        return default
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return default

def render_compare(cid):
    src_f = ROOT / "source" / (cid + ".md")
    if not src_f.exists():
        return _wrap_compare(cid, "<p>정규화된 원문이 없습니다.</p>")
    A = split_blocks(src_f.read_text(encoding="utf-8"))

    tracks = []          # [(단계키, 라벨, css클래스, 블록목록)]
    for st in TRACK_STAGES:
        f = ROOT / "stages" / cid / (st + ".md")
        if f.exists():
            cls = "draft" if st == "draft" else ("revise" if st in ("ai_revise",) else "review")
            tracks.append((st, STAGE_LABEL.get(st, st), cls, split_blocks(f.read_text(encoding="utf-8"))))
    if not tracks:
        return _wrap_compare(cid, "<p>아직 번역 단계 스냅샷이 없습니다.</p>")

    reviews = {}         # 단계 -> {블록번호: [의견]}
    for n, st in ((1, "ai_review_1"), (2, "ai_review_2")):
        d = load_json("reviews/%s-review%d.json" % (cid, n), None)
        if d:
            m = {}
            for c in d.get("comments", []):
                m.setdefault(c.get("block", -1), []).append(c)
            reviews[st] = m
    approvals = load_json("reviews/%s-approvals.json" % cid, {})

    body = ('<div class="bar">'
            '<span class="cnt">확정 <b id="done">0</b> · 확인 유보 <b id="held">0</b>'
            ' / 전체 <b id="total">0</b></span>'
            '<button id="onlyOpen">확인 유보만 보기</button>'
            '<span class="cnt" style="margin-left:auto">'
            '손대지 않은 문단은 <b>확인 유보</b>로 남습니다 — 의견이 있는 문단만 확정하고 다음 단계로 넘어가도 됩니다'
            '</span></div>')
    body += ('<div class="legend">'
             '<span><i style="background:var(--faint)"></i>원문</span>'
             '<span><i style="background:var(--accent)"></i>AI 번역</span>'
             '<span><i style="background:#7a9e3a"></i>AI 감수</span>'
             '<span><ins>추가</ins></span><span><del>삭제</del></span></div>')
    lens = {len(t[3]) for t in tracks} | {len(A)}
    if len(lens) > 1:
        body += ('<div class="warn">단계별 문단 수가 다릅니다 — 원문 %d개, %s. '
                 '문단 1:1 대응이 깨졌을 수 있습니다.</div>'
                 % (len(A), ", ".join("%s %d개" % (t[1], len(t[3])) for t in tracks)))

    n_blocks = max([len(A)] + [len(t[3]) for t in tracks])

    # 페이지 마커만 있는 블록은 독립 문단으로 세우지 않고 앞 문단에 붙인다
    marker_only = re.compile(r"^\[원서 p\.[^\]]+\]$")
    groups = []
    for i in range(n_blocks):
        src_b = A[i] if i < len(A) else ""
        if groups and marker_only.match(src_b.strip()):
            groups[-1]["markers"].append(src_b.strip())
        else:
            groups.append({"idx": i, "markers": [], "no": len(groups) + 1})

    for g in groups:
        i = g["idx"]
        rec = approvals.get(str(i)) or {}
        cur = rec.get("current") or (rec if rec.get("status") else None)
        hist = rec.get("history", [])
        st_cls = " st-" + {"approved": "approved", "rejected": "rejected",
                           "note": "note"}.get((cur or {}).get("status", ""), "none")
        changed_stages = 0

        rows = []
        prev = None
        for st, label, cls, blocks_ in tracks:
            cur_txt = blocks_[i] if i < len(blocks_) else ""
            if not cur_txt:
                continue
            first = prev is None
            changed = (not first) and prev != cur_txt
            if changed:
                changed_stages += 1
            shown = cur_txt if first else diff_marked(prev, cur_txt)
            tag = label + ("" if first else (" · 전 단계에서 수정" if changed else " · 변경 없음"))
            quiet = "" if (first or changed) else " quiet"   # 변경 없는 단계는 이력에서만 표시
            note_html = ""
            for c in reviews.get(st, {}).get(i, []):
                note_html += ('<div class="note"><b>%s · %s</b> — %s<br>원문: %s / %s → %s</div>'
                              % (_html.escape(c.get("severity", "")), _html.escape(c.get("type", "")),
                                 _html.escape(c.get("comment", "")), _html.escape(c.get("source", "")),
                                 _html.escape(c.get("before", "")), _html.escape(c.get("after", ""))))
            rows.append('<div class="side %s%s"><span class="tag">%s</span>%s</div>%s'
                        % (cls, quiet, _html.escape(tag), to_html(shown, True), note_html))
            prev = cur_txt

        badge = ""
        if changed_stages or len(hist) > 1:
            badge = ('<button class="hist">이력 %d</button>'
                     % (changed_stages + max(0, len(hist) - 1)))
        folded = "" if (changed_stages or cur) else " folded"

        body += ('<div class="pair%s" data-block="%d" data-no="%d" data-confirmed="%d">'
                 % (st_cls, i, g["no"], 1 if cur else 0))
        body += ('<div class="phead"><span class="no">문단 %d</span>%s</div>' % (g["no"], badge))
        body += ('<div class="side src"><span class="tag">원문</span>%s</div>'
                 % (to_html(A[i], True) if i < len(A) else "<p>(없음)</p>"))
        body += "".join(rows)
        for mk in g["markers"]:
            body += ('<div class="mk"><span>%s 여기까지 ⇥</span></div>'
                     % _html.escape(mk.strip("[]")))
        if len(hist) > 1:
            log = "".join('<div>%s · %s%s</div>'
                          % (_html.escape(h.get("ts", "")[:16].replace("T", " ")),
                             {"approved": "승인", "rejected": "반려", "note": "메모",
                              "withdrawn": "철회"}.get(h.get("status", ""), h.get("status", "")),
                             ("  — " + _html.escape(h["note"])) if h.get("note") else "")
                          for h in hist)
            body += '<div class="histlog"><b>확인 이력</b>%s</div>' % log

        sel = (cur or {}).get("status", "")
        body += ('<div class="ok%s" data-block="%d" data-no="%d" data-confirmed="%d">'
                 '<button class="toggle">%s</button>'
                 '<div class="body">'
                 '<button class="yes%s"%s>승인</button>'
                 '<button class="no%s"%s>반려</button>'
                 '<textarea rows="2"%s placeholder="의견 메모 (선택) — 모서리를 끌어 크기를 바꿀 수 있습니다">\n%s</textarea>'
                 '<button class="commit">%s</button>'
                 '<span class="state">%s</span>'
                 '</div></div>'
                 % (folded, i, g["no"], 1 if cur else 0,
                    "사용자 확인" if not cur else ("사용자 확인 · " + STATUS_KO.get((cur or {}).get("status",""), "확정")),
                    " on" if sel == "approved" else "", " disabled" if cur else "",
                    " on" if sel == "rejected" else "", " disabled" if cur else "",
                    " disabled" if cur else "",
                    _html.escape((cur or {}).get("note", "")),
                    "철회" if cur else "확정",
                    _html.escape(("확정 · %s · %s" % (STATUS_KO.get(cur.get("status",""), ""),
                                                        cur["ts"][:16].replace("T", " ")))
                                 if cur else "확인 유보")))
        body += "</div>"
    return _wrap_compare(cid, body)

COMPARE_JS = """
function refreshCount(){
  var all=document.querySelectorAll('.pair').length;
  var done=document.querySelectorAll('.pair[data-confirmed="1"]').length;
  document.getElementById('total').textContent=all;
  document.getElementById('done').textContent=done;
  document.getElementById('held').textContent=all-done;
}
document.querySelectorAll('.hist').forEach(function(b){
  b.onclick=function(){ b.closest('.pair').classList.toggle('open'); };
});
document.querySelectorAll('.ok .toggle').forEach(function(b){
  b.onclick=function(){ b.closest('.ok').classList.toggle('folded'); };
});
document.querySelectorAll('.ok').forEach(function(row){
  var blk=row.dataset.block, inp=row.querySelector('textarea');
  var yes=row.querySelector('.yes'), no=row.querySelector('.no');
  var commit=row.querySelector('.commit'), state=row.querySelector('.state');
  var pair=document.querySelector('.pair[data-block="'+blk+'"]');
  function locked(on){
    [yes,no,inp].forEach(function(el){ el.disabled=on; });
    commit.textContent=on?'철회':'확정';
    row.querySelector('.toggle').textContent=on?'사용자 확인 · 확정됨':'사용자 확인';
  }
  // 선택은 화면에서만 (다시 누르면 해제) — 저장은 '확정'을 눌러야 일어납니다
  yes.onclick=function(){ if(yes.disabled)return;
    var on=yes.classList.toggle('on'); if(on) no.classList.remove('on'); };
  no.onclick=function(){ if(no.disabled)return;
    var on=no.classList.toggle('on'); if(on) yes.classList.remove('on'); };
  commit.onclick=function(){
    var confirmed=row.dataset.confirmed==='1';
    var status;
    if(confirmed){ status='withdrawn'; }
    else if(yes.classList.contains('on')) status='approved';
    else if(no.classList.contains('on')) status='rejected';
    else if(inp.value.trim()) status='note';
    else { alert('승인 또는 반려를 고르거나 메모를 남긴 뒤 확정해 주세요.'); return; }
    fetch('/api/approve',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({chunk:CID,block:blk,label:row.dataset.no,status:status,note:inp.value})})
    .then(function(r){return r.json();}).then(function(j){
      if(!j.ok){ alert(j.message||'저장하지 못했습니다.'); return; }
      if(status==='withdrawn'){
        row.dataset.confirmed='0'; pair.dataset.confirmed='0';
        pair.className=pair.className.replace(/ st-\\w+/,'')+' st-none';
        state.textContent='확인 유보'; locked(false);
      }else{
        row.dataset.confirmed='1'; pair.dataset.confirmed='1';
        pair.className=pair.className.replace(/ st-\\w+/,'')+' st-'+
          (status==='approved'?'approved':status==='rejected'?'rejected':'note');
        state.textContent='확정 · '+({approved:'승인',rejected:'반려',note:'메모'}[status]||'')
          +' · '+new Date().toLocaleString('ko-KR');
        locked(true);
      }
      refreshCount();
    });
  };
});
// 같은 문장을 단계별로 함께 짚어준다 (문장 순서가 어긋난 문단에서는 짚이지 않을 수 있음)
// 마우스를 올리면 따라다니고, 클릭하면 그 문장에 고정된다. 다시 클릭하면 풀린다.
document.querySelectorAll('.pair').forEach(function(pair){
  var pinned=null;
  function paint(si){
    pair.querySelectorAll('.sx').forEach(function(x){
      var on = (si!==null && x.dataset.si===si);
      x.classList.toggle('hl', on);
      x.classList.toggle('pin', on && pinned!==null);
    });
  }
  function hit(e){
    var sp = e.target.closest ? e.target.closest('.sx') : null;
    return (sp && pair.contains(sp)) ? sp : null;
  }
  pair.addEventListener('mouseover', function(e){
    if(pinned!==null) return;
    var sp=hit(e); if(!sp) return;
    paint(sp.dataset.si);
  });
  pair.addEventListener('mouseleave', function(){
    if(pinned!==null) return;
    paint(null);
  });
  pair.addEventListener('click', function(e){
    var sp=hit(e); if(!sp) return;
    var si=sp.dataset.si;
    if(pinned===si){ pinned=null; paint(si); }   // 같은 문장 재클릭 → 고정 해제, hover 모드 복귀
    else { pinned=si; paint(si); }
    pair.classList.toggle('pinned', pinned!==null);
  });
});
var onlyBtn=document.getElementById('onlyOpen');
onlyBtn.onclick=function(){
  var on=onlyBtn.classList.toggle('on');
  document.querySelectorAll('.pair').forEach(function(p){
    p.style.display=(on && p.dataset.confirmed==='1')?'none':'';
  });
};
refreshCount();
"""

def _wrap_compare(cid, body):
    return ("<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>%s · 단계별 대조</title><style>%s%s</style></head><body><div class='page'>"
            "<div class='crumb'>%s · 원문과 단계별 번역 대조</div>%s</div>"
            "<script>var CID=%s;%s</script></body></html>"
            % (cid, VIEW_CSS, COMPARE_CSS, _html.escape(cid), body,
               json.dumps(cid), COMPARE_JS))

def render_view(kind, cid):
    folder = "source" if kind == "source" else "chapters"
    label = "원문(정규화)" if kind == "source" else "번역본"
    f = ROOT / folder / (cid + ".md")
    if not f.exists():
        body = "<p>아직 만들어지지 않은 파일입니다: <code>%s/%s.md</code></p>" % (folder, cid)
    else:
        body = md_to_html(f.read_text(encoding="utf-8"))
    return ("<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>%s · %s</title><style>%s</style></head><body><div class='page'>"
            "<div class='crumb'>%s · %s</div>%s</div></body></html>"
            % (cid, label, VIEW_CSS, _html.escape(cid), _html.escape(label), body))

def set_approval(cid, block, status, note, label=None):
    """문단 확인 상태를 기록한다. 현재 상태와 이력을 함께 남긴다.

    status: approved(승인) / rejected(반려) / note(메모만) / withdrawn(철회)
    """
    if status not in ("approved", "rejected", "note", "withdrawn"):
        return False, "알 수 없는 상태입니다."
    path = ROOT / "reviews" / ("%s-approvals.json" % cid)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    key = str(block)
    rec = data.get(key) or {"history": []}
    if "history" not in rec:                       # 이전 단일 상태 구조에서 이월
        rec = {"history": [rec] if rec.get("status") else []}
    entry = {"status": status, "note": note or "",
             "ts": datetime.now().isoformat(timespec="seconds")}
    rec["history"].append(entry)
    rec["current"] = None if status == "withdrawn" else entry
    data[key] = rec
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    kind = {"approved": "approve", "rejected": "reject",
            "note": "note", "withdrawn": "withdraw"}[status]
    log_decision(kind, "%s 문단 %s" % (cid, label or block), status, note or "")
    return True, "저장했습니다."


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/api/state":
            self._send(200, json.dumps(build_state(), ensure_ascii=False))
        elif u.path == "/compare":
            q = parse_qs(u.query)
            cid = re.sub(r"[^A-Za-z0-9_-]", "", (q.get("id", [""])[0]))
            self._send(200, render_compare(cid), "text/html; charset=utf-8")
        elif u.path == "/view":
            q = parse_qs(u.query)
            cid = re.sub(r"[^A-Za-z0-9_-]", "", (q.get("id", [""])[0]))
            kind = "source" if q.get("kind", ["source"])[0] == "source" else "chapters"
            self._send(200, render_view(kind, cid), "text/html; charset=utf-8")
        elif u.path.startswith("/assets/"):
            # 도판 이미지 — 프로젝트 폴더 밖으로는 절대 못 나가게 경로를 검사한다
            rel = u.path.lstrip("/")
            f = (ROOT / rel).resolve()
            base = (ROOT / "assets").resolve()
            if not str(f).startswith(str(base)) or not f.is_file():
                return self._send(404, json.dumps({"error": "not found"}))
            ext = f.suffix.lower()
            ctype = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                     ".gif": "image/gif", ".svg": "image/svg+xml",
                     ".webp": "image/webp"}.get(ext, "application/octet-stream")
            self._send(200, f.read_bytes(), ctype)
        elif u.path in ("/", "/index.html"):
            self._send(200, read("scripts/dashboard.html", "<h1>scripts/dashboard.html 파일이 없습니다.</h1>"),
                       "text/html; charset=utf-8")
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        if not any(self.path.startswith(x) for x in
                   ("/api/decide", "/api/add", "/api/delete", "/api/rename", "/api/approve",
                    "/api/restart", "/api/quit")):
            return self._send(404, json.dumps({"error": "not found"}))
        n = int(self.headers.get("Content-Length", "0"))
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
            actor = "ai" if req.get("actor") == "ai" else "user"
            if self.path.startswith("/api/restart"):
                RESTART["want"] = True
                ok, msg = True, "서버를 다시 띄웁니다."
            elif self.path.startswith("/api/quit"):
                # 새 실행기가 이 서버를 넘겨받으려고 부른다
                RESTART["quit"] = True
                ok, msg = True, "서버를 종료합니다."
            elif self.path.startswith("/api/approve"):
                ok, msg = set_approval(req.get("chunk", ""), req.get("block", ""),
                                       req.get("status", ""), req.get("note", ""),
                                       req.get("label", ""))
            elif self.path.startswith("/api/add"):
                ok, msg = add_term(req.get("term", "").strip(), req.get("choice", "").strip(),
                                   req.get("note", ""), actor)
            elif self.path.startswith("/api/delete"):
                ok, msg = delete_term(req.get("term", "").strip(), actor)
            elif self.path.startswith("/api/rename"):
                ok, msg = rename_term(req.get("term", "").strip(), req.get("choice", "").strip(), actor)
            else:
                ok, msg = apply_decision(req.get("term", ""), req.get("choice", ""),
                                         req.get("note", ""), req.get("full", ""), actor)
            self._send(200 if ok else 400, json.dumps({"ok": ok, "message": msg}, ensure_ascii=False))
        except Exception as e:
            self._send(500, json.dumps({"ok": False, "message": str(e)}, ensure_ascii=False))

    def log_message(self, *a):
        pass

if __name__ == "__main__":
    srv = HTTPServer(("127.0.0.1", PORT), Handler)
    print("대시보드: http://127.0.0.1:%d  (중지: Ctrl+C)" % PORT)
    print("프로젝트 폴더: %s" % ROOT)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n중지했습니다.")
