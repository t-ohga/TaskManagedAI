---
id: "SP-018_hermes_memory_integration"
type: "heavy"
status: "draft"
sprint_no: 18
created_at: "2026-05-24"
updated_at: "2026-05-24"
target_days: 5
max_days: 7
adr_refs:
  - "[ADR-00016](../adr/00016_hermes_agent_integration_strategy.md) # proposed; Hermes pattern adoption + memory/context boundary"
  - "[ADR-00024](../adr/00024_project_auto_discovery_memory_boundary.md) # proposed; cross-project memory retrieval deny-by-default"
  - "[ADR-00014](../adr/00014_multi_agent_orchestration.md) # accepted; trust_level and multi-agent invariant source"
  - "[ADR-00020](../adr/00020_framework_intake_checklist.md) # accepted; framework/pattern intake CI boundary"
planned_adr_refs:
  - "ADR-00016 must be promoted to accepted before DB/API implementation"
  - "ADR-00024 must be promoted to accepted before memory retrieval implementation"
related_sprints:
  - "SP-013_multi_agent_orchestration"
  - "SP-014_orchestrator_agent"
  - "SP-015_inter_agent_communication"
  - "SP-016_ui_cli_parity"
  - "SP-017_ai_society_visualization"
  - "SP-020_curator_insights_integration"
  - "SP-022_framework_intake_hardening"
risks:
  - "DB schema/API/AI prompt boundary change; implementation requires explicit gate after plan review"
  - "cross-project retrieval must be deny-by-default at service, DB, schema, and test layers"
  - "ContextSnapshot 10 columns must remain read-only; memory may only add separate retrieval metadata"
  - "raw secret / canary / raw message body must never be stored in memory records, retrieval artifacts, audit, or prompts"
  - "Hermes integration is pattern adoption only; no external memory cloud, SQLite persistence, or source embed"
---

最終更新: 2026-05-24 (batch 0a plan-only 起票、実装未着手)

## 目的

Hermes-agent 由来の memory / context pattern を TaskManagedAI 境界で再実装し、run history、review finding、user preference、repo cache を tenant/project scoped memory として扱えるようにする。SP-018 は **P1 memory backend の実装 Sprint** だが、DB schema / API / AI prompt boundary を含むため、本 PR では plan-only gate を作り、runtime 実装は ADR-00016 / ADR-00024 accepted 化後に別 batch で行う。

## 対象外

- Hermes / mem0 / supermemory / honcho code embed
- external memory cloud API / telemetry / independent SQLite persistence
- ContextSnapshot 10 columns の置換、overlay、暗黙拡張
- character image generation (SP-021)
- curator / insights automation (SP-020)
- cron / routines Wave 23
- `tm memory` runtime command enablement (SP-018 accepted implementation 後)

## readiness gate

| gate | status | note |
|---|---|---|
| ADR-00016 accepted | blocked | proposed のまま。SP-018 plan review 後に accepted promotion が必要 |
| ADR-00024 accepted | blocked | proposed のまま。cross-project memory retrieval boundary を accepted 化する |
| content storage shape | blocked | ADR-00016 / Phase C は `content_artifact_ref` 正本、ADR-00024 は `redacted_content` 例を持つ。実装前に `content_artifact_ref` + `content_hash` を default として ADR-00024 を同期する |
| artifacts project boundary | ready | `artifacts.project_id` + unique `(tenant_id, project_id, id)` は SP-013 prerequisite で完了済 |
| sanitizer_policy_versions seed | ready | SP-013 migration `0023_multi_agent_foundation_d.py` で minimal table exists。SP-018 は FK 接続と drift handling を追加する |
| GitHub Actions | blocked infra | hosted Actions は月次 quota blocked。local verify を正本にする |

## 設計判断

- **pattern adoption only**: Hermes の設計 pattern は採用するが、source code、SQLite persistence、external providers は取り込まない。
- **memory is not ContextSnapshot**: retrieval result は `memory_retrieval_artifacts` に ref として保存し、ContextSnapshot 10 列を変更しない。
- **raw memory text is artifact-bound**: memory text は raw column に置かず、redaction 済み artifact ref + hash を正本にする。API response / prompt / audit も ref-only を基本にする。
- **deny-by-default project boundary**: `project_id` は必須。cross-project retrieval は service guard、schema validation、DB filter、pytest negative の 4 層で deny。
- **untrusted by default**: memory-derived prompt input は `trust_level=untrusted_content`。`validated_artifact` 昇格は human approval と server-owned refs が揃うまで禁止。
- **sanitizer drift fail-closed**: `sanitizer_policy_versions.config_hash` mismatch は retrieval deny、explicit re-sanitize job、old snippet quarantine の 3 段で扱う。

## 実装チケット

- SP018-T00: plan-only gate (本 PR)。Sprint Pack / registry / Phase E trace を起票し、runtime 実装 blocker を明示する。
- SP018-T01: ADR-00016 / ADR-00024 accepted promotion + content storage shape drift fix。
- SP018-T02: `memory_records` + `memory_retrieval_artifacts` schema / ORM / migrations / rollback round-trip。
- SP018-T03: record_kind 5+ source enum (`manual_user`, `manual_agent`, `auto_completion`, `auto_failure`, `auto_review_finding`) + drift tests。
- SP018-T04: memory store pipeline (artifact ref, content_hash, sanitizer_version_id, secret/canary scan, no raw secret snapshot)。
- SP018-T05: retrieval pipeline (project filter, cross-project deny, archived/retention exclusion, trust_level untrusted)。
- SP018-T06: ContextSnapshot read-only guard + retrieval artifact reference path。
- SP018-T07: backup/restore drill extension (memory_records / retrieval_artifacts / sanitizer drift)。
- SP018-T08: CLI/API disabled contract first, then feature-flagged read-only retrieval endpoint after T02-T07 pass。

## タスク一覧

- [x] SP018-T00 plan-only gate
- [ ] SP018-T01 ADR promotion + drift fix
- [ ] SP018-T02 schema / ORM / migrations
- [ ] SP018-T03 record_kind enum 5+ source
- [ ] SP018-T04 store pipeline
- [ ] SP018-T05 retrieval pipeline
- [ ] SP018-T06 ContextSnapshot read-only guard
- [ ] SP018-T07 backup/restore drill
- [ ] SP018-T08 disabled contract / feature-flagged endpoint

## must_ship / defer_if_over_budget 対応表

| 項目 | must_ship | defer_if_over_budget |
|---|---|---|
| `memory_records` + `memory_retrieval_artifacts` DDL | ○ | - |
| composite FK `(tenant_id, project_id, id)` boundary | ○ | - |
| record_kind enum 5+ source integrity | ○ | - |
| sanitizer_version_id FK + config_hash drift handling | ○ | - |
| secret canary scan + raw value negative tests | ○ | - |
| ContextSnapshot 10 column unchanged test | ○ | - |
| backup/restore drill extension | ○ | - |
| read-only retrieval endpoint | ○ | can remain feature-flag disabled until next Sprint |
| memory mutation UI | × | SP-019/SP-020 |
| curator / insights automation | × | SP-020 |
| cron / routines | × | P1+/P2 Wave 23 |

## 受け入れ条件

- ADR-00016 / ADR-00024 が accepted になり、content storage shape drift が解消されている。
- `memory_records` は tenant/project boundary を DB level で持ち、`unique (tenant_id, project_id, id)` を持つ。
- `memory_retrieval_artifacts` は `memory_records` へ `(tenant_id, project_id, memory_record_id)` FK で接続する。
- `source_artifact_id` を持つ場合は `(tenant_id, project_id, source_artifact_id)` が `artifacts` に存在する。
- record_kind は Python domain / Pydantic schema / DB CHECK / pytest / docs の 5+ source で exact match。
- cross-project retrieval attempt は service, schema, DB filter, regression test の 4 層で deny。
- ContextSnapshot 10 列は schema introspection test で完全一致を維持し、memory retrieval が overlay できない。
- retrieval artifact payload は `trust_level=untrusted_content` 固定で、`trusted_instruction` / `validated_artifact` に自己昇格できない。
- raw secret、fake canary、raw prompt、raw message body は memory records、retrieval artifacts、audit payload、test snapshots に残らない。
- restore 後 sanitizer config_hash mismatch は `stale_sanitizer` deny または explicit re-sanitize path に進む。

## 検証手順

```bash
# plan-only gate
.claude/hooks/sprint/check-sprint-pack-frontmatter.sh docs/sprints/SP-018_hermes_memory_integration.md
git diff --check

# implementation batches after ADR acceptance
uv run ruff check backend/app/services/memory backend/app/schemas tests/memory tests/db
PYTHONPATH=cli uv run mypy backend/app/services/memory backend/app/schemas tests/memory
TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/memory tests/db/test_schema_introspection.py tests/db/test_backup_restore_memory.py -q
TASKMANAGEDAI_DATABASE_URL=<test-db-url> uv run alembic upgrade head
TASKMANAGEDAI_DATABASE_URL=<test-db-url> uv run alembic downgrade -1
TASKMANAGEDAI_DATABASE_URL=<test-db-url> uv run alembic upgrade head
```

## Phase E trace carried into SP-018

| Finding ID | SP-018 handling |
|---|---|
| PE-F-011 | action_class strictness / enum crossing is checked before memory prompt enrichment. ADR update before implementation. |
| PE-F-012 | role_scope/global DB check and link-table edge cases remain SP-013/SP-018 contract review input; SP-018 must not widen role references. |
| PE-F-013 | remote agent adapter/router/frontend/config/test paths remain sealed; memory backend must not create remote dispatch bypass. |

## Review

### 2026-05-24 batch 0a: plan-only gate

changed:
- `docs/sprints/SP-018_hermes_memory_integration.md`
- `docs/sprints/README.md`
- `docs/sprints/SP-022_framework_intake_hardening.md`

implemented:
- SP-018 heavy Sprint Pack 起票。
- ADR-00016 / ADR-00024 proposed status と implementation blocker を明示。
- content storage shape drift (`content_artifact_ref` vs `redacted_content`) を implementation blocker として記録。
- Phase E PE-F-011〜013 の SP-018 trace を Sprint Pack へ移植。

verified:
- `.claude/hooks/sprint/check-sprint-pack-frontmatter.sh docs/sprints/SP-018_hermes_memory_integration.md`
- `git diff --check`

deferred:
- DB schema / migration / API / service implementation は ADR acceptance 後の batch に defer。
- memory UI mutation、curator、cron は SP-019/SP-020/P1+ に defer。

risks:
- `alembic check` は repo 既知の `target_metadata` infrastructure debt が残るため、implementation batch では test DB upgrade/downgrade round-trip を正本 verify にする。
