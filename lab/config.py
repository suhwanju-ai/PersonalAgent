# -*- coding: utf-8 -*-
"""앱 전역 설정과 경로. API 키는 화면·로그·오류 메시지에 노출하지 않는다."""

import functools
import ipaddress
import os
import json
import math
import urllib.parse

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
# 화면에서 고친 연구원 지침. {역할 이름: 지침}. 없는 역할은 roles.py의 기본 지침을 쓴다.
ROLE_PROMPTS_PATH = os.path.join(STATE_DIR, "role_prompts.json")
DATA_PATH_OVERRIDE = os.path.join(STATE_DIR, "data_path.txt")
# 화면에서 주소로 추가한 MCP 서버. 기본 목록(mcp_catalog.json)은 고치지 않고 여기에 따로 둔다.
MCP_CUSTOM_PATH = os.path.join(STATE_DIR, "mcp_custom.json")
# 도구 탭 대화 기록. 요청·응답·도구 호출·결과를 남겨 다음 요청에 이어 넘긴다.
CHAT_HISTORY_PATH = os.path.join(STATE_DIR, "chat_history.json")
CHAT_MAX_TURNS = 30                      # 이보다 오래된 대화는 앞에서부터 잊는다. 매 요청에 전부 실려 가므로 상한을 둔다
LLM_SETTINGS_PATH = os.path.join(STATE_DIR, "llm_settings.json")


@functools.lru_cache(maxsize=None)
def trusted_origins():
    """Deployment origins allowed to reach the local web UI and JSON endpoints.

    .env는 시작할 때 한 번만 읽히므로 결과도 한 번만 계산한다(바꾸려면 재시작).
    """
    load_env()
    origins = []
    for raw in os.environ.get("APP_TRUSTED_ORIGINS", "").split(","):
        raw_origin = raw.strip().rstrip("/")
        if not raw_origin:
            continue
        try:
            parsed = urllib.parse.urlsplit(raw_origin)
            port = parsed.port
        except ValueError:
            continue
        if (parsed.scheme.lower() not in ("http", "https") or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path or any(char.isspace() for char in raw_origin)):
            continue
        host = parsed.hostname.lower()
        if ":" in host:
            host = "[%s]" % host
        scheme = parsed.scheme.lower()
        default_port = 443 if scheme == "https" else 80
        if port is not None and port != default_port:
            host += ":%d" % port
        origins.append(("%s://%s" % (scheme, host), host))
    return tuple(origins)


def access_token():
    """신뢰 origin(외부 노출)으로 접속할 때 Basic 인증 비밀번호로 쓰는 값."""
    load_env()
    return os.environ.get("APP_ACCESS_TOKEN", "").strip()


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


DOTENV_KEYS = set()          # .env에서 읽어 온 변수 이름. stdio MCP 서버에는 넘기지 않는다.


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
            if key:
                DOTENV_KEYS.add(key)            # 부모가 이미 넘겨 준 값이어도 .env 출신으로 표시한다
                if key not in os.environ:
                    os.environ[key] = value


load_env()

# ── OpenRouter ────────────────────────────────────────────────────────
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
GEN_MODEL = os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")
OLLAMA_BASE_DEFAULT = "http://localhost:11434/v1"
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

def is_link_local_host(hostname):
    """호스트가 링크로컬 IP 리터럴(169.254.x.x, fe80::)인지. 호스트 이름은 검사하지 않는다."""
    try:
        return ipaddress.ip_address(hostname).is_link_local
    except ValueError:
        return False


def _normalize_base_url(value, label):
    """OpenAI 호환 서버 주소를 검증하고 /v1 경로를 붙여 돌려준다. label은 오류 문구에 쓴다."""
    if not isinstance(value, str):
        raise ValueError(f"{label} 주소를 문자열로 입력해 주세요.")
    value = (value or "").strip().rstrip("/")
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or any(ord(char) <= 32 for char in value)):
        raise ValueError(f"{label} 주소는 사용자 정보·쿼리 없이 http(s)://호스트/v1 형식으로 입력해 주세요.")
    try:
        parsed.port
    except ValueError:
        raise ValueError(f"{label} 주소의 포트 번호가 올바르지 않습니다.")
    if is_link_local_host(parsed.hostname):
        # 클라우드 메타데이터(169.254.169.254 등)로 요청이 나가지 않게 막는다.
        raise ValueError(f"링크로컬 주소는 {label} 주소로 쓸 수 없습니다.")
    if not parsed.path or parsed.path == "/":
        value += "/v1"
    return value


PROVIDERS = ("openrouter", "ollama", "modeldock")
MODELDOCK_CONTEXT_MIN = 512
MODELDOCK_CONTEXT_MAX = 2000000

_LLM_CACHE = {"stamp": None, "settings": None}


def modeldock_key():
    """MODELDOCK_API_KEY의 앞뒤 공백을 지운 값. 없으면 빈 문자열. 값은 밖으로 내보내지 않는다."""
    # load_env()는 import 때와 설정을 읽을 때 이미 불렸다. 여기서는 .env를 다시 열지 않는다.
    return os.environ.get("MODELDOCK_API_KEY", "").strip()


def _parse_context_tokens(value):
    """0(기본값 사용) 또는 512~2000000 정수. 문자열 숫자는 허용, bool은 거부한다."""
    if isinstance(value, bool):
        raise ValueError("ModelDock 컨텍스트 크기는 숫자로 입력해 주세요.")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("ModelDock 컨텍스트 크기는 유한한 숫자로 입력해 주세요.")
    try:
        number = int(value.strip()) if isinstance(value, str) else int(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("ModelDock 컨텍스트 크기는 숫자로 입력해 주세요.")
    if isinstance(value, float) and value != number:
        raise ValueError("ModelDock 컨텍스트 크기는 정수로 입력해 주세요.")
    if number != 0 and not MODELDOCK_CONTEXT_MIN <= number <= MODELDOCK_CONTEXT_MAX:
        raise ValueError(f"ModelDock 컨텍스트 크기는 0 또는 {MODELDOCK_CONTEXT_MIN}~{MODELDOCK_CONTEXT_MAX} 사이로 입력해 주세요.")
    return number


def llm_settings():
    """현재 모델 제공자 설정을 반환한다. 키와 비밀값은 포함하지 않는다.

    요청마다 여러 번 불리므로 설정 파일의 mtime이 같으면 이전 결과를 재사용한다.
    modeldock_key_set은 환경변수에서 오므로 캐시 밖에서 매번 계산한다.
    """
    try:
        stamp = os.stat(LLM_SETTINGS_PATH).st_mtime_ns
    except OSError:
        stamp = None
    cached = _LLM_CACHE["settings"]     # 한 번만 읽는다: 다른 스레드의 저장이 사이에 None으로 바꿀 수 있다
    if cached is None or _LLM_CACHE["stamp"] != stamp:
        cached = _read_llm_settings()
        _LLM_CACHE["stamp"], _LLM_CACHE["settings"] = stamp, cached
    settings = dict(cached)
    settings["modeldock_key_set"] = bool(modeldock_key())
    return settings


def context_window_tokens():
    """현재 제공자의 컨텍스트 창 크기. ModelDock에 직접 지정한 값이 있으면 그것을 쓴다."""
    settings = llm_settings()
    if settings["provider"] == "modeldock" and settings["modeldock_context_tokens"] > 0:
        return settings["modeldock_context_tokens"]
    return CONTEXT_WINDOW_TOKENS


def _read_llm_settings():
    load_env()
    settings = {
        "provider": "openrouter",
        "openrouter_model": os.environ.get("OPENROUTER_MODEL", GEN_MODEL).strip() or GEN_MODEL,
        "ollama_model": "",
        "ollama_base_url": OLLAMA_BASE_DEFAULT,
        "modeldock_model": "",
        "modeldock_base_url": "",
        "modeldock_context_tokens": 0,
    }
    try:
        with open(LLM_SETTINGS_PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        saved = {}
    if isinstance(saved, dict):
        provider = saved.get("provider")
        if provider in PROVIDERS:
            settings["provider"] = provider
        legacy_model = saved.get("model")
        if isinstance(legacy_model, str) and legacy_model.strip():
            settings[settings["provider"] + "_model"] = legacy_model.strip()
        for key in ("openrouter_model", "ollama_model", "modeldock_model"):
            model = saved.get(key)
            if isinstance(model, str) and model.strip():
                settings[key] = model.strip()
        for key, label in (("ollama_base_url", "Ollama"), ("modeldock_base_url", "ModelDock")):
            base_url = saved.get(key)
            if isinstance(base_url, str) and base_url.strip():
                try:
                    settings[key] = _normalize_base_url(base_url, label)
                except ValueError:
                    pass
        try:
            settings["modeldock_context_tokens"] = _parse_context_tokens(saved.get("modeldock_context_tokens", 0))
        except ValueError:
            pass
    settings["model"] = settings[settings["provider"] + "_model"]
    return settings


def save_llm_settings(payload):
    if not isinstance(payload, dict):
        raise ValueError("설정 형식이 올바르지 않습니다.")
    raw_provider = payload.get("provider")
    if not isinstance(raw_provider, str):
        raise ValueError("모델 제공자를 선택해 주세요.")
    provider = raw_provider.strip().lower()
    if provider not in PROVIDERS:
        raise ValueError("지원하지 않는 모델 제공자입니다.")
    raw_model = payload.get("model")
    if not isinstance(raw_model, str):
        raise ValueError("모델 이름을 입력해 주세요.")
    model = raw_model.strip()
    if not model or len(model) > 160:
        raise ValueError("모델 이름을 1~160자로 입력해 주세요.")
    models = {name: payload.get(name + "_model", "") for name in PROVIDERS}
    if not all(isinstance(value, str) for value in models.values()):
        raise ValueError("모델 이름 형식이 올바르지 않습니다.")
    models = {name: value.strip() for name, value in models.items()}
    models[provider] = model
    if any(len(value) > 160 for value in models.values()):
        raise ValueError("모델 이름은 160자를 넘을 수 없습니다.")
    base_url = _normalize_base_url(payload.get("ollama_base_url") or OLLAMA_BASE_DEFAULT, "Ollama")
    raw_modeldock_url = payload.get("modeldock_base_url") or ""
    if provider == "modeldock" and not (isinstance(raw_modeldock_url, str) and raw_modeldock_url.strip()):
        raise ValueError("ModelDock 주소를 입력해 주세요.")
    modeldock_url = _normalize_base_url(raw_modeldock_url, "ModelDock") if raw_modeldock_url else ""
    context_tokens = _parse_context_tokens(payload.get("modeldock_context_tokens", 0))
    saved = {"provider": provider, "model": model,
             "openrouter_model": models["openrouter"], "ollama_model": models["ollama"],
             "ollama_base_url": base_url,
             "modeldock_model": models["modeldock"], "modeldock_base_url": modeldock_url,
             "modeldock_context_tokens": context_tokens}
    os.makedirs(STATE_DIR, exist_ok=True)
    temp_path = LLM_SETTINGS_PATH + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(saved, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(temp_path, LLM_SETTINGS_PATH)
    _LLM_CACHE["settings"] = None
    return saved


def api_key():
    """OPENROUTER_API_KEY를 반환한다. 없으면 예외. 값은 절대 밖으로 내보내지 않는다."""
    load_env()
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise RuntimeError("NO_API_KEY")
    return key
