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

### DD-02 / DD-03 / DD-04 enum 同期 (PD-R2-F-014 / PD-R4-F-005 / PH-F-005 fix、Phase F-0 前提 task として正式起票)

**Phase F-0 = `action_class` enum 同期 migration**: P0.1 SP-013 着手前に **必ず** 完了する prerequisite Sprint (本 ADR-00009 update 連動). 詳細手順:

| Step | 対象 file | 内容 |
|---|---|---|
| 1 | `docs/基本設計/02_データモデル.md` | `policy_rules` / `approval_requests` / `policy_decisions` の `action_class` CHECK を 7 種 (`task_write` / `repo_write` / `pr_open` / `secret_access` / `merge` / `deploy` / `provider_call`) に書換、`read/search` 削除 |
| 2 | `docs/基本設計/03_AIオーケストレーション設計.md` | action_class 表 (DD-03 で言及されている部分) を 7 種同期 |
| 3 | `docs/基本設計/04_セキュリティ_権限_監査設計.md` | action_class section の表 (DD-04) を 7 種同期、`read/search` を Tool Registry `allowed_actions` 経由に明記 |
| 4 | `.claude/rules/server-owned-boundary.md` §5 | action_class 5 種 enum を 7 種に拡張 (`merge` / `deploy` 追加) |
| 5 | `tests/policy/test_action_class_enum.py` の `EXPECTED_ACTION_CLASSES` | 7 種 frozenset を確認 |
| 6 | `migrations/versions/00NN_p0_action_class_enum_sync.py` | `policy_rules` / `approval_requests` / `policy_decisions` の `action_class` CHECK 制約を 7 種に変更、既存 `action_class='read/search'` row を Tool Registry path に migration、または非該当として archive (実 row 0 件想定だが migration script で 0 件 verify) |

**Phase F-0 前提 task として SP-013 着手前に必ず完了**。SP-013 / SP-014 / SP-015 / SP-016 の planned_adr_refs / acceptance に Phase F-0 完了 verify を必須含める. 以下の Sprint Pack に reference:

- SP-013 受け入れ条件に「Phase F-0 完了確認 (`uv run pytest tests/db/test_action_class_enum.py`)」追加
- SP-014 / 015 / 016 acceptance に同様の前提条件 verify 追加

これにより PH-F-005 CRITICAL の cross-source enum drift を完全 closure.

### 関連 ADR

- ADR-00014 / ADR-00018 / Tool Registry network ADR (P0.1 新規) / Phase C draft §3.9

---

## Sprint 5.5 Output Validator + Input Trust Layer update (2026-05-10、proposed 追記)

SP-005-5 (Output Validator) accepted 化に伴う本 ADR の update。**action_class 7 種は不変** (Sprint 5.5 で拡張なし)、本 update は (1) `repair_retry_max_attempts` policy を `config/policy_pack.toml` に新規導入、(2) `trusted_instruction` 昇格境界を既存 approval 経路に閉じる方針を Approval 4 整合 + decider human-only で明示、(3) Sprint 5.5 で追加する audit_events を 2 taxonomy で記述、の 3 点を追記する。

### action_class 7 種は不変 (Sprint 5.5 で拡張なし)

Sprint 5.5 (Output Validator + Input Trust Layer + repair retry policy) では action_class を **拡張しない**。Output Validator は既存の `task_write` (artifact 生成 / repair retry) と `provider_call` (provider 再呼出) の延長で扱い、Input Trust Layer の trust_level 昇格は既存の `task_write` (validated_artifact 化) と human approval 経由の昇格 (trusted_instruction 化) で扱う。

### `repair_retry_max_attempts` policy 追加 (`config/policy_pack.toml` 新規導入)

Sprint 5.5 で `config/policy_pack.toml` を新規導入し、以下の policy を追加:

| policy key | default | 役割 |
|---|---|---|
| `repair_retry_max_attempts` | 3 | Output Validator の repair retry 上限。BudgetGuard `repair_budget_remaining` との AND で `repair_exhausted` (terminal、ADR-00004 §13 番目の状態) 遷移を制御 |
| `trust_level_promotion_to_trusted_instruction_requires_human_approval` | true | `validated_artifact -> trusted_instruction` 昇格は human approval 経路 (Approval 4 整合 + decider human-only) のみ許可。boolean toggle (default true) で P0 では常時 true、P0.1+ で条件付き auto-promotion を ADR で議論可 |

`policy_pack.toml` は **append-only / monotonic version increment** (Sprint 3 で確立した policy_decision invariant と同 pattern):

- 新 policy 追加時は `policy_version` bump (e.g., `v1.0` → `v1.1`)、ContextSnapshot.policy_pack_lock も同期 update
- 既存 policy 変更時は新 row 追加 + 旧 row deprecated marker、policy_decisions は append-only で旧 version 参照保持
- rollback は forward-fix 戦略 (旧 default に戻す新 row 追加)、file 削除はしない

5+ source 整合:
- file `config/policy_pack.toml` (新規)
- Python parser `backend/app/services/policy/policy_pack_loader.py` (新規)
- Pydantic `PolicyPackConfig` schema (`extra="forbid"` で caller-supplied 経路禁止)
- pytest `tests/policy/test_policy_pack_loader.py` (新規) で policy_pack_lock 整合 + policy_version monotonic
- ContextSnapshot `policy_pack_lock` 列 (Sprint 4 で導入済) との接続 verify

### `trusted_instruction` 昇格境界 (Approval 4 整合 + decider human-only)

`untrusted_content -> validated_artifact` (server-owned 自動昇格、schema validation pass + policy lint pass) と `validated_artifact -> trusted_instruction` (human approval 経由) の **2 段階を明確に分離**:

| 昇格経路 | trigger | gate | actor |
|---|---|---|---|
| `untrusted_content -> validated_artifact` | schema validation pass + policy lint pass | server-owned (`backend/app/services/input_trust/promotion.py` 新規) | server / agent / system (caller-supplied 経路 signature レベル削除) |
| `validated_artifact -> trusted_instruction` | human approval | **既存 Approval 4 整合 + decider human-only** + `policy_pack.trust_level_promotion_to_trusted_instruction_requires_human_approval = true` | human only (DB CHECK + service guard 4 重防御、本 ADR の self-approval 禁止 invariant + decider human-only invariant 継続) |

trusted_instruction 昇格時の Approval 4 整合 (本 ADR §採用案 line 57 既存定義の延長):
1. `artifact_hash` (validated_artifact 状態の hash)
2. `policy_version` + `policy_pack_lock`
3. `provider_request_fingerprint` (artifact 生成元 provider call の fingerprint)
4. `action_class` (`task_write` のサブセット、artifact promotion sub-classification は service layer で扱い、action_class enum 拡張なし)

stale invalidation: 既存 5 ケース (artifact_hash / diff_hash / policy_version / policy_pack_lock / provider_request_fingerprint) のすべてを `tests/policy/test_approval_stale_invalidation.py` で検証済 (Sprint 3 で確立)。Sprint 5.5 で trust_level 昇格 approval を追加しても **invalidation 経路は既存と同 pattern** で動作。

self-approval 禁止: requester != decider 必須、delegated actor が同じ human を `impersonated_by` に持つ場合も reject (本 ADR 既存 invariant 継続、Sprint 5.5 で trust_level 昇格にも適用)。

### Sprint 5.5 audit_events 拡張 (ADR-00004 update §audit_events への追加と整合)

Sprint 5.5 で **2 taxonomy** (Sprint 5 Batch 2 で確立) に従い audit_events に追加する event_type:

| audit_event_type | trigger | payload (raw secret なし) | 関連 AgentRunEvent (ADR-00004 §Sprint 5.5 update) |
|---|---|---|---|
| `output_validation_repair_retry_recorded` | repair retry 実行時の policy / budget check 結果 | tenant_id, run_id, retry_count, policy_max_attempts, budget_remaining_before / after, decision (`allow_retry` / `repair_exhausted`), policy_version | (なし、AgentRunEvent 側は `repair_retry_scheduled` 既存または `repair_exhausted` event #23) |
| `trust_level_promotion_audit` | `validated_artifact -> trusted_instruction` 昇格時 | tenant_id, artifact_id, approval_request_id, decider_actor_id (human only verify), 4 整合 hash 4 種 (artifact_hash / policy_version / provider_request_fingerprint / action_class) | event #24 `trust_level_promoted` |
| `trust_level_promotion_denial_audit` | 昇格 deny 時 (server-owned 経路違反 / Approval 4 整合 mismatch / self-approval 試行 / caller-supplied 試行) | tenant_id, artifact_id, attempted_trust_level, deny_reason_code, raw_secret_check_passed=true (raw 値非露出 verify) | event #25 `trust_level_promotion_denied` |

audit_events の 3 種は **AgentRunEvent とは別 table** (Sprint 5 Batch 2 確立の 2 taxonomy)、actor / run / trace_id / correlation_id / policy_version / reason_code を必須 payload として持ち、raw secret / raw provider response / capability token 生値を含めない (`tests/security/test_audit_no_raw_secret.py` parametrized で検証)。

### policy_decisions への trust_level 昇格 trace 追加 (P0 期間中、既存列の延長)

policy_decisions table に trust_level 昇格判定を保存する場合、**既存列の延長で対応** (新規列追加なし):

- `action_class = 'task_write'` (既存 enum 値、artifact promotion は task_write のサブセット)
- `reason_code` に Sprint 5.5 で追加: `trust_level_promotion_allowed` / `trust_level_promotion_denied_*` (deny_reason_code 5 種)
- `input_hash` に artifact_hash + attempted_trust_level + policy_version の組合せ canonical hash を保存

policy_decisions 列拡張は **行わない** (Sprint 5.5 で additive only 維持、ADR Gate Criteria #2 DB schema は ADR-00002 延長で対応、本 ADR で新規列追加なし)。

### Sprint 5.5 関連 Sprint Pack

- SP-005-5 (Output Validator) 受け入れ条件 + §設計判断 + §Rollback section が本 update と整合
- SP-005-5 BL-0064 (Output Validator core) で `repair_retry_max_attempts` policy 駆動を実装
- SP-005-5 BL-0065 (Input Trust Layer) で trust_level enum + 5+ source 整合を実装
- SP-005-5 BL-0069 (trust_level 昇格 service) で本 update の Approval 4 整合 + decider human-only を実装
- SP-005-5 BL-0071 (AC-HARD-07 prompt_injection_resist fixture loader) で trust_level 昇格 deny の 5 pattern を verify

### 関連 ADR (Sprint 5.5)

- ADR-00004 update §Sprint 5.5: event_type 22 → 25 拡張 (`repair_exhausted` / `trust_level_promoted` / `trust_level_promotion_denied`)、`repair_exhausted` terminal 強制、artifacts.trust_level 列追加、event_type numbering 整合 (Phase D-E は 26-34 にシフト)
- ADR-00006 (SecretBroker): repair retry context redaction で `assert_no_raw_secret` を retry prompt builder で必須実行 (Sprint 5.5 で延長)
- ADR-00010 (Provider Compliance Matrix v2): payload_data_class 算出を Input Trust Layer 側に集約 (Sprint 5.5 で延長、Sprint 5 で確立した caller-supplied 禁止 invariant 継続)
- ADR-00002 (DB schema): artifacts.trust_level 列追加は ADR-00002 の延長として扱う (de facto accepted via Sprint 2 完了)
