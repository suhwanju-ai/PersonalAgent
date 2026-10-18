# -*- coding: utf-8 -*-
"""연구원 에이전트 한 명을 별도 프로세스로 띄운다.

두 에이전트가 이 파일을 같이 쓴다. 다른 것은 역할 지시문과 도구뿐이다.

받는 것 — `POST /task  {"instruction": "..."}`
주는 것 — `{"result": "...", "calls": [...], "searches": [...], "tokens", "elapsed", "steps", "trace": [...]}`
        trace는 이 연구원이 OpenRouter와 주고받은 요청·응답과 실행한 도구의 순서 기록이다.
        연구책임자가 로그에 실어 화면이 "연구원이 안에서 한 일"로 보여 준다.

**연구원끼리는 서로를 부를 수단이 없다.** 연구책임자만 이 주소를 안다.
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)

from lab import config, http_security, llm, roles, runner  # noqa: E402


def serve(role_name):
    role = roles.ROLES[role_name]
    config.load_env()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            pass

        def _json(self, payload, code=200):
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            try:
                http_security.validate_local_host(self, role["port"])
            except http_security.RequestRejected as exc:
                self._json({"ok": False, "message": str(exc)}, exc.status)
                return
            if self.path != "/info":
                self._json({"ok": False}, 404)
                return
            entries, errors = roles.tools_for(role_name)
            self._json({
                "ok": True,
                "role": role_name,
                "label": role["label"],
                "pid": os.getpid(),
                "port": role["port"],
                "web_search": role["web_search"],
                "tools": [{"name": e["name"], "source": e["source"]} for e in entries],
                "errors": errors,
            })

        def do_POST(self):
            if self.path != "/task":
                self._json({"ok": False}, 404)
                return
            try:
                length = http_security.validate_json_post(
                    self, port=role["port"], max_body=1024 * 1024,
                    browser_origins=(),
                )
                body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            except http_security.RequestRejected as exc:
                self._json({"ok": False, "result": str(exc)}, exc.status)
                return
            except (ValueError, UnicodeDecodeError):
                self._json({"ok": False, "result": "지시를 읽지 못했습니다."}, 400)
                return

            instruction = (body.get("instruction") or "").strip()
            if not instruction:
                self._json({"ok": False, "result": "지시가 비어 있습니다."})
                return

            entries, _errors = roles.tools_for(role_name)
            try:
                out = runner.run(instruction, entries,
                                 prompt=role["prompt"],
                                 web_search=role["web_search"],
                                 max_steps=config.AGENT_MAX_STEPS,
                                 trace=True)
            except llm.QuotaExceeded:
                self._json({"ok": False, "result": "호출 한도에 걸렸습니다. 잠시 후 다시."})
                return
            except (llm.LLMError, RuntimeError) as exc:
                self._json({"ok": False, "result": "처리하지 못했습니다: %s" % str(exc)[:120]})
                return

            self._json({"ok": True, "result": out["answer"], "calls": out["calls"],
                        "searches": out["searches"], "tokens": out["tokens"],
                        "elapsed": out["elapsed"], "steps": out["steps"],
                        "trace": out.get("trace", [])})

    server = ThreadingHTTPServer((config.HOST, role["port"]), Handler)
    # 부모가 이 줄을 읽고 기동을 확인한다. 형식을 바꾸지 않는다.
    sys.stdout.write("READY %s %d %d\n" % (role_name, role["port"], os.getpid()))
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
