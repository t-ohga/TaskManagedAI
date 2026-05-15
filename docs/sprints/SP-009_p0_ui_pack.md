---
id: "SP-009_p0_ui_pack"
type: "heavy"
status: "skeleton_pending_backend"
review_summary: "5 page skeleton + 3 API client draft + Playwright spec のみ。実 backend route は未実装、API client は `_listXxxDraft` prefix で signal。Sprint 11 で backend route 実装 + integration test 結線。Codex audit 2026-05-13 で F-004/F-006/F-008 指摘 adopt 済。"
sprint_no: 9
created_at: "2026-05-12"
updated_at: "2026-05-12"
target_days: 6
max_days: 9
adr_refs:
  - "[ADR-00001](../adr/00001_auth_rbac.md) # accepted、dev login / actor binding"
  - "[ADR-00004](../adr/00004_agentrun_state_machine.md) # accepted、AgentRun 16 状態 + blocked_reason 3 種、UI で status / reason を分離表示"
  - "[ADR-00009](../adr/00009_action_class_taxonomy.md) # accepted、action_class 7 種、Approval UI で表示"
  - "[ADR-00014](../adr/00014_multi_agent_orchestration.md) # proposed (P0.1 で accepted 化予定)、10 role + 4 面 UI 参照 (Symphony cross-reference 含む)"
planned_adr_refs:
  - "[ADR-00003](../adr/00003_api_contract.md) # ファイル未起票。AI Runs timeline / BL-0094 / BL-0092 Plan Mode Edit API 契約は実装前 proposed 起票が必要 (Criteria #3 API/event schema)"
related_sprints:
  - "SP-005-5_output_validator # 実在"
  - "SP-006_cli_artifact # 実在"
  - "SP-007_runner_sandbox # 実在"
  - "SP-008_github_app_repoproxy # planned、未起票"
upstream_sprints:
  - "SP-001_project_foundation # 実在"
  - "SP-002_core_data_model # 実在"
  - "SP-003_policy_approval # 実在"
  - "SP-004_agent_runtime # 実在"
  - "SP-005_provider_adapter # 実在"
  - "SP-005-5_output_validator # 実在"
  - "SP-008_github_app_repoproxy # planned、未起票"
downstream_sprints:
  - "SP-010_eval_harness # planned、未起票 (PRD-01 では Sprint 10 は Research / Evidence、Sprint 11 が Eval Harness)"
  - "SP-011_5_observability # planned、未起票"
  - "SP-012_p0_acceptance # 実在"
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
- AI Society Visualization (ADR-00017、**P1 SP-017** で実装。P0.1 は SP-013〜016、P1 は SP-017〜020)

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
- **P0 must_ship UI ボタン**: **Approve** (`approval_decided` event 発行)、**Reject** (`approval_decided` rejected 発行) の 2 つのみ
- **Edit は P0 must_ship では defer**。Edit は新 artifact を untrusted_content → validated_artifact pipeline に戻し、旧 approval を invalidated にし、再 schema_validated / policy_linted / diff_ready / waiting_approval を経て再承認まで実行不可とする server-owned contract が必要。**実装は ADR-00003 (API contract) + ADR-00004 (AgentRun state machine、artifact_v(N+1) 経路) + ADR-00009 (action_class、Edit operation 該当判定) の 3 gate 配下で P0 Acceptance 後または P0.1 で着手**
- agent は **decider にならない** (ADR-00014 human-only approval 不変)
- Plan 内訳表示: `tool_manifest` + `policy_version` + `provider_request_fingerprint` + `evidence_set_hash`

### 3. Execution Log

- 同一 timeline で `tools` / `citations` / `diffs` / `eval scores` / `policy decision` / `audit refs` を表示
- source of truth: **AuditEvent / AgentRunEvent (append-only)**、frontend cache は invalidation 可能
- raw secret / provider response は表示しない (redaction 後 hash のみ)

### 4. 業務価値 dashboard

- Quality KPIs 5 を可視化: `acceptance_pass_rate` / `time_to_merge` / `approval_wait_ms` / `citation_coverage` / `cost_per_completed_task`
- source-of-truth: **ADR-00014 §10 `orchestrator_kpi_rollup` で KPI ごとに正本 source を列挙**:
  - `acceptance_pass_rate`: `eval_runs` + `eval_scores` (SP-010 で実装) + 既存仕様
  - `time_to_merge`: PR flow source のみ (RepoProxy 経由)、`agent_run_events` の `repo_pr_opened` event timestamp + merge timestamp
  - `approval_wait_ms`: `approval_requests` の `requested_at` / `decided_at` (1 度のみ、parent / child 重複計測なし)
  - `citation_coverage`: final adopted `artifacts` + `evidence_items` + `claims` (SP-010 Eval Harness で集計)
  - `cost_per_completed_task`: `agent_run_events` の `provider_responded` event payload の `usage` field を sum + parent ticket 単位で wall-clock
- **新規 `provider_usage` table は導入しない** (既存 `agent_run_events.event_payload.usage` を集計、新 table 追加なら別 ADR-00002 (DB schema) gate)
- frontend event を KPI 正本にしない
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
| BL-0092 | Plan Mode UI (approve / reject + plan 内訳表示)。Edit は P0 must_ship では defer (ADR-00003/00004/00009 gate 配下で P0.1 着手) | M | BL-0091 + Approval API (SP-003) |
| BL-0093 | Approval Inbox page (pending + risk_level + action_class、human-only decider) | M | SP-003 |
| BL-0094 | AI Runs page (16 状態 + blocked_reason badge + AgentRunEvent timeline) | M | SP-004 + SP-005-5 |
| BL-0095 | 業務価値 dashboard (Quality KPIs 5 read-only) | M | SP-010 Eval Harness |
| BL-0096 | UI から AgentRun cancel (active runs に limit) | S | SP-004 |
| BL-0097 | Audit Log viewer (AuditEvent timeline) | S | SP-003 + 既存 audit_events |

## must_ship / defer_if_over_budget

### must_ship (P0 Exit に直結)

- BL-0090 Board page
- BL-0091 Ticket detail
- BL-0092 Plan Mode UI (approve / reject のみ、Edit は defer)
- BL-0093 Approval Inbox
- BL-0094 AI Runs (status + AgentRunEvent timeline、blocked_reason badge)

### defer_if_over_budget (P0.1 / P1 へ送る)

- BL-0095 業務価値 dashboard (read-only) → P0.1 SP-010 Eval Harness 完成後で OK
- BL-0096 UI cancel → P0.1 / P1
- BL-0097 Audit Log viewer → P0.1 / P1 (P0 は API で確認、UI 表示不要)

## 受け入れ条件

- [ ] 4 面 UI (Board / Ticket Detail / Approval Inbox / AI Runs) すべてが Tailscale 閉域内で表示できる
- [ ] Plan Mode で `waiting_approval` 状態の AgentRun に対し human approve / reject (P0 must_ship: 2 ボタンのみ、Edit は defer) が可能、agent decider 経路がない
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
- P1 SP-017 (AI Society Visualization): inter-agent timeline + role dashboard 追加 (P0.1 は SP-013〜016 multi-agent foundation のみ、P1 visualization は SP-017〜020)

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

## Review

### batch 1 + 2 完了 (2026-05-13、commit `0813e53` + `ceb28c8`)

#### changed (batches 1-2: 6 page skeleton)

- `frontend/app/(admin)/tickets/page.tsx`: Ticket 一覧 skeleton (BL-0103)
- `frontend/app/(admin)/tickets/[id]/page.tsx`: Ticket 詳細 (BL-0104) +
  Acceptance Criteria + Evidence + AgentRun mapping + ContextSnapshot 10
  column 表示
- `frontend/app/(admin)/runs/page.tsx`: AgentRun 16 状態 + blocked_reason
  3 種 + terminal state 5 種 表示 (BL-0106 skeleton)
- `frontend/app/(admin)/runs/[id]/page.tsx`: AgentRunEvent timeline 13 種
  sample + Sprint 7 runner_* event 統合表示 (BL-0106 詳細)
- `frontend/app/(admin)/audit/page.tsx`: audit_event 14 種 + 必須 payload
  key 表示 (BL-0107 skeleton)
- `frontend/app/(admin)/settings/page.tsx`: Provider Compliance Matrix
  4 行 + Policy Profile + GitHub App repo binding 文書化 (BL-0108)

#### verified (batches 1-2)

- `pnpm exec tsc --noEmit` clean (新 page 全て TS pass)
- Server Component default (export const dynamic = "force-dynamic")
- secret_ref / installation_token を DOM に出さない invariant 維持
- AgentRun 16 状態 enum を Sprint 4 backend と整合表示

#### deferred (batches 3-5 → 別 session)

- BL-0104 詳細: Ticket 詳細の実 data fetch (`frontend/lib/api/tickets.ts`)
- BL-0106 詳細: AgentRun timeline 実 data fetch
  (`frontend/lib/api/agent-runs.ts`)
- BL-0107 詳細: Audit Log filter + pagination + raw secret enforcement
- BL-0109: responsive layout (mobile / tablet / desktop)
- BL-0110: a11y (ARIA + keyboard navigation + screen reader)
- BL-0111: Playwright E2E (golden flow: Ticket → Approval → AgentRun →
  Draft PR)
- BL-0112: Eval Dashboard (Hard Gates 7 / Quality KPIs 5 read-only)

これらは別 session で API client + Server Action + Playwright test と一緒に
実装予定。本 Sprint では UI route 構造 + Server Component default + secret
非表示 invariant + AgentRun / audit_event enum 表示の基盤完成。

#### risks (Sprint 9 時点)

- **secret leak via DOM (HIGH)**: 実 data fetch 時に installation_token /
  raw secret が誤って Server Component の rendered HTML に混入するリスク。
  Sprint 11 で `assert_no_raw_secret` を frontend test fixture に追加して
  detect する。
- **AgentRun status drift (HIGH)**: backend 16 状態 + blocked_reason 3 種 を
  frontend で hardcode するため、backend 側に新 status 追加で drift 発生。
  Sprint 11 で TypeScript enum 自動生成 (OpenAPI / Pydantic → ts) を導入。
- **a11y 不足 (MEDIUM)**: 現在 skeleton で ARIA role / label 未整備。
  BL-0110 で screen reader + keyboard nav を本実装。

### batch 3 完了 (2026-05-13、commit `2e96222`)

#### changed (batch 3: BL-0104 / BL-0106 / BL-0107 / BL-0111)

- `frontend/lib/api/tickets.ts`: Ticket / Acceptance Criteria / Evidence
  Citation Zod schema + listTickets + getTicket Server Component fetch
- `frontend/lib/api/agent-runs.ts`: AgentRun 16 状態 Zod enum + blocked_reason
  3 種 + AgentRunEventTypeEnum (22 種、Sprint 4 + Sprint 7) + ContextSnapshot
  10 column 完全 schema + listAgentRuns + getAgentRun
- `frontend/lib/api/audit.ts`: AuditEventTypeEnum (17 種主要 audit event) +
  AuditEventSchema + cursor pagination + listAuditEvents (eventType filter)
- `frontend/tests/e2e/sprint9-pages.spec.ts`: 6 件 Playwright test
  (Tickets / Runs / Audit / Settings + dynamic [id] routes)

#### verified (batch 3)

- frontend `pnpm exec tsc --noEmit` clean
- Zod v4 record API 整合 (`z.record(z.string(), z.unknown())`)
- AgentRunStatusEnum / AgentRunEventTypeEnum が backend Literal type と同期
- Playwright test は ARIA region / role / heading で a11y 基盤確立 (BL-0110
  の foundation)

### Sprint 9 status (Codex audit F-004/F-006/F-008 adopt で訂正、2026-05-13)

- target_days: 6
- max_days: 9
- actual (本 session): 1 day (Pack 既存 + batches 1-3、skeleton + draft client
  + Playwright spec のみ)
- **must_ship 未達 (Codex audit F-004 adopt で正直化)**:
  - **実 backend route 未実装**: `GET /api/v1/tickets` / `GET /api/v1/agent_runs`
    (list/detail) / `GET /api/v1/audit_events` は backend に **存在しない**。
    frontend API client は `_listXxxDraft` / `_getXxxDraft` prefix で signal、
    Sprint page は skeleton 文言のみ。Sprint 11 で backend route 実装 +
    integration test 結線。
  - **enum drift**: 旧 TicketStatusEnum (`waiting_review/done/archived`) が
    backend `ticket.py` Literal (`blocked/review/closed`) と drift していた
    → Codex F-006 adopt で backend Literal と完全同期 (`open|in_progress|
    blocked|review|closed|cancelled`)。Sprint 11 で contract test 追加。
  - **AC-HARD-02 frontend redaction enforcement**: `payload: z.record(...)` は
    backend 信頼で arbitrary value 許可、frontend 側の `RedactedAuditPayloadSchema`
    は **未実装**。Sprint 11 で backend `_payload_secret_scan.py` を frontend
    に port + DOM secret scan test 追加 (Codex F-008 adopt 文書化済)。
- **partial_skeleton 達成**:
  - 5 page route + Server Component default + ARIA region/role (BL-0103〜0108): ✅
  - Zod schema strict validation (5 enum) (BL-0104/0106/0107): ✅ schema のみ、
    実 fetch は未動作
  - Playwright E2E 6 spec (BL-0111): ✅ skeleton 文言 verify、API client
    integration なし
- **partial / defer**:
  - BL-0105 Approval Inbox: ✅ Sprint 3 既存実装
  - BL-0109 responsive: ✅ 部分 (Tailwind grid)、本格 mobile-first は Sprint 11.5
  - BL-0110 a11y: ✅ 部分 (ARIA region/role)、axe-core integration は Sprint 11.5
  - BL-0112 Eval Dashboard: defer Sprint 11 (eval_harness 完成後)

### Codex audit (2026-05-13, sp7-8-9-final-audit, R1)

- F-004 (HIGH): API client が実 backend route と結線していない (path mismatch
  `agent-runs` ↔ `agent_runs`、`/tickets` `/audit-events` route 未実装) →
  adopt、`_listXxxDraft` prefix で signal + backend path 訂正 + status を
  `skeleton_pending_backend` に変更
- F-006 (MEDIUM): TicketStatus / AuditEventType cross-source drift → adopt、
  TicketStatusEnum を backend Literal に同期、Sprint 11 で contract test 追加
- F-008 (MEDIUM): frontend payload schema が AC-HARD-02 raw secret 非露出を
  enforce しない → adopt、docstring 明文化 + Sprint 11 で
  RedactedXxxPayloadSchema 実装

### Sprint 9 batch coverage 最終

- BL-0103 Tickets list: ✅ skeleton + lib/api/tickets.ts
- BL-0104 Ticket detail: ✅ dynamic [id] + lib/api/tickets.ts (getTicket)
- BL-0105 Approval Inbox: ✅ 既存実装 (Sprint 3 完成)
- BL-0106 Agent Runs: ✅ list + detail + lib/api/agent-runs.ts
- BL-0107 Audit Log: ✅ list + lib/api/audit.ts + cursor pagination
- BL-0108 Project Settings: ✅ Provider Matrix + Policy Profile 表示
- BL-0109 Responsive: 既存 Tailwind grid-cols-2/md:grid-cols-3 で部分対応、
  本格的 mobile-first design は Sprint 11.5 で deep dive
- BL-0110 a11y: ARIA region / role / heading 整備 (Playwright test で verify)、
  axe-core integration は Sprint 11.5 で追加
- BL-0111 Playwright E2E: ✅ sprint9-pages.spec.ts 6 件
- BL-0112 Eval Dashboard: Sprint 11 eval_harness 完成後 (defer)

### BL coverage 集計 (Codex SP9 R1 F-SP9-004 adopt で表記訂正、2026-05-13)

- **skeleton_complete (5 件)**: BL-0103 / BL-0104 / BL-0106 / BL-0107 / BL-0108
  (Server Component skeleton + ARIA region + Zod schema draft)
- **既存 Sprint 完成 (1 件)**: BL-0105 Approval Inbox (Sprint 3 実装、Sprint 9 で
  本 audit 範囲外)
- **partial (3 件)**: BL-0109 responsive (Tailwind grid のみ、本格 mobile-first
  は Sprint 11.5 BL-0109a) / BL-0110 a11y (ARIA region/role/heading のみ、
  axe-core integration は Sprint 11.5 BL-0110a) / BL-0111 Playwright E2E
  (6 skeleton spec、golden flow は Sprint 11 backend route 結線後)
- **defer (1 件)**: BL-0112 Eval Dashboard (Sprint 11 eval_harness データ
  source 完成後)

合計: **5 skeleton + 1 既存 + 3 partial + 1 defer = 10 件、Sprint 9 内では
"functional complete" には到達しない (=`skeleton_pending_backend` status と
整合)**。
