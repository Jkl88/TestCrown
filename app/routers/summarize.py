"""Загрузка PDF → лимит → Gemini → JSON/HTML с выжимкой."""

from __future__ import annotations

import hashlib
import json
import logging

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import get_limiter, require_api_key
from ..errors import AppError
from ..gemini import gemini_configured, summarize_tender
from ..models import ApiKey, Summary, utcnow
from ..pdf_extract import MIN_USEFUL_CHARS, extract_pdf_text, is_pdf
from ..rate_limit import RateLimiter
from ..webutil import wants_html

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["summarize"])


def _summary_payload(row: Summary, quota: dict) -> dict:
    return {
        "ok": True,
        "id": row.id,
        "filename": row.filename,
        "subject": row.subject,
        "customer": row.customer,
        "contract_amount": row.contract_amount,
        "deadlines": row.deadlines,
        "requirements": json.loads(row.requirements_json or "[]"),
        "penalties": json.loads(row.penalties_json or "[]"),
        "notes": row.notes,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "quota": quota,
    }


@router.post("/summarize")
def summarize(
    request: Request,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_api_key),
    limiter: RateLimiter = Depends(get_limiter),
    file: UploadFile = File(...),
):
    if not gemini_configured():
        raise AppError(503, "gemini_unconfigured", "Не задан API_GMINI — суммаризация выключена.")

    filename = (file.filename or "document.pdf").strip() or "document.pdf"
    if not filename.lower().endswith(".pdf"):
        raise AppError(400, "not_pdf", "Нужен файл с расширением .pdf.")

    data = file.file.read(settings.max_pdf_bytes + 1)
    if len(data) > settings.max_pdf_bytes:
        raise AppError(413, "file_too_large", "PDF больше 15 МБ — такой не принимаем.")
    if not data:
        raise AppError(400, "empty_file", "Пустой файл.")
    if not is_pdf(data):
        raise AppError(400, "not_pdf", "Это не PDF (нет сигнатуры %PDF-).")

    digest = hashlib.sha256(data).hexdigest()

    # повтор той же бумаги тем же ключом — из БД, Gemini не трогаем и лимит не жжём
    cached = (
        db.query(Summary)
        .filter(Summary.api_key_id == key.id, Summary.file_sha256 == digest)
        .order_by(Summary.id.desc())
        .first()
    )
    quota_peek = limiter.peek(key.id)
    quota = {
        "limit": quota_peek.limit,
        "used": quota_peek.used,
        "remaining": quota_peek.remaining,
        "window_sec": quota_peek.window_sec,
        "cached": True,
    }
    if cached is not None:
        payload = _summary_payload(cached, quota)
        if wants_html(request):
            return request.app.state.templates.TemplateResponse(
                request,
                "result.html",
                {"summary": payload, "key": key, "quota": quota_peek},
            )
        return JSONResponse(payload)

    hit = limiter.hit(key.id)
    if not hit.allowed:
        raise AppError(
            429,
            "rate_limited",
            f"Лимит {hit.limit} запросов в минуту. Подождите {hit.retry_after} с.",
            retry_after=hit.retry_after,
        )

    quota = {
        "limit": hit.limit,
        "used": hit.used,
        "remaining": hit.remaining,
        "window_sec": hit.window_sec,
        "cached": False,
    }

    try:
        text = extract_pdf_text(data)
    except Exception:
        logger.exception("не удалось разобрать PDF %s", filename)
        text = ""
    if len(text) < MIN_USEFUL_CHARS:
        text = ""

    try:
        parsed = summarize_tender(filename=filename, pdf_bytes=data, extracted_text=text)
    except RuntimeError as exc:
        logger.warning("gemini summarize failed: %s", exc)
        raise AppError(502, "upstream_error", str(exc)) from exc

    key.last_used_at = utcnow()
    row = Summary(
        api_key_id=key.id,
        filename=filename[:255],
        file_sha256=digest,
        subject=parsed.get("subject"),
        customer=parsed.get("customer"),
        contract_amount=parsed.get("contract_amount"),
        deadlines=parsed.get("deadlines"),
        requirements_json=json.dumps(parsed.get("requirements") or [], ensure_ascii=False),
        penalties_json=json.dumps(parsed.get("penalties") or [], ensure_ascii=False),
        notes=parsed.get("notes"),
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    payload = _summary_payload(row, quota)
    if wants_html(request):
        return request.app.state.templates.TemplateResponse(
            request,
            "result.html",
            {"summary": payload, "key": key, "quota": hit},
        )
    return JSONResponse(payload)


@router.get("/history")
def history(
    request: Request,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_api_key),
    limiter: RateLimiter = Depends(get_limiter),
):
    rows = (
        db.query(Summary)
        .filter(Summary.api_key_id == key.id)
        .order_by(Summary.id.desc())
        .limit(30)
        .all()
    )
    quota = limiter.peek(key.id)
    items = [
        {
            "id": r.id,
            "filename": r.filename,
            "subject": r.subject,
            "contract_amount": r.contract_amount,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    if wants_html(request):
        return request.app.state.templates.TemplateResponse(
            request,
            "history.html",
            {"items": items, "key": key, "quota": quota},
        )
    return JSONResponse({"ok": True, "items": items})
