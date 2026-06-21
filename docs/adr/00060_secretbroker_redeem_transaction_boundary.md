---
id: "ADR-00060"
title: "SecretBroker redeem の transaction 境界 + capability token terminal-state 保証 (R16-F1 follow-up)"
status: "proposed"
date: "2026-06-21"
accepted_at: null
authors:
  - "Claude (autonomous, PLAN-10 Phase 0 SP-PHASE0 batch-3 で R16-F1 defer を follow-up ADR 化)"
related_sprints:
  - "SP-PHASE0_local_bootstrap (batch-1 で R16-F1 defer、batch-3 で本 ADR 起票)"
  - "PLAN-10 (大元計画 Phase 0 / Phase 2 CLIAgentAdapter で broker-mediated operation 配線時に着手)"
supersedes: null
superseded_by: null
---

ADR Gate Criteria #3 (API 契約 / event schema) + #6 (Secrets 管理方式: SecretBroker redeem boundary) に該当。
SP-PHASE0 batch-1 の Codex adversarial R16 で検出し **user 承認 (2026-06-21) で defer** した R16-F1 (broker redeem の
非 custody operation 失敗時の token 終端 / transaction 境界) を、専用 follow-up ADR として正本化する。

> **status: proposed (2026-06-21)**。本 ADR は **defer の正本記録 + 設計選択肢の固定**であり、実装は着手しない。
> broker-mediated operation (`provider.call` / `repo.push` 等を operation callback 付きで redeem する経路) を
> 実配線する **Phase 2 (CLIAgentAdapter + real ProviderAdapter)** の着手直前に、codex-plan-review R1 + 採否判定を
> 経て accepted 昇格し実装する (sprint-pack-adr-gate §12.4)。それまでは下記「残リスク」を accepted residual とする。

## 背景

`SecretBroker.redeem_capability_token` は (1) atomic claim UPDATE で token を `issued -> redeeming` に線形化し、
(2) `secret_refs` を同一 tx 内で再検証して broker 内部で raw secret を resolve し、(3) `operation(context)` を
実行 (broker-mediated operation: provider.call / repo.push 等)、(4) 成功時 `_mark_claimed_token_used()` で
`redeeming -> used` に終端する、という流れを持つ。

R16-F1 (HIGH、pre-existing broker.py 経路): `operation(context)` が **非 custody 例外** (custody/resolver 失敗は
R14-F2/R15-F1 で既に denied 化済のため対象外。ここでは operation 自身の業務例外) を投げると `_mark_claimed_token_used()`
に到達しない。このとき:

- **外部 session が rollback した場合**: atomic claim (`issued -> redeeming`) ごと巻き戻り、token が `issued` に
  戻って **再 redeem 可能**になる。operation が外部副作用 (provider への送信、repo push 等) を既に起こしていても
  再実行され得る = **at-most-once / exactly-once 違反**。
- **外部 session が commit した場合**: token は `redeeming` のまま **非終端**で残る = 状態真実性違反 (terminal
  state guarantee の欠如)。crash 時は `expires_at` 経過で expire するが (secretbroker-boundary §9)、明示終端でない。

根因は redeem の **transaction 契約が未確定**であること: commit-before-side-effect / side-effect-then-commit の
いずれを採るか、operation 失敗時の token 終端 (used / failed-terminal / 再 issue 要求) をどう保証するか、broker が
自前 tx を所有するか caller tx に従属するか、が定義されていない。これは API 契約 + secret access boundary の再設計
であり ADR Gate に該当するため、material lifecycle (batch-1) のスコープ外として defer した。

## 現状のリスク露出 (重要)

`redeem_capability_token` を operation callback 付きで使う **production 配線は現状ゼロ** (Phase 0 では
broker-mediated operation を配線していない。CLI subscription は host-ambient で broker 非経由、API key の
in-process provider.call は Phase 2)。正確には: `operation=` を渡す adapter コード (例: GitHubAppAdapter の
draft PR 作成系) は source に存在するが、いずれの router / worker からも instantiate されず **到達不能 (unwired)**
である。よって本 issue は **forward-looking** であり、Phase 2 で broker-mediated operation を実配線する (unwired
adapter を router/worker から到達可能にする) 前に確定すればよい。

## 選択肢

- **A: side-effect 後に broker 所有 tx で終端 (outbox/2-phase 風)**: broker が redeem 専用 tx を所有し、operation の
  外部副作用を idempotency key で冪等化 + 副作用記録 (outbox) を同一 tx で commit してから token を `used` 終端。
  再 redeem 時は idempotency key で副作用を再生せず結果のみ返す (exactly-once 近似)。
- **B: at-most-once + 失敗時 failed-terminal**: operation 例外時は token を `redeeming -> failed` (新終端 state) に
  し、再 redeem 不可。caller は新 token を再 issue。副作用が起きたか不明な失敗は caller に明示 (副作用の冪等性は
  operation 側責務)。broker は「token は二度と使えない」ことのみ保証 (at-most-once)。
- **C: caller tx 従属 + 明示契約 doc (最小)**: broker は caller tx に従属し、redeem は「operation 成功 + caller commit」
  でのみ used 終端、失敗時は caller が rollback (token は issued に戻る) と契約 doc 化。再 redeem の副作用冪等性は
  caller/operation 責務と明記。実装変更最小、保証は弱い。

## 採用案 (proposed、Phase 2 着手時に確定)

**B (at-most-once + failed-terminal)** を第一候補とする。理由: secret access boundary では「同じ token が外部
副作用後に再利用され得ない」ことが最重要 (at-most-once)。exactly-once (案 A) は outbox + idempotency の追加複雑性が
大きく、P0/Phase2 の broker-mediated operation (provider.call は冪等でない送信) には at-most-once + caller 側 idempotency
の方が単純で安全。具体:

- `secret_capability_tokens.status` に `failed` 終端を追加 (cross-source enum 5+source 整合: DB CHECK / ORM /
  Literal / Pydantic / pytest)。`redeeming -> failed` 遷移を operation 例外時に broker 所有 tx で commit。
- broker は redeem 専用 tx を所有 (caller tx 従属をやめる) = operation 例外でも claim 巻き戻りを防ぐ。
- `failed` token は再 redeem 不可 (atomic claim の `status='issued'` 条件で自然に弾かれる)。retry は policy check
  から新 token を再 issue (secretbroker-boundary §9 既定と整合)。
- audit: operation 例外時 `secret_capability_denied` 相当 (reason: `operation_failed_terminal`) を raw 値なしで記録。
- 副作用の冪等性 (operation が外部送信済か不明な失敗) は operation 実装側責務として契約 doc 化。

最終確定は Phase 2 で broker-mediated operation の具体 (provider.call の冪等性要件) を見て codex-plan-review 経由で行う。

## 却下案

- **A (exactly-once / outbox)**: P0/Phase2 の送信系 operation に対し outbox + idempotency 基盤が過剰。将来 repo.push
  等で必要になれば再検討 (本 ADR を supersede)。
- **C (caller tx 従属のみ)**: at-most-once を broker が保証できず (caller rollback で再 redeem 可)、secret access
  boundary の最低線を満たさない。doc 化だけでは状態真実性違反が残る。

## リスク

- `secret_capability_tokens.status` enum 追加 (`failed`) は cross-source 5+source 整合 + 既存 token state machine
  test の更新を要する (CRITICAL invariant 直結 → codex-adversarial-review 必須)。
- broker 所有 tx 化は既存 caller (issue/redeem を呼ぶ箇所) の tx 境界と干渉し得る → Phase 2 で caller を実配線
  しながら確定 (現状 operation 付き caller ゼロのため干渉なし)。

## rollback 手順

- 本 ADR は proposed (実装なし) のため rollback 対象なし。
- 実装後の rollback: `failed` enum 追加 migration は additive (既存 row 不変) のため downgrade は enum 縮小のみ
  (failed token が無い前提を preflight)。broker tx 所有化は revert 可能 (caller 従属へ戻す)。

## 残リスク (defer 期間中、accepted residual)

- 非 custody operation 失敗時、redeem token の終端状態が caller transaction 境界依存 (commit で `redeeming` 残留 /
  rollback で `issued` 巻き戻り)。**P0 単一 operator + broker-mediated operation 未配線のため実害は構造的に
  発生しない** (operation= を渡す adapter コードは存在するが router/worker から到達不能 = production で
  operation 付き redeem を実行する経路が無い)。
- custody / resolver 失敗時の denied + token revoke は R14-F2 / R15-F1 で既に保証済 (本 defer の対象外)。
- **gate**: Phase 2 で broker-mediated operation を最初に配線する PR の着手直前に本 ADR を accepted 化し B 案を
  実装する。それまで operation 付き `redeem_capability_token` の production 配線を行わない。

## 実装対象ファイル (Phase 2 着手時)

- `backend/app/services/secrets/broker.py` (redeem tx 所有 + operation 例外時 failed 終端)
- `backend/app/db/models/secret_capability_token.py` + migration (status `failed` enum、additive)
- `.claude/rules/secretbroker-boundary.md` §8/§9 (redeem transaction 契約 + failed terminal の正本化)
- tests: operation 例外時の failed 終端 + 再 redeem deny + at-most-once negative test

## テスト指針

- operation callback が例外 → token が `failed` 終端 + 再 redeem deny (atomic claim 0 row) + denied audit。
- operation 成功 → `used` 終端 (既存)。
- at-most-once: 同一 token の 2 回目 redeem は status 条件で全 deny。
- caller tx rollback シナリオで claim が巻き戻らない (broker 所有 tx) ことを確認。
