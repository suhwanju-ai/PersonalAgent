# -*- coding: utf-8 -*-
"""OpenAI-compatible Chat Completions providers (standard library only).

앱 대화 항목을 OpenRouter messages/tools 형식으로 변환한다.
"""

import json
import time
import urllib.error
import urllib.request

from . import config

OLLAMA_TIMEOUT = 600        # 로컬 모델은 첫 요청에서 모델을 올리느라 오래 걸릴 수 있다


class QuotaExceeded(Exception):
    """분당 호출 한도 또는 잔액 초과 (HTTP 429)."""


class LLMError(Exception):
    """API 오류. 메시지에 키를 담지 않는다."""


def _message(detail):
    try:
        return json.loads(detail)["error"].get("message", detail)
    except (ValueError, KeyError, TypeError, AttributeError):
        return detail


def _endpoint(settings):
    base = (config.OPENROUTER_BASE if settings["provider"] == "openrouter"
            else settings["ollama_base_url"])
    return "%s/chat/completions" % base.rstrip("/")


def _post(payload, settings, timeout=None, retries=1):
    local = settings["provider"] == "ollama"
    if timeout is None:
        timeout = OLLAMA_TIMEOUT if local else 150
    url = _endpoint(settings)
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if settings["provider"] == "openrouter":
        headers.update({"Authorization": "Bearer %s" % config.api_key(),
                        "HTTP-Referer": "http://localhost",
                        "X-Title": "Common Agent"})
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = _message(e.read().decode("utf-8", "replace"))[:300]
            if e.code == 429:
                raise QuotaExceeded(detail)
            if e.code in (500, 502, 503, 504) and attempt < retries:
                time.sleep(2.0)
                continue
            raise LLMError("HTTP %d %s" % (e.code, detail))
        except (urllib.error.URLError, OSError) as e:
            # 로컬 모델이 시간 초과면 같은 요청을 다시 보내도 같은 시간을 또 쓴다.
            timed_out = isinstance(e, TimeoutError) or isinstance(getattr(e, "reason", None), TimeoutError)
            if attempt < retries and not (local and timed_out):
                time.sleep(2.0)
                continue
            raise LLMError("network: %s" % (getattr(e, "reason", None) or e.__class__.__name__,))


def _messages(system_prompt, items):
    messages = []
    pending_calls = {}
    for item in items:
        if item.get("type") == "function_call":
            pending_calls[item.get("call_id", "")] = item.get("name", "unknown")
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    for item in items:
        kind = item.get("type")
        if kind == "function_call_output":
            call_id = item.get("call_id", "")
            name = pending_calls.get(call_id, "unknown")
            messages.append({"role": "tool", "tool_call_id": call_id, "name": name,
                             "content": item.get("output", "")})
        elif kind == "function_call":
            call_id = item.get("call_id", "")
            name = item.get("name", "")
            pending_calls[call_id] = name
            call = {"id": call_id, "type": "function",
                    "function": {"name": name, "arguments": item.get("arguments", "{}")}}
            if messages and messages[-1].get("role") == "assistant" and "tool_calls" in messages[-1]:
                messages[-1]["tool_calls"].append(call)
            else:
                messages.append({"role": "assistant", "content": None, "tool_calls": [call]})
        elif kind == "message":
            content = item.get("content", "")
            if isinstance(content, str):
                # 이전 응답을 저장한 history는 Responses API에서도 문자열일 수 있다.
                text = content
            elif isinstance(content, list):
                text = "".join(p.get("text", "") for p in content
                               if isinstance(p, dict) and p.get("type") in ("output_text", "text"))
            else:
                text = ""
            messages.append({"role": item.get("role", "assistant"), "content": text})
        elif "role" in item:
            role = item["role"]
            content = item.get("content", "")
            messages.append({"role": role, "content": content})
    return messages


def _function_tools(declarations):
    return [{"type": "function", "function": {
        "name": d["name"], "description": d.get("description", ""),
        "parameters": d.get("parameters") or {"type": "object", "properties": {}}}}
        for d in declarations]


def call(system_prompt, items, declarations, web_search=False, temperature=None, trace=None):
    """한 턴을 호출하고 앱 내부 Responses 스타일 출력 항목으로 돌려준다."""
    settings = config.llm_settings()
    payload = {"model": settings["model"], "messages": _messages(system_prompt, items),
               "temperature": config.TEMPERATURE if temperature is None else temperature,
               "stream": False}
    tools = _function_tools(declarations)
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    if web_search and settings["provider"] == "openrouter":
        # OpenRouter의 :online 라우팅은 tool calling과 동시 사용이 제한될 수 있으므로
        # 검색을 웹 검색 전용 tool로 요청한다.
        # engine을 지정하지 않으면 OpenRouter가 모델이 지원할 때는 내장 검색을, 아니면 Exa를 고른다.
        # "native"로 못박으면 gpt-4o-mini처럼 내장 검색이 없는 모델에서 404가 난다.
        payload["plugins"] = [{"id": "web"}]

    started = time.time()
    data = _post(payload, settings, retries=1)
    if trace is not None:
        trace.append({"url": _endpoint(settings),
                      "request": json.loads(json.dumps(payload)), "response": data,
                      "elapsed": round(time.time() - started, 2)})

    choices = data.get("choices") or []
    if not choices:
        raise LLMError("응답에 choices가 없습니다")
    choice = choices[0]
    message = choice.get("message") or {}
    output, calls, searches = [], [], []
    content = message.get("content")
    if content:
        output.append({"type": "message", "role": "assistant", "content": content})
    for tc in message.get("tool_calls") or []:
        fn = tc.get("function") or {}
        call_id = tc.get("id", "")
        raw_args = fn.get("arguments") or "{}"
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except ValueError:
            args = {}
        output.append({"type": "function_call", "call_id": call_id,
                       "name": fn.get("name", ""),
                       "arguments": json.dumps(args, ensure_ascii=False)})
        calls.append({"name": fn.get("name", ""),
                      "args": args if isinstance(args, dict) else {}, "call_id": call_id})
    # OpenRouter online 검색 결과는 provider/model에 따라 citations로 제공된다.
    for citation in message.get("citations") or []:
        if isinstance(citation, dict) and citation.get("url"):
            searches.append(citation["url"])

    usage = data.get("usage") or {}
    normalized_usage = {"input_tokens": usage.get("prompt_tokens", 0),
                        "output_tokens": usage.get("completion_tokens", 0),
                        "total_tokens": usage.get("total_tokens", 0)}
    if choice.get("finish_reason") == "length" and not calls and not content:
        raise LLMError("응답이 토큰 한도에서 끝났습니다")
    return {"items": output, "text": content.strip() if isinstance(content, str) else "",
            "calls": calls, "tokens": int(normalized_usage["total_tokens"] or 0),
            "usage": normalized_usage, "searches": searches}
