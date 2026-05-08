from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JsonDict = dict[str, Any]


def rls_ready_metadata() -> JsonDict:
    return {"rls_ready": True}


class Base(DeclarativeBase):
    pass


class TenantIdMixin:
    tenant_id: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
        server_default=sa.text("1"),
    )


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )


class UpdatedAtMixin:
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
        onupdate=lambda: datetime.now(tz=UTC),
    )

