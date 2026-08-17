from __future__ import annotations

from fastapi import HTTPException


class AppError(HTTPException):
    """HTTP-ошибка с машинным кодом — и JSON, и HTML-страница берут одно поле."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        retry_after: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        hdrs = dict(headers or {})
        if retry_after is not None:
            hdrs["Retry-After"] = str(retry_after)
        super().__init__(status_code=status_code, detail=message, headers=hdrs or None)
        self.code = code
        self.message = message
        self.retry_after = retry_after
