#!/usr/bin/env python3
"""단계 스냅샷 저장 (대조 화면의 단계별 비교 재료).

번역본은 파일 하나를 계속 덮어쓰므로, 단계가 바뀔 때마다 그 시점의 사본을
stages/<청크>/<단계>.md 로 남긴다. 대조 화면은 이 사본들을 이어 붙여
'전 단계 대비 무엇이 바뀌었는지'를 보여준다.

    python3 scripts/snapshot_stage.py ch01 draft
"""
import shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAGES = ["draft", "ai_review_1", "ai_review_2", "human_review", "ai_revise", "final"]

def main(cid, stage):
    if stage not in STAGES:
        print("알 수 없는 단계: %s (%s)" % (stage, ", ".join(STAGES))); return
    src = ROOT / "chapters" / (cid + ".md")
    if not src.exists():
        print("번역본이 없습니다: chapters/%s.md" % cid); return
    out = ROOT / "stages" / cid
    out.mkdir(parents=True, exist_ok=True)
    dst = out / (stage + ".md")
    shutil.copy2(src, dst)
    print("스냅샷 저장: stages/%s/%s.md (%d바이트)" % (cid, stage, dst.stat().st_size))

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
