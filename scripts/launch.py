#!/usr/bin/env python3
"""대시보드 실행기 — '대시보드 실행.command'(맥) / '대시보드 실행.bat'(윈도우)이 이 파일을 부릅니다.

하는 일:
  1) 이미 대시보드가 떠 있으면 브라우저만 다시 연다
  2) 아니면 비어 있는 포트를 찾아 서버를 띄우고, 응답을 확인한 뒤 브라우저를 연다
  3) 문제가 생기면 사람이 읽을 수 있는 말로 알려준다
"""
import os, socket, sys, threading, time, urllib.request, webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 기본 포트 목록. PORTS=8899 처럼 환경변수로 바꿀 수 있다(두 번째 인스턴스·시험용).
PORTS = [int(x) for x in os.environ.get("PORTS", "8765,8766,8767,8768").split(",")]
TITLE = "번역 프로젝트 대시보드"

def say(*a): print(*a, flush=True)

def hold(code=0):
    """창이 바로 닫히지 않도록 붙잡는다 (더블클릭 실행 대비)."""
    say("")
    try:
        input("Enter 키를 누르면 창이 닫힙니다. ")
    except Exception:
        pass
    sys.exit(code)

def alive(port, timeout=0.8):
    """그 포트에 우리 대시보드가 떠 있는가?"""
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/api/state" % port, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False

def busy(port):
    s = socket.socket(); s.settimeout(0.4)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()

def watch_and_reload(paths, interval=1.0):
    """서버 코드가 바뀌면 스스로 다시 뜬다.

    dashboard.py 는 프로세스가 시작할 때 한 번 읽혀 메모리에 올라간다. 그 뒤로는
    브라우저를 새로고침해도 파일을 다시 읽지 않으므로, 코드를 고쳐도 반영되지 않는다
    (md 파일은 요청마다 읽으므로 곧바로 반영된다 — 이 차이가 헷갈리기 쉽다).

    파이썬이 알아서 다시 읽어 주지는 않는다. Flask·Django 의 개발 서버는 감시기를
    따로 붙여 그렇게 하는데, 여기 쓰는 표준 http.server 에는 그런 것이 없다.
    그래서 직접 붙인다.
    """
    stamps = {p: p.stat().st_mtime for p in paths if p.exists()}
    while True:
        time.sleep(interval)
        try:
            import dashboard
            if dashboard.RESTART.get("quit"):
                say(""); say("새 실행기가 넘겨받습니다. 이 서버를 종료합니다.")
                os._exit(0)
            if dashboard.RESTART.get("want"):
                say(""); say("화면에서 재실행을 요청했습니다. 대시보드를 다시 띄웁니다.")
                os.environ["DASH_RELOADED"] = "1"
                os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception:
            pass
        for p, was in list(stamps.items()):
            try:
                now = p.stat().st_mtime
            except OSError:
                continue
            if now != was:
                say(""); say("%s 가 바뀌었습니다. 대시보드를 다시 불러옵니다." % p.name)
                os.environ["DASH_RELOADED"] = "1"     # 브라우저를 또 열지 않도록
                os.execv(sys.executable, [sys.executable] + sys.argv)

def open_when_ready(url, port):
    for _ in range(60):                     # 최대 30초
        if alive(port, timeout=0.5):
            webbrowser.open(url); return
        time.sleep(0.5)
    say("브라우저를 자동으로 열지 못했습니다. 주소창에 %s 를 입력해 주세요." % url)

def main():
    say("=" * 46); say("  " + TITLE); say("=" * 46); say("")

    if not (ROOT / "scripts" / "dashboard.py").exists():
        say("대시보드 파일(scripts/dashboard.py)을 찾지 못했습니다.")
        say("실행 파일이 번역 프로젝트 폴더 안에 있는지 확인해 주세요.")
        say("현재 폴더: %s" % ROOT); hold(1)

    # 1) 이미 떠 있는 대시보드가 있으면 넘겨받는다.
    #    예전에는 브라우저만 열고 이 창을 붙잡아 두었는데, 다시 실행할 때마다
    #    창이 하나씩 쌓였다. 옛 서버를 내리고 이 창에서 새로 띄운다.
    for p in PORTS:
        if alive(p):
            say("이미 떠 있는 대시보드(포트 %d)를 종료하고 이 창에서 다시 띄웁니다." % p)
            try:
                urllib.request.urlopen(
                    urllib.request.Request("http://127.0.0.1:%d/api/quit" % p,
                                           data=b"{}", method="POST"), timeout=2).read()
            except Exception:
                pass
            for _ in range(30):                 # 포트가 풀릴 때까지 최대 6초
                if not busy(p): break
                time.sleep(0.2)
            break

    # 2) 비어 있는 포트를 고른다
    port = next((p for p in PORTS if not busy(p)), None)
    if port is None:
        say("쓸 수 있는 포트를 찾지 못했습니다 (%s 모두 사용 중)."
            % ", ".join(str(p) for p in PORTS))
        say("다른 프로그램을 닫고 다시 실행해 주세요."); hold(1)

    url = "http://127.0.0.1:%d/" % port
    say("대시보드를 시작합니다.  →  %s" % url)
    say("")
    say("  · 잠시 뒤 브라우저가 자동으로 열립니다.")
    say("  · 이 검은 창을 닫으면 대시보드가 꺼집니다. 창은 그대로 두세요.")
    say("  · 끝낼 때는 이 창을 닫거나 Ctrl+C 를 누르세요.")
    say("  · 대시보드 코드가 바뀌면 알아서 다시 뜹니다. 브라우저만 새로고침하세요.")
    say("")

    if not os.environ.get("DASH_RELOADED"):
        threading.Thread(target=open_when_ready, args=(url, port), daemon=True).start()

    os.environ["PORT"] = str(port)
    sys.path.insert(0, str(ROOT / "scripts"))
    os.chdir(str(ROOT))
    # 서버 코드가 바뀌면 알아서 다시 뜬다 (아래 watch_and_reload 설명 참조)
    watched = sorted((ROOT / "scripts").glob("*.py"))
    threading.Thread(target=watch_and_reload, args=(watched,), daemon=True).start()
    try:
        import dashboard
        from http.server import HTTPServer
        srv = HTTPServer(("127.0.0.1", port), dashboard.Handler)
        srv.serve_forever()
    except KeyboardInterrupt:
        say(""); say("대시보드를 종료했습니다.")
    except Exception as e:
        say(""); say("대시보드를 시작하지 못했습니다: %s" % e)
        say("이 메시지를 그대로 전달해 주시면 원인을 확인하겠습니다."); hold(1)

main()
