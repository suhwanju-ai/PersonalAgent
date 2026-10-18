# -*- coding: utf-8 -*-
"""앱 전역 설정과 경로. API 키는 화면·로그·오류 메시지에 노출하지 않는다."""

import os

# ── 경로 ──────────────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = os.path.join(ROOT, "data")
NOTES_PATH = os.path.join(DATA_DIR, "notes.json")
SEED_NOTES_PATH = os.path.join(DATA_DIR, "seed", "notes.json")

# 연구 자료. 메모 파일과 폴더를 나눈다.
# 한 폴더에 두면 실험 담당이 notes.json까지 열어 보느라 로그가 지저분해진다.
RESEARCH_DIR = os.path.join(DATA_DIR, "research")

STATE_DIR = os.path.join(ROOT, "state")
TOOL_OVERRIDES_PATH = os.path.join(STATE_DIR, "tool_overrides.json")
SYSTEM_PROMPT_PATH = os.path.join(STATE_DIR, "system_prompt.txt")
DATA_PATH_OVERRIDE = os.path.join(STATE_DIR, "data_path.txt")
# 화면에서 주소로 추가한 MCP 서버. 기본 목록(mcp_catalog.json)은 고치지 않고 여기에 따로 둔다.
MCP_CUSTOM_PATH = os.path.join(STATE_DIR, "mcp_custom.json")
# 도구 탭 대화 기록. 요청·응답·도구 호출·결과를 남겨 다음 요청에 이어 넘긴다.
CHAT_HISTORY_PATH = os.path.join(STATE_DIR, "chat_history.json")
CHAT_MAX_TURNS = 30                      # 이보다 오래된 대화는 앞에서부터 잊는다. 매 요청에 전부 실려 가므로 상한을 둔다


def notes_path():
    """메모 파일 경로. 화면에서 바꿀 수 있다.

    경로가 잘못되어도 앱이 죽지 않고 도구만 오류를 돌려주어야 한다.
    """
    if os.path.exists(DATA_PATH_OVERRIDE):
        try:
            with open(DATA_PATH_OVERRIDE, "r", encoding="utf-8") as f:
                value = f.read().strip()
            if value:
                return value
        except OSError:
            pass
    return NOTES_PATH

MCP_CONFIG_PATH = os.path.join(ROOT, "mcp_config.json")
AGENTS_DIR = os.path.join(ROOT, "agents")

# ── OpenRouter ────────────────────────────────────────────────────────
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
GEN_MODEL = os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")
CONTEXT_WINDOW_TOKENS = int(os.environ.get("OPENROUTER_CONTEXT_WINDOW_TOKENS", "128000"))
REASONING_EFFORT = "none"
TEMPERATURE = 0.0
MAX_TOOL_STEPS = 6                       # 한 요청에서 도구 호출을 반복할 최대 횟수
ORCH_MAX_STEPS = 10                      # 연구책임자는 여러 번 위임하므로 더 준다
AGENT_MAX_STEPS = 10                     # 연구원은 자료를 읽고 코드를 고쳐 가며 쓴다.
                                         # 6이면 파일 읽기 몇 번에 소진된다

# ── 서버 ──────────────────────────────────────────────────────────────
HOST = "127.0.0.1"
PORT = 8770                              # rag-lab(8765) · tool-lab(8766)과 겹치지 않게
RESEARCH_PORT = 8771
EXPERIMENT_PORT = 8772

def load_env():
    """앱 폴더의 .env를 읽어 os.environ에 넣는다 (이미 있는 값은 유지)."""
    path = os.path.join(ROOT, ".env")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def api_key():
    """OPENROUTER_API_KEY를 반환한다. 없으면 예외. 값은 절대 밖으로 내보내지 않는다."""
    load_env()
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise RuntimeError("NO_API_KEY")
    return key
