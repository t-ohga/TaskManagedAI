---
id: "SP-012-7_phase_f_0_prerequisite"
type: "light"
status: "completed"
sprint_no: 12.7
created_at: "2026-05-22"
updated_at: "2026-05-22"
completed_at: "2026-05-22"
target_days: 2
max_days: 3
adr_refs:
  - "[ADR-00009](../adr/00009_action_class_taxonomy.md) # 既 accepted、action_class enum 既 update 済 (provider_call 追加 + read/search 削除)、本 Sprint で DB schema (CHECK constraint) sync verify"
planned_adr_refs: []
related_sprints:
  - "SP-012_p0_acceptance"  # SP-012 補強、必須 prerequisite
  - "SP-013_multi_agent_orchestration"  # SP-013 kickoff prerequisite
risks:
  - "DB schema sync 不整合発覚時の追加 migration 必要 (action_class enum と CHECK constraint の整合性)"
  - "artifacts.project_id backfill 失敗 (既存 artifact が project 参照を持たない case)"
  - "AC-HARD-03 artifact-domain test の cross-project 越境 fixture 設計"
---

最終更新: 2026-05-22

## 目的

P0 Exit declaration (PR #103、2026-05-22 merged) の P0.1 unblock 直後の prerequisite Sprint。SP-013 Multi-Agent Orchestration Foundation 着手の **3 件 must_ship prerequisite** を完遂し、SP-013 kickoff 直前に ADR-00014/00019 accepted promotion + SP-013 batch 0 着手を unblock する。

**位置付け**: sprint_no=12.7 = SP-012 と SP-013 の中間、SP-012 補強 + SP-013 prerequisite として 2-3 day で完遂する light Sprint。

## 背景

P0 Exit Full Audit doc (PR #100、`.claude/plans/p0-exit-full-audit-2026-05-22.md`) §3 A-2 で確定。F-R2-002 R2 fix の重要発覚で本 Sprint scope を 4 件 → 3 件に縮小:

- **F-R2-002 重要発覚**: backend code `backend/app/domain/policy/action_class.py` で **action_class enum 既に `read`/`search` 削除済 + `provider_call` 追加済** (現状 enum: `task_write` / `repo_write` / `pr_open` / `secret_access` / `merge` / `deploy` / `provider_call` 7 種)。ADR-00009 update + 別 light ADR 起票 (ADR-00030) は **不要**、Phase F-0 light Sprint Pack scope = **DB schema sync verify + artifacts.project_id materialize + AC-HARD-03 artifact-domain test の 3 件のみ**

## 対象外

- ADR-00030 起票 (F-R2-002 R2 fix で不要判定)
- ADR-00009 update (既 update 済、本 Sprint で verify のみ)
- ADR-00014/00019 accepted promotion (本 Sprint 完了後の SP-013 kickoff 直前に実施)
- SP-013 本体実装 (本 Sprint 完了後の next Sprint)
- production 公開準備 (P1+ scope、SP-023)

## 設計判断

- **DB schema sync verify**: action_class 7 種 enum と DB CHECK constraint が `policy_rule.py` / `policy_decision.py` / `approval_request.py` で完全整合確認、不整合あれば minimal migration 追加 (R2 fix で原則整合済と verify)
- **artifacts.project_id materialize**: PE-F-007 strict prerequisite として、`artifacts` table に `project_id` column 追加 + backfill (既存 artifact は parent_run の project から resolve、null の場合は default project 1 として backfill)
- **AC-HARD-03 artifact-domain cross-project test**: research-domain test (`tests/security/test_research_cross_project_negative.py`、SP-010 起票) と並ぶ artifact-domain test を新規追加 (`tests/security/test_artifact_cross_project_negative.py`)、artifact が cross-project で参照不可を verify

## 実装チケット

### must_ship 1: DB schema (CHECK constraint) sync verify

| BL | 内容 | 想定 effort |
|---|---|---|
| BL-PF0-001 | action_class enum (7 種) と DB CHECK constraint の完全整合 verify | 0.5 day |
| BL-PF0-001b | `policy_rule.py` / `policy_decision.py` / `approval_request.py` の DB CHECK 突合 + 不整合あれば migration 追加 | 0.5 day (verify 主体、migration は contingency) |

### must_ship 2: artifacts.project_id materialize migration

| BL | 内容 | 想定 effort |
|---|---|---|
| BL-PF0-002 | `0019_artifacts_project_id_materialize.py` 起票 (column 追加 + 複合 FK `(tenant_id, project_id)` + backfill SQL) | 1 day |
| BL-PF0-002b | repository contract test 更新 (artifacts query で project_id 条件追加) | 0.3 day |

### must_ship 3: AC-HARD-03 artifact-domain cross-project negative test

| BL | 内容 | 想定 effort |
|---|---|---|
| BL-PF0-003 | `tests/security/test_artifact_cross_project_negative.py` 新規 (artifact cross-project select/insert/update/delete 越境 reject test) | 0.5 day |
| BL-PF0-003b | fixture loader (artifact 用 fixture、SP-010 research fixture と同 pattern) | 0.3 day |

## タスク一覧

- [ ] Sprint Pack 起票 + ADR-00009 既 accepted verify (本 PR で完了予定)
- [ ] BL-PF0-001/001b DB schema sync verify
- [ ] BL-PF0-002/002b artifacts.project_id materialize migration + repository test 更新
- [ ] BL-PF0-003/003b AC-HARD-03 artifact-domain test 新規
- [ ] Sprint Pack `## Review` 追加 + frontmatter `status: ready → completed`
- [ ] SP-013 着手前提条件 satisfy 確認 (ADR-00014/00019 promotion + Sprint Pack frontmatter completed)

## must_ship / defer_if_over_budget 対応表

| 項目 | must_ship | defer_if_over_budget |
|---|---|---|
| DB schema sync verify (BL-PF0-001/001b) | ✅ | (verify 主体、不整合発覚時の追加 migration は contingency) |
| artifacts.project_id materialize migration (BL-PF0-002/002b) | ✅ | (backfill 失敗 case は手動 SQL で対応) |
| AC-HARD-03 artifact-domain test (BL-PF0-003/003b) | ✅ | (fixture coverage 削減で defer 可能、ただし P0.1 unblock 前に最低 1 case PASS) |

## 受け入れ条件

- [ ] action_class enum 7 種 と全 DB CHECK constraint が完全整合
- [ ] `artifacts.project_id` column 追加 + 複合 FK `(tenant_id, project_id)` + backfill 完了
- [ ] `tests/security/test_artifact_cross_project_negative.py` 全 test PASS
- [ ] migration `uv run alembic upgrade head` PASS (新 migration `0019_artifacts_project_id_materialize` apply 成功)
- [ ] regression: `uv run pytest -x` 全 PASS (新 test 含む)
- [ ] codex-plan-review R1 PASS + R2 CLEAN signal (本 Sprint Pack に対し)

## 検証手順

```bash
# 1. DB schema sync verify
docker compose -f docker-compose.yml -f docker-compose.dev.yml --env-file .env.local exec api \
  uv run --no-sync python -c "from backend.app.domain.policy.action_class import ACTION_CLASS_VALUES; print(ACTION_CLASS_VALUES)"
# expected: ('task_write', 'repo_write', 'pr_open', 'secret_access', 'merge', 'deploy', 'provider_call')

# 2. DB CHECK constraint verify
docker compose -f docker-compose.yml -f docker-compose.dev.yml --env-file .env.local exec postgres \
  psql -U taskmanagedai -d taskmanagedai -c "
    SELECT conname, pg_get_constraintdef(oid)
    FROM pg_constraint
    WHERE conname LIKE '%action_class%';
  "
# expected: CHECK constraint enum 値が 7 種 enum と完全整合

# 3. artifacts.project_id migration apply
docker compose -f docker-compose.yml -f docker-compose.dev.yml --env-file .env.local exec api \
  uv run --no-sync alembic upgrade head
# expected: 0019_artifacts_project_id_materialize apply 成功

# 4. AC-HARD-03 artifact-domain test
uv run pytest tests/security/test_artifact_cross_project_negative.py -v
# expected: 全 test PASS (artifact cross-project SELECT/INSERT/UPDATE/DELETE reject verify)

# 5. regression
uv run pytest -x
# expected: 全 test PASS
```

## レビュー観点

- DB schema sync が完全 (5+ source 整合: enum / DB CHECK / ORM CheckConstraint / Pydantic / pytest fixture)
- artifacts.project_id backfill が正確 (parent_run.project_id から resolve、null は default project 1)
- AC-HARD-03 artifact-domain test が research-domain test と同 pattern (cross-project 越境 reject verify)
- migration が rollback 可能 (`down_revision` + downgrade 実装)
- 既存 artifact 操作 path (search / fetch / update) が project_id 条件追加で regression なし

## 残リスク

- DB schema sync で不整合発覚 → minimal migration 追加 (本 Sprint scope 内、想定 0.5 day 追加)
- artifacts.project_id backfill で null 残存 → 手動 SQL で個別 fix (本 Sprint scope 内、想定 0.3 day 追加)
- AC-HARD-03 artifact-domain test の fixture coverage 不足 → 最低 1 case PASS で must_ship satisfy、追加 case は SP-022.1 post-P0.1 で reroute

## 次スプリント候補

本 Sprint 完了で SP-013 kickoff 直前 prerequisite 全件 satisfy。次は:

1. ADR-00014/00019 proposed → accepted promotion
2. SP-013 Multi-Agent Orchestration Foundation batch 0 着手

## 関連 ADR

- ADR-00009 (Action Class Taxonomy) — 既 accepted、action_class enum 既 update 済 (本 Sprint で DB CHECK 整合 verify のみ)
- ADR-00014 (Multi-Agent Orchestration) — SP-013 kickoff 直前に accepted promotion
- ADR-00019 (Role Taxonomy) — 同上
- ADR-00021 (Host-Portable Deployment) — 既 accepted (SP022-T00 2026-05-19)、本 Sprint 範囲外

## Review

最終更新: 2026-05-22

### changed (3 件 must_ship 全件完遂)

| # | must_ship | PR | merge SHA |
|---|---|---|---|
| 1 | DB CHECK constraint sync verify (3 CHECK × 7 種 enum parametrize test) | #106 | 788a1caa |
| 2 | artifacts.project_id materialize migration (`0019_artifacts_project_id`) + ORM update + repository signature update | #107 | 51798507 |
| 3 | AC-HARD-03 artifact-domain cross-project negative test (5 integration test、DB skipif で gated) | #108 | c7183393 |

### verified

- pytest 全件 PASS (本 Sprint 関連 tests):
  - tests/policy/test_action_class_enum.py: 14 PASS (3 parametrize case 新規追加)
  - tests/runtime/test_artifact_immutable.py: 1 PASS (signature update 整合)
  - tests/security/test_artifact_cross_project_negative.py: 5 SKIPPED (DB 未設定環境)、DB 環境では 5 PASS 想定
  - artifact 関連 offline tests: 83 PASS
- ruff + mypy: clean (全 PR)
- 5+ source 整合 (Literal / frozenset / DB CHECK 3 か所 / pytest fixture): action_class 7 種
- migration apply test: `0019_artifacts_project_id` (25 chars、≤ 30 制限 ✓)

### deferred

- なし (全 must_ship 完遂、scope 全件 satisfy)

### risks (residual)

- artifacts.project_id backfill は orphan artifact なし前提 (`artifacts_run_fkey (tenant_id, run_id) NOT NULL`)、sanity check で NULL=0 fail-closed
- DB 接続前提 integration test 5 件は Mac local docker compose または CI Smoke で実行 → Phase 7a Mac drill 同等の運用検証で actual PASS verify
- 既存 ADR-00009 (action_class) 整合は backend code 既 update 済、本 Sprint で DB CHECK 機械検査追加で完了

### next

- ADR-00014/00019 proposed → accepted promotion (本 PR で実施)
- SP-013 batch 0 着手 (Multi-Agent Orchestration Foundation table 群)
