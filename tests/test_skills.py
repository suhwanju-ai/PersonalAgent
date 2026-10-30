# -*- coding: utf-8 -*-
"""lab/skills.py 테스트 — 실행: py -m unittest tests.test_skills -v"""

import os
import shutil
import tempfile
import unittest

from lab import skills


class SkillsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._orig_dir = skills.SKILLS_DIR
        skills.SKILLS_DIR = self.tmp

    def tearDown(self):
        skills.SKILLS_DIR = self._orig_dir
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_skill(self, folder, text, files=None):
        """skills/<folder>/SKILL.md와 딸린 파일(상대 경로 → 내용)을 쓴다."""
        base = os.path.join(self.tmp, folder)
        os.makedirs(base, exist_ok=True)
        with open(os.path.join(base, "SKILL.md"), "w", encoding="utf-8", newline="") as f:
            f.write(text)
        for rel, content in (files or {}).items():
            path = os.path.join(base, *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(content)
        return base


class ParseTextTests(unittest.TestCase):
    def test_folded_description(self):
        s = skills.parse_text("---\nname: a\ndescription: >\n  첫 줄\n  둘째 줄\n---\n본문", "a")
        self.assertEqual(s["description"], "첫 줄 둘째 줄")

    def test_literal_description_collapses_whitespace(self):
        s = skills.parse_text("---\nname: a\ndescription: |-\n  a\n  b\n---\n본문", "a")
        self.assertEqual(s["description"], "a b")

    def test_description_capped_at_500(self):
        s = skills.parse_text("---\nname: a\ndescription: %s\n---\n본문" % ("가" * 700), "a")
        self.assertEqual(len(s["description"]), 500)

    def test_when_to_use_appended(self):
        s = skills.parse_text("---\nname: a\ndescription: A\nwhen_to_use: B\n---\n본문", "a")
        self.assertEqual(s["description"], "A B")

    def test_allowed_tools_split(self):
        s = skills.parse_text("---\nname: a\nallowed-tools: Read, render_html, Bash\n---\n", "a")
        self.assertEqual(s["tools"], ["render_html"])
        self.assertEqual(s["unsupported_tools"], ["Read", "Bash"])
        s = skills.parse_text("---\nname: a\nallowed-tools: [render_html]\n---\n", "a")
        self.assertEqual(s["tools"], ["render_html"])
        self.assertEqual(s["unsupported_tools"], [])

    def test_disable_model_invocation(self):
        s = skills.parse_text("---\nname: a\ndisable-model-invocation: true\n---\n", "a")
        self.assertIs(s["model_invocable"], False)
        s = skills.parse_text("---\nname: a\n---\n", "a")
        self.assertIs(s["model_invocable"], True)

    def test_uppercase_name_lowercased(self):
        s = skills.parse_text("---\nname: HTML\n---\n본문", "html")
        self.assertEqual(s["name"], "html")

    def test_bad_name_returns_none(self):
        self.assertIsNone(skills.parse_text("---\nname: ns:skill\n---\n", "x"))
        self.assertIsNone(skills.parse_text("---\nname: My.Skill\n---\n", "x"))

    def test_missing_closing_fence_is_body_only(self):
        raw = "---\nname: other\n본문 계속"
        s = skills.parse_text(raw, "folder-name")
        self.assertEqual(s["name"], "folder-name")
        self.assertEqual(s["body"], raw.strip())

    def test_empty_body_ok(self):
        s = skills.parse_text("---\nname: a\ndescription: d\n---\n", "a")
        self.assertEqual(s["body"], "")


class LoadTests(SkillsTestCase):
    def test_dot_folder_skipped(self):
        self.write_skill(".import-x", "---\nname: hidden\n---\n본문")
        self.write_skill("shown", "---\nname: shown\n---\n본문")
        self.assertEqual([s["name"] for s in skills.load_all()], ["shown"])

    def test_entries_hides_non_invocable(self):
        self.write_skill("quiet", "---\nname: quiet\ndisable-model-invocation: true\n---\n본문")
        self.assertEqual(skills.entries(), [])
        self.write_skill("loud", "---\nname: loud\ndescription: d\n---\n본문")
        use = skills.entries()[0]
        self.assertEqual(use["parameters"]["properties"]["name"]["enum"], ["loud"])
        self.assertNotIn("quiet", use["description"])


if __name__ == "__main__":
    unittest.main()
