"""Прокси к Gemini generateContent: PDF или извлечённый текст → JSON-выжимка тендера."""

from __future__ import annotations

import base64
import json
import logging
import re
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


def summarize_tender(*, filename: str, pdf_bytes: bytes, extracted_text: str) -> dict[str, Any]:
    """
    Если из PDF вылез нормальный текст — шлём его (дешевле).
    Иначе — сам PDF inline: модель читает сканы лучше, чем пустой extract.
    """
    if not gemini_configured():
        raise RuntimeError("Gemini не настроен (API_GMINI)")

    user_intro = (
        f"Файл: {filename}\n" "Выдели сумму контракта, сроки, требования к исполнителю и штрафы."
    )
    if extracted_text:
        parts: list[dict[str, Any]] = [
            {"text": user_intro + "\n\n--- текст документа ---\n" + extracted_text}
        ]
    else:
        b64 = base64.b64encode(pdf_bytes).decode("ascii")
        parts = [
            {"inline_data": {"mime_type": "application/pdf", "data": b64}},
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
    timeout = 120.0
    with httpx.Client(timeout=timeout, proxy=_proxy(), follow_redirects=True) as client:
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

    raise RuntimeError(
        "Gemini rate limit на всех моделях: "
        + ", ".join(chain)
        + (f" ({last_err})" if last_err else "")
    )
