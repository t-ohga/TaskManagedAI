# AgentRun State Machine

AgentRun 16 状態、`blocked` サブ 3、terminal state、provider result mapping、repair retry exhaustion を固定するルール。  
状態は snapshot ではなく AgentRunEvent から説明できなければならない。

## 1. Status Enum

AgentRun status は P0 で次の 16 状態に固定する。

1. `queued`
2. `gathering_context`
3. `running`
4. `generated_artifact`
5. `schema_validated`
6. `policy_linted`
7. `diff_ready`
8. `waiting_approval`
9. `blocked`
10. `provider_refused`
11. `provider_incomplete`
12. `validation_failed`
13. `repair_exhausted`
14. `completed`
15. `failed`
16. `cancelled`

## 2. Blocked Sub Categories

`blocked` は status として 1 状態だけ。

`blocked_reason` は次の 3 種のみ。

- `policy_blocked`
- `budget_blocked`
- `runtime_blocked`

DB invariant:

- `status='blocked'` なら `blocked_reason is not null`。
- `status<>'blocked'` なら `blocked_reason is null`。
- `blocked_reason` を status enum に増やさない。
- 16 状態 + blocked サブ 3 を 19 状態として実装しない。

## 3. Terminal State

terminal state:

- `completed`
- `failed`
- `cancelled`
- `provider_refused`
- `repair_exhausted`

terminal ではない state:

- `blocked`
- `provider_incomplete`
- `validation_failed`
- `waiting_approval`
- `diff_ready`
- `policy_linted`
- `schema_validated`
- `generated_artifact`
- `running`
- `gathering_context`
- `queued`

## 4. 標準遷移

```text
queued
-> gathering_context
-> running
-> generated_artifact
-> schema_validated
-> policy_linted
-> diff_ready
-> waiting_approval
-> running
-> completed
```

例外遷移:

- `running -> provider_refused`
- `running -> provider_incomplete`
- `running -> blocked`
- `running -> failed`
- `running -> cancelled`
- `waiting_approval -> cancelled`
- `blocked -> cancelled`
- `provider_incomplete -> cancelled`
- `generated_artifact -> validation_failed`
- `validation_failed -> running`
- `validation_failed -> repair_exhausted`
- `policy_linted -> blocked`
- `diff_ready -> blocked`
- `waiting_approval -> blocked`
- `blocked -> waiting_approval`
- `blocked -> running`
- `blocked -> failed`
- `provider_incomplete -> running`
- `provider_incomplete -> failed`

## 5. Event 原則

- status update だけを正本にしない。
- AgentRunEvent append を必須にする。
- event は `seq_no` で順序を持つ。
- `(tenant_id, run_id, seq_no)` は unique。
- idempotency key を持つ operation は `(tenant_id, run_id, idempotency_key)` で重複防止。
- status update と event append は同一 transaction。
- event payload は raw secret を含まない。
- actor_id を必須にする。

## 6. Event Types

| event_type | 目的 |
|---|---|
| `run_queued` | AgentRun 作成 |
| `context_gathered` | ContextSnapshot 作成 |
| `provider_requested` | ProviderAdapter 呼出前 |
| `provider_responded` | provider response / usage |
| `artifact_generated` | artifact 保存 |
| `schema_validated` | schema validation 成功 |
| `validation_failed` | schema validation 失敗 |
| `repair_retry_scheduled` | repair retry |
| `policy_linted` | policy lint 成功 |
| `policy_blocked` | policy deny |
| `budget_blocked` | budget hard limit |
| `runtime_blocked` | runner / command / path deny |
| `diff_ready` | diff validation 成功 |
| `approval_requested` | approval request 作成 |
| `approval_decided` | approval 決定 |
| `runner_started` | Docker isolated runner 起動 (DD-03、AC-HARD-05/06 監査 trace) |
| `runner_completed` | runner 完了 (exit code、resource cap 結果含む) |
| `runner_blocked` | runner sandbox での deny (forbidden path / dangerous command / resource cap)。AC-HARD-05/06 trace の核 |
| `repo_pr_opened` | RepoProxy 経由で Draft PR 作成 (DD-03、AC-KPI-02 計測元) |
| `run_completed` | success terminal |
| `run_failed` | failure terminal |
| `run_cancelled` | cancel terminal |
| `trust_level_promoted` | Sprint 5.5 BL-0069: Input Trust Layer で `untrusted_content` -> `trusted_instruction` への昇格成功 (Approval 4 整合 hash binding 経由) |
| `trust_level_promotion_denied` | Sprint 5.5 BL-0069: 昇格 deny (Approval 不在 / hash mismatch / policy block) |
| `cli_invocation_started` | Sprint 6 BL-0067: CLI launcher が subprocess spawn 直後 (registry agent_name + redacted argv summary + per-run workdir id) |
| `cli_process_completed` | Sprint 6 BL-0067: subprocess の exit / timeout / cancelled 後の集約 event (exit_code / signal / duration / timeout_reached / cancelled / stdout_bytes / stderr_bytes / redaction_hit_count) |
| `cli_decision_recorded` | Sprint 6 BL-0068: cli_result_summary に対する `adopt` / `reject` / `defer` 採否判定 (actor + reason + decided_at + artifact_hash) |

### 6.1 P0.1+ 拡張 event_type (28 → 37、ADR-00004 update / Phase H PH-F-006 fix / Sprint 6 batch 2 update)

ADR-00014 Multi-Agent Orchestration / ADR-00018 Inter-Agent Communication で導入される追加 event_type 9 種 (event_type 29〜37). P0 期間中は使用しない (P0 sealed CI guard 対象)、P0.1 SP-013/014/015 で実装。

Sprint 6 batch 2 (2026-05-13) で event_type は 25 → 28 に拡張済 (`cli_invocation_started` / `cli_process_completed` / `cli_decision_recorded`)、本 §6.1 の P0.1+ extension はその上に重ねる:

| # | event_type | state transition | 必須 payload (raw secret なし) | audit_events 責務分担 |
|---|---|---|---|---|
| 29 | `orchestrator_dispatched` | running | child_run_id, role_id, role_scope, dispatch_reason, recommended_provider | (AgentRunEvent のみ) |
| 30 | `orchestrator_lease_renewed` | running | lease_token_hash, renewed_at, expires_at | (AgentRunEvent のみ) |
| 31 | `orchestrator_lease_expired` | running -> blocked or running | old_lease_hash, expired_at, reason_code | (AgentRunEvent のみ) |
| 32 | `orchestrator_failover_triggered` | running | old_lease_hash, new_orchestrator_run_id, new_lease_hash, reason_code | audit_events `orchestrator_failover` |
| 33 | `orchestrator_kill_engaged` | running -> blocked (runtime_blocked) | engaged_by_actor_id (human only via UI/CLI), reason | audit_events `orchestrator_kill_engaged` |
| 34 | `inter_agent_message_sent_ref` | (status 不変) | message_id, payload_hash, seq_no, sender_run_id, receiver_run_id, redaction_status | audit_events `inter_agent_message_sent` |
| 35 | `inter_agent_message_consumed_ref` | (status 不変) | + previous_hash_match | audit_events `inter_agent_message_consumed` |
| 36 | `tool_web_fetch_executed` | running | tool_name, domain, provider, payload_data_class, redaction_status | (AgentRunEvent のみ、SP-018 で audit_events 拡張) |
| 37 | `tool_docs_search_executed` | running | 同上 | 同上 |

**5+ source 整合 (cross-source-enum-integrity §1) 更新先**:

- DB CHECK: `migrations/versions/00NN_p0_1_event_type_37.py` で `agent_run_events.event_type` CHECK 拡張
- ORM CheckConstraint: `backend/app/db/models/agent_run_event.py`
- Python Literal: `backend/app/domain/agent_run/event_types.py` の `EVENT_TYPES: frozenset` (28 + 9 = 37)
- Pydantic: `agent_run_event/schemas.py`
- pytest: `tests/agent_runtime/test_event_type_enum.py` の `EXPECTED_EVENT_TYPES` (37)
- frontend: `frontend/lib/domain/agent-run-event.ts` (Sprint 17 で TypeScript enum)

**P0 期間中の sealed**: P0 sealed CI guard で `migrations/versions/*event_type_37*` 等の P0.1 path 追加を禁止 (本 rules + ADR-00021 §11.6 / ADR-00014 §13 で statement 統一).

## 7. Provider Result Mapping

| provider result | status |
|---|---|
| refusal | `provider_refused` |
| safety refusal | `provider_refused` |
| max token / incomplete | `provider_incomplete` |
| timeout retryable | `provider_incomplete` または `failed` |
| unsupported schema | `validation_failed` |
| schema mismatch | `validation_failed` |
| provider request preflight deny | `blocked` + `policy_blocked` |
| data class deny | `blocked` + `policy_blocked` |
| budget exceeded | `blocked` + `budget_blocked` |
| success structured output | `generated_artifact` |

## 8. Repair Retry

- repair retry 対象は `validation_failed`。
- repair retry 上限は BudgetGuard / policy に持つ。
- retry ごとに ContextSnapshot `snapshot_kind=resume` を作る。
- retry の input は previous artifact と validation error の redacted summary。
- raw provider response や secret 値を retry prompt に入れない。
- 上限到達時は `repair_exhausted`。
- `repair_exhausted` は terminal。
- `repair_exhausted` から retry しない。

## 9. Resume

- `blocked` は原因解消後に resume できる。
- `policy_blocked` は approval / policy 更新後のみ。
- `budget_blocked` は budget 更新後のみ。
- `runtime_blocked` は plan / patch 修正後のみ。
- `provider_incomplete` は retry / continuation が可能な場合のみ。
- resume 前に ContextSnapshot `snapshot_kind=resume` を作る。
- stale approval は resume せず再承認を要求する。
- terminal state は resume 不可。

## 10. Cancel

- cancel は API から worker / runner / provider cancellation boundary へ伝播する。
- cancellation request は event に残す。
- worker は安全な境界で停止する。
- runner / provider が止められない場合は timeout と kill policy を使う。
- cancel 完了時は `cancelled`。
- `cancelled` は terminal。
- cancel 後に repo write / provider call を続けない。

## 11. ContextSnapshot 連動

必須 10 カラム:

- `prompt_pack_version`
- `prompt_pack_lock`
- `policy_version`
- `policy_pack_lock`
- `repo_state`
- `tool_manifest`
- `evidence_set_hash`
- `provider_continuation_ref`
- `provider_request_fingerprint`
- `snapshot_kind`

運用:

- `input` は run 開始時。
- `pre_tool` は tool / runner 前。
- `post_tool` は tool / runner 後。
- `resume` は retry / resume 前。
- `final` は terminal 前後。
- `provider_continuation_ref` は secret / provider key を含まない短命参照。


<!-- Phase E 圧縮 (2026-05-17 PR #?): 末尾 verify checklist 削除、plan §3.1.1 invariant trace matrix で自動 verify -->
