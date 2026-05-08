from __future__ import annotations

from typing import Any, Generic, TypeVar, cast
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Delete, Select, Update

from backend.app.db.app_role import (
    assert_tenant_context,
    get_tenant_context,
    set_tenant_context,
)
from backend.app.db.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    def __init__(
        self,
        session: AsyncSession,
        model: type[ModelT],
        tenant_id: int | None = None,
    ) -> None:
        self.session = session
        self.model = model
        self.tenant_id = tenant_id
        if tenant_id is not None:
            self._require_tenant_id(tenant_id)

    def statement_for_get(self, tenant_id: int, id: UUID) -> Select[tuple[ModelT]]:
        self._require_tenant_id(tenant_id)
        return select(self.model).where(
            getattr(self.model, "tenant_id") == tenant_id,
            getattr(self.model, "id") == id,
        )

    def statement_for_list(self, tenant_id: int) -> Select[tuple[ModelT]]:
        self._require_tenant_id(tenant_id)
        return select(self.model).where(getattr(self.model, "tenant_id") == tenant_id)

    def statement_for_update(
        self,
        tenant_id: int,
        id: UUID,
        payload: dict[str, Any],
    ) -> Update:
        self._require_tenant_id(tenant_id)
        data = self._payload_for_update(tenant_id, id, payload)
        return (
            update(self.model)
            .where(
                getattr(self.model, "tenant_id") == tenant_id,
                getattr(self.model, "id") == id,
            )
            .values(**data)
            .returning(self.model)
        )

    def statement_for_delete(self, tenant_id: int, id: UUID) -> Delete:
        self._require_tenant_id(tenant_id)
        return (
            delete(self.model)
            .where(
                getattr(self.model, "tenant_id") == tenant_id,
                getattr(self.model, "id") == id,
            )
            .returning(getattr(self.model, "id"))
        )

    async def get(self, tenant_id: int, id: UUID) -> ModelT | None:
        await self._ensure_tenant_context(tenant_id)
        instance = await self.session.scalar(self.statement_for_get(tenant_id, id))
        return cast(ModelT | None, instance)

    async def list(self, tenant_id: int) -> list[ModelT]:
        await self._ensure_tenant_context(tenant_id)
        result = await self.session.execute(self.statement_for_list(tenant_id))
        return list(result.scalars().all())

    async def create(self, tenant_id: int, payload: dict[str, Any]) -> ModelT:
        await self._ensure_tenant_context(tenant_id)
        data = self._payload_with_tenant_id(tenant_id, payload)
        instance = self.model(**data)
        self.session.add(instance)
        await self.session.flush()
        return instance

    async def update(
        self,
        tenant_id: int,
        id: UUID,
        payload: dict[str, Any],
    ) -> ModelT | None:
        await self._ensure_tenant_context(tenant_id)
        result = await self.session.execute(self.statement_for_update(tenant_id, id, payload))
        return cast(ModelT | None, result.scalar_one_or_none())

    async def delete(self, tenant_id: int, id: UUID) -> int:
        await self._ensure_tenant_context(tenant_id)
        result = await self.session.execute(self.statement_for_delete(tenant_id, id))
        deleted_id = result.scalar_one_or_none()
        return 0 if deleted_id is None else 1

    async def _ensure_tenant_context(self, tenant_id: int) -> None:
        self._require_tenant_id(tenant_id)

        if self.tenant_id is not None and self.tenant_id != tenant_id:
            raise ValueError("repository tenant_id must match method tenant_id.")

        current_tenant_id = await get_tenant_context(self.session)
        if current_tenant_id is None:
            await set_tenant_context(self.session, tenant_id)

        await assert_tenant_context(self.session, tenant_id)

    @staticmethod
    def _require_tenant_id(tenant_id: int) -> None:
        if not isinstance(tenant_id, int) or isinstance(tenant_id, bool) or tenant_id < 1:
            raise ValueError("tenant_id must be a positive integer.")

    @classmethod
    def _payload_with_tenant_id(
        cls,
        tenant_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        cls._require_tenant_id(tenant_id)
        data = dict(payload)

        if "tenant_id" in data and data["tenant_id"] != tenant_id:
            raise ValueError("payload tenant_id must match repository tenant_id.")

        data["tenant_id"] = tenant_id
        if "metadata" in data and "metadata_" not in data:
            data["metadata_"] = data.pop("metadata")
        return data

    @classmethod
    def _payload_for_update(
        cls,
        tenant_id: int,
        id: UUID,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        cls._require_tenant_id(tenant_id)
        data = dict(payload)

        if "tenant_id" in data:
            if data["tenant_id"] != tenant_id:
                raise ValueError("payload tenant_id must match repository tenant_id.")
            data.pop("tenant_id")

        if "id" in data:
            if data["id"] != id:
                raise ValueError("payload id must match repository id.")
            data.pop("id")

        if "metadata" in data and "metadata_" not in data:
            data["metadata_"] = data.pop("metadata")

        return data


__all__ = ["BaseRepository"]

