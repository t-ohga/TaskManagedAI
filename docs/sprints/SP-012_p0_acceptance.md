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

R29 統合計画書 (`../設計検討/修正まとめ統合計画.md`) §6 U-01 採用に伴い、本 Sprint の must_ship を **host migration acceptance (P0 core)** と **Research-to-PR representative flow (gated add)** の 2 表に物理分離する。target_days / dependencies の再見積もりは `## Review` 欄で残す。

### 表 1: P0 core acceptance (host migration + core gold flow、AC-HARD-04 拡張 + AC-HARD/KPI 全件、R29 R2 F-R2-001 反映で BL-0140b を core 側に明示)

| 項目 | must_ship | defer_if_over_budget |
|---|---|---|
| `taskhub restore/migrate/age-rotate/verify` 本実装 | ○ | - |
| host migration drill (Mac → VPS) | ○ | - |
| **BL-0140b (Ticket-to-PR smoke gold flow、旧 BL-0140 後継、P0 core acceptance flow、master plan §37 12 BL count に含む)** | ○ | - |
| AC-HARD 7 全件 PASS | ○ | - |
| AC-KPI 5 未達 1 個以下 | ○ | 1 個未達は SP-022 で改善 Sprint 検討 |
| private staging CI/E2E 完成 | ○ | partial で SP-022 完成可 |
| 運用手順書 (host-migration.md) | ○ | - |
| 自動 host migration scheduling | × | SP-022 |
| 半年に 1 回 drill 自動化 | × | SP-022 |

### 表 2: Research-to-PR representative acceptance proof (gated add、R29 §6 U-01 採用、R2 F-R2-001 反映)

host migration acceptance + BL-0140b core smoke (表 1) とは **物理的に分離**された別表。**`gated_acceptance` 列の意味 (R2 P2R1 F-P2R1-008 反映)**: 表 2 は runtime core gate を直接 block しないが、**BL-0149 (P0 Acceptance report と Sprint Review) / P0 Exit report sign-off は、表 2 の各 gated row が PASS、または `structured_defer(owner, impact, resume_condition, blocked_by, verification, target_hash)` の 6 fields を持たない限り BLOCK** する。これにより gated row が「未記録 / 自然文 defer」のまま P0 Exit する経路を防ぐ。BL-0140 三分割 (R29 §3.5.* D-002) のうち BL-0140a (Research-to-PR、gated add、master plan §37 で gated add 明示) のみが本表 entry、BL-0140b (Ticket-to-PR smoke、P0 core) は表 1 へ移行済。

| 項目 | gated_acceptance | proof_status / 補足 |
|---|---|---|
| BL-0140a (Research-to-PR gold flow): Research → Decision → Generated Ticket → Plan → **Approval (`approval_requests` row + `decided_by_actor_id` = human actor 必須、self-approval deny + `artifact_hash` / `diff_hash` / `policy_version` 4 整合 binding、F-P2R1-009 反映)** → Runner → **Draft PR mock (approval 完了後のみ作成、approval 前作成 deny)** → Eval → Audit 通し | ○ (gated add) | P0 core exit を直接 block しない、Research-to-PR acceptance proof として記録、Sprint Review で target_days/max_days 再判断、**human approval proof + artifact hash chain (research_id / source_set_hash / generated_ticket_hash / plan_artifact_hash / approval_id / pr_artifact_hash) が完全に追跡可能 (F-P2R1-010 反映)** |
| AC-KPI-04 (`citation_coverage ≥ 0.9` AND `citation_source_count >= 1` AND `denominator_nonzero` の 3 条件すべて PASS、F-P2R1-011 反映: 0/0 を 1.0 PASS 経路を防ぐ) を Research-to-PR 経路で verify | ○ (gated add) | core verification は host migration の AC-HARD-04、本項は Research-to-PR 経路特化の proof |
| `agent_runs.parent_run_id` cross-project negative (BL-0029b) を Research-to-PR sub-run でも PASS | ○ (gated add) | core negative test は AC-HARD-03 (表 1 内包)、本項は Research sub-run 経路特化 |
| `research_tasks` cross-project negative (BL-0029c) | ○ (gated add) | tenant/project boundary を Research-to-PR 経路で verify |
| `secret_capability_tokens.agent_run_id` FK (BL-0151b) を Research sub-run でも binding verify | ○ (gated add) | SecretBroker atomic claim を Research sub-run 経路で verify |
| Research → generated Ticket lineage の audit event trail (research_decision_recorded / research_ticket_generated 等の event 化は ADR-00003 update 経由、本 Sprint では acceptance spec として記録、event_type 31 → 33+ 追加は P0.1 へ defer)。ただし **event_type 追加を defer しても、P0 で `research_id` / `source_set_hash` / `generated_ticket_hash` / `plan_artifact_hash` / `approval_id` / `pr_artifact_hash` を acceptance artifact に保存し、hash chain 欠落は gated row FAIL** とする (F-P2R1-010 反映) | partial (acceptance spec のみ、ただし hash chain 必須) | event_type schema 追加は **P0.1 の新規番号 Pack で別途起票 (SP-018 既存 Hermes memory sprint と衝突するため不可、F-P2R1-014 反映)** |
| Research-to-PR representative flow target_days 再見積もり (host migration 5 days + Research-to-PR 2 days = 7 days、max 9 days への引き上げ可能性) | ○ (Review pending、Sprint Review で最終判断) | `## Review` § Pending entries で記録 |

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

# backup / restore / host migration drill (PH-F-003 fix: tm 不使用、taskhub + curl ベース)
$ taskhub backup --output /tmp/sp012-backup.tar.age   # Mac (selected host) で
$ taskhub migrate --target t-ohga-vps --via tailscale # Mac → VPS one-shot
$ ssh vps 'taskhub status'                             # VPS で service up + health verify
$ curl -s https://taskhub.t-ohga-vps.tail-xxxxx.ts.net/api/v1/healthz   # smoke (tm 不使用、PH-F-003)
$ taskhub verify --integrity --multi-agent             # restore 後 integrity verify
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

### Pending entries (本 Sprint 着手前に R29 QL-A で記録、Sprint Review で最終判断)

- **target_days 再見積もり**: Research-to-PR representative flow を gated add したため、host migration (5 days) + Research-to-PR (推定 2 days) = **7 days**、`max_days` は現状 7 のままだと余裕がない。Sprint Review で `max_days=9` への引き上げ可否を最終判断する (target_days/max_days 改定は ADR Gate Criteria #2/#3 該当しない frontmatter 修正のため Sprint Pack DoD 内で完結可能)。
- **dependencies 再計算 (canonical source: `docs/実装計画/P0_バックログ.md:219`、direct depends_on)**: BL-0140a の **direct depends_on は 21 BL** (9 件は旧 BL-0140 から inherit、12 件は Research-to-PR 用に新規追加: BL-0113〜BL-0119 (7 件) + BL-0126 + BL-0148 + BL-0029b + BL-0029c + BL-0151b (5 件) = 12 件)。SP-012 表 2 は P0_バックログ.md を **canonical source** として参照し、本 Pack 内に dependency 列を複製しない (drift 防止、R29 R2 F-R2-002 反映)。
- **transitive closure 必須 (F-P2R1-012 反映)**: direct 21 BL の **transitive closure** を Sprint 12 着手前に artifact 生成し (`docs/設計検討/QL-A_BL-0140a_transitive_closure.md` 等)、closure 内の未完了 BL を `blocked_by` として記録する。例: BL-0148 (AC-KPI 5 件集計) の transitive deps は BL-0124 / BL-0128 / BL-0134 / BL-0164 / BL-0165 を含むため、これらが未完了の場合 BL-0140a も blocked_by に含む。closure artifact が無い state で BL-0140a 着手は禁止。
- **AC-KPI-04 verify path**: Research-to-PR 経路で `citation_coverage ≥ 0.9` を verify するため、AC-KPI-04 fixture (Sprint 11 整備分) が Research source の citation を carry できることを Sprint 12 着手前に Sprint 11 ## Review で確認する。

### gated_acceptance_rows artifact schema (R2 P2R2 F-P2R2-003 反映、acceptance spec)

表 2 の gated row を **機械可読 artifact** で記録するための schema (実装は Sprint 12 着手時、本 Pack は spec のみ):

**artifact path**: `docs/p0-exit/gated_acceptance_rows.json` (P0 Exit 着手時に生成、append-only か署名付き)

**schema (各 row)**:
```json
{
  "row_id": "BL-0140a-research-to-pr | AC-KPI-04-research-coverage | ...",
  "status": "PASS | STRUCTURED_DEFER | FAIL",
  "structured_defer": {
    "owner": "<actor_id>",
    "impact": "<short description>",
    "resume_condition": "<measurable condition>",
    "blocked_by": ["<BL-NNNN or external dep>"],
    "verification": "<test path or artifact ref>",
    "target_hash": "<sha256 of target artifact>"
  },
  "target_hash": "<sha256 of acceptance target>",
  "evidence_artifact_hash": "<sha256 of evidence artifact>",
  "verified_by": "<actor_id, human or service>",
  "verified_at": "<ISO-8601 timestamp>"
}
```

**BL-0149 / P0 Exit sign-off invariant**:
- 表 2 全 row が `status: PASS` または schema-valid `STRUCTURED_DEFER` (6 fields すべて埋まる) であること
- 自然文 "deferred" や 6 fields の一部欠落は `FAIL` 扱い、P0 Exit BLOCK
- artifact 生成 / hash 計算 / verify はすべて **server-owned `AcceptanceArtifactBuilder`** が canonical JSON で実行 (F-P2R2-005 反映、caller 入力不可)

### Research-to-PR hash chain (R2 P2R2 F-P2R2-004 反映、Decision artifact 含む)

BL-0140a Research-to-PR flow の hash chain は **7 hash + 1 approval_id** で構成、Decision artifact 自体も approval target に含む:

| 位置 | hash | 計算対象 | server-owned 検証 |
|---|---|---|---|
| 1 | `research_id` | research_task primary key | 既存 (SP-010) |
| 2 | `source_set_hash` | Research source artifact の canonical JSON sha256 | server 再計算、AcceptanceArtifactBuilder |
| 3 | **`decision_artifact_hash`** (新規、F-P2R2-004 反映) | **Decision artifact** (Research source からどう判断したか) の canonical JSON sha256 | server 再計算、**Decision-level approval target に必ず含む** (差し替え時は approval invalidated) |
| 4 | `generated_ticket_hash` | Decision から生成された Ticket artifact の sha256 | server 再計算 |
| 5 | `plan_artifact_hash` | Plan artifact の sha256 | server 再計算、Plan-level approval target に含む |
| 6 | `approval_id` | `approval_requests` row PK (decided_by_actor_id = human) | DB FK |
| 7 | `pr_artifact_hash` | Draft PR diff の sha256 | server 再計算 |

**Decision approval policy (F-P2R2-004 反映)**:
- 選択肢 A (採用): Plan approval target に `decision_artifact_hash` + `source_set_hash` を必須 binding、Decision 差し替え時は **approval invalidated** (artifact_hash mismatch で server-owned validation が deny)
- 選択肢 B (却下): Decision-level の独立 approval gate (二段 approval、UX 過剰)

### Server-owned AcceptanceArtifactBuilder (R2 P2R2 F-P2R2-005 反映)

P0 Exit artifact / hash chain の生成・検証責務:

- **入力**: persisted Research / Decision / Ticket / Plan / Approval / PR artifact (DB row + artifact store ref)
- **出力**: `docs/p0-exit/gated_acceptance_rows.json` + `acceptance_hash_chain.json` (server 再計算結果)
- **invariant**:
  1. caller (UI / CLI / Sprint Review acceptor) は hash 値を直接渡せない (API endpoint Pydantic schema / service layer / ORM の 3 layer で server-owned-boundary §2 物理削除)
  2. acceptance artifact は append-only (BL-0149 sign-off 時に append、改ざん時は detected)
  3. または **detached signature** (source host signing key で artifact 署名、SP-012 Phase G PGA-F-002 と同 pattern)
  4. BL-0149 sign-off は AcceptanceArtifactBuilder の出力を **再 verify** (target_hash / evidence_artifact_hash と persisted artifact の actual hash 一致)
- **実装 Sprint**: Sprint 12 着手時 (本 Pack は spec のみ)

### QL-D Quality Loop product artifact acceptance spec (R29 §5 QL-D 反映、2026-05-15 doc-only、F-P2R2 系列とは独立追記)

R29 修正まとめ統合計画 §5 QL-D で **open finding zero gate + harness incident zero gate + defer structured state** を SP-012 acceptance spec として記録する future implementation gate を以下に追記する。**code / test / schema / migration 変更を一切行わない**、本 Pack の acceptance spec として cross-reference するのみ。

QL-D scope の core spec は別 design doc `docs/設計検討/quality_loop_product_artifact.md` (本 QL-D run で新規起票) + DD-03 §14 + DD-07 §14 を正本とする。本 SP-012 update は P0 Exit Master Plan の acceptance contract として上記 spec を必須化する記述のみ。

#### open finding zero gate (A-12 反映、SP-012 Sprint Exit invariant、F-PR13-001 + F-PR13-002 P1 adopt 反映)

Sprint Pack 単位の **`conformance` artifact 発行** (= Sprint Exit) は **non-blocking future gate** として P0.1 SP-023 候補 accepted 後の Sprint Exit から mandatory 化する記述として明示:

1. **最新 review chain (= `revision` linked to current artifact の `review` / `rereview`) の `verdict='clean'`** (findings: [] または `P3` / `info` のみで explicit accept、QL-D `docs/設計検討/quality_loop_product_artifact.md §5/§6` の delegate) **OR** 全 finding に `adoption_decision` (adopt / reject / defer) が記録済 (R1 = `verdict='needs_revision'` でも、R2 / R3 で全 finding が adopt/reject/defer 判定済なら gate 通過 OK、historical R1/R2 は append-only history として保持、gate 対象外、F-PR13-002 P1 adopt)
2. `defer_entry` の `verification` 列が記入済 (`P3` / `info` finding を `defer` する場合、§14.2 defer structured state schema 準拠)
3. `must_ship_items[]` 全件達成 (`must_ship_pass_count == must_ship_total`)
4. `hard_gates_pass[]` 全件 PASS (AC-HARD-01〜07 全件、本 Pack §受け入れ条件と整合)
5. `quality_kpis_pass[]` 未達 1 個以下 (AC-KPI-01〜05、§Hard Gates 7 / Quality KPIs 5 準拠)

これらいずれか 1 つでも未達なら `conformance.final_verdict='partial'` または `'blocked'`、Sprint Exit を block。**現状自由文 (例: `## Review §Pending entries`) の defer entry を structured state へ migration するのは P0.1 SP-023 候補 accepted 後** (本 run では doc-only spec のみ)。

**⚠️ P0 期間中 (SP-023 未実装、本 PR commit 時点) の SP-012 P0 Exit acceptance の運用** (F-PR13-001 P1 + F-PR13-R2-003 P2 adopt 反映):

- 上記 5 step は **structured `conformance` artifact** + **`quality_loop_harness_incident` table** を前提とするが、両者の table / API / event schema は SP-023 候補 (P0.1) で実装される。SP-012 で P0 Exit を declare する Sprint 12 着手時点で structured artifact は未実装
- そのため、**P0 期間中の SP-012 P0 Exit acceptance は本 §QL-D update の structured gate (`conformance` artifact + `quality_loop_harness_incident` 両方) を mandatory prerequisite にしない**。代わりに以下で acceptance を判定:
  - **Hard Gates 7** (AC-HARD-01〜07) の自動 pytest / runner PASS — 本 Pack `## 受け入れ条件` の core
  - **Quality KPIs 5** (AC-KPI-01〜05) の metric 計測 PASS (未達 1 個以下)
  - **既存 Sprint Pack `## Review` 自由文 evidence** (各 Sprint Exit で `changed` / `verified` / `deferred` / `risks` を記載済の Sprint Pack 群)
  - **`## 残リスク` の defer entry** (自由文表記、structured 化は P0.1 SP-023 candidate accepted 後)
  - **harness incident の自由文記録** (Sprint Pack `## Review §Pending entries` 等で 自由文 incident 記録、structured `quality_loop_harness_incident` 表は P0.1 SP-023 候補で実装)
- structured `conformance` artifact + structured `quality_loop_harness_incident` 発行を **P0.1 SP-023 candidate accepted 後の Sprint Exit から mandatory 化**。本 QL-D update は future implementation gate として記録するのみ、P0 acceptance gate を **block しない** (F-PR13-R2-003 P2 adopt: harness_incident gate も同様に non-blocking future gate として扱う)

これにより、SP-023 が未実装のまま P0 acceptance が impossibility paradox に陥る経路 (`conformance` artifact + `quality_loop_harness_incident` 両者) を doc レベルで防ぐ。

#### harness incident zero gate (A-12 反映)

Sprint Pack の Sprint Exit 時点で `quality_loop_harness_incident` artifact のうち **`resolved_at` が null** の row が残っているなら、P0 Exit を block:

- harness incident の `recovery_action` が `manual_resolution` でまだ解決していない → `conformance.final_verdict='blocked'`
- harness incident が `abort` で解決済 → SP-012 `## 残リスク` に `defer_entry` で migration して `resolved_at` 記入

これにより、open harness incident (Codex 失敗 / Claude tool error / CI flake 等) を放置したまま P0 Exit 宣言する経路を fail-closed で防ぐ。

#### `defer` structured state schema (A-15 反映、本 Pack `## 残リスク` の structured 化 future gate)

本 Pack の `## 残リスク` / `## 次スプリント候補` / `## Review §Pending entries` で使われる「`defer`」「Pending」表記を **structured state** として表現する future implementation gate (詳細 schema は `docs/設計検討/quality_loop_product_artifact.md §4`):

```yaml
defer_entry:
  defer_id: string (e.g., "DEFER-SP-012-001")
  owner: actor_id (defer 判定責任 actor、`actors.id` UUID、human or agent)
  impact: text (P0 Exit / acceptance / AC-HARD/KPI への影響)
  resume_condition: text (defer 解除条件、accepted ADR / 次 Sprint Pack accepted / dependency resolved 等)
  blocked_by: [string] (defer 解除 blocker 一覧、ADR id / Sprint Pack id / external dependency)
  verification: text (defer 解除時の verification 手順)
  target_artifact_hash: string (F-PR13-R3-002 P2 adopt: defer 対象 artifact の sha256、本 Pack §Server-owned AcceptanceArtifactBuilder の `decision_artifact_hash` + `source_set_hash` binding pattern と整合、defer resume 時に target artifact が変化していないことを再 verify、変化時は defer invalidated)
  target_source_set_hash: string nullable (defer 対象が複数 source artifact を持つ場合の集合 hash、Decision approval policy F-P2R2-004 と整合)
  created_at: timestamp
  resumed_at: timestamp nullable
```

**現状の自由文 entry migration**: 本 Pack `## Review §Pending entries` で記載されている各 Pending row を `defer_id` 付き structured state へ migration するのは P0.1 SP-023 候補 accepted 後の別 run。本 QL-D run では doc-only spec のみ記録。

#### clean evidence verification 6 step (A-12 反映、SP-012 §検証手順 拡張)

`conformance` artifact 発行時の verification 手順 (`docs/設計検討/quality_loop_product_artifact.md §6.3` 準拠):

1. **最新 review chain (= `revision` linked to current artifact の `review` / `rereview`) の `verdict='clean'`** を確認 **OR** 全 finding に `adoption_decision` (adopt / reject / defer) が記録済を確認 (F-PR13-002 P1 adopt 反映)
2. 全 `defer_entry.resume_condition` + `verification` が記入済を確認
3. 全 `must_ship_items[]` の `## 受け入れ条件` PASS を確認 (本 Pack §受け入れ条件と一致)
4. 全 `hard_gates_pass[]` の pytest / 各 hard gate runner PASS を確認
5. 全 `quality_kpis_pass[]` の metric 計測結果が閾値内 (未達 1 個以下)
6. 全 `quality_loop_harness_incident.resolved_at` が NOT NULL or `defer_entry` 移送済 (**P0 期間中 (SP-023 未実装) は本 step を non-blocking** として扱う、自由文 incident 記録 OR `defer_entry` 移送済 OR structured `quality_loop_harness_incident.resolved_at` NOT NULL のいずれかで satisfy、F-PR13-R3-001 P2 adopt 反映)

これら 6 step 全 PASS で `conformance.final_verdict='pass'`、P0 Exit 達成。**P0 期間中 (SP-023 未実装) は step 1 (review chain) + step 6 (harness incident) を non-blocking gate として扱い、structured artifact が未実装でも P0 acceptance を block しない** (F-PR13-001 + F-PR13-R2-003 + F-PR13-R3-001 P2 adopt 反映、上記 「⚠️ P0 期間中の運用」 と整合)。

#### QL-D 関連 ADR / Sprint Pack (本 update で trigger)

- **SP-023 候補 (P0.1、新規 Pack 起票必須)**: Quality Loop product artifact schema (`quality_loop_artifacts` / `quality_loop_reviews` / `quality_loop_defer_entries` table、event_type 拡張、API endpoint) 実装
- **ADR-00026 候補 (P0.1、proposed 新規起票必須)**: Quality Loop schema design (ADR Gate Criteria #2/#3 trigger)
- DD-03 §14 + DD-07 §14 (本 QL-D run で同時追加)
- `docs/設計検討/quality_loop_product_artifact.md` (本 QL-D run で新規起票、core spec)
- ADR-00014 (Multi-Agent Orchestration、accepted): Phase C `review_artifacts` table と Quality Loop `review` artifact の物理分離 (本 §14.4 of DD-03)

#### QL-D 関連 rules (本 update で trigger)

- `.claude/rules/agentrun-state-machine.md §1` (AgentRun.status 16 状態固定、本 Pack §QL-D update の物理分離 invariant の根拠)
- `.claude/rules/sprint-pack-adr-gate.md §131-142` (Sprint Pack Review DoD、本 §open finding zero gate の根拠)
- `.claude/rules/plan-review.md §122-128` (verification checklist、本 §clean evidence verification と整合)
- `.claude/rules/cross-source-enum-integrity.md §1` (5+ source 整合、Quality Loop artifact_kind 6 種は P0.1 SP-023 候補で別途実装)
