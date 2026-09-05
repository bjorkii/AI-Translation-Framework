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
STAGE_LABEL = {"pending": "대기", "normalized": "정규화", "draft": "1차 번역",
               "ai_review_1": "AI 감수 1", "ai_review_2": "AI 감수 2",
               "human_review": "사람 감수", "ai_revise": "AI 보완", "final": "확정"}

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
        if not m or section not in ("chapters", "back_matter"):
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
            "notation": f("notation"), "context": f("context"),
            "definition_en": f("definition_en"), "source": f("source"),
        })
    return entries

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
        c.update(stage=stage, stage_label=STAGE_LABEL.get(stage, stage),
                 stage_index=idx, has_source=has_src, has_target=has_tgt)
        chunks.append(c)
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
                "notation": e["notation"], "context": e["context"],
                "definition_en": e["definition_en"],
                "quotes": c.get("quotes", []),
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

def log_decision(kind, term, choice, note):
    """사용자가 화면에서 내린 결정을 수신함에 기록합니다.
    AI는 작업을 시작할 때 이 파일에서 미확인 항목을 먼저 확인합니다."""
    rec = {"ts": datetime.now().isoformat(timespec="seconds"), "actor": "user",
           "type": kind, "term": term, "choice": choice, "note": note or "", "ack": False}
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

def apply_decision(term, choice, note):
    if len(choice) > 40:
        return False, "번역어가 너무 깁니다(%d자). 표기만 남기고 설명은 메모 칸에 넣어 주세요." % len(choice)
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
    if note:
        body = body.rstrip("\n") + '\n    notation: "%s"\n' % note.replace('"', "'")
    path.write_text(txt[:m.start()] + head + body + txt[m.end():], encoding="utf-8")
    log_decision("decide", term, choice, note)
    return True, "확정: %s → %s" % (term, choice)

def add_term(term, translation, note):
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
    log_decision("add", term, translation, note)
    return True, "추가: %s → %s" % (term, translation)

# ------------------------------------------------------- 마크다운 렌더링

def md_inline(s):
    s = _html.escape(s, quote=False)
    s = re.sub(r"&lt;(/?(?:a|b|i|em|strong|br|span|sup|sub)\b[^&]*?)&gt;", r"<\1>", s)  # 앵커 등 통과
    s = re.sub(r"!\[(.*?)\]\((.*?)\)", r'<figure><img src="\2" alt="\1"><figcaption>\1</figcaption></figure>', s)
    s = re.sub(r"\[(.*?)\]\((.*?)\)", r'<a href="\2">\1</a>', s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\[원서 (p\.[^\]]+)\]", r'<span class="pagemark">원서 \1</span>', s)
    return s

def md_to_html(md):
    out, in_code, in_ul, in_ol = [], False, False, False
    def close():
        nonlocal in_ul, in_ol
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
    for raw in lines:
        line = raw.rstrip()
        if line.strip().startswith("```"):
            close(); out.append("</pre>" if in_code else "<pre class='code'>"); in_code = not in_code; continue
        if in_code:
            out.append(_html.escape(raw)); continue
        m = re.match(r"^\s*<!--\s*(.*?)\s*-->\s*$", line)
        if m:
            close(); out.append('<div class="marker">' + _html.escape(m.group(1)) + "</div>"); continue
        if not line.strip():
            close(); continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            close(); n = len(m.group(1))
            out.append("<h%d>%s</h%d>" % (n, md_inline(m.group(2)), n)); continue
        if re.match(r"^\s*(-{3,}|\*{3,})\s*$", line):
            close(); out.append("<hr>"); continue
        m = re.match(r"^\s*>\s?(.*)$", line)
        if m:
            close(); out.append("<blockquote>%s</blockquote>" % md_inline(m.group(1))); continue
        m = re.match(r"^\s*[-*+]\s+(.*)$", line)
        if m:
            if in_ol: out.append("</ol>"); in_ol = False
            if not in_ul: out.append("<ul>"); in_ul = True
            out.append("<li>%s</li>" % md_inline(m.group(1))); continue
        m = re.match(r"^\s*\d+[.)]\s+(.*)$", line)
        if m:
            if in_ul: out.append("</ul>"); in_ul = False
            if not in_ol: out.append("<ol>"); in_ol = True
            out.append("<li>%s</li>" % md_inline(m.group(1))); continue
        if line.lstrip().startswith("<"):
            close(); out.append(line); continue
        close(); out.append("<p>%s</p>" % md_inline(line))
    if in_code: out.append("</pre>")
    close()
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
.pagemark{font-size:12px;color:var(--faint);border:1px solid var(--border);border-radius:5px;
padding:1px 7px;white-space:nowrap}
a{color:var(--accent)}
figure{margin:20px 0;text-align:center}
figure img{max-width:100%;border:1px solid var(--border);border-radius:6px}
figcaption{font-size:13px;color:var(--muted);margin-top:6px}
blockquote{margin:0 0 15px;padding-left:14px;border-left:3px solid var(--border);color:var(--muted)}
pre.code{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:12px;
overflow-x:auto;font-size:13px}
hr{border:0;border-top:1px solid var(--border);margin:28px 0}
"""

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
        elif u.path == "/view":
            q = parse_qs(u.query)
            cid = re.sub(r"[^A-Za-z0-9_-]", "", (q.get("id", [""])[0]))
            kind = "source" if q.get("kind", ["source"])[0] == "source" else "chapters"
            self._send(200, render_view(kind, cid), "text/html; charset=utf-8")
        elif u.path in ("/", "/index.html"):
            self._send(200, read("scripts/dashboard.html", "<h1>scripts/dashboard.html 파일이 없습니다.</h1>"),
                       "text/html; charset=utf-8")
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        if not (self.path.startswith("/api/decide") or self.path.startswith("/api/add")):
            return self._send(404, json.dumps({"error": "not found"}))
        n = int(self.headers.get("Content-Length", "0"))
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
            if self.path.startswith("/api/add"):
                ok, msg = add_term(req.get("term", "").strip(), req.get("choice", "").strip(), req.get("note", ""))
            else:
                ok, msg = apply_decision(req.get("term", ""), req.get("choice", ""), req.get("note", ""))
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
