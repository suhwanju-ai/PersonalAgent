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
```

- The main app runs at `http://127.0.0.1:8770/`. The researcher agents use `:8771` (research) and `:8772` (experiment). They start from the Agents tab, or automatically when a research run begins.
- To run one agent on its own: `python agents/research_agent.py` or `python agents/experiment_agent.py`. Each exposes `GET /info` and `POST /task {"instruction": ...}`.
- The repo has no test suite, linter, or build step.

## Architecture

**Tool-calling loop (`lab/runner.py`).** The LLM only decides which tool to call; `runner.run()` executes the tool. Every part of the app goes through this one loop: the Tools tab chat, each researcher agent, and the orchestrator. A tool entry is a dict `{name, description, parameters, source, call}`, where `call(args_dict) -> result`. Tool exceptions are caught and returned to the model as `{"오류": ...}` so the model can retry. Every `function_call` needs a matching `function_call_output`, including on stop, or the next turn is invalid. `should_stop` only prevents the *next* step from starting. It cannot interrupt a call already in flight.

**Tool assembly (`lab/registry.py`).** `build()` merges the built-in tools from `lab/tools.py` (`memo_tool_1/2/3` search/save/delete take a single `text` parameter; `memo_tool_4` find-and-replace takes `target`/`find`/`replace` and refuses rather than editing when the target note or the `find` string is ambiguous) with tools from MCP servers via `lab/mcp_client.py`. If two tools share a name, the first one registered wins. Descriptions edited in the UI are stored in `state/tool_overrides.json` and override the code defaults at build time. `llm.py` converts tool declarations to the API format.

**Multi-agent (`lab/orchestrator.py`, `lab/roles.py`, `agents/`).**
- The orchestrator runs inside the main app process. Its only tools are `delegate_research` and `delegate_experiment`, generated in `_delegate_entries`. Each one POSTs to the matching child process and appends `delegate`/`return` entries to a shared log, which includes the child's full `trace`.
- `agents/_serve.py` is shared by both researchers. Only the role differs: prompt plus tools from `roles.tools_for()`. Tool boundaries are enforced in code. The research role gets MCP tools and web search, and no built-ins. The experiment role gets only `read_data_file` (`lab/datafile.py`); Python execution is disabled until an OS-level sandbox exists. Researchers cannot call each other.
- The parent detects that a child has started when the child prints `READY <role> <port> <pid>` to stdout. **Don't change that line's format.** The orchestrator kills stale children from earlier runs at startup.
- Follow-up questions reuse `_SESSION["items"]` as the orchestrator's history.

**Locking in `app.py`.** All POST routes are serialized behind one global `LOCK`, and `/api/research` holds it for the whole run, which can take minutes. Any endpoint that must respond during a run needs `@route(..., lock=False)` (for example `/api/research/stop`), or must be a lock-free GET (`/api/research/progress`, `/api/context`). Add new routes with the `@route` decorator.

**Sandbox (`lab/sandbox.py`).** Python execution fails closed. Import filtering and launching a subprocess as the same Windows user are not a security boundary. Do not re-enable `run_python` until execution is isolated at the OS level with filesystem, network, and resource limits. `lab/datafile.py` confines research file operations to `data/research/`.

**Tools-tab chat history.** Only the Tools-tab chat is stateful. `app.handle_chat` loads `state/chat_history.json` (`runner.load_chat`/`chat_items`), passes it as `history=` to `runner.run`, and saves the new turn only on success. Each turn stores its own API items so trimming to `CHAT_MAX_TURNS` never splits a `function_call`/`function_call_output` pair. `runner.run` itself stays stateless because the agents and orchestrator also call it. `/api/chat/reset` clears the file.

**Context meter (`lab/context_window.py`).** It estimates Instructions/Tools/Context token shares from text length, then scales them to the API's reported usage after each response. It makes no extra API calls. Saved chat history is not part of `Meter.prepare`'s signature; otherwise every refresh after a chat would replace the API-measured value with an estimate. Call `invalidate()` when the history is cleared. `runner.run` feeds it through `on_context`, and the UI polls `/api/context`.

## Config and state

- `lab/config.py` holds model config (`OPENROUTER_MODEL`, `OPENROUTER_CONTEXT_WINDOW_TOKENS`), ports, and step limits.
- `mcp_catalog.json` lists the MCP servers available to connect, and `mcp_config.json` lists the ones currently connected. Servers added by URL in the MCP tab (`/api/mcp/add`) are stored separately in `state/mcp_custom.json` and merged in by `app.catalog()`. When a name exists in both, the base catalog's entry is used. Only these custom servers can be deleted (`/api/mcp/remove`). The server name becomes the tool `source`, so `내장`, `위임`, and `알 수 없음` are rejected. Write secrets as `${VAR}` placeholders. They are filled from `.env` in memory only when connecting.
- `state/` is created at runtime and gitignored. It holds the edited tool descriptions, the system prompt, the notes data path override, and `chat_history.json`. `data/notes.json` resets from `data/seed/notes.json`.
- The role prompts in `lab/roles.py` enforce rules that the app's behavior depends on. For example, final numbers must come from code that actually ran, business assumptions come only from the data file, and the report gives no go/no-go judgment. Keep these rules intact when you edit the prompts.
- The frontend is plain HTML, CSS, and JS in `static/` with no build step.
- Local POST endpoints validate Host, Origin, Fetch Metadata, JSON content type, and body size through `lab/http_security.py`; child agent endpoints reject browser-origin requests.
