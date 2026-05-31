"""ADR-00038 (L-3 SSE realtime): agent_run NOTIFY trigger 2 系統 (event INSERT + status UPDATE)。

Revision ID: 0041_agent_run_event_notify
Revises: 0040_agent_run_ticket_id
Create Date: 2026-06-01 00:00:00.000000

L-3 リアルタイム進捗 (SSE + LISTEN/NOTIFY) の検知機構。dirty-signal channel
``agent_run_event_appended`` へ 2 系統で NOTIFY する:
  (1) ``agent_run_events`` AFTER INSERT  → payload {tenant_id, run_id, seq_no}
  (2) ``agent_runs`` AFTER UPDATE        → payload {tenant_id, run_id}
      (status / blocked_reason / completed_at が変化した場合のみ)

(2) は ``api_bridge.py`` の ``run.status`` 直接代入のような status-only 更新経路
(AgentRunEvent を append しない) でも dirty-signal を保証する (ADR-00038 R9)。
payload は最小 (8KB NOTIFY 上限に余裕)、event row は本体を query で取得する。
重複 NOTIFY は SSE handler の bounded queue + drain-to-empty が吸収する。

additive (列・event schema を変更しない、read-only side-effect のみ)。downgrade は
2 trigger + 2 function を drop するだけの lossless (event 行・status 行は不変)。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0041_agent_run_event_notify"
down_revision: str | None = "0040_agent_run_ticket_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHANNEL = "agent_run_event_appended"


def upgrade() -> None:
    # (1) agent_run_events AFTER INSERT → NOTIFY {tenant_id, run_id, seq_no}
    op.execute(
        sa.text(
            f"""
            CREATE OR REPLACE FUNCTION agent_run_event_notify() RETURNS trigger AS $$
            BEGIN
                PERFORM pg_notify(
                    '{_CHANNEL}',
                    json_build_object(
                        'tenant_id', NEW.tenant_id,
                        'run_id', NEW.run_id,
                        'seq_no', NEW.seq_no
                    )::text
                );
                RETURN NULL;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER agent_run_event_notify_trg
                AFTER INSERT ON agent_run_events
                FOR EACH ROW
                EXECUTE FUNCTION agent_run_event_notify();
            """
        )
    )

    # (2) agent_runs AFTER UPDATE (status/blocked_reason/completed_at DISTINCT) → NOTIFY {tenant_id, run_id}
    op.execute(
        sa.text(
            f"""
            CREATE OR REPLACE FUNCTION agent_run_status_notify() RETURNS trigger AS $$
            BEGIN
                PERFORM pg_notify(
                    '{_CHANNEL}',
                    json_build_object(
                        'tenant_id', NEW.tenant_id,
                        'run_id', NEW.id
                    )::text
                );
                RETURN NULL;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER agent_run_status_notify_trg
                AFTER UPDATE ON agent_runs
                FOR EACH ROW
                WHEN (
                    OLD.status IS DISTINCT FROM NEW.status
                    OR OLD.blocked_reason IS DISTINCT FROM NEW.blocked_reason
                    OR OLD.completed_at IS DISTINCT FROM NEW.completed_at
                )
                EXECUTE FUNCTION agent_run_status_notify();
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS agent_run_status_notify_trg ON agent_runs;"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS agent_run_status_notify();"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS agent_run_event_notify_trg ON agent_run_events;"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS agent_run_event_notify();"))
