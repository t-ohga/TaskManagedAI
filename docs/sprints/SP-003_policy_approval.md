---
id: "SP-003_policy_approval"
type: "heavy"
status: "draft"
sprint_no: 3
created_at: "2026-05-08"
updated_at: "2026-05-09"
target_days: 5.3
max_days: 7
adr_refs:
  - "[ADR-00009](../adr/00009_action_class_taxonomy.md) # Sprint 3 着手で proposed → 2026-05-09 accepted (Batch 4 R3 F-010 fix)、action class 7 種 + initial policy matrix"
planned_adr_refs: []
related_sprints:
  - "SP-002_core_data_model"
  - "SP-004_agent_runtime"
risks:
  - "action class 7 種の境界定義漏れ"
  - "self-approval 禁止の negative test 漏れ"
  - "Approval Inbox vertical slice の design drift"
---

このテンプレの使い方: Sprint 3 の Policy / Approval で、AI 操作の action class、policy matrix、approval request、self-approval 禁止、Approval Inbox vertical slice、In-App Notification、approval KPI source を実装するための heavy Sprint Pack。ADR Gate Criteria #4 AI エージェント権限、#3 API / event schema、#1 actor binding に触れるため、ADR-00009 を proposed 化してから実装へ入る。

最終更新: 2026-05-09 (Sprint 3 Batch 4 R3 F-010 fix で ADR-00009 を accepted 化、`adr_refs` に移送)

## 目的

- TaskManagedAI の AI 操作を、policy decision、human approval、audit event で説明できる責任境界にする。
- action class 7 種を `task_write` / `repo_write` / `pr_open` / `secret_access` / `merge` / `deploy` / `provider_call` に固定し、初期 policy matrix を実装する。
- `policy_rules`、`approval_requests`、`policy_decisions` を作り、AI 生成 artifact が human approval なしに Ticket / repo / secret / provider call へ進まないようにする。
- Approval Inbox の最小 UI vertical slice と In-App Notification を作り、承認待ちが UI と audit から追える状態にする。
- `approval_wait_ms` の計測元を `approval_requests.requested_at` / `decided_at` として固定し、AC-KPI-03 へ接続する。
- AC-HARD-01 `policy_block_recall` の policy 側 source として、action class 7 種、初期 policy matrix、`policy_rules`、deny-by-default reason_code を Sprint 5 / 11 / 12 に trace できる状態にする。
- self-approval 禁止、delegated actor、independent reviewer の negative test を Sprint 3 の release blocker にする。

## 背景

- Sprint 2 は actors / principals、audit_events、notification_events、Core Data Model を用意する。Sprint 3 はその actor schema を使って requester / decider / delegated actor の境界を固定する。
- P0 ロードマップの Sprint 3 must_ship は action class 7 種、初期 policy matrix、Approval Inbox vertical slice、In-App Notification 最小、approval KPI source である。
- AI Output Boundary は、AI 出力を `artifact -> schema_validated -> policy_linted -> diff_ready -> waiting_approval` の段階に通し、command / SQL / workflow / external tool へ直結させないことを要求している。
- DD-04 の古い `read/search` 表記は ADR-00009 で整理する。この Pack では read-only tool action は Sprint 4.5 の Tool Registry / allowed_actions 側に寄せ、Policy action class は `provider_call` を含む 7 種として扱う。
- AC-HARD-01 `policy_block_recall` は Sprint 3 / 5 / 11 / 12 に跨る。Sprint 3 では fixture loader 本体ではなく、Sprint 5 の provider call 直前 deny と Sprint 11 の Eval Harness loader が参照する policy source を作る。
- `merge` / `deploy` は P0 常時 deny とし、独立 reviewer 不在のまま実行可能にしない。`secret_access` は secret 値を返す許可ではなく、SecretBroker mediated operation の許可判定だけを扱う。

## 対象外

- analytics drill-down。P0.1 / P1 へ defer し、この Sprint では `approval_wait_ms` の生データと最小集計に止める。
- Approval Inbox full UI、bulk action、filter 高度化、管理者向け policy editor。Sprint 9 の P0 UI で扱う。
- ProviderAdapter 本実装、Provider Compliance Gate、`provider_request_preflight`。Sprint 5 で扱う。
- AC-HARD-01 fixture loader の Eval Harness 接続。Sprint 11 で扱う。ただし Sprint 3 は `policy_rules` / action class 7 種を policy source として残す。
- AgentRun 16 状態、AgentRunEvent、ContextSnapshot、BudgetGuard。Sprint 4 で扱う。
- merge / deploy 実行、production deploy、auto-merge。P0 では policy matrix で deny する。
- Slack / Email / Discord / mobile push 通知。P0 は In-App Notification の最小範囲に閉じる。
- raw secret / API key / canary 値を含む fixture。fixture は pattern と expected metadata のみを保存する。

## 設計判断

- action class は ADR-00009 の正本に寄せる: `task_write`、`repo_write`、`pr_open`、`secret_access`、`merge`、`deploy`、`provider_call` の 7 種を domain enum、DB check、frontend type、test fixture で一致させる。
- `provider_call` は policy action class として先に定義する: 実 provider 送信は Sprint 5 だが、provider call を approval / deny の対象にできるよう Sprint 3 で policy matrix に載せる。
- 初期 policy matrix は deny-by-default にする: `task_write` / `repo_write` / `pr_open` / `secret_access` / `provider_call` は policy 条件に応じて require_approval または deny、`merge` / `deploy` は P0 常時 deny とする。
- AC-HARD-01 source は policy matrix の reason_code に閉じる: Sprint 3 は known dangerous action を policy で block できる根拠を提供し、Sprint 5 の provider_request_preflight と Sprint 11 の fixture loader へ接続する。
- `policy_decisions` は append-only にする: 最新 decision の上書きではなく、入力 hash、policy_version、reason_code、actor_id、approval_request_id を残す。
- approval は stale invalidation を持つ: artifact hash、diff hash、policy version、provider fingerprint、policy pack lock が変化したら既存承認を `invalidated` にし、再承認を要求する。
- self-approval 禁止は DB と service の両方で守る: `requested_by_actor_id != decided_by_actor_id` を invariant とし、delegated actor が同じ human を impersonate する場合は independent reviewer required action を承認不可にする。
- Approval Inbox UI は read / decide の縦断 slice に限定する: pending 一覧、詳細、approve / reject、invalidated / expired 表示、notification badge までを must_ship とする。
- In-App Notification は `notification_events` から作る: `approval_pending`、`policy_blocked`、`budget_exceeded`、`run_failed` へ後続拡張できる最小 schema を使う。
- rollback は policy_version 単位にする: matrix seed に問題がある場合は新 policy_version を発行して deny-only baseline へ戻し、既存 approval は invalidated にする。

## 実装チケット

| ticket_id | title | 機能 ID | target_days | depends_on | 主成果物 | 関連 DD / 既存 backlog trace |
|---|---|---|---:|---|---|---|
| BL-0031 | action class 7 種 enum + `policy_rules` table | F-006,NF-001 | 0.6 | SP-002 | domain enum、DB check、policy_rules migration | DD-04、PLAN-01 BL-0033/0034 |
| BL-0032 | `approval_requests` / `policy_decisions` table append-only | F-006,NF-005 | 0.7 | BL-0031 | approval state、decision event、input_hash | DD-02 §4.7、PLAN-01 BL-0034 |
| BL-0033 | stale invalidation (diff hash / policy version / provider fingerprint) | F-006,NF-009 | 0.5 | BL-0032 | invalidation service、event seq、negative test | DD-04 §4.2、PLAN-01 BL-0037 |
| BL-0034 | self-approval 禁止 (`requester != decider` invariant) | F-006,NF-001 | 0.4 | BL-0032 | DB / service guard、audit reason | DD-04 §4.3、PLAN-01 BL-0038 |
| BL-0035 | delegated actor / independent reviewer negative test | F-006,NF-001 | 0.5 | BL-0034 | impersonation negative、merge/deploy deny | PLAN-01 R1 BL-0038 |
| BL-0036 | Approval Inbox UI vertical slice | F-006,F-017 | 0.8 | BL-0032,BL-0033 | pending list、detail、approve / reject | PLAN-01 BL-0039 |
| BL-0037 | In-App Notification 最小 (`notification_events` から) | F-007,AC-KPI-03 | 0.5 | BL-0036 | approval badge、unread/read、event insert | PLAN-01 BL-0040 |
| BL-0038 | approval KPI metric (`approval_wait_ms` median 計測) | F-020,AC-KPI-03 | 0.3 | BL-0032,BL-0037 | metric source、median query、dimension | PLAN-01 BL-0165 |
| BL-0039 | AC-KPI-03 fixture skeleton | F-019,AC-KPI-03 | 0.4 | BL-0038 | fixture manifest、expected metric schema | PLAN-00 KPI table |

## タスク一覧

- [ ] ADR-00009 を `docs/adr/00009_action_class_taxonomy.md` として proposed 化し、action class 7 種、P0 default、policy matrix、legacy `read/search` の扱い、rollback を記録する。
- [ ] action class enum を backend domain、DB migration、frontend type、fixture schema で同一集合にする。
- [ ] `policy_rules` に `tenant_id`、project scope、action_class、effect、rule_json、policy_version、metadata を持たせる。
- [ ] 初期 policy matrix seed を作り、`merge` / `deploy` は P0 常時 deny、`secret_access` と `provider_call` は fail-closed にする。
- [ ] AC-HARD-01 trace として、初期 policy matrix が `eval/security/policy_block/*` fixture skeleton に対応する source であることを policy_version / reason_code / action_class で記録する。
- [ ] `approval_requests` と `policy_decisions` を append-only 前提で作り、raw prompt、raw secret、raw canary を payload に含めない。
- [ ] approval target に artifact hash、diff hash、policy_version、policy_pack_lock、provider_request_fingerprint、stale_after_event_seq を保存する。
- [ ] stale invalidation service で diff hash、policy version、provider fingerprint 変化を検出し、既存 approval を `invalidated` にする。
- [ ] `requested_by_actor_id != decided_by_actor_id` を service guard と DB constraint または trigger 相当の test で保証する。
- [ ] delegated actor が同じ human を impersonate するケースを independent reviewer required action で reject する。
- [ ] Approval Inbox API を pending list / detail / decide に限定して実装し、UI は最小 vertical slice に止める。
- [ ] In-App Notification は approval pending 作成、badge 表示、mark read までを実装する。
- [ ] `approval_wait_ms = decided_at - requested_at` を median 集計できる source として固定する。
- [ ] AC-KPI-03 fixture skeleton を dataset version / fixture_id / expected aggregation 付きで作る。
- [ ] policy / approval / notification / KPI の audit event に actor_id、run_id、trace_id、correlation_id を入れる。

## must_ship / defer_if_over_budget 対応表

### ロードマップ §94 正本 (verbatim quote)

| Sprint | target_days | max_days | must_ship | defer_if_over_budget |
|--------|-------------|----------|-----------|----------------------|
| Sprint 3 | 5.3 | 7 | action class 7 種 + 初期 policy matrix + Approval Inbox vertical slice + In-App Notification 最小 + approval KPI source | analytics |

### Sprint Pack 内詳細 trace

ロードマップ正本の must_ship を Sprint Pack 内で詳細化したもの:

| 項目 | ロードマップ → Sprint Pack trace |
|---|---|
| action class 7 種 | 実装チケット BL-0031 |
| 初期 policy matrix | 実装チケット BL-0031, BL-0032。AC-HARD-01 `policy_block_recall` の policy source を提供 |
| Approval Inbox vertical slice | 実装チケット BL-0036 |
| In-App Notification 最小 | 実装チケット BL-0037 |
| approval KPI source | 実装チケット BL-0038, BL-0039 |

## 受け入れ条件

- [ ] ADR-00009 が **accepted** 状態で存在し (Sprint 3 着手で proposed 化、2026-05-09 Batch 4 R3 F-010 fix で accepted 化)、action class 7 種、P0 default、legacy `read/search` の移行扱い、policy matrix、negative test、rollback を含む。
- [ ] action class enum が backend、DB、frontend、fixture schema で一致し、`provider_call` を含む。
- [ ] `policy_rules`、`approval_requests`、`policy_decisions` が `tenant_id` を持ち、Sprint 2 の actors / principals と複合 FK で接続されている。
- [ ] 初期 policy matrix は deny-by-default で、`merge` / `deploy` を P0 常時 deny する。
- [ ] `task_write`、`repo_write`、`pr_open`、`secret_access`、`provider_call` は policy decision と approval requirement を audit できる。
- [ ] **AC-HARD-01 trace**: 初期 policy matrix が `eval/security/policy_block/*` fixture skeleton に対応する。Sprint 5 で provider call 直前 deny を実装し、Sprint 11 で fixture loader を Eval Harness に接続する流れを Sprint Pack 内に明示。Sprint 3 では policy_rules / action class 7 種が AC-HARD-01 の policy 側 source を提供することを記録する。
- [ ] `policy_decisions` は append-only で、allow / deny / require_approval、reason_code、policy_version、input_hash を保存する。
- [ ] approval target に artifact hash、diff hash、policy_version、provider_request_fingerprint、stale_after_event_seq が保存される。
- [ ] diff hash、policy version、provider fingerprint の変化で既存 approval が `invalidated` になり、resume には再承認が必要になる。
- [ ] self-approval は requester と decider が同一 actor の場合に失敗する。
- [ ] delegated actor が同じ human を impersonate する場合、independent reviewer required action は承認不可になる。
- [ ] Approval Inbox は pending 一覧、詳細、approve / reject、invalidated / expired 表示を最小 UI で操作できる。
- [ ] In-App Notification は approval pending を unread として作成し、UI で read 化できる。
- [ ] `approval_wait_ms` は `approval_requests.requested_at` / `decided_at` から median 集計でき、AC-KPI-03 fixture skeleton に trace している。
- [ ] raw secret、API key、capability token、canary raw value が DB payload、audit、notification、frontend state、test snapshot、docs に残らない。
- [ ] AI 出力が approval を bypass して command / SQL / workflow / external tool / repo write / provider call へ直結しない。

## 検証手順

- [ ] `ruby -e 'require "yaml"; YAML.load_file("docs/sprints/SP-003_policy_approval.md")'` で frontmatter が valid YAML として読めることを確認する。
- [ ] `ruby -e 'text=File.read("docs/sprints/SP-003_policy_approval.md"); missing=%w[BL-0031 BL-0032 BL-0033 BL-0034 BL-0035 BL-0036 BL-0037 BL-0038 BL-0039].reject { |id| text.include?(id) }; abort("missing: #{missing.join(",")}") unless missing.empty?'` で 9 チケットが揃っていることを確認する。
- [ ] `ls docs/adr/00009_action_class_taxonomy.md` で planned ADR が存在することを確認する。
- [ ] `uv run alembic upgrade head` を dev DB で実行し、policy / approval migration が通ることを確認する。
- [ ] `uv run pytest tests/policy/test_action_class_enum.py -q` で action class 7 種が backend / DB / frontend contract と一致することを確認する。
- [ ] `uv run pytest tests/policy/test_initial_policy_matrix.py -q` で `merge` / `deploy` deny、`secret_access` / `provider_call` fail-closed、approval required decision を確認する。
- [ ] `uv run pytest tests/eval/test_policy_block_recall_policy_source.py -q` で AC-HARD-01 `policy_block_recall` の policy source が action class 7 種、policy_rules、reason_code に trace していることを確認する。
- [ ] `find eval/security/policy_block -maxdepth 2 -type f | sort` で Sprint 5 / 11 が接続する fixture skeleton の配置予定を確認する。
- [ ] `uv run pytest tests/policy/test_approval_stale_invalidation.py -q` で diff hash、policy version、provider fingerprint 変化時に invalidated になることを確認する。
- [ ] `uv run pytest tests/policy/test_self_approval_negative.py -q` で self-approval、delegated actor、independent reviewer negative が失敗することを確認する。
- [ ] `uv run pytest tests/metrics/test_approval_wait_ms.py -q` で `approval_wait_ms` median の集計元が `requested_at` / `decided_at` であることを確認する。
- [ ] `pnpm lint`、`pnpm typecheck`、`pnpm exec playwright test tests/e2e/approval-inbox.spec.ts` で Approval Inbox vertical slice を確認する。
- [ ] `rg -n "secret_value|get_secret_value|canary_value\s*[:=]" backend frontend tests config --glob '!**/*.md'` で raw secret / raw canary 返却 interface が実装に混入していないことを確認する (実装対象限定、Markdown 除外)。
- [ ] `rg -n "sk-[A-Za-z0-9]{20,}|sk-ant-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{20,}|AGE-SECRET-KEY-[A-Z0-9]{20,}" docs --glob '!docs/sprints/**' --glob '!docs/adr/**' --glob '!docs/設計検討/**'` で docs に実値らしい secret / API key / age key 値がないことを確認する (共通 token regex set)。
- [ ] `ruby -e 'text=File.read(ARGV[0]); forbidden=[["ie","shima"].join, ["academy",["ie","shima"].join].join("."), ["i","FILTER"].join("-")].select { |s| text.include?(s) }; abort("forbidden terms: #{forbidden.join(",")}") unless forbidden.empty?' docs/sprints/SP-003_policy_approval.md` で別プロジェクト固有語がないことを確認する (検証コマンド自身が self-match しないよう禁止語は実行時組立て)。

### Migration rollback DoD (必須)

DB schema 変更 (Alembic migration) を伴う場合、以下を必ず満たす:

1. **migration 適用前**: `pg_dump` で full DB backup を取り、age で暗号化して別ボリュームに保存。restore drill で復号確認
2. **staging 先行**: `uv run alembic upgrade head` を staging DB で実行し、`alembic check` + policy / approval contract test (action_class enum、policy_rules unique constraint、approval status enum、self-approval constraint、append-only index、tenant FK) が PASS
3. **rollback trigger**: production migration 後に unknown action_class が保存可能、初期 matrix が deny-by-default でない、`merge` / `deploy` が allow、self-approval が成功、orphan `approval_requests` / `policy_decisions`、または `approval_wait_ms` source 欠落が検出された場合
4. **rollback step**: `uv run alembic downgrade -1` で 1 step downgrade。downgrade で data loss / inconsistent state になる場合は forward-fix migration を新規作成し、staging で検証してから production 適用
5. **rollback verification**: restore 後に policy / approval contract test を `pytest tests/contract/policy/ tests/policy/test_initial_policy_matrix.py tests/policy/test_self_approval_negative.py -q` で確認

## レビュー観点

- [ ] ADR-00009 の action class 7 種と実装 enum が一致している。
- [ ] Policy Engine は deny-by-default で、matrix 未登録 action、未知 provider_call、未知 resource_ref を fail-closed にする。
- [ ] AC-HARD-01 `policy_block_recall` の Sprint 3 source が policy_rules / action class / reason_code として説明でき、Sprint 5 provider call 直前 deny、Sprint 11 fixture loader、Sprint 12 final 判定へ trace している。
- [ ] `merge` / `deploy` に approval があっても P0 では実行可能にならない。
- [ ] `secret_access` は secret 値取得権限ではなく、SecretBroker mediated operation の policy gate として実装されている。
- [ ] approval invalidation が diff hash、policy version、provider fingerprint を見ており、古い承認を resume に使わない。
- [ ] self-approval 禁止、delegated actor、independent reviewer negative test が actor / principal schema と矛盾していない。
- [ ] Approval Inbox は vertical slice に閉じ、Sprint 9 の full UI と責務が重複していない。
- [ ] audit event は append-only で、actor_id、run_id、trace_id、correlation_id、policy_version、reason_code から判断を追える。
- [ ] `approval_wait_ms` は AC-KPI-03 の source として再計算でき、UI analytics に依存していない。
- [ ] Migration rollback DoD の `pg_dump` / staging / `alembic check` / downgrade / forward-fix / contract test が実行手順として具体化されている。
- [ ] AI 出力が直接 command / SQL / workflow / external tool / provider call / repo write へ接続されていない。

## 残リスク

- action class 7 種の境界定義漏れ: ADR-00009 に legacy `read/search` の扱いと `provider_call` の責務を明記し、enum drift test で検出する。
- AC-HARD-01 trace drift: Sprint 3 の policy_rules / reason_code が Sprint 5 の provider call deny、Sprint 11 の `eval/security/policy_block/*` loader とずれる可能性がある。fixture skeleton と policy source contract test で検出する。
- self-approval 禁止の negative test 漏れ: requester / decider 同一、delegated actor、impersonated_by 同一 human、merge / deploy deny を fixture 化する。
- Approval Inbox vertical slice の design drift: Sprint 3 は pending list / detail / decide / notification badge に閉じ、full UI は Sprint 9 へ送る。
- policy_version rollback 漏れ: seed 変更は新 version として追加し、既存 approval は invalidated にする。schema rollback は Migration rollback DoD に従い、downgrade が危険なら forward-fix migration に切り替える。
- approval KPI が UI event に依存する: DB の `requested_at` / `decided_at` を source of truth とし、frontend telemetry は補助に止める。

## 次スプリント候補

- Sprint 4: Agent Runtime。Policy decision と approval request を AgentRun 16 状態、AgentRunEvent、ContextSnapshot、BudgetGuard、SecretBroker issue / redeem に接続する。
- Sprint 5: Provider Adapter。`provider_call` action class を Compliance Gate、`provider_request_preflight`、BudgetGuard、provider status mapping に接続する。
- Sprint 5.5: Output Validator / Input Trust Layer。human-approved plan のみを `trusted_instruction` 化し、action class / data class policy lint を強化する。
- Sprint 9: Approval Inbox full UI、analytics 表示、notification UX 拡張。
- Sprint 11 / 12: AC-HARD-01 fixture loader、AC-KPI-03 fixture loader、P0 Acceptance final 判定。

## 関連 ADR

- [ADR-00009](../adr/00009_action_class_taxonomy.md): Sprint 3 で proposed 化する。action class 7 種、initial policy matrix、legacy `read/search` 表記の整理、self-approval 禁止、policy rollback を扱う。
- ADR-00001 は actors / principals と dev login actor binding の前提として参照するが、この Sprint では認証方式を変更しない。
- ADR-00006 は `secret_access` の意味が raw secret 取得ではなく SecretBroker mediated operation であることの前提として参照する。
- ADR-00010 は `provider_call` の provider data class gate を Sprint 5 で実装する際に参照する。この Sprint では Provider Compliance Matrix の上限を変更しない。

## Review

完了日: 2026-05-09 (Batch 1-4 + Sprint Exit)

### 実装方式

Codex multi-round adversarial review pattern (Sprint 1/2 から継続):

| Batch | 実装 round | 累計 review round | findings 累計 |
|-------|----------|------------------|----------------|
| Batch 1 (action class enum + policy_rules) | 1 | R1 → R2 fix → R3 (clean) | 2 件 |
| Batch 2 (approval_requests + policy_decisions + stale invalidation + self-approval) | 1 | R1 → R2 fix → R3 (clean) | 3 件 |
| Batch 3 (delegated actor negative + Approval Inbox UI + In-App Notification) | 1 | R1 → R2 → R3 → R4 → R5 → R6 (clean) | 8 件 (BLOCKER 含む) |
| Batch 4 (approval_wait_ms KPI + AC-KPI-03 fixture + AC-HARD-01 policy source) | 1 | R1 → R2 → R3 → R4 → R5 (clean、F-011 LOW Claude直接 fix) | 11 件 |

**累計 ~24 round / 24 findings**。clean gate は `findings: []` の Codex JSON response で判定。

### changed (実装ファイル群)

- **Batch 1** (BL-0031, BL-0032):
  - `backend/app/domain/policy/action_class.py` (ActionClass Literal 7 種 + ALL_ACTION_CLASSES + P0 always-denied / fail-closed / conditional + PolicyEffect Literal)
  - `backend/app/db/models/policy_rule.py` (ORM model with composite FK + action_class CHECK)
  - `backend/app/repositories/policy_rule.py` (read-only repository、mutating API NotImplementedError 抑制)
  - `migrations/versions/0005_policy_rules.py` (table + 7 行 deny-by-default seed)
  - `tests/policy/test_action_class_enum.py`、`test_initial_policy_matrix.py`

- **Batch 2** (BL-0033, BL-0034, BL-0035):
  - `backend/app/db/models/approval_request.py` (ApprovalStatus 5 種 + RiskLevel Literal + 5 種 stale invalidation + self-approval CHECK + decided_at consistency CHECK + decision_completeness CHECK)
  - `backend/app/db/models/policy_decision.py` (append-only event)
  - `backend/app/repositories/approval_request.py` (`_UPDATE_FORBIDDEN_FIELDS` + `create_pending_approval` notifier wiring)
  - `backend/app/repositories/policy_decision.py` (append-only)
  - `backend/app/services/policy/decision_service.py` (atomic UPDATE returning + ORM refresh)
  - `backend/app/services/policy/invalidation.py` (5 種 stale invalidation + returning() check)
  - `backend/app/services/policy/self_approval_guard.py` (`effective_human_actor_id` 双方向 normalization)
  - `migrations/versions/0006_approval_policy_decisions.py`
  - `tests/policy/test_approval_decision_service.py`、`test_approval_stale_invalidation.py`、`test_self_approval_negative.py`、`test_approval_requests_append_only.py`、`test_policy_decisions_append_only.py`

- **Batch 3** (BL-0036, BL-0037):
  - `backend/app/services/notifications/approval_notifier.py`
  - `backend/app/api/approval_inbox.py` (3 endpoints: list/detail/decide)
  - `backend/app/api/notifications.py` (3 endpoints: list/badge_count/mark_read)
  - `frontend/app/(admin)/approvals/page.tsx`、`[id]/page.tsx` (Server Component)
  - `frontend/app/(admin)/approvals/[id]/_components/approval-decide-form.tsx` (Client Component minimal)
  - `frontend/app/(admin)/notifications/page.tsx` + `_components/` + `_actions/mark-read.ts`
  - `frontend/components/notification-badge.tsx` (link 化 + unread count)
  - `frontend/lib/api/approvals.ts`、`notifications.ts` (Zod enum 固定 type-safe API client)
  - `frontend/vitest.setup.ts` + `vitest.config.ts` + `tsconfig.json` + `package.json` (jest-dom matchers)
  - `tests/policy/test_delegated_actor_negative.py`
  - `tests/e2e/test_approval_flow_e2e.py` (httpx ASGITransport で Server Component fetch interception 不能問題を回避)
  - `frontend/__tests__/notification-list.test.tsx`、`approval-decide-form.test.tsx`

- **Batch 4** (BL-0038, BL-0039):
  - `backend/app/services/metrics/approval_wait_ms.py` (PostgreSQL `percentile_cont(0.5/0.95).within_group()` + `decided_at >= requested_at` filter)
  - `migrations/versions/0007_approval_temporal_check.py` (DB CHECK `approval_requests_ck_decided_at_after_requested_at`、F-004 fix)
  - `backend/app/db/models/approval_request.py` (CheckConstraint 同期)
  - `eval/security/policy_block/` (manifest.json + expected_schema.json + public_regression/sample.json + loader.py: AC-HARD-01 reason_code = `task_write_requires_approval`、ADR-00009 + migration 0005 整合)
  - `eval/quality/approval_wait_ms/` (manifest.json + expected_schema.json + public_regression/sample.json + loader.py: p95=13,680,000.0 PostgreSQL `percentile_cont` 仕様準拠、status enum 5 種 + decided_at optional + if-then-else、`_validate_aggregate_consistency` で tampered fixture fail-closed)
  - `tests/eval/test_policy_block_loader.py` (新規、48 test、Sprint 2 Batch 4 23 invariant pattern 完全踏襲)
  - `tests/eval/test_approval_wait_ms_loader.py` (`TestPercentileContBoundaries` class 8 test + 既存 5 test + tamper 3 test)
  - `tests/eval/test_policy_block_recall_policy_source.py` (migration 0005 から regex 動的抽出 reason_code subset)
  - `tests/policy/test_approval_wait_ms.py` (median + p95 + negative wait_ms reject)
  - `docs/adr/00009_action_class_taxonomy.md` (status: proposed → accepted at 2026-05-09)
  - `docs/sprints/SP-003_policy_approval.md` (adr_refs 移送 + 受け入れ条件 accepted 文言整合)

### verified (検証実績)

- migration 0005/0006/0007 全て alembic upgrade head + downgrade base 通過
- Action class enum 7 種が backend Literal / DB CHECK / frontend Zod / fixture schema で完全一致
- Initial policy matrix が deny-by-default、`merge`/`deploy` P0 deny、`task_write`/`repo_write`/`pr_open`/`secret_access`/`provider_call` が approval requirement を保有
- `policy_rules` / `approval_requests` / `policy_decisions` 全て `tenant_id NOT NULL DEFAULT 1` + composite FK 接続
- self-approval CHECK が DB level で違反 INSERT を IntegrityError reject、`effective_human_actor_id` 双方向 normalization で delegated impersonation 経路も block
- 5 種 stale invalidation (artifact_hash / diff_hash / policy_version / policy_pack_lock / provider_request_fingerprint) が `returning()` rowcount check で空更新を fail-closed
- decided_at consistency CHECK + decision_completeness CHECK + temporal CHECK (decided_at >= requested_at) の **三重 CHECK** で approval state machine integrity を DB 層で保護
- Approval Inbox UI vertical slice (Server Component default + minimal Client Component + Server Action mutation) + In-App Notification (link 化 + unread count + mark_read action)
- `approval_wait_ms` aggregate query: PostgreSQL `percentile_cont(0.5/0.95).within_group()` で median/p95/min/max/sample_count 集計、status='approved'/'rejected' + decided_at IS NOT NULL + decided_at >= requested_at の triple defense
- AC-HARD-01 fixture: reason_code = `task_write_requires_approval`、policy source = ADR-00009 + migration 0005 seed 整合、loader 23 invariant defense-in-depth 完備 (48 test)
- AC-KPI-03 fixture: p95 = 13,680,000.0 (PostgreSQL `percentile_cont(0.95)` linear interpolation 仕様)、`_validate_aggregate_consistency` で input から再計算 + tampered fixture fail-closed (median/p95/min/max/sample_count 改変全 reject)
- sha256 immutable index 双方向 verification: AC-HARD-01 (`b7d95d76867f5edb...`) + AC-KPI-03 (`b28614eb3fd6c7a2...`) 両 fixture の actual = expected MATCH
- raw secret / capability_token / api_key 等 13 種 nested key leak が PublicFixture / RedactedFixture 全 path で reject (anti-gaming)
- ADR-00009 accepted 化 + SP-003 `adr_refs` 移送 (planned → accepted) で ADR Gate Criteria #4 / #3 / #1 整合

### deferred (P0 後続 Sprint へ送った項目)

- **Approval Inbox full UI** (filtering / pagination / bulk approve / virtualized list): Sprint 9 (UI sprint) で本格化
- **External notification** (email / Slack / Webhook): P1 以降、外部送信は `payload_data_class` Matrix 通過必須なため P0 範囲外
- **AC-HARD-01 fixture loader を Eval Harness に接続**: Sprint 11 (eval harness) で `eval/runner/` 経由で load + score + report
- **AC-KPI-03 KPI dashboard / drill-down**: Sprint 11.5 (Eval Dashboard) で OTel + Loki + Grafana 統合
- **Provider call 直前 deny の policy enforcement**: Sprint 5 (provider adapter) で `provider_request_preflight` 実装時に AC-HARD-01 trace 完成
- **AgentRun runtime 経路から policy / approval を呼ぶ**: Sprint 4 (agent runtime) で AgentRun 16 状態 + state machine + ContextSnapshot 実装時に統合
- **merge / deploy 実行**: P0 全期間 deny。Sprint 12 P0 Acceptance で `merge` / `deploy` policy_decision 実行不可確認のみ
- **analytics drill-down**: Sprint 11.5 で Approval funnel / time-to-merge / cost dashboard と一緒に
- **Approval expiration auto-handler** (worker job): Sprint 4.5 (worker / arq job) で expired auto-transition

### risks (残リスク + 検知方法)

| risk | 検知方法 | 対応 Sprint |
|------|---------|-----------|
| action class drift (backend Literal / DB CHECK / frontend Zod / fixture schema 間で乖離) | `tests/policy/test_action_class_enum.py` の cross-source enum 一致 test | 現状 PASS、Sprint ごとに maintenance |
| policy block trace drift (AC-HARD-01 reason_code が ADR/migration から乖離) | `tests/eval/test_policy_block_recall_policy_source.py` で migration 0005 から regex 動的抽出 + ADR extra reasons subset 確認 | 現状 PASS、新 reason_code 追加時に毎回 |
| approval bypass via status-only update | `_UPDATE_FORBIDDEN_FIELDS` + DB `approval_requests_ck_decision_completeness` CHECK + `ApprovalDecisionService` atomic UPDATE returning | 三重防御済 |
| stale approval (artifact / diff / policy / provider_request_fingerprint 変化検知漏れ) | 5 種 stale invalidation + returning() rowcount + 0件 detection | Sprint 5 (provider call) で fingerprint 計算実装時に確認 |
| KPI source drift (approval_wait_ms 計算が PostgreSQL `percentile_cont` 仕様と乖離) | `TestPercentileContBoundaries` 8 test + `_validate_aggregate_consistency` deterministic recompute | 現状 PASS |
| notification race (notify_approval_pending と approval insert の transaction 不整合) | `create_pending_approval` で同一 transaction wiring (Batch 3 R3 F-003 fix) | 現状 PASS、external notification で再評価 |
| 負値 wait_ms KPI gaming (decided_at < requested_at で median 偽造) | DB CHECK `approval_requests_ck_decided_at_after_requested_at` + service filter `decided_at >= requested_at` + `_compute_expected_aggregate` で除外 | 三重防御済 |
| jest-dom matchers TypeScript drift (vitest.config / tsconfig / setup files の整合) | `pnpm exec tsc --noEmit` で TS2339 errors detect | Sprint 9 UI 実装増強時に再評価 |

### Sprint Exit 判定

- ✅ **must_ship 全達成**: action class taxonomy + initial policy matrix + approval workflow + Approval Inbox vertical slice + notification + AC-HARD-01 policy source + AC-KPI-03 KPI source + 5 種 stale invalidation + self-approval (incl. delegated impersonation) + 三重 CHECK temporal integrity
- ✅ **ADR-00009 accepted 化** (2026-05-09 Batch 4 R3 F-010 fix)、`adr_refs` 移送完了
- ✅ **Codex multi-round review で全 batch clean 達成** (累計 ~24 round / 24 findings)
- ✅ **AC-HARD-01 + AC-KPI-03 fixture skeleton ready** (loader 接続は Sprint 11)
- ✅ **DB CHECK / ORM / service / loader / test の defense-in-depth** が approval / KPI 全 boundary で揃う
- ✅ **既存 Sprint (1, 2) との regression なし** (action class enum / actor_id / `tenant_id` 整合維持)

→ **Sprint 3 完了**。次 Sprint は Sprint 4 (Agent Runtime: AgentRun 16 状態 + ContextSnapshot 10 カラム + state machine + provider adapter integration)。

## QL-B cross-reference (R29 §5 QL-B、2026-05-15 doc-only、F-PR12-004 P2 adopt)

本 Pack の acceptance spec として、QL-B Quality Loop run で記録された future implementation gate を以下の通り cross-reference する:

- `docs/基本設計/03_AIオーケストレーション設計.md §13.1` PolicyDecision must-precede invariant (outbox / audit-before-dispatch pattern、external action と DB transaction を同一 scope にしない)
- `docs/基本設計/04_セキュリティ_権限_監査設計.md §13.1` action_class 7 種 exact set (read/search は Tool Registry `allowed_actions` 経由に移送)
- `docs/基本設計/04_セキュリティ_権限_監査設計.md §13.3` Auto-allow ≠ approval row (effect=allow path は approval_requests row 作らない、audit metadata で applied_level 記録)
- `docs/adr/00025_autonomy_policy_profiles.md` (proposed) autonomy L0-L3 が approval row に与える影響 (L1-L3 で auto-allow path 利用時、approval_requests 不作成 + audit-only path)
- 本 Pack で実装済の `approval_requests.decided_by_actor_id` human-only DB CHECK は ADR-00025 §不変条件 #2 と整合

