---
id: "ADR-00028"
title: "Split-Brain Second Line of Defense (active-registry marker chain + cutover 2-party-control + 2PC + fleet-wide lease + signer-host ownership + commit-time cryptographic proof + L1+L2+L3 write gate + clock monotonicity)"
status: "proposed"
created_at: "2026-05-21"
updated_at: "2026-05-21"
decision_target: "Host-Portable deployment (ADR-00021) における split-brain prevention の **second line of defense**: active.signed/decommission.signed/prepare.signed/commit.signed marker chain + cutover 2-party-control + two-phase commit + fleet-wide cutover lease + signer-host ownership binding + commit-time cryptographic finalization signature + active-registry write gate (L1 API ingress + L2 worker dequeue + L3 DB mutation boundary) + server-owned clock monotonicity attestation"
sprint_ref:
  - "SP-012_p0_acceptance"
adr_gate_criteria:
  - "#8 (破壊的操作): host migration / cutover の cross-host atomic 不可能性 + rollback 戦略"
  - "#7 (外部公開設定 — host migration の意味で): Tailscale 閉域内の host fleet membership 管理 + 越境 cutover の確実な one-active-host invariant"
  - "#2 (DB schema — 意味的に active state durability): CommitMarker による long-term active state 証明 + L3 DB mutation boundary gate"
co_accepted_with:
  - "ADR-00029 (Approval Keyring Rotation、co-accepted): keyring rotation で生成される signer fingerprint allowlist と active-registry の signer-host ownership binding は相互依存、両 ADR 同時 accepted"
  - "SP-012_p0_acceptance must_ship 2 件 (本 ADR と co-accepted、SP-012 Batch A 着手前に accepted 化必須)"
related_adrs:
  - "ADR-00021 (Host-Portable Deployment、accepted、§11.2 split-brain prevention の first line = freeze.signed 単体、本 ADR は second line として強化)"
  - "ADR-00026 (PITR WAL Archiving、accepted、cutover 後の WAL archive の continuity 保証は本 ADR の cutover phase に依存)"
related_documents:
  - "`.claude/plans/sp012-split-brain-keyring.md` §3.B (active-registry real flow) + §9.3 (ADV2 R1 adopt) + §9.4 (ADV2 R2 adopt) + §9.5 (ADV2 R3 adopt) + §9.6 (ADV2 R5 adopt) + §9.7 (ADV2 R6 adopt) + §9.8 (ADV2 R8 adopt) + §9.9 (ADV2 R9 adopt) + §9.10 (ADV2 R10 adopt)"
  - "`docs/基本設計/00_全体アーキテクチャ.md` (DD-00) host-portable deployment boundary"
---

最終更新: 2026-05-21

# ADR-00028: Split-Brain Second Line of Defense

## 1. 背景

TaskManagedAI P0 (個人専用、Tailscale 閉域、単一 VPS、Docker Compose) は ADR-00021 で host-portable deployment を確立し、host migration (Mac ↔ Linux ↔ VPS) を **freeze.signed** marker による source side 一時停止のみで第一線防御していた。

しかし、Sprint 12 で T09 host migration drill (Mac → VPS、RTO ≤ 4h) を P0 Exit hard gate として実施する過程で、次の **second line of defense gap** が明らかになった:

1. **`freeze.signed` 単体では cross-host split-brain を防げない**: source 側の writes 一時停止だけでは、target 側 startup と同時並行 (race) を防ぐ保証なし、両 host で writes 同時可能化のリスク
2. **cutover (= source decommission + target activate) を atomic に保証する mechanism 不在**: cross-host atomic transaction は分散原理的に不可能、両 host を同時更新する操作は中間失敗時に inconsistent state を残す
3. **2-party-control / approval artifact binding が active state 証明に組み込まれていない**: marker chain だけでは「approval を取って実行された cutover」と「攻撃者が任意に作った marker chain」を区別できない
4. **active-registry gate が API ingress のみ → ARQ worker / background job / service-layer direct mutation を bypass 可能**: write surface 全停止 (split-brain 本質) を達成できない
5. **clock rollback 攻撃で `record_signed_at` を期限内へ backdate するだけで dual-trust expiry すり抜け** (approval issue 経路の独立証明不在)

本 ADR は ADR-00021 §11.2 split-brain prevention を補完し、host migration 後の active state を **暗号学的に証明可能** + **全 write surface を停止可能** + **clock rollback 耐性** を持つ second line of defense として確立する。

## 2. 決定対象

1. ActiveMarker / DecommissionMarker / PrepareMarker / CommitMarker の 4 marker schema を別 signature domain で分離 (`taskhub.active_registry.{active|decommission|cutover_prepare|cutover_commit}.v1`)
2. cutover を **two-phase commit (2PC) pattern** で実装 (Phase α prepare → Phase β commit、cross-host atomic 不可前提)
3. **fleet-wide cutover lease** (`cutover_lease.signed.json`、root-signed) で cross-host 排他保証 + concurrent cutover_id reject
4. **signer-host ownership binding** (`active_registry_fleet.signed.json` に `host_id -> allowed_marker_signer_fingerprints` + role + allowed_marker_kinds 必須化)
5. **commit-time cryptographic finalization signature** (CommitMarker に `commit_finalization_preimage_hash` + required host 全員の `commit_confirmed_at` 署名、backdate 攻撃防御)
6. **immutable archived snapshot** (`cutover_lease_snapshots/<cutover_id>.signed.json` + `fleet_membership_snapshots/<generation>.signed.json` で long-term durability)
7. **3 layer defense-in-depth write gate** (L1 FastAPI dependency / L2 ARQ worker dequeue + startup / L3 SQLAlchemy before_commit listener)
8. **current fleet policy check** (active-registry write gate / startup gate で host status / valid_to / signer fingerprint / role を必須 verify、compromise 即時失効経路)
9. **server-owned clock monotonicity attestation** (3 mode: Linux CLOCK_MONOTONIC + NTP / TPM clock signed attestation / Remote trusted time service)
10. cutover 2-party-control (caller-supplied actor 物理削除 → principal-token-fd 経路、separation of duties enforcement at issue + redeem 両方)
11. ReasonCode 拡張 (active-registry 系 + cutover 系 + commit 系合計約 36 件、§9.3-§9.10 集約で 60 件正本化)

## 3. 関連 Sprint / 前提

- SP-012_p0_acceptance must_ship 2 件 (本 ADR と co-accepted、Batch A 着手前に proposed → accepted 昇格必須)
- T09 host migration drill (Mac → VPS、RTO ≤ 4h、P0 Exit hard gate) は本 ADR 実装後に実施
- ADR-00021 §11.2 first line (freeze.signed) との関係: 本 ADR は 1st line を **置換** ではなく **補完** (freeze.signed は cutover phase 前の source 一時停止用途で残存、cutover phase で decommission.signed に遷移)

## 4. 前提 / 制約

- 本 ADR は SP-012 と **co-accepted** が原則: SP-012 accepted 化条件 = ADR-00028 + ADR-00029 両方 status=accepted (または同一 PR で co-accepted)
- ADR-00028 が rejected / superseded に戻る場合、SP-012 must_ship 2 件は **blocked** へ戻し、Batch A 着手禁止
- 不変条件 #1 (AI 出力直結禁止) / #2 (deny-by-default) / #4 (Provider Compliance Matrix v2 機械判定) / #5 (SecretBroker atomic claim + actor-run-fingerprint binding) / #13 (server-owned boundary) を遵守
- `rules/server-owned-boundary.md` §1 caller-supplied 経路禁止 invariant を遵守 (CutoverApprovalClaim / CommitApprovalClaim から `executor_actor_id` / `approver_actor_id` を物理削除、principal-token-fd 経路に置換)
- `rules/cross-source-enum-integrity.md` §1 cross-source enum 5+ source 整合 (ReasonCode 60 件、6 source で正本化: DB CHECK / ORM / Python Literal / Pydantic / pytest EXPECTED set / CI check)

## 5. 選択肢

### 選択肢 A: marker chain + 2PC + fleet-wide lease + signer-host ownership + commit-time signature + L1+L2+L3 gate + clock monotonicity (採用)

- ActiveMarker / DecommissionMarker / PrepareMarker / CommitMarker の 4 marker schema を別 signature domain で分離
- cutover は two-phase commit (prepare → commit) + commit certificate (commit_finalization_preimage_hash + 全 host commit_confirmed_at signature)
- fleet-wide cutover lease で concurrent cutover_id reject + required_host_ids 全件 prepare lock 必須
- signer-host ownership binding で allowlist + ownership 二重 check
- immutable archived snapshot で long-term durability (lease 自然失効 / fleet generation 更新が既存 active state を invalidate しない)
- L1 (FastAPI) + L2 (ARQ worker) + L3 (SQLAlchemy before_commit) 三層 defense-in-depth で全 write surface 停止
- current fleet policy check で compromise 対応の即時失効経路 (host_removed / status revoked / role demoted / signer revoked / valid_to expired)
- server-owned clock monotonicity 3 mode (Linux CLOCK_MONOTONIC / TPM / Remote trusted time) で backdate 攻撃防御

利点:
- ADR-00021 §11.2 first line を完全に補完、host migration の cryptographic active state proof 確立
- compromise 対応の即時失効と long-term durability を両立 (archived snapshot + reconciliation gate 分離)
- 全 write surface (API + worker + DB commit) で fail-closed
- clock rollback 攻撃にも耐性 (monotonic_clock_attestation independent source)

欠点:
- 実装規模 (25 file / +約 4,400 行 / 142 fixture / 60 ReasonCode / 7 ApprovalClaim variants)
- operator runbook §13-§21 で運用手順を厳密に規定する必要

### 選択肢 B: freeze.signed 単体 + procedural cutover (現状維持、却下)

- 既存 ADR-00021 §11.2 first line のみ
- cutover は operator manual SOP に依存

却下理由:
- cross-host split-brain race を暗号学的に防げない (procedural check のみ)
- ARQ worker / background job が freeze 後も write 続行可能
- compromise 対応で host を revoke しても、既存 CommitMarker を retroactively invalidate できない
- T09 host migration drill (RTO ≤ 4h) を hard gate として確立できない

### 選択肢 C: 中央 coordination service (consul / etcd 等、却下)

- 外部 coordination service で active-registry を管理

却下理由:
- P0 scope (個人専用、Tailscale 閉域、単一 VPS、Docker Compose) では外部 service 不要
- consul/etcd の運用コストが P0 budget を超過
- 外部 dependency 増加で deny-by-default invariant 違反リスク
- 選択肢 A の cryptographic proof は外部 service より operational simplicity 高

## 6. 採用案 (選択肢 A)

`.claude/plans/sp012-split-brain-keyring.md` §3.B + §9.3-§9.10 で詳細仕様確定済。実装 file 一覧:

- `scripts/taskhub_active_registry.py` (新規、marker chain write/read/verify + allocate_next_epoch atomic + trusted_signers allowlist verify + 2PC prepare/commit + lease binding)
- `scripts/taskhub_active_registry_reconciliation_gate.py` (新規、current fleet drift 検出 + benign vs security-relevant 判定 + successor transition required)
- `scripts/taskhub_admin.py` (拡張、cutover --target-host subcommand + freeze + active-registry list + post-stop chain hash reverify)
- `scripts/taskhub_destructive_lock.py` (拡張、cutover subcommand を destructive_lock 対象に追加)
- `scripts/taskhub_remote_status.py` (拡張、remote host marker 取得 + same-epoch dual active reject)
- `scripts/taskhub_approval_cli.py` (拡張、`--cutover-*` issue args、caller-supplied actor 削除、principal-token-fd 経路、issuance_journal append)
- `scripts/taskhub_signed_approval.py` (拡張、authorization_verify vs audit_verify predicate 分離、issuance journal cross-check)
- `scripts/taskhub_entrypoint_active_registry_check.sh` (新規、Docker entrypoint pre-check)
- `backend/app/api/dependencies/active_registry_gate.py` (新規、L1 FastAPI dependency)
- `backend/app/main.py` (拡張、L1 dependency wiring)
- `backend/app/workers/active_registry_worker_gate.py` (新規、L2 worker startup + job dequeue + graceful cancel)
- `backend/app/workers/main.py` (拡張、L2 gate integration)
- `backend/app/db/active_registry_mutation_gate.py` (新規、L3 SQLAlchemy before_commit listener)
- `docker-compose.yml` (拡張、entrypoint script integration)
- `tests/scripts/test_taskhub_active_registry.py` (新規、約 60+ fixture)
- `tests/scripts/test_taskhub_admin.py` (拡張、cutover fixture)
- `docs/deploy/operator-runbook.md` (拡張、§14 split-brain check SOP + §18 approval artifact mode A/B + §20 commit-time invariant + §21 clock attestation 3 mode + §22 cutover SOP)

runtime artifact (production deploy 時に生成):
- `<config_dir>/active_registry/<host_id>/active.signed` / `decommission.signed` / `freeze.signed`
- `<config_dir>/active_registry/cutover_lease.signed.json` (current view) + `cutover_lease_snapshots/<cutover_id>.signed.json` (immutable archive)
- `<config_dir>/active_registry/fleet_membership_snapshots/<generation>.signed.json`
- `<config_dir>/active_registry/cutover_prepare/<cutover_id>.signed` (.pending → .signed atomic rename)
- `<config_dir>/active_registry/cutover_commit/<cutover_id>.signed` (commit certificate)
- `<config_dir>/active_registry/approval_archive/<approval_id>.signed.json` (immutable approval artifact)
- `<config_dir>/active_registry/migration_epoch.journal.signed.jsonl` (signed append-only counter journal)
- `<config_dir>/active_registry/reboot_attestation.signed.jsonl` (Mode A 専用、reboot detection)
- `/etc/taskhub/keyring_state.head.signed` (config_dir 外 monotonic state anchor、ADR-00029 と共有)

## 7. 却下案

選択肢 B (freeze.signed 単体): cryptographic active state proof 不在、T09 host migration drill hard gate 不可能。

選択肢 C (中央 coordination service): P0 scope 外、外部 dependency 増加で deny-by-default invariant 違反リスク。

## 8. リスク

- **実装規模リスク**: 25 file / +約 4,400 行 / 142 fixture と大規模、Batch A-D 分割実装で各 Batch 独立検証可能だが、commit gate (Batch 1 で本文 §3-§9 ↔ §9.3-§9.10 sync) を遵守しないと drift で品質崩壊
- **operator runbook 依存**: clock attestation 3 mode の選択 + reboot detection 運用 + cutover SOP は operator が正しく従う前提、operator 教育が必須
- **TPM / remote trusted time 未配備時の fallback**: Mode A (Linux CLOCK_MONOTONIC) は host reboot で reset、reboot detection + attestation で補強するが、Mode B/C 推奨は本格 fleet 運用時に明示
- **L3 SQLAlchemy before_commit listener performance impact**: 各 commit ごとに active marker + fleet policy verify、benchmark で latency impact を測定 + cache 戦略を確定 (Batch A 完了後に measure)

## 9. rollback 手順

1. ADR-00028 status を `proposed` → `superseded` に move、reason = "<specific failure scenario>"
2. SP-012 must_ship 2 件 status を `blocked` へ戻し、Batch A 着手禁止 (本 ADR が accepted の前提条件)
3. 既存配備 (もしあれば) は `.claude/plans/sp012-split-brain-keyring.md` §9 rollback SOP に従う:
   - bootstrap 未実行環境: `approval-verify-key.pub` single key に戻る
   - bootstrap 成功後環境: §9.5 F-001 canonical 適用 (single-key fallback 復活禁止、`approval_keyring_initialized.signed` marker + tombstone denylist 維持、compromise 含む rollback は append-only 新 manifest generation で rotate/revoke)
4. T09 host migration drill は ADR-00021 §11.2 first line (freeze.signed 単体) で実施、ただし RTO ≤ 4h 達成は **降格条件下** で再評価
5. 24h 以内に retro Pack 起票 + 後継 ADR 草案 (proposed) を作成 (`rules/sprint-pack-adr-gate.md` §10 break-glass 例外運用準拠)

## 10. 実装対象ファイル

§6 採用案で列挙。詳細実装契約は `.claude/plans/sp012-split-brain-keyring.md` §3.B / §9.3 / §9.4 / §9.5 / §9.6 / §9.7 / §9.8 / §9.10 を canonical 正本として参照。

## 11. テスト指針

`tests/scripts/test_taskhub_active_registry.py` で約 60+ fixture (§3.D.2 + §9.3-§9.10 negative test list 集約):

- split-brain detection (same epoch source+target active)
- two-step transition violation (source active → decommission 経由なし)
- signature verify fail (wrong domain / unknown signer / chain hash mismatch)
- trusted signer allowlist (cross-domain reject / fingerprint expired / freshness rule)
- migration_epoch atomic (concurrent allocation unique / counter tamper / replay reject / lower epoch reject / signed journal hash mismatch)
- cutover 2-party-control (issue/redeem both reject decider == approver、caller-supplied actor_id reject、principal-token-fd 経路)
- 2PC prepare/commit (pending rename without certificate reject / commit certificate field tampering / partial host confirmation reject / cross-host prepare lock partial reject)
- fleet-wide lease (concurrent cutover_id reject / lease expired / required_host_ids hash mismatch)
- signer-host ownership (allowlist + ownership exact match / source signer cannot activate target / role demotion reject)
- commit-time cryptographic proof (backdated committed_at reject / confirmation signature must cover committed_at / committed_at >= max host_commit_confirmed_at + ε)
- immutable archived snapshot (committed marker remains valid after lease expiry / committed marker remains valid after new cutover lease replaces current path / fleet membership rotation requires signed successor)
- current fleet policy check (compromise revocation / valid_to expired / role demoted / signer revoked / status retired)
- L1 (API write reject) + L2 (worker job + startup reject) + L3 (DB commit reject)
- clock monotonicity (wall-clock rollback within/exceeding ε / monotonic_clock independent regression / reboot without/with attestation)
- approval artifact verify (missing artifact / random claim hash / mismatched host_id / mismatched cutover_id / revoked signing key / immutable archive overwrite)
- config_dir snapshot rollback (full rollback / generation lower than head / tombstone truncate / lower epoch / legacy fallback blocked when head.initialized=true)

T09 host migration drill (Mac → VPS、RTO ≤ 4h) を P0 Exit hard gate として実施、本 ADR 実装後 drill PASS が P0 Exit 条件。
