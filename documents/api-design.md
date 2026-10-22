# API 설계 문서

Common Agent는 브라우저 화면과 JSON API를 한 프로세스(`app.py`, 기본 `http://127.0.0.1:8770/`)에서 제공하는 로컬 웹 앱이다. Python 표준 라이브러리(`http.server`)만 쓰며 외부 프레임워크가 없다. 연구원 두 명은 별도 프로세스로 뜨고, 연구책임자(본체)만 그들의 주소를 안다.

관련 문서: [시스템 아키텍처](system-architecture.md) · [API 사용자 가이드](api-user-guide.md) · [데이터 저장소 설계](database-design.md)

## 1. 공통 규칙

| 항목 | 내용 |
|------|------|
| 형식 | 모든 API는 JSON(`application/json; charset=utf-8`). 응답에 `Cache-Control: no-store` |
| 바인딩 | `127.0.0.1` 고정 (`config.HOST`). 외부 공개는 같은 서버의 리버스 프록시를 거친다 |
| 본체 | `:8770` — 화면(`/`, `/static/*`)과 `/api/*` |
| 연구원 | `:8771`(research) · `:8772`(experiment) — `GET /info`, `POST /task` 만 |
| 요청 본문 상한 | 본체 8MB(`MAX_BODY`), 연구원 1MB |
| 라우팅 | POST는 `@route(path, lock=True)` 데코레이터로 등록. 모르는 경로는 `404 not found`(text/plain) |
| 성공/실패 | 처리 결과는 HTTP 200 + `{"ok": true/false, "message": ...}`. 보안 검사 실패만 4xx 상태 코드 |

### 1.1 요청 검증 (`lab/http_security.py`)

GET과 POST 모두 먼저 `validate_local_host`를 통과해야 한다. POST는 이어서 `validate_json_post`의 나머지 검사를 받는다.

| 순서 | 검사 | 실패 시 |
|------|------|---------|
| 1 | `Host` 헤더가 `127.0.0.1:포트` · `localhost:포트` · 신뢰 origin의 호스트 중 하나 | 403 `요청한 호스트를 허용하지 않습니다.` |
| 2 | 신뢰 origin으로 들어온 요청은 HTTP Basic 인증 (비밀번호 = `APP_ACCESS_TOKEN`, 사용자명은 무엇이든) | 토큰 미설정 403, 인증 없음/틀림 401 + `WWW-Authenticate` |
| 3 | `Origin`이 `http://127.0.0.1:포트` · `http://localhost:포트` · 신뢰 origin 중 하나 (Origin이 없으면 거절) | 403 `허용되지 않은 요청 출처입니다.` |
| 4 | `Sec-Fetch-Site`가 `cross-site`가 아님 | 403 `교차 출처 요청을 허용하지 않습니다.` |
| 5 | `Content-Type`이 `application/json` | 415 `JSON 요청만 허용됩니다.` |
| 6 | `Content-Length`가 유효하고 상한 이하 | 400 / 413 `보낸 내용이 너무 큽니다.` |
| 7 | 본문이 UTF-8 JSON | 400 `요청을 읽지 못했습니다.` |

- 루프백(`127.0.0.1`/`localhost`) 접속은 인증하지 않는다. Host/Origin 검사가 방어선이다.
- 신뢰 origin은 `.env`의 `APP_TRUSTED_ORIGINS`(쉼표 구분)로 지정하며, **시작할 때 한 번만 읽는다.** 바꾸려면 재시작.
- 연구원 서버는 `browser_origins=()`로 호출해 **브라우저가 보낸 Origin 헤더가 있으면 거절**한다. 본체 프로세스만 호출할 수 있다.

### 1.2 락(LOCK) 규칙

모든 POST는 전역 `LOCK` 하나로 줄 세워 처리한다. `/api/research`는 연구가 끝날 때까지(수 분) 이 락을 쥔다. 따라서:

- 연구 중에도 응답해야 하는 POST는 `lock=False`로 등록한다: `/api/research/stop`, `/api/agents/prompt`, `/api/agents/prompt/reset`.
- 연구 중에도 읽어야 하는 GET은 락을 잡지 않는다: `/api/context`, `/api/agents`, `/api/research/progress`. (`/api/state`만 락을 잡는다.)

## 2. GET 엔드포인트

| 경로 | 설명 | 락 |
|------|------|----|
| `/`, `/index.html` | 화면(`static/index.html`) | - |
| `/static/<파일>` | 정적 파일. `basename`만 사용해 상위 경로 접근 차단 | - |
| `/api/state` | 도구 탭·MCP 탭이 쓰는 전체 상태 | 잡음 |
| `/api/context` | Context Window 계기판 스냅샷 | 안 잡음 |
| `/api/agents` | 세 역할의 프로세스 상태 + 연구원 지침 목록 | 안 잡음 |
| `/api/research/progress` | 진행 중인 연구의 로그(폴링용) | 안 잡음 |

### GET `/api/state`

```json
{
  "tools": [{"name": "memo_tool_1", "source": "내장"}],
  "disabled_tools": [{"source": "국가법령", "name": "get_annexes"}],
  "context_window": {"phase": "ready", "...": "측정값"},
  "chat": [{"message": "...", "answer": "...", "calls": [], "at": 1760000000.0}],
  "prompt": "현재 시스템 프롬프트",
  "prompt_default": "기본 시스템 프롬프트",
  "prompt_edited": false,
  "llm_settings": {"provider": "openrouter", "model": "openai/gpt-4o-mini",
                   "openrouter_model": "openai/gpt-4o-mini", "ollama_model": "",
                   "ollama_base_url": "http://localhost:11434/v1"},
  "research_files": [{"name": "line_transition.csv", "bytes": 512}],
  "errors": [],
  "mcp": {"catalog": [{"name": "mslearn", "label": "Microsoft Learn 문서 서버",
                       "detail": "...", "custom": false, "on": false}]}
}
```

`llm_settings`에는 API 키가 들어 있지 않다.

### GET `/api/agents`

```json
{
  "agents": [
    {"role": "orchestrator", "label": "연구책임자 (이 앱)", "up": true, "pid": 1234, "port": 8770,
     "tools": [{"name": "delegate_research", "source": "위임"}, {"name": "delegate_experiment", "source": "위임"}]},
    {"role": "research", "label": "자료조사 연구원", "up": false, "pid": null, "port": 8771,
     "web_search": true, "tools": []}
  ],
  "prompts": [{"role": "research", "label": "자료조사 연구원", "prompt": "...", "default": "...", "edited": false}]
}
```

### GET `/api/research/progress`

```json
{"running": true, "starting": false, "stopping": false, "question": "...", "follow_up": false,
 "started": 1760000000.0, "elapsed": 42.5, "log": [{"kind": "delegate", "to": "research", "label": "자료조사 연구원", "instruction": "...", "at": 1760000001.0}]}
```

`log` 항목의 `kind`는 `delegate`(맡김) · `return`(돌아옴, `trace` 포함) · `final`(최종 답) 세 가지다.

## 3. POST 엔드포인트 (본체 :8770)

| 경로 | 요청 본문 | 성공 응답 | 락 |
|------|-----------|-----------|----|
| `/api/chat` | `{message}` | `{ok, answer, calls, tokens, searches, elapsed, steps, chat, context_window}` | 잡음 |
| `/api/chat/reset` | `{}` | `{ok}` | 잡음 |
| `/api/llm/settings` | `{provider, model, openrouter_model?, ollama_model?, ollama_base_url?}` | `{ok, settings}` | 잡음 |
| `/api/prompt` | `{text}` | `{ok}` | 잡음 |
| `/api/prompt/reset` | `{}` | `{ok}` | 잡음 |
| `/api/agents/prompt` | `{role, text}` | `{ok, prompts}` | **안 잡음** |
| `/api/agents/prompt/reset` | `{role}` | `{ok, prompts}` | **안 잡음** |
| `/api/agents/start` · `/stop` | `{role}` | `{ok, message?, agents}` | 잡음 |
| `/api/agents/start_all` · `/stop_all` | `{}` | `{ok, agents, message}` | 잡음 |
| `/api/research` | `{question, follow_up?}` | `{ok, answer, log, tokens, steps, follow_up, stopped, elapsed, has_session, auto_started}` | 잡음(수 분) |
| `/api/research/stop` | `{}` | `{ok, message}` | **안 잡음** |
| `/api/research/reset` | `{}` | `{ok, has_session: false}` | 잡음 |
| `/api/data/upload` | `{name, data}` (data = base64) | `{ok, name, replaced, files}` | 잡음 |
| `/api/data/delete` | `{name}` | `{ok, name, files}` | 잡음 |
| `/api/mcp/toggle` | `{name, on}` | `{ok, errors}` | 잡음 |
| `/api/mcp/add` | `{name, url, headers?, fixed_args?}` | `{ok, tools, errors}` | 잡음 |
| `/api/mcp/remove` | `{name}` | `{ok, errors}` | 잡음 |
| `/api/mcp/tool/remove` · `/restore` | `{source, name}` | `{ok}` | 잡음 |

### 3.1 도구 탭

**POST `/api/chat`** — 도구 탭 대화 한 턴. 이전 대화(`state/chat_history.json`)를 `history`로 이어 넘기고, **성공한 턴만 저장**한다.

| 실패 상황 | `message` |
|-----------|-----------|
| `message` 비어 있음 | `무엇을 도와드릴지 입력해 주세요.` |
| 쓸 수 있는 도구가 없음 | `쓸 수 있는 도구가 없습니다.` |
| HTTP 429 | `잠시 후 다시 시도해 주세요 (약 1분).` |
| OpenRouter 키 없음 | `.env 파일에 키가 없습니다. OPENROUTER_API_KEY를 확인해 주세요.` |
| Ollama 연결 실패 | `앱 서버에서 Ollama에 연결하지 못했습니다. ...` |
| Ollama가 요청 거부 | `Ollama가 요청을 거부했습니다(HTTP 코드 ...). ...` |
| 그 밖의 API 오류 | `응답을 받지 못했습니다. 잠시 후 다시 시도해 주세요.` |

대화 기록 저장만 실패하면 `ok: true`에 `chat_error: "대화 기록을 저장하지 못했습니다."`가 붙는다.

**POST `/api/llm/settings`** — 검증: `provider`는 `openrouter`/`ollama`, `model`은 1~160자, `ollama_base_url`은 `http(s)://호스트/v1` 형식(사용자 정보·쿼리 금지, **링크로컬 주소 금지**). 경로가 없으면 `/v1`을 붙인다. 저장은 임시 파일 + `os.replace`로 원자적으로 한다.

### 3.2 에이전트 탭

**POST `/api/agents/prompt`** — 연구원 지침 저장. `role`은 `research`/`experiment`. `text`가 비어 있거나 기본 지침과 같으면 편집본을 지운다(= 기본값 복귀). 20,000자를 넘으면 거절한다. 저장 즉시가 아니라 **다음 위임부터** 적용된다.

| 실패 | `message` |
|------|-----------|
| 모르는 역할 | `그런 역할이 없습니다.` |
| 문자열이 아님 | `지침을 문자열로 보내 주세요.` |
| 길이 초과 | `지침은 20000자를 넘을 수 없습니다.` |
| 디스크 오류 | `지침을 디스크에 저장하지 못했습니다. state/ 폴더 쓰기 권한을 확인해 주세요.` |

**POST `/api/research`** — 연구 한 건을 끝까지 실행한다. 꺼져 있는 연구원은 여기서 자동으로 띄운다(`auto_started`에 이름이 담김). `follow_up: true`이고 앞선 세션이 있을 때만 이어서 묻는다. 진행 상황은 `/api/research/progress`를 폴링해 읽는다.

| 실패 | `message` |
|------|-----------|
| 질문 비어 있음 | `연구 질문을 입력해 주세요.` |
| 연구원 기동 실패 | `<연구원 이름>을(를) 띄우지 못했습니다. ...` |
| 호출 한도 | `호출 한도에 걸렸습니다. 잠시 후 다시 시도해 주세요.` |
| 기타 | `처리하지 못했습니다: ...` |

**POST `/api/research/stop`** — 다음 차례를 시작하지 않게 한다. **이미 연구원에게 맡긴 호출은 끊지 못하고**, 그것이 끝난 뒤에 멈춘다. 진행 중인 연구가 없으면 `{ok:false, message:"진행 중인 연구가 없습니다."}`.

### 3.3 연구 자료

**POST `/api/data/upload`** — `data/research/`에 저장한다. 폴더는 항상 이 하나뿐이다.

| 규칙 | 값 |
|------|----|
| 허용 확장자 | `.csv` `.txt` `.json` |
| 크기 상한 | 2MB (`MAX_UPLOAD`) |
| 인코딩 | UTF-8(BOM 허용). 아니면 거절 |
| 파일명 | `basename`만 사용, `.`으로 시작하는 이름 거절 |
| 같은 이름 | 덮어쓴다(`replaced: true`). 덮어쓸지는 화면이 먼저 확인 |

**POST `/api/data/delete`** — 삭제는 되돌릴 수 없다.

### 3.4 MCP

- `/api/mcp/toggle`: 카탈로그에 있는 서버만 켜고 끈다. 결과를 `mcp_config.json`에 쓰고 연결을 초기화한다.
- `/api/mcp/add`: 이름 40자 이하, 예약어 `내장`·`위임`·`알 수 없음` 불가, 중복 불가, 주소는 `http://` 또는 `https://`이며 공백 불가. `headers`는 `이름: 값` 줄 문자열 또는 `{이름: 값}` 객체이며 20개, 값 2,000자 이하, 제어 문자 불가, `Host`·`Content-Type`·`Accept`·`Mcp-*` 등 예약 헤더 불가. 키는 주소와 헤더 값에 `${변수명}`으로 적으면 연결 시점에 `.env`에서 채운다. 추가 즉시 연결한다. `fixed_args`는 `이름: 값` 줄 문자열 또는 객체(20개 이하)이며, 인증값을 도구 인자로 받는 서버용이다. 그 서버의 모든 `tools/call` 인자에 자동으로 합쳐지고(모델이 같은 이름을 넣어도 고정값 우선) 모델에게 주는 도구 스키마에서는 빠진다. 화면 목록에는 헤더·고정 인자의 이름만 보이고 값은 노출하지 않는다.
- `/api/mcp/remove`: **직접 추가한 서버만** 삭제 가능(`state/mcp_custom.json`). 기본 카탈로그 서버는 연결만 끊을 수 있다.
- `/api/mcp/tool/remove`·`restore`: 서버 단위가 아닌 **도구 단위**로 제외/복원 (`state/disabled_mcp_tools.json`).

## 4. 연구원 서버 (:8771 / :8772)

`agents/_serve.py`가 두 연구원을 같은 코드로 띄운다. 달라지는 것은 역할 지침과 도구뿐이다.

| 메서드·경로 | 설명 |
|-------------|------|
| `GET /info` | `{ok, role, label, pid, port, web_search, tools, errors}` |
| `POST /task` | 본문 `{instruction}` → `{ok, result, calls, searches, tokens, elapsed, steps, trace}` |

- 기동하면 표준 출력에 `READY <role> <port> <pid>` 한 줄을 쓴다. **부모가 이 줄로 기동을 확인하므로 형식을 바꾸면 안 된다.**
- `POST /task`는 호출 때마다 `roles.prompt_for(role)`로 지침을 읽는다 → 화면에서 고친 지침이 재시작 없이 반영된다.
- `trace`는 연구원이 모델과 주고받은 요청·응답, 실행한 도구 호출의 순서 기록이다.
- 본체의 `_send()`가 호출하며 제한 시간은 600초다.

## 5. 외부 호출 (아웃바운드)

| 대상 | 경로 | 제한 시간 | 비고 |
|------|------|-----------|------|
| OpenRouter | `https://openrouter.ai/api/v1/chat/completions` | 150초 | `Authorization: Bearer <키>`. 429는 즉시 `QuotaExceeded`, 500/502/503/504·네트워크 오류는 1회 재시도 |
| Ollama | `<설정한 주소>/chat/completions` | 600초 | 인증 없음. 시간 초과는 재시도하지 않음 |
| MCP(stdio) | 자식 프로세스 | 요청당 20초 | `mcp_config.json`의 `command`/`args` |
| MCP(HTTP) | Streamable HTTP | 요청당 30초 | 프로토콜 버전 `2025-06-18` |

모델 요청은 `temperature 0.0`, `stream: false`다. 웹 검색이 켜진 연구원(자료조사)은 OpenRouter일 때만 `plugins: [{"id":"web","engine":"native"}]`를 붙인다. Ollama에는 웹 검색 플러그인이 없다.

## 6. 인증·비율 제한·페이지네이션

- **인증**: 루프백은 없음. 신뢰 origin은 Basic 인증(`APP_ACCESS_TOKEN`). 토큰이 없으면 신뢰 origin 접속 자체를 거부한다.
- **비율 제한**: 앱 자체에는 없다. 모델 쪽 429만 처리한다.
- **페이지네이션**: 없다. 대화 기록은 최근 30턴(`CHAT_MAX_TURNS`)만 유지한다.
- **에러 응답 형식**: 보안 검사 실패는 `{"ok": false, "message": "..."}` + 4xx(GET은 text/plain). 업무 실패는 HTTP 200 + `ok: false`.
