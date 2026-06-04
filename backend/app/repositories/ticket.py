from __future__ import annotations

import builtins
from datetime import UTC, datetime
from typing import Any, NoReturn, cast
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.actor import Actor
from backend.app.db.models.project import Project
from backend.app.db.models.ticket import Ticket
from backend.app.repositories.base import BaseRepository


class ProjectArchivedError(Exception):
    """Q-4 (ADR-00037): archived project への child write (ticket create/update/import 等) は
    fail-closed。endpoint だけでなく全 ticket mutation が通る repository 境界で raise し、
    HTTP / MCP bridge / research-to-ticket promotion の全経路を凍結する (Codex plan R5)。
    """

    def __init__(self, *, project_id: UUID) -> None:
        super().__init__(
            f"project {project_id} is archived; unarchive it before mutating its tickets."
        )
        self.project_id = project_id


class ProjectNotFoundError(Exception):
    """Q-3 (ADR-00037): 存在しない project への bulk-soft-delete は 404。

    Codex adversarial finding #3: 存在しない project UUID でも active 件数 0 が
    `expected_active_count=0` と一致すると、phantom batch + audit を残してしまう。lock 取得時に
    project 不在を検出して明示的に raise する (audit は実 project の実遷移と 1:1)。
    """

    def __init__(self, *, project_id: UUID) -> None:
        super().__init__(f"project {project_id} not found for tenant.")
        self.project_id = project_id


class BulkDeleteCountMismatch(Exception):
    """Q-3 (ADR-00037): bulk-soft-delete の expected_active_count CAS 不一致 (409)。

    Codex adversarial finding #2: endpoint で count → 別 statement で update すると TOCTOU で
    stale baseline を 409 にできない。project row lock 保持下で count と update を atomic に行い、
    不一致なら本例外で rollback + 409。
    """

    def __init__(self, *, expected: int, actual: int) -> None:
        super().__init__(f"expected {expected} active tickets but found {actual}.")
        self.expected = expected
        self.actual = actual


class TicketNotActionableError(Exception):
    """Q-3 (ADR-00037 / Codex adversarial R3): soft-deleted / 存在しない ticket への作業開始は不可。

    bulk soft-delete 後の古い ticket_id で AgentRun 起動・承認要求・委譲・dispatch を行うと、削除した
    はずの作業が AI 実行・コスト発生へ進む。work-initiation 入口 (bridge_run_create 経由の
    run/delegation/dispatch + bridge_approval_request_create) で active ticket 存在を必須化する。
    """

    def __init__(self, *, ticket_id: str) -> None:
        super().__init__(f"ticket {ticket_id} is not actionable (deleted or not found).")
        self.ticket_id = ticket_id


class AssigneeNotAssignableError(Exception):
    """ADR-00046 (A-6): assignee_actor_id が同一 tenant の human actor を指さない。

    REST endpoint / MCP bridge / research adapter の全 ticket write 経路が通る repository
    choke point (create_in_project / update_in_project) で raise し、
    agent / provider / service / github_app への誤 assign と、cross-tenant / nonexistent
    actor (FK tickets_assignee_actor_fkey の IntegrityError 500) を事前に 422 化する。
    actor_type は caller 申告でなく DB から resolve する (server-owned-boundary)。
    """

    def __init__(self, *, assignee_actor_id: UUID) -> None:
        super().__init__(
            f"assignee {assignee_actor_id} must be a human actor in the same tenant."
        )
        self.assignee_actor_id = assignee_actor_id


class TicketRepository(BaseRepository[Ticket]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Ticket)

    async def _assert_assignee_human(
        self, tenant_id: int, assignee_actor_id: UUID
    ) -> None:
        """assignee は同一 tenant の ``actor_type='human'`` のみ許可する (ADR-00046 D-2)。

        FK (tickets_assignee_actor_fkey) は ``(tenant_id, assignee_actor_id)`` の存在のみを
        担保し ``actor_type`` を制約しない。REST / MCP bridge / research adapter のどの caller も
        ``create_in_project`` / ``update_in_project`` を通るため、ここを choke point として
        human-only + tenant を enforce する (R1 F-001、N-1/N-2 ADR-00041 と同型の迂回封鎖)。
        non-null の assignee 指定時のみ呼ぶ (null = 担当解除 / 未指定は検証 skip)。
        """
        actor_type = await self.session.scalar(
            select(Actor.actor_type).where(
                Actor.tenant_id == tenant_id,
                Actor.id == assignee_actor_id,
            )
        )
        if actor_type != "human":
            # actor 不在 / 別 tenant (None) も非 human も同じく reject (fail-closed)。
            raise AssigneeNotAssignableError(assignee_actor_id=assignee_actor_id)

    async def get(self, tenant_id: int, id: UUID) -> Ticket | None:
        raise NotImplementedError("Use get_in_project(...)")

    async def list(self, tenant_id: int) -> builtins.list[Ticket]:
        raise NotImplementedError("Use list_in_project(...)")

    async def create(self, tenant_id: int, payload: dict[str, Any]) -> Ticket:
        # Q-4 (ADR-00037 R5 #2): base ``create`` は archived guard (_assert_project_active) を
        # 通らないため、ticket では禁止して ``create_in_project`` に強制する。未 override のままだと
        # 非 HTTP 経路 (MCP bridge bridge_ticket_create 等) が base create を踏んで archived project へ
        # 書けてしまう (archive freeze bypass)。get/list/update/delete と同じく project 境界 + archive
        # guard を必須にするため、create も in-project 版へ閉じる。
        raise NotImplementedError("Use create_in_project(...)")

    async def update(
        self,
        tenant_id: int,
        id: UUID,
        payload: dict[str, Any],
    ) -> Ticket | None:
        raise NotImplementedError("Use update_in_project(...)")

    async def delete(self, tenant_id: int, id: UUID) -> int:
        raise NotImplementedError("Use delete_in_project(...)")

    def statement_for_get(self, tenant_id: int, id: UUID) -> NoReturn:
        raise NotImplementedError("Use statement_for_*_in_project / *_in_project.")

    def statement_for_list(self, tenant_id: int) -> NoReturn:
        raise NotImplementedError("Use statement_for_*_in_project / *_in_project.")

    def statement_for_update(
        self,
        tenant_id: int,
        id: UUID,
        payload: dict[str, Any],
    ) -> NoReturn:
        raise NotImplementedError("Use statement_for_*_in_project / *_in_project.")

    def statement_for_delete(self, tenant_id: int, id: UUID) -> NoReturn:
        raise NotImplementedError("Use statement_for_*_in_project / *_in_project.")

    async def _lock_project_status(self, tenant_id: int, project_id: UUID) -> str | None:
        """project row を ``FOR UPDATE`` で lock しつつ status を返す (不在は None)。

        Codex adversarial finding #1/#2: archive toggle (ProjectArchiveService.set_archived) も
        同じ project row を FOR UPDATE する。全 ticket mutation がこの lock を取ることで、archive と
        child write、bulk-delete の count↔update が同一 project row lock で直列化される。非ロック
        read だと「active を読んだ直後に別 tx が archived を commit → child write が flush される」
        race が残り、archive freeze と CAS が競合時に破れる。
        """
        return cast(
            "str | None",
            await self.session.scalar(
                select(Project.status)
                .where(
                    Project.tenant_id == tenant_id,
                    Project.id == project_id,
                )
                .with_for_update()
            ),
        )

    async def _assert_project_active(self, tenant_id: int, project_id: UUID) -> None:
        """Q-4 (ADR-00037): archived project への child write を fail-closed で拒否する。

        全 ticket mutation (create/update/import/restore) が本 helper を通るため、HTTP endpoint
        だけでなく MCP bridge / research-to-ticket promotion 等の直接 repository 呼び出しも凍結される。
        project row を FOR UPDATE lock し、archive toggle と直列化する (Codex adversarial #1)。
        """
        project_status = await self._lock_project_status(tenant_id, project_id)
        if project_status is not None and project_status != "active":
            raise ProjectArchivedError(project_id=project_id)

    async def get_in_project(
        self,
        tenant_id: int,
        project_id: UUID,
        ticket_id: UUID,
        *,
        include_deleted: bool = False,
    ) -> Ticket | None:
        await self._ensure_tenant_context(tenant_id)
        conditions = [
            Ticket.tenant_id == tenant_id,
            Ticket.project_id == project_id,
            Ticket.id == ticket_id,
        ]
        # Q-3 (ADR-00037): default は active scope (soft-deleted を全 read path で除外)。
        if not include_deleted:
            conditions.append(Ticket.deleted_at.is_(None))
        return cast(Ticket | None, await self.session.scalar(select(Ticket).where(*conditions)))

    async def list_in_project(
        self,
        tenant_id: int,
        project_id: UUID,
        *,
        include_deleted: bool = False,
    ) -> builtins.list[Ticket]:
        await self._ensure_tenant_context(tenant_id)
        conditions = [
            Ticket.tenant_id == tenant_id,
            Ticket.project_id == project_id,
        ]
        if not include_deleted:
            conditions.append(Ticket.deleted_at.is_(None))
        result = await self.session.execute(
            select(Ticket).where(*conditions).order_by(Ticket.created_at, Ticket.slug)
        )
        return list(result.scalars().all())

    async def count_active_in_project(self, tenant_id: int, project_id: UUID) -> int:
        await self._ensure_tenant_context(tenant_id)
        count = await self.session.scalar(
            select(func.count())
            .select_from(Ticket)
            .where(
                Ticket.tenant_id == tenant_id,
                Ticket.project_id == project_id,
                Ticket.deleted_at.is_(None),
            )
        )
        return int(count or 0)

    async def assert_project_active(self, tenant_id: int, project_id: UUID) -> None:
        """archived project への work 開始を凍結する public guard (FOR UPDATE lock で直列化)。

        ticket binding を持たない run / import 入口など、ticket を特定せず project の archive freeze
        だけを fail-closed で適用したい経路で使う (Codex adversarial R7)。
        """
        await self._ensure_tenant_context(tenant_id)
        await self._assert_project_active(tenant_id, project_id)

    async def assert_project_exists_active(self, tenant_id: int, project_id: UUID) -> None:
        """import 入口など、project の **存在** も要求する guard (R26 / Codex App PR review)。

        ``assert_project_active`` は archived のみ raise し、**存在しない project は no-op** のため、
        import で nonexistent project を渡すと dry_run が valid を返し、実 import が ticket FK 違反まで
        進んで 409 (誤った concurrent write) を返していた。bulk-delete (``bulk_soft_delete_in_project``) が
        ``ProjectNotFoundError`` (404) を返すのと非整合。project row を FOR UPDATE lock し、不在は
        ``ProjectNotFoundError`` (404)、archived は ``ProjectArchivedError`` (409) を raise する。
        """
        await self._ensure_tenant_context(tenant_id)
        project_status = await self._lock_project_status(tenant_id, project_id)
        if project_status is None:
            raise ProjectNotFoundError(project_id=project_id)
        if project_status != "active":
            raise ProjectArchivedError(project_id=project_id)

    async def assert_ticket_actionable(
        self,
        tenant_id: int,
        project_id: UUID,
        ticket_id: str,
    ) -> None:
        """work-initiation guard (Codex adversarial R3): archived project / soft-deleted ticket への
        作業開始 (AgentRun / approval / delegation / dispatch) を拒否する。

        archived project は ``ProjectArchivedError`` (→ 409)、soft-deleted / 存在しない / 形式不正な
        ticket は ``TicketNotActionableError`` (→ not_found 相当)。

        Codex adversarial R5 #1: project row を FOR UPDATE lock し、archive toggle / bulk-soft-delete
        と直列化する。非ロック read だと guard 読込後・mutation 作成前に別 tx が project を archive /
        ticket を soft-delete して commit でき、削除済/archived ticket に作業を作れてしまう (DoD
        「削除済/archived ticket への作業開始禁止」が競合時に破れる)。
        """
        await self._ensure_tenant_context(tenant_id)
        # archived project への作業開始を凍結する。project row を FOR UPDATE lock し archive toggle /
        # bulk-soft-delete と直列化する (R5 #1)。
        status = await self._lock_project_status(tenant_id, project_id)
        if status is not None and status != "active":
            raise ProjectArchivedError(project_id=project_id)
        # soft-deleted / 存在しない / 形式不正な ticket は actionable でない。project row lock 下で読むため
        # concurrent bulk-soft-delete と直列化され、削除済を active と誤認しない (active scope の get)。
        try:
            ticket_uuid = UUID(ticket_id)
        except (ValueError, AttributeError) as exc:
            raise TicketNotActionableError(ticket_id=ticket_id) from exc
        ticket = await self.get_in_project(
            tenant_id, project_id, ticket_uuid, include_deleted=False
        )
        if ticket is None:
            raise TicketNotActionableError(ticket_id=ticket_id)

    async def create_in_project(
        self,
        tenant_id: int,
        project_id: UUID,
        payload: dict[str, Any],
    ) -> Ticket:
        await self._ensure_tenant_context(tenant_id)
        await self._assert_project_active(tenant_id, project_id)
        data = self._payload_with_tenant_id(tenant_id, payload)

        if "project_id" in data and data["project_id"] != project_id:
            raise ValueError("payload project_id must match repository project_id.")

        data["project_id"] = project_id
        # ADR-00046 (A-6): assignee は human-only + tenant を choke point で enforce (R1 F-001)。
        # non-null 指定時のみ検証 (未指定 / null=未割当 は skip)。insert 前なので FK IntegrityError
        # に至る前に 422 化される (R1 F-004)。
        create_assignee = data.get("assignee_actor_id")
        if create_assignee is not None:
            await self._assert_assignee_human(tenant_id, create_assignee)
        ticket = Ticket(**data)
        self.session.add(ticket)
        await self.session.flush()
        return ticket

    async def update_in_project(
        self,
        tenant_id: int,
        project_id: UUID,
        ticket_id: UUID,
        payload: dict[str, Any],
    ) -> Ticket | None:
        await self._ensure_tenant_context(tenant_id)
        await self._assert_project_active(tenant_id, project_id)
        data = dict(payload)

        if "tenant_id" in data:
            if data["tenant_id"] != tenant_id:
                raise ValueError("payload tenant_id must match repository tenant_id.")
            data.pop("tenant_id")

        data = self._payload_for_update(tenant_id, ticket_id, data)

        if "project_id" in data:
            if data["project_id"] != project_id:
                raise ValueError("payload project_id must match repository project_id.")
            data.pop("project_id")

        # ADR-00046 (A-6): assignee 変更時のみ human-only + tenant を choke point で enforce。
        # payload に assignee_actor_id が無い (未変更) / null (担当解除) は skip (R1 F-001/F-004)。
        if "assignee_actor_id" in data and data["assignee_actor_id"] is not None:
            await self._assert_assignee_human(tenant_id, data["assignee_actor_id"])

        # active scope: soft-deleted ticket は update 対象にしない。
        result = await self.session.execute(
            update(Ticket)
            .where(
                Ticket.tenant_id == tenant_id,
                Ticket.project_id == project_id,
                Ticket.id == ticket_id,
                Ticket.deleted_at.is_(None),
            )
            .values(**data)
            .returning(Ticket)
        )
        return result.scalar_one_or_none()

    async def bulk_soft_delete_in_project(
        self,
        tenant_id: int,
        project_id: UUID,
        *,
        expected_active_count: int,
        deleted_by_actor_id: UUID,
    ) -> tuple[UUID | None, int]:
        """Q-3 (ADR-00037): project 内 active 全 ticket を新 deletion batch で soft-delete。

        **project row lock 保持下で existence + archive + CAS + update を atomic に行う**
        (Codex adversarial #1/#2/#3)。返り値 (batch_id|None, soft_deleted_count) で、no-op
        (active 0 件) は (None, 0)。caller (endpoint) は count>0 のときのみ audit + commit する。

        - 存在チェック: project 不在は ``ProjectNotFoundError`` (404)。phantom batch/audit を防ぐ。
        - archive freeze: archived は ``ProjectArchivedError`` (409、全 mutation 境界で凍結)。
        - CAS: lock 下で count し ``expected_active_count`` と不一致なら ``BulkDeleteCountMismatch``
          (409)。lock により concurrent create が直列化されるため count↔update に TOCTOU がない。
        """
        await self._ensure_tenant_context(tenant_id)
        # project row を FOR UPDATE lock。archive toggle / concurrent create と直列化する。
        status = await self._lock_project_status(tenant_id, project_id)
        if status is None:
            raise ProjectNotFoundError(project_id=project_id)
        if status != "active":
            raise ProjectArchivedError(project_id=project_id)
        # lock 保持下で count → CAS (concurrent create は lock で直列化されるため一貫)。
        current_active = await self.count_active_in_project(tenant_id, project_id)
        if current_active != expected_active_count:
            raise BulkDeleteCountMismatch(
                expected=expected_active_count, actual=current_active
            )
        if current_active == 0:
            # no-op (active 0 件): batch を発行せず、caller は audit を残さない (実遷移と 1:1)。
            return None, 0
        batch_id = uuid4()
        result = await self.session.execute(
            update(Ticket)
            .where(
                Ticket.tenant_id == tenant_id,
                Ticket.project_id == project_id,
                Ticket.deleted_at.is_(None),
            )
            .values(
                deleted_at=datetime.now(tz=UTC),
                deleted_batch_id=batch_id,
                deleted_by_actor_id=deleted_by_actor_id,
            )
            .returning(Ticket.id)
        )
        return batch_id, len(result.scalars().all())

    async def restore_batch_in_project(
        self,
        tenant_id: int,
        project_id: UUID,
        batch_id: UUID,
    ) -> int:
        """Q-3 (ADR-00037): 特定 deletion batch のみ復元 (Codex plan R2)。

        UPDATE は tenant + project + batch + deleted_at IS NOT NULL で限定 (越境復活防止)。
        restored_count を返す。再 restore / 別 project / 空 batch は 0 (idempotent)。

        Q-4 (ADR-00037 R5 #2): archived project への restore は fail-closed (ProjectArchivedError)。
        unarchive を要求する。archived project に active ticket が再出現しないよう archive freeze を
        全経路で enforce する。
        """
        await self._ensure_tenant_context(tenant_id)
        await self._assert_project_active(tenant_id, project_id)
        result = await self.session.execute(
            update(Ticket)
            .where(
                Ticket.tenant_id == tenant_id,
                Ticket.project_id == project_id,
                Ticket.deleted_batch_id == batch_id,
                Ticket.deleted_at.is_not(None),
            )
            .values(deleted_at=None, deleted_batch_id=None, deleted_by_actor_id=None)
            .returning(Ticket.id)
        )
        return len(result.scalars().all())

    async def existing_slugs_in_project(
        self,
        tenant_id: int,
        project_id: UUID,
    ) -> builtins.set[str]:
        """Q-2 (ADR-00037): project 内の全 slug (active + soft-deleted) を返す。

        slug unique (``tickets_uq_tenant_project_slug``) は全行に効くため soft-deleted ticket の slug も
        予約されている。import の衝突検出は active だけでなく deleted も対象にする (delete 済 slug の
        再利用は reject = hard delete 相当で P0 out)。
        """
        await self._ensure_tenant_context(tenant_id)
        result = await self.session.execute(
            select(Ticket.slug).where(
                Ticket.tenant_id == tenant_id,
                Ticket.project_id == project_id,
            )
        )
        return set(result.scalars().all())

    async def import_tickets_in_project(
        self,
        tenant_id: int,
        project_id: UUID,
        items: builtins.list[dict[str, Any]],
    ) -> builtins.list[Ticket]:
        """Q-2 (ADR-00037): 検証済み ticket payload を単一 transaction で一括 insert。

        archived guard (``_assert_project_active``) + 全件 add → flush。flush 時に
        ``tickets_uq_tenant_project_slug`` UNIQUE 違反 (並行 import が app-level pre-validation を
        すり抜けた場合) があれば IntegrityError が送出され、caller (endpoint) が transaction 全体を
        rollback する (DB-level 最終防衛、partial write なし)。caller は事前に in-payload / 既存 slug
        衝突と件数上限を検証してから本メソッドを呼ぶ。
        """
        await self._ensure_tenant_context(tenant_id)
        await self._assert_project_active(tenant_id, project_id)
        tickets: builtins.list[Ticket] = []
        for item in items:
            data = self._payload_with_tenant_id(tenant_id, item)
            if "project_id" in data and data["project_id"] != project_id:
                raise ValueError("payload project_id must match repository project_id.")
            data["project_id"] = project_id
            ticket = Ticket(**data)
            self.session.add(ticket)
            tickets.append(ticket)
        await self.session.flush()
        return tickets

    async def delete_in_project(
        self,
        tenant_id: int,
        project_id: UUID,
        ticket_id: UUID,
    ) -> int:
        """**Hard delete primitive — production の delete 経路ではない**。

        ADR-00037 で production の ticket 削除は **soft-delete (bulk_soft_delete_in_project) + batch
        restore + audit** に統一されており、HTTP endpoint / MCP bridge から本メソッドへの経路は無い
        (ticket DELETE endpoint は Tier 4 で未実装)。現状の caller は tenant/project boundary を検証
        する security/contract test のみ。

        Codex adversarial R2 #1: 本メソッドは soft-delete / audit 契約を bypass する hard delete の
        ため、archive freeze だけは他 mutation と同じく enforce する (`_assert_project_active`、archived
        project への物理削除を 409 で拒否)。soft-delete モデルへの完全統合 (hard delete 撤去 or
        maintenance-only gate 化) は pre-existing security/contract test に依存するため follow-up に
        defer (ADR-00037 残リスク)。本メソッドを production endpoint に配線しないこと。
        """
        await self._ensure_tenant_context(tenant_id)
        await self._assert_project_active(tenant_id, project_id)
        result = await self.session.execute(
            delete(Ticket)
            .where(
                Ticket.tenant_id == tenant_id,
                Ticket.project_id == project_id,
                Ticket.id == ticket_id,
            )
            .returning(Ticket.id)
        )
        deleted_id = result.scalar_one_or_none()
        return 0 if deleted_id is None else 1


__all__ = [
    "BulkDeleteCountMismatch",
    "ProjectArchivedError",
    "ProjectNotFoundError",
    "TicketNotActionableError",
    "TicketRepository",
]

