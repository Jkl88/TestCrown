"""Starlette по умолчанию режет multipart на 1 МБ — для извещений с ЕИС это мало."""

from __future__ import annotations

from starlette.requests import Request as StarletteRequest

from .config import settings

_orig_get_form = StarletteRequest._get_form


def _part_limit() -> int:
    # +2 МБ на границы multipart, не на сам PDF
    return settings.max_pdf_bytes + 2 * 1024 * 1024


async def _get_form(
    self,
    *,
    max_files: int | float = 1000,
    max_fields: int | float = 1000,
    max_part_size: int = 1024 * 1024,
):
    limit = _part_limit()
    if max_part_size < limit:
        max_part_size = limit
    return await _orig_get_form(
        self,
        max_files=max_files,
        max_fields=max_fields,
        max_part_size=max_part_size,
    )


def install_upload_limits() -> None:
    StarletteRequest._get_form = _get_form  # type: ignore[method-assign]
