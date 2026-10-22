# UML 클래스 다이어그램

이 코드베이스는 클래스보다 **모듈과 함수** 중심이다. 클래스는 `Handler`, `Meter`, `StdioServer`, `HttpServer` 등 소수이고, 나머지는 모듈 수준 함수와 딕셔너리 형태의 데이터(`entry`)다. 다이어그램은 모듈을 클래스 상자로 그려 책임과 의존을 보여 준다. 데이터 모양은 [데이터 저장소 설계](database-design.md)를 본다.

## 1. 레이어 구조

```mermaid
classDiagram
    class Handler {
        +do_GET()
        +do_POST()
        -_send(code, body, content_type, headers)
        -_json(payload, code, headers)
        -_static(name)
    }
    class AppModule {
        +ROUTES dict
        +NO_LOCK set
        +LOCK Lock
        +route(path, lock)
        +state() dict
        +handle_chat(payload) dict
        +catalog() dict
        +main()
    }
    class Orchestrator {
        +start(role_name) dict
        +stop(role_name) dict
        +status() list
        +research(question, follow_up) dict
        +request_stop() dict
        +progress() dict
        +cleanup_stale() list
    }
    class Roles {
        +ROLES dict
        +ORDER list
        +ORCHESTRATOR_PROMPT str
        +prompt_for(role_name) str
        +prompts_view() list
        +set_prompt(role_name, text)
        +tools_for(role_name) tuple
    }
    class Runner {
        +run(message, entries, prompt, web_search, max_steps, history, should_stop, trace, on_context) dict
        +system_prompt() str
        +load_chat() list
        +save_chat(turns)
    }
    class Registry {
        +build(include_mcp) tuple
        +declarations(entries) list
        +find(entries, name) dict
        +overrides() dict
        +disable_mcp_tool(source, name)
    }
    class Llm {
        +call(system_prompt, items, declarations, web_search, temperature, trace) dict
        -_post(payload, settings, timeout, retries)
        -_messages(system_prompt, items) list
    }
    class McpClient {
        +connect_all(path) tuple
        +read_config(path) tuple
        +expand_env(value)
        +reset()
    }
    class Config {
        +HOST str
        +PORT int
        +llm_settings() dict
        +save_llm_settings(payload) dict
        +trusted_origins() tuple
        +access_token() str
        +api_key() str
    }
    class HttpSecurity {
        +validate_local_host(handler, port, trusted_origins, access_token)
        +validate_json_post(handler, port, max_body, browser_origins, trusted_origins, access_token) int
    }
    class Datafile {
        +read_data_file(name) dict
        +save_upload(name, data_b64) dict
        +delete_file(name) dict
        +listing_detail() list
    }
    class Tools {
        +TOOLS list
        +note_search(text) dict
        +note_save(text) dict
        +note_delete(text) dict
        +note_update(target, find, replace) dict
    }
    class ContextMeter {
        +prepare(prompt, declarations, history) dict
        +update(prompt, items, declarations)
        +finish(failed)
        +snapshot() dict
        +invalidate()
    }
    class ChildServer {
        +serve(role_name)
    }

    AppModule ..> Handler : 서버에 연결
    Handler ..> HttpSecurity : 요청 검증
    AppModule ..> Orchestrator : 연구 실행
    AppModule ..> Runner : 도구 탭 대화
    AppModule ..> Registry : 도구 목록
    AppModule ..> ContextMeter : 계기판
    AppModule ..> Datafile : 자료 업로드
    Orchestrator ..> Roles : 역할과 지침
    Orchestrator ..> Runner : 위임 도구로 실행
    Orchestrator ..> ChildServer : 프로세스로 기동
    ChildServer ..> Roles : prompt_for, tools_for
    ChildServer ..> Runner : 작업 실행
    Roles ..> Datafile : 실험 담당 도구
    Roles ..> Registry : 조사 담당 MCP 도구
    Runner ..> Llm : 모델 호출
    Runner ..> Registry : 선언과 조회
    Registry ..> Tools : 내장 도구
    Registry ..> McpClient : MCP 도구
    Llm ..> Config : 설정과 키
    Orchestrator ..> Config : 포트와 경로
```

`..>`는 의존(호출) 관계다. 순환 의존이 없도록 `roles`는 `datafile`/`registry`를 함수 안에서 늦게 import한다.

## 2. 도구 항목(entry) 구조

도구는 클래스가 아니라 딕셔너리다. 내장 도구, MCP 도구, 위임 도구, 연구 자료 읽기 도구가 모두 같은 모양을 쓰기 때문에 `runner.run`은 출처를 구분하지 않는다.

```mermaid
classDiagram
    class ToolEntry {
        +name str
        +description str
        +parameters dict
        +source str
        +call(args) result
    }
    class BuiltinEntry {
        +default_description str
        +source 내장
    }
    class McpEntry {
        +source 서버 이름
    }
    class DelegateEntry {
        +source 위임
    }
    class DataFileEntry {
        +source 내장
    }

    BuiltinEntry --|> ToolEntry
    McpEntry --|> ToolEntry
    DelegateEntry --|> ToolEntry
    DataFileEntry --|> ToolEntry
```

| 종류 | 만드는 곳 | 누가 보는가 |
|------|-----------|-------------|
| BuiltinEntry | `registry._builtin()` — `memo_tool_1~4` | 도구 탭 대화 |
| McpEntry | `mcp_client.connect_all()` | 도구 탭 대화, 자료조사 연구원 |
| DelegateEntry | `orchestrator._delegate_entries()` — `delegate_research`, `delegate_experiment` | 연구책임자만 |
| DataFileEntry | `roles.tools_for("experiment")` — `read_data_file` | 실험수행 연구원만 |

도구 경계는 코드로 강제된다. 자료조사는 MCP 도구와 웹 검색만, 실험수행은 `read_data_file`만 받는다. 내장 메모 도구는 어느 연구원에게도 주지 않는다.

## 3. HTTP 서버와 MCP 연결

```mermaid
classDiagram
    class BaseHTTPRequestHandler
    class Handler
    class ChildHandler {
        +do_GET()
        +do_POST()
    }
    class RequestRejected {
        +status int
        +headers dict
    }
    class StdioServer {
        +request(method, params, timeout) dict
        +close()
    }
    class HttpServer {
        +request(method, params, timeout) dict
        -_post(payload, timeout)
    }
    class MissingEnv

    Handler --|> BaseHTTPRequestHandler
    ChildHandler --|> BaseHTTPRequestHandler
    RequestRejected --|> Exception
    MissingEnv --|> Exception
    McpClient ..> StdioServer : command 설정
    McpClient ..> HttpServer : url 설정
    Handler ..> RequestRejected : 잡아서 응답
    ChildHandler ..> RequestRejected : 잡아서 응답
```

## 4. 오류 타입과 계기판

```mermaid
classDiagram
    class QuotaExceeded
    class LLMError
    class Meter {
        -_signature
        -_value dict
        +prepare(prompt, declarations, history) dict
        +update(prompt, items, declarations)
        +finish(failed)
        +snapshot() dict
        +invalidate()
    }

    QuotaExceeded --|> Exception
    LLMError --|> Exception
    Runner ..> QuotaExceeded : 전파
    Runner ..> LLMError : 전파
    AppModule ..> Meter : CONTEXT_METER
```

- `QuotaExceeded`: HTTP 429(분당 한도 또는 잔액). 화면에는 "잠시 후 다시 시도" 문구로 바꿔 보여 준다.
- `LLMError`: 그 밖의 API·네트워크 오류. 메시지에 키를 담지 않는다. Ollama는 접두사 `network:`로 연결 실패와 거부를 구분한다.
- `Meter`: Instructions · Tools · Context 비중을 글자 수로 추정하고, 응답의 실제 사용량이 오면 그 값에 맞춰 비율을 조정한다. 저장된 대화는 서명(`prepare`의 캐시 키)에 넣지 않는다. 넣으면 대화가 끝날 때마다 실측값이 추정값으로 덮인다.
