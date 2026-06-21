"""ADR-00058: secret_ref URI backend を secret://(sops|local)/... へ additive 拡張。

Revision ID: 0049_secret_uri_local_backend
Revises: 0048_agent_run_run_mode
Create Date: 2026-06-20 00:00:00.000000

正本 grammar ``secret://<backend>/<scope>/<name>#v<n>`` の backend segment に ``local`` を additive
追加する (scheme ``secret://`` 不変、scope/name/version 構造不変)。format CHECK と components_match
CHECK を両 backend (sops|local) 許容へ拡張する。

**migration 不変性 (ADR-00058 境界批評 R4)**: 本 migration は runtime 定数 ``SECRET_URI_PATTERN``
を **import しない**。revision 固定の SQL literal (``SECRET_URI_FORMAT_LITERAL``) を hardcode する。
runtime 定数の後日変更が過去 revision の fresh-DB 適用結果を書き換える事故を防ぐ。drift guard test
(tests/secrets/test_secret_uri_pattern_drift.py) が「本 module の ``SECRET_URI_FORMAT_LITERAL`` ==
current ``SECRET_URI_PATTERN``」を CI 強制する (定数を変えたら新 migration を追加する規律)。

downgrade は ``secret://local/%`` row 不在を preflight し、不在時のみ旧 sops-only CHECK へ lossless
revert する (constraint-tightening は legal row preflight 必須)。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0049_secret_uri_local_backend"
down_revision: str | None = "0048_agent_run_run_mode"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "secret_refs"
_FORMAT_CONSTRAINT = "secret_refs_ck_secret_uri_format"
_COMPONENTS_CONSTRAINT = "secret_refs_ck_secret_uri_components_match"

# revision 固定 SQL literal (drift guard 契約)。current SECRET_URI_PATTERN と exact 一致すること。
# SECRET_URI_PATTERN を変えたら本 literal を変えるのではなく **新 migration を追加** する。
SECRET_URI_FORMAT_LITERAL = (
    "^secret://(sops|local)/(p0|workspace|project|repo|agent_run|provider)/[a-z0-9_-]+#v[0-9]+$"
)
# downgrade 先の sops-only literal (0049 以前の固定値)。
_SECRET_URI_FORMAT_LITERAL_SOPS_ONLY = (
    "^secret://sops/(p0|workspace|project|repo|agent_run|provider)/[a-z0-9_-]+#v[0-9]+$"
)

_COMPONENTS_BOTH = (
    "secret_uri = 'secret://sops/' || scope || '/' || name || '#' || version "
    "OR secret_uri = 'secret://local/' || scope || '/' || name || '#' || version"
)
_COMPONENTS_SOPS_ONLY = "secret_uri = 'secret://sops/' || scope || '/' || name || '#' || version"


def upgrade() -> None:
    op.drop_constraint(_FORMAT_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(
        _FORMAT_CONSTRAINT,
        _TABLE,
        f"secret_uri ~ '{SECRET_URI_FORMAT_LITERAL}'",
    )
    op.drop_constraint(_COMPONENTS_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(_COMPONENTS_CONSTRAINT, _TABLE, _COMPONENTS_BOTH)


def downgrade() -> None:
    bind = op.get_bind()
    local_count = bind.execute(
        sa.text(
            "select count(*) from secret_refs where secret_uri like 'secret://local/%'"
        )
    ).scalar_one()
    if local_count:
        raise RuntimeError(
            f"0049 downgrade blocked: {local_count} secret://local/% row(s) exist. "
            "Migrate them to a sops backend or revoke+purge before downgrading "
            "(lossless revert requires no local-backend rows)."
        )
    op.drop_constraint(_FORMAT_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(
        _FORMAT_CONSTRAINT,
        _TABLE,
        f"secret_uri ~ '{_SECRET_URI_FORMAT_LITERAL_SOPS_ONLY}'",
    )
    op.drop_constraint(_COMPONENTS_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(_COMPONENTS_CONSTRAINT, _TABLE, _COMPONENTS_SOPS_ONLY)
