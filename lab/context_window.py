"""Context Window 계기판. API 사용량 합계와 항목별 추정을 구분한다.

외부 토크나이저/API 호출 없이 동작한다. ASCII 4자, 그 외 UTF-8 3바이트를
약 1토큰으로 보는 교육용 근사치이며 모델의 실제 tokenizer와 같지 않다.
API usage가 있으면 입력 합계에 맞춰 항목을 배분하고 출력은 Context에 더한다.
누적 청구 토큰이 아닌 마지막 호출의 점유량을 표시한다.
"""

import copy
import json
import math
import threading

from . import config, llm


def estimate(value):
    if not value:
        return 0
    text = value if isinstance(value, str) else json.dumps(
        value, ensure_ascii=False, separators=(",", ":"))
    return math.ceil(sum(0.25 if ord(c) < 128 else len(c.encode("utf-8")) / 3
                         for c in text))


def measure(prompt, items, declarations, usage=None, phase="ready", step=0, output_items=None):
    settings = config.llm_settings()
    parts = [estimate(prompt), estimate(llm._function_tools(declarations)), estimate(items)]
    usage = usage or {}
    reported = all(isinstance(usage.get(k), int) and not isinstance(usage[k], bool)
                   and usage[k] >= 0 for k in ("input_tokens", "output_tokens"))
    if reported:
        # 최대 나머지 방식: 반올림 후에도 세 항목의 합이 API 사용량과 일치한다.
        total = usage["input_tokens"]
        weights = [n * total / sum(parts) for n in parts] if sum(parts) else [0, 0, total]
        parts = [math.floor(n) for n in weights]
        order = sorted(range(3), key=lambda i: weights[i] - parts[i], reverse=True)
        for i in order[:total - sum(parts)]:
            parts[i] += 1
        parts[2] += usage["output_tokens"]
    elif output_items:
        parts[2] = estimate(list(items) + list(output_items))
    return {
        "model": settings["model"],
        "provider": settings["provider"],
        "limit": config.CONTEXT_WINDOW_TOKENS,
        "total": sum(parts),
        "parts": dict(zip(("instructions", "tools", "context"), parts)),
        "basis": "api" if reported else "estimate",
        "phase": phase,
        "step": step,
    }


class Meter:
    def __init__(self):
        self._lock = threading.Lock()
        self._signature = None
        self._value = measure("", [], [])

    def prepare(self, prompt, declarations, history=None):
        """역할·도구 구성이 바뀌었을 때만 초기 추정값으로 다시 잰다.

        history(저장된 대화)는 서명에 넣지 않는다. 넣으면 대화가 끝날 때마다 서명이 바뀌어
        화면을 새로 고칠 때 API 실측값이 추정값으로 덮인다. 대화를 비울 때는 invalidate()를 부른다.
        """
        signature = json.dumps([config.llm_settings(), config.CONTEXT_WINDOW_TOKENS,
                                prompt, declarations], ensure_ascii=False, sort_keys=True)
        with self._lock:
            if signature != self._signature:
                self._signature = signature
                self._value = measure(prompt, history or [], declarations)
            return copy.deepcopy(self._value)

    def invalidate(self):
        """다음 prepare()가 반드시 다시 재게 한다."""
        with self._lock:
            self._signature = None

    def update(self, prompt, items, declarations, **kwargs):
        value = measure(prompt, items, declarations, **kwargs)
        with self._lock:
            self._value = value

    def finish(self, failed=False):
        with self._lock:
            self._value = dict(self._value, phase="error" if failed else "done")

    def snapshot(self):
        with self._lock:
            return copy.deepcopy(self._value)
