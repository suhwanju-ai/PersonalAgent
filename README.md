# Common Agent

AI에게 도구를 제공하고 연구 작업을 맡기는 로컬 웹앱입니다. 화면은 도구 대화, MCP 관리, 에이전트 협업으로 구성됩니다.

- **도구** — 내장 도구와 연결된 MCP 도구를 사용해 AI와 대화합니다. Context Window 계기판과 저장된 대화가 표시됩니다.
- **MCP** — 외부 도구 서버를 붙입니다. 로컬 PC에서 실행되는 서버와 원격 HTTP 서버를
  같은 조작으로 연결하고, 통합 목록에 도구마다 소속이 표시됩니다. 기본 목록에는 Microsoft Learn 문서 서버만 있습니다.
  「주소로 서버 추가」에 이름과 원격 서버 주소(Streamable HTTP)를 넣으면 목록에 추가하고 바로 연결합니다.
  직접 추가한 서버는 [삭제]로 목록에서 지울 수 있습니다.
- **에이전트** — 연구책임자가 조사·실험 연구원에게 일을 맡깁니다.
  프로세스 상태와 위임 기록을 확인할 수 있습니다. 연구원은 자료 파일을 읽을 수 있습니다.
  Python 코드는 현재 OS 수준 격리기가 없어 실행 도구를 제공하지 않습니다. 위쪽 그래프는 지금 누가 일하는 중인지를 그리고,
  [중지]로 다음 위임부터 멈출 수 있습니다. 예시 질문 칩으로 요청을 채우고, 꺼져 있는 연구원은
  연구를 시작할 때 자동으로 뜹니다. 연구 자료 파일(`data/research/`)은 화면에서 올리고 지울 수 있습니다.

Windows에서는 `run.bat`, Ubuntu에서는 `./run.sh` 또는 `python3 app.py`로 실행합니다. 실행 모드를 선택하는 환경변수는 없습니다.

파이썬 표준 라이브러리만 씁니다. `pip install`이 필요 없습니다.

## Context Window 상태

도구 탭 최상단의 두 바에서 전체 용량 대비 사용률과 Instructions / Tools / Context 비중을 확인합니다. 바와 범례에 마우스를 올리거나 키보드로 초점을 옮기면 토큰 수·사용량 내 비중·최대 용량 대비 비율을 표시합니다.

- 전체 현황: API 응답 뒤에는 **마지막 호출의 입력 + 출력 토큰**을 사용합니다. 여러 호출의 청구 토큰을 누적한 값과 다릅니다. 응답 대기 중과 도구 결과 추가 직후에는 로컬 추정값을 표시합니다.
- 상세 현황: Instructions는 적용한 역할 지시문, Tools는 도구 이름·설명·매개변수 스키마(연결된 MCP 포함), Context는 저장된 앞선 대화와 이번 요청의 메시지·응답·도구 호출·실행 결과입니다. 항목별 수치는 텍스트 길이 기반 추정이며, 응답 뒤에는 API 입력 합계에 비례 배분하고 출력 토큰을 Context에 더합니다. 실제 tokenizer나 API가 항목별로 측정한 값은 아닙니다.
- 대화창의 대화는 `state/chat_history.json`에 저장되어 다음 요청의 입력에 이어 붙습니다(사용자 메시지·응답·도구 호출·도구 결과 모두). 앱을 다시 켜도 이어지며, 최근 30턴(`lab/config.py`의 `CHAT_MAX_TURNS`)까지만 남기고 오래된 턴부터 지웁니다. 대화창의 [대화 초기화]를 누르면 기록을 지우고 Context가 0에서 다시 시작합니다. 입력창에만 작성한 미전송 문장은 포함하지 않습니다. 완료 후 마지막 상태를 유지하며, 역할·도구 구성을 변경해 적용하면 저장된 대화를 포함한 새 구성의 초기 추정값으로 갱신합니다. 처리 중에는 0.5초 간격으로 상태를 조회합니다.
- 모델 제공자와 모델 이름은 도구 탭의 **모델 연결**에서 설정합니다. Ollama는 기본 주소 `http://localhost:11434/v1`을 사용하며, 설치한 모델 이름을 입력합니다. OpenRouter 키는 `.env`에 둡니다. 컨텍스트 최대치는 `OPENROUTER_CONTEXT_WINDOW_TOKENS`로 지정합니다.
- 계기판을 위해 추가 API 호출이나 패키지 설치를 하지 않습니다. `lab/context_window.py`가 계산하고 `/api/context`가 상태를 제공합니다.

## 실행

ZIP을 압축 해제한 뒤 `app.py`가 있는 `Common Agent` 폴더에서 터미널을 엽니다.
Python이 설치되어 있어야 합니다. 별도 패키지 설치는 필요하지 않습니다.

```powershell
Copy-Item .env.example .env
notepad .env
```

`.env`의 `OPENROUTER_API_KEY=` 뒤에 발급받은 API 키를 입력하고 저장합니다. Ollama를 사용할 때는 Ollama를 실행한 뒤 도구 탭의 **모델 연결**에서 제공자를 Ollama로 바꾸고 API 주소와 설치된 모델 이름을 저장합니다. 설정은 `state/llm_settings.json`에 보관됩니다.

```powershell
.\run.bat
```

브라우저가 `http://127.0.0.1:8770/`을 엽니다. 세 탭은 항상 표시됩니다. 에이전트 탭에서 연구원을 시작하면 해당 프로세스가
8771 · 8772 포트에 뜹니다. 창을 닫으면 자식 프로세스까지 정리됩니다.
지난 실행이 남아 있으면 시작할 때 먼저 정리합니다.

### Ubuntu

Python 3가 설치된 환경에서 프로젝트 폴더로 이동해 다음 스크립트를 실행합니다. 앱은 Python 표준 라이브러리만 사용하므로 별도 패키지 설치는 필요하지 않습니다.

```bash
chmod +x run.sh
./run.sh
```

OpenRouter를 사용할 때는 `.env.example`을 `.env`로 복사하고 `OPENROUTER_API_KEY`를 설정합니다. Ollama만 사용할 경우 `.env` 없이 실행한 뒤, 도구 탭의 **모델 연결**에서 Ollama 주소와 설치된 모델 이름을 저장하면 됩니다. 기본 Ollama 주소는 `http://localhost:11434/v1`입니다.

리버스 프록시를 통해 HTTPS 도메인으로 운영하는 경우 `.env`의 `APP_TRUSTED_ORIGINS`에 브라우저에서 접속하는 원본 주소를 정확히 적습니다. 예: `APP_TRUSTED_ORIGINS=https://agent.example.com`. 여러 주소는 쉼표로 구분합니다. 이 주소로 들어오는 요청은 HTTP Basic 인증을 요구합니다(사용자 이름은 아무 값, 비밀번호는 `.env`의 `APP_ACCESS_TOKEN`). `APP_ACCESS_TOKEN`이 비어 있으면 외부 접속을 거부하며, `localhost`·`127.0.0.1` 접속에는 인증이 없습니다. 두 값은 시작할 때만 읽으므로 바꾸면 재시작합니다. 설정 변경이 유지되도록 배포 환경의 `state/` 폴더에 쓰기 권한과 영구 저장 공간을 제공해야 합니다. 운영 서버와 Ollama가 다른 장비라면 Ollama 주소에 `localhost` 대신 운영 서버에서 접근할 수 있는 사설망 주소나 내부 DNS 이름을 입력하고, 방화벽에서 해당 연결을 허용해야 합니다.

## 폴더

```
app.py                      HTTP 서버 · /api/* · 화면 상태
run.bat                    도구·MCP·에이전트 탭을 함께 실행
run.sh                     Ubuntu에서 앱을 실행
mcp_catalog.json            연결할 수 있는 MCP 서버 목록 (화면에서 고른다).
                            키가 필요한 서버는 ${VAR} 자리표시자로 적는다
mcp_config.json             지금 붙어 있는 서버. 처음에는 비어 있다

lab/config.py               모델 제공자 · 모델 · 포트 설정
lab/llm.py                  OpenRouter 또는 Ollama 호환 Chat Completions 호출
lab/tools.py                내장 도구 memo_tool_1/2/3/4 (검색·저장·삭제·수정)
lab/registry.py             내장 도구 + MCP 도구를 한 목록으로. 설명문 덮어쓰기
lab/mcp_client.py           MCP 클라이언트 — stdio 와 Streamable HTTP
lab/skills.py               skills/<이름>/SKILL.md를 읽어 use_skill 도구로 제공
lab/html_render.py          마크다운·JSON을 디자인된 HTML 문서로 변환(render_html 도구)
skills/                     스킬 폴더. 기본 제공: html
lab/runner.py               도구를 쓰는 대화 루프. 결정은 LLM, 실행은 이 파일
lab/roles.py                세 역할의 지시문과 도구 배분
lab/orchestrator.py         자식 프로세스 기동·종료, delegate_* 도구, 위임 로그, 후속 질의 세션
lab/sandbox.py              격리 실행기가 마련될 때까지 Python 코드 실행을 fail-closed 처리
lab/datafile.py             read_data_file — data/research 안의 파일만 읽기 전용.
                            화면의 파일 올리기·지우기도 이 폴더 안에서만 동작

agents/_serve.py            연구원 한 명을 HTTP 서버로 띄우는 공통 코드
agents/research_agent.py    자료조사 연구원 (:8771) — MCP 도구 + 웹 검색
agents/experiment_agent.py  실험수행 연구원 (:8772) — read_data_file (코드 실행 비활성화)

data/notes.json             메모 데이터. 화면의 초기화 버튼이 seed/notes.json으로 되돌린다
data/research/line_transition.csv   연구 자료 (신규 공정 라인 전환의 사업 가정, 가상)
state/                      역할 문구, 연구원 지침 role_prompts.json, 기존 데이터 경로 설정,
                            도구 탭 대화 기록 chat_history.json,
                            MCP 탭에서 주소로 추가한 서버 mcp_custom.json
static/                     index.html · app.js · style.css
```

## 동작 방식

- 내장 메모 도구의 검색·저장·삭제 파라미터는 `text` 하나입니다. 수정 도구(`memo_tool_4`)는
  `target`(메모 제목·키워드) · `find`(본문에서 바꿀 문장) · `replace`(바꿔 넣을 문장)를 받아
  메모 하나의 본문에서 한 곳만 바꿉니다. 메모가 여럿 해당하거나 `find`가 없거나 여러 번 나오면
  고치지 않고 후보 제목이나 현재 내용을 돌려줍니다. 빈 삭제 키워드는 전체 메모를 삭제하지 않도록 거부합니다.
- MCP 키 — 키가 필요한 서버는 설정에 `${API_KEY}`처럼 이름만 적습니다.
  값은 연결하는 순간 `.env`에서 읽어 메모리에서만 채우므로 `mcp_catalog.json`에도
  `mcp_config.json`에도 키가 남지 않습니다. 값이 없으면 그 서버만 오류를 돌려주고
  나머지는 그대로 씁니다. 화면에서 주소로 추가할 때도 같습니다. 예:
  `https://example.com/mcp?apiKey=${EXAMPLE_API_KEY}`. 주소에 키 값을 그대로 적으면
  `state/mcp_custom.json`과 `mcp_config.json`에 그대로 남습니다.
- 주소로 추가한 서버는 `state/mcp_custom.json`에 저장되고 기본 목록(`mcp_catalog.json`)은
  바뀌지 않습니다. 기본 목록과 같은 이름이나 `내장`·`위임` 같은 앱이 쓰는 이름은 받지 않습니다.
  인증 헤더를 요구하는 서버는 "추가 헤더" 칸에 한 줄에 하나씩 `이름: 값`으로 적습니다.
  값에는 `${변수명}`을 쓸 수 있고(예: `Authorization: Bearer ${API_KEY}`), 연결할 때 `.env`에서 채웁니다.
  인증값을 헤더가 아닌 도구 인자(`api_key` 등)로 받는 서버는 "고정 인자" 칸에 `api_key: ${변수명}`처럼 적습니다.
  이 인자는 그 서버의 모든 도구 호출에 자동으로 합쳐지고, AI가 보는 도구 스키마에서는 빠지므로
  키가 모델 요청이나 대화 기록에 실리지 않습니다. AI가 같은 이름의 값을 넣어도 고정값이 이깁니다.
  `Host`·`Content-Type` 등 앱이 직접 쓰는 헤더는 지정할 수 없습니다. 로컬(stdio) 서버의 `env` 항목도
  `mcp_config.json`에서 같은 방식으로 쓸 수 있습니다(화면에서는 보안상 stdio 서버를 추가하지 않습니다).
- 에이전트 탭 — 역할의 경계는 지시문으로, 도구의 경계는 코드로 나뉩니다. 조사 담당은
  실행 도구를 볼 수 없고 실행 담당은 조사 도구를 볼 수 없습니다. 연구원끼리는 서로를
  부를 수단이 없습니다. 위임은 function call이라 지시문 원문과 반환값이 로그에 그대로
  찍힙니다. 1차 질문 뒤 후속 질의는 같은 세션에서 이어집니다.
- 연구원 지침 편집 — 에이전트 탭의 **연구원 지침** 카드에서 자료조사·실험수행 연구원의 지침을 고칠 수 있습니다.
  저장한 값은 `state/role_prompts.json`에 남고, 연구원은 작업을 받을 때마다 이 파일을 읽으므로 연구원을 다시 띄우지 않아도
  **다음 위임부터** 적용됩니다(진행 중인 위임에는 닿지 않습니다). [기본값으로]를 누르거나 기본 지침과 같은 내용을 저장하면
  고친 값을 지우고 `lab/roles.py`의 기본 지침으로 돌아갑니다. 지침에는 "실행하지 않은 수치를 만들지 않는다" 같은 보고 규칙이
  들어 있으니 줄이거나 지울 때 확인하세요. 연구책임자의 지침은 이 카드에서 고치지 않습니다.
- 연구원의 보고에는 OpenRouter와 주고받은 요청·응답 및 사용 도구 순서 기록(`trace`)이 포함됩니다.
- 진행 그래프와 대화방 — `/api/research`는 연구가 끝날 때까지 응답을 쥐고 있으므로, 화면은
  락을 잡지 않는 `/api/research/progress`를 따로 물어 진행 중인 위임 로그를 그립니다.
  연구원을 띄우는 동안에는 `starting`으로 표시됩니다.
  [중지]도 같은 이유로 락 밖(`/api/research/stop`)에서 받습니다. 이미 맡겨 둔 일을
  끊지는 못하고, 다음 차례를 시작하지 않는 방식입니다.

## 스킬

도구 탭 오른쪽의 **스킬** 카드에서 추가·수정·삭제할 수 있고(이름, 설명, 쓸 도구, 지침), 저장하면 다음 요청부터 적용됩니다. 파일로 `skills/<이름>/SKILL.md`를 직접 넣어도 됩니다(앱을 다시 켤 필요 없음). 파일 맨 위 `---` 사이에 `name`, `description`(선택: `tools`)을 쓰고, 그 아래에 사용 지침을 씁니다. Claude Code의 SKILL.md와 같은 형식이라 폴더를 복사해 올 수 있습니다.

- 모델에게는 `use_skill` 도구 하나로 보이고, 도구 설명에 스킬 이름과 설명만 실립니다. 모델이 필요하다고 판단하면 `use_skill(이름)`으로 본문 지침을 읽습니다.
- 기본 제공 `html` 스킬은 `render_html` 도구로 마크다운 본문을 디자인된 HTML 문서로 바꿉니다. 결과는 답변에 미리보기와 [다운로드] 버튼으로 나오고, 파일은 `state/outputs/`에 최근 50개까지 남습니다. 디자인은 `ledger`(남색·금색)와 `dossier`(녹색·주황) 두 가지입니다.
- 스킬은 **코드를 실행하지 않습니다.** 지침 글과 `lab/skills.py`의 `SKILL_TOOLS`에 있는 내장 도구만 쓸 수 있고, 폴더에 파이썬 파일을 넣어도 읽지 않습니다. `tools:`에 적은 이름이 `SKILL_TOOLS`에 없으면 무시합니다.
- 도구 탭과 에이전트 탭의 연구책임자가 스킬을 씁니다. 자료조사·실험수행 연구원에게는 주지 않습니다.

## Python 코드 실행

연구원이 만든 코드를 현재 사용자 권한으로 실행하는 것은 파일과 시스템을 보호하지 못해
비활성화했습니다. 실험수행 연구원은 `read_data_file`로 자료를 읽을 수 있지만,
정량 결과가 필요한 경우 코드를 실행한 것처럼 꾸며 보고하지 않고 실행 불가 사실을 알립니다.
OS 수준 격리 실행기가 구성되기 전까지 `lab/sandbox.py`는 요청을 거부합니다.

## 모델

기본 제공자는 OpenRouter이며 기본 모델은 `openai/gpt-4o-mini`입니다. 제공자와 모델은 웹 UI에서 바꾸며 설정은 `state/llm_settings.json`에 저장됩니다. OpenRouter 키는 `.env`의 `OPENROUTER_API_KEY`를 사용하고, Ollama는 OpenAI 호환 주소(기본 `http://localhost:11434/v1`)로 요청합니다. Ollama 모델은 도구 호출을 지원해야 하며, OpenRouter 웹 검색 플러그인은 Ollama에서 사용하지 않습니다. 앱이 대화 history를 직접 보관합니다.

## 초기 상태와 개발 시작

처음 받은 상태에서는 MCP 연결이 비어 있고 메모는 기본 예제로 초기화되어 있습니다.
연구 자료에는 기본 `line_transition.csv`만 포함됩니다. 실행 기록과 화면에서 변경한 설정은 포함하지 않습니다.
`.env.example`에는 키가 없으며, 실제 `.env`는 각자의 PC에서 만듭니다.

Claude Code에서 이 폴더를 열고 다음과 같이 요청할 수 있습니다.

> README와 소스 코드를 읽고 도구·MCP·에이전트 탭의 동작 흐름과 수정할 파일을 설명해 주세요. .env의 실제 키 값은 읽거나 출력하지 마세요. 아직 코드를 수정하지 마세요.

`app.py`에서 요청 처리를, `static/`에서 화면을 확인할 수 있습니다.
도구 호출 흐름은 `lab/registry.py` → `lab/runner.py`, 에이전트 위임은 `lab/orchestrator.py`와 `agents/`에서 확인합니다.
