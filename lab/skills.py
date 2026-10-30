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
import shutil

from . import config, html_render

SKILLS_DIR = os.path.join(config.ROOT, "skills")
SOURCE = "스킬"
_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
MAX_DESCRIPTION = 500
MAX_BYTES = 80000                   # 지침 2만 자(한글은 글자당 3바이트라 약 6만 바이트) + 머리말을 담는다
REFERENCE_EXTS = {".md", ".txt", ".json", ".csv", ".yaml", ".yml"}
MAX_REF_FILES = 100                 # 스킬 하나가 내놓는 참고 파일 수
MAX_REF_DEPTH = 3                   # 스킬 폴더 아래로 내려갈 수 있는 폴더 단계
MAX_READ_CHARS = 20000


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


# ── 참고 파일 ──────────────────────────────────────────────────────────
# 스킬 폴더 안의 글 파일(references/*.md 등)을 모델이 read_skill_file로 읽는다. 폴더 밖 내용이 새어 나가지 않게
# list_files와 read_file이 같은 규칙(_ref_parts_ok)을 쓰고, 읽을 때는 링크와 실제 경로까지 한 번 더 확인한다.

def _is_link(path):
    """심볼릭 링크나 정션(Windows)이면 True."""
    return os.path.islink(path) or (hasattr(os.path, "isjunction") and os.path.isjunction(path))


def _ref_parts_ok(parts):
    """상대 경로 조각 목록이 참고 파일로 쓸 수 있는 모양인지. 이름만 본다(파일 시스템은 보지 않는다)."""
    if not parts or len(parts) - 1 > MAX_REF_DEPTH:
        return False
    for part in parts:
        if not part or part.startswith("."):        # 빈 조각, ., .., 숨김
            return False
        if part[-1] in ". " or "~" in part:         # Windows가 끝의 점·공백을 지우거나 8.3 짧은 이름으로 바꿔 검사를 피하는 길
            return False
    if any(d.lower() == "scripts" for d in parts[:-1]):
        return False
    if len(parts) == 1 and parts[0].lower() == "skill.md":      # 본문은 use_skill로 읽는다
        return False
    return os.path.splitext(parts[-1])[1].lower() in REFERENCE_EXTS


def list_files(skill_dir):
    """SKILL.md를 뺀 참고 파일의 상대경로(/ 구분, 정렬). 숨김·scripts 폴더와 링크는 건너뛰고, 한도 넘는 건 버린다."""
    found = []
    for root, dirs, names in os.walk(skill_dir):
        rel = os.path.relpath(root, skill_dir)
        base = [] if rel == "." else rel.split(os.sep)
        dirs[:] = sorted(d for d in dirs
                         if not d.startswith(".") and d.lower() != "scripts"
                         and not _is_link(os.path.join(root, d)) and len(base) < MAX_REF_DEPTH)
        for n in sorted(names):
            full = os.path.join(root, n)
            if _ref_parts_ok(base + [n]) and not _is_link(full) and os.path.isfile(full):
                found.append("/".join(base + [n]))
                if len(found) >= MAX_REF_FILES:
                    return sorted(found)
    return sorted(found)


def read_file(name, rel_path):
    """스킬 폴더 안의 참고 파일 하나를 읽는다. 실패는 예외 대신 {"오류": ...}로 돌려준다(경로는 적지 않는다)."""
    skill = next((s for s in load_all() if s["name"] == name), None) if isinstance(name, str) else None
    if skill is None:
        return {"오류": "그런 스킬은 없습니다."}
    denied = {"오류": "읽을 수 없는 경로입니다. 스킬 폴더 안의 참고 파일 경로(예: references/a.md)만 쓸 수 있습니다."}
    if not isinstance(rel_path, str) or not rel_path or any(c in rel_path for c in "\\:\0") or rel_path.startswith("/"):
        return denied
    parts = rel_path.split("/")
    if not _ref_parts_ok(parts):
        return denied
    base = os.path.join(SKILLS_DIR, skill["folder"])
    try:
        walk = base
        for part in parts:                          # 중간 폴더나 파일이 링크면 거부한다
            walk = os.path.join(walk, part)
            if _is_link(walk):
                return denied
        root = os.path.normcase(os.path.realpath(base))
        target = os.path.normcase(os.path.realpath(walk))
        if os.path.commonpath([root, target]) != root or not os.path.isfile(target):
            return denied
        if not _ref_parts_ok(os.path.relpath(target, root).split(os.sep)):     # 실제 이름으로 한 번 더 검사
            return denied
        with open(target, "r", encoding="utf-8-sig") as f:
            text = f.read(MAX_READ_CHARS + 1)
    except UnicodeDecodeError:
        return {"오류": "텍스트로 읽을 수 없습니다."}
    except (OSError, ValueError):
        return denied
    return {"스킬": skill["name"], "경로": rel_path, "내용": text[:MAX_READ_CHARS], "잘림": len(text) > MAX_READ_CHARS}


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
                skill["files"] = list_files(os.path.join(SKILLS_DIR, folder))
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
                    "unsupported_tools": s["unsupported_tools"], "model_invocable": s["model_invocable"],
                    "files": len(s["files"])}
                   for s in load_all()],
        "tools": [{"name": n, "description": spec["description"]} for n, spec in SKILL_TOOLS.items()],
    }


def get(name):
    """스킬 하나의 본문까지 포함한 내용. 없으면 None."""
    for s in load_all():
        if s["name"] == name:
            return {"name": s["name"], "description": s["description"], "tools": s["tools"], "body": s["body"],
                    "model_invocable": s["model_invocable"]}
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
    if name in existing and not existing[name]["model_invocable"]:      # 모델 호출 금지 표시는 편집해도 유지한다
        tools_line += "disable-model-invocation: true\n"
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


# ── ~/.claude/skills 가져오기 ─────────────────────────────────────────────
# 화면은 폴더 이름만 보낸다. 서버는 그 이름을 원본 폴더 목록(importable)에서 찾을 때만 쓰고 경로로는 쓰지 않는다.
# 복사는 skills/.import-new-<이름> 임시 폴더에서 끝낸 뒤 바꿔 넣어서, 중간에 실패해도 기존 스킬이 그대로 남는다.

IMPORT_LABEL = "~/.claude/skills"
MAX_IMPORT_FILES = 40               # 가져올 때 스킬 하나가 가져가는 참고 파일 수
MAX_IMPORT_FILE_BYTES = 60000       # 참고 파일 하나의 크기 한도
MAX_IMPORT_TOTAL = 300000           # 참고 파일 합계 크기 한도(SKILL.md는 MAX_BYTES로 따로 센다)
MAX_IMPORT_SCAN = 2000              # 원본 폴더에서 훑어 볼 파일 수(node_modules 같은 큰 폴더 대비)
MAX_SKIPPED_SHOWN = 20
_CLAUDE_ONLY = re.compile(r"\bbun\b|Artifact|localhost:31337|~/\.claude|Voice Notification|\bTools/\w+\.ts", re.I)


def import_source_dir():
    """가져올 폴더. SKILLS_IMPORT_DIR이 있으면 그것, 없으면 ~/.claude/skills. 부를 때마다 읽는다."""
    return os.environ.get("SKILLS_IMPORT_DIR") or os.path.join(os.path.expanduser("~"), ".claude", "skills")


def _plan_import(skill_dir):
    """원본 스킬 폴더에서 복사할 파일(상대 경로 목록)과 건너뛸 파일(안내 문구 목록)을 가른다. 링크는 따라가지 않는다."""
    take, skipped, seen, total = [], [], 0, 0
    root_real = os.path.normcase(os.path.realpath(skill_dir))
    for root, dirs, names in os.walk(skill_dir):
        rel = os.path.relpath(root, skill_dir)
        base = [] if rel == "." else rel.split(os.sep)
        keep = []
        for d in sorted(dirs):
            if _is_link(os.path.join(root, d)):
                skipped.append("/".join(base + [d]) + " (링크)")
            elif d.startswith(".") or d.lower() == "node_modules":      # 숨김·의존성 폴더는 안을 보지 않고 한 줄로만 알린다
                skipped.append("/".join(base + [d]) + "/ (폴더 전체 건너뜀)")
            else:
                keep.append(d)
        dirs[:] = keep
        for n in sorted(names):
            parts = base + [n]
            shown = "/".join(parts)
            full = os.path.join(root, n)
            if parts == ["SKILL.md"]:
                continue
            seen += 1
            if seen > MAX_IMPORT_SCAN:
                skipped.append(shown + " (너무 많음)")
                continue
            try:
                inside = os.path.commonpath([root_real, os.path.normcase(os.path.realpath(full))]) == root_real
                size = os.path.getsize(full)
            except (OSError, ValueError):
                skipped.append(shown)
                continue
            if _is_link(full) or not inside:
                skipped.append(shown + " (링크)")
            elif not _ref_parts_ok(parts):
                skipped.append(shown)
            elif size > MAX_IMPORT_FILE_BYTES:
                skipped.append(shown + " (너무 큼)")
            elif len(take) >= MAX_IMPORT_FILES:
                skipped.append(shown + " (너무 많음)")
            elif total + size > MAX_IMPORT_TOTAL:
                skipped.append(shown + " (합계 초과)")
            else:
                take.append(shown)
                total += size
    return take, skipped


def _shown(skipped):
    if len(skipped) <= MAX_SKIPPED_SHOWN:
        return skipped
    return skipped[:MAX_SKIPPED_SHOWN] + ["… 외 %d개" % (len(skipped) - MAX_SKIPPED_SHOWN)]


def importable():
    """가져올 수 있는 스킬 폴더 목록. SKILL.md가 없는 폴더는 싣지 않는다."""
    out = {"dir": IMPORT_LABEL, "items": []}
    src = import_source_dir()
    try:
        folders = sorted(os.listdir(src))
    except OSError:
        return out
    have = {s["name"] for s in load_all()}
    for folder in folders:
        if folder.startswith("."):
            continue
        path = os.path.join(src, folder)
        md = os.path.join(path, "SKILL.md")
        if not os.path.isdir(path) or not os.path.isfile(md):
            continue
        item = {"folder": folder, "name": "", "description": "", "files": 0, "skipped": [],
                "exists": False, "ok": False, "reason": ""}
        out["items"].append(item)
        if _is_link(path) or _is_link(md):
            item["reason"] = "링크로 연결된 폴더는 가져올 수 없습니다."
            continue
        try:
            if os.path.getsize(md) > MAX_BYTES:
                item["reason"] = "SKILL.md가 너무 큽니다(%dKB 초과)." % (MAX_BYTES // 1000)
                continue
            with open(md, "r", encoding="utf-8-sig") as f:
                parsed = parse_text(f.read(), folder)
        except (OSError, UnicodeDecodeError):
            item["reason"] = "SKILL.md를 글로 읽을 수 없습니다."
            continue
        if parsed is None:
            item["reason"] = "이름이 규칙에 맞지 않습니다. 영문 소문자·숫자·-·_만 쓸 수 있고 40자까지입니다."
            continue
        take, skipped = _plan_import(path)
        item.update(name=parsed["name"], description=parsed["description"], files=len(take),
                    skipped=_shown(skipped), exists=parsed["name"] in have, ok=True)
    return out


def _recover_backups():
    """이전 가져오기가 교체 도중 끊겨 skills/.import-old-<폴더>만 남았으면 원래 자리로 되돌린다.

    원래 폴더가 이미 있으면 새 스킬이 자리 잡은 뒤 지우지 못한 옛 사본이므로 지운다.
    """
    try:
        names = os.listdir(SKILLS_DIR)
    except OSError:
        return
    for n in names:
        if not n.startswith(".import-old-") or len(n) == len(".import-old-"):
            continue
        old, home = os.path.join(SKILLS_DIR, n), os.path.join(SKILLS_DIR, n[len(".import-old-"):])
        try:
            if os.path.lexists(home):
                shutil.rmtree(old, ignore_errors=True)
            else:
                os.replace(old, home)
        except OSError:
            pass


def import_skill(folder, overwrite=False):
    """importable()에 있는 폴더 하나를 skills/로 복사한다. 문제가 있으면 ValueError."""
    _recover_backups()
    item = next((i for i in importable()["items"] if isinstance(folder, str) and i["folder"] == folder), None)
    if item is None:
        raise ValueError("가져올 수 있는 스킬 폴더 목록에 없는 이름입니다.")
    if not item["ok"]:
        raise ValueError(item["reason"])
    name = item["name"]
    existing = {s["name"]: s for s in load_all()}
    if name in existing and not overwrite:
        raise ValueError("같은 이름의 스킬이 이미 있습니다. 덮어쓰려면 확인해 주세요.")
    if name not in existing and len(existing) >= MAX_SKILLS:
        raise ValueError("스킬은 %d개까지 둘 수 있습니다." % MAX_SKILLS)
    target_folder = existing[name]["folder"] if name in existing else name
    target = os.path.join(SKILLS_DIR, target_folder)
    if name not in existing and os.path.lexists(target):
        # 폴더 이름만 같고 다른 스킬이거나 읽지 못하는 초안일 수 있다. 같은 이름의 스킬이 확인된 폴더만 바꾼다.
        raise ValueError("같은 이름의 폴더가 이미 있지만 같은 스킬로 확인되지 않아 건드리지 않았습니다. 그 폴더를 먼저 정리해 주세요.")
    src = os.path.join(import_source_dir(), folder)
    take, skipped = _plan_import(src)
    stage = os.path.join(SKILLS_DIR, ".import-new-" + name)
    backup = os.path.join(SKILLS_DIR, ".import-old-" + target_folder)
    moved = kept = False
    try:
        os.makedirs(SKILLS_DIR, exist_ok=True)
        shutil.rmtree(stage, ignore_errors=True)
        if os.path.getsize(os.path.join(src, "SKILL.md")) > MAX_BYTES:
            raise ValueError("SKILL.md가 너무 큽니다(%dKB 초과)." % (MAX_BYTES // 1000))
        os.makedirs(stage)
        for rel in ["SKILL.md"] + take:
            dst = os.path.join(stage, *rel.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(os.path.join(src, *rel.split("/")), dst)
        if os.path.exists(target):
            os.replace(target, backup)
            moved = True
        os.replace(stage, target)
        moved = False
        shutil.rmtree(backup, ignore_errors=True)       # 새 폴더가 자리 잡은 뒤에만 옛 사본을 지운다
    except ValueError:
        raise
    except OSError:
        if moved:
            try:
                os.replace(backup, target)
            except OSError:
                kept = True                             # 되돌리지 못하면 옛 사본을 지우지 않고 남긴다
        if kept:
            raise ValueError("스킬을 바꾸지 못했습니다. 기존 스킬은 skills 폴더 안 숨김 폴더(.import-old-%s)에 보관했습니다. "
                             "다시 가져오기를 시도하면 자동으로 복구합니다." % target_folder) from None
        raise ValueError("스킬을 복사하지 못했습니다. 폴더 권한이나 디스크를 확인해 주세요.") from None
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return {"name": name, "copied": len(take), "skipped": _shown(skipped)}


# ── 화면에 붙여 넣은 SKILL.md 읽기 ─────────────────────────────────────────

def parse_form(text):
    """붙여 넣은 SKILL.md를 편집 칸에 채울 값으로. 이름이 규칙에 안 맞으면 -로 정리하고, 손댄 곳은 notes에 적는다."""
    if not isinstance(text, str):
        raise ValueError("붙여 넣은 내용이 글이 아닙니다.")
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError("내용이 너무 큽니다(%dKB 초과)." % (MAX_BYTES // 1000))
    meta, body = _frontmatter(text.replace("\r\n", "\n").strip())
    desc = " ".join((meta.get("description", "") + " " + meta.get("when_to_use", "")).split())
    wanted = []
    for t in _tool_names(meta.get("tools", "") + " " + meta.get("allowed-tools", "")):
        if t not in wanted:
            wanted.append(t)
    unsupported = [t for t in wanted if t not in SKILL_TOOLS]
    body = body.strip()
    notes = []
    if len(desc) > MAX_DESCRIPTION:
        notes.append("설명이 %d자라 %d자로 줄였습니다. 언제 쓰는지가 남도록 다듬어 주세요." % (len(desc), MAX_DESCRIPTION))
    if unsupported:
        notes.append("이 앱에서 쓸 수 없는 도구는 뺐습니다: %s" % ", ".join(unsupported)[:80])
    if _CLAUDE_ONLY.search(body):
        notes.append("지침에 Claude Code 전용 내용(bun, Artifact, 음성 알림 등)이 있습니다. 이 앱에는 없으니 지우거나 바꿔 주세요.")
    name = re.sub(r"[^a-z0-9_-]+", "-", (meta.get("name") or "").lower()).strip("-_")[:40]
    return {"name": name, "description": desc[:MAX_DESCRIPTION], "tools": [t for t in wanted if t in SKILL_TOOLS],
            "body": body, "notes": notes}


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
        out = {"스킬": skill["name"], "지침": skill["body"]}
        if skill["files"]:
            out["참고 파일"] = skill["files"]
            out["안내"] = "참고 파일은 read_skill_file(skill, path)로 읽는다."
        return out

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
    with_files = sorted(s["name"] for s in skills if s["files"])
    if with_files:
        def read_skill_file(args):
            args = args if isinstance(args, dict) else {}
            if args.get("skill") not in with_files:     # 모델에게 보이지 않는 스킬의 파일은 읽지 않는다
                return {"오류": "그런 스킬은 없거나 참고 파일이 없습니다.", "참고 파일이 있는 스킬": with_files}
            return read_file(args["skill"], args.get("path"))

        out.append({
            "name": "read_skill_file",
            "description": "스킬 폴더의 참고 파일을 읽는다. use_skill 결과의 '참고 파일' 목록에 있는 경로만 쓴다.",
            "parameters": {"type": "object",
                           "properties": {"skill": {"type": "string", "enum": with_files, "description": "스킬 이름"},
                                          "path": {"type": "string", "description": "참고 파일 경로(예: references/a.md)"}},
                           "required": ["skill", "path"]},
            "source": SOURCE,
            "call": read_skill_file,
        })
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
