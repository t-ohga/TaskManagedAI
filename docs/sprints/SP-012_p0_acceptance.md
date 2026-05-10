---
id: "SP-012_p0_acceptance"
type: "heavy"
status: "draft"
sprint_no: 12
created_at: "2026-05-10"
updated_at: "2026-05-10"
target_days: 5
max_days: 7
adr_refs: []
planned_adr_refs:
  - "[ADR-00021](../adr/00021_host_portable_deployment.md) # SP-012 で accepted (Criteria #2/#6/#7/#8)"
related_sprints:
  - "SP-001_project_foundation"
  - "SP-011_eval_harness"
  - "SP-022_framework_intake_hardening"
risks:
  - "host migration drill RTO ≤ 4h 達成性"
  - "AC-HARD 7 全件 multi-agent 文脈で再 verify (P0.1 着手前提)"
  - "private staging CI/E2E 完成性"
---

最終更新: 2026-05-10

## 目的

P0 Acceptance を達成する。具体的には (1) Hard Gates 7 全件 PASS、(2) Quality KPIs 5 のうち未達 1 個以下、(3) backup/restore drill (RPO ≤ 24h, RTO ≤ 4h)、(4) **host migration drill (Mac → VPS、ADR-00021)** を含む host-portable 完了 verify、(5) private staging CI/E2E 完成、(6) `taskhub restore` + `migrate` + `age-rotate` + `verify` 本実装.

## 背景

- SP-001 〜 SP-011 で P0 backend / frontend / 基盤が完成、本 Sprint で **P0 Exit gate** を機械検証
- ADR-00021 (Host-Portable Deployment) を SP-001 で proposed 起票済、本 Sprint で accepted 化 + restore / migrate 完成
- P0 Sealed CI guard は本 Sprint 完了で解除可 (P0.1 着手準備)

## 対象外

- multi-agent 機能本体 (P0.1 SP-013+)
- memory backend (P1 SP-018)
- 自動 host migration scheduling (SP-022)

## 設計判断

- **host migration drill は "Mac → VPS" を default case** (運用フェーズに合わせ)
- **AC-HARD-04 拡張**: 既存 backup/restore drill に加え、host migration drill (RTO ≤ 4h) を P0 必須 verify に追加
- **age key 安全運搬手順は手動 SOP** (ADR-00021 §5 厳守)
- **private staging CI/E2E は Tailscale 内専用** (Funnel 不使用、ADR-00007 invariant 維持)

## 実装チケット

- SP012-T01: `taskhub restore` 本実装 (age 復号 + pg_restore + Redis import + artifacts 配置 + alembic check + healthcheck + 失敗時 rollback)
- SP012-T02: `taskhub migrate --target <hostname>` (backup → Tailscale file share → 対象 host で restore one-shot)
- SP012-T03: `taskhub age-rotate` (age key rotation + SOPS re-encrypt + 旧 key archived 保管)
- SP012-T04: `taskhub verify --integrity` (PostgreSQL row count + artifacts checksum + Redis key count + alembic head + age fingerprint match)
- SP012-T05: host migration drill 自動化 (Mac → VPS の end-to-end test)
- SP012-T06: AC-HARD-01〜07 fixture を全件 PASS verify (Sprint 11 で skeleton 完成済)
- SP012-T07: AC-KPI-01〜05 計測値が閾値以内であること verify
- SP012-T08: private staging CI/E2E 完成 (Tailscale GitHub Action + frontend E2E full suite)
- SP012-T09: `docs/deploy/host-migration.md` 運用手順書整備
- SP012-T10: ADR-00021 を accepted 化 + ADR-00007 update を accepted

## タスク一覧

- [ ] SP012-T01〜T10 を順次実装
- [ ] AC-HARD 7 全件 PASS、AC-KPI 5 のうち未達 1 個以下を最終 verify
- [ ] host migration drill (Mac → VPS) 実機実施 + RTO 計測 (≤ 4h verify)
- [ ] backup/restore + host migration の rollback path 実機 verify
- [ ] private staging CI で全 contract test + E2E full suite PASS

## must_ship / defer_if_over_budget 対応表

| 項目 | must_ship | defer_if_over_budget |
|---|---|---|
| `taskhub restore/migrate/age-rotate/verify` 本実装 | ○ | - |
| host migration drill (Mac → VPS) | ○ | - |
| AC-HARD 7 全件 PASS | ○ | - |
| AC-KPI 5 未達 1 個以下 | ○ | 1 個未達は SP-022 で改善 Sprint 検討 |
| private staging CI/E2E 完成 | ○ | partial で SP-022 完成可 |
| 運用手順書 (host-migration.md) | ○ | - |
| 自動 host migration scheduling | × | SP-022 |
| 半年に 1 回 drill 自動化 | × | SP-022 |

## 受け入れ条件

- AC-HARD-01 (policy_block_recall): 危険 action が 100% deny される fixture PASS
- AC-HARD-02 (secret_canary_no_leak): fake API key が provider/artifact/runner に漏れない fixture PASS
- AC-HARD-03 (tenant_isolation_negative_pass): DB / app_role / 複合 FK の越境 negative test PASS
- **AC-HARD-04 (backup_restore_rpo_rto)**: RPO ≤ 24h、RTO ≤ 4h 維持 + **host migration drill (Mac → VPS) RTO ≤ 4h 達成**
- AC-HARD-05 (forbidden_path_block): `.env`, `.git/config`, secrets, migrations 等を runner で reject
- AC-HARD-06 (dangerous_command_block): dangerous command を runner で reject
- AC-HARD-07 (prompt_injection_resist): untrusted_content の権限昇格 reject
- AC-KPI-01〜05: 全 KPI 計測値が閾値内 (acceptance_pass_rate ≥ 0.6 / time_to_merge median ≤ 2h / approval_wait_ms median ≤ 4h / citation_coverage ≥ 0.9 / cost_per_completed_task ≤ $0.5)
- `taskhub migrate --target t-ohga-vps` で Mac → VPS の data 移行 + 整合性 verify 完了
- 全機械の `tm` CLI を新 host URL に切替後、smoke PASS

## 検証手順

```bash
# AC-HARD verify (全 fixture)
uv run pytest eval/security/policy_block/ eval/security/secret_canary/ eval/security/tenant_isolation/ \
              eval/security/forbidden_path/ eval/security/dangerous_command/ eval/security/prompt_injection/ -q

# AC-KPI verify
uv run pytest tests/metrics/test_acceptance_pass_rate.py tests/metrics/test_time_to_merge.py \
              tests/metrics/test_approval_wait_ms.py tests/metrics/test_citation_coverage.py \
              tests/metrics/test_cost_per_completed_task.py -q

# backup / restore / host migration drill
$ taskhub backup --output /tmp/sp012-backup.tar.age   # Mac で
$ taskhub migrate --target t-ohga-vps --via tailscale # Mac → VPS one-shot
$ ssh vps 'taskhub status'                             # VPS で service up verify
$ tm --backend https://taskhub.t-ohga-vps.tail-xxxxx.ts.net ticket list   # smoke
$ uv run pytest tests/deploy/test_host_migration_drill.py -q

# private staging CI/E2E
gh workflow run private-staging-e2e
gh run watch
```

## レビュー観点

- AC-HARD 7 fixture の dataset version + private holdout 整合 (Sprint 11 から継続)
- host migration drill の RTO 計測が複数回再現可能 (運用 SOP として SP-022 で半年に 1 回 schedule)
- age key 運搬手順の bypass 経路がない (git/cloud 経由禁止が CI で enforce)
- restore 失敗時の rollback path が `data/_pre-restore-<ts>/` で機能
- private staging CI が Tailscale GitHub Action で外部公開なし

## 残リスク

- Mac の docker performance が VPS と差異あり (Apple Silicon vs x86)、KPI 計測値が host で divergence する可能性 → SP-022 で host 別 baseline 設定検討
- ADR-00021 §5 age key 手動運搬の human error リスク (誤 channel で送信) → SP-022 で `taskhub migrate` 自動化時の age key 統合 (Tailscale tailfs encrypt 等) 検討
- AC-HARD-04 RTO ≤ 4h 超過時の改善 Sprint (defer 可、SP-022 で対応)

## 次スプリント候補

- P0.1 開始 (TASKHUB_P0_1_OPENED=1 + sealed guard 解除 + SP-013 着手)
- SP-022 (framework intake hardening、host migration 自動化)

## 関連 ADR

- ADR-00021 (Host-Portable Deployment + Data Migration、本 Sprint で accepted)
- ADR-00007 update (host 中立 invariant、本 Sprint で同期 accepted)
- AC-HARD-04 (backup/restore drill 拡張)

## Phase G adversarial strengthening (2026-05-10、14 finding 全件 adopt)

ADR-00021 §14 (Phase G adversarial Strengthening Catalog) を本 Sprint に反映:

### 追加 must_ship

- **age key 安全運搬 (PGA-F-001)**: secret manager (1Password / Bitwarden) default-required、scp/direct write は `--break-glass-approval-id` 必須。`taskhub status --age-safety` で FileVault / cloud-sync exclusion / permission 600 verify
- **backup detached signature + signer allowlist (PGA-F-002)**: source host signing key で manifest / checksums / dump hash / Merkle root / freeze_signature を署名、target restore は signer fingerprint allowlist + migration_epoch freshness 必須 verify
- **`taskhub thaw` 2-party-control + active-registry (PGA-F-003)**: target active.signed marker 確認 + decommission marker 必要、source/target 同時 active reject contract test
- **image digest pinning + version matrix (PGA-F-004)**: postgres / redis を `@sha256:<digest>` で pin、compose lock file 自動生成、meta.json に server_version_num + extension version 記録、target restore で exact/compatible matrix verify
- **DB catalog 正本 fingerprint (PGA-F-005)**: `taskhub verify --integrity` に schema-only hash + alembic revision file hash + constraint/index/trigger/function checksum + seed exact rows 追加
- **migration state machine + signed journal (PGA-F-007)**: 8-phase state machine (prepare/freeze/backup/transfer/restore/verify/cutover/thaw)、source/target 双方 signed journal、network partition fixture 必須
- **artifact write atomicity (PGA-F-006)**: temp file + fsync + atomic rename + DB commit ordering、Redis appendfsync policy 選定、Mac runtime preflight (sleep/powernap settings) hard fail
- **uid/gid remapping (PGA-F-008)**: backup meta に service user uid/gid + path mode、restore 時 remap、artifact / postgres / redis dir permission 実 check
- **`taskhub verify --network-invariant` (PGA-F-014)**: docker compose config merged + docker ps + ss -lntp + tailscale serve status JSON + public IP probe + tailnet grants 一括 check
- **Mac selected host hardening baseline (PGA-F-012)**: FileVault / OS patch / screen lock / non-admin daily user / Docker socket access / Tailscale device posture / device revoke drill / age rotation drill / runbook 全件 acceptance に追加
- **`docs/deploy/mac-hardening-baseline.md`** 新規作成 (Mac selected host で必須実施項目 + incident response runbook)

### 追加実装ファイル

- `cli/taskhub/commands/{thaw,active-registry,re-sanitize}.py`
- `cli/taskhub/signing/{detached_signer,signer_allowlist}.py`
- `cli/taskhub/journal/{state_machine,phase_journal}.py`
- `tests/deploy/test_age_key_safety_required.py`
- `tests/deploy/test_backup_detached_signature.py`
- `tests/deploy/test_thaw_2_party_control.py`
- `tests/deploy/test_image_digest_pinning.py`
- `tests/deploy/test_db_catalog_fingerprint.py`
- `tests/deploy/test_migration_state_machine_resume.py`
- `tests/deploy/test_artifact_write_atomicity.py`
- `tests/deploy/test_uid_gid_remap.py`
- `tests/deploy/test_network_invariant_runtime.py`
- `tests/deploy/test_mac_hardening_baseline.py`
- `docs/deploy/mac-hardening-baseline.md`
- `docs/deploy/incident-runbook.md`

### 受け入れ条件追加

- `tests/deploy/test_*` 全 PASS
- Mac selected host で `docs/deploy/mac-hardening-baseline.md` 全項目 verify (新規 hardening test で機械検査)
- migration state machine の 8-phase + network partition fixture (Tailscale 強制切断 + resume / reject 全 case) PASS
- backup signer fingerprint allowlist が空でない (default で source host 自身が allowlist)、悪意 backup (異 signer) reject

## Review

(SP-012 完了時に追記)
