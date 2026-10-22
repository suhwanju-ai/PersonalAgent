# UML 시퀀스 다이어그램

핵심 흐름을 시나리오별로 정리했다. 구조는 [시스템 아키텍처](system-architecture.md), 경로 명세는 [API 설계](api-design.md)를 본다.

## 1. 요청 검증 · 인증 (모든 요청 공통)

이 앱에는 사용자 계정이 없다. 로그인 대신 **Host/Origin 검사 + 외부 접속 시 Basic 인증**이 인증 역할을 한다.

```mermaid
sequenceDiagram
    participant C as 클라이언트
    participant H as Handler
    participant S as http_security

    C->>H: 요청 (Host, Origin, Authorization)
    H->>S: validate_local_host
    alt Host가 허용 목록에 없음
        S-->>H: RequestRejected 403
        H-->>C: 403 요청한 호스트를 허용하지 않습니다
    else 신뢰 origin으로 들어옴
        alt APP_ACCESS_TOKEN 미설정
            S-->>H: RequestRejected 403
            H-->>C: 403 외부 접속에는 토큰 설정이 필요합니다
        else Authorization 없음 또는 비밀번호 불일치
            S-->>H: RequestRejected 401
            H-->>C: 401 + WWW-Authenticate Basic
        else 비밀번호 일치
            S-->>H: 통과
        end
    else 루프백 접속
        S-->>H: 통과 (인증 없음)
    end
    Note over H,S: POST는 이어서 Origin, Sec-Fetch-Site, Content-Type, 본문 크기를 검사한다
```

## 2. 도구 탭 대화 (`POST /api/chat`)

모델은 어떤 도구를 부를지 **결정만** 하고, 실행은 `runner.run()`이 한다.

```mermaid
sequenceDiagram
    participant B as 브라우저
    participant A as app.py
    participant R as runner.run
    participant L as llm.call
    participant M as 모델 API
    participant T as 도구 entry

    B->>A: POST /api/chat message
    A->>A: LOCK 획득, 저장된 대화 로드
    A->>R: run(message, entries, history)
    loop 최대 6단계
        R->>L: call(prompt, items, declarations)
        L->>M: chat/completions
        M-->>L: 메시지 또는 tool_calls
        L-->>R: items, calls, usage
        alt 도구 호출 없음
            R-->>A: answer
        else 도구 호출 있음
            R->>T: call(args)
            T-->>R: 결과 (예외는 오류 dict로 변환)
            R->>R: function_call_output 항목 추가
        end
    end
    A->>A: 성공한 턴만 chat_history.json 저장
    A-->>B: ok, answer, calls, chat, context_window
```

- 도구가 예외를 던져도 앱은 죽지 않는다. `{"오류": ...}`로 모델에게 돌려줘 재시도하게 한다.
- 모든 `function_call`에는 짝이 되는 `function_call_output`이 있어야 한다. 중지하는 경우에도 채운다.
- 6단계를 다 쓰고도 끝나지 않으면 "요청을 끝내지 못했습니다" 문구로 마친다.

## 3. 연구 요청 (`POST /api/research`) — 핵심 비즈니스 흐름

```mermaid
sequenceDiagram
    participant B as 브라우저
    participant A as app.py
    participant O as orchestrator
    participant R as runner.run
    participant RS as 자료조사 연구원 8771
    participant EX as 실험수행 연구원 8772

    B->>A: POST /api/research question
    A->>A: LOCK 획득 (연구가 끝날 때까지 유지)
    A->>O: begin(question) 도는 중 표시
    loop 꺼져 있는 연구원
        A->>O: start(role)
        O-->>A: READY 확인
    end
    A->>O: research(question)
    O->>R: run(prompt=ORCHESTRATOR_PROMPT, 위임 도구 2개)
    loop 최대 10단계
        R->>O: delegate_research 또는 delegate_experiment
        O->>O: 로그에 delegate 기록
        alt 자료조사
            O->>RS: POST /task instruction
            RS-->>O: result, calls, trace
        else 실험수행
            O->>EX: POST /task instruction
            EX-->>O: result, calls, trace
        end
        O->>O: 로그에 return 기록
        O-->>R: 연구원 보고
    end
    R-->>O: 최종 답
    O->>O: 로그에 final 기록, 도는 중 표시 해제
    O-->>A: answer, log
    A-->>B: ok, answer, log
    par 연구 중 폴링
        B->>A: GET /api/research/progress (락 없음)
        A-->>B: running, log
    end
```

- 연구책임자는 위임 도구 둘만 가진다. 직접 조사하거나 코드를 짜지 못한다.
- 연구원끼리는 서로를 부를 수단이 없다. 한 연구원의 결과는 연구책임자가 지시문에 담아 다음 연구원에게 전달한다.
- 연구원은 호출 때마다 `roles.prompt_for(role)`로 지침을 읽는다.
- 연구원 호출 한 번의 제한 시간은 600초다.

## 4. 연구 중지와 에러 처리

```mermaid
sequenceDiagram
    participant B as 브라우저
    participant A as app.py
    participant O as orchestrator
    participant R as runner.run
    participant EX as 연구원

    Note over A,R: /api/research가 LOCK을 쥔 채 실행 중
    B->>A: POST /api/research/stop (lock=False)
    A->>O: request_stop
    O->>O: _PROGRESS stop = True
    O-->>A: ok 중지를 요청했습니다
    A-->>B: ok
    R->>R: 다음 단계 전 should_stop 확인
    alt 연구원 호출이 아직 진행 중
        EX-->>R: 호출은 끝까지 진행 (끊지 못함)
        R->>R: 남은 호출은 사용자가 중지했습니다 로 채움
    end
    R-->>O: stopped = true, 중지했습니다 답
    O-->>B: 연구 응답 (stopped true)
```

모델 호출 실패 시의 처리는 다음과 같다.

```mermaid
sequenceDiagram
    participant O as orchestrator
    participant L as llm
    participant M as 모델 API

    O->>L: call
    L->>M: POST chat/completions
    alt HTTP 429
        M-->>L: 429
        L-->>O: QuotaExceeded
        O-->>O: 호출 한도에 걸렸습니다 응답
    else 500 502 503 504
        M-->>L: 5xx
        L->>L: 2초 후 1회 재시도
        L->>M: 재요청
        M-->>L: 결과 또는 오류
    else 네트워크 오류
        L->>L: 로컬 시간 초과면 재시도 없음, 아니면 1회 재시도
        L-->>O: LLMError network
    else 연구원이 응답하지 않음
        O->>O: 연구원에게 연결하지 못했습니다 보고로 변환
    end
```

## 5. 연구원 지침 저장과 반영

```mermaid
sequenceDiagram
    participant B as 브라우저
    participant A as app.py
    participant RO as roles
    participant F as role_prompts.json
    participant EX as 연구원 프로세스

    B->>A: POST /api/agents/prompt role, text (락 없음)
    A->>RO: set_prompt(role, text)
    RO->>RO: 역할, 타입, 길이 검증
    alt 빈 값이거나 기본 지침과 같음
        RO->>F: 해당 역할 키 삭제
        Note right of F: 키가 모두 사라지면 파일 삭제
    else 편집본
        RO->>F: 임시 파일에 쓰고 os.replace
    end
    A-->>B: ok, prompts
    Note over EX: 재시작 없음
    B->>A: POST /api/research (다음 위임)
    A->>EX: POST /task
    EX->>RO: prompt_for(role)
    RO->>F: 매번 읽음
    RO-->>EX: 편집본 또는 기본 지침
```

## 6. MCP 서버 추가 (`POST /api/mcp/add`)

```mermaid
sequenceDiagram
    participant B as 브라우저
    participant A as app.py
    participant FS as state와 mcp_config
    participant MC as mcp_client
    participant SV as 원격 MCP 서버

    B->>A: POST /api/mcp/add name, url
    A->>A: 이름, 예약어, 중복, 주소 형식 검증
    A->>FS: mcp_custom.json에 서버 추가
    A->>FS: mcp_config.json에 연결 목록 기록
    A->>MC: reset 후 registry.build
    MC->>MC: URL의 변수 자리표시자를 env 값으로 치환 (메모리만)
    MC->>SV: initialize, tools/list
    SV-->>MC: 도구 목록
    MC-->>A: entries, errors
    A-->>B: ok, tools 개수, errors
```

## 7. 앱 기동과 종료

```mermaid
sequenceDiagram
    participant U as 사용자
    participant A as app.py main
    participant O as orchestrator
    participant RG as registry

    U->>A: run.bat 또는 python app.py
    A->>A: notes.json 없으면 seed에서 생성
    A->>O: cleanup_stale
    O->>O: 8771, 8772에 /info 확인 후 같은 역할이면 종료
    A->>RG: build 후 도구 목록 출력
    A->>A: 127.0.0.1:8770 에서 serve_forever
    A->>U: 브라우저 열기 (1초 뒤)
    U->>A: Ctrl+C 또는 창 닫기
    A->>O: stop_all (연구원 종료)
    A->>RG: mcp_client.reset
```

Windows에서 부모 창을 강제로 닫으면 `atexit`이 돌지 않아 자식이 남을 수 있다. 그래서 기동 때 `cleanup_stale`로 한 번 더 정리한다.

## 8. 스킬로 HTML 문서 만들기

```mermaid
sequenceDiagram
    participant B as 브라우저
    participant A as app.py
    participant R as runner.run
    participant M as 모델 API
    participant SK as skills
    participant HR as html_render
    participant FS as state outputs

    B->>A: POST /api/chat 결과를 HTML로 만들어줘
    A->>R: run(message, entries)
    R->>M: 도구 목록 (use_skill 설명에 스킬 이름과 설명)
    M-->>R: use_skill name html 호출
    R->>SK: use_skill(html)
    SK-->>R: html 스킬 지침 본문
    R->>M: 지침을 읽은 결과
    M-->>R: render_html title, markdown, register 호출
    R->>SK: render_html(args)
    SK->>HR: from_markdown 후 render
    HR-->>SK: 이스케이프된 HTML 문서
    SK->>HR: save(html)
    HR->>FS: state outputs id html 저장
    SK-->>R: 표시 줄 html 마커와 id
    R->>M: 도구 결과
    M-->>R: 최종 답변 (마커 한 줄 포함)
    Note over R: 모델이 마커를 빠뜨리면 답변 끝에 붙인다
    R-->>A: answer
    A-->>B: ok, answer
    B->>A: GET /api/output?id=id (마커를 만나면)
    A->>FS: load(id)
    A-->>B: HTML (sandbox 헤더)
    Note over B: sandbox iframe 미리보기와 다운로드 버튼
```

오류 흐름: 마크다운이나 형식이 틀리면 `render_html`이 `{"오류": ...}`를 돌려주고 모델이 고쳐 다시 부른다. 에이전트 탭에서는 같은 흐름을 연구책임자가 쓴다(연구원에게는 스킬 도구가 없다).

## 9. 스킬 추가·수정·삭제

```mermaid
sequenceDiagram
    participant B as 브라우저
    participant A as app.py
    participant SK as skills
    participant FS as skills 폴더
    participant RG as registry

    B->>A: POST /api/skills/save name, description, tools, body
    A->>SK: save(...)
    SK->>SK: 이름 형식, 길이, 허용된 도구인지 검사
    alt 검사 실패
        SK-->>A: ValueError
        A-->>B: ok false, message
    else 통과
        SK->>FS: skills 이름 폴더의 SKILL.md 쓰기 (같은 이름이면 덮어씀)
        A-->>B: ok, skills 목록
        B->>A: GET /api/state (갱신)
        A->>RG: build
        RG->>SK: entries (매번 폴더를 다시 읽음)
        SK-->>RG: use_skill과 스킬이 고른 도구
        A-->>B: tools에 반영
    end
```

앱을 다시 켜지 않아도 다음 요청부터 반영되는 이유는 `registry.build()`가 부를 때마다 스킬 폴더를 새로 읽기 때문이다. 삭제(`/api/skills/delete`)도 같은 방식으로 `SKILL.md`를 지우고 목록을 다시 읽는다.
