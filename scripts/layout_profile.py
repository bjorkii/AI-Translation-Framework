#!/usr/bin/env python3
"""조판 의존 상수 한자리 모음 (레이아웃 프로파일).

정규화 규칙에는 두 종류가 섞여 있다.

  **일반 원리** — 어느 책에 옮겨도 성립한다.
      · 명단·서지의 항목 경계는 문장부호가 아니라 줄 시작 좌표에 있다
      · 캡션은 도판과 가로로 실제 겹쳐야 그 도판의 것이다
      · 사진 안에는 제목 크기의 글자가 들어 있지 않다
      · 도해는 화살표와 배치에 뜻이 있어 텍스트로 옮길 수 없다

  **그 원리를 이 책의 조판에 맞춘 수치** — 아래 값들이다.
      쪽 여백이 다르거나, 제목 글자가 더 작거나, 2단이 아닌 책에서는 달라진다.

두 번째 것들이 코드 여기저기 숫자로 박혀 있으면, 다른 책을 시작하는 사람은
무엇을 확인해야 하는지 알 수 없다. 그래서 한자리에 모으고 이름을 붙였다.
프로젝트마다 다르면 `structure-map.yaml` 의 `layout:` 블록에서 덮어쓴다.

    layout:
      foot_band: 0.92        # 쪽번호가 더 아래에 있는 책
      h2_pt: 13.5            # 제목 글자가 작은 책

새 책을 시작할 때 확인할 순서는 `scripts/layout_probe.py` 의 출력이다.
"""
import os

DEFAULTS = {
    # ── 쪽 가장자리 ──────────────────────────────────────────────
    # 이 위/아래 띠는 머리말·쪽번호 자리로 보고 본문에서 뺀다.
    "head_band": 0.09,        # 쪽 높이 대비
    "foot_band": 0.88,
    "head_maxlen": 60,        # 이보다 긴 글은 머리말로 보지 않는다

    # ── 제목 ────────────────────────────────────────────────────
    "h2_pt": 15.0,            # 이 크기 이상이면 큰 제목
    "h3_pt": 13.0,            # 이 크기 이상이면 작은 제목
    "banner_pad": 30.0,       # 제목 글자 높이 + 이만큼이면 '제목 배너'(도판 아님)

    # ── 단(段) ──────────────────────────────────────────────────
    "column_split": 0.45,     # 쪽 너비의 이 지점을 좌우 단 경계로 본다
    "column_minlen": 40,      # 단 판정에 넣을 최소 글자 수

    # ── 도판 ────────────────────────────────────────────────────
    "fig_min_w": 55.0,        # 이보다 작으면 도판으로 보지 않는다
    "fig_min_h": 40.0,
    "cap_gap": 46.0,          # 도판 아래 이 거리 안의 작은 글씨 = 캡션
    "cap_overlap": 0.4,       # 캡션이 도판과 가로로 겹쳐야 하는 최소 비율

    # ── 항목 목록(명단·서지·색인) ───────────────────────────────
    "indent_tol": 2.0,        # 좌측 정렬선으로 볼 오차
    "indent_min": 6.0,        # 이만큼 들여쓰면 앞 항목에 이어지는 줄
    "gap_tol": 3.0,           # 항목 사이 간격이 이만큼 벌어지면 새 항목

    # ── 글머리표 ────────────────────────────────────────────────
    # 원서가 목록에 쓰는 기호. 책마다 다르다(–, ▪, ·, * 등).
    "bullets": "•",
}

_cache = None


def profile():
    """structure-map.yaml 의 layout: 로 덮어쓴 프로파일."""
    global _cache
    if _cache is not None:
        return _cache
    p = dict(DEFAULTS)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    f = os.path.join(root, "structure-map.yaml")
    try:
        import yaml
        d = yaml.safe_load(open(f, encoding="utf-8")) or {}
        for k, v in (d.get("layout") or {}).items():
            if k not in DEFAULTS:
                print("  !! 알 수 없는 layout 항목: %s (무시)" % k)
                continue
            p[k] = v
    except Exception:
        pass          # yaml 이 없어도 기본값으로 돈다
    _cache = p
    return p


def get(name):
    return profile()[name]
