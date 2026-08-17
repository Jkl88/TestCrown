"""Прокси к Gemini generateContent: PDF или извлечённый текст → JSON-выжимка тендера."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import httpx

from .config import settings

logger = logging.getLogger(__name__)

API_BASE = "https://generativelanguage.googleapis.com/v1beta"

SYSTEM_PROMPT = """Ты аналитик тендерной документации госзакупок РФ (44-ФЗ / 223-ФЗ).
Работай только по фактам из документа. Цифры, сроки и штрафы не выдумывай.

Верни СТРОГО JSON без markdown и без пояснений:
{
  "subject": "предмет закупки кратко или null",
  "customer": "заказчик если указан, иначе null",
  "contract_amount": "НМЦК / цена контракта с валютой, иначе null",
  "deadlines": "сроки выполнения / период / дата окончания, иначе null",
  "requirements": ["ключевые требования к исполнителю"],
  "penalties": ["штрафы, пени, неустойки"],
  "notes": "важные оговорки одной фразой или null"
}

Если поля в документе нет — null или пустой список. Не более 12 пунктов в каждом списке.
"""


def gemini_configured() -> bool:
    return bool((settings.api_gemini or "").strip())


def _proxy() -> str | None:
    p = (settings.ai_proxy_url or "").strip()
    return p or None


def _headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "x-goog-api-key": (settings.api_gemini or "").strip(),
    }


def _extract_text(data: dict[str, Any]) -> str:
    cands = data.get("candidates") or []
    if not cands:
        raise RuntimeError(f"Gemini: пустой ответ {data!r}"[:400])
    content = (cands[0] or {}).get("content") or {}
    parts = content.get("parts") or []
    texts = [str(p.get("text") or "") for p in parts if isinstance(p, dict)]
    out = "\n".join(t for t in texts if t).strip()
    if not out:
        raise RuntimeError(f"Gemini: нет текста в parts: {data!r}"[:400])
    return out


def parse_summary_json(raw: str) -> dict[str, Any]:
    """Модель иногда оборачивает JSON в ``` — снимаем ограду и чиним типы."""
    text = (raw or "").strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # на случай хвоста после JSON
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            data = json.loads(text[start : end + 1])
        else:
            raise RuntimeError("Gemini вернул не JSON") from None
    if not isinstance(data, dict):
        raise RuntimeError("Gemini вернул не объект")

    def _str(key: str) -> str | None:
        val = data.get(key)
        if val is None:
            return None
        s = str(val).strip()
        return s or None

    def _list(key: str) -> list[str]:
        val = data.get(key)
        if not isinstance(val, list):
            return []
        out: list[str] = []
        for item in val:
            s = str(item).strip()
            if s:
                out.append(s)
            if len(out) >= 12:
                break
        return out

    return {
        "subject": _str("subject"),
        "customer": _str("customer"),
        "contract_amount": _str("contract_amount"),
        "deadlines": _str("deadlines"),
        "requirements": _list("requirements"),
        "penalties": _list("penalties"),
        "notes": _str("notes"),
    }


def _upload_pdf(client: httpx.Client, *, filename: str, pdf_bytes: bytes) -> str:
    """
    Files API, не inline: base64 от 50 МБ не влезет в лимит generateContent (~20 МБ).
    Возвращает file.uri для file_data.
    """
    key = (settings.api_gemini or "").strip()
    start = client.post(
        f"{API_BASE.rsplit('/v1beta', 1)[0]}/upload/v1beta/files",
        headers={
            "x-goog-api-key": key,
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(len(pdf_bytes)),
            "X-Goog-Upload-Header-Content-Type": "application/pdf",
            "Content-Type": "application/json",
        },
        json={"file": {"display_name": filename[:120]}},
    )
    if start.status_code >= 400:
        raise RuntimeError(f"Gemini upload start HTTP {start.status_code}: {start.text[:300]}")
    upload_url = start.headers.get("x-goog-upload-url") or start.headers.get("X-Goog-Upload-URL")
    if not upload_url:
        raise RuntimeError("Gemini upload: нет X-Goog-Upload-URL")

    done = client.post(
        upload_url,
        headers={
            "x-goog-api-key": key,
            "Content-Length": str(len(pdf_bytes)),
            "X-Goog-Upload-Offset": "0",
            "X-Goog-Upload-Command": "upload, finalize",
        },
        content=pdf_bytes,
    )
    if done.status_code >= 400:
        raise RuntimeError(f"Gemini upload HTTP {done.status_code}: {done.text[:300]}")
    payload = done.json()
    info = payload.get("file") or payload
    name = str(info.get("name") or "").strip()
    uri = str(info.get("uri") or "").strip()
    if not name:
        raise RuntimeError(f"Gemini upload: нет file.name {payload!r}"[:400])

    for _ in range(30):
        state = str(info.get("state") or "").upper()
        if state == "ACTIVE":
            return uri or f"https://generativelanguage.googleapis.com/v1beta/{name}"
        if state == "FAILED":
            raise RuntimeError("Gemini не смог обработать PDF (state=FAILED)")
        time.sleep(1)
        poll = client.get(f"{API_BASE}/{name}", headers={"x-goog-api-key": key})
        if poll.status_code >= 400:
            raise RuntimeError(f"Gemini file poll HTTP {poll.status_code}")
        info = poll.json().get("file") or poll.json()
        name = str(info.get("name") or name)
        uri = str(info.get("uri") or uri)
    raise RuntimeError("Gemini слишком долго обрабатывает PDF")


def _delete_file(client: httpx.Client, file_uri_or_name: str) -> None:
    name = file_uri_or_name
    if "/files/" in name:
        name = "files/" + name.rsplit("/files/", 1)[-1]
    if not name.startswith("files/"):
        return
    try:
        client.delete(
            f"{API_BASE}/{name}",
            headers={"x-goog-api-key": (settings.api_gemini or "").strip()},
        )
    except Exception:
        logger.warning("gemini: не удалось удалить uploaded file %s", name)


def summarize_tender(*, filename: str, pdf_bytes: bytes, extracted_text: str) -> dict[str, Any]:
    """
    Если из PDF вылез нормальный текст — шлём его (дешевле).
    Иначе — PDF через Files API: так проходят сканы на десятки мегабайт.
    """
    if not gemini_configured():
        raise RuntimeError("Gemini не настроен (API_GMINI)")

    user_intro = (
        f"Файл: {filename}\nВыдели сумму контракта, сроки, требования к исполнителю и штрафы."
    )
    uploaded: str | None = None
    timeout = httpx.Timeout(180.0, connect=30.0)
    with httpx.Client(timeout=timeout, proxy=_proxy(), follow_redirects=True) as client:
        if extracted_text:
            parts: list[dict[str, Any]] = [
                {"text": user_intro + "\n\n--- текст документа ---\n" + extracted_text}
            ]
        else:
            uploaded = _upload_pdf(client, filename=filename, pdf_bytes=pdf_bytes)
            parts = [
                {"file_data": {"mime_type": "application/pdf", "file_uri": uploaded}},
                {"text": user_intro + "\nДокумент приложен как PDF (текст извлечь не удалось)."},
            ]

        body: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 2048,
                "responseMimeType": "application/json",
            },
        }

        chain = settings.gemini_model_list
        last_err: str | None = None
        try:
            for mid in chain:
                url = f"{API_BASE}/models/{mid}:generateContent"
                resp = client.post(url, headers=_headers(), json=body)
                if resp.status_code == 429:
                    last_err = f"{mid}: 429"
                    logger.warning("gemini: 429 на %s — следующая модель", mid)
                    continue
                if resp.status_code == 404:
                    last_err = f"{mid}: 404"
                    logger.warning("gemini: 404 на %s — модель недоступна", mid)
                    continue
                if resp.status_code >= 400:
                    raise RuntimeError(f"Gemini HTTP {resp.status_code}: {(resp.text or '')[:300]}")
                raw = _extract_text(resp.json())
                parsed = parse_summary_json(raw)
                parsed["model"] = mid
                return parsed
        finally:
            if uploaded:
                _delete_file(client, uploaded)

    raise RuntimeError(
        "Gemini rate limit на всех моделях: "
        + ", ".join(chain)
        + (f" ({last_err})" if last_err else "")
    )
