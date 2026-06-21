---
id: "ADR-00059"
title: "SP-001-5 host-portable の local 決着 (DB/Redis loopback bind 維持) + secret revoke material 物理削除の破壊的操作"
status: "accepted"
date: "2026-06-20"
accepted_at: "2026-06-20"
authors:
  - "Claude (autonomous, user 承認 scope: 大元計画 Phase 0 + ADR Gate 8 決定 user 確認済)"
related_sprints:
  - "SP-001-5_host_portable_amendment"
  - "PLAN-10 (大元計画 Phase 0)"
supersedes: null
superseded_by: null
---

ADR Gate Criteria #8 (破壊的操作: host-portable reconciliation + secret revoke material 物理削除) に該当。大元計画 (PLAN-10) Phase 0。SP-001-5 host-portable が in_progress で抱えていた design tension (DB/Redis loopback bind vs 出荷済 restore 契約) を local scope で正式決着し、secret revoke の store material 物理削除の破壊的操作方針を定める。**user 確認ゲート: loopback 維持 / revoke material 削除 (rollback=再登録) を user 承認済 (2026-06-20)**。

最終更新: 2026-06-20

> **status: accepted (2026-06-20)**。codex adversarial plan-review R1-R20 (ADR-00058 と共通 branch、計 33 HIGH + 1 MEDIUM 全 adopt、R20 approve / SHIP-READY) + §12.4 gate + user 承認 (loopback 維持 / revoke material 削除) をもって accepted 昇格。Phase 0 詳細設計 workflow で実コード照合の結果、SP-001-5 の tension は「実装変更でなく正本化で解消」と判明 (現状すでに loopback bind が正しい契約、ports 撤回は過去 adversarial R1 で実害・R2 で revert 済の地雷)。実装着手直前に codex-plan-review R1 minimum + 採否判定 を経て accepted へ昇格 (sprint-pack-adr-gate §12.4)。

## 背景

- 決定対象:
  1. **SP-001-5 host-portable reconciliation の local scope 決着**: DB/Redis を loopback bind (127.0.0.1) 維持とするか、internal-only expose (ports 撤回) へ変えるか。
  2. **secret revoke 時の store material 物理削除** を破壊的操作 (#8) として扱う方針と rollback。
- 関連 Sprint: PLAN-10 Phase 0 / SP-001-5 (host_portable_amendment、in_progress) / ADR-00021 (host_portable_deployment)。
- 前提 / 制約:
  - 大元計画 §0: deploy = local Mac first。VPS 本番は後フェーズ D-1 に分離。worker は host worker (ADR-00058)。
  - **実コード事実 (Phase 0 設計で確認)**: 現状 `docker-compose.yml` は既に `127.0.0.1:5432:5432` / `127.0.0.1:6379:6379` の explicit loopback bind を維持。restore preflight `verify_target_binding_consistency` (taskhub_restore_orchestrator.py) が **この explicit loopback binding を必須要求**。
  - **過去の地雷**: SP-001-5 Pack が目標とした internal-only / ports 撤回 / nc reject は restore/rollback recovery を破壊し、過去 adversarial R1 で実害発生、R2 で revert 済 (memory: operation-bugfix-campaign 教訓)。
  - **SecretBroker 不変条件 (canonical = `secretbroker-boundary.md §5` / `secretbroker-contract.md`)**: revoke は `secret_refs.status` の terminal 化。許可遷移は **`pending->revoked` / `active->revoked` / `deprecated->revoked`** の 3 経路 (rule §5 が明記、**active からの直接 revoke は許容**)。`rotation.py.revoke()` は **rotation フロー専用**の `deprecated->revoked` ステップ (rotation の「revoke old version」) であり canonical の全許可遷移ではない。本 ADR の直接 `secret revoke` は rule §5 準拠 (active 含む) の **新 revoke 経路**で実装し、rotation.py.revoke() は不変。rotation.py は status/timestamp のみ操作 (raw material は別管理)。

## 選択肢

### (1) host-portable bind 方式

| 選択肢 | 概要 | 利点 | 欠点 / リスク |
|--------|------|------|---------------|
| A: loopback bind 維持 (採用) | `127.0.0.1:5432/6379` 維持、internal-only 化は D-1 (VPS) へ分離 | 出荷済 restore preflight と整合、restore/rollback 破壊なし、実コードと一致、tension を実装変更ゼロで closure。P0 個人 1 user・tailnet/外部非公開で十分 | host から psql 直接到達可 (loopback のみ、外部非公開) |
| B: 今 internal-only 化 | ports 撤回 + internal-only expose + restore を docker compose exec 経由へ書換 | SP-001-5 Pack 当初目標、host 非到達でより厳格 | restore orchestrator 大規模書換 + 実 host restore drill 必須、過去 R2 で revert 済の実害地雷、Phase 0 scope 大幅超過 |

### (2) secret revoke material 物理削除

| 選択肢 | 概要 | 利点 | 欠点 / リスク |
|--------|------|------|---------------|
| A: revoked 確定後に store 物理削除 (採用) | rule §5 許可遷移 (active/deprecated/pending → revoked) で revoke 後、別 step で store material 削除、durable reconciliation で収束 | canonical rule §5 遵守 (active→revoked 許容)、material を eventually-consistent 扱い、`status='revoked' AND material_purged_at IS NULL` を source of truth | revoke は terminal で rollback 不能 (rollback=再登録)、DB tx と store (tx 外) の非 atomicity を reconciliation で吸収 |
| B: rotation.py に material 配置/削除を統合 | revoke と material 削除を 1 フロー | 一見シンプル | rotation.py の status-only invariant 破壊、DB tx と store 書込の atomicity が境界跨ぎ、rotation 専用メソッドを直接 revoke へ流用は責務混在 |

## 採用案

- 採用: **(1) 案A loopback bind 維持** + **(2) 案A revoked 後 store 物理削除** (user 承認済 2026-06-20)。
- 理由:
  - (1) 現状すでに loopback が正しい契約 (restore preflight 依存)。ports 撤回は過去 R2 で revert 済の地雷。tension は実装変更でなく本 ADR + local-first runbook での正本化で解消。VPS internal-only は restore orchestrator の docker compose exec 専用化 + 実 host drill を前提に D-1 へ分離。
  - (2) canonical rule §5 (`active`/`deprecated`/`pending` → `revoked`) を遵守し、直接 `secret revoke` は **rule 準拠の新 revoke 経路** (rotation.py.revoke() は rotation 専用 deprecated→revoked で不変、責務分離)。material 削除は status 確定後の別 step、削除失敗は durable reconciliation (`status='revoked' AND material_purged_at IS NULL`) で収束 (source of truth = DB status + material_purged_at flag、eventually-consistent)。
- 実装 Sprint: PLAN-10 Phase 0。
- 実装対象ファイル:
  - `docs/deploy/host-setup.md` (新規 or 追記、Mac local-first runbook + loopback bind の正本化記述)
  - `tests/deploy/test_compose_loopback_binding.py` (新規、ports 撤回の CI regression guard)
  - `backend/app/services/secrets/secret_registration.py` (直接 `secret revoke` = **rule §5 準拠の新 revoke 経路** `active`/`deprecated`/`pending` → `revoked` を実装。rotation.py.revoke() は rotation 専用 deprecated→revoked で流用せず。revoked 確定後に `material_reconciliation` 経由で `LocalSecretStore.delete()` を別 step、`material_purged_at` set)
  - `backend/app/services/secrets/material_reconciliation.py` (新規、**durable orphan-material reconciliation**: `secret_refs.status='revoked'` を source of truth として走査し store 側 material 残存を検出 → idempotent 削除。secret_refs に `material_purged_at timestamptz NULL` + `purge_attempts int` 列を additive 追加し「revoked だが material 未 purge」を durable に検出・再試行可能にする)
  - `migrations/versions/00NN_secret_ref_material_lifecycle.py` (新規、material lifecycle tracking の additive 列: `material_state` (`writing`/`present`/`purging`/`purged`、create/rotate と revoke の crash-safe source of truth、ADR-00058 finding-2 と共有) + `material_purged_at` + `purge_attempts`。**downgrade は 3 条件 preflight**: ① `status='revoked' AND material_purged_at IS NULL` 0 件 ② `material_state IN ('writing','purging')` 0 件 ③ `secret_uri LIKE 'secret://local/%'` 0 件 (full rollback で 0049 より先に local row + lifecycle 列の skew を防ぐ)、いずれか残存で fail-fast)
  - `scripts/taskhub_admin.py` (`secret revoke` subcommand、DESTRUCTIVE_SUBCOMMANDS approval gate + `secret gc-orphans` reconciliation subcommand)
  - `docs/sprints/SP-001-5_host_portable_amendment.md` (Review 欄に local 決着を記録、status 更新)
- 実装ガイダンス:
  - loopback bind は現状維持 = 実装変更なし。`test_compose_loopback_binding.py` で `127.0.0.1:5432/6379` の explicit bind を assert し誤った ports 撤回を CI で阻止。ADR-00021 §12.2 (DB/Redis internal-only 目標) は VPS/production 目標として retain (local override と scope 分離、矛盾でない)。
  - revoke: 直接 `secret revoke` は **rule §5 準拠の新 revoke 経路** (`active`/`deprecated`/`pending` → `revoked` を許容、approval gate が安全弁) で status 遷移を commit。rotation.py.revoke() (rotation 専用 deprecated→revoked) は流用せず不変 (責務分離)。**この時点で material は残存しうる (DB commit と store delete の間で crash しても、revoked は durable に「未 purge」)**。続いて `material_reconciliation` が `store.delete()` を試み、成功時のみ `material_purged_at=now()` を set。失敗時は `purge_attempts++` + 失敗理由を audit に記録し DB revoked + material_purged_at NULL のまま (= 再試行 source of truth として残す)。material 操作は rotation.py の外 (status-only invariant を壊さない)。
  - **crash-safety**: DB revoked commit 後の crash / store delete 失敗いずれも、`status='revoked' AND material_purged_at IS NULL` を走査する `secret gc-orphans` (idempotent、定期 or 手動) が material を確実に purge し material_purged_at を set する。「revoked = secret-at-rest 削除済」の監査表示は **material_purged_at が non-NULL になって初めて真**とし、revoked かつ未 purge の乖離を可視化する。
  - `taskhub secret revoke` は破壊的 subcommand として approval gate を適用 (誤 revoke 前段防御)。
- テスト指針:
  - `tests/deploy/test_compose_loopback_binding.py`: docker-compose の `127.0.0.1:5432/6379` explicit bind を assert (regression guard)。
  - revoke: rule §5 許可遷移を test 固定 — `active->revoked` (直接 revoke、approval gate 経由) / `deprecated->revoked` / `pending->revoked` が成功し store.delete + `material_purged_at` set、`revoked->*` (terminal から再遷移) は reject。再登録 (rollback) で新 version active。
  - **crash-window test (finding-4)**: ① DB revoked commit 後・store.delete 前に crash を模擬 (store.delete を例外注入) → DB は revoked + `material_purged_at IS NULL` + `purge_attempts` 増加、material は store に残存。② `secret gc-orphans` を再実行 → material が purge され `material_purged_at` set (idempotent、2 回目は no-op)。③ `status='revoked' AND material_purged_at IS NULL` が reconciliation で全件検出されること。
  - restore preflight `verify_target_binding_consistency` が loopback bind で PASS する smoke。

## 却下案

- (1) B (今 internal-only 化): restore orchestrator 大規模書換 + 実 host restore drill 必須で Phase 0 scope を大幅超過。過去 R2 で revert 済の実害地雷。VPS 本番化は D-1 で restore orchestrator 改修と共に行うのが正しい → 却下 (D-1 へ分離)。
- (2) B (rotation.py に material 統合): status-only invariant 破壊 + DB tx と store の atomicity 境界跨ぎ + rotation 専用メソッド (deprecated→revoked) を直接 revoke へ流用すると責務混在 → 却下 (直接 revoke は rule §5 準拠の新経路で実装)。

## リスク

| リスク | 検知方法 | 軽減策 |
|--------|----------|--------|
| 誤って ports 撤回が混入し restore 破壊 | `test_compose_loopback_binding.py` CI regression | loopback explicit bind を CI で assert、ADR で正本化 |
| host から psql 直接到達 (loopback) | - | local のみ・tailnet/外部非公開・P0 個人 1 user で許容 (user 承認済)。VPS internal-only は D-1 |
| revoke 途中 crash (DB revoked / material 残存) | `status='revoked' AND material_purged_at IS NULL` の durable 走査 (`secret gc-orphans`) | DB revoked + material_purged_at 列を source of truth、reconciliation が idempotent に purge。crash-window test で commit 後 crash を再現。「revoked=削除済」表示は material_purged_at non-NULL で初めて真 |
| 誤 revoke (terminal、rollback 不能) | approval gate | `taskhub secret revoke` を DESTRUCTIVE approval gate 化、rollback=再登録 |

## rollback 手順

1. **loopback bind**: 現状維持のため rollback 不要。誤った ports 撤回混入は `test_compose_loopback_binding.py` が CI で阻止。
2. **revoke material 削除**: revoked は terminal で rollback 不能 → rollback = `SecretRegistrationService.register` で **再登録 (新 version active)**。
3. 削除途中 crash (DB revoked / material 残存): `secret gc-orphans` reconciliation (`status='revoked' AND material_purged_at IS NULL` を idempotent purge) で収束、DB revoked 維持。
4. **material_lifecycle migration (0050) の downgrade (finding R8/R19 反映)**: `material_state` / `material_purged_at` / `purge_attempts` 列削除は in-flight material の source of truth を消すため **無条件 lossless にしない**。downgrade は **(a) `status='revoked' AND material_purged_at IS NULL` が 0 件、(b) `material_state IN ('writing','purging')` が 0 件、(c) `secret_uri LIKE 'secret://local/%'` の row が 0 件 (local backend material が残っていない、sops へ migrate 済 or revoked+purged 済)** の **3 条件すべて**を **preflight で要求**。これにより full rollback (0050 downgrade → 0049 downgrade) の順序で、local row が残ったまま lifecycle source of truth (material_state 等) だけが先に消える skew を防ぐ (0049 の `secret://local/%` 拒否 preflight と整合、0050 が先に fail-fast)。未収束時は fail-fast し `secret gc-orphans` / local→sops migrate を促す。3 条件 0 件確認後にのみ 3 列を削除。
5. 検証: restore preflight `verify_target_binding_consistency` が loopback で PASS、再登録した secret_ref の redeem 成功、crash-window test (revoke + create/rotate 双方) で reconciliation 収束、**downgrade preflight test (未 purge revoked / material_state writing/purging / `secret://local/%` row のいずれかが残る状態で 0050 downgrade を fail-fast、解消後に downgrade 成功)**、**full rollback regression test (local present row がある状態で 0050→0049 downgrade が lifecycle 列削除前に停止)**。

## 実装 amendment (2026-06-20、SP-PHASE0 batch-1、§12.3 drift 解消 + Codex adversarial R1 adopt)

実装着手時に確定した詳細を本 ADR に追記する (proposed への戻しは不可、accepted のまま amend)。

### A-1. material lifecycle の対象 = broker-owned (local) material

`material_state` / `material_purged_at` / `purge_attempts` は **broker-owned material、すなわち `local`
backend** を統治する。`sops` backend の material は外部 (SOPS file) 管理で本 lifecycle の対象外。
これに伴い:

- **migration 0050 backfill**: 既存 row は 非 revoked→`present` / **revoked→`purged` + `material_purged_at=COALESCE(revoked_at, now())`**。pre-0050 の revoked row は broker-owned local material を持たない (local backend は本 Phase 新設) ため「既に purge 済 (broker-owned material 無し)」が honest。
- **runtime revoke**: `local` は `material_state='purging'` + `material_purged_at NULL` (gc-orphans 対象)、**非 local (sops) は `material_purged_at=now()` を即 set** (broker-owned material 無し)。
- 結果、**`material_purged_at IS NULL` を「local revoked + purge 待ち」のみが真**とする globally-consistent 不変条件が成立し、downgrade condition (a) (`revoked AND material_purged_at IS NULL`=0) が既存 sops revoked row で deadlock しない。当初本文の「revoked 行は material_purged_at NULL のまま backfill」は **新規 runtime local revoke** を指し、pre-0050 既存 revoked row の backfill には適用しない (上記が正)。

### A-2. Codex adversarial R1 findings adopt (4 件、CRITICAL×2 + HIGH×2)

- **F1 (CRITICAL)**: `LocalSecretStore.delete` の keyring 失敗を成功扱いしない。不在のみ idempotent no-op、locked / permission-denied 等は伝播し caller が `purge_attempts++` + `material_purged_at NULL` で再試行 (material 残留のまま purged 化を防止)。
- **F2 (CRITICAL)**: `gc-orphans` の writing-orphan は **row を delete せず `revoked`+`purging` に tombstone** (DB owner を残す)。grace 超過後に resume した late writer の promote (WHERE pending+writing) は 0 rows となり、material は revoke-orphan purge 経路が durable に削除。register/rotate も promote 失敗時に best-effort `store.delete` で自分の material を cleanup (durable backstop = gc-orphans)。row 消滅により owner なし orphan material が残る経路を排除。
- **F3 (HIGH)**: legacy `SecretRotationService.promote` にも `material_state='present'` gate を追加 (precheck + conditional UPDATE WHERE)。status のみで false-present (writing) row を active 化する穴を塞ぐ。
- **F4 (HIGH)**: file backend は write (`os.replace`) / delete (`unlink`) 後に **parent dir を fsync** し crash-safety を確保 (power-loss で DB `present`/`purged` と store の乖離を防ぐ)。

### A-4. Codex adversarial R2 findings adopt (4 件、CRITICAL×2 + HIGH×2、R1 fix の残穴)

- **R2-F1 (CRITICAL)**: keyring `_keyring_delete` の `PasswordDeleteError` は「不在」と「delete failure」を区別できないため、**再 get で不在を確認できた時のみ idempotent success**、値が残る / 再 get 失敗は `LocalSecretStoreError` として伝播 (material 残留を purged 化しない)。
- **R2-F2 (CRITICAL)**: `_purge_revoke_orphans` は local revoked 行を **全件 (purged 含む) 走査し `store.delete` を idempotent backstop** として実行。tombstone+purged 確定後に late writer が material を再作成し cleanup 前に crash しても、次回 gc が再削除し永久 orphan を防ぐ。これにより A-3 の残リスクを **解消** (purged は「最後に purge した時刻」、gc が継続的に absence を enforce)。
- **R2-F3 (HIGH)**: migration 0050 downgrade **condition (a) を local backend に scope** (`AND secret_uri LIKE 'secret://local/%'`)。material lifecycle は broker-owned (local) 統治で sops の purged_at は適用外のため、legacy `SecretRotationService.revoke` (status-only) が残す sops revoked 行 (purged_at NULL は sops では正常) で downgrade が deadlock するのを防ぐ。
- **R2-F4 (HIGH)**: `_fsync_dir` は EINVAL / ENOTSUP (dir fsync 非対応 FS) のみ degraded 許容し、それ以外の durability failure (EIO / ENOSPC / EACCES) は `LocalSecretStorePermissionError` で伝播 (DB を present/purged に進めない)。

### A-5. Codex adversarial R3 findings adopt (2 件、CRITICAL×1 + HIGH×1、運用完全性)

- **R3-F1 (CRITICAL)**: `MaterialReconciliationService.gc_orphans` を runtime から invokable にする
  **`taskhub secret-gc-orphans --tenant-id N` CLI** を batch-1 に追加 (`scripts/taskhub_secret_gc.py` +
  `scripts/taskhub_admin.py`)。これにより revoke 失敗時の durable convergence (再実行で material 削除に
  収束) が実際に実行可能となり「durable convergence」主張が真になる。raw secret 非出力、purge_failed
  残存時 exit 1。user 向け secret 管理 CLI (init/status/create/rotate/revoke) は S3 が担当 (本 CLI は
  revoke backstop に限定)。
- **R3-F2 (HIGH)**: `_purge_revoke_orphans` の backstop delete 失敗を **already_purged 行含め全件**
  `report.purge_failed` + `purge_attempts++` に記録 (purged tombstone の late-writer 再作成 material が
  消せない場合に GC が clean を誤報告しない)。

### A-6b. Codex adversarial R4-R6 findings adopt (mirror gate 網羅)

R3 で CRITICAL 解消後、R4-R6 は「promote / broker に入れた gate の未カバー mirror 経路」を順次封鎖
(全 HIGH、CRITICAL=0 継続):

- **R4-F1 (HIGH)**: `taskhub secret-gc-orphans --writing-grace-seconds` に正整数 validator。
- **R4-F2 (HIGH)**: `rotation.promote` の new promote 失敗時に old demote を `session.rollback()`。
- **R5-F1 (HIGH)**: grace 正整数強制を `gc_orphans()` service 入口へ移動 (直接 Python API も保護、bool 拒否)。
- **R5-F2 (HIGH)**: `rotation.rollback()` の deprecated_restore 失敗時にも `session.rollback()`。
- **R6-F1 (HIGH)**: `rotation.rollback()` に identity + material_state gate (scope/name 一致 +
  `active.rotated_from_id == target` + target `material_state='present'`、UPDATE WHERE にも反映)。
  promote の F-PR48-002 + false-present 防止の rollback 版欠落を封鎖。
- **R6-F2 (HIGH)**: `CompositeSecretResolver` の local 分岐に status active/deprecated +
  `material_state='present'` fail-closed gate。broker を経由しない直接利用 (RepoProxy/webhook、
  `DbWebhookSecretResolver` は注入 resolver へ委譲) でも未検証 material を resolve させない。

### A-6c. Codex adversarial R7 findings adopt (3 件、rotate precondition + sops material 整合 + resolver canonical)

R6 で mirror gate 網羅後、R7 は「register と rotate の非対称」「local default が sops に与える副作用」
「resolver の独立 grammar」という残穴を封鎖 (HIGH×2 + MEDIUM×1、CRITICAL=0 継続):

- **R7-F1 (HIGH)**: `SecretRegistrationService.rotate()` に write 前 precondition gate を追加 (old が
  `status='active'` + `material_state='present'` + new allowlists 非空)。`promote_rotated` は old=active
  を必須とするため、非 active / 未 present の old から rotate すると、新 row が **永久 promote 不能な
  pending+present orphan** になり (gc-orphans は pending+writing のみ tombstone)、material at-rest 保持
  + (tenant,scope,name) pending≤1 index を占有していた。register の allowlist guard と対称化。
- **R7-F2 (HIGH)**: migration 0050 / ORM に CHECK `secret_refs_ck_transient_material_local_only`
  (`material_state in ('writing','purging')` ⟹ `secret_uri like 'secret://local/%'`) を追加。default
  server-default `'writing'` は local の false-present 防止に必要だが、sops の直接登録 (operational SQL
  / D-4) が material_state を省略すると default `'writing'` で **silent に broker-unusable**
  (issue/redeem の `material_state='present'` gate が `material_not_present` で deny) になっていた。
  transient state を local 専用に限定し、use 時の無言 deny を **insert 時の fail-closed** へ前倒し。
  operational SQL (`docs/操作手順/github-app-registration.md`) と DB test fixture も `present` 明示へ更新。
- **R7-F3 (MEDIUM)**: `SopsSubprocessResolver` の独立 URI regex (`scope=[a-z0-9_]+`) を撤去し
  `uri_pattern.parse_secret_uri` / `SECRET_SCOPES` へ集約 (backend は sops のみ許可)。canonical 集約前は
  DB CHECK が弾く非 canonical scope (例 `secret://sops/cluster/...`) を resolver boundary だけが受理し、
  注入 resolver 直接利用で cross-source-enum-integrity §1 が破れていた。

### A-6d. Codex adversarial R8 findings adopt (1 件、rotate present 化の atomic claim 化)

R7-F1 の precondition gate が **fetch 時点の stale precheck** に過ぎない TOCTOU を封鎖 (HIGH×1、CRITICAL=0 継続):

- **R8-F1 (HIGH)**: `rotate()` の present 化 UPDATE を **old が現在も active+present であること** に
  atomic 条件付けした (非相関 EXISTS、`old.status='active' AND old.material_state='present'`)。R7-F1 の
  precheck (fetch 時) から present 化 UPDATE までの間に別操作が old を promote/revoke/deprecate すると、
  UPDATE が new の status/material_state しか見ないため new が pending+present として残り、promote_rotated
  (old=active 必須) が永久失敗 + gc-orphans (pending+writing のみ tombstone) でも回収されない durable
  orphan + pending≤1 index 占有になっていた。EXISTS 不一致時は UPDATE が 0 行 → new は pending+writing の
  まま (gc-orphans が tombstone) + material best-effort cleanup + conflict 返却。DB-gated SQL invariant
  test 追加 (old deprecated→0 行/writing 維持、old active→1 行/present)。並行 service レベル e2e は S4。

### A-6e. Codex adversarial R9 findings adopt (1 件、post-present orphan を gc-orphans 延長で回収)

R8-F1 の atomic claim が present 化時点しか塞げない post-present window を封鎖 (HIGH×1、CRITICAL=0 継続):

- **R9-F1 (HIGH)**: present 化 commit 後 `promote_rotated` 前の window で old が並行 revoke/rollback/promote
  されると、old が active+present でなくなり new は永久 promote 不能な pending+present orphan になる
  (R8-F1 の EXISTS は present 化時点の非 locking check で、READ COMMITTED の post-present window は塞げ
  ない)。**設計判断**: R9 提示の 2 案 — (A) rotate 中に old を `rotating`/lease で予約し revoke/rollback
  /promote が拒否する reservation 方式、(B) gc-orphans を延長して stale pending+present を回収する方式 —
  のうち **(B) を Phase 0 invariant として採用**。理由: 本 ADR の core 設計が「material lifecycle +
  gc-orphans reconciliation で eventual-consistent 収束」(A-1/A-3) であり、新 status enum / column / lock
  を導入する reservation 方式 (5+source enum 拡張 = ADR Gate、write-path guard 多数、lease expiry 管理) は
  Phase 0 には重く multi-host (D-1) 向き。(B) は確立済 reconciliation の additive 延長で低リスク・整合的。
  - 実装: `MaterialReconciliationService._tombstone_stale_rotation_candidates` を `gc_orphans` の
    tombstone-writing と purge の間に追加。grace 経過後、`rotated_from` の old が active+present でない
    local pending+present row を **相関 NOT EXISTS** で検出し revoked+purging へ tombstone (続く
    `_purge_revoke_orphans` が material を idempotent purge)。in-flight rotate→promote と race しないよう
    grace + tombstone 時 NOT EXISTS re-check (SELECT→UPDATE 間に promote が走れば old active 化で 0 行 =
    legit promote を pre-empt しない)。promote_rotated は old=active 必須のため、old が active でない new は
    どのみち promote 不能 → tombstone は legit candidate を巻き込まない。
  - test: DB-gated SQL invariant test (old deprecated→1 行 tombstone/revoked+purging、old active→0 行/preserve)。
    並行 service レベル e2e (present 化後 old 並行 revoke → gc 回収) は S4。
  - 残リスク: gc 実行間隔の間は stale pending+present が一時残存 (broker gate で issue/redeem 不可、次回 gc で
    回収)。eventually-consistent 収束は Phase 0 accepted (A-6 と同方針)。

### A-6f. Codex adversarial R10 findings adopt (1 件、backstop delete 失敗時の false-purged 撤回)

R2-F2/R3-F2 で導入した「purged 行も全件走査する backstop delete」の delete 失敗時 fail-open を封鎖
(HIGH×1、CRITICAL=0 継続):

- **R10-F1 (HIGH)**: `_purge_revoke_orphans` は purged 確定済 local revoked 行も走査し、late-writer が
  再作成した material を backstop delete する。しかし **delete 失敗時** は purge_attempts++ と report 追記
  のみで `material_state='purged'` / `material_purged_at` non-null を維持していた。late-writer 再作成 +
  delete 失敗のシナリオでは **material が実在するのに DB source of truth と `/api/v1/me` inventory が
  「secret-at-rest 削除済」と言い続ける false-purged (fail-open)** になる (purge_attempts は履歴回数で
  absence 検証状態を表さない)。fix: already-purged 行の delete 失敗時は **`material_state='purging'` +
  `material_purged_at=NULL` へ撤回** (purge_attempts++ と併せ)。これにより inventory / 0050 downgrade
  preflight (condition (a): `revoked AND material_purged_at IS NULL AND local`) が「未 purge」と認識し
  fail-closed、次回 gc が再 delete を試行する。material_purged_at non-null = durable 削除済 (A-1/A-3) の
  invariant を absence 検証不能時に偽証しない。DB-gated regression test 追加 (purged 行 + delete 失敗 →
  purging+NULL+purge_attempts++ + purge_failed 報告)。

### A-6g. Codex adversarial R11 findings adopt (1 件 CRITICAL、LocalSecretStore backend drift fail-closed)

R10-F1 の撤回ロジックより手前で false-purged が再発する根本経路を封鎖 (CRITICAL×1、R3 以来初の CRITICAL):

- **R11-F1 (CRITICAL)**: `LocalSecretStore` の物理 backend (keyring/file) は `_detect_keyring()` の
  **runtime 検出**で決まり、material に束縛されていなかった。`TASKHUB_DISABLE_KEYRING` / keyring import
  不在 / probe 例外で silent に file mode へ fallback するため、keyring mode で登録した material を後続の
  revoke/gc が file mode で実行すると `_file_delete()` が対象不在で **no-op 成功** → caller が
  `material_state='purged'` / `material_purged_at` を set できる (逆方向も同様)。R1/R2 の「keyring delete
  failure を伝播」対策を、**delete が成功扱いになることで迂回**する別経路で、material が片方の store に
  残ったまま inventory / downgrade preflight / gc report が clean を示す false-purged になる。単一 host
  でも env / Keychain availability の変化で起きるため D-1 へ defer 不可、P0 で封鎖。
  - **設計判断**: R11 提示の 2 案 — (A) secret_ref に per-material backend を永続化 (新 column = migration /
    service 横断 / store signature 変更)、(B) deployment-wide に backend を固定し drift 時 fail-closed —
    のうち **(B) を採用**。Phase 0 は単一 deployment (local Mac first) であり、(B) は LocalSecretStore に
    自己完結 (schema / service 非変更) で低リスク。実装: `base_dir/backend.marker` (non-secret) に初回
    store で物理 backend を pin し、store/resolve/delete の全入口で runtime backend と marker の drift を
    検出して `LocalSecretStoreError` を上げる (fail-closed)。drift 時 delete は raise → caller (revoke の
    `_best_effort_purge` / gc の `_purge_revoke_orphans`) が purged 化せず再試行 (R10-F1 撤回と連動)。
  - test: keyring↔file drift で delete/resolve が fail-closed (material は元 backend に残存) + marker 記録 +
    consistent reopen 不破壊。
  - 残リスク: 正当な backend 移行 (Mac→Linux 等) は marker drift で全 IO fail-closed になる → operator が
    material を新 backend へ移行し marker 更新する運用手順が必要 (silent false-purge より安全側、Phase 0
    accepted、runbook は S3/S4)。

### A-6h. Codex adversarial R12 findings adopt (1 件 CRITICAL、marker absence / init-race の fail-open 封鎖)

R11-F1 の marker が「不在時 fail-open」「初期化 race」という残穴を持つことを封鎖 (CRITICAL×1):

- **R12-F1 (CRITICAL)**: R11 の `_assert_backend_consistent()` は marker 不在を「未初期化=空 deployment=
  安全」として success を返していた。material が既に存在する状況 (marker 削除 / `TASKHUB_SECRETS_HOME`
  変更 / marker 無しの restore / marker を dir で置換) では、file-mode store が keyring-owned material に
  対し `delete()` を呼んで `_file_delete()` が no-op 成功 → revoke/gc が `material_state='purged'` に進む
  false-purged が再発する。加えて concurrent first-store で 2 process が同時に marker 不在を観測し、
  `_record_backend()` の非排他 overwrite で loser が別 backend に material を書くと marker と乖離する。
  これは R11 が閉じたはずの false-purged class が marker absence / 初期化 race へ移っただけ。単一 host
  でも起きるため P0 で封鎖 (D-1 defer 不可)。
  - fix (R12 推奨を全採用):
    1. **marker 不在を resolve()/delete() で fail-closed** (`require_marker=True`)。authoritative backend
       を確定できない以上、現在 backend の no-op 成功 / 誤 not-found を許さず例外を上げ、caller が purged
       化せず再試行する (R10-F1 撤回と連動)。
    2. **store() の marker pin を atomic 化** (`O_CREAT|O_EXCL`)。既存なら re-read して現在 backend と
       一致を verify してから material を書く。first-store race の loser は EEXIST → re-read で winner の
       backend を読み、自分と異なれば drift で fail-closed (別 backend へ material を書かない)。
    3. **非正規 / insecure marker を reject** (symlink / 非通常ファイル / group・other writable)。
  - test: marker 削除後の delete/resolve fail-closed (material 残存) / 非正規 (dir) marker reject /
    world-writable marker reject / pin 済と別 backend での store reject (keyring に material が入らない)。
    既存 keyring delete test は marker=keyring を事前 pin して「初期化済 deployment での delete 挙動」を
    検証するよう更新 (marker 不在 fail-closed と区別)。
  - 残リスク: A-6g と同様、正当な backend 移行は marker 更新 (operator init / reconcile) を要する。
    upgrade / restore で marker を欠いた既存 deployment は明示初期化が必要 (silent false-purge より安全側、
    runbook は S3/S4)。

### A-6i. Codex adversarial R13 findings adopt (2 件 CRITICAL、first-store race-safety)

R11/R12 で backend-authority を pin した後に残った **first-store concurrency race** 2 件を封鎖 (CRITICAL×2):

- **R13-F1 (CRITICAL)**: `_load_or_create_master_key` が非 atomic だった。`_write_secure_file` は共有 temp
  名 (`.{name}.tmp`) + `O_TRUNC` で、concurrent first-store で 2 process が別 Fernet key を生成し一方が
  `master.key` を上書きすると、上書き前 key で暗号化済 material が復号不能 (false-present / material loss、
  restart 後に別 key を読む)。fix: master key 生成を `_atomic_publish` (unique temp→`os.link` で atomic
  create-if-absent) 経由にし、winner / loser とも **同一の最終 key** を返す (loser は winner の完成 file を
  読む)。`_write_secure_file` も共有 temp を `tempfile.mkstemp` の per-call unique temp へ変更。
- **R13-F2 (CRITICAL)**: R12 の `_ensure_marker_pinned` の `FileExistsError` 分岐は `raced is not None and
  raced != current` でのみ raise し、**marker が O_EXCL 後〜re-read 前に削除されると `raced is None` で
  success を返し**、marker 無しで material を書いてしまう (registration は present で commit、後続
  resolve/delete は marker 不在で fail-closed → active material が stranded、purge 収束も block)。fix:
  marker 作成を `_atomic_publish` に統一し、loser は winner の完成 marker を読む。**winner の backend が
  current と一致しない / 読めない場合は必ず fail-closed** (`final != current → raise`)。publish 後に marker
  を再読し content / mode を verify してから material 書込を許す (final-verify)。
  - test: `_atomic_publish` の loser-returns-existing (上書きなし) / master.key 既存時は上書きせず既存 key で
    material 復号可能 (R13-F1) / pin 済と別 backend の store reject (R13-F2、drift)。
  - 残リスク: `os.link` 非対応 FS では create-if-absent が OSError → fail-closed (Phase 0 target の APFS /
    ext4 は link 対応)。concurrent first-store の loser は (同一 backend なら) winner 値で成功、別 backend
    なら fail-closed → caller retry (rare、recoverable、material loss / false-purge なし)。

### A-6j. Codex adversarial R14 findings adopt (2 件 HIGH、新 fail-closed 挙動の統合整合)

LocalSecretStore の fail-closed 化 (R11-R13) が caller 側に与える 2 つの P0-reachable 不整合を封鎖 (HIGH×2):

- **R14-F1 (HIGH)**: `register()` / `rotate()` は pending+writing の DB owner row を `store.store()`
  (= marker pin) **より前**に commit する。fresh base_dir で「row commit 後 / store() 前」に crash すると
  marker 不在のまま row が残り、後続 gc の `delete()` (marker 必須・fail-closed) が永久に purge_failed →
  `material_purged_at=NULL` のまま収束不能 (ADR-00058 create-crash convergence 違反)。fix:
  `LocalSecretStore.ensure_initialized()` を公開し、register/rotate が **DB row commit の前**に呼んで
  marker を先に pin する。test: pinned marker 下で store 前 crash の writing-orphan が gc で revoked→
  purging→purged に収束 (DB-gated)。
- **R14-F2 (HIGH)**: `redeem_capability_token()` は atomic claim 後 `_resolve_secret()` を try なしで呼ぶ。
  LocalSecretStore / CompositeSecretResolver が新たに raise する custody/resolver 失敗 (marker 不在 /
  drift / permission / decrypt / material gate) が **claim 済 token を消費したまま例外伝播**すると、
  `secret_capability_denied` audit と token revoke を bypass し 500 + token_used 誤分類になる (custody
  失敗を隠蔽)。fix: `_resolve_secret()` を custody/resolver 例外 (`CompositeResolverError` /
  `LocalSecretStoreError` / `SopsResolverError`) で捕捉し、claimed token revoke + `secret_capability_denied`
  audit + `BrokerRedeemDenied(material_not_present)` を返す (raw secret / 例外詳細は出さず reason_code のみ)。
  test: claim 後に raise する resolver を注入し denied + operation 未実行 + denied audit + redeemed audit
  なしを検証 (no-DB)。

### A-6k. Codex adversarial R15 findings adopt (1 件 HIGH、operation path の custody 失敗封鎖)

R14-F2 が pre-resolve のみ保護していた穴を operation path へ拡張 (HIGH×1、Phase-0-reachable):

- **R15-F1 (HIGH)**: `redeem_capability_token()` の R14-F2 custody 捕捉は `_resolve_secret()` のみで、
  `operation(context)` は try 外だった。Phase 0 GitHub path は `GitHubAppAdapter` → broker `operation` →
  `HttpxGitHubTransport.create_draft_pr()` が **installation token を再 resolve** する。そこで resolver が
  custody 失敗 (SOPS timeout / age key 欠落 / LocalSecretStore drift) すると、claim 済 token を消費したまま
  例外伝播し、R14-F2 の denied audit + token revoke を bypass (500 + token_used 誤分類)。fix: pre-resolve と
  operation の両 path を共有 helper `_deny_after_claim_custody_failure` で denied 化 (token revoke +
  `secret_capability_denied` audit + `BrokerRedeemDenied(material_not_present)`、stage=resolve/operation を
  log)。**非 custody な operation 失敗 (provider 5xx / GitHub API error 等) は従来どおり伝播**させ token は
  消費済扱い (boundary §9) — custody/resolver 例外型 (`CompositeResolverError` / `LocalSecretStoreError` /
  `SopsResolverError`) のみ denied 化する。
  - test: operation が `LocalSecretStoreError` を raise → denied + revoke + denied audit + redeemed audit
    なし / 非 custody (`RuntimeError`) は伝播 (no-DB)。

### A-6l. Codex adversarial R16 findings (1 件 HIGH 採用 / 1 件 HIGH defer、ともに pre-existing SecretBroker)

R16 の 2 件は **本 batch (S1+S2 material lifecycle) の regression ではなく pre-existing SecretBroker 経路**
(R16-F1 = redeem transaction 境界、R16-F2 = rotation.read_* approval target、いずれも broker.py の既存 commit
由来)。broker.py に触れた diff の深掘り監査で表面化。user 判断 (2026-06-21) で **F2 採用 + F1 defer**:

- **R16-F2 (HIGH、採用)**: `secret.verify` / `rotation.read_old` / `rotation.read_new` の approval/target は
  caller-supplied `target` を信用し、実 `secret_ref.id` / `version` との同一性を検証していなかった。secret A の
  token を発行しつつ target に secret B を入れ、B の approval で通すと fingerprint は不整合 target に自己整合し
  redeem でき、operation には secret A の handle が渡る (approval/audit の対象すり替え)。fix (server-owned-
  boundary §1 準拠): secret 自己参照 3 operation で `target.secret_ref_id == secret_ref.id AND target.version ==
  secret_ref.version` を **issue (approval 照合前) と claim (post-claim) の両方で強制** (不一致は
  `secret_target_mismatch` deny、claim 側は token revoke + denied audit)。現状 production caller は無く
  (webhook は resolver 直接 resolve、`issue_capability_token` の caller ゼロ) forward-looking hardening。
  test: issue/redeem の target substitution deny + match pass (no-DB)。
- **R16-F1 (HIGH、defer → follow-up ADR)**: `redeem_capability_token` の `operation(context)` が **非 custody
  例外**を投げると `_mark_claimed_token_used()` に到達せず、外部 session が rollback すれば atomic claim ごと
  巻き戻り token が `issued` に戻って **再 redeem 可能** (外部副作用後でも)、commit すれば `redeeming` のまま
  非終端 = 状態真実性違反。これは **redeem の transaction 契約 (commit-before-side-effect / at-most-once /
  exactly-once semantics) の再設計**を要し、ADR Gate (API 契約 + secret access boundary) に該当するため、本
  batch (material lifecycle) のスコープ外として **専用 ADR + follow-up sprint へ defer** (user 承認 2026-06-21)。
  - **残リスク (defer 期間中)**: 非 custody operation 失敗時、redeem token の終端状態が caller transaction 境界
    依存。P0 単一 operator では実害は限定的だが、broker redeem を operation 付きで使う前に follow-up で
    transaction 境界を確定する。custody/resolver 失敗は R14-F2/R15-F1 で既に denied 化済 (本 defer の対象外)。
  - **follow-up**: SecretBroker redeem transaction boundary / capability token terminal-state guarantee ADR
    (新規)。本 batch では着手しない。

### A-6. 残リスク (Phase 0 accepted)

R2-F2 + R3-F1 で late-writer 永久 orphan + 実行経路欠如は解消。gc 実行間隔の間は再作成 material が一時的に
残る (encrypted-at-rest・broker gate で redeem 不可、次回 `taskhub secret-gc-orphans` で除去) — operator
or 定期実行での drain を前提とした eventually-consistent 収束は Phase 0 accepted。定期 scheduler 化と
O(local revoked 行) 再走査の lease/epoch bound は D-1 (multi-host) で検討。
