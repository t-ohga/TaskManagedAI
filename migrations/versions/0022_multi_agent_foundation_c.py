"""Multi-agent orchestration foundation phase C: check_project_role_link trigger.

SP-013 batch 0d (ADR-00014 §3 + PE-F-012 mitigation).

`check_project_role_link()` PL/pgSQL 関数 + agent_runs trigger:
- role_scope='project' のとき project_agent_roles に row が存在しなければ raise exception
- role_scope='global' のとき standard_role_ids_mirror に role_id が含まれることを確認

PE-F-012 mitigation: application layer validation を DB layer で補強、cross-project
role reference / non-existent role reference を DB レベルで reject。

scope:
- check_project_role_link() PL/pgSQL function 新規
- agent_runs BEFORE INSERT/UPDATE trigger 設置 (tenant_id, project_id, role_id, role_scope の更新でも発火)

scope 外 (次 batch):
- sanitizer_policy_versions table (batch 0e)
- 5 検証項目 backup drill (batch 0e)

Revision ID: 0022_multi_agent_foundation_c
Revises: 0021_multi_agent_foundation_b
Create Date: 2026-05-22 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0022_multi_agent_foundation_c"
down_revision: str | None = "0021_multi_agent_foundation_b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # check_project_role_link() PL/pgSQL function
    # ADR-00014 §3 + PE-F-012 mitigation
    op.execute(
        """
        create or replace function check_project_role_link()
            returns trigger
            language plpgsql
        as $$
        begin
            -- role が NULL の場合は check skip (role_consistency CHECK で別途 enforce 済)
            if NEW.role_id is null or NEW.role_scope is null then
                return NEW;
            end if;

            if NEW.role_scope = 'project' then
                -- project scope: project_agent_roles に該当 row が存在しなければ reject
                -- (cross-project role reference 防御、deprecated_at が立っていれば dispatch 不可)
                if not exists (
                    select 1 from project_agent_roles
                     where tenant_id = NEW.tenant_id
                       and project_id = NEW.project_id
                       and role_id = NEW.role_id
                       and deprecated_at is null
                ) then
                    raise exception
                        'check_project_role_link: project role missing (role_id=%, tenant=%, project=%)',
                        NEW.role_id, NEW.tenant_id, NEW.project_id;
                end if;
            elsif NEW.role_scope = 'global' then
                -- global scope: standard_role_ids_mirror に role_id が含まれることを確認
                -- (PE-F-001 reserved namespace + global は STANDARD_ROLE_IDS only invariant)
                if not exists (
                    select 1 from standard_role_ids_mirror
                     where role_id = NEW.role_id
                ) then
                    raise exception
                        'check_project_role_link: role_id=% role_scope=global not in standard_role_ids_mirror',
                        NEW.role_id;
                end if;
            end if;

            return NEW;
        end;
        $$;
        """
    )

    # agent_runs BEFORE INSERT/UPDATE trigger (PE-F-012 mitigation)
    # tenant_id, project_id, role_id, role_scope の更新でも発火
    op.execute(
        """
        create trigger agent_runs_check_project_role
            before insert or update of tenant_id, project_id, role_id, role_scope on agent_runs
            for each row execute function check_project_role_link();
        """
    )


def downgrade() -> None:
    op.execute("drop trigger if exists agent_runs_check_project_role on agent_runs")
    op.execute("drop function if exists check_project_role_link()")
