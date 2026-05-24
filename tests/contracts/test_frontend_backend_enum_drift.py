from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

from backend.app.domain.agent_runtime.event_type import ALL_AGENT_RUN_EVENT_TYPES
from backend.app.domain.agent_runtime.status import (
    ALL_AGENT_RUN_STATUSES,
    ALL_BLOCKED_REASONS,
)
from backend.app.schemas.ticket import TicketPriority, TicketStatus

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FRONTEND_API = _REPO_ROOT / "frontend" / "lib" / "api"


def _frontend_zod_enum_options(relative_path: str, enum_name: str) -> tuple[str, ...]:
    source = (_FRONTEND_API / relative_path).read_text(encoding="utf-8")
    match = re.search(
        rf"export const {re.escape(enum_name)} = z\.enum\(\[(?P<body>.*?)\]\);",
        source,
        flags=re.DOTALL,
    )
    assert match is not None, f"{enum_name} not found in frontend/lib/api/{relative_path}"
    return tuple(re.findall(r'"([^"]+)"', match.group("body")))


def test_ticket_status_and_priority_frontend_match_backend_literals() -> None:
    assert _frontend_zod_enum_options("tickets.ts", "TicketStatusEnum") == get_args(
        TicketStatus
    )
    assert _frontend_zod_enum_options("tickets.ts", "TicketPriorityEnum") == get_args(
        TicketPriority
    )


def test_agent_run_status_and_blocked_reason_frontend_match_backend_literals() -> None:
    assert (
        _frontend_zod_enum_options("agent-runs.ts", "AgentRunStatusEnum")
        == ALL_AGENT_RUN_STATUSES
    )
    assert (
        _frontend_zod_enum_options("agent-runs.ts", "BlockedReasonEnum")
        == ALL_BLOCKED_REASONS
    )


def test_agent_run_event_type_frontend_matches_backend_literal_order() -> None:
    assert (
        _frontend_zod_enum_options("agent-runs.ts", "AgentRunEventTypeEnum")
        == ALL_AGENT_RUN_EVENT_TYPES
    )


def test_audit_event_schema_stays_open_until_backend_registry_exists() -> None:
    """AuditEvent.event_type is still open text, so frontend must not exact-gate it.

    SP-009 reconciliation keeps AuditEventTypeEnum as filter suggestions only.
    Adding a backend registry can replace this with an exact-set comparison.
    """

    audit_source = (_FRONTEND_API / "audit.ts").read_text(encoding="utf-8")
    assert "event_type: z.string()" in audit_source
