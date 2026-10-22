# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Common Agent is a local web app (Korean UI, Korean code comments) for experimenting with LLM tool use. It has three tabs: **Tools** (built-in memo tools with editable descriptions and a raw API call log), **MCP** (attach stdio or Streamable HTTP MCP servers), and **Agents** (an orchestrator that delegates work to two researcher agents, each running as its own process). It uses OpenRouter Chat Completions.

**Python standard library only.** There is no `requirements.txt` and no `pip install` step. Don't add third-party dependencies. HTTP goes through `urllib` and the server is built on `http.server`.

Do not read or print the contents of `.env`, which holds `OPENROUTER_API_KEY`. `lab/config.py` deliberately keeps the key out of every log, UI response, and error message.

## Commands

```powershell
Copy-Item .env.example .env      # then set OPENROUTER_API_KEY=
.\run.bat                        # or: python app.py  (sets PYTHONUTF8=1 first in run.bat)
./run.sh                         # Ubuntu/bash equivalent
```

- `run.bat` exits if `.env` is missing, even when using Ollama only. Running `python app.py` directly skips that check. Set `PYTHONUTF8=1` yourself when you bypass the scripts, since the UI and data are Korean.
- When serving over HTTPS behind a reverse proxy, list the browser-facing origin in `.env` `APP_TRUSTED_ORIGINS` (comma-separated). Otherwise `lab/http_security.py` rejects the POSTs. Requests arriving through a trusted origin must pass HTTP Basic auth with `APP_ACCESS_TOKEN` as the password (refused outright if the token is unset); loopback access is not authenticated. Both values are read once at startup. The Ollama base URL setting rejects link-local addresses.

- The main app runs at `http://127.0.0.1:8770/`. The researcher agents use `:8771` (research) and `:8772` (experiment). They start from the Agents tab, or automatically when a research run begins.
- To run one agent on its own: `python agents/research_agent.py` or `python agents/experiment_agent.py`. Each exposes `GET /info` and `POST /task {"instruction": ...}`.
- The repo has no test suite, linter, or build step.

## Architecture

**Tool-calling loop (`lab/runner.py`).** The LLM only decides which tool to call; `runner.run()` executes the tool. Every part of the app goes through this one loop: the Tools tab chat, each researcher agent, and the orchestrator. A tool entry is a dict `{name, description, parameters, source, call}`, where `call(args_dict) -> result`. Tool exceptions are caught and returned to the model as `{"오류": ...}` so the model can retry. Every `function_call` needs a matching `function_call_output`, including on stop, or the next turn is invalid. `should_stop` only prevents the *next* step from starting. It cannot interrupt a call already in flight.

**Tool assembly (`lab/registry.py`).** `build()` merges the built-in tools from `lab/tools.py` (`memo_tool_1/2/3` search/save/delete take a single `text` parameter; `memo_tool_4` find-and-replace takes `target`/`find`/`replace` and refuses rather than editing when the target note or the `find` string is ambiguous) with tools from MCP servers via `lab/mcp_client.py`. If two tools share a name, the first one registered wins. Descriptions edited in the UI are stored in `state/tool_overrides.json` and override the code defaults at build time. `llm.py` converts tool declarations to the API format.

**Multi-agent (`lab/orchestrator.py`, `lab/roles.py`, `agents/`).**
- The orchestrator runs inside the main app process. Its tools are `delegate_research` and `delegate_experiment` (generated in `_delegate_entries`) plus the skill tools from `skills.entries()` (`use_skill`, `render_html`); it never gets MCP or built-in tools. Each one POSTs to the matching child process and appends `delegate`/`return` entries to a shared log, which includes the child's full `trace`.
- `agents/_serve.py` is shared by both researchers. Only the role differs: prompt plus tools from `roles.tools_for()`. Tool boundaries are enforced in code. The research role gets MCP tools and web search, and no built-ins. The experiment role gets only `read_data_file` (`lab/datafile.py`); Python execution is disabled until an OS-level sandbox exists. Researchers cannot call each other.
- The parent detects that a child has started when the child prints `READY <role> <port> <pid>` to stdout. **Don't change that line's format.** The orchestrator kills stale children from earlier runs at startup.
- Follow-up questions reuse `_SESSION["items"]` as the orchestrator's history.

**Skills (`lab/skills.py`, `skills/`).** `skills/<name>/SKILL.md` (Claude Code format: `---` frontmatter with `name`, `description`, optional `tools`, then instructions) is read by `registry.build()` on every build (no restart; skipped files (over `MAX_BYTES`, bad name) are reported in `registry.build()` errors via `skills.problems()`; `/api/state` carries only name/description/tools, the body comes from `/api/skills/get`; the Tools-tab "스킬" card writes these files via `/api/skills/save` and `/api/skills/delete`, validating the name as a folder name and limiting `tools` to `SKILL_TOOLS`) and exposed as one `use_skill` tool whose description lists skill names; the body is returned only when the model calls it. Skills never run code: they can only name built-in tools from `skills.SKILL_TOOLS` (today `render_html`, which takes markdown, or JSON `content`, and renders via `lab/html_render.py`; all text is escaped, so downloaded files are safe to open). `render_html` saves to `state/outputs/<id>.html` and returns `[[html:<id>]]`; `runner.run` appends that marker to the answer if the model omitted it, and the frontend `md()` turns it into a sandboxed iframe preview with a download button (`GET /api/output?id=`). The orchestrator gets the skill tools; the researchers do not. Add built-in skill tools by extending `SKILL_TOOLS`, not by loading code from the skills folder.

**Route errors.** `do_POST` runs handlers through `_run`, which turns an unexpected exception (wrong-typed payload) into `{ok: false, message}` and prints the traceback, so the connection is never dropped. `fixed_args` values are masked (`***`) in MCP tool results and errors (`mcp_client._make_caller`) so a server that echoes its arguments cannot leak the secret into model context or `chat_history.json`.

**Locking in `app.py`.** All POST routes are serialized behind one global `LOCK`, and `/api/research` holds it for the whole run, which can take minutes. Any endpoint that must respond during a run needs `@route(..., lock=False)` (for example `/api/research/stop`), or must be a lock-free GET (`/api/research/progress`, `/api/context`). Add new routes with the `@route` decorator.

**Sandbox (`lab/sandbox.py`).** Python execution fails closed. Import filtering and launching a subprocess as the same Windows user are not a security boundary. Do not re-enable `run_python` until execution is isolated at the OS level with filesystem, network, and resource limits. `lab/datafile.py` confines research file operations to `data/research/`.

**Tools-tab chat history.** Only the Tools-tab chat is stateful. `app.handle_chat` loads `state/chat_history.json` (`runner.load_chat`/`chat_items`), passes it as `history=` to `runner.run`, and saves the new turn only on success. Each turn stores its own API items so trimming to `CHAT_MAX_TURNS` never splits a `function_call`/`function_call_output` pair. `runner.run` itself stays stateless because the agents and orchestrator also call it. `/api/chat/reset` clears the file.

**Context meter (`lab/context_window.py`).** It estimates Instructions/Tools/Context token shares from text length, then scales them to the API's reported usage after each response. It makes no extra API calls. Saved chat history is not part of `Meter.prepare`'s signature; otherwise every refresh after a chat would replace the API-measured value with an estimate. Call `invalidate()` when the history is cleared. `runner.run` feeds it through `on_context`, and the UI polls `/api/context`.

## Config and state

- `lab/config.py` holds model config (`OPENROUTER_MODEL`, `OPENROUTER_CONTEXT_WINDOW_TOKENS`), ports, and step limits.
- The model provider, model name, and Ollama OpenAI-compatible base URL are stored in ignored `state/llm_settings.json`. OpenRouter credentials remain in `.env`; never return them in state or UI responses. Ollama does not use OpenRouter's web-search plugin.
- `mcp_catalog.json` lists the MCP servers available to connect, and `mcp_config.json` lists the ones currently connected. Servers added by URL in the MCP tab (`/api/mcp/add`) are stored separately in `state/mcp_custom.json` and merged in by `app.catalog()`. When a name exists in both, the base catalog's entry is used. Only these custom servers can be deleted (`/api/mcp/remove`). The server name becomes the tool `source`, so `내장`, `위임`, and `알 수 없음` are rejected. Write secrets as `${VAR}` placeholders (in the URL, in `headers` values, in stdio `args`/`env`). They are filled from `.env` in memory only when connecting. Remote servers accept extra `headers` (`mcp_client.clean_headers` rejects reserved ones like `Host`/`Content-Type` and control characters); the add form takes them as `Name: value` lines. For servers that want auth as a tool argument, `fixed_args` (`{name: "${VAR}"}`) is merged into every `tools/call` (fixed value wins) and removed from the schema the model sees (`_hide_fixed`), so the secret never enters model requests or `chat_history.json`. The UI deliberately cannot add stdio servers (that would let anyone reaching the UI run commands); stdio `env` is only read from `mcp_config.json`.
- `state/` is created at runtime and gitignored. It holds the edited tool descriptions, the system prompt, the notes data path override, and `chat_history.json`. `data/notes.json` resets from `data/seed/notes.json`.
- Researcher prompts are editable from the Agents tab (`/api/agents/prompt`, `lock=False` so it saves during a run). Edits live in `state/role_prompts.json`, keyed by role. `roles.prompt_for()` reads that file on every call, and `agents/_serve.py` calls it per task, so an edit reaches an already running child on the next delegation without a restart. Saving empty text or the default text deletes the override. Don't read `roles.ROLES[...]["prompt"]` directly where the effective prompt is meant. The orchestrator's prompt is not editable.
- The role prompts in `lab/roles.py` enforce rules that the app's behavior depends on. For example, final numbers must come from code that actually ran, business assumptions come only from the data file, and the report gives no go/no-go judgment. Keep these rules intact when you edit the prompts.
- The frontend is plain HTML, CSS, and JS in `static/` with no build step.
- `README.md` (Korean) documents user-facing behavior and the folder layout. `Plan.md` is a product-status and roadmap doc whose roadmap section is proposals, not commitments. `Tool추가.md` is a worked example of adding a built-in tool (`memo_tool_4`): one entry in `lab/tools.py` `TOOLS` is enough, and the UI, context meter, and API log pick it up with no frontend change.
- Local POST endpoints validate Host, Origin, Fetch Metadata, JSON content type, and body size through `lab/http_security.py`; child agent endpoints reject browser-origin requests.
