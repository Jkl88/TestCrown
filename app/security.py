"""Выдача и проверка API-ключей. Сырой ключ в cookie, в Postgres — только хэш."""

from __future__ import annotations

import hashlib
import secrets

from fastapi import Request, Response

from .config import settings

KEY_PREFIX = "crn_"


def generate_api_key() -> str:
    """Случайный ключ. Префикс crn_ — чтобы в логах сразу было видно, чей это токен."""
    return KEY_PREFIX + secrets.token_urlsafe(32)


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def key_prefix(raw: str) -> str:
    """Кусок для UI. Полный ключ JS не видит (httpOnly)."""
    return (raw or "")[:12]


def read_api_key_cookie(request: Request) -> str | None:
    raw = (request.cookies.get(settings.cookie_name) or "").strip()
    return raw or None


def set_api_key_cookie(response: Response, raw_key: str) -> None:
    response.set_cookie(
        key=settings.cookie_name,
        value=raw_key,
        max_age=settings.cookie_max_age_sec,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_api_key_cookie(response: Response) -> None:
    response.delete_cookie(key=settings.cookie_name, path="/")
