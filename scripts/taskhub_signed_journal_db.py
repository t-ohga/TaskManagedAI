"""SP022-T08 batch 5: signed journal verification CLI **DB mode** (real I/O).

`taskhub verify --signed-journal --from-db --tenant-id <int>` で audit_events
table 全件を fetch + recompute signed journal chain + final_hash verify する。

offline JSONL mode (taskhub_signed_journal_offline.py) と並ぶ 2 mode の片方で、
mutually exclusive (`--input` と `--from-db` は同時指定不可)。

# Implementation contract

- async DB session (AsyncSession) で audit_events 全件 fetch
  - tenant_id 必須 (multi-tenant invariant)
  - `created_at ASC, id ASC` 安定順序 (build_signed_journal_chain 前提)
- pure function `build_signed_journal_chain()` で hash chain reconstruct
- output JSON: offline mode と同 schema (final_hash / entry_count / tamper_detected /
  expected_final_hash_match)
- expected_final_hash 指定時は equality check (mismatch = tamper_detected=True)
- raw secret は audit payload に含まれない invariant (assert_no_raw_secret upstream)
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any

from backend.app.services.audit.signed_journal import (
    SIGNED_JOURNAL_INITIAL_HASH,
    build_signed_journal_chain,
)

__all__ = [
    "DEFAULT_MAX_ENTRIES",
    "EXPECTED_FINAL_HASH_REGEX",
    "SignedJournalDbUsageError",
    "verify_db_signed_journal",
    "verify_db_signed_journal_async",
]

DEFAULT_MAX_ENTRIES: int = 100000

# Codex PR #90 R1 F-004 fix (P2): `$` は Python regex で trailing newline を許可するため、
# `\Z` (end-of-string anchor、改行も含めて文字列終端) を使う。
EXPECTED_FINAL_HASH_REGEX = re.compile(r"\A[0-9a-f]{64}\Z")

# Codex PR #90 R1 F-003 fix (P2): DB mode は offline mode と同 100k 上限を enforce
# (`limit max_entries + 1` で memory / latency 抑止)。
MAX_ALLOWED_MAX_ENTRIES: int = DEFAULT_MAX_ENTRIES


class SignedJournalDbUsageError(Exception):
    """`--signed-journal --from-db` CLI invocation usage error.

    Raised when caller provides invalid args / DB connection fail / tenant not found.
    stderr_message() emits structured error_code + summary for operator triage.
    """

    def __init__(self, error_code: str, summary: str) -> None:
        super().__init__(f"{error_code}: {summary}")
        self.error_code = error_code
        self.summary = summary

    def stderr_message(self) -> str:
        return f"ERROR [{self.error_code}]: {self.summary}"


async def verify_db_signed_journal_async(
    session: Any,  # noqa: ANN401 - AsyncSession (sqlalchemy.ext.asyncio.AsyncSession)
    *,
    tenant_id: int,
    expected_final_hash: str | None = None,
    max_entries: int = DEFAULT_MAX_ENTRIES,
) -> dict[str, Any]:
    """Async core: fetch audit_events from DB + build signed journal chain + verify.

    Args:
        session: AsyncSession (`backend.app.db.session.AsyncSessionFactory()`)
        tenant_id: multi-tenant scope (audit_events.tenant_id WHERE)
        expected_final_hash: 期待 final_hash (64 chars hex)、None なら check skip
        max_entries: fetch 上限 (default 100k、defense-in-depth)

    Returns:
        dict (offline mode と同 schema):
            mode: "db"
            tenant_id: int
            entry_count: int
            final_hash: str (64 chars hex)
            initial_hash: str (genesis sentinel)
            expected_final_hash_match: bool | None
            tamper_detected: bool

    Raises:
        SignedJournalDbUsageError: tenant_id <= 0 / max_entries 不正 / DB query fail
    """
    from sqlalchemy import select

    from backend.app.db.models.audit_event import AuditEvent

    # Codex PR #90 R1 F-001 fix (P2): bool は int 部分型のため `isinstance(True, int)` が True
    # を返す。`type(...) is int` で strict type check (`int(True)` accidental call を防ぐ)。
    if type(tenant_id) is not int or tenant_id <= 0:
        raise SignedJournalDbUsageError(
            "invalid_tenant_id",
            f"tenant_id must be positive integer (not bool), got {tenant_id!r}",
        )
    # Codex PR #90 R1 F-002 (P3) + F-003 (P2) fix: bool reject + upper bound enforce
    if type(max_entries) is not int or max_entries < 1:
        raise SignedJournalDbUsageError(
            "invalid_max_entries",
            f"max_entries must be positive integer (not bool), got {max_entries!r}",
        )
    if max_entries > MAX_ALLOWED_MAX_ENTRIES:
        raise SignedJournalDbUsageError(
            "max_entries_out_of_range",
            f"max_entries must be <= {MAX_ALLOWED_MAX_ENTRIES} (DoS defense), "
            f"got {max_entries}",
        )
    if expected_final_hash is not None and not EXPECTED_FINAL_HASH_REGEX.match(
        expected_final_hash
    ):
        raise SignedJournalDbUsageError(
            "invalid_expected_final_hash",
            f"expected_final_hash must be 64 chars hex (no trailing newline), "
            f"got {expected_final_hash!r}",
        )

    # tenant-scoped fetch with stable ordering
    # (build_signed_journal_chain は ordered iterable を前提)
    stmt = (
        select(AuditEvent)
        .where(AuditEvent.tenant_id == tenant_id)
        .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
        .limit(max_entries + 1)  # +1 で max_entries 超過検知
    )
    result = await session.execute(stmt)
    audit_events = list(result.scalars())

    if len(audit_events) > max_entries:
        raise SignedJournalDbUsageError(
            "max_entries_exceeded",
            f"audit_events count exceeds max_entries={max_entries}; "
            f"adjust --max-entries or paginate (got >{max_entries})",
        )

    # build chain (pure function、no I/O)
    chain = build_signed_journal_chain(audit_events)

    expected_match: bool | None = None
    tamper_detected = False
    if expected_final_hash is not None:
        expected_match = chain.final_hash == expected_final_hash
        if not expected_match:
            tamper_detected = True

    return {
        "mode": "db",
        "tenant_id": tenant_id,
        "entry_count": len(audit_events),
        "final_hash": chain.final_hash,
        "initial_hash": SIGNED_JOURNAL_INITIAL_HASH,
        "expected_final_hash_match": expected_match,
        "tamper_detected": tamper_detected,
    }


def verify_db_signed_journal(
    *,
    tenant_id: int,
    database_url: str | None = None,
    expected_final_hash: str | None = None,
    max_entries: int = DEFAULT_MAX_ENTRIES,
) -> dict[str, Any]:
    """Sync wrapper around verify_db_signed_journal_async (CLI 用、asyncio.run() bridge).

    Args:
        tenant_id: multi-tenant scope
        database_url: SQLAlchemy URL (None なら backend.app.config.get_settings().database_url)
        expected_final_hash / max_entries: verify_db_signed_journal_async に渡す

    Returns:
        verify_db_signed_journal_async の結果 dict

    Raises:
        SignedJournalDbUsageError: usage / DB connection error
    """
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    if database_url is None:
        # 遅延 import (循環依存防止)
        from backend.app.config import get_settings

        database_url = get_settings().database_url

    async def _run() -> dict[str, Any]:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        try:
            factory = async_sessionmaker(bind=engine, expire_on_commit=False)
            async with factory() as session:
                return await verify_db_signed_journal_async(
                    session,
                    tenant_id=tenant_id,
                    expected_final_hash=expected_final_hash,
                    max_entries=max_entries,
                )
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_run())
    except SignedJournalDbUsageError:
        raise
    except Exception as exc:
        raise SignedJournalDbUsageError(
            "db_connection_error",
            f"failed to fetch audit_events from DB: {exc}",
        ) from exc


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint (`taskhub verify --signed-journal --from-db` 経由).

    Args:
        argv: ["--tenant-id", "<int>", ["--expected-final-hash", "<hex>"],
              ["--max-entries", "<int>"], ["--database-url", "<url>"]]

    Returns:
        0: success (no tamper detected)
        1: tamper detected (expected_final_hash mismatch)
        2: usage error / DB error
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="taskhub verify --signed-journal --from-db",
        description="Verify signed journal chain from DB (SP-022 T08 batch 5)",
    )
    parser.add_argument("--tenant-id", type=int, required=True)
    parser.add_argument("--expected-final-hash", type=str, default=None)
    parser.add_argument(
        "--max-entries", type=int, default=DEFAULT_MAX_ENTRIES,
        help=f"fetch limit (default {DEFAULT_MAX_ENTRIES})",
    )
    parser.add_argument(
        "--database-url", type=str, default=None,
        help="SQLAlchemy URL (None=Settings.database_url)",
    )
    args = parser.parse_args(argv)

    try:
        result = verify_db_signed_journal(
            tenant_id=args.tenant_id,
            database_url=args.database_url,
            expected_final_hash=args.expected_final_hash,
            max_entries=args.max_entries,
        )
    except SignedJournalDbUsageError as exc:
        print(exc.stderr_message(), file=sys.stderr)  # noqa: T201
        return 2

    print(json.dumps(result, sort_keys=True))  # noqa: T201
    return 1 if result.get("tamper_detected") else 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
