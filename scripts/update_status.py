#!/usr/bin/env python3
"""structure-map.yaml과 실제 파일 상태에서 status.md를 다시 생성합니다.

세션이 바뀌어도 진행 지점을 잃지 않도록, 단계가 바뀔 때마다 실행합니다.
    python3 scripts/update_status.py
"""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
spec = importlib.util.spec_from_file_location("dash", HERE / "dashboard.py")
dash = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dash)

st = dash.build_state()
p, g = st["progress"], st["glossary"]

rows = ["| %s | %s | %s | %s | %s |" % (
    c["id"], c["title"], "–".join(c.get("printed") or []),
    c.get("pages") or "", c["stage_label"]) for c in st["chunks"]]

out = ("# 진행 상태\n\n"
       "원서: The Film Preservation Guide (NFPF, 2004) · 133쪽 · 영 → 한\n"
       "번역 시작 %s · %d일째 · 진행율 %s%% (%d/%d 단계)\n\n"
       "단계: %s\n\n"
       "| 청크 | 제목 | 원서 쪽 | 분량 | 단계 |\n|---|---|---|---|---|\n%s\n\n"
       "용어집: 전체 %d항목 · 확정 %d · 결정 대기 %d · 미착수 %d\n\n"
       "> 이 파일은 `scripts/update_status.py`가 생성합니다. 직접 고치지 말고 스크립트를 다시 실행해 주세요.\n"
       ) % (p["started"], p["elapsed_days"], p["percent"], p["steps_done"], p["steps_total"],
            " → ".join(p["stage_labels"]), "\n".join(rows),
            g["total"], g["decided"], g["pending"], g["untouched"])

(ROOT / "status.md").write_text(out, encoding="utf-8")
print("status.md 갱신 · 진행율 %s%% · 청크 %d개 · 용어집 확정 %d/%d"
      % (p["percent"], len(st["chunks"]), g["decided"], g["total"]))
