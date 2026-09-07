#!/usr/bin/env python3
"""structure-map.yaml에 정의된 청크의 원문(source/*.md)을 일괄 생성한다.

    python3 scripts/normalize_all.py            # 아직 없는 청크만
    python3 scripts/normalize_all.py --force    # 전부 다시 생성
    python3 scripts/normalize_all.py ch02 ch03  # 지정한 청크만
"""
import subprocess, sys, io, yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAP = yaml.safe_load(io.open(ROOT / "structure-map.yaml", encoding="utf-8"))
PDF = ROOT / MAP["source"]

def chunks():
    out = []
    for key in ("front_matter", "chapters", "back_matter"):
        for c in MAP.get(key) or []:
            out.append(c)
    return out

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    (ROOT / "source").mkdir(exist_ok=True)
    todo = [c for c in chunks() if (not args or c["id"] in args)]
    for c in todo:
        dest = ROOT / "source" / (c["id"] + ".md")
        if dest.exists() and not force and not args:
            print("건너뜀 (이미 있음): %s" % c["id"]); continue
        a, b = c["file"]
        # structure-map.yaml 의 parser 값(record / term_definition / rebuild)을 그대로 넘긴다.
        # 이 값이 없으면 산문 규칙으로 처리한다.
        pmode = c.get("parser") or "prose"
        print("\n### %s  파일 %d-%d  (원서 %s-%s)  [%s]  %s"
              % (c["id"], a, b, c["printed"][0], c["printed"][1], pmode, c.get("title", "")))
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "normalize.py"),
                            str(PDF), str(a), str(b), c["id"], str(dest),
                            "--parser=%s" % pmode],
                           capture_output=True, text=True)
        if r.returncode:
            print("  !! 실패\n" + (r.stderr or "")[-800:]); continue
        for line in r.stdout.splitlines():
            # '!!' 는 경고다. 걸러 내면 오버라이드가 안 먹은 것 같은 일을 아무도 모른다.
            if "!!" in line or "여백 실측" in line or ">>>" in line or "paras:" in line or "fn_defs:" in line:
                print("  " + line.strip())
        print("  → %s (%d바이트)" % (dest.relative_to(ROOT), dest.stat().st_size))

main()
