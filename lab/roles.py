# -*- coding: utf-8 -*-
"""세 에이전트의 역할과 도구.

역할의 경계는 아래 지시문으로, 도구의 경계는 코드로 나눈다.
조사 담당은 실행 도구를 아예 볼 수 없고, 실행 담당은 조사 도구를 볼 수 없다.
"""

import json
import os
import threading

from . import config

ROLE_PROMPT_MAX_CHARS = 20000
_PROMPT_WRITE_LOCK = threading.Lock()

ORCHESTRATOR_PROMPT = """너는 연구책임자다. 두 명의 연구원에게 일을 맡겨 연구를 진행한다.

- 자료조사 연구원 — 이 문제를 어떻게 분석할지 방법을 설계한다.
- 실험수행 연구원 — 코드를 짜서 돌리고, 나온 수치를 돌려준다.

- 너는 직접 조사하거나 코드를 짜지 않는다. 반드시 연구원에게 맡긴다.
- 한 번에 한 명에게 맡기고, 돌아온 결과를 보고 다음에 무엇을 할지 정한다.
- 맡길 때는 무엇을 해야 하는지 구체적으로 적는다. 연구원은 네가 준 지시문만 본다.
- 두 연구원은 서로의 결과를 모른다. 필요한 내용은 네가 지시문에 담아 전달한다.

- **최종 정량 결과는 실제 실행된 코드의 결과만 사용한다.**
  현재 격리 실행기가 없어 실험 담당이 코드를 실행할 수 없으면 숫자를 추정하지 말고 실행 불가를 알린다.

- **돌아온 수치를 검토한다.** 서로 어긋나는 수치 — 예를 들어 상관계수가 모두 0 근처이거나,
  적자 확률이 하위 5% 와 맞지 않거나(하위 5% 가 0 근처면 적자 확률도 5% 근처여야 한다),
  조건을 불리하게 바꿨는데 결과가 좋아진 것 — 는 그대로 쓰지 않고 실험 담당에게 확인을 맡긴다.

- **사업 가정의 수치를 지어내지 않는다.** 주어진 자료 파일에 적힌 값만 쓴다.
  파일을 읽을 수 있는 것은 실험 담당뿐이다. 값이 필요하면 실험 담당에게
  파일을 읽어 알려 달라고 맡긴다.

- 보고는 중앙값·하위 5%·상위 5%·민감도 순위까지다.
  추진 여부나 사업성 판단을 쓰지 않는다.
- 한국어로 쓴다."""

RESEARCH_PROMPT = """너는 이 문제를 어떻게 분석할지 설계한다.

- 어떤 변수를 확률변수로 둘 것인가
- 주어진 형태에 맞는 분포는 무엇인가
- 시행 횟수는 얼마로 하고, 수렴은 어떻게 확인하는가
- 결과를 무엇으로 요약하는가
- 민감도는 어떻게 보는가

- 분석 방법과 가정은 OpenRouter 웹 검색 또는 연결된 MCP 검색 도구로 확인한다.
  사용할 검색 도구가 없으면 확인할 수 없다고 밝힌다.
- 방법의 이름과 가정을 함께 적고, 무엇을 어디서 확인했는지 밝힌다.
- 코드를 짜거나 실행하지 않는다. 그것은 실험 담당의 일이다.
- **너는 수치를 산출하지 않는다.** 기댓값·평균 등을 직접 계산해 적지 않는다.
  실험 담당도 격리 실행기가 없으면 코드를 실행할 수 없으므로 필요한 수치를 만들 수 없다고 보고할 수 있다.
- 한국어로 간결하게 정리해 돌려준다."""

EXPERIMENT_PROMPT = """너는 실험수행 연구원이다.

- 받은 지시를 자료 파일로 확인할 수 있는 범위에서 분석한다.
- 코드 실행 도구는 격리 실행기가 마련될 때까지 제공되지 않는다.
- 실행하지 않은 계산 결과를 만들어 내지 말고, 정량 결과가 필요하면 실행할 코드와 필요한 입력을 보고한다.
- 수치를 그대로 보고한다. 그것이 무엇을 뜻하는지 결론짓지 않는다. 해석은 다른 사람의 일이다.
- 한국어로 간결하게 돌려준다."""

ROLES = {
    "research": {
        "label": "자료조사 연구원",
        "port": config.RESEARCH_PORT,
        "prompt": RESEARCH_PROMPT,
        "web_search": True,      # 내장 웹 검색을 쓴다
        "tools": "mcp",          # 연결된 MCP 서버의 도구를 물려받는다
        "script": "research_agent.py",
    },
    "experiment": {
        "label": "실험수행 연구원",
        "port": config.EXPERIMENT_PORT,
        "prompt": EXPERIMENT_PROMPT,
        "web_search": False,
        "tools": "data",         # 연구 자료 파일만. 격리 실행기 도입 전 코드 실행 금지
        "script": "experiment_agent.py",
    },
}

ORDER = ["research", "experiment"]


# ── 화면에서 고친 연구원 지침 ─────────────────────────────────────────
# 연구원은 별도 프로세스라 모듈 상수를 바꿔도 닿지 않는다. 파일에 남기고
# 연구원이 작업을 받을 때마다 읽어 가므로, 저장하면 다음 위임부터 적용된다(재시작 불필요).

def _read_overrides():
    try:
        with open(config.ROLE_PROMPTS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def prompt_for(role_name):
    """그 역할이 지금 따르는 지침. 고친 값이 있으면 그것을, 없으면 기본 지침을 돌려준다."""
    text = _read_overrides().get(role_name)
    if isinstance(text, str) and text.strip():
        return text
    return ROLES[role_name]["prompt"]


def prompts_view():
    """화면에 보여 줄 역할별 지침. 기본 지침도 함께 실어 '되돌리기'를 비교할 수 있게 한다."""
    overrides = _read_overrides()
    out = []
    for name in ORDER:
        role = ROLES[name]
        edited = isinstance(overrides.get(name), str) and bool(overrides[name].strip())
        out.append({"role": name, "label": role["label"], "prompt": prompt_for(name),
                    "default": role["prompt"], "edited": edited})
    return out


def _write_overrides(data):
    os.makedirs(config.STATE_DIR, exist_ok=True)
    temp_path = config.ROLE_PROMPTS_PATH + ".tmp"
    if data:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(temp_path, config.ROLE_PROMPTS_PATH)
    elif os.path.exists(config.ROLE_PROMPTS_PATH):
        os.remove(config.ROLE_PROMPTS_PATH)


def set_prompt(role_name, text):
    """지침을 저장한다. 비었거나 기본 지침과 같으면 고친 값을 지워 기본으로 돌린다."""
    if not isinstance(role_name, str) or role_name not in ROLES:
        raise ValueError("그런 역할이 없습니다.")
    if not isinstance(text, str):
        raise ValueError("지침을 문자열로 보내 주세요.")
    text = text.replace("\r\n", "\n").strip()
    if len(text) > ROLE_PROMPT_MAX_CHARS:
        raise ValueError("지침은 %d자를 넘을 수 없습니다." % ROLE_PROMPT_MAX_CHARS)
    with _PROMPT_WRITE_LOCK:
        data = _read_overrides()
        if not text or text == ROLES[role_name]["prompt"].strip():
            data.pop(role_name, None)
        else:
            data[role_name] = text
        _write_overrides(data)


def clear_prompt(role_name):
    set_prompt(role_name, "")


def tools_for(role_name):
    """그 역할이 볼 수 있는 도구만 돌려준다.

    조사 담당은 연결된 MCP 서버의 도구를, 실험 담당은 연구 자료 읽기만 본다.
    격리 실행기가 마련되기 전까지 Python 실행 도구는 제공하지 않는다.
    내장 메모 도구는 어느 쪽에도 주지 않는다.
    """
    from . import datafile, registry

    role = ROLES[role_name]
    if role["tools"] == "data":
        tool = datafile.TOOL
        return [{
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["parameters"],
            "source": "내장",
            "call": (lambda f: (lambda args: f(**args)))(tool["function"]),
        }], []

    entries, errors = registry.build()
    return [e for e in entries if e["source"] != "내장"], errors
