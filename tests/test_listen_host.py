# -*- coding: utf-8 -*-
"""APP_HOST: 메인 앱이 듣는 주소 설정."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lab import config  # noqa: E402


class ListenHostTests(unittest.TestCase):
    def host(self, value):
        env = {} if value is None else {"APP_HOST": value}
        with mock.patch.dict(os.environ, env, clear=False):
            if value is None:
                os.environ.pop("APP_HOST", None)
            return config.listen_host()

    def test_default_is_loopback(self):
        self.assertEqual(self.host(None), "127.0.0.1")
        self.assertEqual(self.host("  "), "127.0.0.1")

    def test_accepts_ipv4_and_localhost(self):
        self.assertEqual(self.host("0.0.0.0"), "0.0.0.0")
        self.assertEqual(self.host(" 192.168.0.10 "), "192.168.0.10")
        self.assertEqual(self.host("LocalHost"), "127.0.0.1")

    def test_rejects_garbage(self):
        for bad in ("::", "example.com", "0.0.0.0:8770", "999.1.1.1", "http://0.0.0.0"):
            with self.assertRaises(ValueError, msg=bad):
                self.host(bad)

    def test_agents_stay_on_loopback(self):
        with mock.patch.dict(os.environ, {"APP_HOST": "0.0.0.0"}):
            self.assertEqual(config.HOST, "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
