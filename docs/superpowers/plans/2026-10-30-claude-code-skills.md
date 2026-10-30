# Claude Code 스킬 호환 확장 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Claude Code `SKILL.md`(블록 머리말, 참고 파일, `allowed-tools`)를 그대로 읽고, `~/.claude/skills`에서 화면으로 가져올 수 있게 한다.

**Architecture:** 모든 로직은 `lab/skills.py`에 둔다. 머리말 파서 하나를 서버에 두고 화면 붙여 넣기도 그것을 부른다. 참고 파일은 `read_skill_file` 도구로 점진적으로 읽고, 가져오기는 고정 원본 폴더를 서버가 직접 나열해 폴더 이름만 받는다. 스킬은 코드를 실행하지 않는다.

**Tech Stack:** Python 표준 라이브러리만(`unittest` 포함), `http.server`, 순수 HTML/CSS/JS.

**Spec:** `docs/superpowers/specs/2026-10-30-claude-code-skills-design.md`

## Global Constraints

- Python 표준 라이브러리만. 서드파티 의존성 추가 금지.
- `.env` 내용을 읽거나 출력하지 않는다. 키·절대경로를 오류 문구·로그·화면에 싣지 않는다.
- 스킬은 코드를 실행하지 않는다. `scripts/`는 읽지도 복사하지도 않는다. `run_python`은 다시 켜지 않는다.
- `READY <role> <port> <pid>` 줄과 `lab/roles.py`의 역할 지침 규칙은 건드리지 않는다.
- 설명 한도 500자, 참고 파일 확장자 `.md .txt .json .csv .yaml .yml`, 읽기 한도 20000자, 가져오기 한도 파일 40개·파일당 60KB·합계 300KB, `MAX_SKILLS` 30.
- 주석·화면 문구·오류 문구는 한국어. 기존 코드의 주석 밀도와 이름 붙이는 방식을 따른다.
- 커밋은 사용자가 요청했을 때만 한다. 아래 Commit 단계는 그때 실행할 메시지다.
- 테스트 명령(Windows): `py -m unittest tests.test_skills -v` (프로젝트 루트에서).

## Review Focus

1. `read_skill_file`에 `../x`, `C:\x`, `/etc/x`, `a\..\..\x`, 폴더 밖을 가리키는 링크가 주어짐 → 예외 없이 `{"오류"}`, 폴더 밖 내용은 절대 반환하지 않음 (Task 2).
2. `description: >`에 콜론·따옴표·빈 줄이 든 블록, 닫는 `---`가 없는 파일, 머리말만 있고 본문이 빈 파일 → 앱이 죽지 않고 해당 스킬만 건너뜀/빈 본문 처리 (Task 1).
3. 참고 파일이 UTF-8이 아님(cp949)이거나 바이너리 → `{"오류": "텍스트로 읽을 수 없습니다."}` (Task 2).
4. 가져오기 중 실패(복사 도중 한도 초과) 후 기존 같은 이름 스킬이 온전함, `.import-*` 임시 폴더가 남지 않고 스킬로 읽히지 않음 (Task 3).
5. 대문자/콜론/점이 든 이름(`My.Skill`, `ns:skill`), 같은 이름이 대소문자만 다른 두 폴더 → 가져올 수 없음 이유 표시 또는 첫 번째만 등록, 충돌 거부 (Task 3).

---

### Task 1: 머리말 파서와 스킬 메타데이터

**Files:**
- Create: `tests/test_skills.py`
- Modify: `lab/skills.py` (`_parse`, `load_all`, `problems`, `save`, `view`, `get`, `entries`)

**Interfaces:**
- Produces:
  - `skills.MAX_DESCRIPTION = 500`
  - `skills.parse_text(raw: str, folder: str = "") -> dict | None` — 문자열 하나를 파싱. 반환 `{"name", "folder", "description", "tools": [유효 도구], "unsupported_tools": [str], "model_invocable": bool, "body"}`. 이름 규칙 위반이면 `None`.
  - `_parse(path, folder)`는 파일을 읽어 `parse_text`에 넘긴다(크기 검사 유지).
  - `load_all()`은 `.`로 시작하는 폴더를 건너뛴다.
  - `view()`의 각 스킬에 `unsupported_tools`, `model_invocable`을 추가한다(`files`는 Task 2).
  - `entries()`는 `model_invocable`이 False인 스킬을 `use_skill` 목록·enum과 도구 수집에서 뺀다. 모델 호출 가능한 스킬이 없으면 빈 목록.
- 테스트 공통: `SkillsTestCase.setUp`이 `tempfile.mkdtemp()`를 만들고 `skills.SKILLS_DIR`을 그 경로로 바꾼다. `tearDown`에서 복원하고 지운다. 헬퍼 `write_skill(folder, text, files=None)`.

- [ ] **Step 1: 실패하는 테스트를 쓴다** — `tests/test_skills.py`에 `ParseTextTests`:
  - `test_folded_description`: `description: >\n  첫 줄\n  둘째 줄\n` → `description == "첫 줄 둘째 줄"`.
  - `test_literal_description_collapses_whitespace`: `description: |-\n  a\n  b` → `"a b"` (설명은 항상 공백을 접는다).
  - `test_description_capped_at_500`: 700자 → `len == 500`.
  - `test_when_to_use_appended`: `description: A` + `when_to_use: B` → `"A B"`.
  - `test_allowed_tools_split`: `allowed-tools: Read, render_html, Bash` → `tools == ["render_html"]`, `unsupported_tools == ["Read", "Bash"]`. `allowed-tools: [render_html]`도 같은 결과 형태.
  - `test_disable_model_invocation`: `disable-model-invocation: true` → `model_invocable is False`; 값 없음 → True.
  - `test_uppercase_name_lowercased`, `test_bad_name_returns_none`(`ns:skill`, `My.Skill`).
  - `test_missing_closing_fence_is_body_only`: 닫는 `---` 없음 → 폴더 이름을 name으로, 전체가 body.
  - `test_empty_body_ok`.
  그리고 `LoadTests`: `test_dot_folder_skipped`(`.import-x/SKILL.md`는 `load_all()`에 없음), `test_entries_hides_non_invocable`(비호출 스킬만 있으면 `entries() == []`, 섞이면 enum에 호출 가능한 것만).
- [ ] **Step 2: 실패를 확인한다** — Run: `py -m unittest tests.test_skills -v` / Expected: FAIL (`parse_text` 없음).
- [ ] **Step 3: 구현한다** — `lab/skills.py`에 `_frontmatter(raw) -> (dict, str)`를 두고 `parse_text`가 쓴다. YAML 부분집합: `key: value` 한 줄(짝 맞는 따옴표만 벗김), 값이 `>` `>-` `|` `|-`이면 이후 들여쓴 줄(빈 줄 포함)을 모아 접거나(`>`) 줄바꿈 유지(`|`)하고, 들여쓰지 않은 줄을 만나면 끝. 키는 소문자. `tools`와 `allowed-tools`는 `[`·`]`를 떼고 쉼표/공백으로 쪼갠다. 설명 상한은 `MAX_DESCRIPTION`을 쓰고 `save`의 300 검사와 `ValueError` 문구도 500으로 바꾼다. `problems()`는 `parse_text`가 None인 이유를 기존 문구 그대로 낸다.
- [ ] **Step 4: 통과를 확인한다** — Run: `py -m unittest tests.test_skills -v` / Expected: PASS. 그리고 `py -m py_compile lab/skills.py`.
- [ ] **Step 5: Commit** — `git add tests/test_skills.py lab/skills.py` / `git commit -m "feat: Claude Code SKILL.md 머리말(블록·allowed-tools·모델 호출 금지) 읽기"`

---

### Task 2: 참고 파일과 `read_skill_file`

**Files:**
- Modify: `lab/skills.py`
- Test: `tests/test_skills.py`

**Interfaces:**
- Consumes: Task 1의 `load_all()`, `entries()`.
- Produces:
  - `skills.REFERENCE_EXTS = {".md", ".txt", ".json", ".csv", ".yaml", ".yml"}`, `MAX_REF_FILES = 100`, `MAX_REF_DEPTH = 3`, `MAX_READ_CHARS = 20000`.
  - `skills.list_files(skill_dir: str) -> list[str]` — `SKILL.md`를 뺀 참고 파일의 상대경로(`/` 구분, 정렬). 숨김(`.`로 시작) 폴더·`scripts`·링크는 제외. 한도 초과분은 버린다.
  - `skills.read_file(name: str, rel_path: str) -> dict` — 성공 `{"스킬", "경로", "내용", "잘림": bool}`, 실패 `{"오류": str}` (예외를 올리지 않는다, 오류 문구에 절대경로 없음).
  - `load_all()`의 각 스킬에 `"files": list[str]` 추가. `view()`는 `files`를 개수로(`"files": len`) 싣는다.
  - `entries()`: 호출 가능한 스킬 중 `files`가 있는 것이 하나라도 있으면 도구 `read_skill_file`(인자 `skill` enum=파일 있는 스킬 이름, `path` string)을 추가한다(source `"스킬"`). `use_skill` 결과에 `files`가 있으면 `"참고 파일": [...]`과 한 줄 안내(`read_skill_file(skill, path)로 읽는다`)를 더한다.

- [ ] **Step 1: 실패하는 테스트를 쓴다** — `ReferenceFileTests`:
  - `test_list_files_excludes_scripts_and_skill_md`: `references/a.md`, `notes.txt`, `scripts/run.py`, `assets/x.png` → `["notes.txt", "references/a.md"]`.
  - `test_read_returns_content`, `test_read_truncates_at_20000`(`잘림 is True`, `len(내용) == 20000`).
  - `test_read_rejects_escape` — 다음 각각 `"오류" in result`이고 폴더 밖 파일 내용이 결과에 없음: `"../secret.md"`, `"..\\secret.md"`, 절대경로(`os.path.abspath` 한 파일), `"C:\\x.md"`, `"references/../../secret.md"`, 빈 문자열, `"scripts/run.py"`, `"references"`(폴더).
  - `test_read_rejects_link_escape`: 폴더 안에서 밖을 가리키는 심볼릭 링크를 만들 수 있으면 거부 확인(`os.symlink`가 `OSError`면 `skipTest`).
  - `test_read_non_utf8`: cp949로 쓴 `.md` → `{"오류": "텍스트로 읽을 수 없습니다."}` 또는 동등한 오류, 예외 없음.
  - `test_read_unknown_skill`.
  - `test_entries_adds_read_tool_only_when_files_exist`, `test_use_skill_lists_files`.
- [ ] **Step 2: 실패를 확인한다** — Run: `py -m unittest tests.test_skills.ReferenceFileTests -v` / Expected: FAIL.
- [ ] **Step 3: 구현한다** — `read_file`은 먼저 `rel_path`가 비어 있거나 `\`·`:`·앞쪽 `/`·`..` 조각을 포함하면 거부하고, 이어서 `os.path.realpath`로 푼 결과가 스킬 폴더 realpath 안인지 `os.path.commonpath`로 확인한 뒤(Windows 대소문자는 `os.path.normcase`), 확장자가 `REFERENCE_EXTS`이고 일반 파일일 때만 `utf-8-sig`로 읽는다. `list_files`는 `os.walk`로 깊이와 개수를 제한하고 `os.path.islink`인 항목과 `scripts`·`.`시작 폴더를 건너뛴다.
- [ ] **Step 4: 통과를 확인한다** — Run: `py -m unittest tests.test_skills -v` / Expected: PASS.
- [ ] **Step 5: Commit** — `git add lab/skills.py tests/test_skills.py` / `git commit -m "feat: 스킬 참고 파일과 read_skill_file 도구"`

---

### Task 3: `~/.claude/skills` 가져오기 (서버)

**Files:**
- Modify: `lab/skills.py`, `app.py` (스킬 라우트 옆, 약 433행 이후)
- Test: `tests/test_skills.py`

**Interfaces:**
- Consumes: Task 1 `parse_text`, Task 2 `list_files`, `REFERENCE_EXTS`; 기존 `save`가 쓰는 `MAX_SKILLS`, `SKILLS_DIR`.
- Produces:
  - `skills.IMPORT_LABEL = "~/.claude/skills"`
  - `skills.import_source_dir() -> str` — 환경 변수 `SKILLS_IMPORT_DIR`이 있으면 그 값, 없으면 `os.path.join(os.path.expanduser("~"), ".claude", "skills")`. 호출 때마다 읽는다.
  - `skills.importable() -> dict` — `{"dir": IMPORT_LABEL, "items": [{"folder", "name", "description", "files": int, "skipped": [str], "exists": bool, "ok": bool, "reason": str}]}`. 폴더가 없으면 `items == []`. `SKILL.md`가 없는 폴더는 목록에 없다. `ok=False`이면 `reason`(이름 규칙 위반, 너무 큼 등)이 있다.
  - `skills.import_skill(folder: str, overwrite: bool = False) -> dict` — 성공 `{"name", "copied": int, "skipped": [str]}`. 실패는 `ValueError(한국어 메시지)`: 목록에 없는 폴더, 이름 규칙 위반, 이미 있는데 `overwrite` 아님, `MAX_SKILLS` 초과, `SKILL.md` 한도 초과.
  - 라우트 `POST /api/skills/importable` → `{"ok": True, **importable()}`, `POST /api/skills/import {folder, overwrite}` → `{"ok": True, "name", "copied", "skipped", "skills": skills.view()}` 또는 `{"ok": False, "message"}`. 둘 다 `lock=False`가 아니어도 되지만 `folder`가 문자열이 아니면 `ok:false`.
  - `skills.parse_text`는 화면 붙여 넣기용 라우트 `POST /api/skills/parse {text}` → `{"ok": True, "skill": {name, description, tools, body, notes: [str]}}`에도 쓰인다. `notes`에는 설명이 500자로 잘렸을 때, 지원 안 하는 도구가 있을 때, Claude Code 전용 내용(기존 JS의 정규식과 같은 검사)이 있을 때의 문구를 담는다. 이름이 규칙에 맞지 않으면 `name`을 `-`로 정리한 값을 준다.

- [ ] **Step 1: 실패하는 테스트를 쓴다** — `ImportTests`(원본은 임시 폴더 + `os.environ["SKILLS_IMPORT_DIR"]`, `tearDown`에서 복원):
  - `test_importable_lists_ok_and_bad`: 정상 1개(`references/g.md`, `scripts/r.py`), `ns:bad` 1개 → 정상 `ok True, files 1, skipped ["scripts/r.py"]`, 나쁜 것 `ok False, reason` 비어 있지 않음.
  - `test_import_copies_text_files_only`: 가져온 뒤 `skills/<name>/references/g.md` 있고 `scripts/`는 없음, `load_all()`에 등록됨.
  - `test_import_unknown_folder_rejected`: `"../x"`, 없는 이름, 절대경로 → `ValueError`.
  - `test_import_existing_requires_overwrite`, `test_import_overwrite_replaces`: 덮어쓰면 옛 참고 파일이 남지 않는다.
  - `test_import_failure_keeps_existing`: 원본 `SKILL.md`를 `MAX_BYTES`보다 크게 → `ValueError`, 기존 스킬 폴더 내용 그대로, `skills/.import-*` 없음.
  - `test_import_respects_limits`: 파일 41개 → 40개만 복사, 나머지는 `skipped`에 "너무 많음" 계열 문구.
  - `test_import_skips_links`(링크 생성 불가면 skip).
  - `test_import_max_skills`: 30개가 이미 있으면 새 이름은 거부.
  - `test_missing_source_dir_returns_empty`.
  - `ParseRouteTests`는 함수 수준에서: `app._skill_parse({"text": "---\nname: A_B\ndescription: >\n  x\n  y\n---\nbody"})["skill"]`가 `description == "x y"`, `name == "a_b"`. `text`가 문자열이 아니면 `ok False`.
- [ ] **Step 2: 실패를 확인한다** — Run: `py -m unittest tests.test_skills.ImportTests -v` / Expected: FAIL.
- [ ] **Step 3: 구현한다** — `import_skill`은 `importable()['items']`에서 `folder`와 같은 항목을 찾고 없으면 거부한다(경로로 쓰지 않는다). `skills/.import-<name>` 임시 폴더에 `SKILL.md`와 허용 파일을 한도 안에서 복사하고(`realpath`가 원본 폴더 밖이면 건너뜀), 성공하면 기존 폴더를 지우고 `os.replace`로 교체한다. 예외가 나면 임시 폴더를 `shutil.rmtree`로 지운다. 이름이 `SKILL.md` 머리말과 폴더 이름이 다르면 폴더는 정규화한 `name`으로 만든다. 새 라우트는 기존 `@route`/`ValueError → ok:false` 패턴을 따른다.
- [ ] **Step 4: 통과를 확인한다** — Run: `py -m unittest tests.test_skills -v` / Expected: PASS. `py -m py_compile app.py lab/skills.py`.
- [ ] **Step 5: Commit** — `git add app.py lab/skills.py tests/test_skills.py` / `git commit -m "feat: ~/.claude/skills 가져오기와 SKILL.md 서버 파서 라우트"`

---

### Task 4: 화면 — 가져오기 목록, 배지, 붙여 넣기 서버 파서

**Files:**
- Modify: `static/index.html` (스킬 카드 약 90행 근처, 팝업 192~207행), `static/app.js` (`drawSkills`, `importSkillMd`, 새 가져오기 팝업 핸들러), `static/style.css`
- 검증은 Playwright로 한다(저장소에 프론트 테스트 없음).

**Interfaces:**
- Consumes: `/api/skills/importable`, `/api/skills/import`, `/api/skills/parse`; `skills.view()`의 `files`, `unsupported_tools`, `model_invocable`.
- Produces: `index.html`의 `app.js?v=` 쿼리를 올려 캐시를 깬다(현재 값 확인 후 +1).

- [ ] **Step 1: 화면 구조를 넣는다** — 스킬 카드에 버튼 `#importClaudeSkills`("Claude Code 스킬 가져오기"), 새 `<dialog id="claudeSkillDialog">`(목록 `#claudeSkillList`, 안내 줄, 닫기). 목록 행: 이름·설명·"참고 파일 N"·건너뜀 목록·`ok=False` 이유(비활성)·`exists`면 "덮어쓰기" 확인 문구. 스킬 편집 팝업의 설명 `maxlength`를 500으로.
- [ ] **Step 2: `drawSkills`에 배지를 단다** — `files>0`이면 "참고 파일 N", `model_invocable===false`이면 "모델 호출 금지", `unsupported_tools.length`이면 "지원 안 하는 도구: …". 값은 모두 `esc()`로 이스케이프한다.
- [ ] **Step 3: 가져오기 동작을 연결한다** — 버튼 클릭 때 `/api/skills/importable`을 불러 목록을 그리고, 행의 "가져오기"가 `/api/skills/import`를 부른다. `exists`이면 `confirm()` 대신 행 안의 두 번째 클릭("덮어쓰기 확인")으로 `overwrite:true`를 보낸다(브라우저 모달 대화상자를 쓰지 않는다). 성공하면 `drawSkills(r.skills)`와 결과(복사 N개, 건너뜀)를 행에 표시.
- [ ] **Step 4: 붙여 넣기를 서버 파서로 바꾼다** — `importSkillMd`를 지우고 `$("skillImportRun")` 핸들러가 `/api/skills/parse`를 부른다. 결과를 같은 칸들에 채우고 `notes`를 `skillImportNote`에 표시한다. 고치는 중이면 이름 칸은 그대로 둔다(기존 동작 유지).
- [ ] **Step 5: 브라우저로 확인한다** — 앱을 임시 포트로 띄우고(`config.PORT` 패치 방식, 기존 검증과 동일) Playwright로: (a) 임시 `SKILLS_IMPORT_DIR`에 만든 샘플(`description: >`, `references/`, `scripts/`)이 목록에 보이고 가져오면 스킬 목록에 "참고 파일 1"이 붙는다, (b) 같은 스킬을 다시 가져오면 덮어쓰기 확인이 나온다, (c) `description: >`가 든 SKILL.md 붙여 넣기가 설명 칸을 한 줄로 채운다, (d) 콘솔 오류 없음, (e) 좁은 폭(390px)과 다크 모드에서 레이아웃이 깨지지 않는다. 스크린샷은 스크래치패드에 저장.
- [ ] **Step 6: Commit** — `git add static/index.html static/app.js static/style.css` / `git commit -m "feat: Claude Code 스킬 가져오기 화면과 붙여 넣기 서버 파서"`

---

### Task 5: 통합 확인과 문서

**Files:**
- Modify: `CLAUDE.md` (Skills 단락, "no test suite" 문장), `README.md` (스킬 사용 설명), `.env.example`(`SKILLS_IMPORT_DIR` 주석 한 줄, 값 비움)
- Test: 수동 end-to-end (스크립트는 스크래치패드)

**Interfaces:**
- Consumes: Task 1~4 전체.

- [ ] **Step 1: 모델 루프 확인** — 가짜 `llm._post`로 오케스트레이터와 같은 `runner.run`을 돌려, 참고 파일이 있는 스킬에서 `use_skill` → `read_skill_file`(`path="references/g.md"`) → 최종 답이 이어지는지 확인한다. `read_skill_file("../x")` 호출은 오류 결과를 모델이 받고 계속 진행한다. 기대: 도구 결과에 `내용`이 포함되고 예외 없음.
- [ ] **Step 2: 회귀 확인** — 기존 `html` 스킬이 목록에 있고 `render_html` 호출이 동작, 화면 저장/삭제(`/api/skills/save`·`delete`)가 동작하며 저장 후 `references/`가 보존된다(R8). `py -m unittest tests.test_skills -v` 전체 통과, 앱 전체 `py -m py_compile`.
- [ ] **Step 3: 실제 Claude Code 스킬로 한 번 시험한다** — 사용자의 `~/.claude/skills`를 **읽기만** 해서 목록이 뜨는지 확인한다(가져오기는 사용자가 고른 것만; 임의 가져오기 금지). 목록의 `ok=False` 이유가 이해되는 문구인지 본다.
- [ ] **Step 4: 문서를 고친다** — `CLAUDE.md` Skills 단락에: 머리말 파서 범위, `read_skill_file`, 가져오기 원본·`SKILLS_IMPORT_DIR`, "저장소 테스트는 `tests/test_skills.py` 하나뿐" 문장(Commands의 "no test suite" 문구 수정). `README.md`에 사용자용 설명 한 단락. `.env.example`에는 키 이름만(값 없음).
- [ ] **Step 5: Commit** — `git add CLAUDE.md README.md .env.example` / `git commit -m "docs: Claude Code 스킬 호환 설명"`

---

## Self-Review

- **스펙 대응:** R1·R2·R3·R9 → Task 1 / R4·R5 → Task 2(가져오기의 R5는 Task 3) / R6 → Task 3 / R7·R7b → Task 3(라우트)·4(화면) / R8 → Task 5 Step 2 / 수용 기준 1~8 → Task 1·2·3·4·5의 테스트·확인 단계로 각각 대응(8은 Task 4 Step 5-c).
- **이름 일관성:** `parse_text`, `list_files`, `read_file`, `import_source_dir`, `importable`, `import_skill`, 상수 `MAX_DESCRIPTION`·`REFERENCE_EXTS`·`MAX_READ_CHARS`·`IMPORT_LABEL` 모두 정의 Task와 사용 Task가 같다. 라우트 함수 이름 `_skill_parse`는 Task 3 테스트가 쓰므로 구현 때 그 이름으로 만든다.
- **비례:** 계획 길이는 스펙의 약 2배이고 코드 본문은 넣지 않았다.
- **열린 위험:** 저장소에 프론트 테스트가 없어 Task 4는 수동 Playwright 확인에 의존한다. `confirm()` 대신 행 안 2단계 확인을 쓰는 이유는 브라우저 모달이 자동화와 접근성에 방해가 되기 때문이다.
