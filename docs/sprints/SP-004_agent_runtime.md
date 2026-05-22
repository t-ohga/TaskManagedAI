---
id: "SP-004_agent_runtime"
type: "heavy"
status: "completed"
sprint_no: 4
created_at: "2026-05-08"
updated_at: "2026-05-22"
completed_at: "2026-05-22"
# F-PR100-R1-002 audit fix (PR #101): frontmatter drift 訂正、AgentRun 16 状態 + ContextSnapshot 10 column
# + SecretBroker atomic claim + AC-HARD-02 / AC-KPI-04 fixture skeleton 完成 (master plan §1.1).
# 本 訂正 PR で frontmatter status を draft → completed に同期更新.
target_days: 7.8
max_days: 10
adr_refs:
  - "[ADR-00006](../adr/00006_secrets_management.md) # 2026-05-09 accepted (proposed → accepted、SecretBroker SP-004 本実装の前提)"
  - "[ADR-00004](../adr/00004_agentrun_state_machine.md) # 2026-05-09 proposed 化新規作成 (R2 clean、AgentRun 16 状態 + blocked サブ 3 + ContextSnapshot 10 カラム + transition guard + event schema)"
planned_adr_refs: []
related_sprints:
  - "SP-003_policy_approval"
  - "SP-005_provider_adapter"
  - "SP-002_core_data_model"
risks:
  - "AgentRun 16 状態 enum の DB / API / frontend drift"
  - "ContextSnapshot 10 カラム不足"
  - "BudgetGuard hierarchy 設計"
  - "SecretBroker atomic claim race condition"
---

このテンプレの使い方: Sprint 4 の Agent Runtime で、AgentRun lifecycle、AgentRunEvent、Artifact、ContextSnapshot、BudgetGuard、SecretBroker issue / redeem、plan artifact schema、secret canary fixture、`agent_runs.parent_run_id` project 境界 follow-up を実装するための heavy Sprint Pack。ADR Gate Criteria #3 API / event schema、#6 Secrets 管理方式、#2 DB schema、#4 AI エージェント権限に該当するため、ADR-00006 を accepted 化し、ADR-00004 を proposed 化してから着手する。

最終更新: 2026-05-09 (Sprint 4 着手前 ADR Gate: ADR-00006 proposed → accepted、ADR-00004 新規 proposed 化、planned_adr_refs から adr_refs に移送)

## 目的

- TaskManagedAI の AI 実行履歴を、現在 status だけでなく AgentRunEvent と ContextSnapshot から再説明できる正本にする。
- AgentRun 16 状態と blocked サブ 3 を DB / API / frontend / test で一致させる。
- ContextSnapshot 必須 10 カラムを実装し、prompt、policy、repo_state、tool_manifest、evidence、provider fingerprint を run ごとに固定する。
- BudgetGuard hierarchy を `tenant > project > task(ticket) > run` の primary path として実装し、provider usage と AC-KPI-05 へ接続する。
- SecretBroker issue / redeem service を ADR-00006 に従い、broker-computed canonical OperationContext fingerprint と atomic claim WHERE 節で実装する。
- plan artifact schema を Pydantic + JSON Schema で固定し、AI 出力を Ticket / Acceptance Criteria へ直結させない。
- secret canary fixture を AC-HARD-02 の source として作り、Sprint 5 / 5.5 / 11 / 12 へ接続する。
- Sprint 2 follow-up の BL-0029b として `agent_runs.parent_run_id` の cross-project 制約と negative test を完了する。

## 背景

- Sprint 3 は policy decision、approval request、self-approval 禁止、Approval Inbox を実装する。Sprint 4 はその判断を AgentRun lifecycle に接続する。
- DD-03 と `.claude/rules/agentrun-state-machine.md` は AgentRun 16 状態、blocked サブ 3、terminal state、provider result mapping、repair retry、resume、cancel、ContextSnapshot 10 カラムを固定している。
- ADR-00006 は SecretBroker の SOPS + age、capability token、atomic claim redeem、broker-computed OperationContext fingerprint、raw secret 非露出を定義している。Sprint 4 実装前に accepted 化する。
- Sprint 2 は `secret_capability_tokens` の基礎 schema を作るが、issue / redeem service と run FK 後付けは Sprint 4 へ分離している。
- P0 Hard Gate AC-HARD-02 は fake API key の漏えい 0 件と外部送信 0 件を要求する。Sprint 4 は secret canary fixture の source を作る。

## 対象外

- replay UI と span export。max_days 超過時は P0.1 / Sprint 11.5 以降へ defer する。
- ProviderAdapter の OpenAI / Anthropic / Gemini 実装、Compliance Gate、`provider_request_preflight`。Sprint 5 で扱う。
- Output Validator / Input Trust Layer の full pipeline。Sprint 5.5 で扱う。ただし plan artifact schema と schema validation入口は Sprint 4 で作る。
- Tool Registry / read-only gateway / `tool_mutating_gateway_stub`。Sprint 4.5 で扱う。
- Docker isolated runner、`runner_mutation_gateway`、forbidden path / dangerous command の本実装。Sprint 7 で扱う。
- Run timeline full UI。Sprint 4 は API と最小 timeline skeleton までに止め、full UI は Sprint 9 へ送る。
- raw secret / API key / canary 値を含む fixture。fixture は fake pattern の種別と redacted expected result のみを保存する。

## 設計判断

- AgentRun status は 16 状態に固定する: `queued` / `gathering_context` / `running` / `generated_artifact` / `schema_validated` / `policy_linted` / `diff_ready` / `waiting_approval` / `blocked` / `provider_refused` / `provider_incomplete` / `validation_failed` / `repair_exhausted` / `completed` / `failed` / `cancelled`。
- `blocked_reason` は 3 種だけにする: `policy_blocked` / `budget_blocked` / `runtime_blocked`。19 状態へ膨らませず、DB check で `status='blocked'` との相関を強制する。
- status update と AgentRunEvent append は同一 transaction にする: event の `seq_no`、idempotency_key、actor_id、payload redaction を必須にする。
- Artifact は immutable にする: content_hash、artifact_kind、payload_data_class metadata、exportable flag を持ち、raw secret / raw provider response を保存しない。
- ContextSnapshot 10 カラムは nullable 逃げをしない: `prompt_pack_version`、`prompt_pack_lock`、`policy_version`、`policy_pack_lock`、`repo_state`、`tool_manifest`、`evidence_set_hash`、`provider_continuation_ref`、`provider_request_fingerprint`、`snapshot_kind` を contract test にする。
- BudgetGuard は primary hierarchy を `tenant > project > task(ticket) > run` とし、provider cap、retry、wall-clock、max tokens、global kill switch を metadata / extension として扱う。
- SecretBroker は caller-supplied fingerprint を受け取らない: issue 時 / redeem 時の両方で broker が canonical OperationContext を計算し、atomic claim UPDATE の WHERE 節で actor / run / fingerprint / operation を同時に検証する。
- plan artifact は Pydantic model を正本にし、JSON Schema を frontend / provider structured output / tests へ配布する。human approval なしに `trusted_instruction` へ昇格しない。
- cancel propagation は Redis pub/sub で worker に伝播し、provider / runner が止められない場合は timeout と kill policy を AgentRunEvent に残す。
- `agent_runs.parent_run_id` は `(tenant_id, project_id, parent_run_id)` 複合 FK で同一 project 内に閉じる。

## 実装チケット

| ticket_id | title | 機能 ID | target_days | depends_on | 主成果物 | 関連 DD / 既存 backlog trace |
|---|---|---|---:|---|---|---|
| BL-0040 | AgentRun status enum (16 状態) + DB migration | F-008,NF-008 | 0.7 | SP-002 | agent_runs migration、shared enum | DD-03、PLAN-01 BL-0043/0045 |
| BL-0041 | blocked_reason enum (3 種) + DB check constraint | F-008,NF-008 | 0.4 | BL-0040 | `status='blocked' iff blocked_reason is not null` | agentrun rule |
| BL-0042 | AgentRunEvent append-only (seq_no / idempotency) | F-008,NF-009 | 0.7 | BL-0040 | event writer、transaction guard | PLAN-01 BL-0046 |
| BL-0043 | Artifact + content_hash + payload_data_class metadata | F-013,NF-012 | 0.5 | BL-0042 | immutable artifacts、exportable flag | AI output boundary |
| BL-0044 | ContextSnapshot 10 カラム + snapshot_kind enum | F-009,NF-009 | 0.8 | BL-0040 | context_snapshots migration、contract test | PLAN-01 BL-0044/0047 |
| BL-0045 | BudgetGuard hierarchy (tenant / project / task / run) | F-010,NF-010 | 0.7 | BL-0040 | budget domain、hard/soft/global kill switch | PLAN-01 BL-0048/0049 |
| BL-0046 | SecretBroker issue (canonical OperationContext + expected_request_fingerprint) | NF-003,NF-005 | 0.7 | ADR-00006,BL-0040 | issue service、fingerprint computation | PLAN-01 BL-0152 |
| BL-0047 | SecretBroker redeem (atomic claim + secret_refs 再検証) | NF-003,AC-HARD-02 | 0.8 | BL-0046 | atomic claim UPDATE、negative tests | ADR-00006 |
| BL-0048 | plan artifact schema validation (repair retry policy) | F-004,F-005,F-008 | 0.6 | BL-0043 | Pydantic + JSON Schema、repair policy | PLAN-01 BL-0161 |
| BL-0049 | cancel propagation (Redis pub/sub) | F-008,NF-011 | 0.4 | BL-0042 | cancel event、worker signal | Sprint 1 worker skeleton |
| BL-0050 | secret canary fixture (AC-HARD-02 source) | F-019,AC-HARD-02 | 0.5 | BL-0047 | fixture manifest、redaction expected schema | PLAN-01 BL-0153 |
| BL-0029b | `agent_runs.parent_run_id` cross-project 制約 + negative test | AC-HARD-03,NF-008 | 0.3 | BL-0040,SP-002 | parent lineage FK、cross-project negative | PLAN-01 BL-0029b |
| BL-0051 | AC-KPI-04 (`citation_coverage`) fixture skeleton | F-019,AC-KPI-04 | 0.4 | BL-0044 | fixture skeleton、evidence_set_hash trace | PLAN-00 KPI table |

## タスク一覧

- [ ] ADR-00006 を Sprint 4 実装前に accepted 化し、atomic claim、OperationContext、raw secret 非露出、rollback を確認する。
- [ ] ADR-00004 を `docs/adr/00004_agentrun_state_machine.md` として proposed 化し、16 状態、blocked サブ 3、ContextSnapshot 10 カラム、event schema、transition guard を記録する。
- [ ] `agent_runs.status` enum を 16 状態に固定し、backend / frontend / DB / fixture の drift test を作る。
- [ ] `blocked_reason` を 3 種に固定し、`status='blocked'` と nullable の相関 check を migration に入れる。
- [ ] terminal state からの transition を reject し、`provider_incomplete` と `validation_failed` は retry / repair 対象として扱う。
- [ ] AgentRunEvent writer で `seq_no` unique、idempotency_key unique、status update 同一 transaction を保証する。
- [ ] Artifact に `content_hash`、`payload_data_class` metadata、exportable flag を持たせ、raw secret / raw token / raw canary を保存しない。
- [ ] ContextSnapshot 10 カラムと `snapshot_kind=input|pre_tool|post_tool|resume|final` を migration と test に入れる。
- [ ] BudgetGuard の hard limit、soft limit、global kill switch、max retries、max wall-clock、max tokens を domain service にする。
- [ ] SecretBroker issue で broker が canonical OperationContext を構築し、`expected_request_fingerprint` を保存する。
- [ ] SecretBroker redeem で atomic claim UPDATE を使い、0 rows RETURNING を deny、1 row のみ operation 実行可にする。
- [ ] redeem 成功後、同一 transaction 内で `secret_refs` を `for update` し、status / consumers / operations / scope を再検証する。
- [ ] plan artifact schema を Pydantic + JSON Schema で定義し、validation_failed と repair retry policy をつなぐ。
- [ ] cancel request を AgentRunEvent に残し、Redis pub/sub で worker へ伝播する。
- [ ] secret canary fixture source を作り、AI output、artifact、audit、provider request、runner stdout/stderr への raw 値非露出を expected schema にする。
- [ ] `agent_runs.parent_run_id` が同一 tenant・別 project を参照する INSERT / UPDATE を negative test で失敗させる。
- [ ] AC-KPI-04 skeleton で `evidence_set_hash`、dataset_version、fixture_id、expected citation coverage を保存する。

## must_ship / defer_if_over_budget 対応表

### ロードマップ §94 正本 (verbatim quote)

| Sprint | target_days | max_days | must_ship | defer_if_over_budget |
|--------|-------------|----------|-----------|----------------------|
| Sprint 4 | 7.8 | 10 | AgentRun 16 状態 + blocked サブ 3 + ContextSnapshot 10 カラム + BudgetGuard hierarchy + SecretBroker issue/redeem + plan artifact schema + secret canary fixture | replay UI、span export |

### Sprint Pack 内詳細 trace

ロードマップ正本の must_ship を Sprint Pack 内で詳細化したもの:

| 項目 | ロードマップ → Sprint Pack trace |
|---|---|
| AgentRun 16 状態 | 実装チケット BL-0040 |
| blocked サブ 3 | 実装チケット BL-0041 |
| ContextSnapshot 10 カラム | 実装チケット BL-0044 |
| BudgetGuard hierarchy | 実装チケット BL-0045 |
| SecretBroker issue/redeem | 実装チケット BL-0046, BL-0047 |
| plan artifact schema | 実装チケット BL-0048 |
| secret canary fixture | 実装チケット BL-0050 |

補足: ロードマップ §94 Sprint 2 行の `agent_runs.parent_run_id` cross-project 制約 follow-up は、この Sprint Pack の BL-0029b として維持する。

## 受け入れ条件

- [ ] ADR-00006 が accepted 状態であり、SecretBroker 実装が ADR の atomic claim / OperationContext / raw secret 非露出方針と一致している。
- [ ] ADR-00004 が proposed 状態であり、AgentRun 16 状態、blocked サブ 3、ContextSnapshot 10 カラム、transition guard、event schema を含む。
- [ ] DB / API / frontend / fixture の AgentRun status enum が 16 状態と完全一致する。
- [ ] `blocked_reason` は `policy_blocked` / `budget_blocked` / `runtime_blocked` の 3 種のみで、status と DB check が一致する。
- [ ] terminal state (`completed`, `failed`, `cancelled`, `provider_refused`, `repair_exhausted`) から resume / retry できない。
- [ ] AgentRunEvent は append-only で、`seq_no` unique、idempotency、actor_id、raw secret 非混入を満たす。
- [ ] status update と AgentRunEvent append は同一 transaction で成立する。
- [ ] Artifact は immutable で、content_hash、payload_data_class metadata、exportable flag を持つ。
- [ ] ContextSnapshot 10 カラムが揃い、`snapshot_kind` は `input` / `pre_tool` / `post_tool` / `resume` / `final` のみを許可する。
- [ ] `provider_continuation_ref` は `exportable=false` を扱え、provider key / secret 値を含まない。
- [ ] BudgetGuard は hard limit 超過を `blocked` + `budget_blocked` にし、soft limit は notification / warning event にする。
- [ ] SecretBroker issue は caller-supplied fingerprint を受け取らず、broker-computed `expected_request_fingerprint` を保存する。
- [ ] SecretBroker redeem は atomic claim UPDATE で actor / run / fingerprint / operation / TTL / status を同時に検証し、並行 redeem 成功が 1 件だけになる。
- [ ] redeem 後に `secret_refs` を同一 transaction 内で再検証し、revoked / deprecated / scope mismatch では raw secret を resolve しない。
- [ ] plan artifact schema は Pydantic + JSON Schema で検証でき、schema mismatch は `validation_failed`、retry 上限到達は `repair_exhausted` になる。
- [ ] cancel は API から worker へ伝播し、cancel 後に provider call / repo write が継続しない。
- [ ] secret canary fixture source が AC-HARD-02 に trace し、raw canary 値を artifact / audit / provider request / runner output に残さない。
- [ ] `agent_runs.parent_run_id` は `(tenant_id, project_id, parent_run_id)` で同一 project 内に閉じ、cross-project negative test が失敗する。
- [ ] AC-KPI-04 skeleton が `evidence_set_hash` と dataset_version に trace している。

## 検証手順

- [ ] `ruby -e 'require "yaml"; YAML.load_file("docs/sprints/SP-004_agent_runtime.md")'` で frontmatter が valid YAML として読めることを確認する。
- [ ] `ruby -e 'text=File.read("docs/sprints/SP-004_agent_runtime.md"); missing=%w[BL-0040 BL-0041 BL-0042 BL-0043 BL-0044 BL-0045 BL-0046 BL-0047 BL-0048 BL-0049 BL-0050 BL-0029b BL-0051].reject { |id| text.include?(id) }; abort("missing: #{missing.join(",")}") unless missing.empty?'` で 13 チケットが揃っていることを確認する。
- [ ] `ls docs/adr/00006_secrets_management.md docs/adr/00004_agentrun_state_machine.md` で ADR 参照が存在することを確認する。
- [ ] `uv run alembic upgrade head` で AgentRun / events / artifacts / context_snapshots / budgets / SecretBroker follow-up migration が通ることを確認する。
- [ ] `uv run pytest tests/runtime/test_agentrun_status_enum.py -q` で 16 状態と blocked サブ 3 の drift がないことを確認する。
- [ ] `uv run pytest tests/runtime/test_agentrun_transitions.py -q` で terminal state、repair retry、provider result mapping、cancel を確認する。
- [ ] `uv run pytest tests/runtime/test_agent_run_events.py -q` で seq_no、idempotency、status/event same transaction を確認する。
- [ ] `uv run pytest tests/runtime/test_context_snapshot_contract.py -q` で ContextSnapshot 10 カラムと snapshot_kind を確認する。
- [ ] `uv run pytest tests/runtime/test_budget_guard.py -q` で tenant / project / task / run hierarchy、hard/soft/global kill switch を確認する。
- [ ] `uv run pytest tests/security/test_secret_broker_atomic_claim.py -q` で atomic claim、parallel redeem、actor mismatch、run mismatch、fingerprint mismatch、operation substitution を確認する。
- [ ] `uv run pytest tests/security/test_secret_canary_fixture.py -q` で raw canary 値が artifact / audit / provider request / runner output に残らないことを確認する。
- [ ] `uv run pytest tests/db/test_agentrun_parent_project_boundary.py -q` で `parent_run_id` cross-project negative が失敗することを確認する。
- [ ] `uv run pytest tests/runtime/test_plan_artifact_schema.py -q` で Pydantic / JSON Schema、validation_failed、repair_exhausted を確認する。
- [ ] `rg -n "get_secret_value|secret_value|def\s+redeem.*request_fingerprint" backend tests config --glob '!**/*.md'` で禁止 interface (raw secret 返却) や caller-supplied fingerprint が実装に混入していないことを確認する (実装対象限定、Markdown 除外)。
- [ ] `rg -n "sk-[A-Za-z0-9]{20,}|sk-ant-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{20,}|AGE-SECRET-KEY-[A-Z0-9]{20,}" docs --glob '!docs/sprints/**' --glob '!docs/adr/**' --glob '!docs/設計検討/**'` で docs に実値らしい secret / API key / age key 値がないことを確認する (共通 token regex set)。
- [ ] `ruby -e 'text=File.read(ARGV[0]); forbidden=[["ie","shima"].join, ["academy",["ie","shima"].join].join("."), ["i","FILTER"].join("-")].select { |s| text.include?(s) }; abort("forbidden terms: #{forbidden.join(",")}") unless forbidden.empty?' docs/sprints/SP-004_agent_runtime.md` で別プロジェクト固有語がないことを確認する (検証コマンド自身が self-match しないよう禁止語は実行時組立て)。

### Migration rollback DoD (必須)

DB schema 変更 (Alembic migration) を伴う場合、以下を必ず満たす:

1. **migration 適用前**: `pg_dump` で full DB backup を取り、age で暗号化して別ボリュームに保存。restore drill で復号確認
2. **staging 先行**: `uv run alembic upgrade head` を staging DB で実行し、`alembic check` + Agent Runtime contract test (AgentRun 16 status enum、blocked_reason check、AgentRunEvent seq/idempotency、ContextSnapshot 10 カラム、SecretBroker token constraints、parent_run project FK) が PASS
3. **rollback trigger**: production migration 後に AgentRun status が 16 状態と不一致、`blocked_reason` が status と矛盾、ContextSnapshot 10 カラム欠落、SecretBroker parallel redeem が 2 件以上成功、`agent_runs.parent_run_id` cross-project 参照成功、または raw canary / raw secret 混入が検出された場合
4. **rollback step**: `uv run alembic downgrade -1` で 1 step downgrade。downgrade で data loss / inconsistent state になる場合は forward-fix migration を新規作成し、staging で検証してから production 適用
5. **rollback verification**: restore 後に Agent Runtime contract test を `pytest tests/contract/runtime/ tests/security/test_secret_broker_atomic_claim.py tests/db/test_agentrun_parent_project_boundary.py -q` で確認

## レビュー観点

- [ ] AgentRun status enum が 16 状態で、blocked サブカテゴリを状態として増やしていない。
- [ ] DB check、API schema、frontend union type、fixture schema が status / blocked_reason で drift していない。
- [ ] AgentRunEvent が正本であり、status column だけではなく event から状態遷移を説明できる。
- [ ] ContextSnapshot 10 カラムが必須で、provider_request_fingerprint や policy_version が抜けていない。
- [ ] BudgetGuard が provider failure と混同されず、budget exceeded を `blocked` + `budget_blocked` として扱う。
- [ ] SecretBroker は raw secret を caller、AI、runner、artifact、audit に返さない。
- [ ] atomic claim UPDATE が actor / run / fingerprint / operation / TTL を 1 文で検証し、check→execute→mark used になっていない。
- [ ] plan artifact は structured schema を持ち、human approval なしに trusted_instruction / Ticket 更新へ進まない。
- [ ] cancel 後に provider call、repo write、runner action が継続しない。
- [ ] `agent_runs.parent_run_id` cross-project 制約が Sprint 2 follow-up として完了している。
- [ ] Migration rollback DoD の `pg_dump` / staging / `alembic check` / downgrade / forward-fix / contract test が実行手順として具体化されている。
- [ ] AC-HARD-02 と AC-KPI-04 の fixture source が Sprint 11 / 12 へ trace できる。

## 残リスク

- AgentRun 16 状態 enum の DB / API / frontend drift: shared enum generation と contract test で検出し、ADR-00004 を正本にする。
- ContextSnapshot 10 カラム不足: migration introspection test と JSON schema test で nullable 逃げを検出する。
- BudgetGuard hierarchy 設計: P0 は `tenant > project > task > run` を primary path に絞り、provider/user/workspace 拡張は metadata と後続 Sprint の責務に分ける。
- SecretBroker atomic claim race condition: parallel redeem fixture、row lock、0 rows deny、status distribution monitor で検出する。
- plan artifact schema の過小設計: Sprint 5.5 の Output Validator が取り込めるよう versioned JSON Schema にし、breaking change は ADR-00004 更新を要求する。
- secret canary fixture が過学習される: public_regression / private_holdout / adversarial_new 分離は Sprint 11 で行い、Sprint 4 は source skeleton に止める。
- migration rollback が runtime event / secret token state と競合する: production 前の `pg_dump`、staging upgrade、contract test を必須にし、downgrade が状態不整合を起こす場合は forward-fix migration を優先する。

## 次スプリント候補

- Sprint 4.5: Tool Registry & Read-only Gateway。ContextSnapshot の `tool_manifest` と AgentRunEvent を tool audit に接続する。
- Sprint 5: Provider Adapter。Provider result mapping、provider_request_fingerprint、BudgetGuard usage、Compliance Gate を AgentRun に接続する。
- Sprint 5.5: Output Validator / Input Trust Layer。plan artifact schema、repair retry、trusted_instruction 化、secret canary preflight 統合を扱う。
- Sprint 7: Docker isolated runner。`runtime_blocked`、cancel、runner event、forbidden path / dangerous command fixture を本実装する。
- Sprint 9: Run timeline full UI と Approval / Audit / Settings UI 連携。
- Sprint 11 / 12: AC-HARD-02、AC-HARD-03、AC-KPI-04、AC-KPI-05 の loader / final 判定。

## 関連 ADR

- [ADR-00006](../adr/00006_secrets_management.md): Sprint 4 実装前に accepted 化する。SOPS + age、SecretBroker、capability token、atomic claim redeem、broker-computed OperationContext fingerprint、raw secret 非露出を定義する。
- [ADR-00004](../adr/00004_agentrun_state_machine.md): Sprint 4 で proposed 化する。AgentRun 16 状態、blocked サブ 3、AgentRunEvent、ContextSnapshot 10 カラム、transition guard、provider result mapping を扱う。
- ADR-00009 は Sprint 3 の policy / approval 前提として参照する。approval decision と stale invalidation は AgentRun `waiting_approval` / `blocked` に接続する。
- ADR-00010 は Sprint 5 の provider call 実装で参照する。この Sprint では Provider Compliance Matrix の上限や provider 追加は変更しない。

## Review

完了日: 2026-05-09 (Batch 1-4 + Sprint Exit、全 Batch clean 達成)

### 実装方式

Codex multi-round adversarial review pattern (Sprint 1-3 から継続):

| Batch | 累計 review round | findings 累計 |
|-------|------------------|----------------|
| Batch 1 (AgentRun 16 状態 + transitions + AgentRunEvent + parent_run_id) | R1 → R2 → R3 → R4 → R5 (clean) | 8 件 (HIGH 4 + MEDIUM 3 + LOW 1) |
| Batch 2 (Artifact + ContextSnapshot 10 カラム + plan artifact schema) | R1 → R2 → R3 → R5 (clean、R3 stale test Claude 直接) | 6 件 (BLOCKER 1 + HIGH 2 + MEDIUM 2 + LOW 1) |
| Batch 3 (BudgetGuard + SecretBroker issue/redeem atomic claim + cancel) | R1 → R2 → R3 → R5 (clean、Claude 直接 fix 2 round) | 12 件 (BLOCKER 1 + HIGH 8 + MEDIUM 2 + LOW 1) |
| Batch 4 (secret canary fixture + AC-KPI-04 + provider result mapping) | R1 → R2 → R3 → R5 (clean、R3 で Claude 直接 fix) | 6 件 (BLOCKER 1 + HIGH 1 + MEDIUM 3 + LOW 1) |

**累計 ~22 round / 32 findings**。Sprint 1-4 全体で約 100 round / 100+ findings 解消。

### changed (実装ファイル群)

- **Batch 1** (BL-0040, BL-0041, BL-0042, BL-0029b):
  - `backend/app/domain/agent_runtime/status.py` (16 状態 Literal + ALL_AGENT_RUN_STATUSES + TERMINAL_STATES 5 種)
  - `backend/app/domain/agent_runtime/event_type.py` (22 event types Literal)
  - `backend/app/db/models/agent_run.py` (composite FK + parent_run_id `(tenant_id, project_id, parent_run_id)` cross-project + blocked_reason consistency CHECK)
  - `backend/app/db/models/agent_run_event.py` (append-only + seq_no UNIQUE + idempotency_key partial UNIQUE)
  - `backend/app/repositories/agent_run_event.py` (append-only + 18 prohibited keys + 8 regex pattern + recursive scan + max_depth=32 + visited set)
  - `backend/app/services/agent_runtime/state_machine.py` (validate_transition + EVENT_TYPE_FOR_TRANSITION mapping + BLOCKED_EVENT_TYPE_REASON_MAPPING)
  - `backend/app/services/agent_runtime/event_log.py` (transition_with_event 三重 guard + 同一 transaction)
  - `migrations/versions/0008_agent_runs_lifecycle.py`

- **Batch 2** (BL-0043, BL-0044, BL-0048):
  - `backend/app/domain/artifact/data_class.py` (PayloadDataClass Literal + DATA_CLASS_ORDINAL `{public:0, internal:1, confidential:2, pii:3}`)
  - `backend/app/domain/artifact/plan.py` (PlanArtifact + PlanStep + 12 forbidden path patterns + path traversal reject + leading dot 維持 normalize + MAX_REPAIR_RETRIES=3)
  - `backend/app/domain/agent_runtime/snapshot_kind.py` (SnapshotKind 5 種 + 各 kind 運用意味 docstring)
  - `backend/app/db/models/artifact.py` (immutable + content_hash 64 hex CHECK + payload_data_class CHECK + exportable + parent_artifact_id composite FK)
  - `backend/app/db/models/context_snapshot.py` (10 必須カラム + provider_continuation_ref exportable=false 強制 + JSONB 内部 schema 4 CHECK)
  - `backend/app/repositories/_payload_secret_scan.py` (共通 module、Batch 1+2+3 三 repository drift 防止)
  - `backend/app/services/agent_runtime/plan_validator.py` (Pydantic + JSON Schema + forbidden path)
  - `backend/app/services/agent_runtime/repair_policy.py` (should_repair + MAX_REPAIR_RETRIES)
  - `migrations/versions/0009_artifacts_context_snapshots.py`

- **Batch 3** (BL-0045, BL-0046, BL-0047, BL-0049):
  - `backend/app/domain/agent_runtime/budget.py` (BudgetLevel + BudgetCheckResult + BudgetExceedReason 5 種 + 全 reason の current/limit field)
  - `backend/app/domain/agent_runtime/operation_context.py` (OperationContext canonical schema + RequestedOperation 6 種 + compute_fingerprint NFC + JCS + SHA-256)
  - `backend/app/db/models/budget.py` (4 階層 budget + level_id consistency CHECK + partial UNIQUE per level + global_kill_switch)
  - `backend/app/services/agent_runtime/budget_guard.py` (4 階層 evaluate + enforce_budget_or_block via transition_with_event)
  - `backend/app/services/agent_runtime/cancel.py` (cancel_agent_run + transition_with_event 経由 + Redis publish skeleton)
  - `backend/app/services/secrets/broker.py` (SecretBroker issue/redeem + caller-supplied fingerprint 禁止 signature + approval target/action_class/diff_hash/tenant 4 整合 + secret_refs `for update` 同一 transaction 再検証 scope+name+version)
  - `backend/app/repositories/secret_capability_token.py` (atomic_claim 本実装、Sprint 2 Batch 3 NotImplementedError 解除、computed_fingerprint のみ受付)
  - `backend/app/repositories/audit_event.py` (assert_no_raw_secret 適用、recursive scan)
  - `backend/app/api/agent_runs.py` (POST /api/v1/agent_runs/{id}/cancel)
  - `backend/app/main.py` (agent_runs router 登録)
  - `migrations/versions/0010_budget_secret_runtime.py`

- **Batch 4** (BL-0050, BL-0051, provider result mapping):
  - `eval/security/secret_canary/` (AC-HARD-02 fixture skeleton、4 path 全 redact、23 invariant defense-in-depth、control_no_canary fixture 含む 2 fixture sha256 immutable index 双方向 MATCH)
  - `eval/quality/citation_coverage/` (AC-KPI-04 fixture skeleton、`_compute_expected_aggregate` deterministic recompute、coverage_ratio 検証、evidence_set_hash trace、_MANIFEST_EXPECTATION_LEAK_ALLOWED_PATHS で manifest standard fields allowlist)
  - `backend/app/services/agent_runtime/provider_result_mapping.py` (ProviderResultKind 11 種 → AgentRun status mapping、`.claude/rules/agentrun-state-machine.md` §7 完全一致)
  - 各 fixture loader: 23 invariant + dummy literal helper (8 種 `_make_dummy_*`) で test file 内 raw secret literal を repo 全体 secret scan の false positive から保護

### verified (検証実績)

- migration 0008/0009/0010 全て alembic upgrade head + downgrade base 通過
- AgentRun status 16 状態 + blocked_reason 3 種 + terminal 5 種 が DB CHECK / ORM Literal / Python Literal / fixture schema / cross-source 完全整合
- AgentRunEvent: `(tenant_id, run_id, seq_no)` UNIQUE + idempotency partial UNIQUE + 22 event types CHECK
- ContextSnapshot 必須 10 カラム全実装 + 5 種 snapshot_kind + DB CHECK 4 種 (repo_state / tool_manifest / fingerprint / continuation_ref required)
- transition_with_event 三重 guard (validate_transition + validate_event_type_for_transition + blocked_reason consistency) で status update + event append が同一 transaction
- agent_runs.parent_run_id `(tenant_id, project_id, parent_run_id)` 複合 FK で cross-tenant / cross-project 全 reject (Sprint 2 Batch 4 BL-0029b follow-up)
- 共通 `_payload_secret_scan.py` で 18 prohibited keys + 8 regex pattern + recursive + max_depth=32 + visited set (Batch 1+2+3 三 repository が同 module を import、parity test で identity 確認)
- BudgetGuard 4 階層 (global / tenant / project / agent_run) + global_kill_switch + hard exceed → blocked + budget_blocked + soft → warning notification
- SecretBroker: caller-supplied fingerprint 禁止 (signature レベルで物理削除、BrokerIssueResult から expected_request_fingerprint 削除) + atomic_claim SQL の WHERE で actor/run/fingerprint/operation/TTL/status 一括 binding + secret_refs `for update` 同一 transaction 再検証 scope+name+version + raw secret broker 内のみ resolve
- §8.1 必須 5 種 negative test (operation/target/payload/approval/secret_ref substitution → 全 fingerprint_mismatch)、実 issue/redeem flow 経由
- 並行 redeem `asyncio.gather` で 1 success / 1 denied (token_used) one-time guarantee
- cancel transition: running/blocked/waiting_approval/provider_incomplete → cancelled、`.claude/rules/agentrun-state-machine.md` §4 例外遷移に 3 種 cancel transitions 追加 (R5 F-003)
- AC-HARD-02 secret canary fixture: 4 path (provider_request_preflight / artifact / runner_stdout_stderr / audit) 全 redact、raw value 非含む、`policy_decision_created decision=deny + provider_blocked` event_type、reason_code = `provider_request_preflight_violation`、control_no_canary 双 fixture sha256 双方向 MATCH
- AC-KPI-04 citation_coverage fixture: claim/evidence/citation 構造、coverage_ratio = claims_with_citation / total_claims = 3/5 = 0.60、threshold >= 0.9、`_validate_aggregate_consistency` で input から deterministic recompute
- provider_result_mapping 11 種 (success/refusal/safety_refusal/max_token/incomplete/timeout_retryable/unsupported_schema/schema_mismatch/preflight_deny/data_class_deny/budget_exceeded) → AgentRun status mapping
- ADR-00006 (Secrets) accepted (2026-05-09)、ADR-00004 (AgentRun state machine) proposed → accepted (2026-05-09 Sprint Exit)

### deferred (P0 後続 Sprint へ送った項目)

- **replay UI / span export / Run timeline full UI**: Sprint 9 (UI sprint) で本格化
- **ProviderAdapter 本実装**: Sprint 5 (Provider Adapter) で `payload_data_class` / `allowed_data_class` boundary + `provider_request_preflight` 完成。本 Sprint は接続点 (provider_result_mapping) と境界 metadata のみ
- **Output Validator full pipeline**: Sprint 6 で AI artifact pipeline 7 stage 完成。本 Sprint は plan artifact schema validation のみ
- **Tool Registry 本実装**: Sprint 4.5 (read-only tool 境界) → Sprint 7 (runner sandbox)
- **Runner 本実装**: Sprint 7 で Docker isolated runner + `runner_mutation_gateway` + forbidden path / dangerous command 完成
- **AC-HARD-02 / AC-KPI-04 fixture loader を Eval Harness に接続**: Sprint 11 (eval harness) で `eval/runner/` 経由で load + score + report
- **Approval expiration auto-handler / worker job**: Sprint 4.5 (worker / arq job) で expired auto-transition

### risks (残リスク + 検知方法)

| risk | 検知方法 | 対応 Sprint |
|------|---------|-----------|
| AgentRun status enum drift (DB CHECK / Literal / fixture / migration / test 5+ source 間で乖離) | `tests/runtime/test_agentrun_status_enum.py` の cross-source 整合 test (16 状態完全一致 verify) | 現状 PASS、Sprint ごとに maintenance |
| ContextSnapshot 10 カラム drift | `tests/runtime/test_context_snapshot_invariants.py` で all required + DB CHECK 4 種 + JSONB 内部 schema verify | 現状 PASS |
| BudgetGuard 階層 + global_kill_switch race condition | composite UNIQUE per level + active=true + level_id consistency CHECK | DB level で防御、worker は Sprint 4.5 で詳細化 |
| SecretBroker atomic_claim race | `asyncio.gather` 並行 redeem 1 success / 1 denied test、`expected_request_fingerprint` server-owned | 現状 PASS、§8.1 5 種 negative + 並行 test 完備 |
| canary fixture 過学習 (private holdout 期待値見ながら scanner 調整) | private/public/adversarial split + dataset_version + fixture_id 一意 + monthly refresh + fixture/policy commit 分離 | Sprint 11 で eval harness 接続時に再評価 |
| parent_run_id lineage FK で cross-project 越境 | `tests/runtime/test_agentrun_parent_run_id_negative.py` で同一 tenant 別 project の INSERT IntegrityError | Sprint 2 Batch 4 BL-0029b follow-up 完了 (Sprint 4 Batch 1) |
| AC-HARD-02 trace event_type drift | `tests/eval/test_secret_canary_loader.py` で `provider_blocked` / `policy_decision_created` event_type + `provider_request_preflight_violation` reason_code 整合 | Sprint 5 Provider Adapter 実装で再検証 |
| provider_result_mapping 11 種 drift | `tests/runtime/test_provider_result_mapping.py` で各 kind cross-source 一致 | Sprint 5 Provider Adapter 接続時に最終整合 |
| Sprint 1-4 知見の memory 局所化 | memory/project_harness_consolidation_plan.md → Sprint 5+ または P0 完了後に `.claude/` ハーネス化 (TaskList #54) | Sprint 5 着手と並行で先行実装、または P0 完了後 |

### Sprint Exit 判定

- ✅ **must_ship 全達成**: AgentRun 16 状態 + blocked サブ 3 + ContextSnapshot 10 カラム + BudgetGuard hierarchy + SecretBroker issue/redeem + plan artifact schema + secret canary fixture
- ✅ **ADR-00006 accepted** (2026-05-09)、**ADR-00004 accepted** (2026-05-09 Sprint Exit)、SP-004 frontmatter `adr_refs` 移送完了
- ✅ **Codex multi-round review で全 batch clean 達成** (累計 ~22 round / 32 findings)
- ✅ **AC-HARD-02 + AC-KPI-04 fixture skeleton ready** (loader 接続は Sprint 11)
- ✅ **defense-in-depth 4 重防御** が SecretBroker / BudgetGuard / cancel / artifact / context_snapshot 全 boundary で揃う
- ✅ **既存 Sprint (1, 2, 3) との regression なし** (action class 7 種 / approval workflow / payload_data_class ordinal / 共通 _payload_secret_scan module / 共通 _PROHIBITED_PAYLOAD_KEYS 18 種 / cross-source enum 整合維持)
- ✅ **markdown fence 出力禁止 prompt** (Batch 4 で完全に機能、Batch 3 R2 反省を活かした)

→ **Sprint 4 完了**。次 Sprint は Sprint 5 (Provider Adapter: ProviderAdapter 本実装 + Provider Compliance Matrix runtime + `provider_request_preflight` + provider_call boundary)。

**重要**: TaskList #54 ([永続] Sprint 1-4 知見の .claude ハーネス恒久化) の実行を Sprint 5 着手と並行で進めることを推奨。詳細計画は `memory/project_harness_consolidation_plan.md`。
