# API 사용자 가이드

이 앱의 API는 화면을 위한 것이지만, 같은 PC에서 스크립트로 호출할 수도 있다. 이 문서는 개발자가 처음 호출해 보는 순서를 안내한다. 전체 명세는 [API 설계 문서](api-design.md)를 본다.

## 1. 시작하기

### 1.1 서버 켜기

설치·실행 절차는 [프로그램 사용 설명서](user-guide.md)를 따른다. 켜지면 `http://127.0.0.1:8770/`에서 응답한다.

### 1.2 인증

| 접속 방식 | 인증 |
|-----------|------|
| 같은 PC에서 `127.0.0.1` 또는 `localhost`로 접속 | 없음 |
| 리버스 프록시의 공개 주소로 접속 (`.env`의 `APP_TRUSTED_ORIGINS`에 등록) | HTTP Basic. 사용자명은 아무거나, 비밀번호는 `APP_ACCESS_TOKEN` |

토큰 발급 절차는 없다. `.env`에 직접 긴 임의 문자열을 적고 앱을 재시작한다.

### 1.3 첫 호출

GET은 헤더 없이 된다.

```bash
curl http://127.0.0.1:8770/api/agents
```

**POST는 반드시 세 가지를 지켜야 한다.** 하나라도 빠지면 거절된다.

1. `Content-Type: application/json`
2. `Origin: http://127.0.0.1:8770` (브라우저가 아닌 클라이언트는 직접 붙여야 한다)
3. `Host`가 `127.0.0.1:8770` 또는 `localhost:8770` (curl이 URL에서 자동으로 채운다)

```bash
curl -X POST http://127.0.0.1:8770/api/chat \
  -H "Content-Type: application/json" \
  -H "Origin: http://127.0.0.1:8770" \
  -d '{"message": "회의 메모 찾아줘"}'
```

## 2. 언어별 예제

### 2.1 Python (`urllib`, 표준 라이브러리)

```python
import json
import urllib.request

BASE = "http://127.0.0.1:8770"

def post(path, payload):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Origin": BASE},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.loads(r.read().decode("utf-8"))

print(post("/api/chat", {"message": "회의 메모 찾아줘"})["answer"])
```

### 2.2 JavaScript (`fetch`)

브라우저 콘솔에서 앱 화면이 열린 탭이라면 `Origin`은 브라우저가 붙여 준다.

```javascript
const res = await fetch("/api/chat", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ message: "회의 메모 찾아줘" }),
});
const data = await res.json();
console.log(data.ok ? data.answer : data.message);
```

### 2.3 공개 주소(Basic 인증)로 호출

```bash
curl -u ":$APP_ACCESS_TOKEN" -X POST https://agent.example.com/api/chat \
  -H "Content-Type: application/json" \
  -H "Origin: https://agent.example.com" \
  -d '{"message": "안녕"}'
```

## 3. 주요 시나리오

### 시나리오 A — 모델 바꾸기

```bash
# OpenRouter 모델 바꾸기
curl -X POST http://127.0.0.1:8770/api/llm/settings -H "Content-Type: application/json" \
  -H "Origin: http://127.0.0.1:8770" \
  -d '{"provider":"openrouter","model":"openai/gpt-4o-mini"}'

# Ollama로 전환 (도구 호출을 지원하는 모델이어야 한다)
curl -X POST http://127.0.0.1:8770/api/llm/settings -H "Content-Type: application/json" \
  -H "Origin: http://127.0.0.1:8770" \
  -d '{"provider":"ollama","model":"qwen3:8b","ollama_base_url":"http://localhost:11434/v1"}'
```

저장하면 다음 요청부터 바로 적용된다(설정 파일의 수정 시각이 바뀌면 다시 읽는다).

### 시나리오 B — 자료 올리고 연구 돌리기

1. `/api/data/upload`로 자료를 올린다. `data`는 파일 내용의 base64다.
2. `/api/research`로 질문한다. **응답이 올 때까지 수 분 걸릴 수 있다.** 타임아웃을 넉넉히(예: 900초) 둔다.
3. 같은 시간에 다른 프로세스에서 `/api/research/progress`를 1~2초 간격으로 폴링해 진행을 본다.

```python
import base64, threading, time

data = base64.b64encode(open("line_transition.csv", "rb").read()).decode()
print(post("/api/data/upload", {"name": "line_transition.csv", "data": data}))

def run():
    out = post("/api/research", {"question": "24개월 누적 영업이익 분포를 분석해 줘"})
    print(out["answer"])

t = threading.Thread(target=run); t.start()
while t.is_alive():
    time.sleep(2)
    p = json.load(urllib.request.urlopen(BASE + "/api/research/progress"))
    print(p["elapsed"], [e["kind"] for e in p["log"]])
t.join()
```

### 시나리오 C — 연구 중지

```bash
curl -X POST http://127.0.0.1:8770/api/research/stop -H "Content-Type: application/json" \
  -H "Origin: http://127.0.0.1:8770" -d '{}'
```

이 요청은 락을 기다리지 않아 연구 도중에도 즉시 응답한다. 이미 연구원에게 맡긴 일은 끝난 뒤에 멈춘다.

### 시나리오 D — 연구원 지침을 바꿔 다음 위임에 반영

```bash
curl -X POST http://127.0.0.1:8770/api/agents/prompt -H "Content-Type: application/json" \
  -H "Origin: http://127.0.0.1:8770" \
  -d '{"role":"research","text":"(새 지침 전문)"}'
```

연구원을 다시 띄울 필요가 없다. 기본값으로 되돌리려면 `/api/agents/prompt/reset`에 `{"role":"research"}`를 보낸다.

### 시나리오 E — MCP 서버 붙이기

```bash
curl -X POST http://127.0.0.1:8770/api/mcp/add -H "Content-Type: application/json" \
  -H "Origin: http://127.0.0.1:8770" \
  -d '{"name":"my-docs","url":"https://example.com/mcp?key=${API_KEY}"}'
```

`${API_KEY}`는 문자 그대로 보낸다. 값은 연결할 때 `.env`에서 채워지고 어디에도 기록되지 않는다.

### 시나리오 F — `mcpServers` JSON을 그대로 붙이기

```bash
curl -X POST http://127.0.0.1:8770/api/mcp/add_json -H "Content-Type: application/json" \
  -H "Origin: http://127.0.0.1:8770" \
  -d '{"json":"{\"mcpServers\":{\"my-docs\":{\"url\":\"http://localhost:8005/mcp\",\"headers\":{\"Authorization\":\"Bearer ${API_KEY}\"}}}}"}'
```

응답의 `added`는 추가된 서버 이름, `problems`는 건너뛴 서버와 이유다. `command`가 있는 서버(명령을 실행하는 서버)는 추가되지 않는다. 키는 `${API_KEY}`처럼 이름으로 적고 값은 `.env`에 둔다.

### 시나리오 G — 스킬 추가하고 HTML 문서 받기

```bash
curl -X POST http://127.0.0.1:8770/api/skills/save -H "Content-Type: application/json" \
  -H "Origin: http://127.0.0.1:8770" \
  -d '{"name":"report-style","description":"보고서 문체 규칙. 보고서를 쓸 때 읽는다","tools":[],"body":"한 줄 요약으로 시작한다."}'
```

저장하면 다음 요청부터 모델이 `use_skill`로 이 지침을 읽을 수 있다. 기본 제공 `html` 스킬을 쓰는 요청(예: `/api/chat`에 "결과를 HTML 문서로 만들어줘")은 답변 끝에 `[[html:<id>]]` 한 줄을 돌려준다. 그 문서는 `GET /api/output?id=<id>`로 받을 수 있다.

## 4. 에러 코드와 대처

| 상태 | 메시지 | 원인 / 대처 |
|------|--------|-------------|
| 401 | `인증이 필요합니다.` | 공개 주소로 접속했는데 Basic 인증이 없거나 비밀번호가 다름 |
| 403 | `요청한 호스트를 허용하지 않습니다.` | `Host`가 허용 목록에 없음. 프록시가 `Host`를 바꾸지 않게 설정 |
| 403 | `외부 접속에는 .env의 APP_ACCESS_TOKEN 설정이 필요합니다.` | 신뢰 origin만 등록하고 토큰을 안 넣음 |
| 403 | `허용되지 않은 요청 출처입니다.` | POST에 `Origin` 헤더가 없거나 다름 |
| 403 | `교차 출처 요청을 허용하지 않습니다.` | 다른 사이트에서 보낸 브라우저 요청 |
| 413 | `보낸 내용이 너무 큽니다.` | 본문이 8MB 초과. 파일은 2MB 이하로 |
| 415 | `JSON 요청만 허용됩니다.` | `Content-Type: application/json` 누락 |
| 400 | `요청을 읽지 못했습니다.` | JSON이 아니거나 UTF-8이 아님 |
| 404 | `not found` | 없는 경로 |
| 200, `ok:false` | 각 API의 `message` | 업무 실패. `message`를 그대로 화면에 보여 주면 된다 |

## 5. FAQ / 트러블슈팅

**POST만 403이 난다.** `Origin` 헤더를 붙였는지 확인한다. curl은 기본으로 붙이지 않는다.

**연구 요청이 끝나지 않는다.** 정상일 수 있다. 연구원 한 명의 호출이 최대 600초까지 걸린다. `/api/research/progress`의 `log`가 늘어나고 있다면 진행 중이다.

**연구 중에 다른 POST가 멈춰 있다.** `/api/research`가 전역 락을 쥐고 있기 때문이다. 연구가 끝나거나 `/api/research/stop`으로 멈추면 풀린다. `/api/agents/prompt`와 `/api/research/stop`은 예외로 락 없이 응답한다.

**`.env`를 고쳤는데 반영되지 않는다.** `APP_TRUSTED_ORIGINS`와 `APP_ACCESS_TOKEN`은 시작할 때 한 번만 읽는다. 재시작한다.

**포트가 이미 사용 중이라고 나온다.** Windows는 같은 포트에 서버 둘이 붙을 수 있어, 옛 서버가 조용히 요청을 받는 일이 있다. 켜기 전에 `netstat -ano | findstr :8770`으로 확인한다. `scripts/dev/start-dev.bat`이 이 점검을 해 준다.
