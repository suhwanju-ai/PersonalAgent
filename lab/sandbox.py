# -*- coding: utf-8 -*-
"""Disabled Python runner.

Import filtering and subprocess timeouts do not isolate untrusted Python from
the current Windows user. Keep this compatibility module fail-closed until an
OS-level sandbox is configured.
"""

DISABLED_MESSAGE = (
    "코드 실행은 현재 비활성화되어 있습니다. 사용자 파일과 시스템을 보호할 수 있는 "
    "OS 수준 격리 실행기가 구성된 뒤에 사용할 수 있습니다."
)


def run(code, cwd=None):
    return {"ok": False, "output": "", "error": DISABLED_MESSAGE}


def tool_run_python(code=""):
    return {"오류": DISABLED_MESSAGE, "출력": ""}


TOOL = {
    "name": "run_python",
    "description": DISABLED_MESSAGE,
    "parameters": {
        "type": "object",
        "properties": {"code": {"type": "string", "description": "실행할 파이썬 코드"}},
        "required": ["code"],
    },
    "function": tool_run_python,
    "source": "내장",
}
