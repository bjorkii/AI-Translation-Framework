#!/usr/bin/env python3
"""청크별 조각을 모아 layout-manifest.yaml 을 만든다 (파이프라인 2.6절).

원본 요소의 위치를 인라인 마커로만 두면 "원본의 이미지 열두 개가 최종본에 다
들어갔는가"를 확인할 방법이 사람 눈밖에 없다. normalize.py 가 원문을 만들면서
intermediate/manifest/<청크>.json 에 조각을 남기고, 이 스크립트가 그것을 모은다.

    .venv/bin/python scripts/build_manifest.py

검증은 scripts/check_manifest.py 가 한다.
"""
import glob
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "intermediate", "manifest")
OUT = os.path.join(ROOT, "layout-manifest.yaml")


def order_key(path):
    """structure-map.yaml 의 차례대로 정렬한다."""
    import yaml
    m = yaml.safe_load(open(os.path.join(ROOT, "structure-map.yaml"), encoding="utf-8"))
    ids = [c["id"] for k in ("front_matter", "chapters", "back_matter")
           for c in (m.get(k) or [])]
    return ids


def main():
    ids = order_key(None)
    files = sorted(glob.glob(os.path.join(SRC, "*.json")),
                   key=lambda p: ids.index(os.path.basename(p)[:-5])
                   if os.path.basename(p)[:-5] in ids else 999)
    if not files:
        print("매니페스트 조각이 없습니다. 먼저 원문을 생성해 주세요:")
        print("    .venv/bin/python scripts/normalize_all.py --force")
        return 1

    lines = ["# 위치정보 매니페스트 (파이프라인 2.6절) — 자동 생성물",
             "#",
             "# scripts/normalize_all.py 가 원문을 만들 때 남긴 조각을",
             "# scripts/build_manifest.py 가 모은 것이다. 직접 고치지 않는다.",
             "#",
             "# 쓰임",
             "#   누락 검증  번역이 끝난 뒤 scripts/check_manifest.py 가 최종 md 를 훑어",
             "#              빠진 이미지·표·각주와 페이지별 문단 수 불일치를 뽑아낸다.",
             "#   원본 재판독 이상이 보일 때 bbox 로 원본 페이지의 그 자리를 바로 찾아간다.",
             "#   회귀 대조  스크립트를 고친 전후로 이 파일이 같은지 비교한다.",
             "",
             "elements:"]
    nrec = 0
    for f in files:
        d = json.load(open(f, encoding="utf-8"))
        for r in d["records"]:
            nrec += 1
            lines.append("  - id: %s" % r["id"])
            lines.append("    type: %s" % r["type"])
            lines.append("    chunk: %s" % r["chunk"])
            lines.append("    source_page: \"%s\"" % r["source_page"])
            lines.append("    bbox: [%s]" % ", ".join(str(v) for v in r["bbox"]))
            if r.get("asset"):
                lines.append("    asset: %s" % r["asset"])
            if r.get("diagram"):
                lines.append("    diagram: true")
            if r.get("rows"):
                lines.append("    rows: %d" % r["rows"])
                lines.append("    cols: %d" % r["cols"])
            lines.append("    status: pending")     # check_manifest.py 가 채운다

    lines += ["", "pages:"]
    npage = 0
    for f in files:
        d = json.load(open(f, encoding="utf-8"))
        for p in d["pages"]:
            npage += 1
            lines.append("  - chunk: %s" % p["chunk"])
            lines.append("    source_page: \"%s\"" % (p["source_page"] or ""))
            lines.append("    paragraph_count: %d" % p["paragraph_count"])
            lines.append("    first_line: %s" % json.dumps(p["first_line"], ensure_ascii=False))

    open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("layout-manifest.yaml 생성 · 요소 %d건 · 페이지 %d개" % (nrec, npage))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
