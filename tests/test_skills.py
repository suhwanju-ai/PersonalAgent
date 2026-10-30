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


class ReferenceFileTests(SkillsTestCase):
    HEAD = "---\nname: ref\ndescription: d\n---\n본문"

    def make(self, files=None):
        return self.write_skill("ref", self.HEAD, files or {})

    def test_list_files_excludes_scripts_and_skill_md(self):
        base = self.make({"references/a.md": "A", "notes.txt": "N", "scripts/run.py": "x",
                          "assets/x.png": "p", "scripts/doc.md": "s", ".git/c.md": "h"})
        self.assertEqual(skills.list_files(base), ["notes.txt", "references/a.md"])

    def test_list_files_limits_depth_and_count(self):
        base = self.make({"a/b/c/d/deep.md": "x", "a/b/c/ok.md": "x"})
        self.assertEqual(skills.list_files(base), ["a/b/c/ok.md"])
        files = {"f%03d.md" % i: "x" for i in range(skills.MAX_REF_FILES + 5)}
        base = self.write_skill("many", self.HEAD.replace("ref", "many"), files)
        self.assertEqual(len(skills.list_files(base)), skills.MAX_REF_FILES)

    def test_load_all_carries_files_and_view_counts(self):
        self.make({"references/a.md": "A"})
        self.assertEqual(skills.load_all()[0]["files"], ["references/a.md"])
        self.assertEqual(skills.view()["skills"][0]["files"], 1)

    def test_read_returns_content(self):
        self.make({"references/a.md": "안녕"})
        r = skills.read_file("ref", "references/a.md")
        self.assertEqual(r, {"스킬": "ref", "경로": "references/a.md", "내용": "안녕", "잘림": False})

    def test_read_truncates_at_20000(self):
        self.make({"big.txt": "가" * 25000})
        r = skills.read_file("ref", "big.txt")
        self.assertIs(r["잘림"], True)
        self.assertEqual(len(r["내용"]), 20000)

    def test_read_rejects_escape(self):
        self.make({"references/a.md": "A", "scripts/run.py": "print(1)"})
        secret = os.path.join(self.tmp, "secret.md")
        with open(secret, "w", encoding="utf-8") as f:
            f.write("TOPSECRET")
        for bad in ["../secret.md", "..\\secret.md", os.path.abspath(secret), "C:\\x.md",
                    "references/../../secret.md", "", "scripts/run.py", "references", "/secret.md",
                    "references//a.md", "./references/a.md", "ref\0.md", "SKILL.md", "SKILL.md.txt"]:
            r = skills.read_file("ref", bad)
            self.assertIn("오류", r, bad)
            self.assertNotIn("TOPSECRET", str(r), bad)
            self.assertNotIn(self.tmp, str(r), bad)
        self.assertIn("오류", skills.read_file("ref", None))

    def test_read_rejects_windows_name_tricks(self):
        self.make({"scripts/run.md": "SCRIPTBODY", ".hidden/h.md": "HIDDENBODY"})
        for bad in ["scripts /run.md", "scripts./run.md", "Scripts/run.md", "scripts/run.md ",
                    ".hidden/h.md", "HIDDEN~1/h.md", "a~1/run.md"]:
            r = skills.read_file("ref", bad)
            self.assertIn("오류", r, bad)
            self.assertNotIn("BODY", str(r), bad)

    def test_read_rejects_link_escape(self):
        base = self.make({"references/a.md": "A"})
        outside = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        with open(os.path.join(outside, "s.md"), "w", encoding="utf-8") as f:
            f.write("TOPSECRET")
        try:
            os.symlink(os.path.join(outside, "s.md"), os.path.join(base, "link.md"))
            os.symlink(outside, os.path.join(base, "linkdir"), target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("심볼릭 링크를 만들 수 없습니다")
        for bad in ["link.md", "linkdir/s.md"]:
            r = skills.read_file("ref", bad)
            self.assertIn("오류", r)
            self.assertNotIn("TOPSECRET", str(r))
        self.assertEqual(skills.list_files(base), ["references/a.md"])

    def test_read_non_utf8(self):
        base = self.make()
        with open(os.path.join(base, "k.md"), "wb") as f:
            f.write("한글".encode("cp949"))
        r = skills.read_file("ref", "k.md")
        self.assertEqual(r, {"오류": "텍스트로 읽을 수 없습니다."})

    def test_read_rejects_other_extensions(self):
        self.make({"x.png": "p", "x.py": "print(1)"})
        self.assertIn("오류", skills.read_file("ref", "x.png"))
        self.assertIn("오류", skills.read_file("ref", "x.py"))

    def test_read_unknown_skill(self):
        self.make({"a.md": "A"})
        self.assertIn("오류", skills.read_file("nope", "a.md"))
        self.assertIn("오류", skills.read_file(None, "a.md"))

    def test_read_agrees_with_list(self):
        self.make({"references/a.md": "A", "n.TXT": "N", "d/e/f/g.csv": "1"})
        listed = skills.list_files(os.path.join(self.tmp, "ref"))
        self.assertEqual(listed, ["d/e/f/g.csv", "n.TXT", "references/a.md"])
        for rel in listed:
            self.assertNotIn("오류", skills.read_file("ref", rel), rel)

    def test_entries_adds_read_tool_only_when_files_exist(self):
        self.write_skill("plain", "---\nname: plain\ndescription: d\n---\n본문")
        self.assertEqual([e["name"] for e in skills.entries()], ["use_skill"])
        self.make({"references/a.md": "A"})
        tools = {e["name"]: e for e in skills.entries()}
        read = tools["read_skill_file"]
        self.assertEqual(read["source"], "스킬")
        self.assertEqual(read["parameters"]["properties"]["skill"]["enum"], ["ref"])
        self.assertEqual(read["call"]({"skill": "ref", "path": "references/a.md"})["내용"], "A")
        self.assertIn("오류", read["call"]({"skill": "plain", "path": "a.md"}))
        self.assertIn("오류", read["call"](None))

    def test_use_skill_lists_files(self):
        self.make({"references/a.md": "A"})
        use = skills.entries()[0]["call"]({"name": "ref"})
        self.assertEqual(use["참고 파일"], ["references/a.md"])
        self.assertIn("read_skill_file", use["안내"])
        self.write_skill("plain", "---\nname: plain\ndescription: d\n---\n본문")
        self.assertNotIn("참고 파일", skills.entries()[0]["call"]({"name": "plain"}))


if __name__ == "__main__":
    unittest.main()
