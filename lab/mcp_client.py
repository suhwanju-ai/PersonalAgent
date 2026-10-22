# -*- coding: utf-8 -*-
"""MCP 클라이언트 — mcp_config.json에 적힌 서버에 연결해 도구 목록을 받아 온다.

두 가지 연결 방식을 지원한다.
  - 로컬 stdio : {"command": "python", "args": ["...server.py"]}
  - 원격 HTTP  : {"url": "https://..."}   (Streamable HTTP)

설정 값에 `${API_KEY}`처럼 적으면 연결할 때 .env의 값으로 채운다.
키를 설정 파일에 적지 않기 위한 처리다 (expand_env 참고).

설정은 앱을 다시 실행할 때 반영된다. 한 서버가 실패해도 나머지는 그대로 쓴다.
파이썬 표준 라이브러리만 사용한다.
"""

import json
import os
import queue
import re
import subprocess
import sys
import threading
import urllib.error
import urllib.request

from . import config

PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "tool-lab", "version": "1.0"}
RESULT_LIMIT = 12000         # 도구 결과가 너무 길면 잘라서 넘긴다

_CACHE = {"entries": None, "errors": None, "servers": []}
LAUNCH_LOG = []              # 어떤 서버를 어떤 실행 파일로 띄웠는지 (기동 로그용)


# ── 설정 속 ${VAR} 치환 ───────────────────────────────────────────────
# 키가 필요한 원격 서버가 있다. 그 값을 설정 파일에 적으면 카탈로그에도
# mcp_config.json에도 그대로 남는다. 그래서 파일에는 ${API_KEY} 같은
# 자리표시자만 두고, 연결하는 순간에만 .env의 값으로 채운다.
# 채운 주소는 메모리에만 있고 어디에도 기록하지 않는다.

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class MissingEnv(Exception):
    """자리표시자에 해당하는 값이 .env에 없다. 메시지에는 이름만 담는다."""


def expand_env(value):
    """문자열 안의 ${VAR}를 환경 변수 값으로 바꾼다. 값이 없으면 MissingEnv."""
    if not isinstance(value, str) or "${" not in value:
        return value
    missing = []

    def replace(match):
        name = match.group(1)
        found = os.environ.get(name, "").strip()
        if not found:
            missing.append(name)
            return ""
        return found

    filled = _ENV_PATTERN.sub(replace, value)
    if missing:
        raise MissingEnv(", ".join(sorted(set(missing))))
    return filled


# ── 로컬 stdio 서버 ───────────────────────────────────────────────────

class StdioServer(object):
    def __init__(self, name, command, args, cwd, env=None):
        self.name = name
        self._next_id = 0
        self._queue = queue.Queue()
        self._lock = threading.Lock()

        argv = [_resolve_command(command)] + [_resolve_path(a, cwd) for a in args]
        self.executable = argv[0]
        kwargs = {
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.DEVNULL,
            "cwd": cwd,
            "env": _child_env(env),
        }
        if os.name == "nt":
            kwargs["creationflags"] = 0x08000000        # CREATE_NO_WINDOW
        self._proc = subprocess.Popen(argv, **kwargs)

        self._reader = threading.Thread(target=self._read_loop)
        self._reader.daemon = True
        self._reader.start()

    def _read_loop(self):
        try:
            for raw in self._proc.stdout:
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    self._queue.put(json.loads(line))
                except ValueError:
                    continue                            # JSON이 아닌 출력은 버린다
        except Exception:
            pass

    def _send(self, message):
        data = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
        self._proc.stdin.write(data)
        self._proc.stdin.flush()

    def request(self, method, params, timeout=20):
        with self._lock:
            return self._request(method, params, timeout)

    def _request(self, method, params, timeout):
        self._next_id += 1
        message_id = self._next_id
        self._send({"jsonrpc": "2.0", "id": message_id, "method": method, "params": params})
        waited = 0.0
        while waited < timeout:
            try:
                message = self._queue.get(timeout=0.5)
            except queue.Empty:
                waited += 0.5
                if self._proc.poll() is not None:
                    raise IOError("서버가 종료되었습니다.")
                continue
            if message.get("id") == message_id:
                if "error" in message:
                    raise IOError(str(message["error"])[:200])
                return message.get("result") or {}
        raise IOError("응답이 없습니다.")

    def notify(self, method, params):
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def close(self):
        try:
            self._proc.terminate()
        except Exception:
            pass


def _resolve_command(command):
    """설정의 python / python3는 지금 앱을 실행 중인 파이썬으로 해석한다.

    (설정 파일 본문은 그대로 두고, py 런처만 있는 PC에서도 서버가 뜨게 한다.)
    """
    base = os.path.basename(command).lower()
    if base in ("python", "python3", "python.exe", "python3.exe", "py", "py.exe"):
        return sys.executable
    return command


def _resolve_path(value, cwd):
    """설정의 상대 경로는 앱 실행 폴더 기준으로 푼다 (절대 경로를 쓰지 않기 위한 처리)."""
    if isinstance(value, str) and value.endswith(".py") and not os.path.isabs(value):
        candidate = os.path.join(cwd, value.replace("/", os.sep))
        if os.path.exists(candidate):
            return candidate
    return value


def _child_env(extra=None):
    env = dict(os.environ)
    env.update(extra or {})
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


# ── 원격 HTTP 서버 ────────────────────────────────────────────────────

_HEADER_NAME = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]+$")
# 프로토콜이 쓰는 헤더는 덮어쓰지 못하게 한다. 요청이 깨지거나 다른 호스트로 새는 것을 막는다.
_RESERVED_HEADERS = {"content-type", "accept", "content-length", "host", "connection",
                     "transfer-encoding", "mcp-session-id", "mcp-protocol-version"}


def clean_headers(value):
    """원격 서버에 덧붙일 헤더를 검증해 {이름: 값}으로 돌려준다. 잘못되면 ValueError(한국어 문구).

    값에는 ${VAR}를 쓸 수 있고, 치환은 연결할 때 한다. 여기서는 형식만 본다.
    """
    if value in (None, "", {}):
        return {}
    if not isinstance(value, dict):
        raise ValueError("헤더 형식이 올바르지 않습니다.")
    if len(value) > 20:
        raise ValueError("헤더는 20개까지 쓸 수 있습니다.")
    out = {}
    for key, val in value.items():
        if not isinstance(key, str) or not _HEADER_NAME.match(key) or len(key) > 100:
            raise ValueError("헤더 이름이 올바르지 않습니다: %s" % str(key)[:40])
        if key.lower() in _RESERVED_HEADERS:
            raise ValueError("'%s' 헤더는 앱이 직접 쓰므로 지정할 수 없습니다." % key)
        if not isinstance(val, str) or not val.strip() or len(val) > 2000:
            raise ValueError("'%s' 헤더의 값을 1~2000자로 입력해 주세요." % key)
        if any(ord(c) < 32 or ord(c) == 127 for c in val):
            raise ValueError("'%s' 헤더의 값에 줄바꿈이나 제어 문자를 쓸 수 없습니다." % key)
        out[key] = val.strip()
    return out


def parse_header_lines(text):
    """화면에서 줄마다 '이름: 값'으로 적은 헤더를 dict로 바꾼다. 형식이 틀리면 ValueError."""
    out = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        key, sep, val = line.partition(":")
        if not sep:
            raise ValueError("헤더는 '이름: 값' 형식으로 한 줄에 하나씩 적어 주세요.")
        out[key.strip()] = val.strip()
    return clean_headers(out)


def clean_fixed_args(value):
    """모든 도구 호출에 자동으로 합쳐 보낼 고정 인자를 검증해 {이름: 값}으로 돌려준다.

    본문(arguments)에 인증 값을 요구하는 서버용이다. 값에는 ${VAR}를 쓸 수 있다.
    """
    if value in (None, "", {}):
        return {}
    if not isinstance(value, dict):
        raise ValueError("고정 인자 형식이 올바르지 않습니다.")
    if len(value) > 20:
        raise ValueError("고정 인자는 20개까지 쓸 수 있습니다.")
    out = {}
    for key, val in value.items():
        if not isinstance(key, str) or not re.match(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$", key):
            raise ValueError("고정 인자 이름이 올바르지 않습니다: %s" % str(key)[:40])
        if not isinstance(val, str) or not val.strip() or len(val) > 2000:
            raise ValueError("'%s' 고정 인자의 값을 1~2000자로 입력해 주세요." % key)
        out[key] = val.strip()
    return out


def parse_fixed_arg_lines(text):
    """화면에서 줄마다 '이름: 값' 또는 '이름=값'으로 적은 고정 인자를 dict로 바꾼다."""
    out = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        positions = [p for p in (line.find(":"), line.find("=")) if p > 0]
        if not positions:
            raise ValueError("고정 인자는 '이름: 값' 형식으로 한 줄에 하나씩 적어 주세요.")
        cut = min(positions)
        out[line[:cut].strip()] = line[cut + 1:].strip()
    return clean_fixed_args(out)


def parse_servers_json(text):
    """붙여 넣은 {"mcpServers": {이름: {url, headers}}} JSON을 [(이름, url, headers, fixed_args)]로 바꾼다.

    이름: {...}만 있는 형태도 받는다. 원격(url) 서버만 허용한다.
    """
    try:
        data = json.loads(text or "")
    except ValueError:
        raise ValueError("JSON 형식이 올바르지 않습니다. 괄호와 따옴표를 확인해 주세요.")
    if isinstance(data, dict) and isinstance(data.get("mcpServers"), dict):
        data = data["mcpServers"]
    if not isinstance(data, dict) or not data:
        raise ValueError('{"mcpServers": {"서버이름": {"url": ...}}} 형식이어야 합니다.')
    if len(data) > 20:
        raise ValueError("한 번에 20개까지만 추가할 수 있습니다.")
    out = []
    for name, spec in data.items():
        if not isinstance(spec, dict):
            raise ValueError("'%s' 항목은 {...} 형식이어야 합니다." % name)
        if "command" in spec:
            raise ValueError("'%s'은(는) 명령을 실행하는 서버라 화면에서 추가할 수 없습니다. 원격(url) 서버만 가능합니다." % name)
        url = spec.get("url")
        if not isinstance(url, str) or not url.strip():
            raise ValueError("'%s' 항목에 url이 없습니다." % name)
        out.append((name, url.strip(), spec.get("headers"), spec.get("fixed_args")))
    return out


class HttpServer(object):
    def __init__(self, name, url, headers=None):
        self.name = name
        self.url = url
        self.extra_headers = dict(headers or {})
        self.session = None
        self._next_id = 0
        self._lock = threading.Lock()

    def _post(self, payload, timeout=30):
        headers = dict(self.extra_headers)
        headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        })
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        request = urllib.request.Request(
            self.url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            found = response.headers.get("Mcp-Session-Id")
            if found:
                self.session = found
            return response.read().decode("utf-8", "replace")

    def request(self, method, params, timeout=30):
        # 원격 서버는 요청마다 독립된 HTTP 호출이므로 동시에 보내도 된다.
        # 잠그는 것은 번호 발급뿐이다. 하위 에이전트들이 병렬로 검색할 수 있어야 한다.
        with self._lock:
            self._next_id += 1
            message_id = self._next_id
        body = self._post({"jsonrpc": "2.0", "id": message_id,
                           "method": method, "params": params}, timeout)
        for message in _parse_messages(body):
            if message.get("id") == message_id:
                if "error" in message:
                    raise IOError(str(message["error"])[:200])
                return message.get("result") or {}
        raise IOError("응답을 해석하지 못했습니다.")

    def notify(self, method, params):
        try:
            self._post({"jsonrpc": "2.0", "method": method, "params": params}, timeout=15)
        except Exception:
            pass                                        # 알림 실패는 연결을 막지 않는다

    def close(self):
        pass


def _parse_messages(body):
    """일반 JSON 응답과 SSE(text/event-stream) 응답을 함께 처리한다."""
    text = (body or "").strip()
    if not text:
        return []
    if not text.startswith("event:") and not text.startswith("data:"):
        try:
            data = json.loads(text)
            return data if isinstance(data, list) else [data]
        except ValueError:
            return []
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            try:
                out.append(json.loads(line[5:].strip()))
            except ValueError:
                continue
    return out


# ── 도구 설명 다듬기 ──────────────────────────────────────────────────

ALLOWED_KEYS = ("type", "description", "properties", "items", "required", "enum", "default")


def collapse_union(node):
    """anyOf / oneOf를 분기 하나로 접는다.

    선택 파라미터를 {"anyOf": [{실제 타입}, {"type": "null"}], "default": null}로
    적는 서버가 있다 (Tavily가 그렇다). anyOf를 그냥 버리면 타입과 enum이 함께
    사라져 모든 값이 문자열이 되고, 모델이 빈 문자열을 넣어 서버가 거절한다.
    null이 아닌 첫 분기를 남기고 바깥의 description 같은 값을 얹는다.
    """
    for key in ("anyOf", "oneOf"):
        options = node.get(key)
        if not isinstance(options, list):
            continue
        real = [o for o in options if isinstance(o, dict) and o.get("type") != "null"]
        if not real:
            continue
        merged = dict(real[0])
        for k, v in node.items():
            if k not in ("anyOf", "oneOf") and k not in merged:
                merged[k] = v
        return merged
    return node


def clean_schema(node):
    """서버가 준 JSON 스키마에서 함수 선언에 필요한 항목만 남긴다 (모델이 못 읽는 확장 필드 제거)."""
    if not isinstance(node, dict):
        return {"type": "string"}
    node = collapse_union(node)
    out = {}
    for key in ALLOWED_KEYS:
        if key not in node:
            continue
        value = node[key]
        if key == "properties" and isinstance(value, dict):
            out[key] = dict((k, clean_schema(v)) for k, v in value.items())
        elif key == "items":
            out[key] = clean_schema(value)
        elif key == "required" and isinstance(value, list):
            out[key] = [str(v) for v in value]
        elif key == "default":
            # 기본값이 있으면 모델이 그 인자를 생략해도 된다는 것을 안다.
            # null은 넘기지 않는다. 넘기면 모델이 그대로 null을 채워 넣는다.
            if value is not None:
                out[key] = value
        else:
            out[key] = value
    if out.get("type") == "object" and "properties" not in out:
        out["properties"] = {}
    if "type" not in out:
        out["type"] = "object" if "properties" in out else "string"
    return out


def _result_text(result):
    """MCP 도구 결과를 사람이 읽는 문자열로 바꾼다."""
    if not isinstance(result, dict):
        return str(result)[:RESULT_LIMIT]
    chunks = []
    for item in result.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "text":
            chunks.append(item.get("text") or "")
    text = "\n".join(c for c in chunks if c).strip()
    if not text:
        text = json.dumps(result.get("structuredContent") or result, ensure_ascii=False)
    if len(text) > RESULT_LIMIT:
        text = text[:RESULT_LIMIT] + " …(생략)"
    if result.get("isError"):
        return {"오류": text}
    return text


# ── 연결 ──────────────────────────────────────────────────────────────

def read_config(path):
    """설정 파일을 읽어 (서버 dict, 오류 문구 목록)을 돌려준다."""
    if not os.path.exists(path):
        return {}, []
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception:
        return {}, ["설정 파일의 형식이 올바르지 않습니다. JSON 내용을 확인해 주세요."]
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        return {}, []
    return servers, []


def _connect_one(name, spec, cwd):
    if spec.get("url"):
        # 치환한 주소와 헤더 값은 여기서만 쓰고 파일에도 로그에도 남기지 않는다.
        headers = {k: expand_env(v) for k, v in clean_headers(spec.get("headers")).items()}
        server = HttpServer(name, expand_env(spec["url"]), headers)
    elif spec.get("command"):
        args = [expand_env(a) for a in (spec.get("args") or [])]
        env = spec.get("env") or {}
        if not isinstance(env, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
            raise IOError("env 형식이 올바르지 않습니다.")
        server = StdioServer(name, expand_env(spec["command"]), args, cwd,
                             {k: expand_env(v) for k, v in env.items()})
        LAUNCH_LOG.append((name, spec["command"], server.executable))
    else:
        raise IOError("연결 정보가 없습니다.")

    fixed = {k: expand_env(v) for k, v in clean_fixed_args(spec.get("fixed_args")).items()}
    server.request("initialize", {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": CLIENT_INFO,
    })
    server.notify("notifications/initialized", {})
    listed = server.request("tools/list", {})

    entries = []
    for tool in listed.get("tools") or []:
        tool_name = tool.get("name")
        if not tool_name:
            continue
        entries.append({
            "name": tool_name,
            "description": (tool.get("description") or "").strip(),
            "parameters": _hide_fixed(clean_schema(tool.get("inputSchema")), fixed),
            "source": name,
            "call": _make_caller(server, tool_name, fixed),
        })
    return server, entries


def _hide_fixed(schema, fixed):
    """고정 인자는 모델에게 보이지 않게 스키마에서 뺀다. 모델이 키를 묻거나 지어내지 않고, 요청에도 실리지 않는다."""
    if not fixed or not isinstance(schema, dict):
        return schema
    schema = dict(schema)
    props = schema.get("properties")
    if isinstance(props, dict):
        schema["properties"] = {k: v for k, v in props.items() if k not in fixed}
    if isinstance(schema.get("required"), list):
        schema["required"] = [k for k in schema["required"] if k not in fixed]
    return schema


def _make_caller(server, tool_name, fixed=None):
    def call(args):
        # 고정 인자가 모델이 넣은 같은 이름의 값보다 우선한다.
        merged = dict(args or {})
        merged.update(fixed or {})
        try:
            result = server.request("tools/call", {"name": tool_name, "arguments": merged}, 60)
        except Exception as exc:
            return {"오류": "도구를 실행하지 못했습니다.", "내용": str(exc)[:200]}
        return _result_text(result)
    return call


def connect_all(path):
    """설정에 적힌 서버에 연결한다. 결과는 앱이 실행되는 동안 재사용한다."""
    if _CACHE["entries"] is not None:
        return _CACHE["entries"], _CACHE["errors"]

    config.load_env()                   # ${VAR} 치환에 쓸 값을 먼저 읽어 둔다
    servers, errors = read_config(path)
    del LAUNCH_LOG[:]
    entries = []
    handles = []
    for name in servers:
        spec = servers[name]
        if not isinstance(spec, dict):
            errors.append("%s 서버의 설정을 읽지 못했습니다." % name)
            continue
        try:
            server, tools = _connect_one(name, spec, config.ROOT)
        except MissingEnv as exc:
            # 이름만 알려 준다. 값은 어디에도 찍지 않는다.
            errors.append("%s 서버: .env에 %s 값이 없습니다. 값을 넣고 다시 연결해 주세요."
                          % (name, exc))
            continue
        except Exception:
            errors.append("%s 서버에 연결하지 못했습니다." % name)
            continue
        if not tools:
            errors.append("%s 서버에서 도구 목록을 받지 못했습니다." % name)
            server.close()
            continue
        handles.append(server)
        entries.extend(tools)

    _CACHE["entries"] = entries
    _CACHE["errors"] = errors
    _CACHE["servers"] = handles
    return entries, errors


def reset():
    """연결을 모두 끊고 캐시를 비운다. 설정을 바꾼 뒤 다시 연결할 때 쓴다."""
    for server in _CACHE["servers"]:
        server.close()
    _CACHE["entries"] = None
    _CACHE["errors"] = None
    _CACHE["servers"] = []
    del LAUNCH_LOG[:]
