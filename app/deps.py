"""Зависимости FastAPI: Redis, ключ из cookie, лимитер."""

from __future__ import annotations

from fastapi import Depends, Request
from redis import Redis
from sqlalchemy.orm import Session

from .database import get_db
from .errors import AppError
from .models import ApiKey
from .rate_limit import RateLimiter
from .security import hash_key, read_api_key_cookie


def get_redis(request: Request) -> Redis:
    return request.app.state.redis


def get_limiter(request: Request) -> RateLimiter:
    return request.app.state.limiter


def get_optional_api_key(
    request: Request,
    db: Session = Depends(get_db),
) -> ApiKey | None:
    raw = read_api_key_cookie(request)
    if not raw:
        return None
    row = db.query(ApiKey).filter(ApiKey.key_hash == hash_key(raw)).one_or_none()
    if row is None or row.revoked_at is not None:
        return None
    return row


def require_api_key(key: ApiKey | None = Depends(get_optional_api_key)) -> ApiKey:
    if key is None:
        raise AppError(401, "missing_api_key", "Нужен API-ключ. Получите его на главной.")
    return key
