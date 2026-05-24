---
id: "SP-020_curator_insights_integration"
type: "heavy"
status: "ready"
sprint_no: 20
created_at: "2026-05-24"
updated_at: "2026-05-24"
target_days: 3
max_days: 5
adr_refs:
  - "[ADR-00016](../adr/00016_hermes_agent_integration_strategy.md) # accepted; Wave 22 curator + insights scope"
  - "[ADR-00014](../adr/00014_multi_agent_orchestration.md) # accepted; SecretBroker multi-agent invariant + KPI rollup source"
  - "[ADR-00009](../adr/00009_action_class_taxonomy.md) # accepted; policy_profile exact 14 rows / action_class boundary"
  - "[ADR-00020](../adr/00020_framework_intake_checklist.md) # accepted; external API / persistence / telemetry deny"
  - "[ADR-00024](../adr/00024_project_auto_discovery_memory_boundary.md) # accepted; memory project boundary"
  - "[ADR-00032](../adr/00032_curator_insights_metrics_boundary.md) # accepted 2026-05-24; curator / insights / adopted_artifacts boundary"
planned_adr_refs: []
related_sprints:
  - "SP-014_orchestrator_agent"
  - "SP-015_inter_agent_communication"
  - "SP-016_ui_cli_parity"
  - "SP-018_hermes_memory_integration"
  - "SP-022_framework_intake_hardening"
risks:
  - "curator may archive useful memory unless manual_user weighting and feature flags are fail-closed"
  - "insight summaries must remain ref-only and must not expose raw memory, raw message body, secrets, or capability tokens"
  - "adopted_artifacts attribution can inflate citation_coverage unless tenant/project/run/artifact boundaries are strict"
  - "PE-F-014/015/016 closure needs cross-source tests, not only docs trace"
---

最終更新: 2026-05-24 (SP020-T02 curator service foundation completed)

## 目的

SP-018 で完成した memory backend を使い、Hermes Wave 22 相当の curator / insights pattern を TaskManagedAI 境界で再実装する。完了 run / 失敗 run / review finding から memory を自動生成し、低価値 memory を安全に archive し、insight 集計を UI/CLI/API から ref-only に参照できるようにする。併せて SP-022 Phase E trace の残り PE-F-014 / PE-F-015 / PE-F-016 を SP-020 exit gate で closure する。

## 背景

- SP-013〜SP-018 は completed。memory_records / memory_retrieval_artifacts / feature-flagged read-only API は存在する。
- ADR-00016 Wave 22 は SP-020 に curator + insights を割り当てている。
- SP-022 Phase E trace では PE-F-014/015/016 が SP-020 未起票のまま残っていた。
- SP-020 は DB schema、API/CLI contract、AI prompt boundary、metrics source に触れるため heavy Sprint Pack + ADR gate が必要。

## 対象外

- external memory cloud / telemetry / independent SQLite persistence。
- ContextSnapshot 10 列の変更、置換、overlay。
- raw memory content / raw prompt / raw message body の API/CLI/UI 返却。
- character image generation (SP-021)。
- cron / routines Wave 23。
- broad auto-merge / production deploy / external publishing。

## 設計判断

- **curator writes through MemoryStoreService**: 自動生成 memory も SP-018 の sanitizer / artifact-bound / project boundary を必ず通す。
- **archive is retrieval exclusion, not deletion**: 低価値 memory は `archived_at` を設定し、retrieval から除外する。hard delete はしない。
- **manual_user protection**: `manual_user` は default で自動 archive 対象外。auto archive は `auto_completion` / `auto_failure` / `auto_review_finding` を優先する。
- **insights are ref-only**: insight API / CLI output は record id、record_kind、content_hash、source artifact ref、aggregate count、score だけを返す。
- **adopted_artifacts dedicated link table**: PE-F-015 の citation_coverage final-only attribution は `artifacts` 本体に boolean を足さず、tenant/project/run/artifact scoped link table を第一候補にする。
- **no event_type expansion in SP-020**: `repo_pr_merged` は SP-020 では追加せず、`repo_pr_opened` proxy を明示維持する。新 event_type が必要になった場合は ADR-00004 update + 5+ source enum sync を別 gate にする。
- **Phase E closure in tests**: PE-F-014/015/016 は docs trace ではなく exact reason_code / exact query / exact seed regression で close する。

## 実装チケット

- SP020-T00: plan-only gate (本 PR)。Sprint Pack / ADR-00032 proposed / registry / SP-022 trace を起票する。
- SP020-T01: ADR-00032 accepted promotion + implementation batch split review (completed)。
- SP020-T02: curator service foundation (completed)。completed/failed/review-finding source artifact から `auto_completion` / `auto_failure` / `auto_review_finding` memory を生成。
- SP020-T03: archive policy service。manual_user default protect、auto record aging/relevance policy、`memory_archive_engaged` audit。
- SP020-T04: insights aggregation service + read-only API / CLI surface。raw payload 非露出、feature flag disabled default。
- SP020-T05: adopted_artifacts link table + citation_coverage final-only attribution contract。
- SP020-T06: orchestrator auto-retrieve hook。retrieval output は `untrusted_content` のまま、trusted_instruction 昇格禁止。
- SP020-T07: Phase E closure tests。PE-F-014 6 reason_code / PE-F-015 exact query / PE-F-016 policy_profile 14 seed + review_artifact guard。
- SP020-T08: backup/restore extension。archive state / adopted_artifacts / insight source FK を verify。

## タスク一覧

- [x] SP020-T00 plan-only gate
- [x] SP020-T01 ADR-00032 accepted promotion + batch split
- [x] SP020-T02 curator service foundation
- [ ] SP020-T03 archive policy service
- [ ] SP020-T04 insights read-only API / CLI
- [ ] SP020-T05 adopted_artifacts metric attribution
- [ ] SP020-T06 orchestrator auto-retrieve hook
- [ ] SP020-T07 Phase E PE-F-014/015/016 closure tests
- [ ] SP020-T08 backup/restore extension

## must_ship / defer_if_over_budget 対応表

| 項目 | must_ship | defer_if_over_budget |
|---|---|---|
| ADR-00032 accepted before implementation | ○ | - |
| curator auto memory through MemoryStoreService | ○ | - |
| archive policy with manual_user protection | ○ | - |
| insight aggregation ref-only response | ○ | UI polish may defer |
| adopted_artifacts final-only attribution | ○ | repo_pr_merged event_type deferred; repo_pr_opened proxy must remain explicit |
| PE-F-014 6 reason_code closure | ○ | - |
| PE-F-015 exact query closure | ○ | - |
| PE-F-016 policy_profile closure | ○ | - |
| orchestrator auto-retrieve | ○ | enablement can remain feature-flag disabled |
| cron / routines | × | P1+ Wave 23 |
| character image generation | × | SP-021 |

## 受け入れ条件

- curator が生成する memory は `MemoryStoreService` を通り、raw secret / canary / raw message body が保存されない。
- auto archive は `manual_user` を default で対象外にし、archived record は retrieval に出ない。
- insight API / CLI は ref-only で、raw content を返さない。
- adopted_artifacts は `(tenant_id, project_id, run_id/artifact_id)` boundary を持ち、cross-project attribution を reject する。
- citation_coverage final-only query は adopted_artifacts だけを分母にし、draft / non-adopted artifact を除外する。
- SecretBroker multi-agent 6 negative case は exact reason_code で PASS する。
- policy_profile_action_effects は default + low_risk_auto_allow x 7 action_class = 14 rows exact のまま維持される。
- orchestrator auto-retrieve output は `untrusted_content` から自己昇格できない。
- backup/restore 後に archive state、adopted_artifacts FK、insight source FK が維持される。

## 検証手順

```bash
.claude/hooks/sprint/check-sprint-pack-frontmatter.sh docs/sprints/SP-020_curator_insights_integration.md
scripts/ci/check_phase_e_trace.sh
git diff --check

uv run ruff check backend/app/services/memory backend/app/api/memory.py cli/tm tests/memory tests/metrics tests/security
PYTHONPATH=cli uv run mypy backend/app/services/memory backend/app/api/memory.py cli/tm tests/memory tests/metrics tests/security
TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/memory tests/metrics/test_adopted_artifacts_kpi_boundary.py tests/security/test_secretbroker_multi_agent_reason_matrix.py -q
TASKMANAGEDAI_DATABASE_URL=<test-db-url> uv run alembic downgrade -1
TASKMANAGEDAI_DATABASE_URL=<test-db-url> uv run alembic upgrade head
```

## SP020-T01 implementation batch split

| batch | ticket | scope | risk | PR gate |
|---|---|---|---|---|
| 0a | SP020-T01 | ADR-00032 accepted promotion + batch split | docs / gate only | frontmatter + Phase E trace + diff check |
| 0b | SP020-T02 | curator service foundation through `MemoryStoreService` | memory write boundary | raw payload negative tests + store pipeline regression |
| 0c | SP020-T03 | archive policy service | retrieval exclusion / user data hiding | manual_user protect + archived retrieval exclusion |
| 0d | SP020-T04 | insights aggregation + disabled read-only API / CLI | raw content leakage | feature flag disabled default + ref-only API/CLI tests |
| 0e | SP020-T05 | `adopted_artifacts` link table + citation_coverage final-only query | DB / metrics | migration up/down + cross-project / non-final negatives |
| 0f | SP020-T06 | orchestrator auto-retrieve hook | AI prompt boundary | untrusted_content no self-promotion tests |
| 0g | SP020-T07 | PE-F-014/015/016 closure tests | cross-source invariant | exact reason_code / query / 14 seed regression |
| 0h | SP020-T08 | backup/restore extension + Sprint closeout | restore integrity | archive/adopted/insight FK restore drill |

Batch rule: 0b-0h must each run immediate self-review and `codex_pr_full_review.sh <PR>` after PR creation. Implementation must not proceed from a failed batch by widening scope; fix or defer explicitly.

## レビュー観点

- curator / insights が SP-018 memory boundary を迂回していないか。
- archive policy が manual_user や active memory を過剰に隠していないか。
- adopted_artifacts が citation_coverage を過大評価しないか。
- PE-F-014/015/016 は code/test で closure され、docs trace だけで完了扱いしていないか。
- API / CLI / audit payload に raw secret、raw message body、raw memory content が出ていないか。
- feature flag off の状態で runtime path が service に到達しないか。

## 残リスク

- `repo_pr_merged` event_type は SP-020 では追加せず、future ADR-00004 update + 5+ source enum sync が必要になった場合だけ扱う。
- UI dashboard polish は insight API/CLI contract の後に必要最小限で扱う。
- Cron / routines は Wave 23 として別 Sprint へ送る。

## 次スプリント候補

- SP-021 AI Character Generation (optional / P2)。
- Wave 23 cron / routines Sprint (番号未確定)。

## 関連 ADR

- [ADR-00016](../adr/00016_hermes_agent_integration_strategy.md): Wave 22 curator + insights scope。
- [ADR-00032](../adr/00032_curator_insights_metrics_boundary.md): SP-020 implementation boundary。
- [ADR-00014](../adr/00014_multi_agent_orchestration.md): SecretBroker multi-agent invariant / KPI source。
- [ADR-00009](../adr/00009_action_class_taxonomy.md): policy_profile exact seed。
- [ADR-00024](../adr/00024_project_auto_discovery_memory_boundary.md): memory project boundary。

## Review

### 2026-05-24 plan-only gate

changed:
- `docs/sprints/SP-020_curator_insights_integration.md`
- `docs/adr/00032_curator_insights_metrics_boundary.md`
- `docs/sprints/README.md`
- `docs/sprints/SP-022_framework_intake_hardening.md`
- `docs/adr/00016_hermes_agent_integration_strategy.md`

implemented:
- SP-020 heavy Sprint Pack 起票。
- ADR-00032 proposed 起票。
- SP-022 PE-F-014/015/016 を SP-020 plan gate へ trace。

verified:
- `.claude/hooks/sprint/check-sprint-pack-frontmatter.sh docs/sprints/SP-020_curator_insights_integration.md`
- `scripts/ci/check_phase_e_trace.sh`
- `git diff --check`

deferred:
- Runtime implementation SP020-T02+.

risks:
- Implementation batches must remain feature-flagged and ref-only until API/CLI redaction and boundary tests pass.

### 2026-05-24 SP020-T01 ADR readiness gate

changed:
- `docs/adr/00032_curator_insights_metrics_boundary.md`
- `docs/sprints/SP-020_curator_insights_integration.md`
- `docs/sprints/README.md`
- `docs/sprints/SP-022_framework_intake_hardening.md`

implemented:
- ADR-00032 `proposed → accepted` promotion.
- `planned_adr_refs` から `adr_refs` へ移動。
- SP020-T02〜T08 の batch split を確定。
- `repo_pr_merged` event_type は SP-020 では追加せず、`repo_pr_opened` proxy を明示維持する判断を記録。

verified:
- `.claude/hooks/sprint/check-sprint-pack-frontmatter.sh docs/sprints/SP-020_curator_insights_integration.md`
- `scripts/ci/check_phase_e_trace.sh`
- `git diff --check`

deferred:
- Runtime implementation SP020-T02+.
- `repo_pr_merged` event_type additive expansion (future ADR-00004 update only if needed).

risks:
- SP020-T05 migration は DB schema 変更のため、dedicated PR で migration up/down と cross-project negative tests を必須にする。

### 2026-05-24 SP020-T02 curator service foundation

changed:
- `backend/app/schemas/memory.py`
- `backend/app/services/memory/curator.py`
- `backend/app/services/memory/store.py`
- `backend/app/services/memory/__init__.py`
- `tests/memory/test_curator_service.py`
- `docs/sprints/SP-020_curator_insights_integration.md`
- `docs/sprints/README.md`

implemented:
- `MemoryCuratorService` を追加し、`completed_run` / `failed_run` / `review_finding` を `auto_completion` / `auto_failure` / `auto_review_finding` に server-side map。
- curator memory は `MemoryStoreService` を通して保存し、source artifact は tenant/project/run/id boundary で検証。
- source artifact body は読まず、`artifact_ref` / `artifact_kind` / `artifact_digest` / `run_ref` と `summary_ref` だけを sanitized payload に保存。
- `MemoryCuratorRequest` は caller から `record_kind` / `content_hash` / `trust_level` など server-owned field を受け付けず、`summary_ref` は `artifact://summary/` ref-only に固定。

self_review:
- adopted: `summary_ref` が任意 text を受け取れると raw summary body が保存され得るため、schema validator と negative test を追加。

verified:
- `uv run ruff check backend/app/services/memory backend/app/schemas/memory.py tests/memory`
- `PYTHONPATH=cli uv run mypy backend/app/services/memory backend/app/schemas/memory.py tests/memory/test_curator_service.py`
- `uv run pytest tests/memory -q` (`14 passed, 10 skipped`)
- `TASKMANAGEDAI_DATABASE_URL=<isolated 127.0.0.1:55432 test db> TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/memory/test_curator_service.py tests/memory/test_store_pipeline.py -q` (`10 passed`)

deferred:
- Archive policy / retrieval exclusion (SP020-T03)。
- Insights API / CLI surface (SP020-T04)。
- adopted_artifacts migration and citation_coverage final-only query (SP020-T05)。

risks:
- T03 must keep `manual_user` default protected and retrieval exclusion separate from deletion.
- T04 must keep insight output ref-only and feature-flag disabled by default.
