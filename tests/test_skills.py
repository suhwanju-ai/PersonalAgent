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


class ImportTests(SkillsTestCase):
    def setUp(self):
        super().setUp()
        self.src = tempfile.mkdtemp()
        self._orig_env = os.environ.get("SKILLS_IMPORT_DIR")
        os.environ["SKILLS_IMPORT_DIR"] = self.src

    def tearDown(self):
        if self._orig_env is None:
            os.environ.pop("SKILLS_IMPORT_DIR", None)
        else:
            os.environ["SKILLS_IMPORT_DIR"] = self._orig_env
        shutil.rmtree(self.src, ignore_errors=True)
        super().tearDown()

    def make_src(self, folder, text=None, files=None):
        base = os.path.join(self.src, folder)
        os.makedirs(base, exist_ok=True)
        text = text if text is not None else "---\nname: %s\ndescription: d\n---\n본문" % folder
        with open(os.path.join(base, "SKILL.md"), "w", encoding="utf-8", newline="") as f:
            f.write(text)
        for rel, content in (files or {}).items():
            path = os.path.join(base, *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(content)
        return base

    def tree(self, base):
        out = []
        for root, _d, names in os.walk(base):
            for n in names:
                out.append(os.path.relpath(os.path.join(root, n), base).replace(os.sep, "/"))
        return sorted(out)

    def test_import_source_dir_reads_env_each_call(self):
        self.assertEqual(skills.import_source_dir(), self.src)
        os.environ.pop("SKILLS_IMPORT_DIR")
        self.assertEqual(skills.import_source_dir(),
                         os.path.join(os.path.expanduser("~"), ".claude", "skills"))

    def test_importable_lists_ok_and_bad(self):
        self.make_src("good", files={"references/g.md": "G", "scripts/r.py": "print(1)"})
        self.make_src("bad", "---\nname: ns:bad\n---\n본문")
        os.makedirs(os.path.join(self.src, "nomd"))
        r = skills.importable()
        self.assertEqual(r["dir"], "~/.claude/skills")
        by = {i["folder"]: i for i in r["items"]}
        self.assertEqual(sorted(by), ["bad", "good"])
        good = by["good"]
        self.assertIs(good["ok"], True)
        self.assertEqual(good["files"], 1)
        self.assertEqual(good["skipped"], ["scripts/r.py"])
        self.assertEqual(good["name"], "good")
        self.assertIs(good["exists"], False)
        self.assertIs(by["bad"]["ok"], False)
        self.assertTrue(by["bad"]["reason"])
        self.assertNotIn(self.src, by["bad"]["reason"])

    def test_importable_marks_existing(self):
        self.make_src("good")
        self.write_skill("good", "---\nname: good\ndescription: d\n---\n본문")
        self.assertIs(skills.importable()["items"][0]["exists"], True)

    def test_missing_source_dir_returns_empty(self):
        os.environ["SKILLS_IMPORT_DIR"] = os.path.join(self.src, "없는폴더")
        self.assertEqual(skills.importable()["items"], [])

    def test_import_copies_text_files_only(self):
        self.make_src("good", files={"references/g.md": "G", "scripts/r.py": "x", "a.exe": "x"})
        r = skills.import_skill("good")
        self.assertEqual(r["name"], "good")
        self.assertEqual(r["copied"], 1)
        self.assertIn("scripts/r.py", r["skipped"])
        base = os.path.join(self.tmp, "good")
        self.assertEqual(self.tree(base), ["SKILL.md", "references/g.md"])
        self.assertEqual([s["name"] for s in skills.load_all()], ["good"])

    def test_import_unknown_folder_rejected(self):
        self.make_src("good")
        outside = os.path.dirname(self.src)
        for bad in ("../x", "..", "nope", os.path.join(self.src, "good"), outside, "good/..", "", None, 5):
            with self.assertRaises(ValueError, msg=repr(bad)) as cm:
                skills.import_skill(bad)
            self.assertNotIn(self.src, str(cm.exception))
        self.assertEqual(os.listdir(self.tmp), [])

    def test_import_bad_name_rejected(self):
        self.make_src("bad", "---\nname: ns:bad\n---\n본문")
        with self.assertRaises(ValueError):
            skills.import_skill("bad")

    def test_import_existing_requires_overwrite(self):
        self.make_src("good")
        self.write_skill("good", "---\nname: good\ndescription: old\n---\n옛")
        with self.assertRaises(ValueError):
            skills.import_skill("good")
        with open(os.path.join(self.tmp, "good", "SKILL.md"), encoding="utf-8") as f:
            self.assertIn("옛", f.read())

    def test_import_overwrite_replaces(self):
        self.make_src("good", files={"references/new.md": "N"})
        self.write_skill("good", "---\nname: good\ndescription: old\n---\n옛", {"references/old.md": "O"})
        skills.import_skill("good", overwrite=True)
        self.assertEqual(self.tree(os.path.join(self.tmp, "good")), ["SKILL.md", "references/new.md"])
        self.assertEqual(os.listdir(self.tmp), ["good"])

    def test_import_failure_keeps_existing(self):
        self.make_src("good", "---\nname: good\ndescription: d\n---\n" + "가" * (skills.MAX_BYTES // 3 + 10))
        self.write_skill("good", "---\nname: good\ndescription: old\n---\n옛", {"references/old.md": "O"})
        with self.assertRaises(ValueError):
            skills.import_skill("good", overwrite=True)
        self.assertEqual(self.tree(os.path.join(self.tmp, "good")), ["SKILL.md", "references/old.md"])
        self.assertEqual([n for n in os.listdir(self.tmp) if n.startswith(".import-")], [])

    def test_import_failure_midway_cleans_staging(self):
        self.make_src("good", files={"references/g.md": "G"})
        self.write_skill("good", "---\nname: good\ndescription: old\n---\n옛", {"references/old.md": "O"})
        real = skills.shutil.copyfile
        calls = []

        def boom(src, dst, *a, **k):
            calls.append(dst)
            if len(calls) == 2:
                raise OSError("디스크 오류")
            return real(src, dst, *a, **k)
        skills.shutil.copyfile = boom
        try:
            with self.assertRaises(ValueError):
                skills.import_skill("good", overwrite=True)
        finally:
            skills.shutil.copyfile = real
        self.assertEqual(self.tree(os.path.join(self.tmp, "good")), ["SKILL.md", "references/old.md"])
        self.assertEqual([n for n in os.listdir(self.tmp) if n.startswith(".import-")], [])

    def test_import_respects_limits(self):
        self.assertEqual((skills.MAX_IMPORT_FILES, skills.MAX_IMPORT_FILE_BYTES, skills.MAX_IMPORT_TOTAL),
                         (40, 60000, 300000))
        self.make_src("many", files={"references/f%03d.md" % i: "x" for i in range(41)})
        r = skills.import_skill("many")
        self.assertEqual(r["copied"], 40)
        self.assertEqual(len(r["skipped"]), 1)
        self.assertIn("너무 많음", r["skipped"][0])
        self.assertEqual(len(skills.list_files(os.path.join(self.tmp, "many"))), 40)

    def test_import_skips_big_file(self):
        self.make_src("big", files={"references/ok.md": "x", "references/big.md": "x" * 60001})
        r = skills.import_skill("big")
        self.assertEqual(r["copied"], 1)
        self.assertEqual(r["skipped"], ["references/big.md (너무 큼)"])

    def test_import_total_cap(self):
        files = {"references/f%d.md" % i: "x" * 60000 for i in range(7)}      # 합계 42만
        self.make_src("tot", files=files)
        r = skills.import_skill("tot")
        self.assertEqual(r["copied"], 5)
        self.assertEqual(len(r["skipped"]), 2)
        self.assertTrue(all("합계 초과" in s for s in r["skipped"]))

    def test_import_prunes_hidden_and_node_modules(self):
        self.make_src("p", files={".git/a.md": "x", "node_modules/b.md": "x", "references/ok.md": "x"})
        r = skills.import_skill("p")
        self.assertEqual(r["copied"], 1)
        self.assertEqual(sorted(r["skipped"]), [".git/ (폴더 전체 건너뜀)", "node_modules/ (폴더 전체 건너뜀)"])

    def test_import_refuses_taken_folder_without_destroying(self):
        self.make_src("good")
        self.write_skill("good", "---\nname: other\ndescription: d\n---\n옛", {"notes.md": "N"})
        self.write_skill("draft", "---\nname: ns:bad\n---\n초안")
        for src_name, dirname in (("good", "good"),):
            with self.assertRaises(ValueError):
                skills.import_skill(src_name, overwrite=True)
        self.assertEqual(self.tree(os.path.join(self.tmp, "good")), ["SKILL.md", "notes.md"])
        self.make_src("draft", "---\nname: draft\ndescription: d\n---\n새")
        with self.assertRaises(ValueError):
            skills.import_skill("draft", overwrite=True)
        with open(os.path.join(self.tmp, "draft", "SKILL.md"), encoding="utf-8") as f:
            self.assertIn("초안", f.read())

    def _flaky_replace(self, fail_calls):
        real = skills.os.replace
        calls = []

        def flaky(a, b, *args, **kw):
            calls.append((a, b))
            if len(calls) in fail_calls:
                raise OSError("잠김")
            return real(a, b, *args, **kw)
        skills.os.replace = flaky
        return real

    def test_swap_failure_restores_old(self):
        self.make_src("good", files={"references/new.md": "N"})
        self.write_skill("good", "---\nname: good\ndescription: old\n---\n옛", {"references/old.md": "O"})
        real = self._flaky_replace({2})                 # 1: 옛 폴더 치우기, 2: 새 폴더 넣기
        try:
            with self.assertRaises(ValueError):
                skills.import_skill("good", overwrite=True)
        finally:
            skills.os.replace = real
        self.assertEqual(self.tree(os.path.join(self.tmp, "good")), ["SKILL.md", "references/old.md"])
        self.assertEqual([n for n in os.listdir(self.tmp) if n.startswith(".import-")], [])

    def test_swap_and_restore_failure_keeps_backup_and_recovers(self):
        self.make_src("good", files={"references/new.md": "N"})
        self.write_skill("good", "---\nname: good\ndescription: old\n---\n옛", {"references/old.md": "O"})
        real = self._flaky_replace({2, 3})              # 3: 되돌리기
        try:
            with self.assertRaises(ValueError) as cm:
                skills.import_skill("good", overwrite=True)
        finally:
            skills.os.replace = real
        self.assertIn("보관", str(cm.exception))
        self.assertNotIn(self.tmp, str(cm.exception))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "good")))
        self.assertEqual(self.tree(os.path.join(self.tmp, ".import-old-good")), ["SKILL.md", "references/old.md"])
        with self.assertRaises(ValueError):             # 다음 호출이 먼저 복구하므로 이제 '이미 있음'으로 거부된다
            skills.import_skill("good")
        self.assertEqual(self.tree(os.path.join(self.tmp, "good")), ["SKILL.md", "references/old.md"])
        self.assertEqual([n for n in os.listdir(self.tmp) if n.startswith(".import-")], [])

    def test_stale_backup_with_home_present_is_removed(self):
        self.write_skill("good", "---\nname: good\ndescription: d\n---\n새")
        self.write_skill(".import-old-good", "---\nname: good\n---\n찌꺼기")
        self.make_src("other")
        skills.import_skill("other")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, ".import-old-good")))

    def test_import_skips_links(self):
        outside = os.path.join(self.src, "outside.md")
        with open(outside, "w", encoding="utf-8") as f:
            f.write("비밀")
        base = self.make_src("lnk", files={"references/ok.md": "O"})
        try:
            os.symlink(outside, os.path.join(base, "references", "link.md"))
            os.symlink(self.src, os.path.join(base, "dirlink"), target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("링크를 만들 수 없는 환경")
        r = skills.import_skill("lnk")
        self.assertEqual(self.tree(os.path.join(self.tmp, "lnk")), ["SKILL.md", "references/ok.md"])
        self.assertEqual(r["copied"], 1)
        self.assertTrue(any("link.md" in s for s in r["skipped"]))

    def test_import_max_skills(self):
        for i in range(skills.MAX_SKILLS):
            self.write_skill("s%02d" % i, "---\nname: s%02d\ndescription: d\n---\n본문" % i)
        self.make_src("extra")
        with self.assertRaises(ValueError):
            skills.import_skill("extra")
        self.make_src("s00")            # 이미 있는 이름을 덮어쓰는 건 개수가 늘지 않으므로 된다
        skills.import_skill("s00", overwrite=True)

    def test_import_uses_normalized_name_for_folder(self):
        self.make_src("Weird_Folder", "---\nname: HTML-Report\ndescription: d\n---\n본문")
        r = skills.import_skill("Weird_Folder")
        self.assertEqual(r["name"], "html-report")
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "html-report", "SKILL.md")))


class ParseRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app
        cls.app = app

    def test_parse_folds_and_normalizes_name(self):
        r = self.app._skill_parse({"text": "---\nname: A_B\ndescription: >\n  x\n  y\n---\nbody"})
        self.assertIs(r["ok"], True)
        self.assertEqual(r["skill"]["description"], "x y")
        self.assertEqual(r["skill"]["name"], "a_b")
        self.assertEqual(r["skill"]["body"], "body")

    def test_parse_cleans_bad_name(self):
        r = self.app._skill_parse({"text": "---\nname: ns:My Skill\n---\nbody"})
        self.assertEqual(r["skill"]["name"], "ns-my-skill")

    def test_parse_notes(self):
        text = "---\nname: a\ndescription: %s\nallowed-tools: Bash, render_html\n---\nbun run x" % ("가" * 600)
        sk = self.app._skill_parse({"text": text})["skill"]
        self.assertEqual(len(sk["description"]), 500)
        self.assertEqual(sk["tools"], ["render_html"])
        self.assertEqual(len(sk["notes"]), 3)

    def test_parse_rejects_non_string(self):
        for bad in (None, 5, ["a"], {}):
            self.assertIs(self.app._skill_parse({"text": bad})["ok"], False)


if __name__ == "__main__":
    unittest.main()
