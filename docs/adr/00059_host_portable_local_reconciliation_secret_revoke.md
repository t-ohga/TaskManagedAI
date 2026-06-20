---
id: "ADR-00059"
title: "SP-001-5 host-portable の local 決着 (DB/Redis loopback bind 維持) + secret revoke material 物理削除の破壊的操作"
status: "proposed"
date: "2026-06-20"
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

> **status: proposed**。Phase 0 詳細設計 workflow で実コード照合の結果、SP-001-5 の tension は「実装変更でなく正本化で解消」と判明 (現状すでに loopback bind が正しい契約、ports 撤回は過去 adversarial R1 で実害・R2 で revert 済の地雷)。実装着手直前に codex-plan-review R1 minimum + 採否判定 を経て accepted へ昇格 (sprint-pack-adr-gate §12.4)。

## 背景

- 決定対象:
  1. **SP-001-5 host-portable reconciliation の local scope 決着**: DB/Redis を loopback bind (127.0.0.1) 維持とするか、internal-only expose (ports 撤回) へ変えるか。
  2. **secret revoke 時の store material 物理削除** を破壊的操作 (#8) として扱う方針と rollback。
- 関連 Sprint: PLAN-10 Phase 0 / SP-001-5 (host_portable_amendment、in_progress) / ADR-00021 (host_portable_deployment)。
- 前提 / 制約:
  - 大元計画 §0: deploy = local Mac first。VPS 本番は後フェーズ D-1 に分離。worker は host worker (ADR-00058)。
  - **実コード事実 (Phase 0 設計で確認)**: 現状 `docker-compose.yml` は既に `127.0.0.1:5432:5432` / `127.0.0.1:6379:6379` の explicit loopback bind を維持。restore preflight `verify_target_binding_consistency` (taskhub_restore_orchestrator.py) が **この explicit loopback binding を必須要求**。
  - **過去の地雷**: SP-001-5 Pack が目標とした internal-only / ports 撤回 / nc reject は restore/rollback recovery を破壊し、過去 adversarial R1 で実害発生、R2 で revert 済 (memory: operation-bugfix-campaign 教訓)。
  - SecretBroker 不変条件: revoke は `secret_refs.status` の terminal 化。rotation.py は status / timestamp のみ操作 (raw material は別管理)。`deprecated -> revoked` 必須遷移 (active から直接 revoke 不可)。

## 選択肢

### (1) host-portable bind 方式

| 選択肢 | 概要 | 利点 | 欠点 / リスク |
|--------|------|------|---------------|
| A: loopback bind 維持 (採用) | `127.0.0.1:5432/6379` 維持、internal-only 化は D-1 (VPS) へ分離 | 出荷済 restore preflight と整合、restore/rollback 破壊なし、実コードと一致、tension を実装変更ゼロで closure。P0 個人 1 user・tailnet/外部非公開で十分 | host から psql 直接到達可 (loopback のみ、外部非公開) |
| B: 今 internal-only 化 | ports 撤回 + internal-only expose + restore を docker compose exec 経由へ書換 | SP-001-5 Pack 当初目標、host 非到達でより厳格 | restore orchestrator 大規模書換 + 実 host restore drill 必須、過去 R2 で revert 済の実害地雷、Phase 0 scope 大幅超過 |

### (2) secret revoke material 物理削除

| 選択肢 | 概要 | 利点 | 欠点 / リスク |
|--------|------|------|---------------|
| A: revoked 確定後に store 物理削除 (採用) | `deprecated->revoked` 既存遷移後、別 step で store material 削除、削除失敗は orphan GC | 既存 state machine 遵守、material を eventually-consistent 扱い、status を source of truth | revoke は terminal で rollback 不能 (rollback=再登録)、DB tx と store (tx 外) の非 atomicity を GC で吸収 |
| B: rotation.py に material 配置/削除を統合 | revoke と material 削除を 1 フロー | 一見シンプル | rotation.py の status-only invariant 破壊、DB tx と store 書込の atomicity が境界跨ぎ、active→revoked 直行は既存遷移違反 |

## 採用案

- 採用: **(1) 案A loopback bind 維持** + **(2) 案A revoked 後 store 物理削除** (user 承認済 2026-06-20)。
- 理由:
  - (1) 現状すでに loopback が正しい契約 (restore preflight 依存)。ports 撤回は過去 R2 で revert 済の地雷。tension は実装変更でなく本 ADR + local-first runbook での正本化で解消。VPS internal-only は restore orchestrator の docker compose exec 専用化 + 実 host drill を前提に D-1 へ分離。
  - (2) rotation.py の status-only invariant と `deprecated->revoked` 遷移を遵守。material 削除は status 確定後の別 step とし、削除失敗は orphan material GC で reconciliation (status を source of truth、eventually-consistent)。
- 実装 Sprint: PLAN-10 Phase 0。
- 実装対象ファイル:
  - `docs/deploy/host-setup.md` (新規 or 追記、Mac local-first runbook + loopback bind の正本化記述)
  - `tests/deploy/test_compose_loopback_binding.py` (新規、ports 撤回の CI regression guard)
  - `backend/app/services/secrets/secret_registration.py` (revoke step: `deprecated->revoked` 後に `LocalSecretStore.delete()` を別 step、削除失敗は orphan GC 記録)
  - `scripts/taskhub_admin.py` (`secret revoke` subcommand、DESTRUCTIVE_SUBCOMMANDS approval gate)
  - `docs/sprints/SP-001-5_host_portable_amendment.md` (Review 欄に local 決着を記録、status 更新)
- 実装ガイダンス:
  - loopback bind は現状維持 = 実装変更なし。`test_compose_loopback_binding.py` で `127.0.0.1:5432/6379` の explicit bind を assert し誤った ports 撤回を CI で阻止。ADR-00021 §12.2 (DB/Redis internal-only 目標) は VPS/production 目標として retain (local override と scope 分離、矛盾でない)。
  - revoke: `SecretRotationService` で `deprecated->revoked` 遷移を commit 後、`SecretRegistrationService` 側で `store.delete()` を実行 (material 操作は rotation.py の外、status-only invariant を壊さない)。削除失敗時は orphan material として GC log 記録し DB revoked は維持。
  - `taskhub secret revoke` は破壊的 subcommand として approval gate を適用 (誤 revoke 前段防御)。
- テスト指針:
  - `tests/deploy/test_compose_loopback_binding.py`: docker-compose の `127.0.0.1:5432/6379` explicit bind を assert (regression guard)。
  - revoke: `deprecated->revoked` 遷移 + store.delete、active から直接 revoke は reject (既存遷移遵守)、削除失敗時 DB revoked 維持 + orphan GC 記録、再登録 (rollback) で新 version active。
  - restore preflight `verify_target_binding_consistency` が loopback bind で PASS する smoke。

## 却下案

- (1) B (今 internal-only 化): restore orchestrator 大規模書換 + 実 host restore drill 必須で Phase 0 scope を大幅超過。過去 R2 で revert 済の実害地雷。VPS 本番化は D-1 で restore orchestrator 改修と共に行うのが正しい → 却下 (D-1 へ分離)。
- (2) B (rotation.py に material 統合): status-only invariant 破壊 + DB tx と store の atomicity 境界跨ぎ + active→revoked 直行が既存遷移違反 → 却下。

## リスク

| リスク | 検知方法 | 軽減策 |
|--------|----------|--------|
| 誤って ports 撤回が混入し restore 破壊 | `test_compose_loopback_binding.py` CI regression | loopback explicit bind を CI で assert、ADR で正本化 |
| host から psql 直接到達 (loopback) | - | local のみ・tailnet/外部非公開・P0 個人 1 user で許容 (user 承認済)。VPS internal-only は D-1 |
| revoke 途中 crash (DB revoked / material 残存) | orphan material GC log | status を source of truth、orphan GC で reconciliation。削除は idempotent |
| 誤 revoke (terminal、rollback 不能) | approval gate | `taskhub secret revoke` を DESTRUCTIVE approval gate 化、rollback=再登録 |

## rollback 手順

1. **loopback bind**: 現状維持のため rollback 不要。誤った ports 撤回混入は `test_compose_loopback_binding.py` が CI で阻止。
2. **revoke material 削除**: revoked は terminal で rollback 不能 → rollback = `SecretRegistrationService.register` で **再登録 (新 version active)**。
3. 削除途中 crash (DB revoked / material 残存): orphan material GC で reconciliation (DB revoked 維持)。
4. 検証: restore preflight `verify_target_binding_consistency` が loopback で PASS、再登録した secret_ref の redeem 成功。
