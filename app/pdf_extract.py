"""Разбор PDF: сначала текст, если пусто (скан) — отдаём байты модели как есть."""

from __future__ import annotations

import io

from pypdf import PdfReader

# Ниже этого порога считаем, что текст не извлёкся (картинка/кривая кодировка).
MIN_USEFUL_CHARS = 400
# Gemini съедает большой контекст, но гонять 200 страниц извещения незачем.
MAX_TEXT_CHARS = 80_000


def extract_pdf_text(data: bytes) -> str:
    """Текст из текстового PDF. Сканы почти всегда дают пустую строку — это ок."""
    reader = PdfReader(io.BytesIO(data))
    chunks: list[str] = []
    for page in reader.pages:
        try:
            piece = page.extract_text() or ""
        except Exception:
            # битая страница не должна валить весь файл
            continue
        if piece.strip():
            chunks.append(piece)
    text = "\n\n".join(chunks).strip()
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + "\n\n[текст обрезан по длине]"
    return text


def is_pdf(data: bytes) -> bool:
    return data[:5] == b"%PDF-"
