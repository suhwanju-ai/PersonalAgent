# -*- coding: utf-8 -*-
"""Checks for the app's loopback-only JSON endpoints."""


class RequestRejected(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def validate_local_host(handler, port):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    if handler.headers.get("Host", "").lower() not in allowed_hosts:
        raise RequestRejected(403, "요청한 호스트를 허용하지 않습니다.")


def validate_json_post(handler, *, port, max_body, browser_origins=None):
    """Validate local Host, request origin, JSON content type, and body size.

    ``browser_origins`` is the allowlist for the main UI. For private agent
    endpoints, pass an empty tuple: only same-machine non-browser callers are
    expected, and browser-supplied Origin headers are rejected.
    """
    validate_local_host(handler, port)

    origin = handler.headers.get("Origin")
    if browser_origins is None:
        allowed_origins = {
            f"http://127.0.0.1:{port}",
            f"http://localhost:{port}",
        }
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
