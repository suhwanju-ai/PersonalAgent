# 데이터 저장소 설계 문서

Common Agent에는 **데이터베이스가 없다.** 모든 영속 데이터는 앱 폴더 안의 JSON·텍스트·CSV 파일이며, 표준 라이브러리 `json`과 파일 입출력으로만 다룬다. 이 문서는 DB 설계 문서의 자리에서 파일 저장소를 설명한다. 엔티티 관계는 [ER 다이어그램](er-diagram.md)을 본다.

관련 문서: [시스템 아키텍처](system-architecture.md) · [API 설계](api-design.md)

## 1. 개요

| 항목 | 내용 |
|------|------|
| 저장 방식 | 파일 시스템 (JSON / 텍스트 / CSV) |
| 인코딩 | UTF-8. 읽을 때는 BOM을 허용하는 곳(`utf-8-sig`)이 있다 |
| 트랜잭션 | 없음. 일부 파일은 임시 파일 + `os.replace`로 원자적 교체 |
| 동시성 | 본체의 전역 `LOCK`이 대부분의 쓰기를 직렬화한다. 지침 파일은 별도 `_PROMPT_WRITE_LOCK` |
| 마이그레이션 | 없음. 스키마는 코드가 읽을 때 방어적으로 해석한다 (깨진 파일은 빈 값으로 취급) |
| 백업 | `state/`와 `data/research/`를 복사하면 된다 |

저장 위치는 두 곳이다.

- `state/` — **런타임 상태.** 앱이 처음 쓸 때 만든다. `.gitignore` 대상.
- `data/` — **자료.** `data/seed/notes.json`(원본 샘플), `data/notes.json`(작업본, git 제외), `data/research/`(연구 자료).

## 2. 파일 목록

| 파일 | 한글 설명 | 형식 | 쓰는 곳 | 없을 때 |
|------|-----------|------|---------|---------|
| `state/llm_settings.json` | 모델 제공자·모델 이름·Ollama 주소 | JSON 객체 | `config.save_llm_settings` | `.env` 기본값 + OpenRouter |
| `state/system_prompt.txt` | 도구 탭의 역할 지시문 | 텍스트 | `runner.set_system_prompt` | `DEFAULT_SYSTEM_PROMPT` |
| `state/role_prompts.json` | 화면에서 고친 연구원 지침 | JSON `{역할: 지침}` | `roles.set_prompt` | `roles.py`의 기본 지침 |
| `state/chat_history.json` | 도구 탭 대화 기록 | JSON `{"turns": [...]}` | `runner.save_chat` | 빈 대화 |
| `state/tool_overrides.json` | 내장 도구 설명문 덮어쓰기 | JSON `{도구: 설명}` | `registry.set_override` | 코드의 기본 설명 |
| `state/mcp_custom.json` | 화면에서 주소로 추가한 MCP 서버 | JSON `{이름: {...}}` | `app.write_custom_servers` | 없음 |
| `state/disabled_mcp_tools.json` | 제외한 MCP 도구 | JSON `[[서버, 도구], ...]` | `registry.disable_mcp_tool` | 제외 없음 |
| `state/data_path.txt` | 메모 파일 경로 덮어쓰기 | 텍스트(경로 한 줄) | (파일 직접 편집) | `data/notes.json` |
| `mcp_config.json` | 지금 연결한 MCP 서버 | JSON `{"mcpServers": {...}}` | `app.write_mcp_config` | 연결 없음 |
| `mcp_catalog.json` | 연결 가능한 MCP 서버 기본 목록 | JSON | (수동 편집) | 직접 추가한 서버만 |
| `data/notes.json` | 메모 도구가 다루는 메모 | JSON 배열 | `tools._save` | 시작 시 seed에서 복사 |
| `data/seed/notes.json` | 메모 원본 샘플 | JSON 배열 | (수동) | - |
| `data/research/*.csv·txt·json` | 연구 자료 | 텍스트 | `datafile.save_upload` | 비어 있음 |

> `state/tool_overrides.json`을 쓰는 함수(`registry.set_override`)는 있으나 **현재 이 함수를 부르는 화면 라우트는 없다.** 파일을 직접 만들면 적용된다.

## 3. 파일 상세

### 3.1 `state/llm_settings.json`

| 키 | 타입 | 설명 |
|----|------|------|
| `provider` | string | `openrouter` 또는 `ollama` |
| `model` | string | 현재 제공자의 모델 이름 (1~160자) |
| `openrouter_model` | string | OpenRouter용 모델 이름 |
| `ollama_model` | string | Ollama용 모델 이름 |
| `ollama_base_url` | string | `http(s)://호스트/v1`. 링크로컬 주소 거부 |

읽기는 `config.llm_settings()`가 파일 수정 시각(`st_mtime_ns`)이 같으면 캐시를 쓴다. 저장하면 캐시를 비운다. 이 파일에 BOM이 붙으면 JSON 읽기가 실패해 **조용히 OpenRouter 기본값으로 돌아간다.** Windows PowerShell 5.1의 `Set-Content -Encoding utf8`이 BOM을 붙이므로 직접 편집할 때 주의한다.

### 3.2 `state/role_prompts.json`

```json
{ "research": "고친 자료조사 지침 전문", "experiment": "고친 실험수행 지침 전문" }
```

- 키는 `research`·`experiment`만 유효. 값은 공백이 아닌 문자열이어야 한다. 아니면 기본 지침을 쓴다.
- 편집본이 없는 역할은 키 자체가 없다. 모든 편집본이 사라지면 **파일을 지운다.**
- 최대 20,000자(`ROLE_PROMPT_MAX_CHARS`). 저장 시 `\r\n`을 `\n`으로 바꾸고 양 끝 공백을 자른다.
- 연구원 프로세스가 작업마다 읽으므로 본체와 연구원이 같은 파일을 공유한다.

### 3.3 `state/chat_history.json`

```json
{ "turns": [ { "message": "...", "answer": "...", "calls": [], "at": 1760000000.0, "items": [] } ] }
```

| 필드 | 설명 |
|------|------|
| `message` | 사용자 요청 |
| `answer` | 최종 답 |
| `calls` | 도구 호출 요약 `{tool, source, args, result}` |
| `at` | 저장 시각(epoch 초) |
| `items` | 그 턴에 새로 생긴 API 입력 항목 (메시지·`function_call`·`function_call_output`) |

턴 단위로 저장하는 이유: 오래된 턴을 지울 때 `function_call`과 `function_call_output`의 짝이 깨지지 않게 하려는 것이다. 최근 30턴(`CHAT_MAX_TURNS`)만 남긴다. 파일이 깨졌으면 빈 대화로 취급한다.

### 3.4 `state/mcp_custom.json`

```json
{ "서버이름": { "label": "서버이름", "detail": "직접 추가한 원격 서버 · <주소>", "spec": {"url": "..."}, "custom": true } }
```

서버 이름은 도구의 소속(`source`)이 된다. 예약어 `내장`·`위임`·`알 수 없음`은 쓸 수 없다. 기본 카탈로그와 이름이 겹치면 기본 카탈로그가 이긴다.

### 3.5 `mcp_config.json` · `mcp_catalog.json`

```json
{ "mcpServers": { "국가법령": { "url": "https://mcp.gomdori.app/law" } } }
```

- 항목은 `{"url": ...}`(원격 HTTP) 또는 `{"command": ..., "args": [...]}`(로컬 stdio).
- 값에 `${VAR}`를 적으면 연결할 때 `.env`로 채운다. **채운 값은 메모리에만 두고 파일·로그에 쓰지 않는다.**

### 3.6 `data/notes.json` (메모)

| 필드 | 타입 | 설명 |
|------|------|------|
| `title` | string | 제목. 저장 시 본문 첫 줄 30자 |
| `body` | string | 본문 |
| `date` | string | 날짜. 도구로 저장하면 빈 문자열 |

- 검색·삭제는 **낱말 단위 일치**다. 질의를 공백으로 나눠 낱말 하나라도 제목+본문에 들어 있으면 걸린다.
- 앱이 켜질 때 파일이 없으면 `data/seed/notes.json`으로 만든다. `reset_notes()`는 `state/data_path.txt`도 지운다.

### 3.7 `data/research/`

- 허용 확장자 `.csv`·`.txt`·`.json`, 파일당 2MB.
- 연구원이 읽는 도구 `read_data_file`은 **읽기 전용**이며 이 폴더 밖으로 나가지 못한다 (`basename`만 사용). 한 번에 **6,000자**까지만 돌려주고 넘으면 `…(생략)`을 붙인다.
- 저장소에는 샘플 `line_transition.csv`만 추적된다 (`.gitignore`가 `data/research/*`를 제외하되 이 파일만 예외). 이 파일을 화면에서 지우면 git에는 삭제로 보인다.

## 4. 인덱스·제약

파일 저장소라 DB의 인덱스·외래키는 없다. 대신 아래 규칙이 제약 역할을 한다.

| 규칙 | 위치 |
|------|------|
| 업로드 확장자·크기·인코딩 제한 | `lab/datafile.py` |
| 파일명 경로 이탈 차단 (`basename`) | `datafile._safe` · `_target` |
| 역할 이름 검증 | `roles.set_prompt` |
| 지침 길이 상한 | `roles.ROLE_PROMPT_MAX_CHARS` |
| 모델 이름 길이·주소 형식 검증 | `config.save_llm_settings` |
| 도구 이름 중복 시 먼저 등록된 것 우선 | `registry.build` |

## 5. 쓰기 안전성

| 파일 | 방식 |
|------|------|
| `llm_settings.json`, `chat_history.json`, `role_prompts.json` | 임시 파일(`.tmp`)에 쓰고 `os.replace` — 쓰다 멈춰도 이전 파일이 남는다 |
| `mcp_config.json`, `mcp_custom.json`, `tool_overrides.json`, `disabled_mcp_tools.json`, `notes.json` | 대상 파일에 직접 쓴다. 쓰는 도중 중단되면 깨질 수 있다 |
| `system_prompt.txt`, `data/research/*` | 대상 파일에 직접 쓴다 |

## 6. 운영 메모

- 마이그레이션 전략이 없으므로 키를 추가할 때는 **없는 키를 기본값으로 읽도록** 코드를 짠다 (예: `llm_settings`의 `legacy_model` 처리).
- `state/`를 지우면 모든 화면 설정이 기본값으로 돌아간다. `.env`와 `data/research/`는 영향이 없다.
- 배포 환경에서는 `state/`에 쓰기 권한과 **영구 저장 공간**이 있어야 한다. 없으면 저장 시 "디스크에 저장하지 못했습니다" 메시지가 나온다.
