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
# senses: 번역어는 같지만 뜻의 폭이 다른 경우. 무엇을 고를지가 아니라
#   '어떤 뜻으로 쓰였는지' 를 번역하는 쪽에 알려 주기 위한 칸이다.
SENSES = re.compile(r"^\s{4}senses:\s*$(.*?)(?=^\s{4}\w|\Z)", re.M | re.S)
SENSE = re.compile(r'-\s*case:\s*"(.*?)"[ \t]*(?:\n\s*means:\s*"(.*?)")?')

# nomatch: 이 낱말이 본문에 있어도 그 용어로 보지 않는다.
#   'Leader' 는 필름 앞뒤에 붙이는 여분 필름인데, 본문의 'community leaders'(지도자)까지
#   같은 낱말로 잡힌다. 그런 자리를 미리 빼 두는 칸이다.
# same_as: 같은 뜻의 다른 원어. 'perforation' 과 'sprocket hole' 처럼.
#   따로 등록해야 둘 다 본문에서 짚히고 검사에 걸리지만, 같은 말이라는 사실은
#   데이터로 남아야 한다. 메모에 적어 두면 기계가 모른다.
FIELDS = ("translation", "tbd", "notation", "context", "full",
          "definition_en", "definition_ko", "source", "principle_form", "nomatch",
          "same_as")


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

        senses = []
        sb = SENSES.search(body)
        if sb:
            for m3 in SENSE.finditer(sb.group(1)):
                senses.append({"case": m3.group(1), "means": m3.group(2) or ""})

        e = {"term": term, "alternates": alts, "senses": senses}
        for k in FIELDS:
            e[k] = f(k)
        out.append(e)
    return out


def nomatch(e):
    """이 용어로 보지 않을 낱말 목록."""
    return [x.strip() for x in (e.get("nomatch") or "").split("|") if x.strip()]

def strip_nomatch(text, e):
    """본문에서 오탐 낱말을 지운 사본. 용어가 실제로 등장하는지 셀 때 쓴다."""
    for bad in nomatch(e):
        text = re.sub(r"(?<![A-Za-z0-9])" + re.escape(bad) + r"(?![A-Za-z0-9])",
                      " ", text, flags=re.I)
    return text

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
    if e.get("same_as"):
        s += "  [%s 와 같은 뜻]" % e["same_as"]
    return s

def sense_lines(e):
    """번역하는 쪽에 넘길 뜻갈래 설명. 같은 번역어라도 폭이 다를 때 쓴다."""
    return ["%s → %s" % (x["case"], x["means"]) for x in (e.get("senses") or []) if x.get("case")]

def check_same_as(entries):
    """same_as 로 묶인 것끼리 번역어가 어긋나지 않는지 본다.

    같은 뜻이라 해 놓고 서로 다르게 옮기면 혼란만 는다. 만든 칸이 오히려
    일을 늘리지 않도록, 어긋나면 알린다.
    """
    by = {e["term"]: e for e in entries}
    bad = []
    for e in entries:
        other = by.get(e.get("same_as") or "")
        if not other:
            continue
        a, b = set(translations(e)), set(translations(other))
        if a and b and not (a & b):
            bad.append((e["term"], sorted(a), other["term"], sorted(b)))
    return bad
