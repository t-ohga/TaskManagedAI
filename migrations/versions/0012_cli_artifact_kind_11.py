"""Extend artifacts.kind CHECK from 6 to 11 (add 5 cli_* artifact kinds).

Revision ID: 0012_cli_artifact_kind_11
Revises: 0011_trust_level_event_25
Create Date: 2026-05-12 00:00:00.000000

Sprint 6 BL-0064 (ADR-00003): CLI artifact orchestration の 5 種 artifact_kind
を artifacts.kind CHECK 制約に追加する additive migration。

Added kinds:
- cli_input: CLI agent への input (Markdown / JSON)
- cli_stdout: redacted stdout capture
- cli_stderr: redacted stderr capture
- cli_exit: exit code + signal + duration + timeout / cancelled metadata
- cli_result_summary: 採否判定の前段、redacted summary

Existing 6 kinds (plan / patch / evidence / citation /
provider_continuation_ref / other) は **不変** (additive only、ADR Gate
Criteria #8 非該当)。
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0012_cli_artifact_kind_11"
down_revision: str | None = "0011_trust_level_event_25"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# NOTE: SQL CHECK conditions are kept as inline string literals so that test
# helpers can parse them via AST. Adding a new artifact_kind requires updating
# BOTH the literal here AND ``backend/app/db/models/artifact.py:ArtifactKind``
# / ``ALL_ARTIFACT_KINDS`` (5+ source integrity,
# `.claude/rules/cross-source-enum-integrity.md` §1).

_ARTIFACT_KIND_11_CHECK_SQL = (
    "kind in ("
    "'plan','patch','evidence','citation','provider_continuation_ref','other',"
    "'cli_input','cli_stdout','cli_stderr','cli_exit','cli_result_summary'"
    ")"
)

_ARTIFACT_KIND_6_CHECK_SQL = (
    "kind in ('plan','patch','evidence','citation','provider_continuation_ref','other')"
)


def upgrade() -> None:
    op.drop_constraint(
        "artifacts_ck_kind",
        "artifacts",
        type_="check",
    )
    op.create_check_constraint(
        "artifacts_ck_kind",
        "artifacts",
        _ARTIFACT_KIND_11_CHECK_SQL,
    )


def downgrade() -> None:
    # ``cli_*`` kind を持つ既存 row は CHECK violation で downgrade 失敗する。
    # rollback caller は ADR-00003 rollback §「CLI artifact schema migration
    # rollback」に従い quarantine table への move または delete を先行させる。
    op.drop_constraint(
        "artifacts_ck_kind",
        "artifacts",
        type_="check",
    )
    op.create_check_constraint(
        "artifacts_ck_kind",
        "artifacts",
        _ARTIFACT_KIND_6_CHECK_SQL,
    )
