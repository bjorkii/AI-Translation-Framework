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
            self._send(200, PAGE, "text/html; charset=utf-8")
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

PAGE = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>번역 프로젝트 대시보드</title>
<style>
:root{--ground:#EDEFEE;--surface:#fff;--surface2:#F5F7F6;--ink:#12171A;--muted:#5A6668;
--faint:#8A9698;--accent:#0F6E73;--accent-ink:#fff;--accent-soft:#DDEDED;--warn:#A85F22;
--warn-soft:#F6E8DA;--border:#D2D9D8;--border2:#B6C2C1}
@media(prefers-color-scheme:dark){:root{--ground:#0E1414;--surface:#161F1E;--surface2:#1D2726;
--ink:#E6EDEC;--muted:#93A2A2;--faint:#71807F;--accent:#57C3C7;--accent-ink:#0B1414;
--accent-soft:#17322F;--warn:#DB9752;--warn-soft:#2A2118;--border:#26302F;--border2:#3A4746}}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);font:15px/1.6 -apple-system,BlinkMacSystemFont,
"Apple SD Gothic Neo","Noto Sans KR",system-ui,sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:28px 22px 64px}
header{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-bottom:6px}
h1{font-size:22px;margin:0;letter-spacing:-.01em}
.sub{color:var(--muted);font-size:13.5px}
.live{margin-left:auto;font-size:11.5px;color:var(--faint);font-variant-numeric:tabular-nums}
nav{display:flex;gap:6px;margin:20px 0 22px;border-bottom:1px solid var(--border)}
nav button{font:inherit;font-size:14px;background:none;border:0;border-bottom:2px solid transparent;
padding:9px 14px;color:var(--muted);cursor:pointer}
nav button[aria-selected=true]{color:var(--ink);border-bottom-color:var(--accent);font-weight:600}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin-bottom:22px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:9px;padding:12px 14px}
.card .k{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--faint)}
.card .v{font-size:19px;font-weight:600;font-variant-numeric:tabular-nums;margin-top:2px}
.card .v small{font-size:13px;font-weight:400;color:var(--muted)}
table{width:100%;border-collapse:collapse;background:var(--surface);border:1px solid var(--border);
border-radius:9px;overflow:hidden}
th,td{text-align:left;padding:9px 13px;border-bottom:1px solid var(--border);font-size:14px}
th{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--faint);font-weight:600}
tr:last-child td{border-bottom:0}
td.num{font-variant-numeric:tabular-nums;color:var(--muted);white-space:nowrap}
.badge{display:inline-block;padding:2px 9px;border-radius:99px;font-size:11.5px;
background:var(--surface2);color:var(--muted);border:1px solid var(--border)}
.badge.on{background:var(--accent-soft);color:var(--accent);border-color:transparent}
.badge.wait{background:var(--warn-soft);color:var(--warn);border-color:transparent}
.term{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:18px 20px;
margin-bottom:14px}
.term h3{margin:0 0 3px;font-size:18px}
.term .why{color:var(--muted);font-size:13.5px;margin:0 0 12px}
.q{display:grid;grid-template-columns:64px 1fr;gap:11px;padding-left:11px;
border-left:2px solid var(--border2);margin-bottom:8px;align-items:baseline}
.q .p{font-size:11.5px;color:var(--faint);font-variant-numeric:tabular-nums}
.q .t{font-family:Georgia,"Times New Roman",serif;font-size:15px;line-height:1.5}
.opts{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
.opts button{font:inherit;font-size:14px;background:var(--surface2);color:var(--ink);
border:1px solid var(--border2);border-radius:8px;padding:8px 14px;cursor:pointer}
.opts button:hover{border-color:var(--accent)}
.opts button.sel{background:var(--accent);border-color:var(--accent);color:var(--accent-ink)}
.row{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}
input{font:inherit;font-size:14px;background:var(--surface2);color:var(--ink);
border:1px solid var(--border);border-radius:7px;padding:8px 11px;flex:1 1 220px}
pre{background:var(--surface);border:1px solid var(--border);border-radius:9px;padding:14px;
overflow-x:auto;font-size:13px;line-height:1.55}
.two{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:1px 20px}
.pair{display:flex;justify-content:space-between;gap:10px;padding:5px 0;
border-bottom:1px solid var(--border);font-size:13.5px}
.pair .en{color:var(--muted)}
h2{font-size:15px;margin:26px 0 10px}
.hidden{display:none}
</style></head><body><div class="wrap">
<header>
  <h1>번역 프로젝트 대시보드</h1>
  <span class="sub" id="book"></span>
  <span class="live" id="live">연결 중…</span>
</header>
<nav>
  <button data-tab="overview" aria-selected="true">개요</button>
  <button data-tab="chunks" aria-selected="false">청크</button>
  <button data-tab="glossary" aria-selected="false">용어집</button>
</nav>
<section id="overview"></section>
<section id="chunks" class="hidden"></section>
<section id="glossary" class="hidden"></section>
</div>
<script>
let S=null, tab="overview";
const el=id=>document.getElementById(id);
document.querySelectorAll("nav button").forEach(b=>b.onclick=()=>{
  tab=b.dataset.tab;
  document.querySelectorAll("nav button").forEach(x=>x.setAttribute("aria-selected",x===b));
  ["overview","chunks","glossary"].forEach(t=>el(t).classList.toggle("hidden",t!==tab));
});
const esc=s=>(s==null?"":String(s)).replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));

function renderOverview(){
  const i=S.info||{}, m=i.measured||{}, g=S.glossary;
  const done=S.chunks.filter(c=>c.has_source).length;
  let h='<div class="cards">';
  h+=card("원서 분량", (i.total_file_pages||"-")+"<small> 쪽</small>");
  h+=card("인쇄 쪽번호", "<small>"+esc(i.printed_range||"-")+"</small>");
  h+=card("텍스트 레이어", "<small>"+esc(i.text_layer||"-")+"</small>");
  h+=card("정규화된 청크", done+'<small> / '+S.chunks.length+"</small>");
  h+=card("용어집", g.decided+'<small> / '+g.total+" 확정</small>");
  h+=card("결정 대기", g.pending+"<small> 건</small>");
  h+="</div><h2>측정값</h2><div class=\"cards\">";
  for(const k in m) h+=card(k, "<small>"+esc(m[k])+"</small>");
  h+="</div>";
  if(S.commits.length){
    h+="<h2>최근 작업 기록</h2><pre>"+esc(S.commits.join("\n"))+"</pre>";
  }
  el("overview").innerHTML=h;
}
const card=(k,v)=>'<div class="card"><div class="k">'+esc(k)+'</div><div class="v">'+v+"</div></div>";

function renderChunks(){
  let h="<table><tr><th>청크</th><th>제목</th><th>원서 쪽</th><th>분량</th><th>단계</th><th>비고</th></tr>";
  for(const c of S.chunks){
    const st=c.stage, on=st!=="pending";
    h+="<tr><td>"+esc(c.id)+"</td><td>"+esc(c.title)+"</td>"
      +'<td class="num">'+esc((c.printed||[]).join("–"))+"</td>"
      +'<td class="num">'+esc(c.pages||"")+"</td>"
      +'<td><span class="badge '+(on?"on":"wait")+'">'+esc(st)+"</span></td>"
      +"<td>"+(c.split?'<span class="badge">절 단위 분할</span> ':"")
      +(c.parser?'<span class="badge">'+esc(c.parser)+"</span>":"")+"</td></tr>";
  }
  h+="</table><h2>status.md</h2><pre>"+esc(S.status_md||"(비어 있음)")+"</pre>";
  el("chunks").innerHTML=h;
}

function renderGlossary(){
  const g=S.glossary;
  let h='<div class="cards">'+card("전체 항목",g.total)+card("확정",g.decided)
       +card("결정 대기",g.pending)+card("미착수",g.untouched)+"</div>";
  h+="<h2>결정이 필요한 용어 ("+g.pending+")</h2>";
  if(!g.pending) h+="<p class=\"sub\">모두 확정됐다.</p>";
  for(const t of g.pending_items){
    h+='<div class="term"><h3>'+esc(t.term)+"</h3>";
    if(t.context) h+='<p class="why">'+esc(t.context)+"</p>";
    for(const q of (t.quotes||[]))
      h+='<div class="q"><span class="p">원서 p.'+esc(q.page)+'</span><span class="t">'+esc(q.text)+"</span></div>";
    h+='<div class="opts">';
    for(const o of t.options)
      h+='<button onclick="decide('+JSON.stringify(t.term).replace(/"/g,"&quot;")+','
        +JSON.stringify(o).replace(/"/g,"&quot;")+')"'+(t.current===o?' class="sel"':"")+">"+esc(o)+"</button>";
    h+='</div><div class="row">'
      +'<input placeholder="다른 표기 직접 입력 후 Enter" data-term="'+esc(t.term)+'" data-k="choice">'
      +'<input placeholder="표기 규칙 메모 (선택) — 예: 첫 등장 시 원문 병기" data-term="'+esc(t.term)+'" data-k="note">'
      +"</div></div>";
  }
  h+="<h2>확정된 용어 ("+g.decided+")</h2><div class=\"two\">";
  for(const d of g.decided_items)
    h+='<div class="pair"><span class="en">'+esc(d.term)+'</span><span>'+esc(d.translation)+"</span></div>";
  h+="</div>";
  el("glossary").innerHTML=h;
  el("glossary").querySelectorAll("input").forEach(inp=>{
    inp.onkeydown=e=>{
      if(e.key!=="Enter") return;
      const term=inp.dataset.term, v=inp.value.trim(); if(!v) return;
      if(inp.dataset.k==="choice") decide(term,v);
      else { const c=(S.glossary.pending_items.find(x=>x.term===term)||{}).current;
             if(c) decide(term,c,v); else alert("먼저 번역어를 고르세요."); }
    };
  });
}

async function decide(term,choice,note){
  await fetch("/api/decide",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({term:term,choice:choice,note:note||""})});
  await tick();
}
async function tick(){
  try{
    const r=await fetch("/api/state",{cache:"no-store"});
    S=await r.json();
    el("book").textContent=(S.info.title||"")+" · "+(S.info.publisher||"")+" · "+(S.info.direction||"");
    el("live").textContent="갱신 "+new Date().toLocaleTimeString("ko-KR");
    renderOverview(); renderChunks(); renderGlossary();
  }catch(e){ el("live").textContent="서버 연결 끊김"; }
}
tick(); setInterval(tick,2000);
</script></body></html>
"""

if __name__ == "__main__":
    srv = HTTPServer(("127.0.0.1", PORT), Handler)
    print("대시보드: http://127.0.0.1:%d  (중지: Ctrl+C)" % PORT)
    print("프로젝트 폴더: %s" % ROOT)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n중지했다.")
