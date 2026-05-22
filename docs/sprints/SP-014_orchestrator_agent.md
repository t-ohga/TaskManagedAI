---
id: "SP-014_orchestrator_agent"
type: "heavy"
status: "ready"
sprint_no: 14
created_at: "2026-05-10"
updated_at: "2026-05-22"
target_days: 4
max_days: 6
adr_refs:
  - "[ADR-00014](../adr/00014_multi_agent_orchestration.md) # accepted 2026-05-22 (PR #109)、SP-013 batch 0 完遂で本 Sprint kickoff prerequisite satisfied"
  - "[ADR-00009 update](../adr/00009_action_class_taxonomy.md) # accepted 2026-05-22、policy_profile schema / policy_decisions trace / 14 row seed を batch 0c で実装 (Criteria #4)"
  - "[ADR-00030](../adr/00030_tool_registry_network_enum.md) # accepted 2026-05-22、Tool Registry network_access enum + tool_network_policies を batch 0d で実装 (Criteria #5)"
planned_adr_refs: []
related_sprints:
  - "SP-013_multi_agent_orchestration"
  - "SP-015_inter_agent_communication"
risks:
  - "PE-F-002 (atomic consume SQL の receiver eligibility 抜け)"
  - "PE-F-003 (Tier 2 で agent decider 経路残存)"
  - "PE-F-004 (no-progress detection の閾値設計)"
  - "PE-F-013 (remote_agent_gateway P0.1 deny-only stub の audit schema)"
  - "PE-F-014 (SecretBroker 6 case 個別 reason_code)"
  - "PE-F-015 (KPI rollup の recursive CTE / dedupe)"
  - "PE-F-016 (policy_profile_action_effects seed の網羅性)"
kickoff_readiness:
  prerequisite_sp013_batch_0: "✅ satisfied (PR #133-#140、Multi-Agent Foundation core schema 完成、2026-05-22)"
  prerequisite_agent_runs_lease_columns: "✅ satisfied (PR #136、orchestrator_lease_* 8 columns 完備)"
  prerequisite_check_project_role_trigger: "✅ satisfied (PR #138 → #140、PE-F-012 DB-level defense + project + standard role accept)"
  prerequisite_standard_role_taxonomy: "✅ satisfied (10 standard role + matrix validator + immutable seed、PR #133-#137/#134)"
  kickoff_blocker: "なし"
  recommended_execution: "codex-all-loops mode=code 委譲 (heavy Sprint Pack、scope 大、Codex first 実装で品質担保)"
---

最終更新: 2026-05-22 (task-01 batch 0e: remote_agent_gateway deny-only stub / audit payload 反映)

## 目的

orchestrator agent (司令塔) の本体実装 + lease/heartbeat/failover/kill-switch + max_* 上限 + remote_agent_gateway deny-only stub + 3 階層 operation 分散 (Tier 1/2/3) + policy_profile + Tool Registry network enum + KPI rollup metric contract test + SecretBroker multi-agent negative 6 case を P0.1 で完成させる.

## 背景

- SP-013 で foundation table 群が完成、本 Sprint で orchestrator service module + Policy Engine 拡張 + Tool Registry 拡張 を実装
- ADR-00014 + ADR-00019 は SP-013 で accepted、ADR-00009 update + Tool Registry network ADR は本 Sprint で起票 + accepted
- Phase D PD-F-005 + Phase E PE-F-003 の **Tier 2 human-only invariant** は最重要 (decider human-only を絶対破らない)

## 対象外

- inter_agent_messages 本体 (SP-015、本 Sprint では publisher API のみ stub で先行)
- CLI / Web UI 拡張 (SP-016 / SP-017)
- memory backend (SP-018)
- Wave 23 cron / routines

## 設計判断

- **Tier 2 = approval_requests を作らない** (Policy Engine が effect=allow profile を出すだけ、agent decider 経路を作らない、PD-F-005)
- **policy_profile_action_effects seed = default + low_risk_auto_allow × 7 action_class = 14 rows exact** (PE-F-016)
- **policy_decisions 拡張**: `policy_profile`, `profile_resolved_effect`, `required_review_artifact_id` 列追加 + review_artifacts FK
- **lease atomic claim**: SecretBroker と同等 pattern (UPDATE + WHERE + RETURNING、AgentRunEvent append 同一 transaction)
- **progress lease**: 30 分 no-progress (tenant_config 5-120 分) で `blocked + runtime_blocked` (PE-F-004)
- **remote_agent_gateway**: P0.1 開始時に deny-only stub 作成、`remote_agent_dispatch_denied` audit_event payload 定義 (PE-F-013)
- **Tool Registry network_access**: boolean → enum (`none/allowlist/internet`)、別 table `tool_network_policies` で domain_allowlist/payload_data_class_max/provider_required 保存 (P0 中は web_fetch/docs_search を deny-only)

## 実装チケット

- SP014-T01: actor_type='agent' + role_id='orchestrator' で識別する orchestrator service module + lease_manager / heartbeat / failover / kill_switch / progress_lease / limits
- SP014-T02: review_artifacts table + 4 重防御 (DB CHECK + service guard + Pydantic + contract test)
- SP014-T03: policy_decisions 拡張列追加 + policy_profile + policy_profile_action_effects table + 14 rows seed
- SP014-T04: ADR-00009 update accepted (policy_profile schema + DD-02 同期 + AC-HARD-01 fixture 拡張)
- SP014-T05: Tool Registry network_access enum 化 ADR (新規 P0.1) + tool_network_policies table + web_fetch/docs_search 登録 (deny-only initially)
- SP014-T06: remote_agent_gateway deny-only stub + remote_agent_dispatch_denied audit
- SP014-T07: orchestrator_kpi_rollup query 実装 (recursive CTE + idempotency dedupe) + metric contract test (PE-F-015)
- SP014-T08: SecretBroker multi-agent negative 6 case 個別 reason_code + test (PE-F-014)
- SP014-T09: agent_run_events.event_type 22→31 拡張 (ADR-00004 update)

## タスク一覧

- [ ] SP014-T01-T09 を順次実装
- [ ] ADR-00009 / Tool Registry network ADR を proposed → accepted
- [ ] migration `00NN_p0_1_orchestrator.py` + `00NN_p0_1_policy_profile.py` PASS
- [ ] policy_profile_action_effects 14 rows seed verify
- [ ] orchestrator lease/failover stress test (60s heartbeat 失敗 → failover)
- [ ] max_* 違反全件 reject + 絶対上限 (children≤20/depth≤5/turns≤500/budget≤$50) DB CHECK で破れない確認
- [ ] Tier 2 で agent decider 経路残存しない (4 重防御 negative test)
- [ ] SecretBroker 6 negative case 個別 reason_code で deny

## must_ship / defer_if_over_budget 対応表

| 項目 | must_ship | defer_if_over_budget |
|---|---|---|
| orchestrator service + lease/heartbeat/failover/kill | ○ | - |
| policy_profile + 14 rows seed | ○ | - |
| review_artifacts 4 重防御 | ○ | - |
| Tool Registry network enum + tool_network_policies | ○ | tool 登録は SP-018 で完了可 |
| remote_agent_gateway deny-only stub | ○ | - |
| KPI rollup query + contract test | ○ | adopted_artifacts link table は SP-018 で完成可 |
| SecretBroker 6 negative case | ○ | - |
| event_type 22→31 拡張 | ○ | - |
| progress lease (PE-F-004) | ○ | tenant_config tuning は SP-022 で再検討可 |

## 受け入れ条件

- orchestrator が approval decider として登録試行 → DB CHECK + service guard + Pydantic + test 4 重防御で全件 reject (Tier 2 escape 不可)
- lease 60s renew + 失敗 failover + active child は graceful suspend
- max_* 違反 reject、tenant_config で絶対上限超過 fail-closed
- progress lease no-progress 30 分で `blocked + runtime_blocked`
- 3 階層 operation の各 boundary が機能 (Tier 1 自律 / Tier 2 Policy auto-allow / Tier 3 human approval)
- remote_agent_gateway P0.1 stub: orchestrator_dispatched で remote child 試行 → 全件 deny + remote_agent_dispatch_denied audit
- SecretBroker multi-agent 6 negative case 個別 reason_code で deny
- KPI rollup metric contract test 全件 PASS
- AC-HARD-01 fixture (multi-agent 文脈、unknown profile / missing seed row / secret_access allow drift / provider_call without ZDR / task_write without review_artifact) 全件 deny

## 検証手順

```bash
uv run pytest tests/multi_agent/test_orchestrator_lease_failover.py \
              tests/multi_agent/test_progress_lease.py \
              tests/multi_agent/test_max_limits.py \
              tests/multi_agent/test_action_class_3tier.py \
              tests/multi_agent/test_orchestrator_requester_only.py \
              tests/multi_agent/test_review_artifact_4_defense.py \
              tests/security/test_secretbroker_multi_agent_negative.py \
              tests/multi_agent/test_remote_agent_gateway_p0_1_stub.py \
              tests/metrics/test_*_rollup*.py \
              tests/policy/test_action_class_enum.py \
              tests/policy/test_policy_profile_seed.py -q

uv run alembic check && uv run alembic upgrade head
```

## レビュー観点

- Tier 2 で agent decider 経路が DB / service / Pydantic / test の 4 層で完全 reject
- policy_profile_action_effects seed が exact 14 rows、全 action_class effect が明示
- KPI rollup recursive CTE が 既存正本 source (eval_runs/eval_scores/agent_run_events.event_type='repo_pr_opened/provider_responded'/claims/evidence_items) のみ参照
- SecretBroker 6 negative case の reason_code が cross-source-enum-integrity §1 で 5+ source 整合
- remote_agent_gateway P0.1 stub の audit payload が ADR-00013 mapping table と整合

## 残リスク

- PE-F-002 (atomic consume SQL の receiver eligibility) は SP-015 で確認 (本 Sprint では publisher API stub のみ)
- KPI `time_to_merge` の current source は repo_pr_opened のみ、`repo_pr_merged` event 追加は ADR-00004 update with SP-014 で proposed、SP-022 で final accepted
- citation_coverage の adopted_artifacts link table 設計は SP-018 まで持ち越し
- character image generation (P2) と provider Compliance Matrix の整合は SP-021 で確認

## 次スプリント候補

- SP-015 inter-agent communication (本 Sprint の publisher stub を本実装に拡張)

## 関連 ADR

- ADR-00014 / ADR-00009 update / Tool Registry network ADR (新規) / ADR-00013 update / ADR-00018 (関連) / ADR-00004 update (event_type 22→31)

## Review

- 2026-05-22 task-01 batch 0a: orchestrator lease primitives 完了、PR #145 merged。
- 2026-05-22 task-01 batch 0b: review_artifacts 4 重防御 完了、PR #146 merged。
- 2026-05-22 task-01 batch 0c: policy_profile schema / exact 14 seed / policy_decisions trace / ADR-00009 update 完了。`alembic check` は既存 `migrations/env.py target_metadata` debt で継続 defer。
- 2026-05-22 task-01 batch 0d: Tool Registry network_access enum / tool_network_policies / web_fetch+docs_search deny-only seed / ADR-00030 accepted update 完了。`internet` は enum として保持するが P0 service guard では deny。
- 2026-05-22 task-01 batch 0e: remote_agent_gateway P0.1 deny-only stub 完了。full remote adapter/API/config は ADR-00013 proposed のまま禁止、stub は `remote_agent_dispatch_denied` audit だけを emit。
