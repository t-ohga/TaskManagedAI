---
id: DESIGN-QL-PRODUCT-ARTIFACT
title: "Quality Loop Product Artifact 設計 (6 種 artifact + review_result schema + defer structured state + AgentRun.status 物理分離)"
type: design_doc
status: proposed
revision: R0
created_at: "2026-05-15"
updated_at: "2026-05-15"
source_plan_section: "docs/設計検討/修正まとめ統合計画.md §5 QL-D + §3.1 A-12 + §3.1 A-15 + §3.2 P-08"
landing_sprint: "SP-023 候補 (P0.1、未起票、修正まとめ統合計画 §10.4/§12 で正式予約済)"
adr_gate_criteria_trigger:
  - "#2 DB schema (本 design doc 自体は doc-only、schema 化は SP-023 候補で別 ADR + Sprint Pack 経由)"
  - "#3 API 契約 / event schema (P0.1 で event_type 拡張時に再 trigger)"
related_documents:
  - "../基本設計/03_AIオーケストレーション設計.md §13.3 (QL-B Quality Loop status 物理分離宣言) + §14 (QL-D Quality Loop artifact concept)"
  - "../基本設計/07_可観測性設計.md §14 (QL-D Quality Loop observability)"
  - "../sprints/SP-012_p0_acceptance.md §QL-D update (open finding zero gate + harness incident zero gate acceptance spec)"
  - "../設計検討/phase-c-multi-agent-spec-draft.md §3.3 review_artifacts table (agent-level review verdict、本 doc の Quality Loop artifact とは別 concept、物理分離)"
  - "../設計検討/修正まとめ統合計画.md §5 QL-D + §3.1 A-12/A-15 + §3.2 P-08 (R29 plan source)"
risks:
  - "Quality Loop lifecycle vocabulary が AgentRun.status enum (16 状態) に混入 (T-011 再発)"
  - "Phase C `review_artifacts` table (agent reviewer verdict) と naming 衝突"
  - "Sprint Pack の Pending entries 表記が structured state なしの自由文で drift 発生"
---

# Quality Loop Product Artifact 設計

## 0. このドキュメントの扱い

**doc-only design proposal**。本ドキュメント自体は実装許可ではない。Quality Loop product artifact の DB schema / API / event schema 実装は SP-023 候補 (P0.1) accepted 後の別 run で行う。

本 design doc は:

- 修正まとめ統合計画 §5 QL-D の write scope (`docs/基本設計/03_AIオーケストレーション設計.md` §14 + `docs/基本設計/07_可観測性設計.md` §14 + `docs/sprints/SP-012_p0_acceptance.md` §QL-D update + 本 design doc) の core spec
- §3.1 A-12 (open finding / harness incident clean evidence gate) + §3.1 A-15 (`defer` structured state) + §3.2 P-08 (Quality Loop product artifact 6 種) を統合した artifact schema design
- **AgentRun.status (16 状態) と Quality Loop lifecycle vocabulary の物理分離宣言**
- Phase C `review_artifacts` table (agent reviewer verdict、`pass/fail/needs_revision`) との naming clash を避けるための concept 分離

## 1. 不変条件 (本 design で破ってはならない)

| # | 不変条件 | 根拠 rule |
|---:|---|---|
| 1 | AgentRun.status enum **16 状態** (`queued` / `gathering_context` / `running` / `generated_artifact` / `schema_validated` / `policy_linted` / `diff_ready` / `waiting_approval` / `blocked` / `provider_refused` / `provider_incomplete` / `validation_failed` / `repair_exhausted` / `completed` / `failed` / `cancelled`) に Quality Loop vocabulary を追加しない | `.claude/rules/agentrun-state-machine.md §1` (16 状態固定) + `.claude/rules/cross-source-enum-integrity.md §1` (5+ source 整合) |
| 2 | `blocked_reason` 3 種 (`policy_blocked` / `budget_blocked` / `runtime_blocked`) を拡張しない | `.claude/rules/agentrun-state-machine.md §2` |
| 3 | Quality Loop lifecycle は **別 enum + 別 table** で表現、AgentRun.status と物理分離 | T-011 mitigation、本 design doc §3 |
| 4 | `defer` structured state は **owner / impact / resume_condition / blocked_by / verification** の 5 field 必須 | §3.2 A-15 + 本 design doc §4 |
| 5 | review_result schema は **agent-level `review_artifacts` (Phase C) と物理分離**、Quality Loop の review_result は Sprint Pack lifecycle artifact | phase-c-multi-agent-spec-draft.md §3.3 + 本 design doc §5 |
| 6 | open finding / unresolved harness incident のまま `clean evidence` 不可 | `.claude/rules/sprint-pack-adr-gate.md §131-142` (Sprint Pack Review DoD) + `.claude/rules/plan-review.md §122-128` |
| 7 | 本 design doc 自体は doc-only、DB schema / API / event schema 実装は SP-023 候補 accepted 後の別 run | `修正まとめ統合計画 §8 doc-only gate` |
| 8 | P0 期間中 (SP-023 未実装) は `conformance` artifact 発行は **non-blocking future gate**、SP-012 P0 Exit acceptance は **既存 Sprint Pack `## Review` 自由文 evidence + Hard Gates 7 + Quality KPIs 5 計測** で OK。structured `conformance` artifact 発行を P0 Exit の mandatory prerequisite にしない (F-PR13-001 P1 adopt 反映) | `docs/設計検討/修正まとめ統合計画.md §8 doc-only gate` + 本 design doc §7 |

## 2. Quality Loop product artifact 6 種

修正まとめ統合計画 §3.2 P-08 で提案された 6 種 artifact を Quality Loop lifecycle の structured representation として doc 化する。各 artifact は **Sprint Pack 単位** の lifecycle event を表現し、AgentRun (個別 run) とは別 layer で扱う。

| artifact kind | 目的 | 主要 field | 状態遷移先 |
|---|---|---|---|
| `plan` | Sprint Pack 着手前の計画 artifact (Sprint Pack heavy の `## 設計判断` `## 実装チケット` `## must_ship / defer` 等を structured 化) | `sprint_pack_id` / `plan_version` / `must_ship_items[]` / `defer_items[]` / `adr_refs[]` / `risks[]` / `verification_steps[]` / `target_days` / `max_days` | `review` (Codex / Claude / human が plan review 着手) |
| `review` | 計画 review artifact (Codex plan-review / Claude plan-reviewer agent の verdict) | `reviewed_plan_id` / `reviewer_actor_id` / `reviewer_kind` (codex / claude / human) / `verdict` (clean / needs_revision / blocked) / `findings[]` (severity / category / file:line / quote / suggestion) / `round_no` | `revision` (review に基づく plan 修正) or `plan→implementation` (clean 判定で実装着手) |
| `revision` | review 反映後の plan/code revision artifact (Codex multi-round の adopt/reject/defer 結果を structured 化) | `source_review_id` / `revised_artifact_id` (新 plan or code artifact) / `adoption_decisions[]` (finding_id / decision: `adopt/reject/defer` / rationale) / `revision_commit_sha` (code revision の場合) | `rereview` (Codex review 再 trigger) |
| `rereview` | revision 後の re-review artifact (Codex multi-round の R2/R3/... を structured 化) | `revision_id` / `reviewer_actor_id` / `verdict` / `findings[]` / `round_no` (R2 / R3 等) / `previous_review_id` | `revision` (まだ findings あり) or `conformance` (clean 達成) |
| `conformance` | Sprint Pack 完了時の conformance artifact (must_ship 達成 + defer 移送 + Sprint Exit Review) | `sprint_pack_id` / `must_ship_pass_count` / `must_ship_total` / `defer_to_next_sprint[]` / `hard_gates_pass[]` / `quality_kpis_pass[]` / `final_verdict` (pass / partial / blocked) / `sprint_exit_at` | (terminal、Sprint Pack closed) |
| `harness_incident` | Quality Loop runtime 中の harness incident (Codex rate limit / 100 bytes 未満 応答 / logical failure / Claude tool error 等) | `incident_kind` (`codex_rate_limit` / `codex_logical_failure` / `codex_truncation` / `claude_tool_error` / `ci_flake` / その他) / `incident_at` / `source_artifact_id` (incident 発生時の artifact) / `recovery_action` (`retry` / `skip` / `manual_resolution` / `abort`) / `resolved_at` (terminal not required、open のままも可) | (terminal optional、resume 可能) |

### 2.1 状態遷移の物理分離

AgentRun.status (16 状態) と Quality Loop artifact lifecycle (上記 6 kind) は **完全に別 layer**:

```
AgentRun lifecycle (per-run、§1 #1 invariant):
  queued → gathering_context → running → generated_artifact → schema_validated → policy_linted → diff_ready → waiting_approval → completed/failed/cancelled/blocked/provider_refused/provider_incomplete/validation_failed/repair_exhausted

Quality Loop lifecycle (per-sprint-pack、本 design doc):
  plan → review → revision → rereview (loop until clean) → conformance (Sprint Exit)
  + 任意の point で harness_incident artifact 発生可能 (parallel layer)
```

これらの 2 layer は **別 table + 別 enum + 別 event_type** で表現する。AgentRun.status enum への Quality Loop vocabulary 追加は invariant #1/#2 違反として reject。

### 2.2 audit ledger との整合

各 artifact 作成 / 状態遷移は **audit_events table** に append-only event として記録する (raw secret 除外、`.claude/rules/secretbroker-boundary.md §11` 準拠):

- `quality_loop_plan_created` / `quality_loop_review_created` / `quality_loop_revision_created` / `quality_loop_rereview_created` / `quality_loop_conformance_created` / `quality_loop_harness_incident_recorded`
- 各 event payload: `tenant_id` / `actor_id` / `sprint_pack_id` / `artifact_kind` / `artifact_id` / `correlation_id` / `trace_id` / `timestamp`

event_type 拡張は P0.1 (SP-023 候補) で実施、現状 (P0) は `audit_events.event_type` enum に追加しない。本 design doc は doc-only。

## 3. AgentRun.status 物理分離宣言

Quality Loop lifecycle と AgentRun.status の **vocabulary 物理分離** は本 design doc の core invariant:

### 3.1 禁止: AgentRun.status enum 拡張

以下の vocabulary を AgentRun.status enum / `blocked_reason` 3 種に **追加してはならない**:

- `quality_loop_planning` / `quality_loop_reviewing` / `quality_loop_revising` / `quality_loop_rereviewing` / `quality_loop_clean` / `quality_loop_harness_incident`
- 他、Quality Loop lifecycle 関連の任意 vocabulary

これらは Quality Loop artifact 側の `artifact_kind` enum (本 design doc §2) で表現する。

### 3.2 推奨: harness incident と AgentRun.failed の分離

開発時の harness incident (例: codex review loop 中の logical failure / rate limit / 100 bytes 未満 応答) は **AgentRun.status=failed ではなく** `quality_loop_harness_incident` artifact で記録する:

- AgentRun が provider call で 100 bytes 未満 応答を受けた場合: AgentRun.status は `provider_incomplete` (16 状態内、retry/resume 可能)
- Quality Loop level での incident (Codex skill 全体の失敗 / Claude tool error 等): `quality_loop_harness_incident` artifact (Sprint Pack lifecycle layer)

### 3.3 5+ source 整合への影響

AgentRun.status 16 状態の 5+ source 整合 (`.claude/rules/cross-source-enum-integrity.md §1`) は本 design doc で影響を受けない (vocabulary 追加なし)。Quality Loop artifact_kind 6 種の 5+ source 整合は **P0.1 SP-023 候補で別途実装** (本 design doc では doc-only spec のみ)。

## 4. defer structured state schema (A-15 反映)

Sprint Pack の `## 残リスク` / `## 次スプリント候補` / `## defer_if_over_budget` 列で使われる「`defer`」を **structured state** として表現する。現状は自由文で drift しやすいため、本 design doc で必須 5 field を定義する:

```yaml
defer_entry:
  defer_id: string (e.g., "DEFER-SP-005-001")
  owner: actor_id (defer 判定の責任 actor、`actors.id` UUID、human or agent)
  impact: text (defer による影響範囲、Sprint Exit / acceptance / KPI への影響を明示)
  resume_condition: text (defer 解除条件、accepted ADR / 次 Sprint Pack accepted / dependency resolved 等)
  blocked_by: [string] (defer 解除 blocker 一覧、ADR id / Sprint Pack id / external dependency)
  verification: text (defer 解除時の verification 手順、acceptance spec へ trace)
  created_at: timestamp
  resumed_at: timestamp nullable (defer 解除日)
```

### 4.1 既存自由文 defer entry の migration

現状 Sprint Pack の自由文 defer entry は P0.1 SP-023 候補で structured state に migration:

- 各 defer entry に `defer_id` を assign
- `owner` / `impact` / `resume_condition` / `blocked_by` / `verification` を Sprint Pack reviewer が抽出
- Sprint Pack の `## 残リスク` section を `### defer_entries` (structured) と `### residual_risks` (自由文 narrative) に分離

本 run では doc-only spec のみ、Sprint Pack 自身の structured 化は SP-023 候補 accepted 後。

### 4.2 Pending entries 表記との関係

SP-012_p0_acceptance.md `## Review §Pending entries` 等で使われる「Pending」表記は `defer_entry` の `defer_id` で trace 可能。現状は自由文だが、SP-023 候補で structured 化する future implementation gate。

## 5. review_result schema (Quality Loop level、agent-level review_artifacts と物理分離)

phase-c-multi-agent-spec-draft.md §3.3 で定義された `review_artifacts` table は **agent reviewer verdict** (`pass/fail/needs_revision`) であり、Quality Loop の review artifact (本 design doc §2 の `review` / `rereview` kind) とは **別 concept**:

| 観点 | Phase C `review_artifacts` (agent-level) | Quality Loop `review` / `rereview` artifact (本 design doc) |
|---|---|---|
| scope | AgentRun 内の agent reviewer (orchestrator / reviewer agent) の verdict | Sprint Pack lifecycle の review event (Codex plan-review / Claude plan-reviewer agent / human review) |
| verdict 語彙 | `pass` / `fail` / `needs_revision` | `clean` / `needs_revision` / `blocked` |
| 関連 table | `review_artifacts` (Phase C で proposed) | Quality Loop artifact table (本 design doc で proposed、SP-023 候補で実装) |
| approval との関係 | reviewer は requester、approver は別 human actor (decider human-only) | Quality Loop level の review は plan/code revision を trigger、approval とは別 layer |
| 状態遷移 | review_artifact 単発 | review → revision → rereview → conformance (loop until clean) |

両者は table 名 / enum / event_type を物理分離する。Quality Loop review artifact が agent-level `review_artifacts.verdict` を直接参照する path は P0.1 SP-023 候補で慎重に設計 (cross-reference は許可、混在は禁止)。

### 5.1 Quality Loop review_result 必須 field

```yaml
quality_loop_review:
  review_id: uuid
  reviewed_plan_id: uuid (target Quality Loop artifact)
  reviewer_actor_id: actor_id (reviewer の actor、human / agent)
  reviewer_kind: enum {codex_plan_review, codex_adversarial_review, claude_plan_reviewer, claude_code_reviewer, human_review}
  verdict: enum {clean, needs_revision, blocked}
  findings: [
    {
      finding_id: string (e.g., "F-PR12-R1-001"),
      severity: enum {P0, P1, P2, P3, info},
      category: enum {invariant_violation, schema_drift, security_boundary, performance, wording, other},
      file_path: string nullable (inline finding の場合),
      line_no: int nullable,
      evidence_quote: text (file:line の該当部分の引用、Codex finding の `body` から抽出),
      suggestion: text,
      adoption_decision: enum {adopt, reject, defer} nullable (revision artifact 作成時に記録),
      adoption_rationale: text nullable
    }
  ]
  round_no: int (R1, R2, R3, ...)
  previous_review_id: uuid nullable (R2 以降、前 round の review)
  created_at: timestamp
  cleaned_at: timestamp nullable (verdict=clean 達成日)
```

### 5.2 finding adoption decision の structured 化

`adoption_decision` 列で `adopt / reject / defer` を structured 化することで、Sprint Pack review の閉じ込み度を機械的に集計可能:

- `adoption_pass_rate`: per-Sprint-Pack 単位での `adopt` 比率
- `defer_carry_over`: 各 round で `defer` 判定された finding の Sprint 間移送 trace
- `reject_count_by_round`: round ごとの reject 件数推移 (Codex 誤読率 proxy)

これらは P0.1 SP-023 候補で metrics として実装。

## 6. open finding zero gate / harness incident zero gate (A-12 反映、Sprint Exit 条件)

Sprint Pack の Sprint Exit / acceptance 判定で、open finding が残っているまま `clean evidence` を発行することは invariant #6 違反:

### 6.1 open finding zero gate (F-PR13-002 P1 adopt 反映: latest chain + adoption_decision で gate)

Sprint Pack の `conformance` artifact (本 design doc §2) を発行する条件:

- 該当 Sprint Pack の **最新 review chain (= `revision` linked to current artifact の `review` / `rereview`) の `verdict='clean'`** (findings: [] または `P3` または `info` のみで explicit accept) **OR** 全 finding に `adoption_decision` (adopt / reject / defer) が記録済 (R1 = `verdict='needs_revision'` でも、R2 / R3 で全 finding が adopt/reject/defer 判定されていれば gate 通過 OK、historical R1/R2 の `verdict='needs_revision'` artifact は append-only history として保持、gate 対象外)
- `defer_entry` で `verification` 列が記入済 (`P3` または `info` finding を `defer` する場合)
- `must_ship_items[]` 全件達成 (`must_ship_pass_count == must_ship_total`)
- `hard_gates_pass[]` 全件 PASS (AC-HARD-01〜07 全件)
- `quality_kpis_pass[]` 未達 1 個以下 (AC-KPI-01〜05、`.claude/CLAUDE.md §2` Hard Gates 7 / Quality KPIs 5 準拠)

これらいずれか 1 つでも未達なら `conformance.final_verdict='partial'` または `'blocked'`、Sprint Exit を block。

**P0 期間中 (SP-023 未実装) の運用** (F-PR13-001 P1 adopt 反映): `conformance` artifact 自体は SP-023 候補 (P0.1) で実装されるため、P0 期間中の SP-012 P0 Exit acceptance は **non-blocking future gate** として扱う:

- P0 期間中の Sprint Exit acceptance は **既存 Sprint Pack `## Review` 自由文 evidence + Hard Gates 7 + Quality KPIs 5 計測** で OK
- structured `conformance` artifact 発行は **P0.1 SP-023 candidate accepted 後の Sprint Exit から mandatory 化**、それまでは optional
- P0 acceptance を block するのは Hard Gates 7 / Quality KPIs 5 / `## 受け入れ条件` の自由文 evidence のみ。本 design doc の structured gate は **未実装である限り P0 acceptance gate を block しない**

### 6.2 harness incident zero gate

Sprint Pack の Sprint Exit 時点で `quality_loop_harness_incident` artifact のうち **`resolved_at` が null** の row が残っているなら、Sprint Exit を block:

- harness incident の `recovery_action` が `manual_resolution` でまだ解決していない → `conformance.final_verdict='blocked'`
- harness incident が `abort` で解決済 → Sprint Pack `## 残リスク` に `defer_entry` で migration して `resolved_at` 記入

これにより、open harness incident (Codex 失敗 / Claude tool error) を放置したまま Sprint Exit 宣言する経路を fail-closed で防ぐ。

### 6.3 clean evidence の verification (F-PR13-002 P1 adopt 反映)

`conformance` artifact 発行時の verification 手順:

1. **最新 review chain (= `revision` linked to current artifact の `review` / `rereview`) の `verdict='clean'`** を確認 **OR** 全 finding に `adoption_decision` (adopt / reject / defer) 記録済を確認 (historical R1/R2 の `verdict='needs_revision'` artifact は append-only history として保持、gate 対象外)
2. 全 `defer_entry.resume_condition` が記入済 + `verification` が記入済を確認
3. 全 `must_ship_items[]` の `## 受け入れ条件` PASS を確認
4. 全 `hard_gates_pass[]` の `pytest` / 各 hard gate runner PASS を確認
5. 全 `quality_kpis_pass[]` の metric 計測結果が閾値内 (未達 1 個以下)
6. 全 `quality_loop_harness_incident.resolved_at` が NOT NULL or `defer_entry` 移送済

これら 6 step 全 PASS で `conformance.final_verdict='pass'`、Sprint Pack closed。

## 7. P0.1 SP-023 候補での実装計画 (本 design doc accepted 後)

本 design doc 自体は doc-only。実装は SP-023 候補 (P0.1) accepted 後の別 run で:

- DB schema: `quality_loop_artifacts` table 新規、`quality_loop_reviews` table 新規、`quality_loop_defer_entries` table 新規 (ADR Gate Criteria #2 trigger)
- API: `/api/quality-loop/plans/*`、`/api/quality-loop/reviews/*` 新規 endpoint (ADR Gate Criteria #3 trigger)
- event_type 拡張: `audit_events.event_type` enum に `quality_loop_*` 6 種追加 (ADR Gate Criteria #3 trigger、5+ source 整合)
- frontend: Sprint Pack management UI で Quality Loop artifact view (Sprint 9+)
- migration: 既存 Sprint Pack 自由文 defer entry の structured state migration script

実装着手は SP-023 candidate Sprint Pack accepted + ADR 起票 (Quality Loop schema 用、ADR-00026 候補) + human approval event before effect が必須 (修正まとめ統合計画 §2 #11 ADR Gate Criteria break-glass 対象外)。

## 8. 関連 ADR / Sprint Pack (本 design doc で trigger)

- **SP-023 候補 (P0.1、新規 Pack 起票必須)**: Quality Loop product artifact schema 実装、本 design doc を core spec として cross-reference
- **ADR-00026 候補 (P0.1、proposed 新規起票必須)**: Quality Loop schema design (DB / API / event_type)、本 design doc を background として cross-reference
- ADR-00014 (Multi-Agent Orchestration、accepted): Phase C `review_artifacts` table と本 design doc の Quality Loop `review` artifact の物理分離を明示
- ADR-00009 (Action Class Taxonomy、accepted) §QL-B update: `task_write` action の中で Quality Loop plan/review/revision artifact 生成は通常の `task_write` として扱う
- ADR-00004 (AgentRun / AgentRunEvent schema、accepted): AgentRun.status 16 状態の **物理分離宣言** を本 design doc §3 で明文化

## 9. 関連資料

- `docs/設計検討/修正まとめ統合計画.md §5 QL-D` (R29 plan、本 design doc の source)
- `docs/設計検討/phase-c-multi-agent-spec-draft.md §3.3` (Phase C `review_artifacts` table、本 design doc の §5 で物理分離 reference)
- `.claude/rules/agentrun-state-machine.md` (AgentRun.status 16 状態固定、本 design doc §1 #1 invariant の根拠)
- `.claude/rules/cross-source-enum-integrity.md` (5+ source 整合、本 design doc §3.3 の延長)
- `.claude/rules/sprint-pack-adr-gate.md §131-142` (Sprint Pack Review DoD、本 design doc §6 の根拠)
- `.claude/rules/plan-review.md §122-128` (verification checklist、本 design doc §6.3 と整合)
