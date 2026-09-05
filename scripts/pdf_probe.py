#!/usr/bin/env python3
"""PDF 구조 파악 + 텍스트 레이어 신뢰도 스팟체크 (파이프라인 1절 2단계).

사용법: python3 pdf_probe.py <파일.pdf> [샘플페이지수]
출력: 구조 요약 + 텍스트 품질 지표 + 샘플 원문
"""
import sys, re, statistics
from collections import Counter
import pymupdf

def main(path, n_sample=5):
    doc = pymupdf.open(path)
    npages = len(doc)

    print("=" * 70)
    print(f"파일: {path}")
    print(f"페이지 수: {npages}")
    meta = {k: v for k, v in (doc.metadata or {}).items() if v}
    for k in ("title", "author", "producer", "creator"):
        if meta.get(k):
            print(f"  {k}: {meta[k][:80]}")

    toc = doc.get_toc()
    print(f"\n[목차(북마크)] {len(toc)}개 항목")
    if toc:
        lv1 = [t for t in toc if t[0] == 1]
        print(f"  최상위 레벨 항목: {len(lv1)}개  (전체 레벨: {sorted(set(t[0] for t in toc))})")
        for lvl, title, page in toc[:40]:
            print(f"    {'  '*(lvl-1)}L{lvl} p.{page:>3} {title[:60]}")
        if len(toc) > 40:
            print(f"    ... 외 {len(toc)-40}개")
    else:
        print("  (북마크 없음 — 분할 단위를 본문 제목 패턴으로 추정해야 함)")

    # --- 페이지별 지표 수집 ---
    chars, imgs, links, blocks = [], [], [], []
    long_tok = bad_char = hyphen_eol = single_tok = total_tok = 0
    x0_by_page = []
    sample_txt = {}
    for i, page in enumerate(doc):
        t = page.get_text()
        chars.append(len(t))
        imgs.append(len(page.get_images(full=True)))
        links.append(len(page.get_links()))
        d = page.get_text("dict")
        tb = [b for b in d["blocks"] if b.get("type") == 0]
        blocks.append(len(tb))
        if tb:
            x0_by_page.append([round(b["bbox"][0], 1) for b in tb])
        toks = t.split()
        total_tok += len(toks)
        long_tok += sum(1 for w in toks if len(w) > 25)
        single_tok += sum(1 for w in toks if len(w) == 1 and w.isalpha())
        bad_char += t.count("�")
        hyphen_eol += len(re.findall(r"[A-Za-z]-\n", t))
        if i < n_sample or (npages > 20 and i in (npages//2, npages//2+1)):
            sample_txt[i] = t

    txt_pages = sum(1 for c in chars if c > 50)
    print("\n" + "=" * 70)
    print("[텍스트 레이어 신뢰도 지표]")
    print(f"  텍스트가 있는 페이지: {txt_pages}/{npages}  ({txt_pages/npages*100:.0f}%)")
    print(f"  페이지당 평균 문자수: {statistics.mean(chars):.0f}  (최소 {min(chars)}, 최대 {max(chars)})")
    print(f"  전체 토큰 수: {total_tok:,}")
    print(f"  25자 초과 붙어쓰기 토큰: {long_tok}건  ({long_tok/max(total_tok,1)*100:.2f}%)  <- 띄어쓰기 깨짐 신호")
    print(f"  1글자 토큰: {single_tok}건  ({single_tok/max(total_tok,1)*100:.2f}%)  <- 과분할 신호")
    print(f"  깨진 문자(U+FFFD): {bad_char}건")
    print(f"  줄 끝 하이픈 분철: {hyphen_eol}건  <- 재결합 처리 대상")
    print(f"  이미지: 총 {sum(imgs)}개 (이미지 있는 페이지 {sum(1 for x in imgs if x)}개)")
    print(f"  링크 주석: 총 {sum(links)}개 (링크 있는 페이지 {sum(1 for x in links if x)}개)")
    print(f"  텍스트 블록: 페이지당 평균 {statistics.mean(blocks):.1f}개")

    # 스캔본 판정
    full_img_pages = sum(1 for i, page in enumerate(doc) if imgs[i] == 1 and chars[i] < 50)
    print(f"\n  판정: ", end="")
    if txt_pages / npages < 0.5:
        print("텍스트 레이어 없음/부실 -> OCR 필요 (스캔본 가능성 높음)")
    elif full_img_pages > npages * 0.5:
        print("전면 이미지 페이지 다수 -> 스캔본 + OCR 레이어 가능성")
    elif long_tok / max(total_tok, 1) > 0.01 or bad_char > 10:
        print("텍스트 레이어는 있으나 품질 의심 (띄어쓰기/문자 깨짐)")
    else:
        print("born-digital 텍스트 레이어로 보임 (품질 양호)")

    # 다단 조판 추정: 페이지별 블록 좌측 x좌표 군집
    print("\n[레이아웃 추정]")
    flat = [x for p in x0_by_page for x in p]
    if flat:
        cnt = Counter(round(x/10)*10 for x in flat)
        common = cnt.most_common(6)
        print(f"  텍스트 블록 좌측 x좌표 분포(상위): {common}")
        distinct = [x for x, c in cnt.items() if c > len(flat)*0.08]
        print(f"  주요 좌측 정렬선: {sorted(distinct)}  -> ", end="")
        print("다단 조판 가능성" if len(distinct) >= 3 else "단단(1단) 조판으로 보임")

    print("\n" + "=" * 70)
    print("[샘플 원문 추출 결과]")
    for i, t in sample_txt.items():
        print(f"\n----- p.{i+1} (문자수 {len(t)}) -----")
        print(t[:900])
    doc.close()

if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 5)
