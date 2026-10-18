# -*- coding: utf-8 -*-
"""AI에게 넘길 도구 목록을 한곳에 모은다.

내장 도구(lab/tools.py) + MCP 서버가 알려준 도구를 같은 형태의 항목으로 합친다.
항목 = {"name", "description", "parameters", "source", "call"(인자 dict -> 결과)}

**설명문은 화면에서 고칠 수 있다.** 고친 값은 state/tool_overrides.json에 남고
여기서 코드의 기본값 위에 덮인다. 파일을 고치거나 앱을 다시 켜지 않아도 된다.
"""

import json
import os

from . import config


def _disabled_mcp_tools():
    path = os.path.join(config.STATE_DIR, "disabled_mcp_tools.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (ValueError, OSError):
        return set()
    return {(item[0], item[1]) for item in data
            if isinstance(item, list) and len(item) == 2
            and all(isinstance(part, str) for part in item)}


def disabled_mcp_tools():
    """화면에서 제외 상태를 표시할 MCP 도구 목록."""
    return [{"source": source, "name": name}
            for source, name in sorted(_disabled_mcp_tools())]


def disable_mcp_tool(source, name):
    """선택한 MCP 도구를 앱의 통합 도구 목록에서 제외한다."""
    disabled = _disabled_mcp_tools()
    disabled.add((source, name))
    path = os.path.join(config.STATE_DIR, "disabled_mcp_tools.json")
    os.makedirs(config.STATE_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted([list(item) for item in disabled]), f, ensure_ascii=False, indent=2)
        f.write("\n")


def restore_mcp_tool(source, name):
    """제외된 MCP 도구를 다시 통합 도구 목록에 포함한다."""
    disabled = _disabled_mcp_tools()
    disabled.discard((source, name))
    path = os.path.join(config.STATE_DIR, "disabled_mcp_tools.json")
    if not disabled:
        if os.path.exists(path):
            os.remove(path)
        return
    os.makedirs(config.STATE_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted([list(item) for item in disabled]), f, ensure_ascii=False, indent=2)
        f.write("\n")


# ── 설명문 덮어쓰기 ───────────────────────────────────────────────────

def overrides():
    """{도구 이름: 설명문}. 화면에서 고친 것만 들어 있다."""
    if not os.path.exists(config.TOOL_OVERRIDES_PATH):
        return {}
    try:
        with open(config.TOOL_OVERRIDES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (ValueError, OSError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, str)}


def set_override(name, description):
    data = overrides()
    data[name] = description
    os.makedirs(config.STATE_DIR, exist_ok=True)
    with open(config.TOOL_OVERRIDES_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def clear_overrides():
    """설명문을 코드의 기본값으로 되돌린다."""
    if os.path.exists(config.TOOL_OVERRIDES_PATH):
        os.remove(config.TOOL_OVERRIDES_PATH)


# ── 도구 모으기 ───────────────────────────────────────────────────────

def _builtin():
    from . import tools as builtin_tools

    edited = overrides()
    entries = []
    for item in builtin_tools.TOOLS:
        func = item["function"]
        name = item["name"]
        entries.append({
            "name": name,
            "description": edited.get(name, item.get("description", "")),
            "default_description": item.get("description", ""),
            "parameters": item.get("parameters") or {"type": "object", "properties": {}},
            "source": "내장",
            "call": (lambda f: (lambda args: f(**args)))(func),
        })
    return entries


def build(include_mcp=True):
    """도구 목록과 사용자에게 보여줄 오류 문구를 함께 돌려준다."""
    entries, errors = [], []

    try:
        entries.extend(_builtin())
    except Exception:                                   # noqa: BLE001
        errors.append("도구 파일을 읽지 못했습니다. 마지막 수정 내용을 확인해 주세요.")

    if include_mcp:
        from . import mcp_client
        mcp_entries, mcp_errors = mcp_client.connect_all(config.MCP_CONFIG_PATH)
        disabled = _disabled_mcp_tools()
        entries.extend(entry for entry in mcp_entries
                       if (entry.get("source", ""), entry.get("name", "")) not in disabled)
        errors.extend(mcp_errors)

    seen, unique = {}, []
    for entry in entries:
        if entry["name"] in seen:
            continue                    # 같은 이름이 겹치면 먼저 등록된 쪽을 남긴다
        seen[entry["name"]] = True
        unique.append(entry)
    return unique, errors


def declarations(entries):
    """모델에 넘길 함수 선언 {name, description, parameters}로 추린다. API 형식은 llm.py가 맞춘다."""
    out = []
    for e in entries:
        params = e.get("parameters") or {"type": "object", "properties": {}}
        if not params.get("properties"):
            params = {"type": "object", "properties": {}}
        out.append({"name": e["name"],
                    "description": e.get("description", ""),
                    "parameters": params})
    return out


def find(entries, name):
    for e in entries:
        if e["name"] == name:
            return e
    return None


def subset(entries, names):
    """이름 목록으로 걸러 낸다. 에이전트마다 다른 도구를 주는 데 쓴다."""
    wanted = set(names)
    return [e for e in entries if e["name"] in wanted]
