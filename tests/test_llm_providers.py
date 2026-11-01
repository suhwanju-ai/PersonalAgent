"""LLM 제공자 설정·검증 테스트 (표준 라이브러리 unittest)."""
import json
import os
import shutil
import tempfile
import unittest

from lab import config


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
        for bad in (511, 2000001, "abc", -1):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                config.save_llm_settings(self._payload(modeldock_context_tokens=bad))
        for good in (0, 4096):
            with self.subTest(value=good):
                config.save_llm_settings(self._payload(modeldock_context_tokens=good))
                self.assertEqual(config.llm_settings()["modeldock_context_tokens"], good)

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


if __name__ == "__main__":
    unittest.main()
