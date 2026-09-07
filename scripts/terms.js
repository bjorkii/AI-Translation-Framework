/* 용어 짚기 — 대시보드(용어집 카드)와 원문/번역본 보기가 함께 쓴다.
 *
 * 원문(영문)과 번역본(한국어)은 규칙이 달라야 한다.
 *   영문   낱말 경계로 끊고 복수형(-s/-es)까지 본다.
 *          Print 가 prints 는 잡고 printer·blueprint 는 잡지 않아야 한다.
 *   한국어 낱말 경계가 없고 조사가 뒤에 붙으므로 앞부분 일치로 본다. '유제층이'
 *   공통   여러 낱말로 된 용어는 낱말 사이 공백을 유연하게 본다.
 *          원서와 번역본의 띄어쓰기가 늘 같지는 않다. '보존용 마스터 필름'
 */
(function (g) {
  "use strict";

  function escHTML(s) {
    return (s == null ? "" : String(s)).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function termRegex(term) {
    var body = String(term).trim()
      .replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
      .replace(/\s+/g, "\\s+");
    var ko = /[가-힣]/.test(term);
    return ko
      ? new RegExp("(" + body + ")", "g")
      : new RegExp("(?<![A-Za-z0-9])(" + body + "(?:e?s)?)(?![A-Za-z0-9])", "gi");
  }

  /* 이미 이스케이프된 HTML 조각 안에서 용어를 <mark> 로 감싼다.
     용어도 같은 표기로 맞춰야 한다 — 본문은 & 가 &amp; 로 바뀌어 있다. */
  function markHTML(escaped, term) {
    try {
      return escaped.replace(termRegex(escHTML(term)), "<mark>$1</mark>");
    } catch (e) {
      return escaped;
    }
  }

  // 이 안의 글자는 건드리지 않는다 (이미 링크·코드·표시인 것들)
  var SKIP = /^(A|CODE|PRE|MARK|SCRIPT|STYLE|BUTTON|TEXTAREA|INPUT)$/;

  /* 문서 안의 글자를 훑어 용어를 감싼다.
     서버가 만든 HTML을 다시 파싱하지 않고 텍스트 노드만 건드리므로,
     각주 앵커나 이미지 같은 구조를 깨뜨리지 않는다. */
  function markTextNodes(root, terms, cls) {
    if (!terms.length) return 0;
    // 긴 용어부터 봐야 짧은 용어가 먼저 먹어치우지 않는다 ('마스터' vs '보존용 마스터 필름')
    var list = terms.slice().sort(function (a, b) {
      return String(b.term).length - String(a.term).length;
    });
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: function (n) {
        if (!n.nodeValue || !n.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
        for (var p = n.parentNode; p && p !== root; p = p.parentNode) {
          if (SKIP.test(p.nodeName)) return NodeFilter.FILTER_REJECT;
        }
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    var nodes = [], n, hits = 0;
    while ((n = walker.nextNode())) nodes.push(n);

    nodes.forEach(function (node) {
      var html = escHTML(node.nodeValue), touched = false;
      list.forEach(function (t) {
        var re;
        try { re = termRegex(escHTML(t.term)); } catch (e) { return; }
        // 이미 감싼 구간 안은 다시 건드리지 않는다
        html = html.replace(/<span class="[^"]*"[^>]*>[\s\S]*?<\/span>|[^<]+/g, function (seg) {
          if (seg.charAt(0) === "<") return seg;
          return seg.replace(re, function (m) {
            touched = true; hits++;
            return '<span class="' + cls + (t.decided ? " done" : " todo") +
              '" data-term="' + escHTML(t.term) + '">' + m + "</span>";
          });
        });
      });
      if (touched) {
        var span = document.createElement("span");
        span.innerHTML = html;
        node.parentNode.replaceChild(span, node);
      }
    });
    return hits;
  }

  g.TermTools = { escHTML: escHTML, termRegex: termRegex,
                  markHTML: markHTML, markTextNodes: markTextNodes };
})(window);
