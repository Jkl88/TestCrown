from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ApiKey(Base):
    """Ключ доступа. В БД только sha256, сырое значение живёт в httpOnly cookie."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    key_hash: Mapped[str] = mapped_column(sa.String(64), unique=True, index=True)
    key_prefix: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(sa.DateTime(), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(), nullable=True)

    summaries: Mapped[list["Summary"]] = relationship(back_populates="api_key")


class Summary(Base):
    """Результат разбора PDF. Нужен и для UI-истории, и чтобы не гонять Gemini повторно."""

    __tablename__ = "summaries"

    id: Mapped[int] = mapped_column(primary_key=True)
    api_key_id: Mapped[int] = mapped_column(
        sa.Integer(), sa.ForeignKey("api_keys.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    file_sha256: Mapped[str] = mapped_column(sa.String(64), index=True)
    subject: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    customer: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    contract_amount: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    deadlines: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    requirements_json: Mapped[str] = mapped_column(sa.Text(), nullable=False, default="[]")
    penalties_json: Mapped[str] = mapped_column(sa.Text(), nullable=False, default="[]")
    notes: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(), default=utcnow)

    api_key: Mapped[ApiKey] = relationship(back_populates="summaries")
