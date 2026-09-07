#!/usr/bin/env python3
"""도판(사진·도해) 영역을 찾아 이미지로 잘라내고, 캡션과 짝지어 준다.

왜 '페이지 영역 잘라내기'인가:
  원서의 도판은 두 종류다. 사진은 래스터 이미지(XObject)로 들어 있고,
  필름 단면도나 A/B 롤 도해는 벡터 도형 + 글자로 그려져 있다.
  page.get_images()는 래스터만 나열하므로 벡터 도해는 잡히지 않는다.
  (벡터가 '추출 불가'라는 뜻이 아니다 — get_drawings()로 경로를,
   get_svg_image()로 SVG를 얻을 수 있다.)

  SVG를 쓰지 않은 이유: MuPDF의 SVG 출력은 페이지 전체 내용을 담고 viewBox로만
  잘라내므로, 도판 하나를 뽑아도 그 페이지의 본문이 전부 파일에 들어간다.
  도판만 남기려면 좌표 기준 후처리가 따로 필요하다. 지금은 영역을 잘라 PNG로 렌더하고,
  도판 안의 글자는 아래 labels_in()으로 따로 뽑아 번역 대상으로 남긴다.
  (SVG 경로는 라벨까지 벡터로 번역·재조판할 수 있어 장기적으로 더 낫다. 보류 사유는 위와 같다.)
"""
import re

MIN_W, MIN_H = 55, 40          # 이보다 작은 것은 도판으로 보지 않는다
CAP_GAP = 46                   # 도판 아래 이 거리 안의 작은 글씨를 캡션으로 본다

def _rect(r):
    return (r.x0, r.y0, r.x1, r.y1)

def _overlap(a, b, pad=6):
    return not (a[2] < b[0]-pad or b[2] < a[0]-pad or a[3] < b[1]-pad or b[3] < a[1]-pad)

def _union(a, b):
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))

def _merge(rects, pad=6):
    out = []
    for r in rects:
        hit = None
        for i, o in enumerate(out):
            if _overlap(r, o, pad):
                hit = i; break
        if hit is None:
            out.append(r)
        else:
            out[hit] = _union(out[hit], r)
            # 합치고 나면 다른 것과도 닿을 수 있으므로 다시 훑는다
            merged, again = [], out
            while True:
                out2, changed = [], False
                for x in again:
                    placed = False
                    for j, y in enumerate(out2):
                        if _overlap(x, y, pad):
                            out2[j] = _union(y, x); placed = True; changed = True; break
                    if not placed:
                        out2.append(x)
                again = out2
                if not changed:
                    break
            out = again
    return out

def find_figures(page, exclude=()):
    """도판 영역 목록을 읽기 순서(위 -> 아래, 왼 -> 오)로 돌려준다.

    exclude: 사이드바 상자·표 영역 등 도판으로 보면 안 되는 사각형들
    """
    w, h = page.rect.width, page.rect.height
    rects = []
    # (1) 래스터 이미지
    try:
        for info in page.get_image_info():
            rects.append(tuple(info["bbox"]))
    except Exception:
        pass
    # (2) 벡터 도형 — 표 괘선·각주 구분선·사이드바 배경은 뺀다
    for d in page.get_drawings():
        r = _rect(d["rect"])
        rw, rh = r[2]-r[0], r[3]-r[1]
        if rw < 8 or rh < 4:            # 가는 선
            continue
        if rw > w*0.85 and rh > h*0.85:  # 페이지 테두리
            continue
        rects.append(r)
    rects = [r for r in rects
             if (r[2]-r[0]) >= 8 and (r[3]-r[1]) >= 4
             and not any(_overlap(r, e, -4) for e in exclude)]
    figs = [r for r in _merge(rects, pad=10)
            if (r[2]-r[0]) >= MIN_W and (r[3]-r[1]) >= MIN_H
            and not any(_overlap(r, e, -6) for e in exclude)]
    figs.sort(key=lambda r: (round(r[1] / 12), r[0]))
    return figs

# 도해가 여러 조각으로 잘리는 문제를 여기서 추측으로 풀지 않는다.
#
# 시도해 봤고 물렸다. '조각 사이에 글이 없으면 한 그림'이라는 규칙은 그럴듯하지만,
# 이 책의 도판 사각형은 캡션까지 품고 있어서(원서 p.22의 사진 여섯 장이 그렇다)
# '사이의 글'이 아예 잡히지 않는다. 그 규칙을 쓰면 캡션이 각각 달린 사진 여섯 장이
# 한 덩어리로 붙어 버린다 — 고치려던 것보다 나쁜 결과다.
#
# 대신 normalize.py 가 source/overrides/<청크>.yaml 의 diagrams: 선언을 읽는다.
# 도해인지 아닌지는 페이지를 눈으로 봐야 알 수 있고, 그 판단은 어차피 VISUAL-CHECK
# 단계에서 한 번은 해야 한다. 추측하지 말고 그때 내린 판단을 적어 두는 편이 낫다.

def split_by_captions(fig, blocks, body_size):
    """도판 영역 안에 캡션이 끼어 있으면 그 자리에서 나눈다.

    원서 p.14처럼 사진-캡션-사진-캡션이 세로로 붙어 있으면 한 덩어리로 합쳐지는데,
    그러면 캡션이 다음 사진의 설명인 것처럼 보인다. 캡션 아래에 그림이 더 있으면
    거기서 끊는다."""
    w = fig[2] - fig[0]
    caps = [b for b in blocks
            if b["size"] < body_size - 0.4 and inside(b["bbox"], fig, pad=3)
            and (b["bbox"][2] - b["bbox"][0]) > w * 0.35]
    caps.sort(key=lambda b: b["bbox"][1])
    parts, top = [], fig[1]
    for c in caps:
        bottom = c["bbox"][3]
        if bottom < fig[3] - 25 and bottom - top > MIN_H:   # 아래에 그림이 더 남아 있다
            parts.append((fig[0], top, fig[2], bottom + 2))
            top = bottom + 2
    if not parts:
        return [fig]
    if fig[3] - top > 8:
        parts.append((fig[0], top, fig[2], fig[3]))
    return parts

def caption_for(fig, blocks, body_size):
    """도판 바로 아래의 작은 글씨 블록을 캡션으로 고른다."""
    best, bestd = None, 1e9
    for b in blocks:
        bb = b["bbox"]
        if b["size"] >= body_size - 0.4:
            continue
        d = bb[1] - fig[3]
        if not (-2 <= d <= CAP_GAP):
            continue
        if bb[2] < fig[0] - 30 or bb[0] > fig[2] + 30:   # 가로로 겹치지 않으면 남의 캡션
            continue
        if d < bestd:
            best, bestd = b, d
    return best

def inside(bbox, fig, pad=3):
    return (bbox[0] >= fig[0]-pad and bbox[1] >= fig[1]-pad
            and bbox[2] <= fig[2]+pad and bbox[3] <= fig[3]+pad)

def labels_in(fig, blocks, body_size):
    """도판 영역 안에 들어 있는 글자 조각(도해 라벨).

    본문 흐름에서 빼되 버리지는 않는다. 번역본에서도 도판 설명으로 살려야 하기 때문."""
    out = []
    for b in blocks:
        if b["size"] < body_size - 0.4 and inside(b["bbox"], fig, pad=4):
            t = b["txt"].strip()
            if t:
                out.append(t)
    return out

def render(page, fig, path, dpi=170):
    import pymupdf
    clip = pymupdf.Rect(*fig)
    page.get_pixmap(dpi=dpi, clip=clip).save(path)
