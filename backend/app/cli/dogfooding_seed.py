"""TaskManagedAI dogfooding seed (SP-012-10 BL-DOG-001/002/003).

docs/sprints/ の Sprint Pack を Ticket として DB に seed 投入。idempotent
(`metadata.dogfooding_source` + slug 一意性で re-run 重複 reject)。

usage:
    uv run python -m backend.app.cli.dogfooding_seed --dry-run   # DB 変更なし、変更予定だけ表示
    uv run python -m backend.app.cli.dogfooding_seed --apply     # DB 投入

invariant:
- default_tenant_id (1) + default_project_id (seeds/initial.py 由来) で投入
- slug = `dogfooding-sprint-<sprint-id-kebab>` で一意 (re-run は update / no-op)
- raw secret canary: Sprint Pack 本文に test fixture pattern が含まれる場合は
  本実装段階では parse 範囲が title + objective 1 行のみのため、secret canary
  混入リスクは低い (Sprint Pack `## 目的` 章に raw key を書かない invariant)
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import get_settings
from backend.app.db.models.ticket import Ticket, TicketStatus
from backend.app.db.session import create_engine
from backend.app.seeds.initial import (
    DEFAULT_ACTOR_ID,
    DEFAULT_PROJECT_ID,
    DEFAULT_TENANT_ID,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SPRINTS_DIR = _REPO_ROOT / "docs" / "sprints"
_ADR_DIR = _REPO_ROOT / "docs" / "adr"
_P0_BACKLOG_PATH = _REPO_ROOT / "docs" / "実装計画" / "P0_バックログ.md"

# BL row regex: `| BL-NNNN[a-z]? | title | sprint_no | type | trace | priority | days | depends_on | sprint_pack |`
_BL_ROW_REGEX = re.compile(
    r"^\|\s*(BL-\d{4}[a-z]?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|"
    r"\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|"
)

# Sprint Pack frontmatter status -> Ticket status mapping
_SPRINT_STATUS_TO_TICKET_STATUS: dict[str, str] = {
    "draft": "open",
    "proposed": "open",
    "ready": "open",
    "in_progress": "in_progress",
    "completed": "closed",
    "partial_completed_with_carry_over": "closed",
    "skeleton_pending_backend": "in_progress",
    "done_with_phase5_defer": "closed",
    "partial_skeleton": "in_progress",
}

# ADR frontmatter status -> Ticket status mapping
_ADR_STATUS_TO_TICKET_STATUS: dict[str, str] = {
    "proposed": "open",       # review 中
    "accepted": "closed",     # 採用済
    "rejected": "cancelled",  # 却下
    "superseded": "cancelled",  # 別 ADR で置換
    "deprecated": "cancelled",
}


@dataclass(frozen=True)
class SprintPackMeta:
    """Sprint Pack frontmatter から抽出した meta info."""

    file_name: str
    id: str
    status: str
    sprint_no: str | None
    target_days: str | None
    max_days: str | None
    objective: str  # `## 目的` 章の最初の段落 (1 段落のみ)

    @property
    def ticket_status(self) -> str:
        return _SPRINT_STATUS_TO_TICKET_STATUS.get(self.status, "open")

    @property
    def slug(self) -> str:
        """Ticket slug = `dogfooding-sprint-<id-kebab>`."""
        kebab = re.sub(r"[^a-z0-9-]+", "-", self.id.lower()).strip("-")
        return f"dogfooding-sprint-{kebab}"

    @property
    def title(self) -> str:
        return f"Sprint Pack: {self.id}"

    @property
    def description(self) -> str:
        sprint_no = f"sprint_no={self.sprint_no}, " if self.sprint_no else ""
        days = (
            f"target_days={self.target_days}/max={self.max_days}"
            if self.target_days and self.max_days
            else ""
        )
        return (
            f"[Sprint Pack] {sprint_no}{days}\n\n"
            f"frontmatter status: {self.status} → ticket status: {self.ticket_status}\n\n"
            f"## 目的\n{self.objective}"
        )

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "rls_ready": True,
            "dogfooding_source": {
                "type": "sprint_pack",
                "id": self.id,
                "file_name": self.file_name,
                "sprint_status": self.status,
            },
        }


def _parse_frontmatter(content: str) -> dict[str, str]:
    """Markdown frontmatter (`---\\n...\\n---`) を YAML-like で parse.

    YAML parser dep 追加せず、simple line-based parse (key: value のみ、
    list / nested は無視)。Sprint Pack frontmatter は flat key-value が
    主体 (id / status / sprint_no / target_days 等)。
    """
    match = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
    if not match:
        return {}
    block = match.group(1)
    result: dict[str, str] = {}
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # nested list (- item) and indented lines は skip (flat only)
        if stripped.startswith("-") or line.startswith(" "):
            continue
        if ":" not in stripped:
            continue
        key, _, raw_value = stripped.partition(":")
        value = raw_value.strip().strip('"').strip("'")
        if value:
            result[key.strip()] = value
    return result


def _extract_objective(content: str) -> str:
    """Sprint Pack `## 目的` 章の最初の段落を抽出 (1 段落のみ、最大 500 chars)。"""
    match = re.search(r"^##\s+目的\s*\n(.+?)(?=\n##\s+|\Z)", content, re.MULTILINE | re.DOTALL)
    if not match:
        return "(no objective section)"
    section = match.group(1).strip()
    # 最初の段落 (空行で区切られた最初の block)
    first_paragraph = section.split("\n\n")[0].strip()
    if len(first_paragraph) > 500:
        first_paragraph = first_paragraph[:497] + "..."
    return first_paragraph


def discover_sprint_packs() -> list[Path]:
    """docs/sprints/ から SP-*.md を検出 (template + README 除外)。"""
    return sorted(
        path
        for path in _SPRINTS_DIR.glob("SP-*.md")
        if not path.name.startswith("_template")
    )


def parse_sprint_pack(path: Path) -> SprintPackMeta | None:
    """Sprint Pack file から meta 抽出。frontmatter 不在なら None。"""
    content = path.read_text(encoding="utf-8")
    fm = _parse_frontmatter(content)
    if "id" not in fm or "status" not in fm:
        return None
    return SprintPackMeta(
        file_name=path.name,
        id=fm["id"],
        status=fm["status"],
        sprint_no=fm.get("sprint_no"),
        target_days=fm.get("target_days"),
        max_days=fm.get("max_days"),
        objective=_extract_objective(content),
    )


@dataclass(frozen=True)
class AdrMeta:
    """ADR frontmatter から抽出した meta info."""

    file_name: str
    id: str  # ADR-NNNNN
    title: str
    status: str
    date: str | None  # 起票日
    accepted_at: str | None

    @property
    def ticket_status(self) -> str:
        return _ADR_STATUS_TO_TICKET_STATUS.get(self.status, "open")

    @property
    def slug(self) -> str:
        """Ticket slug = `dogfooding-adr-<id-kebab>`."""
        kebab = re.sub(r"[^a-z0-9-]+", "-", self.id.lower()).strip("-")
        return f"dogfooding-adr-{kebab}"

    @property
    def title_full(self) -> str:
        return f"ADR: {self.id} - {self.title[:80]}"

    @property
    def description(self) -> str:
        accepted = f" / accepted_at={self.accepted_at}" if self.accepted_at else ""
        return (
            f"[ADR] {self.id}, date={self.date or 'unknown'}{accepted}\n\n"
            f"frontmatter status: {self.status} → ticket status: {self.ticket_status}\n\n"
            f"## title\n{self.title}"
        )

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "rls_ready": True,
            "dogfooding_source": {
                "type": "adr",
                "id": self.id,
                "file_name": self.file_name,
                "adr_status": self.status,
            },
        }


def discover_adrs() -> list[Path]:
    """docs/adr/ から NNNNN_*.md を検出 (template + README 除外)。"""
    return sorted(
        path
        for path in _ADR_DIR.glob("*.md")
        if not path.name.startswith("_template")
        and not path.name.upper() == "README.MD"
        and path.name != "README.md"
    )


def parse_adr(path: Path) -> AdrMeta | None:
    """ADR file から meta 抽出。frontmatter 不在なら None。"""
    content = path.read_text(encoding="utf-8")
    fm = _parse_frontmatter(content)
    if "id" not in fm or "status" not in fm:
        return None
    return AdrMeta(
        file_name=path.name,
        id=fm["id"],
        title=fm.get("title", path.stem),
        status=fm["status"],
        date=fm.get("date"),
        accepted_at=fm.get("accepted_at"),
    )


async def _query_existing_dogfooding_tickets(
    session: AsyncSession,
    *,
    slug_prefix: str = "dogfooding-",
) -> dict[str, Ticket]:
    """既存 dogfooding ticket を slug → Ticket で索引化."""
    stmt = select(Ticket).where(
        Ticket.tenant_id == DEFAULT_TENANT_ID,
        Ticket.project_id == DEFAULT_PROJECT_ID,
        Ticket.slug.like(f"{slug_prefix}%"),
    )
    result = await session.execute(stmt)
    return {ticket.slug: ticket for ticket in result.scalars().all()}


@dataclass(frozen=True)
class BlMeta:
    """BL (P0 バックログ) row から抽出した meta info."""

    id: str          # BL-NNNN[a-z]?
    title: str
    sprint_no: str
    bl_type: str     # doc / foundation / feature / test / runtime / research / 等
    trace: str       # F-NNN, AC-HARD-NN, NF-NNN 等 (multi-comma OK)
    priority: str    # P0-A / P0-B / P0-C / P1
    days: str        # target_days
    depends_on: str  # BL-NNNN OR `-`
    sprint_pack: str  # SP-NNN_xxx

    @property
    def ticket_status(self) -> str:
        """BL は status field なし、default は open。

        将来 (P0.1+) で BL 単位 status track 追加時に拡張。
        """
        return "open"

    @property
    def slug(self) -> str:
        """Ticket slug = `dogfooding-bl-<id-kebab>`."""
        kebab = self.id.lower().replace("_", "-")
        return f"dogfooding-bl-{kebab}"

    @property
    def title_full(self) -> str:
        truncated = self.title[:80] + "..." if len(self.title) > 80 else self.title
        return f"BL: {self.id} - {truncated}"

    @property
    def description(self) -> str:
        return (
            f"[BL] sprint={self.sprint_no}, type={self.bl_type}, priority={self.priority}, "
            f"days={self.days}\n\n"
            f"trace: {self.trace}\n"
            f"depends_on: {self.depends_on}\n"
            f"sprint_pack: {self.sprint_pack}\n\n"
            f"## title\n{self.title}"
        )

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "rls_ready": True,
            "dogfooding_source": {
                "type": "bl",
                "id": self.id,
                "sprint_no": self.sprint_no,
                "bl_type": self.bl_type,
                "trace": self.trace,
                "priority": self.priority,
                "sprint_pack": self.sprint_pack,
            },
        }


def discover_bls() -> list[BlMeta]:
    """docs/実装計画/P0_バックログ.md から BL row を抽出."""
    if not _P0_BACKLOG_PATH.exists():
        return []
    content = _P0_BACKLOG_PATH.read_text(encoding="utf-8")
    bls: list[BlMeta] = []
    for line in content.splitlines():
        match = _BL_ROW_REGEX.match(line)
        if not match:
            continue
        bls.append(
            BlMeta(
                id=match.group(1).strip(),
                title=match.group(2).strip(),
                sprint_no=match.group(3).strip(),
                bl_type=match.group(4).strip(),
                trace=match.group(5).strip(),
                priority=match.group(6).strip(),
                days=match.group(7).strip(),
                depends_on=match.group(8).strip(),
                sprint_pack=match.group(9).strip(),
            )
        )
    return bls


@dataclass
class SeedReport:
    rows_added: int = 0
    rows_updated: int = 0
    rows_unchanged: int = 0
    failures: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows_added": self.rows_added,
            "rows_updated": self.rows_updated,
            "rows_unchanged": self.rows_unchanged,
            "failures": self.failures or [],
        }


async def seed_sprint_packs(
    session: AsyncSession,
    *,
    sprint_packs: Iterable[SprintPackMeta],
    dry_run: bool,
) -> SeedReport:
    """Sprint Pack を Ticket として idempotent seed 投入。

    - 既存 (同 slug) があれば status / metadata を update
    - 不在なら create
    - dry_run=True なら DB 操作なし、計画だけ集計
    """
    report = SeedReport(failures=[])
    existing = await _query_existing_dogfooding_tickets(session)

    for pack in sprint_packs:
        existing_ticket = existing.get(pack.slug)
        try:
            if existing_ticket is None:
                if not dry_run:
                    new_ticket = Ticket(
                        tenant_id=DEFAULT_TENANT_ID,
                        project_id=DEFAULT_PROJECT_ID,
                        slug=pack.slug,
                        title=pack.title,
                        description=pack.description,
                        status=cast(TicketStatus, pack.ticket_status),
                        created_by_actor_id=DEFAULT_ACTOR_ID,
                        metadata_=pack.metadata,
                    )
                    session.add(new_ticket)
                report.rows_added += 1
            else:
                # status / title / description / metadata の delta を確認
                changed = (
                    existing_ticket.status != pack.ticket_status
                    or existing_ticket.title != pack.title
                    or existing_ticket.description != pack.description
                    or existing_ticket.metadata_ != pack.metadata
                )
                if changed:
                    if not dry_run:
                        existing_ticket.title = pack.title
                        existing_ticket.description = pack.description
                        existing_ticket.status = cast(TicketStatus, pack.ticket_status)
                        existing_ticket.metadata_ = pack.metadata
                    report.rows_updated += 1
                else:
                    report.rows_unchanged += 1
        except Exception as exc:  # noqa: BLE001  # CLI surface
            if report.failures is None:
                report.failures = []
            report.failures.append(f"{pack.id}: {type(exc).__name__}: {exc}")

    if not dry_run:
        await session.flush()
    return report


async def seed_adrs(
    session: AsyncSession,
    *,
    adrs: Iterable[AdrMeta],
    dry_run: bool,
) -> SeedReport:
    """ADR を Ticket として idempotent seed 投入 (Sprint Pack seed と同 pattern)."""
    report = SeedReport(failures=[])
    existing = await _query_existing_dogfooding_tickets(
        session, slug_prefix="dogfooding-adr-"
    )

    for adr in adrs:
        existing_ticket = existing.get(adr.slug)
        try:
            if existing_ticket is None:
                if not dry_run:
                    new_ticket = Ticket(
                        tenant_id=DEFAULT_TENANT_ID,
                        project_id=DEFAULT_PROJECT_ID,
                        slug=adr.slug,
                        title=adr.title_full,
                        description=adr.description,
                        status=cast(TicketStatus, adr.ticket_status),
                        created_by_actor_id=DEFAULT_ACTOR_ID,
                        metadata_=adr.metadata,
                    )
                    session.add(new_ticket)
                report.rows_added += 1
            else:
                changed = (
                    existing_ticket.status != adr.ticket_status
                    or existing_ticket.title != adr.title_full
                    or existing_ticket.description != adr.description
                    or existing_ticket.metadata_ != adr.metadata
                )
                if changed:
                    if not dry_run:
                        existing_ticket.title = adr.title_full
                        existing_ticket.description = adr.description
                        existing_ticket.status = cast(TicketStatus, adr.ticket_status)
                        existing_ticket.metadata_ = adr.metadata
                    report.rows_updated += 1
                else:
                    report.rows_unchanged += 1
        except Exception as exc:  # noqa: BLE001  # CLI surface
            if report.failures is None:
                report.failures = []
            report.failures.append(f"{adr.id}: {type(exc).__name__}: {exc}")

    if not dry_run:
        await session.flush()
    return report


async def seed_bls(
    session: AsyncSession,
    *,
    bls: Iterable[BlMeta],
    dry_run: bool,
) -> SeedReport:
    """BL (P0 バックログ) を Ticket として idempotent seed 投入."""
    report = SeedReport(failures=[])
    existing = await _query_existing_dogfooding_tickets(
        session, slug_prefix="dogfooding-bl-"
    )

    for bl in bls:
        existing_ticket = existing.get(bl.slug)
        try:
            if existing_ticket is None:
                if not dry_run:
                    new_ticket = Ticket(
                        tenant_id=DEFAULT_TENANT_ID,
                        project_id=DEFAULT_PROJECT_ID,
                        slug=bl.slug,
                        title=bl.title_full,
                        description=bl.description,
                        status=cast(TicketStatus, bl.ticket_status),
                        created_by_actor_id=DEFAULT_ACTOR_ID,
                        metadata_=bl.metadata,
                    )
                    session.add(new_ticket)
                report.rows_added += 1
            else:
                changed = (
                    existing_ticket.status != bl.ticket_status
                    or existing_ticket.title != bl.title_full
                    or existing_ticket.description != bl.description
                    or existing_ticket.metadata_ != bl.metadata
                )
                if changed:
                    if not dry_run:
                        existing_ticket.title = bl.title_full
                        existing_ticket.description = bl.description
                        existing_ticket.status = cast(TicketStatus, bl.ticket_status)
                        existing_ticket.metadata_ = bl.metadata
                    report.rows_updated += 1
                else:
                    report.rows_unchanged += 1
        except Exception as exc:  # noqa: BLE001  # CLI surface
            if report.failures is None:
                report.failures = []
            report.failures.append(f"{bl.id}: {type(exc).__name__}: {exc}")

    if not dry_run:
        await session.flush()
    return report


async def _run(dry_run: bool) -> int:  # noqa: PLR0912, PLR0915  # CLI surface
    # Sprint Pack discover + parse
    sprint_paths = discover_sprint_packs()
    if not sprint_paths:
        print(f"WARNING: no Sprint Pack found in {_SPRINTS_DIR}", file=sys.stderr)  # noqa: T201

    sprint_parsed: list[SprintPackMeta] = []
    sprint_parse_failures: list[str] = []
    for path in sprint_paths:
        meta = parse_sprint_pack(path)
        if meta is None:
            sprint_parse_failures.append(path.name)
        else:
            sprint_parsed.append(meta)

    # ADR discover + parse
    adr_paths = discover_adrs()
    adr_parsed: list[AdrMeta] = []
    adr_parse_failures: list[str] = []
    for path in adr_paths:
        adr = parse_adr(path)
        if adr is None:
            adr_parse_failures.append(path.name)
        else:
            adr_parsed.append(adr)

    # BL discover + parse (from `docs/実装計画/P0_バックログ.md`)
    bls_parsed = discover_bls()

    print(  # noqa: T201
        f"Discovered {len(sprint_paths)} Sprint Pack files ({len(sprint_parsed)} parsed), "
        f"{len(adr_paths)} ADR files ({len(adr_parsed)} parsed), "
        f"{len(bls_parsed)} BL rows parsed from P0 backlog."
    )
    if sprint_parse_failures:
        print(  # noqa: T201
            f"Sprint Pack parse failures: {sprint_parse_failures}", file=sys.stderr
        )
    if adr_parse_failures:
        print(  # noqa: T201
            f"ADR parse failures: {adr_parse_failures}", file=sys.stderr
        )

    settings = get_settings()
    engine = create_engine(settings.database_url)
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    try:
        async with session_factory() as session, session.begin():
            sprint_report = await seed_sprint_packs(
                session,
                sprint_packs=sprint_parsed,
                dry_run=dry_run,
            )
            adr_report = await seed_adrs(
                session,
                adrs=adr_parsed,
                dry_run=dry_run,
            )
            bl_report = await seed_bls(
                session,
                bls=bls_parsed,
                dry_run=dry_run,
            )
    finally:
        await engine.dispose()

    mode = "DRY-RUN" if dry_run else "APPLIED"
    print(f"{mode} Sprint Pack: {sprint_report.to_dict()}")  # noqa: T201
    print(f"{mode} ADR: {adr_report.to_dict()}")  # noqa: T201
    print(f"{mode} BL: {bl_report.to_dict()}")  # noqa: T201
    all_failures = (
        (sprint_report.failures or [])
        + (adr_report.failures or [])
        + (bl_report.failures or [])
    )
    if all_failures:
        print(f"FAILURES: {all_failures}", file=sys.stderr)  # noqa: T201
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="dogfooding_seed",
        description=(
            "Seed docs/sprints/*.md as Tickets for TaskManagedAI dogfooding "
            "(SP-012-10 BL-DOG-001/002/003)."
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="計画 only、DB 変更なし")
    mode.add_argument("--apply", action="store_true", help="DB に投入")
    args = parser.parse_args()

    dry_run = args.dry_run
    exit_code = asyncio.run(_run(dry_run=dry_run))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
