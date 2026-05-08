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

## 12. Contract Test

- [ ] enum が 16 状態と一致する。
- [ ] DB check が `blocked_reason` consistency を強制する。
- [ ] terminal state から遷移できない。
- [ ] provider result mapping が正しい。
- [ ] repair retry 上限到達で `repair_exhausted`。
- [ ] `provider_incomplete` は terminal ではない。
- [ ] status update と event append が同一 transaction。
- [ ] ContextSnapshot 10 カラムが揃う。
- [ ] event payload に raw secret がない。
- [ ] `blocked_reason` を status と混同していない。

