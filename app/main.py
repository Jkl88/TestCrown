"""Точка входа: lifespan (Postgres/Redis), HTML/JSON ошибки, роуты."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from redis import Redis
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import settings
from .database import SessionLocal, engine, get_db
from .deps import get_limiter, get_optional_api_key
from .errors import AppError
from .gemini import gemini_configured
from .models import ApiKey, Summary
from .rate_limit import RateLimiter
from .routers import keys, summarize
from .upload_limits import install_upload_limits
from .webutil import wants_html

install_upload_limits()

logger = logging.getLogger("crown")

ROOT = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(ROOT / "templates"))

ERROR_TITLES = {
    400: "Некорректный запрос",
    401: "Нет API-ключа",
    403: "Доступ запрещён",
    404: "Страница не найдена",
    405: "Метод не поддерживается",
    413: "Файл слишком большой",
    422: "Неверные данные",
    429: "Слишком много запросов",
    500: "Внутренняя ошибка",
    502: "Ошибка Gemini",
    503: "Сервис недоступен",
}


def _error_page(
    request: Request,
    status_code: int,
    message: str,
    *,
    code: str | None = None,
    retry_after: int | None = None,
):
    title = ERROR_TITLES.get(status_code, "Ошибка")
    if wants_html(request):
        return templates.TemplateResponse(
            request,
            "error.html",
            {
                "status_code": status_code,
                "title": title,
                "message": message,
                "code": code,
                "retry_after": retry_after,
            },
            status_code=status_code,
        )
    body: dict = {"ok": False, "error": code or f"http_{status_code}", "message": message}
    if retry_after is not None:
        body["retry_after"] = retry_after
    headers = {}
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return JSONResponse(body, status_code=status_code, headers=headers or None)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    redis.ping()
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    app.state.redis = redis
    app.state.limiter = RateLimiter(
        redis,
        limit=settings.rate_limit_requests,
        window_sec=settings.rate_limit_window_sec,
    )
    app.state.templates = templates
    if not gemini_configured():
        logger.error("API_GMINI пуст — выдача ключей работает, суммаризация вернёт 503")
    else:
        logger.info("Gemini включён, модель %s", settings.gemini_model)
    yield
    redis.close()


app = FastAPI(
    title="Crown",
    description="Шлюз суммаризации тендерной документации (задания 1 + 8 + 9).",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
app.include_router(keys.router)
app.include_router(summarize.router)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return _error_page(
        request,
        exc.status_code,
        exc.message,
        code=exc.code,
        retry_after=exc.retry_after,
    )


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException):
    if isinstance(exc, AppError):
        return await app_error_handler(request, exc)
    detail = exc.detail if isinstance(exc.detail, str) else "Ошибка запроса"
    return _error_page(request, exc.status_code, detail)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    return _error_page(request, 422, "Проверьте поля запроса. Для суммаризации нужен файл PDF.")


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    logger.exception("необработанная ошибка")
    return _error_page(request, 500, "Что-то сломалось на сервере. Попробуйте ещё раз.")


@app.get("/api/health")
def health():
    db_ok = False
    redis_ok = False
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            db_ok = True
        finally:
            db.close()
    except Exception:
        logger.exception("health: postgres")
    try:
        redis_ok = bool(app.state.redis.ping())
    except Exception:
        logger.exception("health: redis")
    ok = db_ok and redis_ok
    status = 200 if ok else 503
    return JSONResponse(
        {
            "ok": ok,
            "service": "crown",
            "postgres": db_ok,
            "redis": redis_ok,
            "gemini": gemini_configured(),
        },
        status_code=status,
    )


@app.get("/")
def index(
    request: Request,
    db: Session = Depends(get_db),
    key: ApiKey | None = Depends(get_optional_api_key),
):
    quota = get_limiter(request).peek(key.id) if key is not None else None
    recent: list[Summary] = []
    if key is not None:
        recent = (
            db.query(Summary)
            .filter(Summary.api_key_id == key.id)
            .order_by(Summary.id.desc())
            .limit(5)
            .all()
        )
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "key": key,
            "quota": quota,
            "recent": recent,
            "gemini": gemini_configured(),
            "max_pdf_mb": settings.max_pdf_mb,
        },
    )
