---
id: "ADR-00009"
title: "Action class taxonomy: 7 種 (task_write/repo_write/pr_open/secret_access/merge/deploy/provider_call) + 初期 policy matrix + self-approval 禁止"
status: "accepted"
date: "2026-05-08"
accepted_at: "2026-05-09"
authors:
  - "t-ohga"
related_sprints:
  - "SP-003_policy_approval"
  - "SP-005_provider_adapter"
  - "SP-008_repo_integration"
  - "SP-011_eval_harness"
supersedes: null
superseded_by: null
---

最終更新: 2026-05-09 (Sprint 3 Batch 4 R3 review F-010 fix で accepted 化)

## 背景

- 決定対象: P0 で AI 操作を policy decision + human approval + audit event で説明できる責任境界にするため、action class 7 種、初期 policy matrix、self-approval 禁止、stale invalidation、`provider_call` の policy gate 化を定義する。
- 関連 Sprint: SP-003 は本 ADR を実装する。SP-005 は `provider_call` を Provider Compliance Matrix / `provider_request_preflight` へ接続する。SP-008 は `repo_write` / `pr_open` を RepoProxy へ接続する。SP-011 は AC-HARD-01 fixture loader を接続する。
- 前提 / 制約: DD-04 §4 の Policy / Approval / Audit boundary、PRD-01 AC-HARD-01 `policy_block_recall`、AC-KPI-03 `approval_wait_ms` を source とする。actors / principals は ADR-00001 に従い、requester / decider / delegated actor を分離する。ADR-00006 の `secret_access` は raw secret 取得ではなく SecretBroker mediated operation の policy gate である。ADR-00010 の `provider_call` は Sprint 5 で Compliance Gate に接続するが、Sprint 3 で action class として先に固定する。DD-04 旧表記の `read/search` は Policy action class から除外し、Sprint 4.5 Tool Registry / `allowed_actions` 側に寄せる。本 ADR は ADR Gate Criteria #4、#3、#1 に該当する。

## 選択肢

| 選択肢 | 概要 | 利点 | 欠点 / リスク |
|---|---|---|---|
| A: 7 種 deny-by-default + self-approval 禁止 + stale invalidation | `task_write` / `repo_write` / `pr_open` / `secret_access` / `merge` / `deploy` / `provider_call` を固定し、`merge` / `deploy` は P0 常時 deny。requester != decider 必須、artifact / diff / policy / provider fingerprint 変化で承認を invalidated にする | AI 出力から command / SQL / workflow / external tool / provider call / repo write への直結を fail-closed で防げる。Sprint 5 / 11 / 12 まで trace 可能 | `secret_access` の意味誤解、matrix seed 漏れ、delegated actor / `impersonated_by` 同一 human の self-approval 漏れ |
| B: 5 種で `pr_open` / `provider_call` を後続 Sprint に送る | `task_write` / `repo_write` / `merge` / `deploy` / `secret_access` のみ定義 | 実装初期コストが低い | Sprint 5 の provider call が policy decision なしで fail-open になりやすい。Sprint 8 で `pr_open` enum が drift する |
| C: action class なし、resource_ref 単位で policy 判定 | resource / operation ごとに個別 rule を評価する | 柔軟で custom rule を書きやすい | policy matrix が爆発し、AC-HARD-01 / AC-KPI-03 trace と AI Output Boundary の段階責務が崩れる |

## 採用案

- 採用: A: 7 種 deny-by-default + self-approval 禁止 + stale invalidation。
- 理由: DD-04 と AC-HARD-01 に整合し、`provider_call` を Sprint 3 で policy 段階に置くことで Sprint 5 Compliance Gate の前段に policy decision / require_approval を置ける。`merge` / `deploy` は独立 reviewer 不在のまま実行可能にしない。self-approval は DB invariant と service guard で二重防御する。
- 実装 Sprint: SP-003 で proposed → accepted 化 + 本実装。Sprint 5 で `provider_call` gate、Sprint 8 で `repo_write` / `pr_open` gate、Sprint 11 で AC-HARD-01 fixture loader に接続する。
- 実装対象ファイル:
  - `backend/app/domain/policy/action_class.py`
  - `backend/app/db/models/policy_rule.py` / `approval_request.py` / `policy_decision.py`
  - `migrations/versions/0005_policy_approval.py`
  - `backend/app/services/policy/{engine,invalidation,self_approval_guard}.py`
  - `backend/app/services/approval/{inbox,notifier}.py`
  - `frontend/app/(admin)/approval-inbox/`
  - `eval/security/policy_block/manifest.json` / `expected_schema.json` / `public_regression/sample.json`
  - `eval/quality/approval_wait_ms/`
  - `tests/policy/{test_action_class_enum,test_initial_policy_matrix,test_approval_stale_invalidation,test_self_approval_negative}.py`
  - `tests/eval/test_policy_block_recall_policy_source.py`
  - `tests/metrics/test_approval_wait_ms.py`
- 実装ガイダンス:
  - action class 7 種は backend / DB CHECK / frontend / fixture schema で同一集合にする。
  - 初期 policy matrix は deny-by-default。`merge` / `deploy` は `effect=deny`、`reason_code=p0_merge_deploy_disabled`。`secret_access` / `provider_call` は fail-closed。`task_write` / `repo_write` / `pr_open` は条件に応じて require_approval または deny。**未登録または解決不能な resource_ref は deny** とし `reason_code=unknown_resource_ref_denied` を `policy_rules` / `policy_decisions` / AC-HARD-01 fixture skeleton に trace する。
  - AC-HARD-01 source は `policy_rules` と reason_code (`policy_matrix_default_deny`, `unknown_action_class_denied`, `provider_not_in_matrix`, `dangerous_command_denied`, `unknown_resource_ref_denied` 等) に固定する。`provider_call` の Provider Compliance 失敗 (未検証 ZDR / retention / region / plan 等) は ADR-00010 の 13 reason_code (`condition_unverified` / `retention_unverified` / `region_unverified` / `plan_unverified` / `training_use_not_no` 等) に委譲し、ADR-00009 の Policy Engine 段階では `provider_not_in_matrix` を使う。
  - **tenant 境界 (ADR-00002 / SP-003 §125 準拠)**: `policy_rules` / `approval_requests` / `policy_decisions` は `tenant_id bigint NOT NULL DEFAULT 1` を持ち、project / resource scope を必要に応じて保存する。`requested_by_actor_id` / `decided_by_actor_id` / `actor_id` / `run_id` / `approval_request_id` は **`tenant_id` を含む複合 FK** で Sprint 2 の `actors` / `principals` / `agent_runs` (Sprint 4 で実装、それまでは nullable + Sprint 4 follow-up TODO) と接続する。**`id` 単独 FK は禁止**。`tests/db/test_schema_introspection.py` (Sprint 3 で 3 table 追加) で `tenant_id` 列、複合 FK、`id` 単独 FK 不在を assert する。
  - `policy_decisions` は append-only で、`policy_decision_id`, `run_id`, `action_class`, `decision`, `reason_code`, `policy_version`, `input_hash`, `actor_id`, `approval_request_id`, `created_at` を残す。
  - approval target は `artifact_hash`, `diff_hash`, `policy_version`, `policy_pack_lock`, `provider_request_fingerprint`, `stale_after_event_seq` を持つ。変化時は `approval_requests.status='invalidated'` とし、resume には新 approval を要求する。
  - self-approval は `requested_by_actor_id != decided_by_actor_id` DB CHECK + service guard。delegated actor が同じ human を `impersonated_by` に持つ場合、independent reviewer required action は reject する。
  - Approval Inbox は pending 一覧、詳細、approve / reject、invalidated / expired 表示、notification badge までを must_ship とし、bulk action / 高度 filter / policy editor は Sprint 9 へ defer する。
  - In-App Notification は `approval_pending` / `policy_blocked` / `budget_exceeded` / `run_failed` の最小 schema に閉じる。外部通知は P0 対象外。
  - `approval_wait_ms` は DB の `approval_requests.requested_at` / `decided_at` から median を計算する。UI event は source of truth にしない。
  - 本 ADR は `tool_mutating_gateway_stub` や `runner_mutation_gateway` の実装ではなく、policy action class と approval boundary の正本である。
- テスト指針: enum 一致、初期 matrix deny (`merge` / `deploy` deny、unknown action / unknown resource_ref deny、unregistered provider deny)、`secret_access` / `provider_call` fail-closed、AC-HARD-01 policy source contract (reason_code が Sprint 5 / 11 trace と整合)、stale invalidation **5 種** (artifact_hash / diff_hash / policy_version / policy_pack_lock / provider_request_fingerprint 変化すべてを `tests/policy/test_approval_stale_invalidation.py` の fixture で検証)、self-approval / delegated actor negative、`merge` / `deploy` 実行不可、`approval_wait_ms` DB 集計、audit event の actor_id / run_id / trace_id / correlation_id / policy_version / reason_code、**schema introspection で `policy_rules` / `approval_requests` / `policy_decisions` 3 table の `tenant_id` 列 / 複合 FK / `id` 単独 FK 不在 (`tests/db/test_schema_introspection.py` 拡張) と cross-tenant negative test (`tests/security/test_tenant_isolation_negative.py` 拡張)** を確認する。
- ADR Gate Criteria 該当: #4 AI エージェント権限を主、#3 API / event schema と #1 actor binding を補助として扱う。

## 却下案

- B: `pr_open` / `provider_call` を除外すると、Sprint 5 の Compliance Gate 前段に policy decision がなく fail-open リスクが高い。Sprint 8 で別 enum を足すと drift するため却下する。
- C: action class なしでは policy matrix が resource_ref 単位で爆発し、AC-HARD-01 / AC-KPI-03 trace、AI Output Boundary、audit explanation が困難になるため却下する。

## リスク

| リスク | 検知方法 | 軽減策 |
|---|---|---|
| action class 7 種の境界定義漏れ | enum drift test、fixture schema test | `secret_access` は SecretBroker mediated operation の policy gate と明記し、enum 一致 contract test を CI smoke 級にする |
| 初期 matrix の deny-by-default 漏れ | `tests/policy/test_initial_policy_matrix.py` | seed migration で unknown action deny、`merge` / `deploy` deny、未登録 provider deny を assert する |
| AC-HARD-01 trace drift | `tests/eval/test_policy_block_recall_policy_source.py` | reason_code 分類を固定し、Sprint 5 / 11 着手時に整合 review する |
| self-approval negative 漏れ | `tests/policy/test_self_approval_negative.py` | DB CHECK + service guard、requester==decider / delegated actor / `impersonated_by` 同一 human を release blocker にする |
| stale invalidation 漏れ | `tests/policy/test_approval_stale_invalidation.py` | artifact_hash / diff_hash / policy_version / policy_pack_lock / provider_request_fingerprint の **5 ケースすべて** を contract test fixture で検証し、`stale_after_event_seq` と紐づけて resume 時に再 verify する |
| `approval_wait_ms` が UI event 依存へ drift | `tests/metrics/test_approval_wait_ms.py` | DB query を source of truth に固定し、frontend telemetry は補助にする |
| policy_version rollback 後に旧 approval を使う | matrix 変更時の invalidation test | 新 `policy_version` 発行時に既存 pending / approved approval を invalidated にする |

## rollback 手順

### 運用 rollback (policy matrix の問題発見)

1. 新 `policy_version` を発行し、deny-only baseline matrix を seed する。`merge` / `deploy` / `secret_access` / `provider_call` はすべて `effect=deny` にする。
2. 既存 `approval_requests.status='pending'` / `'approved'` を `invalidated` に遷移し、再承認を要求する。
3. `policy_decisions` は append-only のまま残し、新 decision は新 `policy_version` で記録する。
4. UI / In-App Notification で stale invalidation を通知する。
5. `tests/policy/test_initial_policy_matrix.py` と `tests/eval/test_policy_block_recall_policy_source.py` を staging で実行し、新 baseline を確認する。

### Migration rollback (DB schema 変更時)

1. migration 適用前に `pg_dump` で full DB backup を取得し、age で暗号化して別ボリュームに保存する。
2. staging DB で `uv run alembic upgrade head`、`alembic check`、policy / approval contract test を先行実行し、action_class enum、`policy_rules` unique constraint、approval status enum、self-approval CHECK、append-only index、tenant FK を確認する。
3. production migration 後に unknown action_class が保存可能、初期 matrix が deny-by-default でない、`merge` / `deploy` が allow、self-approval が成功、orphan `approval_requests` / `policy_decisions`、`approval_wait_ms` source 欠落のいずれかを検出したら rollback trigger とする。
4. `uv run alembic downgrade -1` を実行する。downgrade で data loss / inconsistent state になる場合は forward-fix migration を新規作成し、staging で検証してから production 適用する。最終手段として age 暗号化 backup から restore する。
5. rollback verification は `uv run pytest tests/policy/test_action_class_enum.py tests/policy/test_initial_policy_matrix.py tests/policy/test_self_approval_negative.py tests/policy/test_approval_stale_invalidation.py tests/metrics/test_approval_wait_ms.py tests/eval/test_policy_block_recall_policy_source.py -q` で実行して確認する (Sprint 3 完了後に Sprint Pack 検証手順と合わせて整合確認)。

---

## Phase D R1-R4 + Phase E Multi-Agent vision update (2026-05-10、proposed 追記)

ADR-00014/15/16/17/18/19/20 (Multi-Agent vision) accepted 化に伴う本 ADR の update (Phase D PD-F-004/PD-R2-F-005/PD-R2-F-014/PD-R3-F-003/PD-R4-F-005 + Phase E PE-F-003/PE-F-016 反映、計 7 finding 関連)。

### action_class 7 種は不変 (AP-8 reject 永続化)

`orchestrator_dispatch` / `inter_agent_message` / `auto_approve_low_risk` / `read_only_research` / `read_only_audit` の 5 種を action_class として追加することは禁止 (Phase D PD-F-004 で reject)。代わりに以下 4 boundary に分散:

| 旧 (rejected) | 新 (採用) |
|---|---|
| `orchestrator_dispatch` | `agent_run_event_type='orchestrator_dispatched'` (ADR-00004 update event 23) |
| `inter_agent_message` | `agent_run_event_type='inter_agent_message_sent_ref/consumed_ref'` + audit_events (ADR-00018) |
| `auto_approve_low_risk` | `policy_profile='low_risk_auto_allow'` (本 ADR で新規定義) |
| `read_only_research` | Tool Registry `allowed_actions=['web_fetch','docs_search']` (P0.1 Tool Registry network ADR) |
| `read_only_audit` | Tool Registry `allowed_actions=['trace_read','metric_read']` |

### policy_profile schema (PD-R3-F-003 / PE-F-016 fix)

P0.1 で `policy_profiles` + `policy_profile_action_effects` を追加 (DDL は Phase C draft §3.9 参照)。`projects.policy_profile` の許可値 enum:

- `default` (P0 既存): `task_write` require_approval / 既存 7 種 effect 不変
- `low_risk_auto_allow` (P0.1 新規): `task_write` (artifact のみ + review_artifact 必須) と `provider_call` (zdr_eligible=yes only + payload_data_class<=internal) のみ allow、`repo_write/pr_open/secret_access/merge/deploy` は deny

**14 rows exact seed** (default × 7 + low_risk_auto_allow × 7、PE-F-016 fix):
unknown profile / missing seed row / secret_access allow drift / provider_call without ZDR / task_write without review_artifact を AC-HARD-01 multi-agent fixture で全件 deny verify.

### policy_decisions 拡張列

P0.1 で追加: `policy_profile text not null`、`profile_resolved_effect text not null check (effect in ('allow','deny','require_approval'))`、`required_review_artifact_id uuid null` + review_artifacts FK (PE-F-003).

### Tier 2 = approval_requests を作らない (PD-F-005 / PE-F-003)

Tier 2 (`policy_profile=low_risk_auto_allow` で effect=allow) は **approval_requests に row を作らない**。Policy Engine が policy_decisions に effect=allow を直接記録、agent reviewer は `review_artifacts` を作成して Policy Engine の input にする。**`approval_requests.decided_by_actor_id` は引き続き human のみ** (DB CHECK + service guard 4 重防御、本 ADR の self-approval 禁止 invariant + decider human-only invariant 不変).

### DD-02 / DD-03 / DD-04 enum 同期 (PD-R2-F-014 / PD-R4-F-005 fix、Phase F-0 前提 task)

Phase F-0 で DD-02 の `policy_rules` / `approval_requests` / `policy_decisions` の `action_class` CHECK を本 ADR accepted enum 7 種 (`task_write` / `repo_write` / `pr_open` / `secret_access` / `merge` / `deploy` / `provider_call`) に同期 (legacy `read/search` 削除 + `provider_call` 追加)。`read/search` を action_class として持つ既存 row は Tool Registry `allowed_actions` 経由に migration、または非該当として archive.

### 関連 ADR

- ADR-00014 / ADR-00018 / Tool Registry network ADR (P0.1 新規) / Phase C draft §3.9
