#!/usr/bin/env python3
"""새 번역 프로젝트 시작 묶음을 만든다.

팀원이 다른 책으로 새 프로젝트를 시작할 때 받아야 할 것만 골라 담는다.
이 저장소에는 이 책(The Film Preservation Guide)의 작업물이 함께 들어 있어서,
통째로 내려받으면 남의 원문·번역문·도판까지 따라온다.

    .venv/bin/python scripts/make_starter.py            # starter/ 폴더로
    .venv/bin/python scripts/make_starter.py --zip      # 압축 파일 하나로

무엇을 담는가

  틀      어느 책에나 그대로 쓰는 것 — 스크립트, 실행기, 파이프라인 문서, CLAUDE.md
  서식    책마다 새로 채우는 것 — 구조 지도·용어집·톤 지침·책 지식의 빈 서식
  참고    같은 분야를 번역할 때 도움이 되는 것 — 이 책에서 쌓은 용어집을 참고본으로

무엇을 담지 않는가

  이 책의 원문(source/)·번역문(chapters/)·단계 기록(stages/)·감수 기록(reviews/)
  ·도판(assets/)·원본 PDF·진행 상태. 남의 책 내용이기 때문이다.
"""
import argparse
import io
import json
import os
import shutil
import zipfile
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 그대로 복사 (틀)
COPY = [
    "CLAUDE.md",
    "ai_book_translation_pipeline.md",
    "requirements.txt",
    ".gitignore",
    "docs/대시보드 사용법.md",
    "대시보드 실행.command",
    "대시보드 실행.bat",
    "scripts",
]

# 빈 서식으로 새로 만드는 것 (책마다 다름)
TEMPLATES = {
    "project-info.json": json.dumps({
        "title": "", "subtitle": "", "publisher": "",
        "direction": "영 → 한", "file": "intermediate/원서.pdf",
        "total_file_pages": 0, "printed_range": "", "page_offset": 0,
        "text_layer": "(pdf_probe.py 로 확인)",
    }, ensure_ascii=False, indent=1) + "\n",

    "structure-map.yaml": """# 원서 구조 지도 — 청크 분할과 페이지 마커의 기준
#
# 쪽번호 표기 원칙
#   printed = 원서에 인쇄된 쪽번호 (PDF 페이지 라벨과 같다)
#   file    = PDF 파일 안의 물리적 순번 (1부터)
#
# AI 가 scripts/pdf_probe.py · scripts/layout_probe.py 로 원서를 훑어 채운다.
# 사람은 결과를 확인만 하면 된다.

source: intermediate/원서.pdf
total_file_pages: 0
page_label_offset: 0

# 조판 의존 수치 덮어쓰기 (없으면 scripts/layout_profile.py 의 기본값)
# 규칙은 어느 책에나 통하지만 그 규칙을 적용하는 수치는 원서마다 다르다.
# 무엇을 조정할 수 있는지는 layout_profile.py 에 목록으로 있다.
#
# layout:
#   foot_band: 0.92
#   h2_pt: 13.5
#   bullets: "•–▪"

front_matter: []

chapters: []
  # - {id: ch01, file: [1, 10], printed: [1, 10], pages: 10, title: "", parser: prose}

back_matter: []
  # parser: prose | record | term_definition | rebuild | toc
""",

    "book-knowledge.md": """---
book: (원서 제목)
last_updated: (없음)
---

# 책 지식 축적 문서

용어집(낱말 대응)·톤 지침(문체)과 별개로, **이 책이 무엇을 말하는가에 대한 AI의 이해**를 담는다.
3~4챕터마다 사람이 검토한다.

## 핵심 인물/개체

## 챕터별 핵심 논지 요약

## 반복되는 주제/모티프

## AI가 확신하지 못하는 부분 (사용자 확인 필요)
""",

    "guide/tone-and-decision.md": """# 톤 지침 및 결정 기록

**원서**: (제목 · 발행처 · 연도 · 쪽수) · (번역 방향)

## 예상 독자 / 분야 / 전체 톤

- **원서 성격**:
- **예상 독자**:
- **분야**:
- **전체 톤**:

## 한국어 표기 규칙

- 문장 종결체:
- 인용부호:
- 숫자·단위:

## 표기 방침

## 복수형 다루기

- **용어집 표제어는 단수형으로 등록한다.** 매칭이 복수형을 함께 잡으므로, 복수형으로
  등록하면 오히려 단수형을 놓친다. 예외는 복수형이 독자적인 뜻을 갖는 경우와 늘 짝으로
  쓰이는 관용어뿐이다.
- **번역할 때 `-들`을 굳이 붙이지 않는다.** 다만 복수임을 밝혀야 뜻이 사는 자리에서는 명시한다.

## 결정 기록 (append-only)

> 기존 항목은 수정하지 않는다. 방침을 번복할 때는 "이전 결정을 어느 시점에 왜 번복했는지"를
> 새 항목으로 추가한다.

> 첫 청크의 사람 감수를 마치면 여기에 **[톤 앵커]** 항목을 남긴다 — 어느 청크인지와
> 그 문체의 특징(문장 길이, 열거 방식, 원문 병기 밀도)을. 이후 청크는 그것에 맞추고,
> 정규화를 다시 돌릴 때는 그 청크가 한 글자도 바뀌지 않아야 한다(회귀 감시 기준).
""",

    "glossary/glossary.yaml": """# 용어집 — 이 프로젝트에서 쌓아 가는 것
#
# 스키마 설명은 scripts/glossary_io.py 첫머리에 있다.
#   term         원어. 본문에서 용어를 찾는 열쇠다. **단수형**으로 등록한다
#   translation  기본 번역어
#   alternates   맥락에 따라 갈리는 번역어  [{value, when}]
#   senses       번역어는 같지만 뜻의 폭이 다를 때  [{case, means}]
#   same_as      같은 뜻의 다른 원어
#   nomatch      이 낱말이 나와도 그 용어로 보지 않는다 (오탐 제외)
#   tbd          아직 정하지 못해 사용자에게 물을 선택지 ("가 | 나")
#   full         풀어쓴 이름 (약어일 때)
#   notation     표기 규칙 메모
#   locked       고유명사 등 잠근 항목
#
# 같은 분야 책이라면 reference/ 의 참고 용어집에서 필요한 항목을 가져다 쓸 수 있다.

entries: []
""",

    "status.md": """# 진행 상태

(scripts/update_status.py 가 생성합니다. 직접 고치지 말고 스크립트를 다시 실행해 주세요.)
""",
}

EMPTY_DIRS = ["source", "chapters", "stages", "reviews", "assets",
              "intermediate", "tm", "source/overrides", "glossary", "guide",
              "reference"]

README = """# 새 번역 프로젝트 시작하기

이 폴더를 통째로 복사해 새 프로젝트 폴더로 씁니다.

## 1. 원서 PDF 를 넣습니다

    intermediate/  폴더에 원서 PDF 를 넣으세요.

## 2. 대시보드를 엽니다

| 쓰는 컴퓨터 | 더블클릭할 파일 |
|---|---|
| 맥 | **대시보드 실행.command** |
| 윈도우 | **대시보드 실행.bat** |

처음 한 번은 파이썬 환경을 만드느라 1분쯤 걸립니다. 그 다음부터는 바로 열립니다.

## 3. AI 세션을 시작합니다

AI 에게 이렇게 말하면 됩니다.

> 이 폴더에서 번역 프로젝트를 시작할 거야. `CLAUDE.md` 와
> `ai_book_translation_pipeline.md` 를 읽고, 원서 PDF 로 구조 분석부터 해줘.

AI 가 절차를 알고 있습니다. 원서를 훑어 `structure-map.yaml` 을 채우고, 무엇을
정해야 하는지 물어봅니다. 사람이 할 일은 **선택지에 답하는 것과 감수**뿐입니다.

## 폴더 안내

| 폴더·파일 | 무엇 |
|---|---|
| `CLAUDE.md` | AI 세션이 매번 읽는 지침 |
| `ai_book_translation_pipeline.md` | 파이프라인 전체 절차 |
| `scripts/` | 모든 자동화. 직접 열어 볼 일은 없습니다 |
| `structure-map.yaml` | 원서 구조 지도 (AI 가 채웁니다) |
| `glossary/glossary.yaml` | 이 프로젝트의 용어집 (비어 있는 상태로 시작) |
| `reference/` | 같은 분야 참고 용어집. 필요한 것만 가져다 씁니다 |
| `docs/대시보드 사용법.md` | 화면 사용 안내 |
| `guide/tone-and-decision.md` | 톤 지침과 결정 기록 |
| `source/` `chapters/` | AI 가 만드는 원문·번역문 |

## 참고 용어집

`reference/` 안에 다른 프로젝트에서 쌓은 용어집이 있습니다. **같은 분야**를 번역한다면
용어를 처음부터 다시 정하지 않아도 됩니다. AI 에게 "참고 용어집에서 이 책에 나오는
용어를 가져와 줘" 라고 하면 원서에 실제로 등장하는 것만 골라 옮겨 줍니다.

다른 분야라면 그냥 두거나 지우면 됩니다.
"""


def build(dest):
    if os.path.exists(dest):
        shutil.rmtree(dest)
    os.makedirs(dest)

    for item in COPY:
        src = os.path.join(ROOT, item)
        if not os.path.exists(src):
            print("  !! 없음, 건너뜀: %s" % item)
            continue
        dst = os.path.join(dest, item)
        if os.path.isdir(src):
            shutil.copytree(src, dst,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            os.makedirs(os.path.dirname(dst) or dest, exist_ok=True)
            shutil.copy2(src, dst)

    for d in EMPTY_DIRS:
        p = os.path.join(dest, d)
        os.makedirs(p, exist_ok=True)
        # 빈 폴더는 git 이 담지 못하므로 표시 파일을 둔다
        keep = os.path.join(p, ".gitkeep")
        if not os.listdir(p):
            io.open(keep, "w").close()

    for rel, body in TEMPLATES.items():
        p = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(p) or dest, exist_ok=True)
        io.open(p, "w", encoding="utf-8").write(body)

    io.open(os.path.join(dest, "README.md"), "w", encoding="utf-8").write(README)

    # 참고 용어집 — 이 프로젝트에서 쌓은 것을 분야 참고본으로 남긴다
    src_g = os.path.join(ROOT, "glossary", "glossary.yaml")
    if os.path.exists(src_g):
        info = {}
        pi = os.path.join(ROOT, "project-info.json")
        if os.path.exists(pi):
            try:
                info = json.load(io.open(pi, encoding="utf-8"))
            except Exception:
                pass
        head = ("# 참고 용어집 — %s\n#\n"
                "# 다른 프로젝트에서 쌓은 것입니다. 같은 분야라면 여기서 필요한 항목만\n"
                "# 가져다 쓰세요. AI 에게 '참고 용어집에서 이 책에 나오는 용어를 가져와 줘'\n"
                "# 라고 하면 원서에 실제로 등장하는 것만 골라 옮겨 줍니다.\n#\n"
                "# 이 파일은 직접 쓰지 않습니다. 작업용 용어집은 glossary/glossary.yaml 입니다.\n\n"
                % (info.get("title") or "이전 프로젝트"))
        body = io.open(src_g, encoding="utf-8").read()
        body = body.split("\n", 1)[1] if body.startswith("#") else body
        io.open(os.path.join(dest, "reference", "glossary-reference.yaml"),
                "w", encoding="utf-8").write(head + body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", action="store_true", help="압축 파일로 만든다")
    ap.add_argument("--out", default=os.path.join(ROOT, "starter"))
    a = ap.parse_args()

    build(a.out)
    n = sum(len(f) for _, _, f in os.walk(a.out))
    print("시작 묶음: %s (파일 %d개)" % (os.path.relpath(a.out, ROOT), n))

    if a.zip:
        z = a.out + "-%s.zip" % date.today().isoformat()
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as f:
            for base, _, files in os.walk(a.out):
                for name in files:
                    p = os.path.join(base, name)
                    f.write(p, os.path.join("번역프로젝트-시작",
                                            os.path.relpath(p, a.out)))
        print("압축 파일: %s (%.1fMB)" % (os.path.relpath(z, ROOT),
                                          os.path.getsize(z) / 1e6))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
