# -*- coding: utf-8 -*-
"""데이터 파일을 읽는 도구.

파일 읽기는 이 전용 도구로 제공한다. Python 코드 실행은 OS 수준 격리기가
마련될 때까지 비활성화되어 있다.

읽기 전용이고 `data/` 폴더 밖으로 나가지 않는다.
"""

import base64
import os

from . import config

MAX_CHARS = 6000
ALLOWED_EXT = (".csv", ".txt", ".json")
MAX_UPLOAD = 2 * 1024 * 1024          # 2MB. 여기서 다루는 표 자료는 이보다 훨씬 작다


def _safe(name):
    """`data/` 안의 파일만 허용한다. 경로를 거슬러 올라가지 못하게 한다."""
    base = os.path.basename((name or "").strip())
    if not base:
        return None
    path = os.path.join(config.RESEARCH_DIR, base)
    if not os.path.isfile(path):
        return None
    return path


def _target(name):
    """쓰거나 지울 경로. 아직 없는 파일이어도 된다.

    basename 만 남겨 폴더를 거슬러 올라가지 못하게 하고, 확장자를 제한한다.
    """
    base = os.path.basename((name or "").strip())
    if not base or base.startswith("."):
        return None
    if not base.lower().endswith(ALLOWED_EXT):
        return None
    return os.path.join(config.RESEARCH_DIR, base)


def listing():
    if not os.path.isdir(config.RESEARCH_DIR):
        return []
    return sorted(f for f in os.listdir(config.RESEARCH_DIR)
                  if f.lower().endswith(ALLOWED_EXT))


def listing_detail():
    """화면에 표시할 목록. 이름과 크기."""
    out = []
    for name in listing():
        try:
            out.append({"name": name,
                        "bytes": os.path.getsize(os.path.join(config.RESEARCH_DIR, name))})
        except OSError:
            continue
    return out


def save_upload(name, data_b64):
    """화면에서 올린 파일을 data/research/에 쓴다.

    multipart를 파싱하지 않는다. 이 앱의 POST는 전부 JSON이므로 화면에서
    base64로 실어 보내면 서버에 새 파서를 두지 않아도 된다.
    텍스트로 읽히지 않는 파일은 받지 않는다. read_data_file이 텍스트로 열기 때문이다.
    """
    path = _target(name)
    if path is None:
        return {"ok": False, "message": "csv · txt · json 파일만 올릴 수 있습니다."}
    try:
        raw = base64.b64decode(data_b64 or "", validate=True)
    except ValueError:
        return {"ok": False, "message": "파일을 읽지 못했습니다."}
    if not raw:
        return {"ok": False, "message": "빈 파일입니다."}
    if len(raw) > MAX_UPLOAD:
        return {"ok": False,
                "message": "파일이 너무 큽니다. %dMB 까지 올릴 수 있습니다."
                           % (MAX_UPLOAD // (1024 * 1024))}
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return {"ok": False,
                "message": "텍스트로 읽히지 않습니다. UTF-8로 저장한 텍스트 파일만 올릴 수 있습니다."}

    replaced = os.path.exists(path)
    try:
        os.makedirs(config.RESEARCH_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
    except OSError as exc:
        return {"ok": False, "message": "저장하지 못했습니다: %s" % str(exc)[:120]}
    return {"ok": True, "name": os.path.basename(path), "replaced": replaced}


def delete_file(name):
    path = _target(name)
    if path is None or not os.path.isfile(path):
        return {"ok": False, "message": "그런 파일이 없습니다."}
    try:
        os.remove(path)
    except OSError:
        return {"ok": False, "message": "지우지 못했습니다."}
    return {"ok": True, "name": os.path.basename(path)}


def read_data_file(name=""):
    """이름을 주지 않으면 읽을 수 있는 파일 목록을 돌려준다."""
    files = listing()
    if not (name or "").strip():
        return {"읽을 수 있는 파일": files,
                "안내": "파일 이름을 넣어 다시 부르면 내용을 돌려줍니다."}

    path = _safe(name)
    if path is None:
        return {"오류": "그런 파일이 없습니다: %s" % name, "읽을 수 있는 파일": files}
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            text = f.read()
    except OSError as exc:
        return {"오류": "파일을 읽지 못했습니다: %s" % str(exc)[:120]}

    cut = len(text) > MAX_CHARS
    # 코드에서 직접 열려는 시도가 잦으므로 열 수 있는 경로를 함께 알려 준다.
    # 실행 디렉터리가 앱의 최상위 폴더라 파일 이름만으로는 열리지 않는다.
    rel = os.path.relpath(path, config.ROOT).replace("\\", "/")
    return {"파일": os.path.basename(path),
            "코드에서 열 때 쓸 경로": rel,
            "내용": text[:MAX_CHARS] + (" …(생략)" if cut else "")}


TOOL = {
    "name": "read_data_file",
    "description": ("데이터 파일을 읽어 내용을 그대로 돌려준다. 이름 없이 부르면 "
                    "읽을 수 있는 파일 목록을 준다. 표 형태의 자료를 코드로 다루기 전에 "
                    "무엇이 들어 있는지 먼저 확인할 때 쓴다."),
    "parameters": {
        "type": "object",
        "properties": {"name": {"type": "string",
                                "description": "읽을 파일 이름. 비우면 목록을 준다"}},
    },
    "function": read_data_file,
    "source": "내장",
}
