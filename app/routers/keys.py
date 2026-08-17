"""Выдача тестового ключа и статус текущей cookie."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_limiter, get_optional_api_key, require_api_key
from ..errors import AppError
from ..models import ApiKey, utcnow
from ..rate_limit import RateLimiter
from ..security import (
    generate_api_key,
    hash_key,
    key_prefix,
    set_api_key_cookie,
    clear_api_key_cookie,
)
from ..webutil import wants_html

router = APIRouter(prefix="/api/keys", tags=["keys"])


@router.post("")
def issue_key(
    request: Request,
    db: Session = Depends(get_db),
    existing: ApiKey | None = Depends(get_optional_api_key),
):
    """
    Тестовая выдача ключа. Повторный вызов при живой cookie не плодит записи —
    возвращаем ту же сессию. Сырой ключ в JSON один раз, дальше только httpOnly cookie.
    """
    if existing is not None:
        body = {
            "ok": True,
            "reused": True,
            "prefix": existing.key_prefix,
            "message": "Ключ уже выдан и лежит в httpOnly cookie.",
        }
        if wants_html(request):
            return RedirectResponse("/", status_code=303)
        return JSONResponse(body)

    raw = generate_api_key()
    row = ApiKey(key_hash=hash_key(raw), key_prefix=key_prefix(raw))
    db.add(row)
    db.commit()
    db.refresh(row)

    body = {
        "ok": True,
        "reused": False,
        "prefix": row.key_prefix,
        "key": raw,
        "message": (
            "Ключ записан в httpOnly cookie. В JSON он есть один раз — для curl. "
            "В браузере JS его не прочитает."
        ),
    }
    if wants_html(request):
        response = RedirectResponse("/", status_code=303)
    else:
        response = JSONResponse(body)
    set_api_key_cookie(response, raw)
    return response


@router.get("/me")
def key_status(
    key: ApiKey = Depends(require_api_key),
    limiter: RateLimiter = Depends(get_limiter),
):
    quota = limiter.peek(key.id)
    return {
        "ok": True,
        "prefix": key.key_prefix,
        "created_at": key.created_at.isoformat() if key.created_at else None,
        "quota": {
            "limit": quota.limit,
            "used": quota.used,
            "remaining": quota.remaining,
            "window_sec": quota.window_sec,
        },
    }


@router.post("/revoke")
def revoke_key(
    request: Request,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_api_key),
):
    if key.revoked_at is None:
        key.revoked_at = utcnow()
        db.commit()
    if wants_html(request):
        response = RedirectResponse("/", status_code=303)
    else:
        response = JSONResponse({"ok": True, "revoked": True})
    clear_api_key_cookie(response)
    return response


@router.get("")
def keys_help():
    """Без POST ключ не выдаём — иначе GET из префетча браузера раздует таблицу."""
    raise AppError(
        405,
        "method_not_allowed",
        "Ключ выдаётся POST /api/keys. GET здесь ничего не создаёт.",
    )
