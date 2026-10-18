# -*- coding: utf-8 -*-
"""이 앱이 AI에게 제공하는 내장 도구 — 메모 파일 하나를 검색·저장·삭제·수정한다.

이름은 `memo_tool_1/2/3/4`다. 검색·저장·삭제의 파라미터는 `text` 하나이고,
수정(4)만 `target`·`find`·`replace` 셋을 받는다.
설명문은 화면에서 고칠 수 있다. 여기 적힌 것은 기본값이며,
화면에서 고친 값은 state/tool_overrides.json에 저장되어 이 값 위에 덮인다.
"""

import json
import os

from . import config


# ── 메모 파일 읽고 쓰기 ───────────────────────────────────────────────

def _load():
    path = config.notes_path()
    if not os.path.exists(path):
        raise IOError("메모 파일을 찾을 수 없습니다: %s" % path)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(notes):
    path = config.notes_path()
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        raise IOError("저장할 폴더가 없습니다: %s" % directory)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(notes, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _matches(note, text):
    """낱말 단위 일치. "회의 메모"처럼 두 낱말이 와도 "회의"가 든 메모가 잡힌다.

    부분 문자열 일치("회의 메모" in "주간 회의 정리")로 두면 0건이 된다.
    """
    words = (text or "").split()
    if not words:
        return True
    hay = note.get("title", "") + " " + note.get("body", "")
    return any(w in hay for w in words)


def read_notes():
    """화면에 메모 목록을 보여주기 위한 함수. AI에게 주는 도구가 아니다."""
    try:
        return _load()
    except (IOError, ValueError):
        return []


def reset_notes():
    """seed 원본으로 되돌린다. 화면의 초기화 버튼이 부른다."""
    with open(config.SEED_NOTES_PATH, "r", encoding="utf-8") as f:
        seed = json.load(f)
    os.makedirs(os.path.dirname(config.NOTES_PATH), exist_ok=True)
    with open(config.NOTES_PATH, "w", encoding="utf-8") as f:
        json.dump(seed, f, ensure_ascii=False, indent=2)
        f.write("\n")
    if os.path.exists(config.DATA_PATH_OVERRIDE):
        os.remove(config.DATA_PATH_OVERRIDE)
    return len(seed)


# ── 도구 함수 ─────────────────────────────────────────────────────────

def note_search(text=""):
    notes = _load()
    found = [n for n in notes if _matches(n, text)]
    return {
        "찾은 메모": [{"제목": n.get("title", ""), "내용": n.get("body", ""),
                    "날짜": n.get("date", "")} for n in found],
        "찾은 건수": len(found),
    }


def note_save(text=""):
    body = (text or "").strip()
    if not body:
        return {"오류": "저장할 내용이 비어 있습니다."}
    notes = _load()
    title = body.split("\n")[0][:30]
    notes.append({"title": title, "body": body, "date": ""})
    _save(notes)
    return {"저장한 제목": title, "전체 건수": len(notes)}


def note_delete(text=""):
    text = (text or "").strip()
    if not text:
        return {"오류": "삭제 키워드가 비어 있습니다."}
    notes = _load()
    hit = [n for n in notes if _matches(n, text)]
    kept = [n for n in notes if not _matches(n, text)]
    _save(kept)
    return {"지운 메모": [n.get("title", "") for n in hit],
            "지운 건수": len(hit), "남은 건수": len(kept)}


def note_update(target="", find="", replace=""):
    """메모 하나를 골라 본문의 한 곳만 바꾼다. 나머지 본문은 그대로 둔다.

    대상이 여럿이거나 바꿀 문장이 여러 번 나오면 고치지 않고 되돌려 보낸다.
    삭제처럼 걸린 것을 모두 고치면 여러 메모가 한꺼번에 덮인다.
    """
    target = (target or "").strip()
    if not target:
        return {"오류": "고칠 메모의 제목이나 키워드가 비어 있습니다."}
    if not find:
        return {"오류": "바꿀 문장이 비어 있습니다."}

    notes = _load()
    # 제목이 정확히 같은 메모를 먼저 본다. 없을 때만 낱말 일치로 찾는다.
    hit = [n for n in notes if n.get("title", "") == target]
    if not hit:
        hit = [n for n in notes if _matches(n, target)]
    if not hit:
        return {"오류": "해당하는 메모가 없습니다."}
    if len(hit) > 1:
        return {"오류": "여러 메모가 해당합니다. 제목으로 다시 지정해 주세요.",
                "후보": [n.get("title", "") for n in hit]}

    note = hit[0]
    body = note.get("body", "")
    count = body.count(find)
    if count == 0:
        return {"오류": "메모에 그 문장이 없습니다.", "현재 내용": body}
    if count > 1:
        return {"오류": "그 문장이 %d번 나옵니다. 앞뒤 문장을 더 넣어 한 곳만 가리켜 주세요." % count,
                "현재 내용": body}

    note["body"] = body.replace(find, replace, 1)
    _save(notes)
    return {"수정한 제목": note.get("title", ""), "이전 내용": body, "새 내용": note["body"]}


# ── 도구 목록 ─────────────────────────────────────────────────────────
# 1~3의 parameters는 동일하다.

_TEXT_PARAM = {
    "type": "object",
    "properties": {"text": {"type": "string", "description": "입력 문자열"}},
    "required": ["text"],
}

# 수정 도구만 인자가 셋이다. 어느 메모의 어느 문장을 무엇으로 바꿀지 나눠 받는다.
_UPDATE_PARAM = {
    "type": "object",
    "properties": {
        "target": {"type": "string", "description": "고칠 메모의 제목 또는 키워드"},
        "find": {"type": "string", "description": "본문에서 바꿀 문장 (본문에 있는 그대로)"},
        "replace": {"type": "string", "description": "바꿔 넣을 문장"},
    },
    "required": ["target", "find", "replace"],
}

TOOLS = [
    {
        "name": "memo_tool_1",
        "description": "저장된 메모 중 키워드에 해당하는 것을 찾아 목록으로 보여준다.",
        "parameters": _TEXT_PARAM,
        "function": note_search,
    },
    {
        "name": "memo_tool_2",
        "description": "새 메모를 저장한다. 이미 있는 메모의 내용이 바뀌었다는 말(변경·수정·바뀌었다)이면 "
                       "이 도구로 새로 저장하지 말고 memo_tool_4로 기존 메모를 고친다.",
        "parameters": _TEXT_PARAM,
        "function": note_save,
    },
    {
        "name": "memo_tool_3",
        "description": "키워드에 해당하는 메모를 삭제한다. 되돌릴 수 없다.",
        "parameters": _TEXT_PARAM,
        "function": note_delete,
    },
    {
        "name": "memo_tool_4",
        "description": "이미 있는 메모의 내용이 바뀌었다는 말(변경·수정·바뀌었다)이면 새로 저장하지 말고 "
                       "이 도구로 기존 메모를 고친다. find는 본문에 있는 그대로 적어야 하므로 "
                       "먼저 memo_tool_1로 관련 메모를 찾아 제목과 본문을 확인한 뒤 호출한다. "
                       "제목이나 키워드(target)로 메모 하나를 골라 본문에서 find 문장을 replace로 바꾸고 "
                       "나머지 본문은 그대로 둔다. 메모가 여럿 해당하거나 find가 없거나 여러 번 나오면 "
                       "고치지 않고 후보 제목이나 현재 내용을 돌려준다.",
        "parameters": _UPDATE_PARAM,
        "function": note_update,
    },
]
