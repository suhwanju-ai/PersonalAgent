# -*- coding: utf-8 -*-
"""Common Agent 로컬 서버.

run.bat이 이 파일을 실행한다. 브라우저 화면과 /api/*를 제공한다.
"""

import json
import os
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lab import (config, context_window, datafile, http_security, llm, mcp_client,    # noqa: E402
                 orchestrator, registry, roles, runner, tools)

STATIC = os.path.join(config.ROOT, "static")
CATALOG_PATH = os.path.join(config.ROOT, "mcp_catalog.json")
LOCK = threading.Lock()
CONTEXT_METER = context_window.Meter()
MAX_BODY = 8 * 1024 * 1024            # 파일을 base64로 실어 보내므로 상한을 둔다

MIME = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8", ".svg": "image/svg+xml",
        ".png": "image/png", ".ico": "image/x-icon", ".json": "application/manifest+json; charset=utf-8"}


# ── 상태 ──────────────────────────────────────────────────────────────

def _read_json(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except (ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def custom_servers():
    """화면에서 주소로 추가한 서버. {이름: {"label", "detail", "spec", "custom": True}}"""
    return {n: v for n, v in _read_json(config.MCP_CUSTOM_PATH).items()
            if isinstance(v, dict) and isinstance(v.get("spec"), dict)}


def write_custom_servers(servers):
    os.makedirs(config.STATE_DIR, exist_ok=True)
    with open(config.MCP_CUSTOM_PATH, "w", encoding="utf-8") as f:
        json.dump(servers, f, ensure_ascii=False, indent=2)
        f.write("\n")


def catalog():
    """연결할 수 있는 MCP 서버 목록. 기본 목록 + 화면에서 추가한 서버. 이름이 겹치면 기본 목록이 이긴다."""
    book = _read_json(CATALOG_PATH)
    for name, server in custom_servers().items():
        book.setdefault(name, server)
    return book


def connected_names():
    servers, _ = mcp_client.read_config(config.MCP_CONFIG_PATH)
    return list(servers)


def write_mcp_config(names):
    book = catalog()
    servers = {n: book[n]["spec"] for n in names if n in book}
    with open(config.MCP_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump({"mcpServers": servers}, f, ensure_ascii=False, indent=2)
        f.write("\n")
    mcp_client.reset()            # 다음 build에서 새 설정으로 다시 연결한다


def param_names(entry):
    props = (entry.get("parameters") or {}).get("properties") or {}
    return list(props)


def chat_view(turns):
    """화면에 보일 대화 기록. API 입력 항목(items)은 빼고 보낸다."""
    return [{k: t.get(k) for k in ("message", "answer", "calls", "at")} for t in turns]


def state():
    entries, errors = registry.build()
    turns = runner.load_chat()
    book = catalog()
    live = connected_names()
    return {
        "tools": [{
            "name": e["name"],
            "source": e.get("source", ""),
        } for e in entries],
        "disabled_tools": registry.disabled_mcp_tools(),
        "context_window": CONTEXT_METER.prepare(runner.system_prompt(), registry.declarations(entries),
                                                runner.chat_items(turns)),
        "chat": chat_view(turns),
        "prompt": runner.system_prompt(),
        "prompt_default": runner.DEFAULT_SYSTEM_PROMPT,
        "prompt_edited": os.path.exists(config.SYSTEM_PROMPT_PATH),
        "llm_settings": config.llm_settings(),
        "research_files": datafile.listing_detail(),
        "errors": errors,
        "mcp": {
            "catalog": [{"name": n,
                         "label": book[n].get("label", n),
                         "detail": book[n].get("detail", ""),
                         "custom": bool(book[n].get("custom")),
                         "on": n in live} for n in book],
        },
    }


# ── 요청 처리 ─────────────────────────────────────────────────────────

def handle_chat(payload):
    message = (payload.get("message") or "").strip()
    if not message:
        return {"ok": False, "message": "무엇을 도와드릴지 입력해 주세요."}
    entries, _ = registry.build()
    if not entries:
        return {"ok": False, "message": "쓸 수 있는 도구가 없습니다."}
    # 앞선 대화와 도구 호출·결과를 이어 넘긴다. 실패하면 저장하지 않으므로 파일은 마지막 성공 턴에 머문다.
    turns = runner.load_chat()
    history = runner.chat_items(turns)
    CONTEXT_METER.prepare(runner.system_prompt(), registry.declarations(entries), history)
    failed = True
    try:
        out = runner.run(message, entries, history=history, trace=True,
                         on_context=CONTEXT_METER.update)
        failed = False
    except llm.QuotaExceeded:
        return {"ok": False, "message": "잠시 후 다시 시도해 주세요 (약 1분)."}
    except RuntimeError as exc:
        if str(exc) == "NO_API_KEY":
            return {"ok": False,
                    "message": ".env 파일에 키가 없습니다. OPENROUTER_API_KEY를 확인해 주세요."}
        return {"ok": False, "message": "처리 중 문제가 생겼습니다."}
    except llm.LLMError as exc:
        if config.llm_settings()["provider"] == "ollama":
            # LLMError 메시지는 "network: ..." 또는 "HTTP <코드> ..."이고 키를 담지 않는다.
            if str(exc).startswith("network:"):
                message = ("앱 서버에서 Ollama에 연결하지 못했습니다. Ollama 서버 주소와 "
                           "운영 서버에서의 네트워크 접근을 확인해 주세요.")
            else:
                message = ("Ollama가 요청을 거부했습니다(%s). 모델 이름이 맞는지, "
                           "도구 호출을 지원하는 모델인지 확인해 주세요." % exc)
            return {"ok": False, "message": message}
        return {"ok": False, "message": "응답을 받지 못했습니다. 잠시 후 다시 시도해 주세요."}
    finally:
        CONTEXT_METER.finish(failed=failed)
    turns.append({"message": message, "answer": out["answer"], "calls": out["calls"],
                  "at": time.time(), "items": out["items"][len(history):]})
    try:
        runner.save_chat(turns)
    except OSError:
        out["chat_error"] = "대화 기록을 저장하지 못했습니다."
    out["chat"] = chat_view(runner.load_chat())
    out["context_window"] = CONTEXT_METER.snapshot()
    out["ok"] = True
    return out


ROUTES = {}
NO_LOCK = set()          # 락을 기다리면 안 되는 경로 (아래 설명)


def route(path, lock=True):
    """POST 처리기를 등록한다.

    lock=False는 연구가 도는 중에도 받아야 하는 요청에 쓴다. 모든 POST는
    LOCK 하나로 줄 세워 처리하는데, /api/research가 그 락을 몇 분씩 쥐고 있다.
    중지 요청을 락 뒤에 세우면 연구가 끝난 뒤에야 도착하므로 의미가 없다.
    """
    def wrap(fn):
        ROUTES[path] = fn
        if not lock:
            NO_LOCK.add(path)
        return fn
    return wrap


@route("/api/chat")
def _chat(p):
    return handle_chat(p)


@route("/api/chat/reset")
def _chat_reset(_p):
    runner.clear_chat()
    CONTEXT_METER.invalidate()          # 다음 /api/state가 기록 없이 다시 잰다
    return {"ok": True}


@route("/api/llm/settings")
def _llm_settings_save(p):
    try:
        settings = config.save_llm_settings(p)
    except ValueError as exc:
        return {"ok": False, "message": str(exc)}
    except OSError:
        return {"ok": False,
                "message": "설정을 디스크에 저장하지 못했습니다. 배포 환경에서 state/ 폴더에 쓰기 권한과 영구 저장 공간이 있는지 확인해 주세요."}
    CONTEXT_METER.invalidate()
    return {"ok": True, "settings": settings}


@route("/api/prompt")
def _prompt(p):
    runner.set_system_prompt(p.get("text") or "")
    return {"ok": True}


@route("/api/prompt/reset")
def _prompt_reset(_p):
    runner.clear_system_prompt()
    return {"ok": True}


@route("/api/agents/start")
def _agent_start(p):
    name = p.get("role")
    if name not in roles.ROLES:
        return {"ok": False, "message": "그런 역할이 없습니다."}
    out = orchestrator.start(name)
    out["agents"] = orchestrator.status()
    return out


@route("/api/agents/stop")
def _agent_stop(p):
    name = p.get("role")
    if name not in roles.ROLES:
        return {"ok": False, "message": "그런 역할이 없습니다."}
    out = orchestrator.stop(name)
    out["agents"] = orchestrator.status()
    return out


@route("/api/agents/start_all")
def _agents_start_all(_p):
    failed = [roles.ROLES[r]["label"] for r in roles.ORDER
              if not orchestrator.start(r).get("ok")]
    return {"ok": not failed, "agents": orchestrator.status(),
            "message": ("%s을(를) 띄우지 못했습니다." % ", ".join(failed)) if failed else ""}


@route("/api/agents/stop_all")
def _agents_stop_all(_p):
    orchestrator.stop_all()
    return {"ok": True, "agents": orchestrator.status()}


@route("/api/research")
def _research(p):
    question = (p.get("question") or "").strip()
    if not question:
        return {"ok": False, "message": "연구 질문을 입력해 주세요."}
    follow_up = bool(p.get("follow_up")) and orchestrator.has_session()
    # 꺼져 있는 연구원은 여기서 띄운다. 따로 [시작]을 누르지 않아도 연구가 시작된다.
    # 띄우는 동안에도 진행 상황이 "도는 중"으로 보이도록 먼저 내건다.
    orchestrator.begin(question, follow_up)
    started = []
    for role_name in roles.ORDER:
        if orchestrator.is_up(role_name):
            continue
        r = orchestrator.start(role_name)
        if not r.get("ok"):
            orchestrator.abort()
            return {"ok": False, "log": [],
                    "message": "%s을(를) 띄우지 못했습니다. %s"
                               % (roles.ROLES[role_name]["label"], r.get("message", ""))}
        started.append(roles.ROLES[role_name]["label"])
    out = orchestrator.research(question, follow_up=follow_up)
    out["has_session"] = orchestrator.has_session()
    out["auto_started"] = started
    return out


@route("/api/research/stop", lock=False)
def _research_stop(_p):
    return orchestrator.request_stop()


@route("/api/research/reset")
def _research_reset(_p):
    orchestrator.reset_session()
    return {"ok": True, "has_session": False}


@route("/api/data/upload")
def _data_upload(p):
    out = datafile.save_upload(p.get("name"), p.get("data"))
    out["files"] = datafile.listing_detail()
    return out


@route("/api/data/delete")
def _data_delete(p):
    out = datafile.delete_file(p.get("name"))
    out["files"] = datafile.listing_detail()
    return out


@route("/api/mcp/toggle")
def _mcp_toggle(p):
    name = (p.get("name") or "").strip()
    if name not in catalog():
        return {"ok": False, "message": "그런 서버가 목록에 없습니다."}
    live = connected_names()
    if p.get("on"):
        if name not in live:
            live.append(name)
    else:
        live = [n for n in live if n != name]
    write_mcp_config(live)
    _entries, errors = registry.build()
    return {"ok": True, "errors": errors}


# 서버 이름은 도구의 소속(source)으로 쓰인다. 앱이 이미 쓰는 소속 이름은 받지 않는다.
RESERVED_SOURCES = ("내장", "위임", "알 수 없음")


@route("/api/mcp/add")
def _mcp_add(p):
    """주소(Streamable HTTP)로 MCP 서버를 추가하고 바로 연결한다.

    키가 필요하면 주소에 ${API_KEY}처럼 이름만 적는다. 값은 연결할 때 .env에서 채운다.
    """
    name = " ".join((p.get("name") or "").split())
    url = (p.get("url") or "").strip()
    if not name:
        return {"ok": False, "message": "서버 이름을 입력해 주세요."}
    if len(name) > 40:
        return {"ok": False, "message": "서버 이름은 40자까지 쓸 수 있습니다."}
    if name in RESERVED_SOURCES:
        return {"ok": False, "message": "'%s'은(는) 앱이 쓰는 이름입니다. 다른 이름을 입력해 주세요." % name}
    if name in catalog():
        return {"ok": False, "message": "같은 이름의 서버가 이미 있습니다."}
    if not url.startswith(("https://", "http://")) or any(c.isspace() for c in url):
        return {"ok": False, "message": "주소는 http:// 또는 https://로 시작해야 합니다."}

    custom = custom_servers()
    custom[name] = {"label": name, "detail": "직접 추가한 원격 서버 · %s" % url,
                    "spec": {"url": url}, "custom": True}
    write_custom_servers(custom)

    live = connected_names()
    if name not in live:
        live.append(name)
    write_mcp_config(live)
    entries, errors = registry.build()
    count = sum(1 for e in entries if e["source"] == name)
    return {"ok": True, "tools": count, "errors": errors}


@route("/api/mcp/remove")
def _mcp_remove(p):
    """직접 추가한 서버만 지운다. 기본 목록의 서버는 연결을 끊을 수만 있다."""
    name = (p.get("name") or "").strip()
    custom = custom_servers()
    if name not in custom:
        return {"ok": False, "message": "직접 추가한 서버만 삭제할 수 있습니다."}
    del custom[name]
    write_custom_servers(custom)
    write_mcp_config([n for n in connected_names() if n != name])
    _entries, errors = registry.build()
    return {"ok": True, "errors": errors}


@route("/api/mcp/tool/remove")
def _mcp_tool_remove(p):
    source = (p.get("source") or "").strip()
    name = (p.get("name") or "").strip()
    if not source or not name:
        return {"ok": False, "message": "서버와 도구 이름이 필요합니다."}
    entries, _errors = registry.build()
    if not any(e.get("source") == source and e.get("name") == name
               for e in entries):
        return {"ok": False, "message": "해당 MCP 도구를 찾을 수 없습니다."}
    registry.disable_mcp_tool(source, name)
    mcp_client.reset()
    return {"ok": True}


@route("/api/mcp/tool/restore")
def _mcp_tool_restore(p):
    source = (p.get("source") or "").strip()
    name = (p.get("name") or "").strip()
    if not source or not name:
        return {"ok": False, "message": "서버와 도구 이름이 필요합니다."}
    if (source, name) not in {(item["source"], item["name"])
                              for item in registry.disabled_mcp_tools()}:
        return {"ok": False, "message": "제외된 MCP 도구를 찾을 수 없습니다."}
    registry.restore_mcp_tool(source, name)
    mcp_client.reset()
    return {"ok": True}


# ── HTTP ──────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass                                    # 콘솔을 깨끗하게 둔다

    def _send(self, code, body, content_type, headers=None):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, payload, code=200, headers=None):
        self._send(code, json.dumps(payload, ensure_ascii=False),
                   "application/json; charset=utf-8", headers)

    def _static(self, name):
        path = os.path.join(STATIC, os.path.basename(name))
        if not os.path.isfile(path):
            self._send(404, "not found", "text/plain; charset=utf-8")
            return
        ext = os.path.splitext(path)[1].lower()
        with open(path, "rb") as f:
            self._send(200, f.read(), MIME.get(ext, "application/octet-stream"))

    def do_GET(self):
        try:
            http_security.validate_local_host(
                self, config.PORT, config.trusted_origins(), config.access_token(),
            )
        except http_security.RequestRejected as exc:
            self._send(exc.status, str(exc), "text/plain; charset=utf-8", exc.headers)
            return
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            self._static("index.html")
        elif path.startswith("/static/"):
            self._static(path[len("/static/"):])
        elif path == "/api/state":
            with LOCK:
                self._json(state())
        elif path == "/api/context":
            # /api/chat이 LOCK을 보유하는 동안에도 계기판을 읽는다.
            self._json(CONTEXT_METER.snapshot())
        elif path == "/api/agents":
            self._json({"agents": orchestrator.status()})
        elif path == "/api/research/progress":
            # 여기서는 LOCK을 잡지 않는다. /api/research가 그 락을 쥔 채 도는 동안
            # 진행 상황을 읽어야 하기 때문이다.
            self._json(orchestrator.progress())
        else:
            self._send(404, "not found", "text/plain; charset=utf-8")

    def do_POST(self):
        path = self.path.split("?")[0]
        handler = ROUTES.get(path)
        if handler is None:
            self._send(404, "not found", "text/plain; charset=utf-8")
            return
        try:
            length = http_security.validate_json_post(
                self, port=config.PORT, max_body=MAX_BODY,
                trusted_origins=config.trusted_origins(),
                access_token=config.access_token(),
            )
            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except http_security.RequestRejected as exc:
            self._json({"ok": False, "message": str(exc)}, exc.status, exc.headers)
            return
        except (ValueError, UnicodeDecodeError):
            self._json({"ok": False, "message": "요청을 읽지 못했습니다."}, 400)
            return
        if path in NO_LOCK:
            self._json(handler(payload))        # 연구가 도는 중에도 받아야 한다
        else:
            with LOCK:
                self._json(handler(payload))


def main():
    print("Common Agent를 시작합니다.")
    if not os.path.exists(config.NOTES_PATH):
        tools.reset_notes()

    left = orchestrator.cleanup_stale()
    if left:
        print("지난 실행에서 남아 있던 프로세스를 정리했습니다: %s" % ", ".join(left))

    entries, errors = registry.build()
    print("도구 %d개" % len(entries))
    for entry in entries:
        print("  %-28s %s" % (entry["name"], entry["source"]))
    for line in errors:
        print("  " + line)

    address = "http://%s:%d/" % (config.HOST, config.PORT)
    server = ThreadingHTTPServer((config.HOST, config.PORT), Handler)
    print("\n주소: %s" % address)
    print("이 창을 닫으면 앱이 종료됩니다.\n")

    if not os.environ.get("AGENT_LAB_NO_BROWSER"):
        threading.Timer(1.0, lambda: webbrowser.open(address)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        # 자식 프로세스를 반드시 정리한다. 남아 있으면 포트가 막혀 다시 켜지지 않는다.
        orchestrator.stop_all()
        mcp_client.reset()


if __name__ == "__main__":
    main()
