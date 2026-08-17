from starlette.requests import Request

from app.webutil import wants_html


def _req(headers: list[tuple[bytes, bytes]]) -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 123),
            "server": ("test", 80),
        }
    )


def test_browser_accept_html():
    assert wants_html(_req([(b"accept", b"text/html,application/xhtml+xml")]))


def test_json_client():
    assert not wants_html(_req([(b"accept", b"application/json")]))
