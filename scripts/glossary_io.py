#!/usr/bin/env python3
"""용어집 읽기 — 한 곳에 모아 둔다.

같은 파싱이 대시보드·번역 컨텍스트·감수 스크립트에 따로 있었다. 그래서 용어집에
필드를 하나 더하면 어떤 곳은 알고 어떤 곳은 모르는 상태가 된다. 실제로 alternates
(맥락에 따라 갈리는 번역어)를 더했을 때, 1차 번역에 쓰이는 컨텍스트는 그 규칙을
보지 못했고 2차 감수는 올바른 선택을 '용어집 미반영'으로 잡았다.

스키마 (glossary/glossary.yaml)
    - term: "Storage"                     원어. 본문에서 용어를 찾는 열쇠
      translation: "보존고"                 기본 번역어
      alternates:                          맥락에 따라 갈리는 번역어
        - value: "스토리지"
          when: "디지털 저장장치·저장공간 맥락"
      tbd: "가 | 나"                        아직 정하지 못해 사용자에게 물을 선택지
      full: "…"                            풀어쓴 이름 (약어일 때)
      notation: "…"                        표기 규칙 메모
      definition_en / definition_ko / source / principle_form …
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "glossary", "glossary.yaml")

ENTRY = re.compile(r'  - term: "(.*?)"\n(.*?)(?=\n  - term: |\Z)', re.S)
ALTS = re.compile(r"^\s{4}alternates:\s*$(.*?)(?=^\s{4}\w|\Z)", re.M | re.S)
# value 뒤에 \s* 를 쓰면 줄바꿈까지 먹어 when 이 영영 잡히지 않는다.
ALT = re.compile(r'-\s*value:\s*"(.*?)"[ \t]*(?:\n\s*when:\s*"(.*?)")?')

FIELDS = ("translation", "tbd", "notation", "context", "full",
          "definition_en", "definition_ko", "source", "principle_form")


def load(path=None):
    """용어집 항목 목록. 파일이 없으면 빈 목록."""
    p = path or PATH
    if not os.path.exists(p):
        return []
    txt = open(p, encoding="utf-8").read()
    out = []
    for m in ENTRY.finditer(txt):
        term, body = m.group(1), m.group(2)

        def f(k):
            mm = re.search(r'^\s{4}' + k + r':\s*(?:"(.*?)"|(null))\s*$', body, re.M)
            return mm.group(1) if (mm and mm.group(1) is not None) else None

        alts = []
        ab = ALTS.search(body)
        if ab:
            for a in ALT.finditer(ab.group(1)):
                alts.append({"value": a.group(1), "when": a.group(2) or ""})

        e = {"term": term, "alternates": alts}
        for k in FIELDS:
            e[k] = f(k)
        out.append(e)
    return out


def translations(e):
    """이 용어에 허용되는 번역어 전부 (기본 + 맥락별 대체).

    감수에서 '용어집을 지켰는가' 를 볼 때는 이 목록 중 하나만 나와도 지킨 것이다.
    기본값만 보면, 맥락에 맞게 대체어를 고른 올바른 번역이 위반으로 잡힌다.
    """
    out = []
    if e.get("translation"):
        out.append(e["translation"])
    for a in e.get("alternates") or []:
        if a.get("value"):
            out.append(a["value"])
    return out


def describe(e):
    """번역 컨텍스트에 실을 한 줄. 맥락 분기가 있으면 조건까지 적는다."""
    s = e.get("translation") or "(미정)"
    for a in e.get("alternates") or []:
        s += " / %s%s" % (a["value"], ("(%s)" % a["when"]) if a.get("when") else "")
    return s
