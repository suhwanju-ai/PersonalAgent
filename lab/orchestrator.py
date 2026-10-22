# -*- coding: utf-8 -*-
"""연구책임자 — 자식 프로세스 두 개를 띄우고, 일을 맡기고, 오간 내용을 기록한다.

**위임을 도구 호출로 구현했다.** 그래야 무엇을 맡겼는지가 인자로 남아 로그에 그대로 찍힌다.

자식 프로세스 정리가 중요하다. 부모가 종료되고 자식이 남으면 포트가 막혀 다시 켜지지 않는다.
"""

import atexit
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

from . import config, llm, roles, skills

_CHILDREN = {}          # role -> Popen


# ── 자식 프로세스 ─────────────────────────────────────────────────────

def _info(role_name, timeout=2):
    """자식 프로세스에 상태 정보를 요청한다. 떠 있지 않으면 None."""
    url = "http://%s:%d/info" % (config.HOST, roles.ROLES[role_name]["port"])
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _kill_stale(role_name):
    """지난 실행에서 남은 같은 역할의 프로세스를 정리한다.

    역할 이름이 이 앱의 것과 같을 때만 종료한다. 다른 프로세스는 건드리지 않는다.
    """
    info = _info(role_name)
    if not info or info.get("role") != role_name:
        return False
    pid = info.get("pid")
    if not pid:
        return False
    try:
        os.kill(int(pid), signal.SIGTERM)
    except OSError:
        return False
    for _ in range(20):
        if _info(role_name, timeout=1) is None:
            return True
        time.sleep(0.25)
    return False


def is_up(role_name):
    return bool(_info(role_name, timeout=1))


def start(role_name, wait=25):
    """자식을 띄운다. 이미 떠 있으면 그대로 둔다."""
    if _info(role_name):
        return {"ok": True, "message": "이미 떠 있습니다."}

    script = os.path.join(config.AGENTS_DIR, roles.ROLES[role_name]["script"])
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    kwargs = {"cwd": config.ROOT, "env": env,
              "stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000            # CREATE_NO_WINDOW
    proc = subprocess.Popen([sys.executable, script], **kwargs)
    _CHILDREN[role_name] = proc

    for _ in range(wait * 4):
        if _info(role_name, timeout=1):
            return {"ok": True}
        if proc.poll() is not None:
            err = proc.stderr.read().decode("utf-8", "replace")[-400:]
            return {"ok": False, "message": "기동에 실패했습니다. %s" % err.strip()[:200]}
        time.sleep(0.25)
    return {"ok": False, "message": "기동을 기다렸지만 응답이 없습니다."}


def stop(role_name):
    proc = _CHILDREN.pop(role_name, None)
    if proc is not None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            try:
                proc.kill()
            except OSError:
                pass
    else:
        _kill_stale(role_name)
    for _ in range(20):
        if _info(role_name, timeout=1) is None:
            return {"ok": True}
        time.sleep(0.25)
    return {"ok": False, "message": "종료를 확인하지 못했습니다."}


def stop_all():
    for role_name in list(roles.ORDER):
        try:
            stop(role_name)
        except Exception:                               # noqa: BLE001
            pass


atexit.register(stop_all)


def cleanup_stale():
    """앱을 켤 때 지난 실행의 잔여 프로세스를 정리한다.

    윈도우에서 부모 창을 강제로 닫으면 atexit이 실행되지 않아 자식이 남는다.
    이것이 쌓이면 포트가 막혀 다시 켜지지 않으므로 기동 때 한 번 확인한다.
    """
    cleaned = []
    for role_name in roles.ORDER:
        if role_name in _CHILDREN:
            continue
        if _kill_stale(role_name):
            cleaned.append(roles.ROLES[role_name]["label"])
    return cleaned


def status():
    """세 프로세스의 상태. 부모는 항상 떠 있다."""
    out = [{"role": "orchestrator", "label": "연구책임자 (이 앱)",
            "up": True, "pid": os.getpid(), "port": config.PORT,
            # 위임 도구 둘뿐이다. 조사 도구도 실행 도구도 가지고 있지 않다.
            "tools": [{"name": "delegate_%s" % r, "source": "위임"} for r in roles.ORDER]}]
    for role_name in roles.ORDER:
        info = _info(role_name, timeout=1)
        role = roles.ROLES[role_name]
        out.append({
            "role": role_name,
            "label": role["label"],
            "up": bool(info),
            "pid": (info or {}).get("pid"),
            "port": role["port"],
            "web_search": role["web_search"],
            "tools": (info or {}).get("tools", []),
        })
    return out


# ── 위임 ──────────────────────────────────────────────────────────────

def _send(role_name, instruction, timeout=600):
    # 실험 담당이 코드를 고쳐 가며 세 번 돌리면 200초를 넘길 수 있다(실측 226초). 240초로는 부족하다.
    url = "http://%s:%d/task" % (config.HOST, roles.ROLES[role_name]["port"])
    body = json.dumps({"instruction": instruction}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError) as exc:
        return {"ok": False,
                "result": "연구원에게 연결하지 못했습니다. 기동되어 있는지 확인해 주세요. (%s)"
                          % str(exc)[:80]}


def _delegate_entries(log):
    """위임 도구 두 개. 호출될 때마다 로그에 오간 내용을 남긴다."""
    entries = []
    for role_name in roles.ORDER:
        role = roles.ROLES[role_name]

        def make(rn, label):
            def call(args):
                instruction = (args or {}).get("instruction") or ""
                # 보내기 전에 남긴다. 화면이 이 항목을 보고 해당 연구원이
                # 일하는 중임을 그린다. 짝이 되는 return이 붙으면 끝난 것이다.
                log.append({"kind": "delegate", "to": rn, "label": label,
                            "instruction": instruction, "at": time.time()})
                out = _send(rn, instruction)
                log.append({"kind": "return", "from": rn, "label": label,
                            "ok": bool(out.get("ok")),
                            "result": out.get("result", ""),
                            "calls": out.get("calls", []),
                            "searches": out.get("searches", []),
                            "tokens": out.get("tokens", 0),
                            "steps": out.get("steps", 0),
                            # 연구원 안에서 오간 요청·응답·도구. 화면이 보고 아래에 펼쳐 보여 준다.
                            "trace": out.get("trace", []),
                            "elapsed": out.get("elapsed", 0), "at": time.time()})
                return {"연구원 보고": out.get("result", "")}
            return call

        entries.append({
            "name": "delegate_%s" % role_name,
            "description": "%s 에게 일을 맡기고 결과를 받는다. 무엇을 해야 하는지 "
                           "지시문에 구체적으로 적는다." % role["label"],
            "parameters": {
                "type": "object",
                "properties": {"instruction": {"type": "string",
                                               "description": "연구원에게 줄 지시문"}},
                "required": ["instruction"],
            },
            "source": "위임",
            "call": make(role_name, role["label"]),
        })
    return entries


_SESSION = {"items": None}             # 연구책임자가 기억하는 앞선 대화

# 지금 돌고 있는 연구의 진행 상황. research()가 쓰고 progress()가 읽는다.
_PROGRESS = {"running": False, "log": [], "question": "", "started": 0.0,
             "follow_up": False, "stop": False}


def begin(question, follow_up=False):
    """연구원을 띄우는 동안에도 화면이 "도는 중"으로 보도록 미리 내건다.

    research()가 곧 같은 항목을 다시 채운다. 띄우기에 실패하면 abort()로 내린다.
    """
    _PROGRESS.update({"running": True, "starting": True, "log": [], "question": question,
                      "started": time.time(), "follow_up": bool(follow_up), "stop": False})


def abort():
    _PROGRESS["running"] = False
    _PROGRESS["starting"] = False


def request_stop():
    """중지를 요청한다. **락을 잡지 않는 경로에서 부른다.**

    연구가 POST 락을 쥐고 있으므로, 락을 기다리는 요청으로는 중지를 넣을 수 없다.
    진행 중인 호출을 끊지는 않고 다음 차례를 시작하지 않게 하므로, 이미 연구원에게
    맡겨 둔 일은 그것이 끝난 뒤에 멈춘다.
    """
    if not _PROGRESS["running"]:
        return {"ok": False, "message": "진행 중인 연구가 없습니다."}
    _PROGRESS["stop"] = True
    return {"ok": True, "message": "중지를 요청했습니다. 맡겨 둔 일이 끝나는 대로 멈춥니다."}


def progress():
    """지금까지 오간 내용을 그대로 돌려준다.

    **락을 잡지 않는 GET에서 부른다.** /api/research는 POST 락을 쥔 채 몇 분씩
    돌기 때문에, 진행 중인 내용을 보려면 그 락 밖에서 읽어야 한다.
    log는 위임 도구가 실시간으로 덧붙이는 목록과 같은 객체다.
    """
    return {
        "running": _PROGRESS["running"],
        "starting": bool(_PROGRESS.get("starting") and _PROGRESS["running"]),
        "stopping": bool(_PROGRESS["stop"] and _PROGRESS["running"]),
        "question": _PROGRESS["question"],
        "follow_up": _PROGRESS["follow_up"],
        "started": _PROGRESS["started"],
        "elapsed": (round(time.time() - _PROGRESS["started"], 1)
                    if _PROGRESS["started"] else 0.0),
        "log": list(_PROGRESS["log"]),      # 읽는 동안 늘어나도 되도록 복사해서 넘긴다
    }


def reset_session():
    _SESSION["items"] = None


def has_session():
    return bool(_SESSION["items"])


def research(question, follow_up=False):
    """연구 질문 하나를 끝까지 돌린다.

    follow_up이면 **앞선 연구의 대화를 이어받는다.** 연구책임자가 이미 받아 둔
    분석 설계를 기억하므로 값만 바꿔 다시 실행시킬 수 있다. 조사를 처음부터
    다시 시킬지 말지는 연구책임자가 정한다.

    특정 경로를 강제하지 않는다. 조사 → 실험 → 재조사는 가능한 흐름의 하나이며
    반드시 따라야 하는 순서는 아니다.
    """
    from . import runner

    started = time.time()
    log = []
    # 위임 도구에 더해, 스킬(HTML 문서 만들기 등)을 쓸 수 있다. 연구원에게는 주지 않는다.
    entries = _delegate_entries(log) + skills.entries()
    history = _SESSION["items"] if follow_up else None
    if not follow_up:
        reset_session()

    # 화면이 진행 중에 들여다볼 수 있도록 이 목록을 내건다.
    _PROGRESS.update({"running": True, "starting": False, "log": log, "question": question,
                      "started": started, "follow_up": bool(follow_up), "stop": False})
    try:
        try:
            out = runner.run(question, entries,
                             prompt=roles.ORCHESTRATOR_PROMPT,
                             max_steps=config.ORCH_MAX_STEPS,
                             history=history,
                             should_stop=lambda: _PROGRESS["stop"])
        except llm.QuotaExceeded:
            return {"ok": False, "message": "호출 한도에 걸렸습니다. 잠시 후 다시 시도해 주세요.",
                    "log": log}
        except (llm.LLMError, RuntimeError) as exc:
            return {"ok": False, "message": "처리하지 못했습니다: %s" % str(exc)[:140],
                    "log": log}

        _SESSION["items"] = out["items"]
        log.append({"kind": "final", "text": out["answer"], "at": time.time(),
                    "stopped": bool(out.get("stopped"))})
        return {"ok": True, "answer": out["answer"], "log": log,
                "tokens": out["tokens"], "steps": out["steps"],
                "follow_up": bool(follow_up), "stopped": bool(out.get("stopped")),
                "elapsed": round(time.time() - started, 1)}
    finally:
        # 어떻게 끝나든 "도는 중" 표시를 내린다. 내리지 않으면 화면이 계속 폴링한다.
        _PROGRESS["running"] = False
