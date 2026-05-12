---
id: "SP-009_p0_ui_pack"
type: "heavy"
status: "draft"
sprint_no: 9
created_at: "2026-05-12"
updated_at: "2026-05-12"
target_days: 6
max_days: 9
adr_refs:
  - "[ADR-00001](../adr/00001_auth_rbac.md) # accepted、dev login / actor binding"
  - "[ADR-00003](../adr/00003_api_contract.md) # accepted (P0 で proposed → 着手時 accepted)、FastAPI + OpenAPI + Pydantic response model"
  - "[ADR-00004](../adr/00004_agentrun_state_machine.md) # accepted、AgentRun 16 状態 + blocked_reason 3 種、UI で status / reason を分離表示"
  - "[ADR-00009](../adr/00009_action_class_taxonomy.md) # accepted、action_class 7 種、Approval UI で表示"
  - "[ADR-00014](../adr/00014_multi_agent_orchestration.md) # proposed (P0.1 で accepted 化予定)、10 role + 4 面 UI 参照 (Symphony cross-reference 含む)"
planned_adr_refs: []
related_sprints:
  - "SP-005-5_output_validator"
  - "SP-006_cli_artifact"
  - "SP-007_runner_sandbox"
  - "SP-008_github_app_repoproxy"
upstream_sprints:
  - "SP-001_project_foundation"
  - "SP-002_core_data_model"
  - "SP-003_policy_approval"
  - "SP-004_agent_runtime"
  - "SP-005_provider_adapter"
  - "SP-005-5_output_validator"
  - "SP-008_github_app_repoproxy"
downstream_sprints:
  - "SP-010_eval_harness"
  - "SP-011_5_observability"
  - "SP-012_p0_acceptance"
risks:
  - "UI scope creep (4 面 UI + Plan Mode + dashboard を 6/9 day 枠で収めにくい)"
  - "frontend telemetry を KPI 正本にする regression"
  - "UI 都合で AgentRun status enum を増やす invariant 破壊"
  - "Approval UI で agent が decider になる経路の混入"
  - "Execution Log で raw secret / provider response の暴露"
---

最終更新: 2026-05-12 (light skeleton 起票、Phase A integration、実装着手前に heavy 化必要)

## 目的

- P0 UI の **読みやすさ + 承認の流れ + 実行の透明性** を 4 面 UI + Plan Mode で実装する
- AI-UIUX レポート (`docs/設計検討/AI統合タスク管理プラットフォームの最新UIUXと実装選定レポート.md`) と統合結論 (`docs/設計検討/2026-05-12_external_ai_concept_uiux_integration.md`) を P0 UI に吸収する
- **read-only / approval-centered** に絞る、bulk action / policy editor / analytics drill-down は P1 へ送る (UI scope creep 防止)

## 背景

- P0 UI は PRD-01 F-017 (Ticket / Approval Inbox / Agent Runs / Audit / Eval Dashboard) で要求
- これまで Sprint 9 用の Pack は未起票 (`SP-009_p0_ui_pack.md` not exist)
- AI-UIUX レポートで「UI 4 面構成 + Plan Mode + 業務価値 + 技術監視 2 軸 dashboard」が業界ベストプラクティスとして示唆された (2026-05-12 採用判定済)
- 既存 AgentRun 16 状態 / Approval Workflow / AgentRunEvent はすべて整合、新 status / 新 approval semantics は作らない

## 対象外 (P1 / Sprint 11.5 へ)

- bulk action (複数 ticket 同時 approve)
- policy editor UI
- analytics drill-down (時系列 / cohort 分析)
- 技術監視 dashboard (p95 latency / queue depth / provider error rate / 429 rate) は **Sprint 11.5 observability で実装**
- WebSocket / Server-Sent Events での live update (P0 は polling + page refresh で完結)
- AI Society Visualization (ADR-00017、P0.1 SP-017 で実装)

## 設計判断

### 1. 4 面 UI (AI-UIUX レポート §推奨ワークフロー より採用)

```text
[ Portfolio / Team Board ]                  ← Board page
┌──────────────────────────────────────────┐
│ Sprint / Queue / SLA / Risk             │
│ ───────────────────────────────────────  │
│ To Plan │ In Execution │ Review │ Done  │
└──────────────────────────────────────────┘

[ Task Detail ]                              ← Ticket detail page
┌──────────────────┬────────────────────────┐
│ 左: 依頼・要件   │ 右: AI 計画 / 承認     │
│ - 目的           │ - plan_v3              │
│ - 制約           │ - reviewer comment     │
│ - 期限           │ - approve/edit/reject  │
├──────────────────┴────────────────────────┤
│ Execution Log: tools / citations / diffs  │ ← 同 page 下部
│   / eval scores / policy decision         │
└───────────────────────────────────────────┘

[ Approval Inbox ]                           ← Approval Inbox page
- pending approvals + risk_level + action_class
- decider human-only enforced

[ AI Runs ]                                  ← Agent Runs page
- 16 状態 + blocked_reason 表示
- AgentRunEvent timeline
```

### 2. Plan Mode (AI 計画 → 人間 approve / edit / reject)

- AgentRun `generated_artifact → schema_validated → policy_linted → diff_ready → waiting_approval` の **`waiting_approval` 状態を Plan Mode UI で表現**
- UI ボタン: **Approve** (`approval_decided` event 発行)、**Edit** (artifact を artifact_v(N+1) として作り直し)、**Reject** (`approval_decided` rejected 発行)
- agent は **decider にならない** (ADR-00014 human-only approval 不変)
- Plan 内訳表示: `tool_manifest` + `policy_version` + `provider_request_fingerprint` + `evidence_set_hash`

### 3. Execution Log

- 同一 timeline で `tools` / `citations` / `diffs` / `eval scores` / `policy decision` / `audit refs` を表示
- source of truth: **AuditEvent / AgentRunEvent (append-only)**、frontend cache は invalidation 可能
- raw secret / provider response は表示しない (redaction 後 hash のみ)

### 4. 業務価値 dashboard

- Quality KPIs 5 を可視化: `acceptance_pass_rate` / `time_to_merge` / `approval_wait_ms` / `citation_coverage` / `cost_per_completed_task`
- source: **DB + audit_events + provider_usage table**、frontend event を KPI 正本にしない
- read-only、drill-down は P1
- 技術監視 (p95 latency / queue / error rate) は **Sprint 11.5 で Grafana 化、本 Sprint には含めない**

### 5. AgentRun status / blocked_reason 表示

- status は 16 個固定 (`docs/基本設計/03_AIオーケストレーション設計.md` §39-74)
- `blocked` 状態のみ `blocked_reason` (`policy_blocked` / `budget_blocked` / `runtime_blocked`) を別 badge で表示
- UI 都合で新 status / 新 blocked_reason を増やさない (invariant 破壊)

## 実装チケット (案、heavy 化時に詳細化)

| ID | 概要 | 工数 | 依存 |
|---|---|---:|---|
| BL-0090 | Board page (Portfolio / Team / Sprint view + To Plan / In Execution / Review / Done columns) | M | SP-008 完了 |
| BL-0091 | Ticket detail page (依頼/要件 + AI 計画/承認 + Execution Log timeline) | L | BL-0090 |
| BL-0092 | Plan Mode UI (approve / edit / reject + plan 内訳表示) | M | BL-0091 + Approval API (SP-003) |
| BL-0093 | Approval Inbox page (pending + risk_level + action_class、human-only decider) | M | SP-003 |
| BL-0094 | AI Runs page (16 状態 + blocked_reason badge + AgentRunEvent timeline) | M | SP-004 + SP-005-5 |
| BL-0095 | 業務価値 dashboard (Quality KPIs 5 read-only) | M | SP-010 Eval Harness |
| BL-0096 | UI から AgentRun cancel (active runs に limit) | S | SP-004 |
| BL-0097 | Audit Log viewer (AuditEvent timeline) | S | SP-003 + 既存 audit_events |

## must_ship / defer_if_over_budget

### must_ship (P0 Exit に直結)

- BL-0090 Board page
- BL-0091 Ticket detail
- BL-0092 Plan Mode UI (approve / reject)
- BL-0093 Approval Inbox
- BL-0094 AI Runs (status + AgentRunEvent timeline、blocked_reason badge)

### defer_if_over_budget (P0.1 / P1 へ送る)

- BL-0095 業務価値 dashboard (read-only) → P0.1 SP-010 Eval Harness 完成後で OK
- BL-0096 UI cancel → P0.1 / P1
- BL-0097 Audit Log viewer → P0.1 / P1 (P0 は API で確認、UI 表示不要)

## 受け入れ条件

- [ ] 4 面 UI (Board / Ticket Detail / Approval Inbox / AI Runs) すべてが Tailscale 閉域内で表示できる
- [ ] Plan Mode で `waiting_approval` 状態の AgentRun に対し human approve / reject が可能、agent decider 経路がない
- [ ] AgentRun status 16 個固定、UI が status enum を増やしていない
- [ ] `blocked_reason` 3 種 (`policy_blocked` / `budget_blocked` / `runtime_blocked`) を status と分離 badge で表示
- [ ] Execution Log で raw secret / provider response が表示されない (redaction 後 hash のみ)
- [ ] frontend は KPI 正本にしない (DB + audit_events を source of truth)
- [ ] Playwright E2E で 4 面の主要 flow (login → Board → Ticket Detail → Approve → Done) が通る
- [ ] AI-UIUX レポート §UI/UX + 統合結論 §3 (Plan Mode + 4 面 UI 採用判定) との整合確認
- [ ] ADR-00014 Symphony cross-reference (§外部参照モデル) に整合した UI 設計

## 検証手順

```bash
# Frontend
cd frontend
pnpm install --frozen-lockfile
pnpm exec tsc --noEmit
pnpm exec eslint . --max-warnings=0
pnpm exec vitest run
pnpm exec playwright test

# Backend (API contract)
uv run pytest tests/api/ -q
```

E2E test 追加候補:
- `frontend/tests/e2e/board.spec.ts`: Board page で AI Runs / Approval Inbox link が render
- `frontend/tests/e2e/ticket-detail.spec.ts`: Plan Mode で approve / reject ボタンが visible、agent decider 経路なし
- `frontend/tests/e2e/agent-runs.spec.ts`: 16 状態 + blocked_reason badge 表示

## レビュー観点

- AgentRun status enum 不変 (16 個)
- `blocked_reason` 3 種以外を追加していない
- Approval decider が human-only (agent decider 経路なし)
- raw secret / provider response の暴露なし
- frontend cache が KPI 正本になっていない
- AI-UIUX レポート §UI/UX + 統合結論 §3 との整合
- ADR-00014 Symphony cross-reference との整合 (ticket board = control plane)

## 残リスク

- **UI scope creep**: 4 面 + Plan Mode + dashboard を 6/9 day で収めにくい → 9 day で must_ship のみ完遂、業務価値 dashboard は defer
- **frontend telemetry KPI 化 regression**: code review で「KPI source-of-truth は DB / audit_events 不変」を必ず確認
- **invariant 破壊**: status enum / blocked_reason / approval decider human-only の 3 invariant を破る PR は即 reject
- **Execution Log secret leak**: redaction 後 hash のみ表示、`assert_no_raw_secret` を frontend response にも適用

## 次スプリント候補

- Sprint 10 (Eval Harness): 業務価値 dashboard の KPI metric を eval harness で算出
- Sprint 11.5 (Observability): 技術監視 dashboard (p95 / queue / error rate) を Grafana で実装
- Sprint 12 (P0 Acceptance): UI を含めた P0 全体 acceptance verify
- P0.1 SP-016 (UI/CLI parity): UI と CLI で同 operation を提供
- P0.1 SP-017 (AI Society Visualization): inter-agent timeline + role dashboard 追加

## 関連 ADR / Sprint Pack / Doc

- ADR-00001 (auth/rbac) - dev login + actor binding
- ADR-00003 (api contract) - FastAPI + OpenAPI + Pydantic
- ADR-00004 (AgentRun state machine) - 16 状態 + blocked_reason
- ADR-00009 (action_class taxonomy) - 7 種 + Approval UI
- ADR-00014 (Multi-agent orchestration) - 10 role + Symphony cross-reference (§外部参照モデル)
- ADR-00015 (UI/CLI parity) - P0.1 で UI と CLI を同等化
- SP-003 (Policy / Approval) - Approval API
- SP-004 (Agent Runtime) - AgentRun + AgentRunEvent
- SP-005-5 (Output Validator) - 現在進行、trust_level / repair retry
- SP-008 (GitHub App + RepoProxy) - Draft PR flow
- SP-010 (Eval Harness) - 業務価値 KPI metric
- SP-011.5 (Observability) - 技術監視 dashboard
- AI-UIUX レポート: `docs/設計検討/AI統合タスク管理プラットフォームの最新UIUXと実装選定レポート.md`
- 統合結論: `docs/設計検討/2026-05-12_external_ai_concept_uiux_integration.md`

## Review (Sprint 9 完了後追記)

- changed: <実際に変えたこと>
- verified: <確認したこと>
- deferred: <後回しにしたこと>
- risks: <残ったリスク>
