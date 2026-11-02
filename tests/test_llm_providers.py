"""LLM 제공자 설정·검증 테스트 (표준 라이브러리 unittest)."""
import json
import os
import shutil
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import app
from lab import config, llm, mcp_client


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old_path = config.LLM_SETTINGS_PATH
        self.old_state_dir = config.STATE_DIR
        self.old_key = os.environ.get("MODELDOCK_API_KEY")
        config.LLM_SETTINGS_PATH = os.path.join(self.tmp, "llm_settings.json")
        config.STATE_DIR = self.tmp
        config._LLM_CACHE["settings"] = None

    def tearDown(self):
        config.LLM_SETTINGS_PATH = self.old_path
        config.STATE_DIR = self.old_state_dir
        config._LLM_CACHE["settings"] = None
        if self.old_key is None:
            os.environ.pop("MODELDOCK_API_KEY", None)
        else:
            os.environ["MODELDOCK_API_KEY"] = self.old_key
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, text):
        with open(config.LLM_SETTINGS_PATH, "w", encoding="utf-8") as f:
            f.write(text)

    def _payload(self, **extra):
        payload = {"provider": "modeldock", "model": "m1",
                   "modeldock_base_url": "http://h:6060/v1"}
        payload.update(extra)
        return payload

    def test_old_settings_file_still_loads(self):
        self._write(json.dumps({"provider": "ollama", "model": "m", "ollama_model": "m"}))
        settings = config.llm_settings()
        self.assertEqual(settings["provider"], "ollama")
        self.assertEqual(settings["modeldock_base_url"], "")
        self.assertEqual(settings["modeldock_context_tokens"], 0)

    def test_corrupt_settings_file_falls_back(self):
        self._write("{깨진 json")
        self.assertEqual(config.llm_settings()["provider"], "openrouter")

    def test_save_modeldock_roundtrip(self):
        config.save_llm_settings(self._payload(modeldock_base_url="http://h:6060"))
        settings = config.llm_settings()
        self.assertEqual(settings["provider"], "modeldock")
        self.assertEqual(settings["model"], settings["modeldock_model"])
        self.assertEqual(settings["modeldock_model"], "m1")
        self.assertTrue(settings["modeldock_base_url"].endswith("/v1"))
        self.assertEqual(settings["modeldock_base_url"], "http://h:6060/v1")

    def test_save_modeldock_requires_base_url_and_model(self):
        with self.assertRaises(ValueError):
            config.save_llm_settings(self._payload(modeldock_base_url=""))
        with self.assertRaises(ValueError):
            config.save_llm_settings(self._payload(model=""))

    def test_save_rejects_bad_urls(self):
        for url in ("ftp://h/v1", "http://169.254.169.254/v1", "http://u:p@h/v1", "http://h/v 1"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                config.save_llm_settings(self._payload(modeldock_base_url=url))

    def test_save_rejects_unknown_provider(self):
        with self.assertRaises(ValueError):
            config.save_llm_settings(self._payload(provider="azure"))

    def test_context_tokens_range(self):
        for bad in (511, 2000001, "abc", -1, True, float("inf"), float("nan")):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                config.save_llm_settings(self._payload(modeldock_context_tokens=bad))
        for good in (0, 4096, "4096"):
            with self.subTest(value=good):
                config.save_llm_settings(self._payload(modeldock_context_tokens=good))
                self.assertEqual(config.llm_settings()["modeldock_context_tokens"], int(good))

    def test_read_nonfinite_context_tokens_falls_back(self):
        for raw in ("Infinity", "-Infinity", "NaN", "1e999"):
            with self.subTest(raw=raw):
                self._write('{"provider": "ollama", "modeldock_context_tokens": %s}' % raw)
                config._LLM_CACHE["settings"] = None
                settings = config.llm_settings()
                self.assertEqual(settings["modeldock_context_tokens"], 0)
                self.assertEqual(settings["provider"], "ollama")

    def test_key_set_not_written_to_file(self):
        os.environ["MODELDOCK_API_KEY"] = "secret-x"
        config.save_llm_settings(self._payload())
        with open(config.LLM_SETTINGS_PATH, encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("modeldock_key_set", text)
        self.assertNotIn("secret-x", text)

    def test_unselected_modeldock_url_validated_only_when_present(self):
        base = {"provider": "openrouter", "model": "x/y"}
        config.save_llm_settings(dict(base, modeldock_base_url=""))
        with self.assertRaises(ValueError):
            config.save_llm_settings(dict(base, modeldock_base_url="ftp://h/v1"))

    def test_key_set_flag_never_exposes_key(self):
        os.environ["MODELDOCK_API_KEY"] = "secret-x"
        settings = config.llm_settings()
        self.assertIs(settings["modeldock_key_set"], True)
        self.assertNotIn("secret-x", json.dumps(settings))
        del os.environ["MODELDOCK_API_KEY"]
        self.assertIs(config.llm_settings()["modeldock_key_set"], False)

    def test_context_window_tokens_override(self):
        config.save_llm_settings(self._payload(modeldock_context_tokens=4096))
        self.assertEqual(config.context_window_tokens(), 4096)
        config.save_llm_settings({"provider": "openrouter", "model": "x/y",
                                  "modeldock_context_tokens": 4096})
        self.assertEqual(config.context_window_tokens(), config.CONTEXT_WINDOW_TOKENS)


class FakeModelDock:
    """테스트용 OpenAI 호환 서버. 포트 0으로 스레드에서 열고 받은 요청을 requests에 쌓는다.

    handler(request) -> (status, headers, body). request는
    {"method", "path", "headers"(소문자 키), "body"(파싱된 JSON 또는 None)}이고
    body가 bytes/str이면 그대로, 그 밖에는 JSON으로 내보낸다.
    """

    def __init__(self, handler):
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    body = json.loads(raw.decode("utf-8")) if raw else None
                except ValueError:
                    body = None
                request = {"method": self.command, "path": self.path, "body": body,
                           "headers": {k.lower(): v for k, v in self.headers.items()}}
                outer.requests.append(request)
                status, headers, payload = handler(request)
                if isinstance(payload, bytes):
                    data = payload
                else:
                    data = (payload if isinstance(payload, str) else json.dumps(payload)).encode("utf-8")
                self.send_response(status)
                for name, value in (headers or {}).items():
                    self.send_header(name, value)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = _handle

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self):
        return "http://127.0.0.1:%d/v1" % self.server.server_address[1]

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def ok_reply(content="안녕"):
    return (200, {}, {"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                      "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})


class TransportTests(unittest.TestCase):
    KEY = "md-secret-key-123"

    def serve(self, handler):
        fake = FakeModelDock(handler)
        self.addCleanup(fake.close)
        return fake

    def use(self, fake, **extra):
        """config.llm_settings가 fake 서버를 가리키게 한다."""
        settings = {"provider": "modeldock", "model": "m1", "modeldock_model": "m1",
                    "modeldock_base_url": fake.base_url, "modeldock_context_tokens": 0,
                    "modeldock_key_set": True, "ollama_base_url": config.OLLAMA_BASE_DEFAULT}
        settings.update(extra)
        patcher = mock.patch.object(config, "llm_settings", return_value=settings)
        patcher.start()
        self.addCleanup(patcher.stop)
        return settings

    def set_env(self, name, value):
        """환경변수를 설정(None이면 제거)하고 테스트가 끝나면 원래대로 되돌린다."""
        old = os.environ.get(name)
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value

        def restore():
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old
        self.addCleanup(restore)

    def sleeps(self):
        patcher = mock.patch.object(llm.time, "sleep")
        sleep = patcher.start()
        self.addCleanup(patcher.stop)
        return sleep

    def call(self, **kwargs):
        return llm.call("sys", [{"role": "user", "content": "hi"}], [], **kwargs)

    def fake_opener(self, exc):
        """llm의 리다이렉트 금지 opener를 항상 exc를 던지는 가짜로 바꾸고, 호출 인자를 기록한다."""
        opener = mock.Mock()
        opener.open.side_effect = exc
        patcher = mock.patch.object(llm, "_NO_REDIRECT_OPENER", opener)
        patcher.start()
        self.addCleanup(patcher.stop)
        return opener

    def test_timeout_is_not_resent(self):
        self.set_env("MODELDOCK_API_KEY", self.KEY)
        self.use(self.serve(lambda r: ok_reply()))
        self.sleeps()
        opener = self.fake_opener(llm.urllib.error.URLError(TimeoutError("timed out")))
        with self.assertRaises(llm.LLMError) as cm:
            self.call()
        self.assertEqual(opener.open.call_count, 1)
        self.assertTrue(str(cm.exception).startswith("network:"))

    def test_other_network_error_is_retried_once(self):
        self.set_env("MODELDOCK_API_KEY", self.KEY)
        self.use(self.serve(lambda r: ok_reply()))
        self.sleeps()
        opener = self.fake_opener(llm.urllib.error.URLError(ConnectionRefusedError("refused")))
        with self.assertRaises(llm.LLMError):
            self.call()
        self.assertEqual(opener.open.call_count, 2)

    def test_list_models_uses_short_timeout(self):
        self.set_env("MODELDOCK_API_KEY", self.KEY)
        settings = self.use(self.serve(lambda r: ok_reply()))
        self.sleeps()
        opener = self.fake_opener(llm.urllib.error.URLError(TimeoutError("timed out")))
        with self.assertRaises(llm.LLMError):
            llm.list_models(settings)
        self.assertEqual(opener.open.call_count, 1)
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 20)

    def test_empty_modeldock_address_is_llm_error(self):
        self.set_env("MODELDOCK_API_KEY", self.KEY)
        settings = self.use(self.serve(lambda r: ok_reply()), modeldock_base_url="")
        for run in (self.call, lambda: llm.list_models(settings)):
            with self.assertRaises(llm.LLMError) as cm:
                run()
            self.assertEqual(str(cm.exception), "ModelDock 주소가 설정되지 않았습니다")
            self.assertNotIn(self.KEY, str(cm.exception))

    def test_sends_bearer_and_json_to_v1_chat_completions(self):
        self.set_env("MODELDOCK_API_KEY", self.KEY)
        fake = self.serve(lambda r: ok_reply())
        self.use(fake)
        result = self.call(web_search=True)
        self.assertEqual(result["text"], "안녕")
        self.assertEqual(len(fake.requests), 1)
        req = fake.requests[0]
        self.assertEqual(req["method"], "POST")
        self.assertEqual(req["path"], "/v1/chat/completions")
        self.assertEqual(req["headers"]["authorization"], "Bearer " + self.KEY)
        self.assertEqual(req["headers"]["content-type"], "application/json")
        self.assertNotIn("http-referer", req["headers"])
        self.assertNotIn("x-title", req["headers"])
        self.assertEqual(req["body"]["model"], "m1")
        self.assertIs(req["body"]["stream"], False)
        self.assertNotIn("plugins", req["body"])

    def test_trace_has_no_headers_or_key(self):
        self.set_env("MODELDOCK_API_KEY", self.KEY)
        fake = self.serve(lambda r: ok_reply())
        self.use(fake)
        trace = []
        self.call(trace=trace)
        self.assertNotIn(self.KEY, json.dumps(trace))
        self.assertNotIn("headers", trace[0])

    def test_no_authorization_header_without_key(self):
        self.set_env("MODELDOCK_API_KEY", None)
        fake = self.serve(lambda r: ok_reply())
        self.use(fake)
        self.call()
        self.assertNotIn("authorization", fake.requests[0]["headers"])

    def test_error_body_echoing_key_is_masked(self):
        self.set_env("MODELDOCK_API_KEY", self.KEY)
        fake = self.serve(lambda r: (401, {}, {"error": {
            "message": "bad key " + r["headers"]["authorization"][len("Bearer "):]}}))
        self.use(fake)
        with self.assertRaises(llm.LLMError) as ctx:
            self.call()
        self.assertNotIn(self.KEY, str(ctx.exception))
        self.assertIn("***", str(ctx.exception))
        self.assertIn("401", str(ctx.exception))

    def test_scrub_masks_both_keys_and_ignores_empty(self):
        self.set_env("MODELDOCK_API_KEY", "md-key-aaa")
        self.set_env("OPENROUTER_API_KEY", "or-key-bbb")
        self.assertEqual(llm._scrub("a md-key-aaa b or-key-bbb c"), "a *** b *** c")
        self.set_env("MODELDOCK_API_KEY", "")
        self.set_env("OPENROUTER_API_KEY", "")
        self.assertEqual(llm._scrub("그대로 두기"), "그대로 두기")

    def test_redirect_is_not_followed(self):
        self.set_env("MODELDOCK_API_KEY", self.KEY)
        other = self.serve(lambda r: ok_reply())
        fake = self.serve(lambda r: (302, {"Location": other.base_url + "/chat/completions"}, ""))
        self.use(fake)
        self.sleeps()
        with self.assertRaises(llm.LLMError) as ctx:
            self.call()
        self.assertIn("HTTP 302", str(ctx.exception))
        self.assertEqual(other.requests, [])

    def test_retry_after_503_then_success(self):
        replies = [(503, {"Retry-After": "0"}, {"error": {"message": "busy"}}), ok_reply()]
        fake = self.serve(lambda r: replies.pop(0))
        self.use(fake)
        sleep = self.sleeps()
        self.assertEqual(self.call()["text"], "안녕")
        self.assertEqual(len(fake.requests), 2)
        sleep.assert_called_once_with(0)

    def test_503_without_retry_after_is_not_looped(self):
        fake = self.serve(lambda r: (503, {}, {"error": {"message": "down"}}))
        self.use(fake)
        self.sleeps()
        with self.assertRaises(llm.LLMError) as ctx:
            self.call()
        self.assertEqual(len(fake.requests), 2)
        self.assertIn("HTTP 503", str(ctx.exception))

    def test_retry_after_is_capped(self):
        replies = [(503, {"Retry-After": "999"}, "{}"), ok_reply()]
        fake = self.serve(lambda r: replies.pop(0))
        self.use(fake)
        sleep = self.sleeps()
        self.call()
        sleep.assert_called_once_with(30)

    def test_non_ascii_digit_retry_after_is_ignored(self):
        fake = self.serve(lambda r: (503, {"Retry-After": "\u00b2"},
                                     "{}"))
        self.use(fake)
        sleep = self.sleeps()
        with self.assertRaises(llm.LLMError) as ctx:
            self.call()
        self.assertIn("HTTP 503", str(ctx.exception))
        self.assertEqual(len(fake.requests), 2)
        sleep.assert_called_once_with(2.0)

    def test_non_json_success_body_raises_llm_error(self):
        for body in ("<html>web ui</html>", b"\xff\xfe\x00bad"):
            with self.subTest(body=body):
                fake = self.serve(lambda r, b=body: (200, {}, b))
                self.use(fake)
                with self.assertRaises(llm.LLMError) as ctx:
                    self.call()
                self.assertNotIn("web ui", str(ctx.exception))

    def test_trace_scrubs_key_echoed_in_response(self):
        self.set_env("MODELDOCK_API_KEY", self.KEY)
        fake = self.serve(lambda r: ok_reply("echo " + r["headers"]["authorization"]))
        self.use(fake)
        trace = []
        result = self.call(trace=trace)
        self.assertNotIn(self.KEY, json.dumps(trace))
        self.assertIn("***", trace[0]["response"]["choices"][0]["message"]["content"])
        self.assertEqual(sorted(trace[0]), ["elapsed", "request", "response", "url"])
        self.assertTrue(result["text"].startswith("echo "))

    def test_retry_after_tries_are_limited(self):
        fake = self.serve(lambda r: (503, {"Retry-After": "1"}, "{}"))
        self.use(fake)
        self.sleeps()
        with self.assertRaises(llm.LLMError):
            self.call()
        # 첫 요청 + Retry-After 재시도 3번 + 일반 재시도 1번
        self.assertEqual(len(fake.requests), 5)

    def test_429_raises_quota_exceeded(self):
        fake = self.serve(lambda r: (429, {}, {"error": {"message": "slow down"}}))
        self.use(fake)
        self.sleeps()
        with self.assertRaises(llm.QuotaExceeded):
            self.call()
        self.assertEqual(len(fake.requests), 1)

    def test_list_models_parses_openai_list(self):
        self.set_env("MODELDOCK_API_KEY", self.KEY)
        fake = self.serve(lambda r: (200, {}, {"object": "list", "data": [{"id": "a"}, {"id": "b"}]}))
        settings = self.use(fake)
        self.assertEqual(llm.list_models(), ["a", "b"])
        self.assertEqual(llm.list_models(settings), ["a", "b"])
        req = fake.requests[0]
        self.assertEqual((req["method"], req["path"]), ("GET", "/v1/models"))
        self.assertEqual(req["headers"]["authorization"], "Bearer " + self.KEY)

    def test_list_models_rejects_bad_shapes(self):
        for body in ({"data": "x"}, {"data": [{"id": 1}]}, {"data": [1]}, {"nope": []}, [],
                     "<html>web ui</html>", b"\xff\xfe\x00bad"):
            with self.subTest(body=body):
                fake = self.serve(lambda r, b=body: (200, {}, b))
                self.use(fake)
                with self.assertRaises(llm.LLMError) as ctx:
                    llm.list_models()
                self.assertNotIn("web ui", str(ctx.exception))

    def test_tool_call_response_is_converted(self):
        message = {"content": None, "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "memo_tool_1", "arguments": '{"text": "x"}'}}]}
        fake = self.serve(lambda r: (200, {}, {"choices": [{"message": message,
                                                            "finish_reason": "tool_calls"}]}))
        self.use(fake)
        result = self.call()
        self.assertEqual(result["calls"], [{"name": "memo_tool_1", "args": {"text": "x"},
                                            "call_id": "c1", "bad_args": False}])
        self.assertEqual(result["items"][0]["type"], "function_call")
        self.assertEqual(result["items"][0]["call_id"], "c1")


class AppTests(unittest.TestCase):
    KEY = "md-secret-key-123"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old_path = config.LLM_SETTINGS_PATH
        self.old_state_dir = config.STATE_DIR
        self.old_key = os.environ.get("MODELDOCK_API_KEY")
        config.LLM_SETTINGS_PATH = os.path.join(self.tmp, "llm_settings.json")
        config.STATE_DIR = self.tmp
        config._LLM_CACHE["settings"] = None
        os.environ["MODELDOCK_API_KEY"] = self.KEY

    def tearDown(self):
        config.LLM_SETTINGS_PATH = self.old_path
        config.STATE_DIR = self.old_state_dir
        config._LLM_CACHE["settings"] = None
        if self.old_key is None:
            os.environ.pop("MODELDOCK_API_KEY", None)
        else:
            os.environ["MODELDOCK_API_KEY"] = self.old_key
        shutil.rmtree(self.tmp, ignore_errors=True)

    def serve(self, handler):
        fake = FakeModelDock(handler)
        self.addCleanup(fake.close)
        return fake

    def test_error_messages_by_provider(self):
        md = {"provider": "modeldock"}
        cases = [
            ("network: timed out", "연결하지"),
            ("HTTP 401 invalid key " + self.KEY, "MODELDOCK_API_KEY"),
            ("HTTP 403 forbidden " + self.KEY, "MODELDOCK_API_KEY"),
            ("HTTP 404 no model " + self.KEY, "공개"),
            ("HTTP 503 loading " + self.KEY, "준비되지"),
            ("HTTP 400 bad request", "거부"),
        ]
        for text, word in cases:
            message = app.provider_error_message(md, llm.LLMError(text))
            self.assertIn(word, message, text)
            self.assertNotIn(self.KEY, message, text)
        for code in ("401", "403", "404"):
            self.assertNotIn("detail-xyz", app.provider_error_message(
                md, llm.LLMError("HTTP %s detail-xyz" % code)))

    def test_error_message_503_shows_server_reason(self):
        md = {"provider": "modeldock"}
        message = app.provider_error_message(md, llm.LLMError("HTTP 503 model is loading " + self.KEY))
        self.assertIn("서버 응답: model is loading", message)
        self.assertNotIn(self.KEY, message)  # 키는 LLMError를 만들 때 이미 가려진다고 가정하지 않고 확인
        self.assertNotIn("서버 응답", app.provider_error_message(md, llm.LLMError("HTTP 503")))

    def test_error_message_context_overflow(self):
        md = {"provider": "modeldock"}
        text = ("HTTP 400 request (6591 tokens) exceeds the available context size "
                "(4096 tokens), try increasing it")
        message = app.provider_error_message(md, llm.LLMError(text))
        self.assertIn("6591", message)
        self.assertIn("4096", message)
        self.assertIn("ctx", message)
        self.assertNotIn("도구 호출을 지원하는 모델", message)
        self.assertIn("HTTP 400 bad request",
                      app.provider_error_message(md, llm.LLMError("HTTP 400 bad request")))

    def test_error_message_modeldock_fallback(self):
        message = app.provider_error_message({"provider": "modeldock"},
                                             llm.LLMError("응답이 JSON이 아닙니다"))
        self.assertIn("처리하지", message)
        self.assertNotIn(self.KEY, message)

    def test_error_messages_keep_old_providers(self):
        ollama = {"provider": "ollama"}
        self.assertEqual(app.provider_error_message(ollama, llm.LLMError("network: x")),
                         "앱 서버에서 Ollama에 연결하지 못했습니다. Ollama 서버 주소와 "
                         "운영 서버에서의 네트워크 접근을 확인해 주세요.")
        self.assertEqual(app.provider_error_message(ollama, llm.LLMError("HTTP 500 x")),
                         "Ollama가 요청을 거부했습니다(HTTP 500 x). 모델 이름이 맞는지, "
                         "도구 호출을 지원하는 모델인지 확인해 주세요.")
        self.assertEqual(app.provider_error_message({"provider": "openrouter"}, llm.LLMError("HTTP 500")),
                         "응답을 받지 못했습니다. 잠시 후 다시 시도해 주세요.")

    def test_models_route_returns_ids(self):
        fake = self.serve(lambda r: (200, {}, {"data": [{"id": "a"}, {"id": "b"}]}))
        result = app.ROUTES["/api/llm/models"]({"modeldock_base_url": fake.base_url})
        self.assertEqual(result, {"ok": True, "models": ["a", "b"]})

    def test_models_route_uses_saved_url_when_empty(self):
        fake = self.serve(lambda r: (200, {}, {"data": [{"id": "z"}]}))
        config.save_llm_settings({"provider": "modeldock", "model": "m1",
                                  "modeldock_base_url": fake.base_url})
        result = app.ROUTES["/api/llm/models"]({"modeldock_base_url": "  "})
        self.assertEqual(result, {"ok": True, "models": ["z"]})

    def test_models_route_needs_an_address(self):
        result = app.ROUTES["/api/llm/models"]({})
        self.assertFalse(result["ok"])
        self.assertIn("주소", result["message"])

    def test_models_route_rejects_bad_url(self):
        for url in ("http://169.254.169.254/v1", "ftp://h/v1", 5, ["x"]):
            result = app.ROUTES["/api/llm/models"]({"modeldock_base_url": url})
            self.assertFalse(result["ok"], url)
            self.assertTrue(result["message"], url)

    def test_models_route_maps_server_errors(self):
        fake = self.serve(lambda r: (401, {}, {"error": {"message": "bad " + self.KEY}}))
        result = app.ROUTES["/api/llm/models"]({"modeldock_base_url": fake.base_url})
        self.assertFalse(result["ok"])
        self.assertIn("MODELDOCK_API_KEY", result["message"])
        self.assertNotIn(self.KEY, result["message"])

    def test_models_route_is_lock_free(self):
        self.assertIn("/api/llm/models", app.NO_LOCK)

    def test_state_exposes_flag_not_key(self):
        with mock.patch.object(app.registry, "build", return_value=([], [])), \
                mock.patch.object(app.registry, "disabled_mcp_tools", return_value=[]), \
                mock.patch.object(app.runner, "load_chat", return_value=[]), \
                mock.patch.object(app, "catalog", return_value={}), \
                mock.patch.object(app, "connected_names", return_value=[]), \
                mock.patch.object(app.datafile, "listing_detail", return_value=[]), \
                mock.patch.object(app.skills, "view", return_value=[]):
            view = app.state()["llm_settings"]
        self.assertIn("modeldock_key_set", view)
        self.assertTrue(view["modeldock_key_set"])
        self.assertNotIn(self.KEY, json.dumps(view))

    def test_modeldock_key_is_an_app_secret(self):
        self.assertIn("MODELDOCK_API_KEY", mcp_client.APP_SECRETS)
        self.assertEqual(mcp_client.reserved_placeholders("${MODELDOCK_API_KEY}"),
                         ["MODELDOCK_API_KEY"])
        with self.assertRaises(mcp_client.MissingEnv):
            mcp_client.expand_env("Bearer ${MODELDOCK_API_KEY}")


if __name__ == "__main__":
    unittest.main()
