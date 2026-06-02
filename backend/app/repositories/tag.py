from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.tag import TAG_COLORS, Tag, TicketTag
from backend.app.domain.tag import assert_tag_name_safe
from backend.app.repositories.audit_event import AuditEventRepository
from backend.app.repositories.ticket import TicketRepository


class TagNotFoundError(Exception):
    """ADR-00044: 指定 project に存在しない tag (→ 404)。"""

    def __init__(self, *, tag_id: UUID) -> None:
        super().__init__(f"tag {tag_id} not found for project.")
        self.tag_id = tag_id


class TagNameConflictError(Exception):
    """ADR-00044: 同 project に同名の tag が既に存在する (→ 409)。"""

    def __init__(self, *, name: str) -> None:
        super().__init__(f"a tag named {name!r} already exists in this project.")
        self.name = name


class TagColorInvalidError(Exception):
    """ADR-00044: palette 外の color (→ 422)。Pydantic と二重防御 (direct repository call 用)。"""

    def __init__(self, *, color: str) -> None:
        super().__init__(f"color {color!r} is not an allowed tag color.")
        self.color = color


class TagInUseError(Exception):
    """ADR-00044 R4: 使用中 (ticket_tags 有) tag の削除は不可 (→ 409)。FK2 RESTRICT と二重防御。"""

    def __init__(self, *, tag_id: UUID, attached_count: int) -> None:
        super().__init__(
            f"tag {tag_id} is attached to {attached_count} ticket(s); detach before deleting."
        )
        self.tag_id = tag_id
        self.attached_count = attached_count


class TagRepository:
    """ADR-00044 A-5: project-scoped tag CRUD + ticket への attach/detach。

    全 mutation は ``TicketRepository`` の active-project guard (FOR UPDATE lock で archive toggle と
    直列化) / ``assert_ticket_actionable`` を経由する。secret scan は ``assert_tag_name_safe`` (domain) に
    集約し、REST / MCP / seed のどの経路から create/rename を呼んでも raw secret tag name を弾く。
    ``BaseRepository`` の generic delete/update primitive は本 repository では公開しない (guard 迂回防止)。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._tickets = TicketRepository(session)
        self._audit = AuditEventRepository(session)

    async def list_tags(self, tenant_id: int, project_id: UUID) -> list[Tag]:
        # read path も RLS-ready な tenant context を設定する (app-role / RLS policy 整合、Codex R1 HIGH)
        await self._tickets._ensure_tenant_context(tenant_id)
        result = await self.session.execute(
            select(Tag)
            .where(Tag.tenant_id == tenant_id, Tag.project_id == project_id)
            .order_by(Tag.name)
        )
        return list(result.scalars().all())

    async def get_tag(self, tenant_id: int, project_id: UUID, tag_id: UUID) -> Tag | None:
        await self._tickets._ensure_tenant_context(tenant_id)
        return cast(
            "Tag | None",
            await self.session.scalar(
                select(Tag).where(
                    Tag.tenant_id == tenant_id,
                    Tag.project_id == project_id,
                    Tag.id == tag_id,
                )
            ),
        )

    async def create_tag(
        self,
        tenant_id: int,
        project_id: UUID,
        *,
        name: str,
        color: str,
        actor_id: UUID | None = None,
    ) -> Tag:
        # 存在 + active project を FOR UPDATE で要求 (archived → ProjectArchivedError=409)
        await self._tickets.assert_project_exists_active(tenant_id, project_id)
        normalized = name.strip()
        assert_tag_name_safe(normalized)  # raw secret / canary → ValueError=422
        if color not in TAG_COLORS:
            raise TagColorInvalidError(color=color)
        existing = await self.session.scalar(
            select(Tag.id).where(
                Tag.tenant_id == tenant_id,
                Tag.project_id == project_id,
                Tag.name == normalized,
            )
        )
        if existing is not None:
            raise TagNameConflictError(name=normalized)
        tag = Tag(
            id=uuid4(),
            tenant_id=tenant_id,
            project_id=project_id,
            name=normalized,
            color=color,
        )
        self.session.add(tag)
        await self.session.flush()
        if actor_id is not None:
            await self._audit.append(
                tenant_id=tenant_id,
                event_type="config_changed",
                payload={
                    "change": "tag_created",
                    "project_id": str(project_id),
                    "tag_id": str(tag.id),
                    "name": normalized,
                    "color": color,
                },
                actor_id=actor_id,
            )
        return tag

    async def rename_tag(
        self,
        tenant_id: int,
        project_id: UUID,
        tag_id: UUID,
        *,
        name: str | None = None,
        color: str | None = None,
    ) -> Tag:
        await self._tickets.assert_project_active(tenant_id, project_id)
        tag = await self.get_tag(tenant_id, project_id, tag_id)
        if tag is None:
            raise TagNotFoundError(tag_id=tag_id)
        if name is not None:
            normalized = name.strip()
            assert_tag_name_safe(normalized)
            if normalized != tag.name:
                conflict = await self.session.scalar(
                    select(Tag.id).where(
                        Tag.tenant_id == tenant_id,
                        Tag.project_id == project_id,
                        Tag.name == normalized,
                    )
                )
                if conflict is not None:
                    raise TagNameConflictError(name=normalized)
                tag.name = normalized
        if color is not None:
            if color not in TAG_COLORS:
                raise TagColorInvalidError(color=color)
            tag.color = color
        await self.session.flush()
        return tag

    async def delete_tag(
        self,
        tenant_id: int,
        project_id: UUID,
        tag_id: UUID,
        *,
        actor_id: UUID | None = None,
    ) -> None:
        await self._tickets.assert_project_active(tenant_id, project_id)
        tag = await self.get_tag(tenant_id, project_id, tag_id)
        if tag is None:
            raise TagNotFoundError(tag_id=tag_id)
        # 使用中ガード (FK2 RESTRICT と二重防御): 1 件でも付与があれば 409
        attached = (
            await self.session.scalar(
                select(func.count())
                .select_from(TicketTag)
                .where(
                    TicketTag.tenant_id == tenant_id,
                    TicketTag.project_id == project_id,
                    TicketTag.tag_id == tag_id,
                )
            )
            or 0
        )
        if attached > 0:
            raise TagInUseError(tag_id=tag_id, attached_count=int(attached))
        tag_name = tag.name
        await self.session.execute(
            delete(Tag).where(
                Tag.tenant_id == tenant_id,
                Tag.project_id == project_id,
                Tag.id == tag_id,
            )
        )
        # observability audit (復旧用 snapshot ではない、ADR-00044)
        await self._audit.append(
            tenant_id=tenant_id,
            event_type="config_changed",
            payload={
                "change": "tag_deleted",
                "project_id": str(project_id),
                "tag_id": str(tag_id),
                "name": tag_name,
            },
            actor_id=actor_id,
        )

    async def attach_tag(
        self,
        tenant_id: int,
        project_id: UUID,
        ticket_id: UUID,
        tag_id: UUID,
    ) -> None:
        # archived project → 409 / soft-deleted・不在 ticket → 404
        await self._tickets.assert_ticket_actionable(tenant_id, project_id, str(ticket_id))
        tag = await self.get_tag(tenant_id, project_id, tag_id)
        if tag is None:
            raise TagNotFoundError(tag_id=tag_id)
        existing = await self.session.scalar(
            select(TicketTag.tag_id).where(
                TicketTag.tenant_id == tenant_id,
                TicketTag.project_id == project_id,
                TicketTag.ticket_id == ticket_id,
                TicketTag.tag_id == tag_id,
            )
        )
        if existing is None:  # idempotent
            self.session.add(
                TicketTag(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    ticket_id=ticket_id,
                    tag_id=tag_id,
                )
            )
            await self.session.flush()

    async def detach_tag(
        self,
        tenant_id: int,
        project_id: UUID,
        ticket_id: UUID,
        tag_id: UUID,
    ) -> None:
        await self._tickets.assert_ticket_actionable(tenant_id, project_id, str(ticket_id))
        # attach と対称に tag の project 所属を検証する (Codex adversarial R5 HIGH)。
        # cross-project / nonexistent tag_id は path/target mismatch として 404 に fail-close し、
        # 0 rows delete を「成功」と取り違えて stale/越境 caller state を隠さない。
        # valid tag の未付与 detach は get_tag が通り 0 rows delete で idempotent 204 を維持する。
        tag = await self.get_tag(tenant_id, project_id, tag_id)
        if tag is None:
            raise TagNotFoundError(tag_id=tag_id)
        await self.session.execute(
            delete(TicketTag).where(
                TicketTag.tenant_id == tenant_id,
                TicketTag.project_id == project_id,
                TicketTag.ticket_id == ticket_id,
                TicketTag.tag_id == tag_id,
            )
        )

    async def tags_for_tickets(
        self,
        tenant_id: int,
        project_id: UUID,
        ticket_ids: Sequence[UUID] | Iterable[UUID],
    ) -> dict[UUID, list[Tag]]:
        """per-ticket の tag を **単一 join query** で bulk 取得 (N+1 回避、ADR-00044)。"""
        ids = list(ticket_ids)
        if not ids:
            return {}
        await self._tickets._ensure_tenant_context(tenant_id)  # RLS-ready (Codex R1 HIGH)
        result = await self.session.execute(
            select(TicketTag.ticket_id, Tag)
            .join(
                Tag,
                (Tag.tenant_id == TicketTag.tenant_id)
                & (Tag.project_id == TicketTag.project_id)
                & (Tag.id == TicketTag.tag_id),
            )
            .where(
                TicketTag.tenant_id == tenant_id,
                TicketTag.project_id == project_id,
                TicketTag.ticket_id.in_(ids),
            )
            .order_by(Tag.name)
        )
        out: dict[UUID, list[Tag]] = {}
        for ticket_id, tag in result.all():
            out.setdefault(ticket_id, []).append(tag)
        return out

    async def ticket_ids_with_tag(
        self, tenant_id: int, project_id: UUID, tag_id: UUID
    ) -> list[UUID]:
        """tag filter 用: 指定 tag を持つ ticket_id を返す (同 project scope)。"""
        await self._tickets._ensure_tenant_context(tenant_id)  # RLS-ready (Codex R1 HIGH)
        result = await self.session.execute(
            select(TicketTag.ticket_id).where(
                TicketTag.tenant_id == tenant_id,
                TicketTag.project_id == project_id,
                TicketTag.tag_id == tag_id,
            )
        )
        return list(result.scalars().all())


__all__ = [
    "TagRepository",
    "TagNotFoundError",
    "TagNameConflictError",
    "TagColorInvalidError",
    "TagInUseError",
]
