#!/usr/bin/env python3
"""마커 위치 검사 — LAYOUT-UNCERTAIN(p.N) 이 정말 'N쪽 본문 구간' 안에 있는지 검사.

우리 규약: [원서 p.N] = 'N쪽은 여기서 끝'.
따라서 N쪽 본문은  [원서 p.(N-1)] 다음 ~ [원서 p.N] 앞  구간이다.
"""
import glob, io, re
bad = ok = 0
for f in sorted(glob.glob('source/*.md')):
    lines = io.open(f, encoding='utf-8').read().splitlines()
    ends = {}                      # 페이지라벨 -> 그 페이지 끝 마커의 줄번호
    for i, ln in enumerate(lines):
        m = re.match(r'^\[원서 p\.([^\]]+)\]$', ln.strip())
        if m: ends[m.group(1)] = i
    for i, ln in enumerate(lines):
        m = re.search(r'LAYOUT-UNCERTAIN: p\.(\S+)', ln)
        if not m: continue
        pg = m.group(1)
        end_here = ends.get(pg)
        try:
            prev = str(int(pg) - 1)
        except ValueError:
            prev = None
        start_after = ends.get(prev)
        inside = (end_here is None or i < end_here) and \
                 (start_after is None or i > start_after)
        if inside: ok += 1
        else:
            bad += 1
            print("  [어긋남] %s:%d  p.%s 경고 · 이전끝=%s · 이번끝=%s"
                  % (f, i+1, pg, start_after, end_here))
print("구간 안 %d건 / 어긋남 %d건" % (ok, bad))
import sys
sys.exit(1 if bad else 0)
