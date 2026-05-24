---
id: "ADR-00004"
title: "AgentRun state machine: 16 状態 + blocked サブ 3 + ContextSnapshot 10 カラム + transition guard + event schema"
status: "accepted"
date: "2026-05-09"
accepted_at: "2026-05-09"
authors:
  - "t-ohga"
related_sprints:
  - "SP-004_agent_runtime"
  - "SP-005_provider_adapter"
  - "SP-007_runner_sandbox"
supersedes: null
superseded_by: null
---

最終更新: 2026-05-24 (SP-009-5 Batch E0 で Approval `request_revision` の state-machine boundary note を append。前: 2026-05-09 Sprint 4 accepted 化)

## 背景

TaskManagedAI は、Deep Research から実装 PR までの AI 作業を、証拠、判断、承認、実行ログ、コスト、レビュー結果とともに管理する。AI 実行を単なる worker job や現在 status だけで扱うと、後から「どの入力、どの policy、どの repo state、どの provider fingerprint、どの承認、どの retry で結果が出たか」を説明できない。

そのため Sprint 4 の Agent Runtime では、AgentRun を再現可能で評価可能な開発プロセスとして扱うために、次を固定する必要がある。

- AgentRun status を 16 状態に固定する。
- `blocked` は 1 状態のまま維持し、停止理由は `blocked_reason` 3 種で表現する。
- terminal state 5 種からの resume / retry を禁止する。
- ContextSnapshot 必須 10 カラムで、prompt、policy、repo state、tool manifest、evidence、provider request fingerprint を保存する。
- AgentRunEvent を append-only の正本とし、status update と event append を同一 transaction にする。
- Provider result、repair retry、resume、cancel の扱いを state machine と event で説明できるようにする。
- AI Output Boundary の artifact pipeline 7 stage を、AgentRun status と event schema へ接続する。

本 ADR は、`.claude/rules/agentrun-state-machine.md`、DD-03、PRD-01 F-008 / F-009、SP-004 の must_ship を実装前に ADR Gate として固定する。

## 決定対象

本 ADR で決定する対象は次の通り。

- AgentRun status enum 16 状態。
- `blocked_reason` 3 種。
- terminal state 5 種。
- ContextSnapshot 必須 10 カラム。
- `snapshot_kind` 5 種。
- AgentRunEvent schema:
  - `tenant_id`
  - `run_id`
  - `seq_no`
  - `event_type`
  - `event_payload`
  - `actor_id`
  - `idempotency_key`
  - `created_at`
  - raw secret / provider key / capability token 生値を含めない payload contract
- `(tenant_id, run_id, seq_no)` unique。
- non-null `idempotency_key` を持つ operation の `(tenant_id, run_id, idempotency_key)` 重複防止。
- status update + AgentRunEvent append を同一 transaction にする不変条件。
- transition guard:
  - 許可遷移のみ通す。
  - terminal state からの transition を reject する。
  - `blocked_reason` と `status='blocked'` の相関を DB CHECK と service guard で強制する。
- Provider result mapping。
- repair retry exhaustion。
- cancel propagation。
- approval / policy / budget 解消後の resume path。
- SP-007 runner isolation で追加接続する `runner_started` / `runner_completed` / `runner_blocked` event。

## 関連 Sprint

- SP-004 Agent Runtime: 本 ADR の主対象。AgentRun 16 状態、blocked サブ 3、ContextSnapshot 10 カラム、AgentRunEvent、Artifact、BudgetGuard、SecretBroker issue / redeem、plan artifact schema、cancel propagation を実装する。
- SP-005 Provider Adapter: ProviderAdapter 本実装、Provider Compliance Matrix、`payload_data_class` / `allowed_data_class` enforcement、`provider_request_preflight`、provider result mapping を本 ADR の state machine に接続する。
- SP-007 Runner Sandbox: Docker isolated runner、`runner_mutation_gateway`、forbidden path / dangerous command / resource cap を `runtime_blocked` と runner event に接続する。
- SP-002 Core Data Model: tenant / project / actor / principal / secret token の基礎 schema と AgentRun 関連 follow-up trace を用意済み。AgentRun 本体、AgentRunEvent、Artifact、ContextSnapshot、`agent_runs.parent_run_id` project 境界は SP-004 で閉じる。
- SP-003 Policy / Approval: action class、policy decision、approval request、self-approval 禁止、stale invalidation を実装し、SP-004 で `waiting_approval` / `blocked` / resume path へ接続する。

## 前提 / 制約

- P0 は個人専用、Tailscale 閉域、単一 VPS、Docker Compose で運用する。
- Backend は FastAPI、worker は arq、DB は PostgreSQL、coordination は Redis、frontend は Next.js を前提にする。
- tenant 境界と project 境界は `agent_runs` / `artifacts` / `context_snapshots` / `agent_run_events` の全 table で維持する。
  - `tenant_id` は必須。
  - project boundary は `project_id` を直接保持するか、`agent_runs(tenant_id, project_id, id)` への複合 FK / service contract で閉じる。
  - `id` 単独 FK は禁止する。
- actor / principal / approval は SP-001 / SP-003 で確立済みの境界を使う。
- AgentRunEvent は `actor_id` を必須にし、provider / worker / service actor も actors table の tenant 境界に従う。
- SecretBroker は SP-002 で schema 基礎を持ち、SP-004 で issue / redeem の本実装を行う。redeem は atomic claim であり、AI / runner / artifact / audit に raw secret を出さない。
- Provider call は SP-005 で本実装する。SP-004 では `payload_data_class` / `allowed_data_class` 境界、provider fingerprint、preflight deny を受ける status mapping の準備に止める。
- AI 出力は artifact pipeline を通す。command、SQL、workflow、repo write、external mutating tool、secret resolve に直接接続しない。
- 本 ADR は ADR Gate Criteria #3 API 契約 / event schema、#4 AI エージェント権限、#2 DB schema、**#6 Secrets 管理方式** に該当する。AgentRun status、AgentRunEvent、ContextSnapshot、SecretBroker issue / redeem は high-risk として実装前 ADR を必須にする。Secrets 管理方式は ADR-00006 が accepted (2026-05-09) で正本となるが、SecretBroker 接続点は本 ADR と SP-004 で初めて runtime に組み込まれるため #6 にも該当する。
- 関連 ADR (整合確認済):
  - ADR-00002 (DB schema、proposed): tenant / project 境界、複合 FK、`agent_runs(tenant_id, project_id, id)` 複合 unique、`id` 単独 FK 禁止の前提を共有する。AgentRun 本体 / AgentRunEvent / Artifact / ContextSnapshot / `agent_runs.parent_run_id` の table 設計は本 ADR + SP-004 で確定する。
  - ADR-00006 (Secrets management、accepted at 2026-05-09): SecretBroker issue / redeem の atomic claim、OperationContext canonical fingerprint、raw secret 非露出方針を SP-004 の本実装で踏襲する。secret 値が AgentRun / AgentRunEvent / ContextSnapshot に漏れないことを本 ADR の event payload contract で強制する。
  - ADR-00009 (Action class taxonomy、accepted): `task_write` / `repo_write` / `pr_open` / `secret_access` / `merge` / `deploy` / `provider_call` の 7 種が `policy_blocked` reason_code source となり、本 ADR の `blocked` + `policy_blocked` 接続点に対応する。SP-003 の self-approval 禁止 / stale invalidation は本 ADR の `waiting_approval` / `blocked` / resume path 設計に整合する。
  - ADR-00010 (Provider 追加 / 切替、proposed): Provider Compliance Matrix、`payload_data_class` / `allowed_data_class` ordinal、conditional ZDR の `condition_status=verified` 解禁条件は SP-005 で本実装するが、本 ADR の `provider_refused` / `provider_incomplete` / `validation_failed` / `blocked` + `policy_blocked` mapping の前提となる。`provider_request_fingerprint` (ContextSnapshot 10 カラムの 1 つ) は ADR-00010 の Matrix version + provider request fingerprint と整合する。

## 選択肢

| 選択肢 | 概要 | 利点 | 欠点 / リスク |
|---|---|---|---|
| A: 16 状態 + blocked サブ 3 | `.claude/rules/agentrun-state-machine.md` と DD-03 の通り、status は 16 状態に固定し、`blocked_reason` で `policy_blocked` / `budget_blocked` / `runtime_blocked` を表現する | artifact pipeline、provider partial result、repair retry、approval resume、budget stop、runner block を過不足なく表現できる。DB / API / frontend / fixture の contract test にしやすい | state machine 実装、event writer、transition guard、drift test が必要 |
| B: 19 状態 | `policy_blocked` / `budget_blocked` / `runtime_blocked` を status enum に flatten し、`blocked` を分割する | UI 表示は単純に見える | `blocked` の resume / 解除 path が状態爆発する。approval / budget / runtime の意味論差を status enum に閉じ込められない。DD-03 と `.claude/rules/agentrun-state-machine.md` に反する |
| C: 軽量 5 状態 | `queued` / `running` / `completed` / `failed` / `cancelled` のみを扱う | 実装初期コストは低い | AI artifact pipeline 7 stage、provider refusal / incomplete、schema validation、policy lint、diff gate、approval、repair retry exhaustion、budget blocked を説明できない |

## 採用案

- 採用: A: 16 状態 + blocked サブ 3。
- 理由: TaskManagedAI の価値は、AI 作業を「実行した / 失敗した」ではなく、artifact、schema validation、policy lint、approval、runner / repo action、provider result、repair retry、audit event から説明できることにある。16 状態 + blocked サブ 3 は、PRD-01 F-008 / F-009、DD-03、AI Output Boundary、SP-004 must_ship と一致する最小の状態集合である。
- 実装 Sprint: SP-004 で proposed のまま実装着手可能にし、実装後 review で DB / API / frontend / fixture drift がないことを確認して accepted 化する。SP-005 / SP-007 で provider / runner の追加 event と mapping を接続する。

### AgentRun status enum 16 状態

| No | status | terminal | 用途 |
|---:|---|---:|---|
| 1 | `queued` | no | AgentRun 作成直後 |
| 2 | `gathering_context` | no | ContextSnapshot 作成、repo_state / tool_manifest / evidence_set_hash 確定 |
| 3 | `running` | no | provider / validator / approval resume / runner or repo action の実行中 |
| 4 | `generated_artifact` | no | provider structured output から artifact が保存された状態 |
| 5 | `schema_validated` | no | JSON Schema / Pydantic / Zod validation 通過 |
| 6 | `policy_linted` | no | action class / data class / forbidden path / secret canary lint 通過 |
| 7 | `diff_ready` | no | patch path / diff size / command plan / runtime cap 確認済み |
| 8 | `waiting_approval` | no | approval request 作成後、人間判断待ち |
| 9 | `blocked` | no | policy / budget / runtime 起因で停止中。理由は `blocked_reason` で表現 |
| 10 | `provider_refused` | yes | provider refusal / safety refusal |
| 11 | `provider_incomplete` | no | max token、途中停止、retry / continuation 可能な incomplete |
| 12 | `validation_failed` | no | schema mismatch / unsupported schema / validation error。repair retry 対象 |
| 13 | `repair_exhausted` | yes | repair retry 上限到達 |
| 14 | `completed` | yes | success terminal |
| 15 | `failed` | yes | unrecoverable failure terminal |
| 16 | `cancelled` | yes | user / system cancel terminal |

### blocked_reason 3 種

`blocked` は status として 1 状態だけにする。`blocked_reason` は次の 3 種のみを許可する。

| blocked_reason | 用途 | resume 条件 |
|---|---|---|
| `policy_blocked` | policy deny、provider request preflight deny、data class deny、approval rejected / stale | approval / policy 更新後のみ resume 可能 |
| `budget_blocked` | hard limit、global kill switch、budget exceeded | budget 更新後のみ resume 可能 |
| `runtime_blocked` | runner path deny、dangerous command、resource cap、patch / command plan 修正が必要な停止 | plan / patch 修正後のみ resume 可能 |

DB invariant:

- `status='blocked'` なら `blocked_reason is not null`。
- `status<>'blocked'` なら `blocked_reason is null`。
- `blocked_reason` を status enum に増やさない。
- 16 状態 + blocked サブ 3 を 19 状態として実装しない。

### terminal state 5 種

terminal state は次の 5 種に固定する。

- `completed`
- `failed`
- `cancelled`
- `provider_refused`
- `repair_exhausted`

terminal state からの resume / retry / transition は不可とする。terminal state に対する cancel request、repair retry、approval resume、provider continuation は service guard で reject し、必要なら audit / error event に raw secret なしで記録する。

### 標準遷移 + 例外遷移

標準遷移は `.claude/rules/agentrun-state-machine.md` §4 と完全一致させる。

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

例外遷移も同じく固定する。

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

transition guard は、現在 status、遷移先 status、`blocked_reason`、actor、approval state、budget state、retry count、provider continuation availability を検証する。guard を通らない遷移は DB 更新前に reject する。

### ContextSnapshot 必須 10 カラム

ContextSnapshot は PRD-01 F-009 / DD-03 / DD-02 と一致する次の 10 カラムを必須 contract とする。

| No | column | 内容 |
|---:|---|---|
| 1 | `prompt_pack_version` | system prompts / templates の lock 版 |
| 2 | `prompt_pack_lock` | 複数 pack を組み合わせた場合の配列ロック |
| 3 | `policy_version` | policy rules 適用時のバージョン |
| 4 | `policy_pack_lock` | 複数 policy pack の配列ロック |
| 5 | `repo_state` | commit SHA / branch / dirty flag / diff hash |
| 6 | `tool_manifest` | tool registry version + tool allowlist hash |
| 7 | `evidence_set_hash` | NFC UTF-8 + JCS canonical JSON + claim_id / source_id 昇順 + URL 正規化 + PROV bundle hash |
| 8 | `provider_continuation_ref` | `{provider, kind, artifact_ref, sha256, expires_at, exportable=false}`。本体は短期 artifact とし、監査 export から除外 |
| 9 | `provider_request_fingerprint` | `{provider, model_requested, model_resolved, api_version, sdk_version, region, temperature, top_p, max_tokens, safety_settings, tool_schema_hash, response_format_schema_hash}` |
| 10 | `snapshot_kind` | `input` / `pre_tool` / `post_tool` / `resume` / `final` |

`provider_continuation_ref` は secret 値、provider key、export 不可 provider state 本体を含めない。監査 export では `exportable=false` を尊重する。

### snapshot_kind 5 種

`snapshot_kind` は次の 5 種に固定する。

| snapshot_kind | 作成タイミング |
|---|---|
| `input` | run 開始時、Provider / runner に渡す前の初期入力 |
| `pre_tool` | tool / runner 前 |
| `post_tool` | tool / runner 後 |
| `resume` | retry / resume 前 |
| `final` | terminal state 前後 |

repair retry と blocked resume の前には `snapshot_kind=resume` を作成する。terminal 前後には `snapshot_kind=final` を作成し、最終状態を event と snapshot の両方から説明できるようにする。

### AgentRunEvent schema

AgentRunEvent は append-only の正本であり、status column だけを正本にしない。

| field | 必須 | contract |
|---|---:|---|
| `id` | yes | event row id。DB 実装は bigserial または uuid のどちらでもよいが、外部 contract は `tenant_id` + `run_id` + `seq_no` を順序の正本にする |
| `tenant_id` | yes | tenant 境界。全 query / FK / unique に含める |
| `run_id` | yes | AgentRun 参照。project boundary は AgentRun の `(tenant_id, project_id, id)` に閉じる |
| `seq_no` | yes | run 内順序。`(tenant_id, run_id, seq_no)` unique |
| `event_type` | yes | allowlist された event type |
| `event_payload` | yes | JSON payload。raw secret、provider key、capability token 生値、raw canary 値を含めない |
| `actor_id` | yes | human / service / agent / provider / github_app actor。`tenant_id` を含む FK |
| `idempotency_key` | operation dependent | non-null の場合、`(tenant_id, run_id, idempotency_key)` で重複防止 |
| `created_at` | yes | event append 時刻 |

status update と AgentRunEvent append は同一 DB transaction で成立させる。status update が成功して event append が失敗する状態、または event append だけ成功して status update が失敗する状態を許可しない。

### Event type allowlist

P0 の AgentRunEvent は次を初期 allowlist とする。

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
| `runner_started` | Docker isolated runner 起動 |
| `runner_completed` | runner 完了。exit code、resource cap 結果を含む |
| `runner_blocked` | runner sandbox deny。forbidden path / dangerous command / resource cap |
| `repo_pr_opened` | RepoProxy 経由で Draft PR 作成 |
| `run_completed` | success terminal |
| `run_failed` | failure terminal |
| `run_cancelled` | cancel terminal |

SP-007 で runner 本実装を行うまでは、`runner_started` / `runner_completed` / `runner_blocked` は schema と contract test に先に含め、実 event 発火は runner boundary 実装時に接続する。

### Provider result mapping

Provider result は `.claude/rules/agentrun-state-machine.md` §7 と一致する mapping に固定する。

| provider result | AgentRun status |
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

`payload_data_class > allowed_data_class`、provider / feature 未登録、`payload_data_class` 未設定、secret canary preflight deny は provider に送信せず、`blocked` + `policy_blocked` とする。

### repair retry

- repair retry 対象は `validation_failed` のみ。
- repair retry 上限は BudgetGuard / policy に持つ。
- retry ごとに ContextSnapshot `snapshot_kind=resume` を作る。
- retry input は previous artifact と validation error の redacted summary に限定する。
- raw provider response、raw secret、provider key、capability token 生値を retry prompt に入れない。
- retry 可能なら `validation_failed -> running`。
- 上限到達時は `validation_failed -> repair_exhausted`。
- `repair_exhausted` は terminal であり、そこから retry しない。

### cancel propagation

- cancel は API から worker / runner / provider cancellation boundary へ伝播する。
- cancellation request と cancellation completion は AgentRunEvent に残す。
- worker は安全な境界で停止する。
- runner / provider が即時停止できない場合は timeout と kill policy を使う。
- cancel 完了時は `cancelled`。
- `cancelled` は terminal。
- cancel 後に provider call、repo write、runner action を継続しない。

### approval / policy / budget 解消後の resume

- `blocked` は原因解消後に resume できる。
- `policy_blocked` は approval / policy 更新後のみ resume できる。
- `budget_blocked` は budget 更新後のみ resume できる。
- `runtime_blocked` は plan / patch 修正後のみ resume できる。
- `provider_incomplete` は retry / continuation が可能な場合のみ `running` へ戻れる。
- resume 前に ContextSnapshot `snapshot_kind=resume` を作る。
- stale approval は resume せず、再承認を要求する。
- terminal state は resume 不可。

## 却下案 (詳細)

- B: 19 状態は却下する。`policy_blocked` / `budget_blocked` / `runtime_blocked` は、いずれも「解除条件が異なる blocked」であって、独立した lifecycle status ではない。status enum に flatten すると、`blocked -> waiting_approval`、`blocked -> running`、`blocked -> failed` の resume / 解除 path が 3 倍に分岐し、transition guard と frontend 表示が状態爆発する。また、approval / budget / runtime の意味論差は policy / budget / runner service の判断に残すべきで、status enum に閉じ込めると SP-005 / SP-007 の拡張時に drift する。DD-03 と `.claude/rules/agentrun-state-machine.md` は 16 状態 + blocked サブ 3 を正本としており、19 状態実装はこの正本に反する。
- C: 軽量 5 状態は却下する。`queued` / `running` / `completed` / `failed` / `cancelled` だけでは、AI Output Boundary の `artifact -> schema_validated -> policy_linted -> diff_ready -> approval_required -> waiting_approval -> runner_or_repo_action` を event / status から説明できない。provider refusal、provider incomplete、unsupported schema、schema mismatch、repair retry exhaustion、policy deny、budget exceeded、runtime blocked をすべて `failed` に押し込むと、再開可能な停止と terminal failure の区別が消える。結果として Eval fixture、approval invalidation、cost / retry policy、audit review が壊れる。

## リスク

| リスク | 検知方法 | 軽減策 |
|---|---|---|
| 状態 enum drift (DB / API / frontend / fixture) | enum cross-source 一致 test。DB CHECK、Pydantic Literal、frontend Zod、fixture schema の 4 source を比較 | 16 状態を shared source から生成するか、CI smoke で drift を release blocker にする |
| `blocked_reason` を status に増やす提案の再発 | status enum test で `policy_blocked` / `budget_blocked` / `runtime_blocked` が status に存在しないことを assert | 本 ADR と DD-03 を正本にし、UI 表示では status + blocked_reason の derived label を使う |
| terminal state からの resume 試行 | `completed` / `failed` / `cancelled` / `provider_refused` / `repair_exhausted` それぞれの negative transition test | state_machine guard で reject し、service/API は terminal resume を 409 相当で返す |
| repair retry の race | validation_failed から並行 retry を発火する concurrent test | retry count 更新、snapshot 作成、event append、status update を同一 transaction にする |
| ContextSnapshot 10 カラム drift | migration introspection test、Pydantic schema test、snapshot_kind enum drift test | PRD-01 F-009 / DD-03 / `.claude/CLAUDE.md` の 10 カラムを contract test 化する |
| AgentRunEvent seq_no race | concurrent insert test で `(tenant_id, run_id, seq_no)` unique violation / retry handling を確認 | run 単位 lock、transaction 内 seq allocation、idempotency_key reuse detection を実装する |
| status update と event append の transaction 分離 | fault injection test で event append failure / status update failure を発生させる | state transition service 以外から status を更新しない。DB transaction helper を 1 箇所に集約する |
| provider result mapping drift | mapping table test で refusal / incomplete / unsupported schema / preflight deny / budget exceed を検証 | SP-005 ProviderAdapter contract test に ADR-00004 mapping を読み込ませる |
| cancel propagation 不完全 | cancel 後の provider call / repo write / runner action 継続を検出する test | API -> worker -> provider / runner boundary の cancellation event と timeout / kill policy を実装する |

## rollback

### Migration rollback

1. enum / DB CHECK / column 追加は Alembic migration で reversible にする。P0 では PostgreSQL enum 型より text + CHECK を優先し、downgrade で CHECK / column drop を可能にする。
2. migration 適用前に `pg_dump` で full DB backup を取得し、age で暗号化して別ボリュームへ保存する。restore drill で復号確認する。
3. staging DB で `uv run alembic upgrade head`、`alembic check`、AgentRun status enum、blocked_reason consistency、AgentRunEvent seq/idempotency、ContextSnapshot 10 カラム、parent_run project boundary の contract test を実行する。
4. production migration 後に、16 状態 enum 不一致、`blocked_reason` consistency 違反、ContextSnapshot 10 カラム欠落、AgentRunEvent unique / idempotency 不整合、status/event transaction 分離、terminal resume 成功のいずれかを検出したら rollback trigger とする。
5. `uv run alembic downgrade -1` で 1 step 戻す。downgrade が event history や terminal state と不整合になる場合は、downgrade ではなく forward-fix migration を新規作成し、staging 検証後に production 適用する。
6. rollback verification は Agent Runtime contract test 一式を実行し、status enum、blocked_reason CHECK、transition guard、event ordering、ContextSnapshot 10 カラムが rollback 後も説明可能であることを確認する。

### Event schema rollback

1. AgentRunEvent schema を変更する必要が出た場合、既存 event を破壊的に rewrite しない。
2. `event_schema_version` または event payload version を追加し、新旧 schema の dual-write / dual-read transition を置く。
3. consumer が新旧両方を読めることを確認してから旧 schema write を止める。
4. raw secret / provider key / capability token 生値を含む event が検出された場合は、該当 payload を quarantine / redaction し、原因となった writer を停止してから再開する。

### 状態定義 rollback / defer

1. 重大な状態定義変更が必要になった場合、SP-004 内で ad-hoc に enum を変えない。
2. Sprint Pack の `defer_if_over_budget` または後続 Sprint の ADR 更新として扱う。
3. 既存 16 状態 + blocked サブ 3 で表現できる場合は、status を増やさず event payload / reason_code / metadata で表現する。
4. status 追加が不可避な場合は、DB / API / frontend / fixture の 4 source drift test、migration rollback、existing event replay 方針を ADR 更新に含める。

## 実装対象ファイル + テスト指針

### 実装対象ファイル

- `backend/app/db/models/agent_run.py`
- `backend/app/db/models/agent_run_event.py`
- `backend/app/db/models/artifact.py`
- `backend/app/db/models/context_snapshot.py`
- `backend/app/services/agent_runtime/state_machine.py`
- `backend/app/services/agent_runtime/event_log.py`
- `migrations/versions/0008_agent_runs_lifecycle.py` (推定 revision)
- `tests/runtime/test_agentrun_status_enum.py`
- `tests/runtime/test_agentrun_transitions.py`
- `tests/runtime/test_agent_run_events.py`
- `tests/runtime/test_context_snapshot_invariants.py`

必要に応じて、frontend Zod / API schema / fixture schema 側にも AgentRun status、`blocked_reason`、`snapshot_kind` の generated or checked source を置く。ただし正本は本 ADR、DD-03、`.claude/rules/agentrun-state-machine.md` とする。

### テスト指針

- enum cross-source 一致 test:
  - DB CHECK
  - Pydantic Literal
  - frontend Zod
  - fixture schema
  - 上記 4 source が 16 状態と完全一致することを確認する。
- `blocked_reason` consistency negative test:
  - `status='blocked'` かつ `blocked_reason is null` を reject。
  - `status<>'blocked'` かつ `blocked_reason is not null` を reject。
  - `policy_blocked` / `budget_blocked` / `runtime_blocked` が status enum に混入していないことを確認。
- terminal state from-not-allowed negative test:
  - `completed` / `failed` / `cancelled` / `provider_refused` / `repair_exhausted` から resume / retry / cancel / running 遷移を reject。
- transition guard test:
  - 標準遷移と例外遷移だけが通ることを確認。
  - unknown transition は service guard で reject。
- AgentRunEvent seq_no race concurrent insert test:
  - 同一 `(tenant_id, run_id)` への並行 append で seq_no 重複が成功しないことを確認。
  - idempotency_key の重複 request が二重 event にならないことを確認。
- status update + event append same transaction test:
  - status update 成功 + event append 失敗の片側成功を許可しない。
  - event append 成功 + status update 失敗の片側成功を許可しない。
- ContextSnapshot 10 カラム full present test:
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
  - 上記が DB / Pydantic / fixture で欠落しないことを確認。
- snapshot_kind enum drift test:
  - `input` / `pre_tool` / `post_tool` / `resume` / `final` のみ許可。
- provider result mapping table test:
  - refusal -> `provider_refused`
  - safety refusal -> `provider_refused`
  - max token / incomplete -> `provider_incomplete`
  - timeout retryable -> `provider_incomplete` または `failed`
  - unsupported schema -> `validation_failed`
  - schema mismatch -> `validation_failed`
  - provider request preflight deny -> `blocked` + `policy_blocked`
  - data class deny -> `blocked` + `policy_blocked`
  - budget exceeded -> `blocked` + `budget_blocked`
  - success structured output -> `generated_artifact`
- repair retry exhaustion path test:
  - `validation_failed -> running` の retry が上限内だけ許可されること。
  - 上限到達で `repair_exhausted` になること。
  - `repair_exhausted` から retry できないこと。
- cancel propagation test:
  - cancel request が AgentRunEvent に残ること。
  - worker / provider / runner boundary へ cancel が伝播すること。
  - cancel 後に provider call / repo write / runner action が継続しないこと。
- raw secret 非混入 test:
  - AgentRunEvent `event_payload`
  - ContextSnapshot
  - Artifact metadata
  - audit payload
  - 上記に raw secret、provider key、GitHub installation token、capability token 生値、raw canary 値が含まれないことを確認する。

---

## Phase D R1-R4 + Phase E Multi-Agent vision update (2026-05-10、proposed 追記)

ADR-00014/15/16/17/18/19/20 (Multi-Agent vision) accepted 化に伴う本 ADR の update (Phase D 40 + Phase E 16 = 計 56 finding 反映)。本 update は **既存 16 状態 + blocked サブ 3 + ContextSnapshot 10 列 invariant を不変前提** に、event_type と parent/child semantics を additive 拡張のみ。

### event_type 28 → 37 拡張 (SP-014 accepted implementation / PD-R2-F-004 / PE-F-018)

Sprint 6 batch 2 までに P0 baseline は 28 event_type へ拡張済み。SP-014 accepted implementation では既存 28 event_type に追加 9 種を加え、current source は 37 event_type とする:

| # | event_type | state transition | 必須 payload | audit_events |
|---|---|---|---|---|
| 29 | `orchestrator_dispatched` | running | child_run_id, role_id, role_scope, dispatch_reason, recommended_provider | (AgentRunEvent のみ) |
| 30 | `orchestrator_lease_renewed` | running | lease_token_hash, renewed_at, expires_at | (AgentRunEvent のみ) |
| 31 | `orchestrator_lease_expired` | running -> blocked/running | old_lease_hash, expired_at, reason_code | (AgentRunEvent のみ) |
| 32 | `orchestrator_failover_triggered` | running | old/new lease + reason | audit_events `orchestrator_failover` |
| 33 | `orchestrator_kill_engaged` | running -> blocked (runtime_blocked) | engaged_by_actor_id (human only), reason | audit_events `orchestrator_kill_engaged` |
| 34 | `inter_agent_message_sent_ref` | (status 不変) | message_id, payload_hash, seq_no, sender_run_id, receiver_run_id, redaction_status | audit_events `inter_agent_message_sent` |
| 35 | `inter_agent_message_consumed_ref` | (status 不変) | + previous_hash_match | audit_events `inter_agent_message_consumed` |
| 36 | `tool_web_fetch_executed` | running | tool_name, domain, provider, payload_data_class, redaction_status | (AgentRunEvent のみ) |
| 37 | `tool_docs_search_executed` | running | 同上 | 同上 |

5+ source 整合: migration `0025_sp014_event_type_37.py` DB CHECK + ORM CheckConstraint + Python Literal `AgentRunEventType` / `ALL_AGENT_RUN_EVENT_TYPES` (37) + Pydantic schema + pytest `EXPECTED_AGENT_RUN_EVENT_TYPES` + frontend TS enum.

### parent/child semantics

- `agent_runs.parent_run_id` (既存) は multi-agent 文脈で orchestrator → child lineage
- parent / child 各々独立 16 状態進行、parent status は child 状態に依存しない
- SP-014 で agent_runs に追加: `orchestrator_lease_token` / `orchestrator_lease_expires_at` / `lease_renewed_at` / `orchestrator_kill_at` / `last_progress_at` / `progress_seq` / `role_id` / `role_scope`
- failover 時 active child は `cancel_requested -> cancelled` (default) or `blocked + runtime_blocked` (force_kill)、terminal child は不変
- progress lease no-progress 30 分 (tenant_config 5-120 分) で `blocked + runtime_blocked`

### `(tenant_id, project_id, id)` unique 追加 (PD-R2-F-001 / PE-F-007)

SP-013 で agent_runs に `unique (tenant_id, project_id, id)` 追加 → 後続 multi-agent table が `(tenant_id, project_id, foreign_run_id)` 複合 FK を張る基盤.

### 関連 ADR

- ADR-00014 / ADR-00018 / Phase C draft §3.7

---

## Sprint 5.5 Output Validator + Input Trust Layer update (2026-05-10 proposed 追記 / 2026-05-12 Sprint 5.5 着手で accepted)

SP-005-5 (Output Validator) accepted 化に伴う本 ADR の update。**P0 期間中** (Sprint 5.5) で event_type を 22 → 25 に拡張、`repair_exhausted` を terminal 強制、Input Trust Layer の `trust_level` enum (artifact 単体) を導入。当時の Phase D-E P0.1 proposal はこの Sprint 5.5 update により numbering 再調整が必要になり、current final numbering は SP-014 の 28 → 37 に同期済み (詳細は §event_type numbering 整合)。

### event_type 22 → 25 拡張 (P0 期間中、Sprint 5.5 で追加)

既存 22 event_type に Sprint 5.5 で **新規 3 種** を追加 (P0 期間中):

| # | event_type | state transition | 必須 payload (raw secret なし) | 用途 |
|---|---|---|---|---|
| 23 | `repair_exhausted` | `validation_failed -> repair_exhausted` (terminal) | retry_count, last_validation_error_summary (redacted), repair_budget_remaining=0 or policy_max_reached, ContextSnapshot.snapshot_kind=resume の最終 ref | repair retry 上限到達 (policy_pack `repair_retry_max_attempts` または BudgetGuard `repair_budget_remaining` 失効)、terminal state |
| 24 | `trust_level_promoted` | (status 不変) | artifact_id, from_trust_level, to_trust_level, promotion_path (`schema_validation_passed` / `policy_lint_passed` / `human_approval_passed`), approval_request_id (trusted_instruction 昇格時のみ、4 整合 hash) | Input Trust Layer 昇格 (untrusted_content → validated_artifact 自動 / validated_artifact → trusted_instruction = approval) |
| 25 | `trust_level_promotion_denied` | (status 不変) | artifact_id, attempted_trust_level, deny_reason_code (`schema_validation_failed` / `policy_lint_failed` / `approval_4整合_mismatch` / `decider_not_human` / `caller_supplied_path_attempt`), audit trail | Input Trust Layer 昇格 deny (server-owned 経路違反、caller-supplied 試行、Approval 4 整合 mismatch、self-approval 試行 等) |

5+ source 整合 update (`.claude/rules/cross-source-enum-integrity.md` §1 pattern):

- migration `00NN_p0_event_type_25.py` で `agent_run_events.event_type` CHECK 制約を 22 → 25 に拡張
- ORM `backend/app/db/models/agent_run_event.py` の `CheckConstraint`
- Python Literal `backend/app/domain/agent_runtime/event_type.py` の `AgentRunEventType` + `ALL_AGENT_RUN_EVENT_TYPES` (22 → 25)
- Pydantic `agent_run_event` schema
- pytest `tests/runtime/test_agent_run_events.py` の `EXPECTED_AGENT_RUN_EVENT_TYPES` (25)
- frontend TypeScript enum (Sprint 9 で追加、P0 段階では未要)

### Input Trust Layer trust_level enum 追加 (artifact 単体、P0.1 SP-015 で inter_agent_messages 再利用前提)

`artifacts.trust_level` 列追加 (additive only、NOT NULL DEFAULT `'untrusted_content'`):

```sql
alter table artifacts
    add column trust_level text not null default 'untrusted_content'
    check (trust_level in ('untrusted_content', 'validated_artifact', 'trusted_instruction'));
```

5+ source 整合:
- DB CHECK (上記 migration)
- ORM CheckConstraint (`backend/app/db/models/artifact.py`)
- Python Literal (`backend/app/domain/artifact/trust_level.py` 新規、`TRUST_LEVELS: frozenset = {'untrusted_content', 'validated_artifact', 'trusted_instruction'}`)
- Pydantic Field validator
- pytest `tests/input_trust/test_trust_level_enum_drift.py` の `EXPECTED_TRUST_LEVELS`

trust_level 昇格は server-owned のみ (caller-supplied 経路 signature レベル物理削除、`extra="forbid"` schema reject、`.claude/rules/server-owned-boundary.md` §1 invariant 継続)。

### `repair_exhausted` terminal 強制

ADR-00004 §147 terminal state 5 種 (既存定義) に **追加変更なし** (`repair_exhausted` は既存 16 状態の 13 番目で既に terminal 定義済)。Sprint 5.5 では既存 terminal 強制を contract test (`tests/runtime/test_repair_exhausted_terminal.py`) で 16 状態 × invalid transition matrix で full coverage する。

repair retry 上限到達条件 (どちらか一方で `repair_exhausted` 遷移):
1. `policy_pack.repair_retry_max_attempts` (Sprint 5.5 で新規導入、default 3) 到達
2. BudgetGuard `repair_budget_remaining` 0 到達

### event_type numbering 整合 (P0 / P0.1+ 衝突回避)

**履歴**: Phase D-E update は当初 22 → 31 として proposed されたが、Sprint 5.5 で 22 → 25、Sprint 6 batch 2 で 25 → 28 が先行 accepted 化されたため、final accepted numbering は SP-014 の 28 → 37 で固定する:

- **元の Phase D-E numbering (historical proposed)**: 23-31 (orchestrator_dispatched 等 9 種)
- **Sprint 5.5 accepted 化後**: 23-25 (repair / trust_level)
- **Sprint 6 batch 2 accepted 化後**: 26-28 (CLI artifact)
- **SP-014 accepted implementation**: 29-37 (orchestrator / inter-agent refs / tool execution)

本 ADR の SP-014 section が current source であり、historical proposed numbering は invalidated。PD-R2-F-004 / PE-F-018 反映の意味は不変。

5+ source 整合の事実上の影響: P0 期間中は 22 → 25 → 28、P0.1 SP-014 完遂後は 28 → 37。

### audit_events への追加 (本 ADR 範囲外、ADR-00009 update §audit_events と整合)

Sprint 5.5 で audit_events に追加する event_type (本 ADR の AgentRunEvent allowlist とは別 taxonomy、Sprint 5 で確立した 2 taxonomy 分離):

- `output_validation_repair_retry_recorded` (audit-only): repair retry の policy_decision / budget_check 結果
- `trust_level_promotion_audit` (audit-only): trust_level 昇格時の Approval 4 整合 + decider human-only verify
- `trust_level_promotion_denial_audit` (audit-only): 昇格 deny 時の reason_code + raw secret 非露出 verify

これらは ADR-00009 update §Sprint 5.5 audit_events 拡張 (新規追加予定) で扱う。

### 関連 ADR (Sprint 5.5)

- ADR-00009 (action_class taxonomy) update §Sprint 5.5: `repair_retry_max_attempts` policy + `trusted_instruction` 昇格境界 (Approval 4 整合 + decider human-only)
- ADR-00010 (Provider Compliance Matrix v2): payload_data_class 算出を Input Trust Layer 側に集約 (本 Sprint 5.5 で延長、Sprint 5 で確立した caller-supplied 禁止 invariant 継続)
- ADR-00006 (SecretBroker): repair retry context redaction で `assert_no_raw_secret` を retry prompt builder で必須実行
- SP-005-5 §設計判断 + §Rollback section
- `.claude/rules/agentrun-state-machine.md` §6 (Sprint 5.5 / Sprint 6 / SP-014 を反映し、current event_type 37 を正本化済み)

## SP-009-5 request_revision state-machine boundary (2026-05-24 planning note)

SP-009-5 Batch E adds an Approval revision-request loop. The initial E1/E2 implementation must not expand AgentRun status or AgentRunEvent enum values.

### State semantics

- A pending approval receiving `request_revision` becomes `invalidated`.
- The related AgentRun remains in the existing blocked / waiting path until a revised artifact creates a fresh approval request.
- The old approval row never returns to `pending`, and cannot be approved or rejected after invalidation.
- Revised artifact handoff creates a new approval request with fresh `artifact_hash`, `diff_hash`, `policy_version`, `policy_pack_lock`, `provider_request_fingerprint`, and `stale_after_event_seq` binding.

### Event boundary

- E1/E2 must not add `approval_revision_requested` or similar values to `agent_run_events.event_type`.
- The revision request itself is represented by the additive `approval_revision_requests` table plus metadata-only audit and notification events.
- Any future AgentRunEvent enum addition for revision-request runtime flow must be a separate PR that updates DB CHECK, SQLAlchemy CheckConstraint, Python Literal, Pydantic/frontend schema, and pytest expected-set drift tests together.

### Regression requirements

- approving/rejecting an invalidated approval returns conflict
- duplicate open revision requests are rejected
- replacement approval uses fresh decision-packet hashes
- terminal AgentRun states remain non-resumable
- audit and notification payloads do not contain raw rationale or raw artifact content
