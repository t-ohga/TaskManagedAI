"""Multi-agent orchestration foundation phase E: check_project_role_link trigger fix.

SP-013 batch 0f / Codex PR #138 P1 fix: project + standard role (e.g., 'implementer')
が trigger で reject される regression を fix。

修正方針 (ADR-00014 §1 invariant + validate_role_scope_consistency と整合):
- role_scope='project' + standard role (`standard_role_ids_mirror` 内) → accept (project-scoped standard role 適用)
- role_scope='project' + non-standard role → project_agent_roles に row 必須 (custom role)
- role_scope='global' は不変 (standard_role_ids_mirror only)

旧 trigger は project branch で project_agent_roles のみ check → standard role を reject の bug。

Revision ID: 0024_multi_agent_foundation_e
Revises: 0023_multi_agent_foundation_d
Create Date: 2026-05-22 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0024_multi_agent_foundation_e"
down_revision: str | None = "0023_multi_agent_foundation_d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # check_project_role_link() を replace (project branch で standard role accept 追加)
    # Codex PR #138 R1 P1 fix
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
                -- Codex PR #138 P1 fix: project + standard role は accept (project-scoped 標準役職)
                -- project + non-standard role のみ project_agent_roles に row 必須 (custom role)
                if exists (
                    select 1 from standard_role_ids_mirror
                     where role_id = NEW.role_id
                ) then
                    return NEW;
                end if;

                -- non-standard role: project_agent_roles に row 必須
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


def downgrade() -> None:
    # 旧 trigger function (PR #138) に restore
    op.execute(
        """
        create or replace function check_project_role_link()
            returns trigger
            language plpgsql
        as $$
        begin
            if NEW.role_id is null or NEW.role_scope is null then
                return NEW;
            end if;

            if NEW.role_scope = 'project' then
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
