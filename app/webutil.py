"""Accept: если браузер просит HTML — отдаём страницу, иначе JSON."""

from __future__ import annotations

from fastapi import Request


def wants_html(request: Request) -> bool:
    accept = (request.headers.get("accept") or "").lower()
    if "application/json" in accept and "text/html" not in accept:
        return False
    if "text/html" in accept:
        return True
    # формы из браузера часто без Accept, но с origin page
    content_type = (request.headers.get("content-type") or "").lower()
    if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
        hx = request.headers.get("hx-request")
        if hx:
            return True
        # fetch() из нашей страницы шлёт JSON; нативные form POST — HTML
        requested = request.headers.get("x-requested-with", "")
        if requested.lower() == "xmlhttprequest":
            return False
        sec_fetch = (request.headers.get("sec-fetch-mode") or "").lower()
        if sec_fetch == "navigate":
            return True
    return False
