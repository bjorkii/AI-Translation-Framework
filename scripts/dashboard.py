#!/usr/bin/env python3
"""번역 프로젝트 로컬 대시보드.

    python3 scripts/dashboard.py        ->  http://127.0.0.1:8765

표준 라이브러리만 사용한다(별도 설치 불필요). 파일을 요청마다 새로 읽으므로
AI가 파일을 고치든 사용자가 화면에서 고치든 양쪽이 곧바로 반영된다.
"""
import json, re, subprocess, sys, os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = int(os.environ.get("PORT", "8765"))

# ---------------------------------------------------------------- 파일 읽기

def read(p, default=""):
    f = ROOT / p
    return f.read_text(encoding="utf-8") if f.exists() else default

def parse_structure():
    """structure-map.yaml에서 청크 목록을 읽는다."""
    out, section = [], None
    for line in read("structure-map.yaml").splitlines():
        if re.match(r"^(chapters|back_matter|front_matter):", line):
            section = line.split(":")[0]
            continue
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
    """glossary.yaml을 항목 단위로 파싱한다."""
    txt = read("glossary/glossary.yaml")
    entries = []
    for m in re.finditer(r'  - term: "(.*?)"\n(.*?)(?=\n  - term: |\Z)', txt, re.S):
        term, body = m.group(1), m.group(2)
        def f(k):
            mm = re.search(r'^\s{4}' + k + r':\s*(?:"(.*?)"|(null))\s*$', body, re.M)
            if not mm: return None
            return mm.group(1) if mm.group(1) is not None else None
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
        out = subprocess.run(["git", "log", "--oneline", "-%d" % n],
                             cwd=ROOT, capture_output=True, text=True, timeout=5)
        return [l for l in out.stdout.splitlines() if l.strip()]
    except Exception:
        return []

def build_state():
    info = json.loads(read("project-info.json", "{}") or "{}")
    ctx = json.loads(read("glossary/term-context.json", "{}") or "{}")
    chunks = []
    for c in parse_structure():
        stage, has_src, has_tgt = chunk_stage(c["id"])
        c.update(stage=stage, has_source=has_src, has_target=has_tgt)
        chunks.append(c)
    gl = parse_glossary()
    pending = []
    for e in gl:
        if e["tbd"]:
            info_ctx = ctx.get(e["term"], {})
            pending.append({
                "term": e["term"],
                "options": info_ctx.get("options") or [o.strip() for o in e["tbd"].split("|")],
                "quotes": info_ctx.get("quotes", []),
                "context": e["context"], "definition_en": e["definition_en"],
                "current": e["translation"],
            })
    decided = [e for e in gl if e["translation"] and not e["tbd"]]
    return {
        "info": info, "chunks": chunks, "status_md": read("status.md"),
        "commits": git_log(),
        "glossary": {
            "total": len(gl), "decided": len(decided), "pending": len(pending),
            "untouched": len([e for e in gl if not e["translation"] and not e["tbd"]]),
            "pending_items": pending,
            "decided_items": [{"term": e["term"], "translation": e["translation"],
                               "notation": e["notation"]} for e in decided],
        },
    }

# ---------------------------------------------------------------- 파일 쓰기

def apply_decision(term, choice, note):
    """glossary.yaml의 해당 항목에 번역어를 확정하고 tbd를 제거한다."""
    path = ROOT / "glossary" / "glossary.yaml"
    txt = path.read_text(encoding="utf-8")
    pat = re.compile(r'(  - term: "' + re.escape(term) + r'"\n)(.*?)(?=\n  - term: |\Z)', re.S)
    m = pat.search(txt)
    if not m:
        return False, "용어집에서 항목을 찾지 못했다: " + term
    head, body = m.group(1), m.group(2)
    body = re.sub(r'^\s{4}translation:.*$', '    translation: "%s"' % choice, body, count=1, flags=re.M)
    body = re.sub(r'^\s{4}tbd:.*\n', '', body, flags=re.M)          # 결정됐으므로 제거
    body = re.sub(r'^\s{4}notation:.*\n', '', body, flags=re.M)
    if note:
        body = body.rstrip("\n") + '\n    notation: "%s"\n' % note.replace('"', "'")
    txt = txt[:m.start()] + head + body + txt[m.end():]
    path.write_text(txt, encoding="utf-8")
    return True, "확정: %s → %s" % (term, choice)

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
        if self.path.startswith("/api/state"):
            self._send(200, json.dumps(build_state(), ensure_ascii=False))
        elif self.path in ("/", "/index.html"):
            self._send(200, read("scripts/dashboard.html", "<h1>scripts/dashboard.html 파일이 없습니다.</h1>"), "text/html; charset=utf-8")
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        if not self.path.startswith("/api/decide"):
            return self._send(404, json.dumps({"error": "not found"}))
        n = int(self.headers.get("Content-Length", "0"))
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
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
        print("\n중지했다.")
