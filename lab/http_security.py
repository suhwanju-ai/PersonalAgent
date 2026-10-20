# -*- coding: utf-8 -*-
"""Checks for the app's local endpoints and explicitly trusted deployments."""


import base64
import binascii
import hmac


class RequestRejected(Exception):
    def __init__(self, status, message, headers=None):
        super().__init__(message)
        self.status = status
        self.headers = headers or {}


def validate_local_host(handler, port, trusted_origins=(), access_token=""):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    allowed_hosts.update(host for _, host in trusted_origins)
    host = handler.headers.get("Host", "").lower()
    if host not in allowed_hosts:
        raise RequestRejected(403, "요청한 호스트를 허용하지 않습니다.")
    _require_access(handler, host, trusted_origins, access_token)


def _require_access(handler, host, trusted_origins, access_token):
    """신뢰 origin(외부 노출)으로 들어온 요청은 APP_ACCESS_TOKEN을 비밀번호로 하는 Basic 인증을 요구한다.

    루프백 접속은 Host/Origin 검사가 방어선이라 인증하지 않는다. 토큰이 없으면 외부 접속 자체를 거부한다.
    프록시가 Host를 바꿔 보내도 Origin이 신뢰 origin이면 같은 검사를 받는다.
    """
    origin = handler.headers.get("Origin")
    via_trusted = (host in {h for _, h in trusted_origins}
                   or origin in {o for o, _ in trusted_origins})
    if not via_trusted:
        return
    if not access_token:
        raise RequestRejected(
            403, "외부 접속에는 .env의 APP_ACCESS_TOKEN 설정이 필요합니다.")
    challenge = {"WWW-Authenticate": 'Basic realm="Common Agent", charset="UTF-8"'}
    auth = handler.headers.get("Authorization", "")
    scheme, _, encoded = auth.partition(" ")
    if scheme.lower() != "basic":
        raise RequestRejected(401, "인증이 필요합니다.", challenge)
    try:
        _, _, password = base64.b64decode(encoded.strip(), validate=True).decode("utf-8").partition(":")
    except (binascii.Error, UnicodeDecodeError):
        raise RequestRejected(401, "인증이 필요합니다.", challenge)
    if not hmac.compare_digest(password.encode("utf-8"), access_token.encode("utf-8")):
        raise RequestRejected(401, "인증이 필요합니다.", challenge)


def validate_json_post(handler, *, port, max_body, browser_origins=None,
                       trusted_origins=(), access_token=""):
    """Validate local Host, request origin, JSON content type, and body size.

    ``browser_origins`` is the allowlist for the main UI. For private agent
    endpoints, pass an empty tuple: only same-machine non-browser callers are
    expected, and browser-supplied Origin headers are rejected.
    """
    validate_local_host(handler, port, trusted_origins, access_token)

    origin = handler.headers.get("Origin")
    if browser_origins is None:
        allowed_origins = {
            f"http://127.0.0.1:{port}",
            f"http://localhost:{port}",
        }
        allowed_origins.update(origin for origin, _ in trusted_origins)
        if origin not in allowed_origins:
            raise RequestRejected(403, "허용되지 않은 요청 출처입니다.")
    elif origin is not None:
        if origin not in browser_origins:
            raise RequestRejected(403, "허용되지 않은 요청 출처입니다.")

    if handler.headers.get("Sec-Fetch-Site", "").lower() == "cross-site":
        raise RequestRejected(403, "교차 출처 요청을 허용하지 않습니다.")
    if handler.headers.get_content_type() != "application/json":
        raise RequestRejected(415, "JSON 요청만 허용됩니다.")

    try:
        length = int(handler.headers.get("Content-Length") or 0)
    except ValueError:
        raise RequestRejected(400, "요청 크기를 확인할 수 없습니다.")
    if length < 0:
        raise RequestRejected(400, "요청 크기가 올바르지 않습니다.")
    if length > max_body:
        raise RequestRejected(413, "보낸 내용이 너무 큽니다.")
    return length
