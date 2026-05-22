# task-01 batch 0c 完了報告 (2026-05-22)

## summary

- task: SP-014 batch 0c policy_profile + policy_decisions trace + ADR-00009 update (SP014-T03/T04)
- start: 2026-05-22 23:55 JST
- end: 2026-05-23 00:35 JST (~0.7h)
- 完了 BL / ticket: SP014-T03/T04 batch 0c slice
- 累計 PR: pending at report creation

## PR list

| PR | merge SHA | scope | Codex finding |
|---|---|---|---|
| pending | pending | policy_profiles + policy_profile_action_effects + policy_decisions trace + ADR/DD docs | Self-Plan HIGH x4 + MEDIUM x4 adopted; Self-Impl HIGH x2 + MEDIUM x3 adopted |

## Codex finding 採否判定

| PR | finding | severity | judgment | follow-up PR |
|---|---|---|---|---|
| pending | Existing-tenant-only seed leaves new tenant project default FK broken. | HIGH | adopt: tenant insert trigger + fixture verification | included |
| pending | Caller-supplied policy_profile can select low_risk_auto_allow. | HIGH | adopt: schema/repository reject caller path | included |
| pending | Unknown profile / missing action seed could fail open. | HIGH | adopt: resolver fail-closed deny reason codes | included |
| pending | Tier 2 requires review_artifact trace without approval_requests row. | HIGH | adopt: policy_decisions.required_review_artifact_id FK | included |
| pending | Mutating negative test poisons exact seed verification. | MEDIUM | adopt: restore canonical seed in finally | included |
| pending | ADR/DD docs drift from implemented enum/profile schema. | MEDIUM | adopt: docs updated | included |
| pending | Local DB had old unmerged 0027 applied. | MEDIUM | adopt: recreate temp DB before verification | included |

## defer / carry-over

- SP014-B0C-DEFER-001: `uv run alembic check` remains blocked by existing migration env / ORM drift debt (`migrations/env.py` has no `target_metadata`). 移送先: task-08 docs drift fix or a dedicated migration-drift carry-over Sprint Pack.
- SP014-B0C-DEFER-002: Broad direct-project-insert adversarial sweep found stale fixtures unrelated to batch 0c:
  - `tests/runtime/test_artifact_immutable.py` omits current `artifacts.project_id not null`.
  - `tests/security/test_artifact_cross_project_negative.py` references removed `agent_runs.intent`.
  移送先: task-07 backend test coverage expansion or task-08 docs drift fix.
- SP014-B0C-DEFER-003: task-01 batch 0d-0f remain open.

## blocker

- No CRITICAL / HIGH blocker remains for batch 0c PR.
- `alembic check` is not clean for repo infrastructure reasons; `downgrade -1 -> upgrade head` passed on local temporary test DB.

## verification (DoD checklist 結果)

- [x] ruff check + mypy backend clean
- [x] pytest `tests/policy/test_policy_profile_seed.py` PASS (`8 passed`)
- [x] pytest `tests/policy/` PASS (`73 passed, 1 xfailed`)
- [x] pytest `tests/db/test_repository_layer.py tests/db/test_schema_introspection.py tests/test_seeds.py` PASS (`37 passed`)
- [x] pytest `tests/multi_agent/` PASS (`47 passed`)
- [x] pytest `tests/runtime/test_agent_run_events.py tests/runtime/test_agentrun_transitions.py` PASS (`51 passed`)
- [x] migration Mac local downgrade -1 + upgrade head 確認
- [x] ADR-00009 / SP-014 / DD-02 docs sync
- [ ] codex_pr_full_review.sh baseline 確認 + finding 採否判定 (PR 起票後)
- [ ] Sprint Pack frontmatter `status: ready -> completed` + Review 章完成 (task-01 全 batch 完了時)

## Claude verification 依頼項目

1. `tenants_seed_policy_profiles` trigger が new tenant default project FK の production invariant として妥当か verify。
2. `ProjectCreate` + `ProjectRepository` の caller-supplied `policy_profile` reject が server-owned-boundary として十分か verify。
3. `policy_decisions.required_review_artifact_id` FK が batch 0b review_artifacts 4 重防御と整合するか verify。
4. `resolve_policy_profile_action_effect()` の unknown/missing seed fail-closed reason_code が AC-HARD-01 fixture 拡張に使える粒度か verify。
5. `alembic check` debt と stale fixture drift を task-07/task-08 carry-over に送る判断が妥当か verify。
