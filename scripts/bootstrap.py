#!/usr/bin/env python3
"""프로젝트 전용 파이썬 환경(.venv)을 만든다. 맥·윈도우 공통.

왜 필요한가:
    한 대의 컴퓨터에 파이썬이 여러 개 깔려 있는 일이 흔하다. 실제로 이 프로젝트를
    만든 맥에는 파이썬이 넷 있었고, PyMuPDF 는 그중 하나에만, PyYAML 은 어디에도
    없었다. 어느 파이썬으로 실행하느냐에 따라 되기도 하고 안 되기도 하는데,
    실패 메시지는 늘 같은 ModuleNotFoundError 라서 원인을 짚기 어렵다.

    그래서 '어느 파이썬을 쓸지'를 매번 고르지 않는다. 프로젝트 폴더 안에 .venv 를
    하나 만들고 모든 스크립트가 그것만 쓴다. 팀원은 실행 파일을 누르기만 하면 된다.

    표준 라이브러리만 쓴다. 이 스크립트 자체가 설치를 필요로 하면 안 되기 때문이다.

    python3 scripts/bootstrap.py            # 없으면 만들고, 있으면 패키지만 확인
    python3 scripts/bootstrap.py --force    # .venv 를 지우고 다시 만든다
"""
import os
import shutil
import subprocess
import sys
import venv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENV = os.path.join(ROOT, ".venv")
REQ = os.path.join(ROOT, "requirements.txt")
NEEDED = ("pymupdf", "yaml")            # import 이름 (설치 이름과 다르다)


def venv_python(root=VENV):
    """이 환경의 파이썬 실행 파일 경로. 윈도우는 Scripts\\python.exe 다."""
    if os.name == "nt":
        return os.path.join(root, "Scripts", "python.exe")
    return os.path.join(root, "bin", "python")


def has_packages(py):
    if not os.path.exists(py):
        return False
    code = "import " + ", ".join(NEEDED)
    r = subprocess.run([py, "-c", code], capture_output=True, text=True)
    return r.returncode == 0


def main():
    force = "--force" in sys.argv
    quiet = "--quiet" in sys.argv
    py = venv_python()

    if force and os.path.isdir(VENV):
        print("기존 환경을 지웁니다: .venv")
        shutil.rmtree(VENV)

    if has_packages(py):
        if not quiet:
            print("파이썬 환경이 이미 준비되어 있습니다: .venv")
        return 0

    if not os.path.exists(py):
        print("파이썬 환경을 만드는 중입니다… (처음 한 번만, 1분쯤 걸립니다)")
        try:
            venv.EnvBuilder(with_pip=True, clear=False).create(VENV)
        except Exception as e:
            print("\n환경을 만들지 못했습니다: %s" % e)
            if os.name != "nt":
                print("맥이라면 터미널에서 다음을 한 번 실행해 보세요:")
                print("    xcode-select --install")
            return 1

    print("필요한 패키지를 설치하는 중입니다…")
    cmds = [[py, "-m", "pip", "install", "--upgrade", "pip", "--quiet"],
            [py, "-m", "pip", "install", "-r", REQ, "--quiet"]]
    for c in cmds:
        r = subprocess.run(c, capture_output=True, text=True)
        if r.returncode and c is cmds[-1]:
            print("\n패키지를 설치하지 못했습니다.\n" + (r.stderr or "")[-1200:])
            print("\n회사 네트워크가 막고 있는 경우일 수 있습니다.")
            print("그럴 때는 사내 IT에 PyPI(pypi.org) 접근을 요청해 주세요.")
            return 1

    if not has_packages(py):
        print("\n설치는 끝났는데 불러오기에 실패했습니다. 다음을 실행해 주세요:")
        print("    python3 scripts/bootstrap.py --force")
        return 1

    print("준비를 마쳤습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
