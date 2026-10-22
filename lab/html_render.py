# -*- coding: utf-8 -*-
"""내용 JSON을 디자인된 HTML 문서 한 파일로 바꾼다.

모델은 내용만 JSON으로 정리하고, 배치·글꼴·색은 여기서 정한다. 모델이 HTML을 직접 쓰지 않으므로
결과가 일정하고, 모든 글자를 이스케이프해 스크립트가 끼어들 수 없다(내려받아 열어도 안전하다).
Claude Code의 HTML 스킬(Render.ts)을 파이썬 표준 라이브러리만으로 옮긴 것이다. 글꼴 파일은 넣지 않고
시스템 글꼴을 쓴다. 외부 요청이 없는 문서를 만든다.

글에는 **굵게**와 `코드`만 쓸 수 있다. 그 밖의 태그는 글자 그대로 보인다.
"""

import json
import os
import re
import uuid

from . import config

OUTPUT_DIR = os.path.join(config.STATE_DIR, "outputs")
MAX_OUTPUTS = 50                    # 오래된 것부터 지운다
_ID = re.compile(r"^[0-9a-f]{12}$")

MAX_SECTIONS, MAX_BLOCKS, MAX_ROWS, MAX_TEXT = 40, 100, 300, 8000

REGISTERS = {
    "dossier": {
        "label": "어두운 녹색 + 주황. 근거 묶음, 비판 검토, 조사 기록",
        "vars": {"ink": "#0d1712", "panel": "#121f17", "line": "#26382c", "fg": "#f2ede2",
                 "dim": "#c6c0b1", "accent": "#f58220", "accent2": "#7d9fc4", "danger": "#d0654a"},
        "display": "Impact, 'Arial Narrow', 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif",
        "mono": "'Courier New', 'D2Coding', 'Malgun Gothic', monospace",
        "solid": ["VERIFIED", "확인됨"],
    },
    "ledger": {
        "label": "짙은 남색 + 금색. 보고서, 계획, 비교, 수치",
        "vars": {"ink": "#101623", "panel": "#161e30", "line": "#2a3550", "fg": "#dce6f2",
                 "dim": "#9fb0c8", "accent": "#d9a441", "accent2": "#6fbf9f", "danger": "#c96f6f"},
        "display": "'Iowan Old Style', Palatino, 'Batang', 'Noto Serif KR', Georgia, serif",
        "mono": "Consolas, Menlo, 'D2Coding', 'Malgun Gothic', monospace",
        "solid": ["VERIFIED", "CONFIRMED", "확인됨"],
    },
}
BODY_FONT = "'Pretendard', 'Malgun Gothic', 'Apple SD Gothic Neo', 'Noto Sans KR', system-ui, sans-serif"

EXAMPLE = {
    "title": "F-3 라인 전환 검토 요약",
    "eyebrow": "연구 보고 · 2026년 10월",
    "subtitle": "시뮬레이션 결과를 한 장으로 정리했습니다.",
    "summary": {"label": "한 줄 요약", "text": "누적 영업이익 **중앙값 12.3억**, 적자 확률 **18%**."},
    "sections": [
        {"title": "핵심 수치", "intro": "실제 실행한 코드의 결과입니다.",
         "blocks": [
             {"type": "table", "headers": ["항목", "값"], "rows": [["중앙값", "12.3억"], ["하위 5%", "-4.1억"]]},
             {"type": "list", "items": [{"lead": "가장 큰 변수.", "text": "수율 램프 기간."}]},
             {"type": "callout", "text": "추진 여부 판단은 포함하지 않습니다."},
         ]},
    ],
    "footer": "자료: line_transition.csv",
}


def schema_text():
    return json.dumps(EXAMPLE, ensure_ascii=False, indent=2)


# ── 글 처리 ───────────────────────────────────────────────────────────

def esc(value):
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def inline(value):
    """이스케이프한 뒤 **굵게**와 `코드`만 되살린다. 줄바꿈은 <br>."""
    text = esc(value)
    text = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    return text.replace("\n", "<br>")


def _paragraphs(value):
    parts = [p.strip() for p in re.split(r"\n\s*\n", str(value)) if p.strip()]
    return "".join("<p>%s</p>" % inline(p) for p in parts)


def _text(value, what):
    if value is None:
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str):
        raise ValueError("%s은(는) 글이어야 합니다." % what)
    if len(value) > MAX_TEXT:
        raise ValueError("%s이(가) 너무 깁니다. %d자까지 쓸 수 있습니다." % (what, MAX_TEXT))
    return value


# ── 블록 ──────────────────────────────────────────────────────────────

def _block(b, reg, where):
    if not isinstance(b, dict):
        raise ValueError("%s: 블록은 {...} 형식이어야 합니다." % where)
    kind = b.get("type")
    if kind == "prose":
        return '<div class="prose">%s</div>' % _paragraphs(_text(b.get("text"), where + " text"))
    if kind == "callout":
        return '<div class="callout">%s</div>' % _paragraphs(_text(b.get("text"), where + " text"))
    if kind == "group":
        detail = _text(b.get("detail"), where + " detail")
        return '<p class="group"><b>%s</b>%s</p>' % (
            esc(_text(b.get("label"), where + " label")), " · " + esc(detail) if detail else "")
    if kind == "quote":
        badge = _text(b.get("badge"), where + " badge")
        solid = " solid" if badge.upper() in [s.upper() for s in reg["solid"]] else ""
        badge_html = '<span class="badge%s">%s</span>' % (solid, esc(badge)) if badge else ""
        quote = _text(b.get("quote"), where + " quote")
        body = ('<p class="q"><span class="om">“</span>%s<span class="om">”</span></p>' % esc(quote)) if quote else ""
        text = _text(b.get("text"), where + " text")
        note = _text(b.get("note"), where + " note")
        source = _text(b.get("source"), where + " source")
        return ('<div class="ex"><div class="id">%s%s</div><div>%s%s%s%s</div></div>' % (
            esc(_text(b.get("id"), where + " id")), badge_html, body,
            "<p>%s</p>" % inline(text) if text else "",
            '<p class="src">%s</p>' % inline(note) if note else "",
            '<p class="src">%s</p>' % inline(source) if source else ""))
    if kind == "list":
        items = b.get("items")
        if not isinstance(items, list) or not items:
            raise ValueError("%s: list에는 items가 필요합니다." % where)
        rows = []
        for i, it in enumerate(items[:MAX_BLOCKS]):
            if isinstance(it, str):
                it = {"lead": "", "text": it}
            if not isinstance(it, dict):
                raise ValueError("%s: items[%d]는 {lead, text} 형식이어야 합니다." % (where, i))
            lead = _text(it.get("lead"), where + " lead")
            rows.append("<li><p>%s%s</p></li>" % ("<b>%s</b> " % esc(lead) if lead else "",
                                                  inline(_text(it.get("text"), where + " text"))))
        return '<ul class="lead">%s</ul>' % "".join(rows)
    if kind == "cut":
        return ('<div class="cut"><div class="stamp">%s</div><div><span class="q">“%s”</span><p>%s</p></div></div>' % (
            esc(_text(b.get("stamp"), where + " stamp")), esc(_text(b.get("quote"), where + " quote")),
            inline(_text(b.get("note"), where + " note"))))
    if kind == "code":
        return "<pre><code>%s</code></pre>" % esc(_text(b.get("text"), where + " text"))
    if kind == "table":
        headers, rows = b.get("headers"), b.get("rows")
        if not isinstance(headers, list) or not isinstance(rows, list):
            raise ValueError("%s: table에는 headers와 rows(글 배열의 배열)가 필요합니다." % where)
        head = "".join("<th>%s</th>" % esc(_text(h, where + " header")) for h in headers)
        body = []
        for r in rows[:MAX_ROWS]:
            if not isinstance(r, list):
                raise ValueError("%s: rows의 각 줄은 배열이어야 합니다." % where)
            body.append("<tr>%s</tr>" % "".join("<td>%s</td>" % inline(_text(c, where + " cell")) for c in r))
        return '<div class="tablewrap"><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>' % (
            head, "".join(body))
    raise ValueError("%s: 알 수 없는 블록 종류입니다(%s). prose, callout, group, quote, list, cut, table, code 중에서 고르세요."
                     % (where, kind))


# ── 스타일 ────────────────────────────────────────────────────────────

_STYLE = """
*{box-sizing:border-box}
html{background:var(--ink)}
body{background:var(--ink);color:var(--fg);font-family:BODY;line-height:1.7;font-size:16px;margin:0;word-break:keep-all;overflow-wrap:anywhere}
.page{max-width:780px;margin:0 auto;padding:64px 28px 80px}
.eyebrow{font-family:MONO;font-size:12px;letter-spacing:.2em;text-transform:uppercase;color:var(--accent);margin:0 0 14px}
h1{font-family:DISPLAY;font-weight:800;font-size:clamp(32px,7vw,54px);line-height:1.15;margin:0 0 12px;text-wrap:balance}
h1 .acc{color:var(--accent)}
.subtitle{color:var(--dim);max-width:60ch;margin:0 0 36px}
h2{font-family:DISPLAY;font-weight:800;font-size:24px;line-height:1.3;margin:50px 0 6px;text-wrap:balance}
h2 .n{color:var(--accent);font-family:MONO;font-size:15px;margin-right:10px}
.rule{height:1px;background:var(--line);border:0;margin:0 0 18px}
.intro{color:var(--dim);max-width:62ch;margin:0 0 20px}
.slab{background:var(--panel);border:1px solid var(--line);border-left:5px solid var(--accent);padding:22px 26px;margin:0 0 8px}
.slab p{margin:0}
.slab b{color:var(--accent)}
.callout{background:var(--panel);border:1px solid var(--line);border-left:5px solid var(--accent2);padding:18px 22px;margin:14px 0}
.callout p{margin:0 0 10px}.callout p:last-child{margin:0}
.group{font-family:MONO;font-size:12px;letter-spacing:.16em;text-transform:uppercase;color:var(--dim);margin:28px 0 6px}
.group b{color:var(--fg)}
.ex{display:grid;grid-template-columns:78px 1fr;gap:18px;border-top:1px solid var(--line);padding:16px 0}
.ex:last-of-type{border-bottom:1px solid var(--line)}
.ex .id{font-family:MONO;font-size:12px;color:var(--accent);padding-top:3px}
.ex .id .badge{display:block;margin-top:6px;width:max-content}
.badge{font-family:MONO;font-size:10px;letter-spacing:.1em;padding:2px 6px;color:var(--dim);border:1px solid var(--dim);border-radius:2px}
.badge.solid{background:var(--accent);color:var(--ink);border-color:var(--accent);font-weight:700}
.ex p{margin:0 0 6px}
.ex .q{font-family:MONO;font-size:14.5px}
.ex .q .om{color:var(--accent)}
.ex .src{font-size:13px;color:var(--dim)}
ul.lead{list-style:none;margin:0;padding:0}
ul.lead li{padding:12px 0;border-top:1px solid var(--line)}
ul.lead li:last-child{border-bottom:1px solid var(--line)}
ul.lead p{margin:0;font-size:15px;color:var(--dim)}
ul.lead b{color:var(--fg)}
.cut{display:grid;grid-template-columns:110px 1fr;gap:16px;padding:14px 0;border-top:1px solid var(--line)}
.cut:last-of-type{border-bottom:1px solid var(--line)}
.cut .stamp{font-family:MONO;color:var(--danger);border:2px solid var(--danger);font-size:11px;letter-spacing:.1em;font-weight:700;padding:4px 6px;text-align:center;align-self:start;transform:rotate(-3deg)}
.cut .q{font-family:MONO;font-size:14px;color:var(--dim);text-decoration:line-through;text-decoration-thickness:2px}
.cut p{margin:6px 0 0;font-size:13.5px;color:var(--dim)}
.tablewrap{overflow-x:auto;margin:14px 0}
table{border-collapse:collapse;width:100%;font-size:14.5px}
th{font-family:MONO;font-size:12px;letter-spacing:.06em;color:var(--dim);text-align:left;padding:8px 14px 8px 0;border-bottom:1px solid var(--fg);white-space:nowrap}
td{padding:9px 14px 9px 0;border-bottom:1px solid var(--line);vertical-align:top;font-variant-numeric:tabular-nums}
.prose{max-width:64ch}.prose p{margin:0 0 12px}
code{font-family:MONO;font-size:.92em;background:var(--panel);padding:1px 5px;border-radius:3px}
pre{background:var(--panel);border:1px solid var(--line);padding:14px 16px;overflow-x:auto;margin:14px 0;font-size:13.5px;line-height:1.55}pre code{padding:0;background:none}
.foot{margin-top:52px;color:var(--dim);font-size:13px;border-top:1px solid var(--line);padding-top:16px}
@media(max-width:560px){.page{padding:40px 18px 60px}.ex{grid-template-columns:1fr;gap:6px}.cut{grid-template-columns:1fr}.cut .stamp{justify-self:start}}
@media print{html,body{background:#fff}body{color:#111}}
"""


def _css(reg):
    v = reg["vars"]
    root = (":root{--ink:%s;--panel:%s;--line:%s;--fg:%s;--dim:%s;--accent:%s;--accent2:%s;--danger:%s}"
            % tuple(v[k] for k in ("ink", "panel", "line", "fg", "dim", "accent", "accent2", "danger")))
    return root + _STYLE.replace("BODY", BODY_FONT).replace("MONO", reg["mono"]).replace("DISPLAY", reg["display"])


# ── 문서 ──────────────────────────────────────────────────────────────

def render(doc, register="ledger"):
    """내용 JSON(dict)을 완성된 HTML 문서 글자로 바꾼다. 형식이 틀리면 ValueError."""
    reg = REGISTERS.get(register)
    if reg is None:
        raise ValueError("register는 %s 중 하나여야 합니다." % ", ".join(REGISTERS))
    if not isinstance(doc, dict):
        raise ValueError("content는 {title, sections[]} 형식의 객체여야 합니다.")
    title = _text(doc.get("title"), "title").strip()
    sections = doc.get("sections")
    if not title or not isinstance(sections, list) or not sections:
        raise ValueError("content에는 title(글)과 sections(비어 있지 않은 배열)가 필요합니다. 형식 예시:\n" + schema_text())
    if len(sections) > MAX_SECTIONS:
        raise ValueError("섹션은 %d개까지 쓸 수 있습니다." % MAX_SECTIONS)

    words = title.split()
    accent = doc.get("accentLastWord", True) is not False and len(words) > 1
    last = words.pop() if accent else ""
    h1 = esc(" ".join(words)) + (' <span class="acc">%s</span>' % esc(last) if last else "")
    if not accent:
        h1 = esc(title)
    numbered = doc.get("numberedSections", True) is not False

    out = []
    for i, s in enumerate(sections):
        where = "sections[%d]" % i
        if not isinstance(s, dict):
            raise ValueError("%s는 {title, blocks[]} 형식이어야 합니다." % where)
        blocks = s.get("blocks") or []
        if not isinstance(blocks, list) or len(blocks) > MAX_BLOCKS:
            raise ValueError("%s: blocks는 %d개 이하의 배열이어야 합니다." % (where, MAX_BLOCKS))
        intro = _text(s.get("intro"), where + " intro")
        out.append('<section><h2>%s%s</h2><hr class="rule">%s%s</section>' % (
            '<span class="n">%02d</span>' % (i + 1) if numbered else "",
            esc(_text(s.get("title"), where + " title")),
            '<p class="intro">%s</p>' % inline(intro) if intro else "",
            "\n".join(_block(b, reg, "%s.blocks[%d]" % (where, j)) for j, b in enumerate(blocks))))

    summary = doc.get("summary")
    summary_html = ""
    if isinstance(summary, dict) and (summary.get("text") or summary.get("html")):
        label = _text(summary.get("label"), "summary.label")
        summary_html = '<div class="slab">%s<p>%s</p></div>' % (
            '<p class="eyebrow" style="margin-bottom:8px">%s</p>' % esc(label) if label else "",
            inline(_text(summary.get("text") or summary.get("html"), "summary.text")))
    eyebrow = _text(doc.get("eyebrow"), "eyebrow")
    subtitle = _text(doc.get("subtitle"), "subtitle")
    footer = _text(doc.get("footer"), "footer")

    return ('<!doctype html>\n<html lang="ko"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; img-src data:">'
            "<title>%s</title><style>%s</style></head><body><div class=\"page\">\n%s<h1>%s</h1>\n%s%s\n%s\n%s</div></body></html>\n" % (
                esc(title), _css(reg),
                '<p class="eyebrow">%s</p>' % esc(eyebrow) if eyebrow else "", h1,
                '<p class="subtitle">%s</p>' % inline(subtitle) if subtitle else "", summary_html,
                "\n".join(out),
                '<p class="foot">%s</p>' % inline(footer) if footer else ""))


# ── 마크다운 → 내용 ───────────────────────────────────────────────────

_LIST_ITEM = re.compile(r"^\s*([-*•]|\d+[.)])\s+")
_TABLE_ROW = re.compile(r"^\|.*\|$")


def from_markdown(md, title="", eyebrow="", subtitle="", footer=""):
    """마크다운 글을 내용 dict로 바꾼다.

    작은 모델도 중첩 JSON보다 마크다운은 안정적으로 쓴다. ## 는 섹션, ### 는 소제목, 표·목록·인용(>)·코드를
    각각 table, list, callout, code 블록으로 옮기고, 첫 ## 앞의 글은 한 줄 요약으로 쓴다.
    """
    lines = str(md).replace("\r\n", "\n").split("\n")
    summary, sections, para = [], [], []

    def blocks():
        if not sections:
            sections.append({"title": "내용", "blocks": []})
        return sections[-1]["blocks"]

    def flush():
        if para:
            text = "\n".join(para).strip()
            if not sections:
                summary.append(text)
            elif text:
                blocks().append({"type": "prose", "text": text})
            del para[:]

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        head = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if stripped.startswith("```"):
            flush()
            code = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            blocks().append({"type": "code", "text": "\n".join(code)})
        elif head and len(head.group(1)) == 1 and not title:
            flush()
            title = head.group(2).strip()
        elif head and len(head.group(1)) <= 2:
            flush()
            if not (len(head.group(1)) == 1 and head.group(2).strip() == title):   # 제목을 다시 쓴 줄은 건너뛴다
                sections.append({"title": head.group(2).strip(), "blocks": []})
        elif head:
            flush()
            blocks().append({"type": "group", "label": head.group(2).strip()})
        elif _TABLE_ROW.match(stripped):
            flush()
            rows = []
            while i < len(lines) and _TABLE_ROW.match(lines[i].strip()):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.match(r"^:?-{2,}:?$", c) for c in cells):
                    rows.append(cells)
                i += 1
            i -= 1
            if rows:
                blocks().append({"type": "table", "headers": rows[0], "rows": rows[1:]})
        elif _LIST_ITEM.match(lines[i]):
            flush()
            items = []
            while i < len(lines) and _LIST_ITEM.match(lines[i]):
                body = _LIST_ITEM.sub("", lines[i], count=1).strip()
                lead = re.match(r"^\*\*(.+?)\*\*[:：]?\s*(.*)$", body)
                items.append({"lead": lead.group(1), "text": lead.group(2)} if lead else {"lead": "", "text": body})
                i += 1
            i -= 1
            blocks().append({"type": "list", "items": items})
        elif stripped.startswith(">"):
            flush()
            quote = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip().lstrip(">").strip())
                i += 1
            i -= 1
            blocks().append({"type": "callout", "text": "\n".join(quote)})
        elif not stripped or re.match(r"^-{3,}$", stripped):
            flush()
        else:
            para.append(stripped)
        i += 1
    flush()

    doc = {"title": title or "문서", "sections": sections or [{"title": "내용", "blocks": []}]}
    if summary:
        doc["summary"] = {"text": "\n\n".join(summary)}
    for key, value in (("eyebrow", eyebrow), ("subtitle", subtitle), ("footer", footer)):
        if value:
            doc[key] = value
    return doc


# ── 저장 ──────────────────────────────────────────────────────────────

def save(html):
    """만든 문서를 state/outputs/에 두고 id를 돌려준다."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_id = uuid.uuid4().hex[:12]
    with open(os.path.join(OUTPUT_DIR, out_id + ".html"), "w", encoding="utf-8", newline="") as f:
        f.write(html)
    files = sorted((os.path.join(OUTPUT_DIR, n) for n in os.listdir(OUTPUT_DIR) if n.endswith(".html")),
                   key=os.path.getmtime)
    for old in files[:-MAX_OUTPUTS]:
        try:
            os.remove(old)
        except OSError:
            pass
    return out_id


def load(out_id):
    """id로 문서를 읽는다. 형식이 틀렸거나 없으면 None."""
    if not isinstance(out_id, str) or not _ID.match(out_id):
        return None
    try:
        with open(os.path.join(OUTPUT_DIR, out_id + ".html"), "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None
