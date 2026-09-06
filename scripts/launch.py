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
PORTS = [8765, 8766, 8767, 8768]
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

    # 1) 이미 떠 있는 대시보드가 있으면 그쪽을 연다
    for p in PORTS:
        if alive(p):
            url = "http://127.0.0.1:%d/" % p
            say("대시보드가 이미 실행 중입니다 (포트 %d). 브라우저를 엽니다." % p)
            say("→ %s" % url); webbrowser.open(url)
            say(""); say("이 창은 닫으셔도 됩니다."); hold(0)

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
    say("")

    threading.Thread(target=open_when_ready, args=(url, port), daemon=True).start()

    os.environ["PORT"] = str(port)
    sys.path.insert(0, str(ROOT / "scripts"))
    os.chdir(str(ROOT))
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
