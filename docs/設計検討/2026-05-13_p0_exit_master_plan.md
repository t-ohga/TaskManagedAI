---
id: PLAN-MASTER-P0-EXIT-2026-05-13
title: "P0 Exit Master Plan (Sprint 10 / 11 / 11.5 / 12 + Phase 5 統合計画)"
status: draft
date: 2026-05-13
authors:
  - "claude (sprint7-9 audit owner)"
related_documents:
  - "../要件定義/01_P0要求定義.md"
  - "../実装計画/00_ロードマップ.md"
  - "../実装計画/P0_バックログ.md"
  - "../sprints/SP-007_runner_sandbox.md"
  - "../sprints/SP-008_github_app_repoproxy.md"
  - "../sprints/SP-009_p0_ui_pack.md"
  - "../sprints/SP-012_p0_acceptance.md"
  - "../adr/00011_github_app_permission_matrix.md"
  - "../adr/00012_hook_trust_boundary.md"
  - "../adr/00021_host_portable_deployment.md"
  - "./2026-05-13_sprint7-9_audit_complete_handoff.md"
  - "../../.claude/CLAUDE.md"
---

# P0 Exit Master Plan (Sprint 10 / 11 / 11.5 / 12 + Phase 5 統合計画)

## 0. Executive Summary

本 master plan は Sprint 9 完了状態 (2026-05-13、commit `211db46` push 済) から **P0 Exit (Hard Gates 7 全件 PASS + Quality KPIs 5 未達 1 個以下 + backup/restore RPO≤24h/RTO≤4h + host migration drill PASS)** までの完遂計画を 1 doc に統合する。

CLAUDE.md §6.5.0 「**急がなくていい。それぞれ品質重視で codex をしっかり使い完璧に**」を遵守し、各 Sprint で Codex multi-round review (R1 → R2 → ... → `verdict=clean`) を必須とする。speed 優先で round 短絡しない。

scope: Sprint 10 (Research / Evidence) → Sprint 11 (Eval Harness + Sprint 7-9 carry-over) → Sprint 11.5 (Observability + a11y carry-over) → Sprint 12 (P0 Acceptance + Phase G strengthening) + Phase 5 (Hook Trust Boundary、並走可) の 5 fence。

remaining BL 概算 (正本 BL ID = PLAN-01 docs/実装計画/P0_バックログ.md 同期、Codex R1 F-R1-001/002/003 adopt):
- **Sprint 10**: 10 BL (`BL-0029c + BL-0113〜0121`)
- **Sprint 11**: 12 本来 (`BL-0122〜0130 + BL-0158/0159/0163`) + 15 carry-over = **27 BL**
- **Sprint 11.5**: 11 本来 (`BL-0131〜0139 + BL-0156/0159b`) + 3 carry-over = **14 BL**
- **Sprint 12**: 12 本来 (`BL-0140b + BL-0141〜0149 + BL-0164/0166` = 1 + 9 + 2 = **12 BL count 維持**) + R29 §6 U-01 で **gated add `BL-0140a` (Research-to-PR representative flow、Sprint 12 表 2 で acceptance、target_days 再見積もり対象)** ※ 旧 BL-0140 は R29 §3.5.* D-002 で三分割: BL-0140a=Research-to-PR (gated add、SP-012 表 2) / BL-0140b=Ticket-to-PR smoke (旧 BL-0140 後継、SP-012 表 1 維持)、BL-0140c=alerting rules は SP-0115 へ移送 + Phase G strengthening 既存 SP-012 反映済 = **12 BL + 1 gated add + 11 PGA file 群**
- **Phase 5**: 3 BL (`BL-0082/0083/0084`) + ADR-00012 accepted = **4 task**
- **累計**: 本来 BL = 10 + 27 + 14 + 12 = **63 BL** + Phase G strengthening 11 + Phase 5 4 task = **78 work item** (Codex R2 F-R2-003 adopt: 82 表記削除)

Codex round budget 累計 (Codex R1 F-R1-006/007 adopt: BL 数 × 平均 round で式と整合): **195-266 rounds**
- Sprint 10 = 10 BL × 3-4 round = 30-40
- Sprint 11 = 27 BL (carry-over 15 × 2-3 + 本来 12 × 3-4 = 30-45 + 36-48、overlap 削減で **60-80**)
- Sprint 11.5 = 14 BL × 2-3 round = 28-42
- Sprint 12 = 23 work item × 3-4 round = 69-92
- Phase 5 = 4 task × 2-3 round = 8-12

## 1. 現状 (2026-05-13、Sprint 9 audit clean 完遂後)

### 1.1 完了 Sprint

| Sprint | status | BL 完了 | Codex audit rounds | 累計 findings |
|---|---|---|---:|---:|
| Sprint 0 (Bootstrap) | done | — | — | — |
| Sprint 1 (Foundation) | done | — | — | — |
| Sprint 2 (Core Data Model) | done | — | — | — |
| Sprint 3 (Policy / Approval) | done | — | — | — |
| Sprint 4 (Agent Runtime) | done | — | — | — |
| Sprint 4.5 (Tool Registry) | done | — | — | — |
| Sprint 5 (Provider Adapter) | done | — | — | — |
| Sprint 5.5 (Output Validator + Input Trust Layer) | done | — | — | — |
| Sprint 6 (CLI Artifact) | done | — | — | — |
| Sprint 7 (Runner Sandbox) | **done_with_phase5_defer** | 11/14 | R0-R7 (8 round) | 15 distinct + 1 Phase 5 defer |
| Sprint 8 (GitHub Draft PR Flow) | **partial_skeleton** | 4/9 | R1-R3 (3 round) | 10 (7 adopt + 3 既存 backlog) |
| Sprint 9 (P0 UI Pack) | **skeleton_pending_backend** | 5/10 + 3 client draft | R1-R3 (3 round) | 6 (3 adopt + 3 既存 backlog) |
| **累計** | | **20/33 ≈ 60% (Sprint 7-9)** | **13 round** | **32 findings** |

### 1.2 P0 Hard Gates / Quality KPIs trace (Codex R1 F-R1-008/009/010 adopt: source → registry → final の 3 段 trace)

#### Hard Gates 7 trace (PLAN-01:281-287 §Hard Gate fixture trace 同期、Codex R2 F-R2-004 adopt: source / enhancement 列分離)

| AC ID | Gate | source BL (PLAN-01 §Hard Gate fixture trace) | enhancement / prerequisite (Sprint 11/11.5) | registry / loader (Sprint 11) | final 判定 (Sprint 12) |
|---|---|---|---|---|---|
| AC-HARD-01 | `policy_block_recall` | BL-0041 | — | BL-0127 | BL-0141 |
| AC-HARD-02 | `secret_canary_no_leak` | BL-0153, BL-0160 | BL-0089 (Sprint 4 canary) + BL-0138 (Sprint 11.5 rotation drill) + BL-0158/0159 (Sprint 11 fixture loader 接続) | BL-0127 | BL-0142 |
| AC-HARD-03 | `tenant_isolation_negative_pass` | BL-0029, BL-0029b, BL-0029c, BL-0158 | — (BL-0158 は source 兼 registry 接続) | BL-0127 | BL-0143 |
| AC-HARD-04 | `backup_restore_rpo_rto` | BL-0137, BL-0159, BL-0159b | — | BL-0127 | BL-0144 (restore drill 実施) |
| AC-HARD-05 | `forbidden_path_block` | BL-0073, BL-0087, BL-0102 | BL-0080a (Sprint 11 carry-over fixture 拡張 private_holdout + adversarial_new) | BL-0127 | BL-0145 |
| AC-HARD-06 | `dangerous_command_block` | BL-0074, BL-0083, BL-0091 | BL-0081a (Sprint 11 carry-over fixture 拡張) | BL-0127 | BL-0146 |
| AC-HARD-07 | `prompt_injection_resist` | BL-0078, BL-0157 | — | BL-0127 | BL-0147 |

#### Quality KPIs 5 trace (PLAN-01 §KPI ↔ source 表 と同期)

| AC ID | KPI | source BL | aggregation / final BL |
|---|---|---|---|
| AC-KPI-01 | `acceptance_pass_rate` | BL-0031 (Sprint 2) + BL-0124 (Sprint 11 decomposition) + BL-0125 (Sprint 11 coding/review) | BL-0148 (Sprint 12 集計) |
| AC-KPI-02 | `time_to_merge` | BL-0098 (Sprint 8 Draft PR、carry-over BL-0102) + BL-0164 (Sprint 12 mock merge timestamp) | BL-0148 |
| AC-KPI-03 | `approval_wait_ms` | BL-0037 (Sprint 3) + BL-0040 (Sprint 3 notification) + BL-0165 (Sprint 3 metric source) | BL-0134 (Sprint 11.5 dashboard) + BL-0148 |
| AC-KPI-04 | `citation_coverage` | BL-0119 (Sprint 10 source) + BL-0126 (Sprint 11 aggregator) | BL-0148 |
| AC-KPI-05 | `cost_per_completed_task` | BL-0053 (Sprint 4) + BL-0069 (Sprint 5) + BL-0128 (Sprint 11 aggregator) | BL-0148 |

#### AC-HARD-04 Sprint 責務分担 (Codex R1 F-R1-010 adopt)

| Sprint | 責務 | BL |
|---|---|---|
| Sprint 11 | fixture contract skeleton を Eval Harness に登録 | BL-0159 |
| Sprint 11.5 | WAL archiving + PITR backup で fixture activation | BL-0159b (BL-0137 WAL prep の上に build) |
| Sprint 12 | restore drill 実施 + host migration drill (Mac → VPS) RTO≤4h | BL-0144 (PGA-F-001〜014 strengthening 経由) |

### 1.3 ADR 状態

| ADR | status | accepted 化 path |
|---|---|---|
| ADR-00011 (GitHub App Permission Matrix) | proposed | **Sprint 11.5 末** で `acceptance_blocked_by` 8 件全件解消後 (Sprint 11 末は 7/8 unblock review のみ、frontmatter `proposed` 維持。Codex R1/R2/R3 adopt) |
| ADR-00012 (Hook Trust Boundary) | proposed | Phase 5 で wrapper + manifest + dotfiles 管理完成後 |
| ADR-00021 (Host-Portable Deployment) | proposed | Sprint 12 で host migration drill PASS 後 |
| ADR-00007 (External Exposure) update | proposed (host 中立 invariant) | Sprint 12 で ADR-00021 同期 accepted |

### 1.4 不足 Sprint Pack

`docs/sprints/` を確認した結果、以下が未起票:

- **SP-010_research_evidence.md** (Sprint 10 Research / Evidence) → 本 plan で SP-010 起票プラン提示
- **SP-011_eval_harness.md** (Sprint 11 Eval Harness + carry-over) → 本 plan で SP-011 起票プラン提示
- **SP-011-5_operational_hardening.md** (Sprint 11.5 Observability + carry-over) → 本 plan で SP-011-5 起票プラン提示
- **SP-012_p0_acceptance.md**: 既存 (Phase G strengthening 反映済、ADR-00021 §14 14 finding 全件 adopt)
- **Phase 5 plan**: 本 plan で `docs/設計検討/2026-05-13_phase5_hook_trust_boundary_plan.md` 起票プラン提示

## 2. P0 Exit Criteria 再確認

PRD-00 / PRD-01 / 00_ロードマップ.md §P0 Exit Criteria に基づく:

```text
P0 完了 = (Hard Gates 7 全件達成) AND (Quality KPI 未達数 <= 1)
```

- **Hard Gates 7**: 1 件でも未達なら release blocker
- **Quality KPIs 5**: 2 個以上未達なら改善 Sprint 追加 (SP-022 candidate)
- **AC-HARD-04 拡張** (ADR-00021): 既存 backup/restore drill に加え host migration drill (RTO≤4h) を P0 必須 verify に追加

## 3. 完遂までの Sprint 構成

### 3.1 Sprint 10 — Research / Evidence Foundation

**target_days**: 4.3 / **max_days**: 7 (00_ロードマップ.md 既存値)

**Sprint Pack status**: 未起票 → 本 plan で SP-010 draft 化を Task #56 で扱う。

**must_ship**:

- `ResearchTask` / `Claim` / `EvidenceSource` / `EvidenceItem` table + migration
- `canonical_url` / `retrieved_at` / `published_at` / `content_hash` / `relation` / `locator` / `relevance_score` / `freshness_score` / `provenance_json` columns
- `evidence_set_hash` の computation (NFC UTF-8 + JCS canonical JSON + claim_id/source_id 昇順 + URL 正規化 + PROV bundle hash)
- Research-to-Ticket artifact contract (server-owned artifact_hash binding)
- AC-KPI-04 `citation_coverage` source ticket (BL-0119 + BL-0126)
- ContextSnapshot.evidence_set_hash 結線

**BL 概要** (P0_バックログ.md §Sprint 10 から):

- BL-0114: ResearchTask DDL + tenant_id + project FK
- BL-0115: Claim DDL + provenance_json + freshness_score
- BL-0116: EvidenceSource DDL + canonical_url + content_hash
- BL-0117: EvidenceItem DDL + locator + relevance_score
- BL-0118: PROV validation + provenance_json schema
- BL-0119: evidence_set_hash computation + ContextSnapshot 結線
- BL-0120: Research-to-Ticket artifact + adapter
- BL-0121: 越境 negative test + cross-project negative
- BL-0029c: `research_tasks` cross-project 制約 (Sprint 2 carry-over)

**Codex multi-round budget**: 20-30 round (PostgreSQL DDL + computation + adapter で平均 4-6 round / BL × 9 BL ≈ 36-54 round、ただし schema 系は state machine ほど round 増えず実績 4-6 round で clean)

**検証 command**:

```bash
uv run alembic upgrade head
uv run pytest tests/research_evidence/ tests/contracts/test_evidence_set_hash.py -q
uv run pytest tests/security/test_research_cross_project_negative.py -q
uv run mypy backend
uv run ruff check backend tests
```

**ADR Gate**:

- ADR-00002 (DB schema) 該当 — Research/Evidence schema 追加で update
- ADR-00003 (API contract) 該当 — Research-to-Ticket adapter で update

**Rollback**:

- migration revision を 1 件 down で revert
- ContextSnapshot.evidence_set_hash は null 許容にして既存 AgentRun を保護

---

### 3.2 Sprint 11 — Eval Harness + Sprint 7-9 carry-over (Largest scope)

**target_days**: 5.6 / **max_days**: 7 (00_ロードマップ.md 既存値)、ただし carry-over 15+ BL 追加分で **実 effort は max 10-12 days** 想定。Sprint Pack は heavy 形式で起票し、batch 分割で 6-8 batch を想定。

**Sprint Pack status**: 未起票 → 本 plan で SP-011 draft 化。

**must_ship (本来 scope)**:

- 6 領域 Eval (decomposition / coding / review / research / security / cost)
- `public_regression` / `private_holdout` / `adversarial_new` 3 split + dataset version + Anti-Gaming Rules
- Hard Gates 7 件すべての fixture registry / loader 統合
- private gold task 30-50 件
- Quality KPI 5 件の計測 endpoint

**must_ship (Sprint 7-9 carry-over)**:

Sprint 7 carry-over (3 BL):

- **BL-0079a**: runner audit payload に `actor_id` / `trace_id` / `correlation_id` / `gateway_kind` / `artifact_refs` 追加 + AgentRunEvent integration + `runner_cancelled` / `runner_cleanup_completed` event_type 追加
- **BL-0080a**: AC-HARD-05 fixture private_holdout + adversarial_new 充実 (symlink / `..` traversal / URL-encoded / Unicode ZWJ variants 各 10+ 件)
- **BL-0081a**: AC-HARD-06 fixture private_holdout + adversarial_new 充実 (shell injection / encoding / Docker escape / fork bomb / resource abuse variants 各 10+ 件)

Sprint 8 carry-over (7 BL):

- **BL-0094**: GitHub App 登録 + private key SOPS encrypt (admin 手動)
- **BL-0095**: SecretBroker `repo.push` / `repo.pr_open` allowed_operations 追加 + capability_token issue flow 結線
- **BL-0097**: GitHubAppAdapter httpx wrapper (broker-mediated only)
- **BL-0100**: AgentRunEvent `repo_pr_opened` actual emission
- **BL-0102**: AC-KPI-02 `time_to_merge` 計測 endpoint
- **BL-0096a**: RepoProxy 4 整合 binding server-side 再計算 refactor (`create_draft_pr(approval_id, agent_run_id)` signature)
- **BL-0101a**: Webhook HMAC SecretBroker-mediated service layer + Redis SETNX replay + rotation status 検証

Sprint 9 carry-over (5 BL):

- **BL-0103a**: `GET /api/v1/tickets` list + detail route + tenant boundary + repository contract test
- **BL-0106a**: `GET /api/v1/agent_runs` list + detail route
- **BL-0107a**: `GET /api/v1/audit_events` route + cursor pagination + tenant filter
- **BL-0107b**: `RedactedAuditPayloadSchema` / `RedactedAgentRunEventPayloadSchema` (frontend AC-HARD-02 enforcement) + DOM secret scan test
- **BL-EnumDrift**: TicketStatus / AgentRunStatus / AgentRunEventType / AuditEventType / PayloadDataClass の cross-source drift contract test (backend Literal / DB CHECK / frontend Zod の exact set 比較)

**BL 概要 (本来 scope の Sprint 11、12 BL)**:

- BL-0122 / BL-0123: Eval Harness core (dataset version + fixture loader + Anti-Gaming Rules)
- BL-0124 / BL-0125: acceptance_pass_rate aggregator + decomposition fixture
- BL-0126: citation_coverage aggregator
- BL-0127: review eval (Sprint 5.5 Output Validator 連動)
- BL-0128: cost_per_completed_task aggregator (BL-0053 / BL-0069 source 統合)
- BL-0129: provider bake-off fixture + provider contract test 統合
- BL-0130: backup/restore RPO≤24h fixture (AC-HARD-04 source) — SP-012 と分担
- BL-0131: private gold task 30-50 件への拡張
- BL-0132: Hard Gates 7 件 fixture registry + loader 統合 endpoint
- BL-0133: Anti-Gaming Rules CI gate (fixture creation commit と policy / runner module 修正 commit が分離されているかの check)

**累計 BL**: 本来 12 + carry-over 15 = **27 BL**

**Codex multi-round budget**: **60-80 rounds** (Codex R1 F-R1-006/007 + R2 F-R2-003 adopt、§6 と整合: carry-over 15 × 2-3 = 30-45 + 本来 12 × 3-4 = 36-48 = 66-93、R1 共通 review overlap 削減で 60-80)

**検証 command**:

```bash
# carry-over verify
uv run pytest tests/secrets/test_repo_operations.py tests/repoproxy/test_github_app_adapter.py \
              tests/agent_runtime/test_repo_pr_opened_event.py tests/contracts/test_kpi_time_to_merge.py \
              tests/repoproxy/test_4integrity_negative.py tests/repoproxy/test_webhook_service_layer.py \
              tests/api/test_tickets_route.py tests/api/test_agent_runs_list.py \
              tests/api/test_audit_events_route.py tests/contracts/test_ac_hard_02_frontend_redaction.py \
              tests/contracts/test_frontend_backend_enum_drift.py \
              tests/agent_runtime/test_runner_audit_event_emission.py \
              tests/security/test_ac_hard_05_private_holdout.py tests/security/test_ac_hard_06_private_holdout.py -q

# eval harness (Sprint 本来 scope)
uv run pytest eval/ -q
uv run pytest tests/metrics/ -q

# ADR-00011 acceptance gate
uv run python -m backend.app.services.repoproxy.permission_matrix --check \
              --current-permissions-json $(gh api /app/installations/<id>/access_tokens | jq .permissions)
```

**ADR Gate**:

- **ADR-00011 acceptance 7/8 unblock review**: 本 Sprint で 7 件 (BL-0094/0095/0097/0100/0102 + BL-0096a/0101a) unblock を verify、frontmatter `proposed` 維持。**accepted 昇格は Sprint 11.5 末** (残 1 件 BL-Permission-CLI 完成で 8/8 達成後、Codex R1/R2/R3 adopt)
- ADR-00003 (API contract) update — backend route 追加で
- ADR-00009 (action_class) — `repo.push` / `repo.pr_open` enforcement で
- ADR-00021 — host migration drill source ticket (BL-0159 backup/restore) が SP-012 に渡される

**Sprint Exit 条件**:

- 27 BL すべて Codex multi-round で `verdict=clean`
- SP-007 status `done_with_phase5_defer` 維持 (Phase 5 待ち、本 Sprint で SP-007 を変更しない)
- SP-008 status `partial_skeleton` → `done` 昇格 (5 carry-over BL + 2 refactor BL 完了後)
- SP-009 status `skeleton_pending_backend` → `done` 昇格 (5 carry-over BL 完了後)
- ADR-00011 7/8 unblock review 完了、frontmatter `proposed` 維持 (Sprint 11.5 BL-Permission-CLI 完成後に accepted、Codex R3 F-R3-001 adopt)

**Rollback**:

- carry-over BL は SP-008/009 frontmatter で `partial_skeleton` / `skeleton_pending_backend` 維持で revert 可
- ADR-00011 accepted 化失敗時は `proposed` 維持 + Sprint 12 へ defer

---

### 3.3 Sprint 11.5 — Operational Hardening + a11y / responsive carry-over

**target_days**: 5.4 / **max_days**: 7

**Sprint Pack status**: 未起票 → 本 plan で SP-011-5 draft 化。

**must_ship (本来 scope)**:

- OpenTelemetry / Prometheus / Loki / Grafana dashboard
- alerting (approval / run_failed / budget_exceeded)
- private staging Tailscale GitHub Action + WAL archiving / PITR prep
- secret rotation drill (rotation 状態遷移 `pending -> active -> deprecated -> revoked`)
- audit export (raw secret 除外 invariant の export-time enforcement)
- `payload_data_class` / `allowed_data_class` dimension on Prometheus metrics

**must_ship (Sprint 9 a11y / responsive carry-over)**:

- **BL-0109a**: responsive mobile-first design (Tailwind grid + 768/1024/1440px Playwright viewport test)
- **BL-0110a**: a11y axe-core integration test (WCAG 2.1 AA 違反 0)
- **BL-Permission-CLI**: GitHub API current permissions fetch + CI workflow integration (ADR-00011 acceptance carry-over)

**BL 概要 (本来 scope)**:

- BL-0136: OTel collector + auto-instrument FastAPI / arq
- BL-0137: Prometheus metrics endpoint + scrape target
- BL-0138: Loki promtail config + log shipping
- BL-0139: Grafana dashboard (Hard Gates + KPIs)
- BL-0140c: alerting rules (approval pending > 4h / budget exceeded / run_failed spike、**alert は signal-only invariant: R2 P2R1 F-P2R1-016 反映で `approval_requests` の `decision` / `status` を alert 発火で変更せず、approval state 変更 / run resume / re-approval は human approval row 必須**、auto-approve / auto-retry 経路で human-only approval decider invariant を bypass しない) ※ R29 §3.5.* D-002 で BL-0140 三重 collision (Research-to-PR / Ticket-to-PR / alerting rules) 解消 → 別 ID 割当、`docs/実装計画/P0_バックログ.md` も同期更新済 (BL-0140a/0140b は SP-012、BL-0140c は本 Sprint 11.5 = SP-0115)
- BL-0141: private staging Tailscale GitHub Action
- BL-0142: WAL archiving + PITR drill (AC-HARD-04 source)
- BL-0143: secret rotation drill + canary preflight
- BL-0144: audit export (raw secret 除外 verify) + `secret_capability_revoked` event
- BL-0145: payload_data_class dimension on metrics

**累計 BL**: 本来 11 (`BL-0131〜0139 + BL-0156/0159b`) + carry-over 3 (`BL-0109a/0110a/BL-Permission-CLI`) = **14 BL** (Codex R2 F-R2-002 adopt)

**Codex multi-round budget**: **20-30 rounds** (Observability 系は schema / DDL ほど厳格 multi-round 不要、3-4 round / BL 平均)

**検証 command**:

```bash
# observability
docker compose --profile observability up -d
curl -s http://localhost:9090/metrics | grep -E 'agent_runs_total|payload_data_class'
curl -s http://localhost:3900/api/datasources | jq

# a11y / responsive
cd frontend && pnpm exec playwright test --grep '@a11y|@responsive'
cd frontend && pnpm exec axe http://localhost:3900/admin/tickets --rules wcag2aa,wcag21aa

# secret rotation drill
uv run python -m backend.scripts.secret_rotation_drill --dry-run
uv run pytest tests/secrets/test_rotation_state_transition.py -q
```

**ADR Gate**:

- ADR-00006 (Secrets) update — rotation drill 完成で
- ADR-00007 (External Exposure) — private staging Tailscale GitHub Action 確認

**Sprint Exit 条件**:

- 14 BL すべて Codex multi-round で clean
- Grafana dashboard で AC-HARD 7 + AC-KPI 5 すべて可視化
- secret rotation drill が dry-run + real-rotation 双方で成功
- a11y axe-core WCAG 2.1 AA 違反 0 を Playwright で enforce

**Rollback**:

- Observability stack は別 docker-compose profile (`--profile observability`) で起動、profile off で revert 可
- secret rotation 失敗時は旧 secret_ref を `status='active'` に戻す手順

---

### 3.4 Sprint 12 — P0 Acceptance Test + Phase G Strengthening

**target_days**: 5.5 / **max_days**: 7 (既存 SP-012 frontmatter)

**Sprint Pack status**: 既存 (Phase G strengthening 反映済、14 finding 全件 adopt)

**must_ship (P0 Acceptance 本体)**:

- AC-HARD-01〜07 fixture 全件 PASS verify (Sprint 11 で skeleton 完成済を private_holdout / adversarial_new 含めて enforcement)
- AC-KPI-01〜05 計測値が閾値以内 (未達 1 個以下)
- backup/restore drill (RPO≤24h, RTO≤4h)
- **host migration drill (Mac → VPS、ADR-00021)**
- private staging CI/E2E 完成
- `taskhub restore` / `migrate` / `age-rotate` / `verify` 本実装

**Phase G strengthening 14 finding ↔ 11 file 群対応表 (Codex R1 F-R1-012 adopt)**:

| Phase G finding | 対応実装 file (SP-012 既存 Pack §145-163) | must_ship 分類 |
|---|---|---|
| PGA-F-001 (age key 安全運搬) | `tests/deploy/test_age_key_safety_required.py` + `taskhub status --age-safety` | P0 must_ship |
| PGA-F-002 (backup detached signature) | `tests/deploy/test_backup_detached_signature.py` + `cli/taskhub/signing/{detached_signer,signer_allowlist}.py` | P0 must_ship |
| PGA-F-003 (`taskhub thaw` 2-party-control) | `tests/deploy/test_thaw_2_party_control.py` + `cli/taskhub/commands/thaw.py` + `active-registry.py` + `re-sanitize.py` | P0 must_ship |
| PGA-F-004 (image digest pinning) | `tests/deploy/test_image_digest_pinning.py` + `compose-lock.yml` + meta.json schema | P0 must_ship |
| PGA-F-005 (DB catalog 正本 fingerprint) | `tests/deploy/test_db_catalog_fingerprint.py` + `taskhub verify --integrity` extension | P0 must_ship |
| PGA-F-006 (artifact write atomicity) | `tests/deploy/test_artifact_write_atomicity.py` + temp file + fsync + atomic rename impl | P0 must_ship |
| PGA-F-007 (migration state machine 8-phase) | `tests/deploy/test_migration_state_machine_resume.py` + `cli/taskhub/journal/{state_machine,phase_journal}.py` | P0 must_ship |
| PGA-F-008 (uid/gid remapping) | `tests/deploy/test_uid_gid_remap.py` + backup meta + restore 時 remap impl | P0 must_ship |
| PGA-F-012 (Mac selected host hardening) | `tests/deploy/test_mac_hardening_baseline.py` + `docs/deploy/mac-hardening-baseline.md` + `docs/deploy/incident-runbook.md` | P0 must_ship |
| PGA-F-014 (`taskhub verify --network-invariant`) | `tests/deploy/test_network_invariant_runtime.py` + `taskhub verify --network-invariant` impl | P0 must_ship |
| PGA-F-009/010/011/013 (4 finding) | 既存 SP012-T01〜T10 に統合 (個別 file なし、本体 CLI / runbook で対応) | P0 must_ship (本体に統合済) |

**累計**: 14 finding = 10 個別 deploy test + 4 既存 task 統合。11 file 群との一致: `cli/taskhub/commands/{thaw,active-registry,re-sanitize}.py` (3) + `cli/taskhub/signing/` (2) + `cli/taskhub/journal/` (2) + `tests/deploy/test_*` (10) + `docs/deploy/mac-hardening-baseline.md` (1) + `docs/deploy/incident-runbook.md` (1) ≈ 11+ work item (SP-012 Pack で詳細確定済)

**must_ship (Phase G strengthening、ADR-00021 §14、14 finding adopt)**:

- PGA-F-001: age key 安全運搬 (secret manager default-required + `taskhub status --age-safety`)
- PGA-F-002: backup detached signature + signer allowlist (signer fingerprint allowlist + migration_epoch freshness verify)
- PGA-F-003: `taskhub thaw` 2-party-control + active-registry
- PGA-F-004: image digest pinning (`postgres:@sha256:<digest>` 等) + version matrix
- PGA-F-005: DB catalog 正本 fingerprint (`taskhub verify --integrity` extension)
- PGA-F-006: artifact write atomicity (temp file + fsync + atomic rename)
- PGA-F-007: migration state machine 8-phase (prepare/freeze/backup/transfer/restore/verify/cutover/thaw) + signed journal
- PGA-F-008: uid/gid remapping (backup meta + restore 時 remap)
- PGA-F-012: Mac selected host hardening baseline (FileVault / non-admin daily user / Docker socket access / device posture)
- PGA-F-014: `taskhub verify --network-invariant` (docker compose + ss + tailscale serve + public IP probe)

**BL 概要 (SP-012 から)**:

- SP012-T01: `taskhub restore` 本実装
- SP012-T02: `taskhub migrate --target <hostname>`
- SP012-T03: `taskhub age-rotate`
- SP012-T04: `taskhub verify --integrity`
- SP012-T05: host migration drill 自動化
- SP012-T06: AC-HARD-01〜07 全件 PASS verify
- SP012-T07: AC-KPI-01〜05 verify
- SP012-T08: private staging CI/E2E 完成
- SP012-T09: `docs/deploy/host-migration.md` 運用手順書
- SP012-T10: ADR-00021 / ADR-00007 accepted 化
- + 11 件 Phase G strengthening (cli/taskhub/commands/{thaw,active-registry,re-sanitize}.py + signing + journal + 8 deploy test)

**累計 BL**: 12 + Phase G 11 = **23 BL**

**Codex multi-round budget**: **30-40 rounds** (CLI / migration state machine / signing は schema レベルで厳格、4-5 round / BL 平均)

**検証 command**:

```bash
# AC-HARD verify (全 fixture)
uv run pytest eval/security/policy_block/ eval/security/secret_canary/ eval/security/tenant_isolation/ \
              eval/security/forbidden_path/ eval/security/dangerous_command/ eval/security/prompt_injection/ -q

# AC-KPI verify
uv run pytest tests/metrics/ -q

# host migration drill
taskhub backup --output /tmp/sp012-backup.tar.age
taskhub migrate --target t-ohga-vps --via tailscale
ssh vps 'taskhub status'
taskhub verify --integrity --multi-agent
uv run pytest tests/deploy/ -q   # 11 deploy test (Phase G)

# private staging CI/E2E
gh workflow run private-staging-e2e
gh run watch
```

**ADR Gate**:

- **ADR-00021 accepted 化** (host migration drill PASS 後)
- **ADR-00007 update accepted 化** (host 中立 invariant)
- AC-HARD-04 拡張 (backup/restore + host migration drill)

**Sprint Exit 条件 = P0 Exit 条件**:

- AC-HARD 7 全件 PASS
- AC-KPI 5 未達 1 個以下
- host migration drill (Mac → VPS) RTO ≤ 4h 達成
- 23 BL すべて Codex multi-round で clean
- ADR-00021 / ADR-00007 accepted

**Rollback**:

- host migration 失敗時は source host で運用継続 (target host を `taskhub thaw` で 2-party-control gate)
- restore 失敗時は `data/_pre-restore-<ts>/` で rollback

---

### 3.5 Phase 5 — Hook Trust Boundary (並走 Sprint 11/12、**P0 Exit blocker ではない、Codex R1 F-R1-011 adopt**)

**P0 Exit blocker 性**: **non-blocker** (post-P0 residual)

Phase 5 は SP-007 status `done_with_phase5_defer` → `done` 昇格にのみ影響し、Hard Gates 7 + KPIs 5 計測には直接寄与しない。P0 Exit (Sprint 12 完了) は Phase 5 完成を待たずに declaration 可能。

ただし以下の trade-off あり:

- **P0 Exit までに Phase 5 完了 (推奨)**: SP-007 status `done` 昇格で audit 一貫性確保、ADR-00012 accepted で residual risk 解消。Codex review 8-12 round / 1-2 session で完遂可能。
- **P0 Exit 後に Phase 5 (許容)**: P0 Exit 後の post-P0 work item として `harness-residual-risks.md` PH4-F-001/002 を維持、Phase 5 完成までは Bash tool 経由の `.claude/hooks/` 改ざん攻撃は依然可能 (docs に記録済 residual risk)。

default: **P0 Exit までに Phase 5 完了** (Sprint 11 と並走で 1-2 session 消費、P0 audit 一貫性最優先)



**target_days**: 計画値なし (Phase 工程、Sprint と独立に並走)

**Sprint Pack status**: 未起票 → 本 plan で `docs/設計検討/2026-05-13_phase5_hook_trust_boundary_plan.md` 起票プラン提示

**must_ship**:

- **BL-0082**: repo 外 trusted wrapper (`~/.claude-trusted/taskmanagedai-hook-wrapper.sh`) + manifest 検証 + fail-closed
- **BL-0083**: snapshot state repo 外移動 (`~/.claude-trusted-state/taskmanagedai/`) + dotfiles 管理化 + migration note
- **BL-0084**: sha256 manifest 生成 / 検証 + wrapper self-test
- **ADR-00012 accepted 化**: wrapper / state / manifest 完成 + self-test 通過後

**BL 数**: 3 + ADR 1 = **4 task**

**Codex multi-round budget**: **10-15 rounds** (wrapper script + manifest + self-test、shell スクリプト中心で round 少なめ)

**検証 command**:

```bash
# wrapper self-test
bash ~/.claude-trusted/taskmanagedai-hook-wrapper.sh --self-test

# manifest verify
sha256sum -c ~/.claude-trusted/taskmanagedai-manifest.sha256

# dotfiles 管理確認
ls -la ~/dotfiles/editor/claude-code/claude-trusted/

# PH4-F-001 / PH4-F-002 解消 verify
bash .claude/hooks/runner/check-dangerous-command-fixture.sh  # wrapper 経由で実行されることを確認
```

**ADR Gate**:

- **ADR-00012 accepted 化** (本 Phase で実装完成後)
- ADR-00008 (Destructive Operation) 関連 update

**Phase 5 完了条件**:

- BL-0082/0083/0084 完了
- ADR-00012 accepted
- **SP-007 status `done_with_phase5_defer` → `done` 昇格** (Phase 5 完了の正本 marker)

**Rollback**:

- wrapper 不在時は `.claude/settings.json` を `direct` mode に戻す (旧 hook 実行経路)
- snapshot state repo 内 fallback (Phase 5 完成前と同等)

## 4. 依存順序 + Critical Path

```text
Sprint 10 (Research/Evidence)
  ↓ (AC-KPI-04 source ticket)
Sprint 11 (Eval Harness + Sprint 7-9 carry-over)
  ↓ (Hard Gates 7 fixture registry / SP-008 status done / SP-009 status done / ADR-00011 accepted)
Sprint 11.5 (Observability + a11y/responsive)
  ↓ (rotation drill / dashboard / Permission Matrix CLI)
Sprint 12 (P0 Acceptance + Phase G strengthening)
  → P0 Exit

[並走可能]
Phase 5 (Hook Trust Boundary)
  → SP-007 status done 昇格 (independent of Sprint 10-12)
  → ADR-00012 accepted
```

**Critical path**: Sprint 10 → 11 → 11.5 → 12 (Sprint 12 が P0 Exit gate)。Phase 5 は SP-007 status 昇格にのみ影響 (Sprint 11/12 と並走可、ただし P0 Exit blocker ではない)。

**Sprint 10 と 11 の並走可能性**: Research/Evidence schema (BL-0114〜0118) は Sprint 11 carry-over BL (Sprint 7/8/9) と独立。Sprint 11 が容量大のため、Sprint 10 BL-0114〜0118 を **Sprint 11 batch 0 として並走** させる選択肢あり (ただし schema 変更を伴うので慎重に。本 plan の default は Sprint 10 → Sprint 11 の sequential)。

## 5. ADR Acceptance Path (Codex R1 F-R1-004/005 adopt)

| ADR | 現 status | accepted 化 Sprint | acceptance 条件 |
|---|---|---|---|
| ADR-00011 (GitHub App Permission Matrix) | proposed | **Sprint 11.5 末** (Codex R1 F-R1-004 adopt: blocker 残存中の Sprint 11 末 accepted 化は ADR 本文 `acceptance_blocked_by 8 件` と矛盾) | `acceptance_blocked_by` 8 件 (BL-0094/0095/0097/0100/0102 + BL-0096a/0101a + BL-Permission-CLI) 全件完了。Sprint 11 末では 7/8 unblock review、Sprint 11.5 BL-Permission-CLI 完成で 8/8 達成 → 正式 accepted |
| ADR-00012 (Hook Trust Boundary) | proposed | Phase 5 (P0 Exit blocker ではない、SP-007 status 昇格にのみ影響) | BL-0082/0083/0084 完了 + wrapper self-test PASS |
| ADR-00021 (Host-Portable Deployment) | proposed | Sprint 12 | host migration drill (Mac→VPS) RTO≤4h PASS + SP012-T01〜T10 完了。ADR-00021 frontmatter の accepted target を SP-012 で正式 update (Codex R1 F-R1-005 adopt: 既存 frontmatter の target Sprint 整合 verify が必要) |
| ADR-00007 update (External Exposure host 中立) | proposed | Sprint 12 | ADR-00021 と同期 accepted |
| ADR-00002 update (Research/Evidence schema) | accepted (現) | Sprint 10 で update | 既存 accepted を Research/Evidence schema 追加で update (新規 table 追加は重要変更、proposed → accepted の段階を経る) |
| ADR-00006 update (Secrets rotation drill) | accepted (現) | Sprint 11.5 で update | secret rotation drill 完成で update |

### ADR-00011 acceptance timing 詳細 (F-R1-004 adopt)

- **Sprint 11 末**: 7/8 blocker (BL-0094/0095/0096a/0097/0100/0101a/0102) unblock review、ADR-00011 ## Status 詳細 に「7/8 unblock 達成、BL-Permission-CLI のみ Sprint 11.5 carry-over」記載。frontmatter `status: proposed` 維持
- **Sprint 11.5 末**: BL-Permission-CLI 完成で 8/8 全件 unblock 達成。frontmatter `status: accepted` 昇格、`acceptance_blocked_by` field 削除
- **rationale**: ADR 本文の `acceptance_blocked_by` 全件解消が accepted 化の必要条件 (ADR Gate Criteria 11 種 #11 GitHub App permission の慎重性原則)。Sprint 11 末で frontmatter を accepted にすると ADR 本文 `acceptance_blocked_by 8 件` との内部矛盾

## 6. Codex Multi-Round Budget 集計 (Codex R1 F-R1-006/007 adopt: 二重化解消 + 式と整合)

| Sprint | BL 数 (work item) | 想定 rounds / BL | 累計 rounds (式と整合) |
|---|---:|---:|---:|
| Sprint 10 | 10 | 3-4 | 10 × 3-4 = **30-40** |
| Sprint 11 | 27 (本来 12 + carry-over 15) | carry-over 15 × 2-3 + 本来 12 × 3-4 | (30-45) + (36-48) = 66-93、ただし overlap 削減で **60-80** |
| Sprint 11.5 | 14 (本来 11 + carry-over 3) | 2-3 | 14 × 2-3 = **28-42** |
| Sprint 12 | 23 (本来 12 + Phase G 11) | 3-4 | 23 × 3-4 = **69-92** |
| Phase 5 | 4 task | 2-3 | 4 × 2-3 = **8-12** |
| **累計** | **78 work item** | **平均 3-4** | **195-266 rounds** (本 plan §0 と同期、F-R1-006 二重化解消) |

**Sprint 11 overlap 削減根拠** (F-R1-007 adopt): carry-over 15 BL のうち BL-EnumDrift / BL-0107b / BL-0080a / BL-0081a は **既存 audit (Sprint 7-9 R1-R7) で問題範囲が確定済**なので、各 BL 平均 2-3 round で clean、累計 30-45 round 想定。本来 scope 12 BL は schema / aggregator / Hard Gates registry で 3-4 round / BL、累計 36-48 round。Total 66-93、ただし R1 共通 review で 5-10 round overlap 削減 → 60-80 round。

**注**: Sprint 1-9 累計 round は ~250-300 (Sprint 7 alone で R0-R7=8 round)、本 master plan の **残 round budget 195-266** は P0 Exit までの **3-5 month** 想定 (週 10-15 round で消費 = 1-2 session / week)。

CLAUDE.md §6.5.0 「**急がなくていい、時間よりも品質**」遵守のため、round 数自体を時間制約にしない。`verdict=clean` 到達まで loop する。budget 超過時は SP-011 / SP-012 を分割 (Sprint 11a / 11b、Sprint 12a / 12b) して再見積もりする。

## 7. Verification Gate (Per Sprint)

各 Sprint Exit で必須実行 (CLAUDE.md §6.5.2 Step 5/6/7):

```bash
# Common (全 Sprint)
uv run alembic upgrade head    # migration drift check
uv run alembic check           # migration → model drift
uv run ruff check backend tests
uv run mypy backend
uv run pytest -q
cd frontend && pnpm exec tsc --noEmit
cd frontend && pnpm exec eslint . --max-warnings=0
cd frontend && pnpm test

# Sprint 11+ (Hard Gates / KPIs)
uv run pytest eval/ -q
uv run pytest tests/metrics/ -q
uv run pytest tests/contracts/ -q

# Sprint 11.5 (Observability)
docker compose --profile observability up -d
curl -s http://localhost:9090/metrics
cd frontend && pnpm exec playwright test --grep '@a11y|@responsive'

# Sprint 12 (P0 Acceptance)
taskhub backup && taskhub migrate --target t-ohga-vps --via tailscale
taskhub verify --integrity --network-invariant --age-safety
uv run pytest tests/deploy/ -q
gh workflow run private-staging-e2e && gh run watch

# Phase 5
bash ~/.claude-trusted/taskmanagedai-hook-wrapper.sh --self-test
sha256sum -c ~/.claude-trusted/taskmanagedai-manifest.sha256
```

## 8. Risk + Rollback

### 8.1 主要 Risk

| Risk | Sprint | Severity | Mitigation |
|---|---|---|---|
| Sprint 11 carry-over BL 漏れ (15+ BL の audit 互換性) | 11 | HIGH | 各 carry-over BL を Codex audit R1 で別 round 監査、SP-008/009 ## Review との差分 audit |
| ADR-00011 acceptance 失敗 (Sprint 11.5 完了後も BL-Permission-CLI unblocked) | 11.5 | MEDIUM | accepted 化を Sprint 12 へ defer、AC-KPI-02 計測は別 fixture で代替 |
| host migration drill RTO > 4h | 12 | HIGH | Sprint 11.5 で WAL archiving + dry-run drill 事前実施 |
| Phase G strengthening 11 finding の scope creep | 12 | MEDIUM | 各 finding を batch 分割 (image digest pin / signing / journal / Mac hardening を別 batch) |
| Phase 5 wrapper 化が dotfiles 管理失敗で hook 実行不能 | Phase 5 | HIGH | fail-closed 設計 (`~/.claude/settings.json` direct mode fallback)、wrapper unavailable detect + alert |
| Sprint 11 round budget 超過 (60-80 round 想定が実 100+ round) | 11 | LOW | carry-over BL を別 mini-Sprint (Sprint 11a / 11b) に分割可能 |
| ContextSnapshot.evidence_set_hash 既存 AgentRun 破壊 (Sprint 10) | 10 | MEDIUM | nullable column 追加 + backfill default、既存 row は null |

### 8.2 Rollback Strategy

| Sprint | Rollback path |
|---|---|
| Sprint 10 | migration revision 1 件 down + evidence_set_hash null backfill |
| Sprint 11 | SP-008/009 frontmatter 維持 (`partial_skeleton` / `skeleton_pending_backend` のまま)、ADR-00011 `proposed` 維持 |
| Sprint 11.5 | docker compose profile off で Observability stack revert、secret rotation 失敗時は旧 secret_ref `status='active'` 復元 |
| Sprint 12 | host migration 失敗時は source host で運用継続、`taskhub thaw` で target 2-party-control gate |
| Phase 5 | `.claude/settings.json` を direct mode に戻す (wrapper bypass) |

## 9. Schedule (Round Budget ベース)

CLAUDE.md §6.5.0 遵守で時間軸ではなく **round budget** で見積もる。1 session で平均 10-15 round 消化 (Sprint 7-9 audit 実績、13 round / 1 session)。

| Sprint | 累計 round | 想定 session 数 (10-15 round/session) |
|---|---:|---:|
| Sprint 10 | 30-40 | 2-4 session |
| Sprint 11 | 60-80 (carry-over overlap 削減後、§6 と整合) | 4-6 session |
| Sprint 11.5 | 28-42 | 2-4 session |
| Sprint 12 | 69-92 | 5-9 session |
| Phase 5 | 8-12 | 1-2 session |
| **累計** | **195-266** (本 plan §0 / §6 と完全同期、Codex R2 F-R2-003 adopt) | **13-22 session** |

**注**: rate limit / cache TTL の制約上、1 day で 1-2 session が現実的 (Codex deep-review profile xhigh は token 消費大)。P0 Exit までに **3-5 month** 想定。ただし時間軸より round 完遂 + clean を優先する。

## 10. Next Action (本 master plan 採用後)

### A. 本 master plan accepted 化

- 本 doc を `docs/設計検討/2026-05-13_p0_exit_master_plan.md` で commit
- Codex plan-review R1 → R2 → ... → clean まで loop

### B. 不足 Sprint Pack 起票 (本 plan の draft 化を受けて)

- **SP-010_research_evidence.md** (heavy Pack、target_days=4.3 / max_days=7、**10 BL** = BL-0029c + BL-0113〜0121)
- **SP-011_eval_harness.md** (heavy Pack、target_days=5.6 / max_days=10、27 BL = 本来 12 (BL-0122〜0130 + BL-0158/0159/0163) + carry-over 15)
- **SP-011-5_operational_hardening.md** (heavy Pack、target_days=5.4 / max_days=7、**14 BL** = 本来 11 (BL-0131〜0139 + BL-0156/0159b) + carry-over 3、Codex R2 F-R2-002 adopt)
- **`docs/設計検討/2026-05-13_phase5_hook_trust_boundary_plan.md`** (Phase plan、3 BL + ADR-00012 accepted)

SP-012 は既存 (本 plan で参照)。

### C. 実装着手順序

1. Sprint 10 batch 0 (ADR-00002 update + Research/Evidence schema migration) から開始
2. Sprint 10 完了後、Sprint 11 batch 0 (Eval Harness core + carry-over BL-0079a/0080a/0081a) 着手
3. Sprint 11 batch 1-4 で Sprint 7-9 carry-over 完遂 (BL-0094〜0107b 全件)
4. Sprint 11 batch 5-6 で Eval Harness 本来 scope (6 領域 + private gold task)
5. Sprint 11.5 全 14 BL (本来 11 + carry-over 3、Codex R2 F-R2-002 adopt)
6. Sprint 12 全 23 BL + P0 Acceptance verify
7. Phase 5 は Sprint 11 と並走可能 (BL-0082/0083/0084 + ADR-00012 accepted)

### D. main ff merge timing

- 各 Sprint Exit (`uv run pytest -q` + `frontend` PASS + Sprint Pack `## Review` 記載) 後に `worktree-sprint6-batch1-cli-artifact` branch → main を user 直接 ff merge (CLAUDE.md §6.7)
- Sprint 12 完了で **P0 Exit declaration** を `docs/release/p0_exit_2026_MM_DD.md` に commit

## 11. Open Decisions (本 plan で未決定、Codex plan-review で決定したい項目)

- **Q1**: Sprint 10 と Sprint 11 を sequential or 並走?  
  default: **sequential** (Sprint 10 → Sprint 11)、scope creep 防止のため  
  代替: 並走 (Sprint 10 BL-0114〜0118 を Sprint 11 batch 0 で並列、ただし schema change 並走 risk あり)

- **Q2**: ADR-00011 accepted 化 timing? (Codex R1 F-R1-004 + R2 F-R2-001 adopt で決定済)  
  default: **Sprint 11.5 末** (BL-Permission-CLI 完成で 8/8 unblock 達成後)  
  Sprint 11 末では 7/8 unblock review のみ、frontmatter `proposed` 維持

- **Q3**: Phase 5 を Sprint 11 と並走 or Sprint 12 と並走?  
  default: **Sprint 11 と並走**、SP-007 status 早期昇格で audit 一貫性確保  
  代替: Sprint 12 と並走、Hook Trust Boundary が低 priority のため

- **Q4**: Sprint 11 で carry-over 15 BL を 1 Sprint で扱う or Sprint 11a / 11b 分割?  
  default: **1 Sprint で扱う**、ただし batch 6-8 分割で慎重に  
  代替: Sprint 11a (carry-over only) → Sprint 11b (Eval Harness 本来 scope) に分割、effort 明確化

- **Q5**: Sprint 11 で SP-008 / SP-009 status を `done` 昇格させるか、`done_with_carry_over_complete` 等 custom status か?  
  default: **`done` 昇格**、carry-over BL は別 Sprint Pack (Sprint 11) で扱うため SP-008/009 自体は完了  
  代替: `done_with_carry_over_complete` 等 custom status (SP-007 の `done_with_phase5_defer` pattern 踏襲)

---

(本 plan は draft、Codex plan-review R1 で観点 (1) BL カバレッジ / (2) Hard Gates 7 + KPIs 5 trace 完全性 / (3) ADR acceptance path 妥当性 / (4) round budget 現実性 / (5) scope creep 検出 を実施予定)
