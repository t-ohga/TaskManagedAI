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
