# -*- coding: utf-8 -*-
"""스킬 — skills/<이름>/SKILL.md 폴더를 읽어 모델이 쓸 수 있게 한다.

SKILL.md는 Claude Code 형식과 같다. 맨 위 --- 사이에 name, description(과 선택적으로 tools)을 적고,
그 아래에 사용 지침을 쓴다. 폴더를 넣고 앱을 다시 켜면 등록된다.

모델에게는 use_skill 도구 하나로 보인다. 도구 설명에 스킬 이름과 설명만 실어 두고, 모델이
필요하다고 판단하면 use_skill(이름)으로 본문 지침을 읽는다. 스킬이 늘어도 프롬프트가 커지지 않는다.

**스킬은 코드를 실행하지 않는다.** 지침 글과, 아래 SKILL_TOOLS에 이름이 있는 내장 도구만 쓸 수 있다.
스킬 폴더에 파이썬을 넣어도 읽지 않는다. 폴더에 쓸 수 있는 사람이 앱에서 코드를 돌리는 길을 만들지 않으려는 것이다.
"""

import json
import os
import re

from . import config, html_render

SKILLS_DIR = os.path.join(config.ROOT, "skills")
SOURCE = "스킬"
_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
MAX_DESCRIPTION = 500
MAX_BYTES = 80000                   # 지침 2만 자(한글은 글자당 3바이트라 약 6만 바이트) + 머리말을 담는다


def _unquote(value):
    """값 전체를 감싼 짝이 맞는 따옴표 한 쌍만 벗긴다. 글 끝에 있는 따옴표는 지우지 않는다."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _frontmatter(raw):
    """머리말(--- 사이)과 본문으로 나눈다. YAML 전체가 아니라 스킬에 필요한 부분집합만 읽는다.

    `key: value` 한 줄, 값이 > >- | |- 이면 이후 들여쓴 줄(빈 줄 포함)을 모은다.
    값이 비어 있고 다음 줄이 들여쓰여 있으면 목록(- 항목)으로 보고 모은다.
    닫는 ---가 없으면 머리말이 없는 글로 본다.
    """
    lines = raw.split("\n")
    if not lines or lines[0].rstrip() != "---":
        return {}, raw
    end = next((i for i in range(1, len(lines)) if lines[i].rstrip() == "---"), None)
    if end is None:
        return {}, raw
    meta, i = {}, 1
    while i < end:
        line = lines[i]
        i += 1
        key, sep, value = line.partition(":")
        if not sep or line[:1] in " \t#" or not key.strip():
            continue
        key, value = key.strip().lower(), value.strip()
        block = value in (">", ">-", "|", "|-", ">+", "|+")
        if block or not value:
            held = []
            while i < end and (not lines[i].strip() or lines[i][:1] in " \t"):
                held.append(lines[i].strip())
                i += 1
            while held and not held[-1]:
                held.pop()
            if block and value[0] == "|":
                value = "\n".join(held)
            else:
                value = " ".join(h[2:] if h.startswith("- ") else h for h in held if h)
        else:
            value = _unquote(value)
        meta[key] = value
    return meta, "\n".join(lines[end + 1:]).lstrip("\n")


def _tool_names(value):
    """`a, b`, `a b`, `[a, b]` 모두 이름 목록으로."""
    value = value.replace("[", " ").replace("]", " ")
    return [_unquote(t) for t in re.split(r"[,\s]+", value) if t]


def parse_text(raw, folder=""):
    """SKILL.md 글 하나를 읽는다. 이름 규칙에 어긋나면 None."""
    meta, body = _frontmatter(raw.replace("\r\n", "\n"))
    name = (meta.get("name") or folder).lower()     # Claude Code 스킬은 name이 대문자인 경우가 있다(HTML)
    if not _NAME.match(name):
        return None
    desc = " ".join((meta.get("description", "") + " " + meta.get("when_to_use", "")).split())
    wanted = []
    for t in _tool_names(meta.get("tools", "") + " " + meta.get("allowed-tools", "")):
        if t not in wanted:
            wanted.append(t)
    return {"name": name, "folder": folder, "description": desc[:MAX_DESCRIPTION],
            "tools": [t for t in wanted if t in SKILL_TOOLS],
            "unsupported_tools": [t for t in wanted if t not in SKILL_TOOLS],
            "model_invocable": meta.get("disable-model-invocation", "").lower() not in ("true", "yes", "1"),
            "body": body.strip()}


def _parse(path, folder):
    try:
        if os.path.getsize(path) > MAX_BYTES:
            return None
        with open(path, "r", encoding="utf-8-sig") as f:
            raw = f.read()
    except OSError:
        return None
    return parse_text(raw, folder)


def load_all():
    """등록된 스킬 목록. 읽을 수 없는 폴더는 건너뛴다."""
    found = {}
    try:
        folders = sorted(os.listdir(SKILLS_DIR))
    except OSError:
        return []
    for folder in folders:
        if folder.startswith("."):                  # .import-* 같은 작업 폴더는 스킬이 아니다
            continue
        path = os.path.join(SKILLS_DIR, folder, "SKILL.md")
        if os.path.isfile(path):
            skill = _parse(path, folder)
            if skill and skill["name"] not in found:
                found[skill["name"]] = skill
    return list(found.values())


def problems():
    """읽지 못해 건너뛴 스킬 폴더의 안내 문구. 조용히 사라지면 원인을 알 수 없어서 화면에 알린다."""
    out = []
    try:
        folders = sorted(os.listdir(SKILLS_DIR))
    except OSError:
        return out
    for folder in folders:
        if folder.startswith("."):
            continue
        path = os.path.join(SKILLS_DIR, folder, "SKILL.md")
        if not os.path.isfile(path):
            continue
        try:
            if os.path.getsize(path) > MAX_BYTES:
                out.append("%s 스킬이 너무 커서(%dKB 초과) 건너뛰었습니다." % (folder, MAX_BYTES // 1000))
                continue
        except OSError:
            continue
        if _parse(path, folder) is None:
            out.append("%s 스킬을 읽지 못해 건너뛰었습니다. 이름은 영문 소문자·숫자·-·_만 쓸 수 있습니다." % folder)
    return out


# ── 스킬이 쓸 수 있는 내장 도구 ──────────────────────────────────────────

def _render_html(args):
    """markdown(권장)이나 content(JSON)로 문서를 만든다. 작은 모델은 중첩 JSON을 자주 깨뜨려서 markdown을 먼저 받는다."""
    content = args.get("content")
    try:
        if isinstance(content, str):                    # 모델이 JSON을 글자로 넘기는 일이 있다
            try:
                content = json.loads(content)
            except ValueError:
                return {"오류": "content가 JSON 형식이 아닙니다. markdown 인자로 본문을 넘겨 주세요."}
        if content is None:
            markdown = args.get("markdown")
            if not isinstance(markdown, str) or not markdown.strip():
                return {"오류": "markdown(문서 본문)이 필요합니다."}
            extra = {k: args[k] for k in ("title", "eyebrow", "subtitle", "footer") if isinstance(args.get(k), str)}
            content = html_render.from_markdown(markdown, **extra)
        html = html_render.render(content, args.get("register") or "ledger")
    except ValueError as exc:
        return {"오류": str(exc)}
    out_id = html_render.save(html)
    return {"결과": "HTML 문서를 만들었습니다.",
            "표시": "[[html:%s]]" % out_id,
            "안내": "최종 답변에 위 표시 줄을 그대로 한 줄로 넣으면 화면에 미리보기와 다운로드 버튼이 나옵니다. "
                    "문서 내용을 답변에 다시 쓸 필요는 없습니다."}


SKILL_TOOLS = {
    "render_html": {
        "description": "마크다운 본문을 받아 디자인된 HTML 문서 한 장으로 만들어 화면에 보여 준다. "
                       "사용자가 HTML로 달라고 할 때 쓰고, HTML 코드를 직접 쓰지 않는다. "
                       "처음에는 use_skill('html')로 작성 방법을 읽는다. 결과의 '표시' 줄을 최종 답변에 그대로 넣는다.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "문서 제목"},
                "markdown": {"type": "string",
                             "description": "문서 본문을 마크다운으로. ## 는 섹션, ### 는 소제목, 표·목록·> 인용을 쓸 수 있다. "
                                            "첫 ## 앞의 글은 한 줄 요약이 된다."},
                "register": {"type": "string", "enum": list(html_render.REGISTERS),
                             "description": "디자인. ledger=남색+금색(보고서·수치), dossier=녹색+주황(근거·검토)"},
                "subtitle": {"type": "string", "description": "제목 아래 설명(선택)"},
                "footer": {"type": "string", "description": "맨 아래 출처·방법 메모(선택)"},
            },
            "required": ["title", "markdown"],
        },
        "function": _render_html,
    },
}


# ── 화면에서 추가·수정·삭제 ──────────────────────────────────────────────
# 스킬은 글과 도구 이름뿐이라 화면에서 써도 코드가 실행되는 길이 생기지 않는다.
# 쓸 수 있는 도구는 SKILL_TOOLS에 있는 것으로 제한하고, 이름은 폴더 이름으로 쓰므로 형식을 검사한다.

MAX_SKILLS = 30
MAX_BODY = 20000


def view():
    """화면에 보여 줄 스킬 목록과, 스킬이 고를 수 있는 도구."""
    # 본문은 싣지 않는다. 화면이 상태를 자주 읽는데 스킬마다 최대 2만 자가 매번 실리면 낭비다. 본문은 get()으로 받는다.
    return {
        "skills": [{"name": s["name"], "description": s["description"], "tools": s["tools"],
                    "unsupported_tools": s["unsupported_tools"], "model_invocable": s["model_invocable"]}
                   for s in load_all()],
        "tools": [{"name": n, "description": spec["description"]} for n, spec in SKILL_TOOLS.items()],
    }


def get(name):
    """스킬 하나의 본문까지 포함한 내용. 없으면 None."""
    for s in load_all():
        if s["name"] == name:
            return {"name": s["name"], "description": s["description"], "tools": s["tools"], "body": s["body"]}
    return None


def save(name, description, tools, body):
    """SKILL.md를 쓴다. 같은 이름이 있으면 그 폴더에 덮어쓴다. 문제가 있으면 ValueError."""
    name = (name or "").strip() if isinstance(name, str) else ""
    if not _NAME.match(name):
        raise ValueError("이름은 영문 소문자·숫자·밑줄(_)·하이픈(-)만 쓸 수 있고 40자까지입니다. 예: report-style")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("설명을 입력해 주세요. 모델이 이 설명을 보고 스킬을 쓸지 정합니다.")
    description = " ".join(description.split())
    if len(description) > MAX_DESCRIPTION:
        raise ValueError("설명은 %d자까지 쓸 수 있습니다." % MAX_DESCRIPTION)
    if not isinstance(body, str) or not body.strip():
        raise ValueError("지침을 입력해 주세요.")
    if len(body) > MAX_BODY:
        raise ValueError("지침은 %d자까지 쓸 수 있습니다." % MAX_BODY)
    tools = tools if isinstance(tools, list) else []
    bad = [t for t in tools if t not in SKILL_TOOLS]
    if bad:
        raise ValueError("쓸 수 없는 도구입니다: %s" % ", ".join(str(b) for b in bad)[:80])

    existing = {s["name"]: s for s in load_all()}
    if name not in existing and len(existing) >= MAX_SKILLS:
        raise ValueError("스킬은 %d개까지 둘 수 있습니다." % MAX_SKILLS)
    folder = existing[name]["folder"] if name in existing else name
    tools_line = "tools: %s\n" % ", ".join(tools) if tools else ""
    text = "---\nname: %s\ndescription: %s\n%s---\n\n%s\n" % (
        name, description, tools_line, body.strip().replace("\r\n", "\n"))
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError("스킬이 너무 큽니다. 지침을 줄여 주세요.")
    target = os.path.join(SKILLS_DIR, folder)
    os.makedirs(target, exist_ok=True)
    with open(os.path.join(target, "SKILL.md"), "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return name


def remove(name):
    """스킬 폴더의 SKILL.md를 지운다. 다른 파일이 남아 있으면 폴더는 그대로 둔다."""
    for s in load_all():
        if s["name"] == name:
            path = os.path.join(SKILLS_DIR, s["folder"])
            os.remove(os.path.join(path, "SKILL.md"))
            try:
                os.rmdir(path)
            except OSError:
                pass
            return True
    return False


# ── 모델에게 줄 도구 ──────────────────────────────────────────────────

def entries():
    """use_skill과, 등록된 스킬이 쓰겠다고 한 내장 도구. 스킬이 없으면 빈 목록."""
    skills = [s for s in load_all() if s["model_invocable"]]    # 모델 호출 금지 스킬은 모델에게 보이지 않는다
    if not skills:
        return []
    by_name = {s["name"]: s for s in skills}

    def use_skill(args):
        name = (args or {}).get("name")
        skill = by_name.get(name) if isinstance(name, str) else None
        if skill is None:
            return {"오류": "그런 스킬은 없습니다.", "쓸 수 있는 스킬": sorted(by_name)}
        return {"스킬": skill["name"], "지침": skill["body"]}

    listing = "\n".join("- %s: %s" % (s["name"], s["description"]) for s in skills)
    out = [{
        "name": "use_skill",
        "description": "작업에 맞는 스킬의 지침을 읽는다. 아래 스킬 중 요청에 맞는 것이 있으면 먼저 호출한다.\n" + listing,
        "parameters": {"type": "object",
                       "properties": {"name": {"type": "string", "enum": sorted(by_name),
                                               "description": "스킬 이름"}},
                       "required": ["name"]},
        "source": SOURCE,
        "call": use_skill,
    }]
    wanted = []
    for s in skills:
        for t in s["tools"]:
            if t not in wanted:
                wanted.append(t)
    for t in wanted:
        spec = SKILL_TOOLS[t]
        out.append({"name": t, "description": spec["description"], "parameters": spec["parameters"],
                    "source": SOURCE, "call": spec["function"]})
    return out
