---
id: "SP-011_eval_harness"
type: "heavy"
status: "completed"
sprint_no: 11
created_at: "2026-05-13"
updated_at: "2026-05-24"
completed_at: "2026-05-17"
target_days: 5.6
max_days: 10
adr_refs:
  - "[ADR-00002](../adr/00002_db_schema.md) # accepted、Sprint 11 で update"
  - "[ADR-00003](../adr/00003_api_contract.md) # accepted、backend route 追加で update"
  - "[ADR-00004](../adr/00004_agentrun_state_machine.md) # accepted、event_type 拡張で update"
  - "[ADR-00006](../adr/00006_secrets_management.md) # accepted、SecretBroker allowed_operations 拡張"
  - "[ADR-00009](../adr/00009_action_class_taxonomy.md) # accepted、repo.push / repo.pr_open enforcement"
  - "[ADR-00011](../adr/00011_github_app_permission_matrix.md) # accepted after Sprint 11.5 BL-Permission-CLI completion (F-R1-004 adopt)"
planned_adr_refs: []
related_sprints:
  - "SP-007_runner_sandbox # carry-over BL-0079a/0080a/0081a"
  - "SP-008_github_app_repoproxy # carry-over 7 BL"
  - "SP-009_p0_ui_pack # carry-over 5 BL"
  - "SP-010_research_evidence # AC-KPI-04 source"
  - "SP-012_p0_acceptance # P0 Exit gate"
  - "SP-011-5_operational_hardening"
upstream_sprints:
  - "SP-007_runner_sandbox"
  - "SP-008_github_app_repoproxy"
  - "SP-009_p0_ui_pack"
  - "SP-010_research_evidence"
downstream_sprints:
  - "SP-011-5_operational_hardening"
  - "SP-012_p0_acceptance"
risks:
  - "carry-over 15 BL の audit 互換性破壊 (Sprint 7-9 audit clean を壊さない)"
  - "ADR-00011 acceptance 失敗 (acceptance_blocked_by 8 件のいずれか unblocked)"
  - "Eval fixture と policy / runner module の commit 分離違反 (Anti-Gaming Rules)"
  - "private_holdout 期待値の漏えい (eval fixture の期待値を policy / prompt 調整に使う overfit)"
  - "round budget 超過 (60-80 round 想定が 100+ round、Codex R2 F-R2-003 adopt で master plan §6 と整合)"
  - "AC-HARD-04 backup_restore_rpo_rto と SP-012 の責務分担曖昧"
---

このテンプレの使い方: ADR Gate Criteria #2 DB schema + #3 API contract + #11 GitHub App permission + #5 MCP/tool 権限 (eval fixture loader) に該当する Sprint。Eval Harness 本来 scope (12 BL) + Sprint 7-9 carry-over (15 BL) = 27 BL の最大規模 Sprint。Codex multi-round で `verdict=clean` まで全件 polish する。

最終更新: 2026-05-13

## 目的

### 本来 scope (Eval Harness、12 BL)

- 6 領域 Eval (decomposition / coding / review / research / security / cost) の harness + dataset loader
- `public_regression` / `private_holdout` / `adversarial_new` 3 split + dataset version + Anti-Gaming Rules
- Hard Gates 7 件すべての fixture registry / loader 統合
- private gold task 30-50 件への拡張
- Quality KPI 5 件の計測 endpoint + aggregator

### Sprint 7-9 carry-over (15 BL)

- Sprint 7 (3 BL): BL-0079a (runner audit payload 拡張) / BL-0080a (AC-HARD-05 fixture 充実) / BL-0081a (AC-HARD-06 fixture 充実)
- Sprint 8 (7 BL): BL-0094 / BL-0095 / BL-0097 / BL-0100 / BL-0102 + refactor BL-0096a / BL-0101a
- Sprint 9 (5 BL): BL-0103a / BL-0106a / BL-0107a / BL-0107b / BL-EnumDrift

## 背景

- Sprint 9 完了時点で SP-008 `partial_skeleton` / SP-009 `skeleton_pending_backend` の carry-over 残あり (2026-05-13 audit で 25 adopt + 6 backlog tracking + 1 Phase 5 defer)。2026-05-24 status hygiene 時点では SP-009 は `partial_skeleton` に再分類済み。
- ADR-00011 (GitHub App Permission Matrix) の `acceptance_blocked_by` 8 件のうち 7 件が本 Sprint で解消対象 (残 1 件は Sprint 11.5 の BL-Permission-CLI)、accepted 化は **Sprint 11.5 完了後** (本 Sprint では 7 件解消の verify review のみ、frontmatter は `proposed` 維持。Codex R1 F-R1-004 adopt: blocker 残存中に accepted 昇格は ADR 本文と矛盾)
- Eval Harness は P0 Exit の中核 (Hard Gates 7 + KPIs 5 計測の正本)、SP-012 で acceptance gate を判定する前に completion 必要

## 対象外

- 自動再分解 (P1 へ defer)
- shadow mode (P1 へ defer)
- 6 領域の自動 ranking / leaderboard (Sprint 11.5 で Grafana 可視化のみ)
- AC-HARD-04 backup_restore_rpo_rto drill (SP-012 で実施、本 Sprint では fixture skeleton のみ)

## 設計判断

- **Anti-Gaming Rules 厳守**: fixture creation commit (本 Sprint) と policy / prompt 修正 commit (Sprint 1-9 + Sprint 11 内の policy fix) を分離。CI gate で commit author + commit timestamp の inversion を検出。
- **private_holdout 期待値隠蔽**: `eval/security/*/private_holdout/` 配下の期待値は test 実行時に loader 経由でのみ access、source code grep で期待値が出ない構造 (encrypted SOPS + age 経由で復号)。
- **3 split の役割分担**:
  - `public_regression`: CI で常時実行、regression 検出
  - `private_holdout`: monthly refresh、append-only、policy / prompt 修正と分離
  - `adversarial_new`: monthly 1-3 件追加、prompt injection / secret canary / dangerous command / forbidden path / cross-tenant 強化
- **dataset version**: `(fixture_id, dataset_version, fixture_kind)` の 3 unique で AgentRun / EvalRun / EvalResult に保存 (Sprint 4 で AgentRun に dataset_version_id 列確保済)
- **carry-over BL の audit 互換性**: 各 carry-over BL を Codex audit R1 で別 round 監査し、Sprint 7-9 audit clean を破壊しないことを enforcement
- **ADR-00011 acceptance**: 本 Sprint 末では **7/8 unblock review のみ** (BL-0094/0095/0096a/0097/0100/0101a/0102 完成 verify)、frontmatter `status: proposed` 維持。**Sprint 11.5 BL-Permission-CLI 完成で 8/8 unblock 達成後に accepted 昇格** (Codex R1 F-R1-004 + R2 F-R2-001 adopt: blocker 残存中の accepted 化は ADR 本文 `acceptance_blocked_by 8 件` と内部矛盾)

## 実装チケット

### batch 0: ADR + Eval Harness core skeleton

| BL ID | 内容 | depends_on |
|---|---|---|
| (placeholder) | Eval Harness directory skeleton (`eval/harness/loader.py`, `eval/harness/runner.py`、本格実装は batch 5 の BL-0122/0123) | — |

注: batch 0 は ADR-00011 acceptance 準備 + Sprint 11 carry-over BL audit 環境準備のみ (新規 BL なし)。Eval Harness 本実装 (BL-0122/0123) は batch 5 で開始。

### batch 1: Sprint 7 carry-over (3 BL)

| BL ID | 内容 |
|---|---|
| BL-0079a | runner audit payload に actor_id / trace_id / correlation_id / gateway_kind / artifact_refs 追加 + AgentRunEvent integration + `runner_cancelled` / `runner_cleanup_completed` event_type 追加 |
| BL-0080a | AC-HARD-05 fixture private_holdout + adversarial_new 充実 (symlink / `..` traversal / URL-encoded / Unicode ZWJ variants 各 10+ 件) |
| BL-0081a | AC-HARD-06 fixture private_holdout + adversarial_new 充実 (shell injection / encoding / Docker escape / fork bomb / resource abuse variants 各 10+ 件) |

### batch 2: Sprint 8 carry-over (5 BL)

| BL ID | 内容 |
|---|---|
| BL-0094 | GitHub App 登録 + private key SOPS encrypt (admin 手動 + `secret_refs.allowed_operations` に repo.push/pr_open 追加) |
| BL-0095 | SecretBroker `repo.push` / `repo.pr_open` allowed_operations 追加 + capability_token issue flow 結線 + broker `_validate_allowed_operations` |
| BL-0097 | GitHubAppAdapter httpx wrapper (broker-mediated only + retries + rate limit + api_version=2022-11-28 + no raw token leak) |
| BL-0100 | AgentRunEvent `repo_pr_opened` actual emission (2026-05-24 Batch D/D2 で `RepoPROpenedEventWriter` + payload schema + DB append test + `DraftPRRuntime` call-site wrapper を追加済。残作業は real GitHub transport 有効化後の外部 API/worker adoption) |
| BL-0102 | AC-KPI-02 `time_to_merge` 計測 endpoint (`/api/v1/agent_runs/{run_id}/kpi`) + per-run `repo_pr_opened` → AgentRun completed proxy exposure |

### batch 3: Sprint 8 refactor (2 BL)

| BL ID | 内容 |
|---|---|
| BL-0096a | RepoProxy 4 整合 binding server-side 再計算 refactor (`create_draft_pr(approval_id, agent_run_id)` signature + DB / ContextSnapshot / Git ref から 4 hash 再計算 + 1 mismatch per case negative test) |
| BL-0101a | Webhook HMAC SecretBroker-mediated service layer (2026-05-24 Batch C/C2 で `GitHubWebhookVerifier` service boundary + SecretRef resolver + Redis SETNX replay adapter + FastAPI `/webhooks/github` route wiring + `secret_refs.status` 検証を追加済。残作業は deployment SOPS material resolver wiring) |

### batch 4: Sprint 9 carry-over (5 BL)

| BL ID | 内容 |
|---|---|
| BL-0103a | `GET /api/v1/tickets` list + detail route + tenant boundary + repository contract test + 越境 negative test |
| BL-0106a | `GET /api/v1/agent_runs` list + detail route (既存 POST /cancel に加えて list / detail) |
| BL-0107a | `GET /api/v1/audit_events` route + cursor pagination + tenant filter |
| BL-0107b | `RedactedAuditPayloadSchema` / `RedactedAgentRunEventPayloadSchema` (frontend) + backend `_payload_secret_scan.py` を frontend に port + DOM secret scan test (AC-HARD-02 enforcement) |
| BL-EnumDrift | TicketStatus / AgentRunStatus / AgentRunEventType / AuditEventType / PayloadDataClass の cross-source drift contract test (backend Literal / DB CHECK / frontend Zod の exact set 比較) |

### batch 5: Eval Harness 本来 scope (9 BL、正本 BL ID = PLAN-01)

| BL ID | 内容 |
|---|---|
| BL-0122 | `dataset_versions` / eval tables の fixture loader (dataset version + fixture_kind enum + (fixture_id, dataset_version, fixture_kind) 3 unique) |
| BL-0123 | public_regression / private_holdout / adversarial_new を split directory + Anti-Gaming metadata enforcement (BL-0129 と integration) |
| BL-0124 | decomposition eval suite (AC-KPI-01 acceptance_pass_rate source、BL-0031 連動) |
| BL-0125 | coding / review eval suites (Sprint 5.5 Output Validator 連動、BL-0090 carry-over 依存) |
| BL-0126 | research eval suite + citation_coverage 判定 (AC-KPI-04 aggregator、SP-010 BL-0119 source 経由 evidence_set_hash 統合) |
| BL-0127 | Hard Gates 7 件すべての fixture registry / loader 統合 (BL-0041/0078/0083/0091/0102/0153/0157/0158/0159/0160 source 連動) |
| BL-0128 | cost eval suite + cost_per_completed_task (AC-KPI-05、BL-0053 / BL-0069 source 統合) |
| BL-0129 | Anti-Gaming Rules dataset metadata enforcement (fixture creation commit + policy / runner / prompt 修正 commit 分離 verify、commit author / timestamp inversion 検出) |
| BL-0130 | nightly regression job (CI 経由で public_regression 自動実行、private_holdout は monthly schedule) |
| BL-0158 | `tenant_isolation_negative_pass` fixture loader を Eval Harness に接続 (AC-HARD-03、BL-0029/0029b/0029c source 連動) |
| BL-0159 | `backup_restore_rpo_rto` fixture contract を Eval Harness に登録 (AC-HARD-04 fixture skeleton、PITR activation は Sprint 11.5 BL-0159b) |
| BL-0163 | Gold Task Seed v0 を private gold task 30-50 件へ拡張 (BL-0006 / BL-0155 source 連動、payload_data_class 付与) |

## タスク一覧

- [ ] batch 0: ADR-00011 acceptance prep + Eval Harness directory skeleton (新規 BL なし、環境準備のみ)
- [ ] batch 1: Sprint 7 carry-over (BL-0079a/0080a/0081a) — 各 BL を Codex audit R1 で別 round 監査
- [ ] batch 2: Sprint 8 carry-over (BL-0094/0095/0097/0100/0102) — broker-mediated installation token + capability_token 流
- [ ] batch 3: Sprint 8 refactor (BL-0096a/0101a) — server-owned 4 整合 + Webhook HMAC service layer
- [ ] batch 4: Sprint 9 carry-over (BL-0103a/0106a/0107a/0107b/BL-EnumDrift) — backend route + frontend redaction
- [ ] batch 5: Eval Harness 12 BL (BL-0122〜0130 + BL-0158/0159/0163)
- [ ] Sprint Exit: ADR-00011 acceptance は **Sprint 11.5 BL-Permission-CLI 完了後** に正式 accepted 化 (本 Sprint 末は ADR draft acceptance review のみ、frontmatter status は `proposed` 維持)。SP-008/009 status `done` 昇格 + Sprint Pack ## Review

## must_ship / defer_if_over_budget 対応表

| 項目 | must_ship | defer_if_over_budget |
|---|---|---|
| Eval Harness core + 6 領域 + 3 split + dataset version | ○ | — |
| Sprint 7 carry-over 3 BL | ○ | — |
| Sprint 8 carry-over 7 BL (5 main + 2 refactor) | ○ | — |
| Sprint 9 carry-over 5 BL | ○ | — |
| Hard Gates 7 件 fixture registry / loader 統合 | ○ | — |
| Quality KPI 5 件 aggregator | ○ | — |
| Anti-Gaming Rules CI gate | ○ | — |
| ADR-00011 acceptance review (本 Sprint で 7 件 unblock 確認) | ○ | Sprint 11.5 BL-Permission-CLI 完了後に正式 accepted、Sprint 12 へ defer 可 |
| private gold task 30-50 件 (BL-0163) | ○ | 30 件で達成可、50 件は SP-022 |
| `tenant_isolation_negative_pass` fixture loader (BL-0158) | ○ | — |
| `backup_restore_rpo_rto` fixture contract skeleton (BL-0159) | ○ | activation は Sprint 11.5 BL-0159b |
| nightly regression job (BL-0130) | ○ | — |
| 自動再分解 | × | P1 |
| shadow mode | × | P1 |
| 6 領域 leaderboard | × | Sprint 11.5 で Grafana 可視化 |

## 受け入れ条件

- 27 BL すべて Codex multi-round で `verdict=clean` 到達 (CRITICAL=0 / HIGH ≤ 2、全 finding adopt / reject 判定済) ※ Sprint 11 Exit (2026-05-17、Codex PR #39 R1 F-PR39 全件 adopt 後) で **scope 縮減**: 本 Sprint 完遂は **16 BL clean** (Eval Harness 本来 scope 12 BL + Sprint 7-9 carry-over 完遂 5 BL = BL-0094/0095/0097/0101a/0102 aggregator)、当時の未実装 carry-over 11 BL (BL-0079a/0080a/0081a/0096a/0100/0102 endpoint/0103a/0106a/0107a/0107b/EnumDrift) + BL-0125 SP-022 defer = 計 12 BL は Sprint 12 (P0 Acceptance) または SP-022 へ defer 移送。2026-05-24 follow-up で BL-0102 endpoint は completed。詳細は ## Review Sprint 11 Exit Summary 参照
- Sprint 7-9 audit clean (2026-05-13) を本 Sprint で破壊しない (regression test PASS)
- SP-008 status `partial_skeleton` → `done` 昇格
- SP-009 status `skeleton_pending_backend` → `done` 昇格 (original Sprint 11 target; Sprint Exit で scope 縮減。2026-05-24 status hygiene 時点では `partial_skeleton` 維持)
- ADR-00011 7/8 件 unblock review 完了 (frontmatter `proposed` 維持)、accepted 昇格は Sprint 11.5 BL-Permission-CLI 完了後 (Codex R1 F-R1-004 adopt)
- AC-HARD 7 件 + AC-KPI 5 件すべて fixture registry / aggregator 経由で測定可能
- Anti-Gaming Rules CI gate が fixture creation commit + policy 修正 commit 分離 verify
- private_holdout 期待値が source code grep で漏えいしない (SOPS + age 経由復号)

### QL-C 拡充 acceptance spec (R29 §5 QL-C、P-09 + P-18 反映、doc-only)

本 section は **QL-C run (2026-05-15、quality-loop/QL-C-research-eval-pack)** で追記した修正まとめ拡充 spec。**本 SP-011 では schema 追加なし** (acceptance spec のみ)、実 BL 詳細は本 Sprint 11 carry-over + 本来 scope 内で landing する。SP-010 が source contract (SearchRun / EvidenceSearchHit / GroundingSupport / RetrievalEvalRun) を提供、SP-011 は **集計 / metric 計測** が責務。

- **recall@k acceptance spec** (k = 5, 10、retrieval quality 計測):
  - 計算: gold answer の relevant evidence_source_id 集合のうち、SearchRun の top-k EvidenceSearchHit に含まれる数 / 全 relevant 数
  - 集計単位: `RetrievalEvalRun.recall_at_k` json column (`{"5": float, "10": float}`)
  - P0 で `recall@5 >= 0.6`、`recall@10 >= 0.75` (Sprint 12 で final verify)
- **precision@k acceptance spec** (k = 5, 10、retrieval signal-to-noise 計測):
  - 計算: SearchRun の top-k EvidenceSearchHit のうち relevant な数 / k
  - 集計単位: `RetrievalEvalRun.precision_at_k` json column
- **ndcg@k acceptance spec** (k = 10、retrieval ranking quality 計測):
  - **gain source (Codex F-QLC-005 P1 adopt)**: 標準 nDCG@10、**gain は gold relevance labels (fixture の graded relevance)** から取る — EvidenceSearchHit.relevance_score (ranker 自己採点) を gain に使うと **ranker が自分で高く採点した非 relevant hit でも nDCG を上げられる** self-reported score 依存になり Anti-Gaming 致命的。gold relevance は recall/precision と同じ fixture 由来 (dataset_versions に紐付く gold annotation)。
  - 計算: gold relevance を gain、`log2(rank+1)` で discount、`(tenant_id, project_id, search_run_id, rank)` unique を SP-010 で enforce 済 (top-k 安定再計算)
  - 集計単位: `RetrievalEvalRun.ndcg_at_k` json column (`{"10": float}`)
  - `EvidenceSearchHit.ndcg_contribution` 列は **記録用 metric のみ**、nDCG 集計の gain source としては使わない (Anti-Gaming reject)
- **citation_coverage acceptance spec** (AC-KPI-04、grounding quality 計測):
  - **claim-level 集計 (Codex F-QLC-004 P1 adopt、SP-010 と整合)**: AC-KPI-04 既存 contract は `count(distinct claim_id with >= 1 GroundingSupport) / count(distinct claim_id within evaluated AgentRun)` — claim 単位で集計、generated_artifact-level は誤り (歪み発生)
  - **final-adopted artifact filter (Codex R3 F-QLC-R3-001 P2 adopt)**: multi-agent/orchestrator context での AC-KPI-04 rollup は `.claude/reference/multi-agent-orchestration-draft.md` の規則 (#15 review pass = human approval ではない、final-adopted artifact のみが metric source) を遵守。candidate / child draft artifact (final adopt されていない) は分母 / 分子 から除外し、**final adopted artifact 由来の claim のみ** で集計。filter source: artifact の `is_final_adopted: bool` flag (Sprint 11 BL-0126 で追加列、または `agent_runs.final_artifact_id` の参照経由)。
  - P0 で `claim-level citation_coverage >= 0.9` (Sprint 12 AC-KPI-04 final verify、final-adopted artifact のみ対象)
  - **null evidence_set_hash AgentRun の扱い (SP-010 F-QLC-007 と整合)**: 分母に含め、分子は 0 として uncovered として数える (除外しない、ただし final-adopted artifact を持つ AgentRun のみ対象)
- **grounded_answer_rate acceptance spec** (P0 Quality KPI 補強、optional Eval metric):
  - 計算: GroundingSupport 1 件以上関連付く **claim** の比率 (claim-level、generated_artifact-level ではない、citation_coverage と同等定義)
- **tool_trajectory_match acceptance spec** (Eval fixture vs actual AgentRun trajectory):
  - **計算 (Codex F-QLC-008 P2 adopt)**: fixture 想定 tool sequence vs actual AgentRunEvent emitted tool sequence の **order-preserving metric** — **Jaccard index は使わない** (順序消失、`search→read→cite` と `cite→read→search` を同 score にする)。
  - 推奨 metric: **Normalized Edit Distance** (`1 - levenshtein(expected, actual) / max(len(expected), len(actual))`、float [0, 1]) を P0 default に。alternative として `Longest Common Subsequence ratio` / `prefix match ratio` を fixture 設計時に選択可能。
  - **Empty sequence edge case (Codex R2 F-QLC-R2-004 P2 adopt)**: `max(0, 0) = 0` で division-by-zero / NaN 発生を防ぐため、両 sequence empty / 片方のみ empty の挙動を明示固定:
    - `expected = [] AND actual = []` → score `1.0` (no tool 期待 + no tool emit = match)
    - `expected = [] AND actual = [_, ...]` → score `0.0` (tool emit すべきでない fixture で emit された)
    - `expected = [_, ...] AND actual = []` → score `0.0` (tool emit 期待 fixture で emit されなかった)
    - 上記 edge case を含む Eval fixture の集計時、本 metric は always [0, 1] 範囲で安定 (NaN / exception 発生なし)
  - 集計単位: `RetrievalEvalRun.tool_trajectory_match` float [0, 1] + `tool_trajectory_metric_kind` enum (`edit_distance` / `lcs_ratio` / `prefix_ratio`) を `RetrievalEvalRun` の metric_metadata に記録
  - Anti-Gaming invariant: fixture commit と AgentRun emit logic 修正 commit を **別 author / 別 timestamp** で分離 (BL-0129 CI gate)

### Pack reuse + cross-ref 注記 (R29 P-09 + P-18 反映)

- 本 SP-011 は前 session commit `369672b` で作成済の **既存 Pack**。本 QL-C run では拡充 spec のみ追記、新規 Pack 作成なし。
- SP-010 cross-ref: 上記 metrics の **source schema (SearchRun / EvidenceSearchHit / GroundingSupport / RetrievalEvalRun)** は SP-010 で acceptance spec 追記済 (本 PR 同一 file)。SP-011 は同 schema からの **集計のみ** が責務。
- **eval_runs schema 拡張 (Codex R3 F-QLC-R3-004 P2 adopt cross-ref)**: SP-010 RetrievalEvalRun spec で `(tenant_id, eval_run_id, agent_run_id) references eval_runs(tenant_id, id, agent_run_id)` 複合 FK が必要 → 本 SP-011 BL-0122 で `eval_runs.agent_run_id` 列追加が前提条件。ADR-00002 update で `eval_runs` schema 拡張を明文化、Sprint 11 BL-0122 着手前に accepted 化。
- 既存 BL trace 維持 (Sprint 11 本来 scope 12 BL + carry-over 15 BL = 27 BL は R29 §5 QL-C verification で破壊不可)。

## 検証手順

```bash
# 全 carry-over verify (15 BL)
uv run pytest tests/secrets/test_repo_operations.py tests/repoproxy/test_github_app_adapter.py \
              tests/repoproxy/test_repo_pr_opened_event.py tests/contracts/test_kpi_time_to_merge.py \
              tests/repoproxy/test_4integrity_negative.py tests/repoproxy/test_webhook_service.py \
              tests/api/test_tickets_route.py tests/api/test_agent_runs_list.py tests/api/test_audit_events_route.py \
              tests/contracts/test_ac_hard_02_frontend_redaction.py \
              tests/contracts/test_frontend_backend_enum_drift.py \
              tests/agent_runtime/test_runner_audit_event_emission.py \
              tests/security/test_ac_hard_05_private_holdout.py tests/security/test_ac_hard_06_private_holdout.py -q

# Eval Harness 本来 scope
uv run pytest eval/ -q
uv run pytest tests/metrics/ -q
uv run pytest tests/eval_harness/ -q

# Anti-Gaming Rules CI gate
uv run python -m backend.scripts.anti_gaming_audit --check-commit-separation

# Hard Gates 7 fixture registry
curl -s http://localhost:8000/api/v1/eval/hard-gates/status | jq

# ADR-00011 acceptance gate
uv run python -m backend.app.services.repoproxy.permission_matrix --check

# 既存 audit clean regression
uv run pytest -q  # 全 backend (2219+) PASS 維持
cd frontend && pnpm exec tsc --noEmit && pnpm exec eslint . --max-warnings=0
```

## レビュー観点

- 各 carry-over BL の Codex audit clean (R1 で個別監査、R2 で integration 監査)
- SP-008/009 ## Review 章への carry-over 完了記録 (本 Sprint の Review 章に追記)
- AC-HARD-05 / AC-HARD-06 private_holdout の **fixture creation commit + policy 修正 commit 分離** verify
- broker-mediated installation token が server-owned (capability_token issue flow が SecretBroker 経由のみ、caller-supplied 経路なし)
- frontend redaction schema が backend `_payload_secret_scan.py` と enum-level integrity (Zod ↔ Pydantic exact set match)
- BL-EnumDrift contract test が backend / DB / frontend の 3 source で drift 検出 (新 enum 追加忘れ / 削除忘れ両方)
- ADR-00011 acceptance の final blocker (BL-Permission-CLI) が ADR 本文に明記 (Sprint 11.5 で完成、本 Sprint 末は frontmatter proposed 維持)

## Rollback (per batch)

- batch 1 失敗 (Sprint 7 carry-over): BL-0079a (runner audit payload) → 旧 schema 維持、AgentRunEvent integration を defer / BL-0080a/0081a (fixture) → public_regression のみで運用、private/adversarial は Sprint 12 final verify に defer
- batch 2 失敗 (Sprint 8 carry-over GitHub App 結線): SP-008 status `partial_skeleton` 維持、Mock RepoProxy で運用継続、AC-KPI-02 計測は Sprint 12 で別 source
- batch 3 失敗 (Sprint 8 refactor): server-owned 4 整合 + Webhook HMAC 旧実装に revert、Sprint 12 で再 refactor
- batch 4 失敗 (Sprint 9 carry-over): SP-009 status `skeleton_pending_backend` 維持、frontend は `_listXxxDraft` prefix 継続、backend route は Sprint 12 へ defer
- batch 5 失敗 (Eval Harness 12 BL): BL-0122/0123 (dataset_versions / split) → file system 直 load で運用継続、Hard Gates 7 fixture registry は SP-012 で個別 verify、AC-KPI aggregator (BL-0124/0126/0128) は SP-012 で個別計測
- ADR-00011 acceptance review 失敗: frontmatter `proposed` 維持、Sprint 11.5 / Sprint 12 で再 review

## Audit Event

新規 event_type (Sprint 11 で追加または既存 source 連動):

- `runner_cancelled` (BL-0079a、AgentRun cancel → runner SIGTERM 経路)
- `runner_cleanup_completed` (BL-0079a、workspace dir cleanup 完了)
- `repo_pr_opened` (BL-0100、Draft PR 作成完了、Sprint 8 で event_type 予約済を本 Sprint で actual emission)
- `eval_run_started` (BL-0122 / BL-0124〜0128、eval suite 起動)
- `eval_run_completed` (BL-0124〜0128、result aggregation)
- `eval_anti_gaming_violation` (BL-0129、commit author / timestamp inversion detect)

audit_events payload に必須 field (BL-0079a 完成後): `tenant_id` / `actor_id` / `run_id` / `eval_run_id?` / `fixture_id?` / `dataset_version?` / `trace_id` / `correlation_id` / `gateway_kind` / `timestamp`。raw secret / raw provider response / raw fixture 期待値 は payload に含めず、reason_code + hash のみ記録 (AC-HARD-02 invariant)。

## 残リスク

- **carry-over 15 BL の audit 互換性 (HIGH)**: Sprint 7-9 audit clean を本 Sprint で破壊しないよう、各 BL を別 Codex round で個別監査 + 全 carry-over 完了後 integration audit
- **ADR-00011 acceptance 失敗 (MEDIUM)**: 本 Sprint で 7/8 件 unblock review、frontmatter `proposed` 維持。accepted 昇格は **Sprint 11.5 BL-Permission-CLI 完了後** (Codex R1 F-R1-004 adopt)。Sprint 11.5 でも完成しない場合は Sprint 12 へ defer 可
- **Eval fixture と policy 修正の commit 分離違反 (HIGH、Anti-Gaming)**: CI gate で commit author + commit timestamp inversion 検出、違反時は CI fail
- **private_holdout 期待値漏えい (CRITICAL、Anti-Gaming)**: SOPS + age 経由復号で grep 隠蔽、ただし test 実行 log で期待値が出る経路がないか別途 audit
- **round budget 超過 (LOW、60-80 round 想定が 100+ round)**: batch 分割 6-8 で各 batch 8-12 round / 累計 60-80 round に収まる想定、超過時は Sprint 11a (carry-over only) / 11b (Eval Harness 本来 scope) 分割を Sprint 12 着手前に AskUserQuestion で判断 (Codex R2 F-R2-003 adopt: master plan §6 と整合)
- **AC-HARD-04 backup_restore_rpo_rto と SP-012 責務分担 (LOW)**: 本 Sprint は fixture skeleton のみ、実 drill は SP-012 で実施 (BL-0130 で skeleton 確保)

## 次スプリント候補

- Sprint 11.5 (Operational Hardening + a11y / responsive carry-over) — Permission Matrix CLI + Observability
- Sprint 12 (P0 Acceptance) — Hard Gates 7 + KPIs 5 final verify + host migration drill

## 関連 ADR

- ADR-00002 (DB schema) — Eval Harness DDL 追加で update
- ADR-00003 (API contract) — backend route 追加 + Eval endpoint で update accepted
- ADR-00004 (AgentRun state machine) — runner_cancelled / runner_cleanup_completed event_type 追加で update
- ADR-00006 (Secrets management) — SecretBroker allowed_operations 拡張で update
- ADR-00009 (Action class taxonomy) — repo.push / repo.pr_open enforcement
- **ADR-00011 (GitHub App Permission Matrix) — proposed → accepted 化**

## Review

### Sprint 11 Exit Summary (2026-05-17、status: completed for main scope、carry-over は Sprint 12 defer)

**期間**: 2026-05-13 〜 2026-05-17 (5 day、target_days=5.6 / max=10 内、`time_to_merge` AC-KPI-02 median ~2h 維持)

**Scope 縮減宣言 (Codex PR #39 R1 F-PR39-001/002/003/004 P2 adopt)**:

SP-011 PR #39 起票時 (2026-05-17) に「27 BL 完遂」と記載していたが、Codex F-PR39-002/003/004 で **Sprint 7-9 carry-over の一部 (BL-0079a/0080a/0081a/0096a/0100/0102 endpoint/0103a/0106a/0107a/0107b/BL-EnumDrift 計 11 BL) が未実装** との指摘あり、repo 実態確認で事実と判明。事実誤認による Sprint Pack 虚偽記録を防ぐため、本 Sprint 11 Exit は **Eval Harness 本来 scope 12 BL + Sprint 7-9 carry-over の完遂分 5 BL = 計 16 BL のみ完遂** として記録し、未実装 carry-over 11 BL は Sprint 12 (P0 Acceptance) へ defer 移送。2026-05-24 follow-up で BL-0102 endpoint は completed。Sprint 11 受け入れ条件 line 181「27 BL clean」は本 Exit で **16 BL clean (carry-over 11 BL は Sprint 12 へ defer)** に再定義。

#### Sprint 7 carry-over (3 BL 中 0 BL 完遂、3 BL Sprint 12 へ defer)
- ❌ BL-0079a (`runner_cancelled` / `runner_cleanup_completed` event_type): 不在 (`backend/app/domain/agent_runtime/event_type.py` に追加されていない) → **Sprint 12 へ defer**
- ❌ BL-0080a (AC-HARD-05 forbidden_path private_holdout + adversarial_new 各 10+ 件): `eval/security/forbidden_path/{private_holdout,adversarial_new}/` に README のみ → **Sprint 12 へ defer**
- ❌ BL-0081a (AC-HARD-06 dangerous_command private_holdout + adversarial_new 各 10+ 件): `eval/security/dangerous_command/{private_holdout,adversarial_new}/` に README のみ → **Sprint 12 へ defer**

#### Sprint 8 carry-over (7 BL 中 5 BL 完遂、2 BL Sprint 12 へ defer at Sprint 11 Exit。2026-05-24 follow-up で BL-0102 endpoint completed)
- ✅ BL-0094 (GitHub App 登録 + SecretBroker `repo.push`/`repo.pr_open` allowed_operations 拡張): `backend/app/services/secrets/broker.py:445,647-648,657-658` 実在
- ✅ BL-0095 (capability_token issue flow): `backend/app/services/secrets/broker.py` + `backend/app/repositories/secret_capability_token.py` + `backend/app/db/models/secret_capability_token.py` 実在
- ❌ BL-0096a (RepoProxy 4 整合 binding signature refactor): 2026-05-17 Sprint 11 exit 時点では Draft PR request 直接受け渡しの旧 signature のままで、ID binding signature への refactor は未完了だった (file 内コメント line 12 に「Sprint 11 で refactor」と書かれていたが実装は未着手) → **Sprint 12 へ defer**。2026-05-24 follow-up: SP-008 Batch A/A2 で public signature は `DraftPRBinding` のみに閉じ、DB-backed ApprovalRequest+ContextSnapshot resolver まで追加。live Git ref re-fetch は GitHubAppAdapter 側の残作業として継続。
- ✅ BL-0097 (GitHubAppAdapter / RepoProxy): 2026-05-17 時点では `backend/app/services/repoproxy/{repoproxy,permission_matrix}.py` 実在 (mock 含む) のみ。2026-05-24 follow-up: `github_app_adapter.py` broker-mediated boundary 追加済、real httpx transport + live Git ref re-fetch は残作業。
- ✅ BL-0100 (`repo_pr_opened` AgentRunEvent actual emission): 2026-05-17 Sprint 11 exit 時点では event_type は予約済だが emission code が不在だった。2026-05-24 follow-up: `RepoPROpenedEventWriter` + DB append test + `DraftPRRuntime` call-site wrapper を追加済。real GitHub transport 有効化後の外部 API/worker adoption は残作業。
- ✅ BL-0101a (Webhook HMAC SecretBroker-mediated service layer): 2026-05-24 follow-up で `GitHubWebhookVerifier` service boundary + SecretRef resolver + Redis replay adapter + FastAPI route + status validation test を追加済。deployment SOPS material resolver は残作業。
- ✅ BL-0102 (AC-KPI-02 `time_to_merge`): aggregator は `backend/app/services/eval/kpis/time_to_merge.py` 完成 (PR #34)。2026-05-24 follow-up で `GET /api/v1/agent_runs/{run_id}/kpi` + `AgentRunKpiService` を追加し、per-run `repo_pr_opened` first event → `agent_runs.completed_at` proxy を API exposure 済。

#### Sprint 9 carry-over (5 BL 中 0 BL 完遂、5 BL Sprint 12 へ defer)
- ❌ BL-0103a (`GET /api/v1/tickets` list + detail): `backend/app/api/tickets.py` **file 不在** → **Sprint 12 へ defer**
- ❌ BL-0106a (`GET /api/v1/agent_runs` list + detail): `backend/app/api/agent_runs.py` に `POST /{run_id}/cancel` のみ、list/detail endpoint 不在 → **Sprint 12 へ defer**
- ❌ BL-0107a (`GET /api/v1/audit_events` route): `backend/app/api/audit_events.py` **file 不在** → **Sprint 12 へ defer**
- ❌ BL-0107b (RedactedAuditPayloadSchema + DOM secret scan / AC-HARD-02 enforcement): frontend 内に該当 schema 不在 → **Sprint 12 へ defer**
- ❌ BL-EnumDrift (3 source enum drift detection contract test): `tests/contracts/test_frontend_backend_enum_drift*.py` **file 不在** → **Sprint 12 へ defer**

#### Eval Harness 本来 scope (12 BL、完遂)
- BL-0122 (`dataset_versions` / `eval_runs` / `eval_cases` / `eval_scores` 4 tables + loader、batch 5a / PR #28)
- BL-0123 (public_regression / private_holdout / adversarial_new split + Anti-Gaming metadata、batch 5b)
- BL-0124 (decomposition eval / `acceptance_pass_rate` AC-KPI-01、batch 5f / PR #33)
- **BL-0125 (coding / review eval suites) → SP-022 へ defer** (Sprint 5.5 Output Validator + BL-0090 dependency 未解決、`docs/sprints/SP-022_framework_intake_hardening.md` で carry-over、Sprint 11 受け入れ条件 line 181 を「26 BL すべて Codex multi-round で `verdict=clean`」へ update、本 batch 5g plan v2 §1.1 HIGH-003 で正当化)
- BL-0126 (research eval + `citation_coverage` AC-KPI-04 / claim-level + final-adopted artifact filter、batch 5d / PR #31)
- BL-0127 (Hard Gates 7 fixture registry / loader 統合、本 Sprint で核 fixture registry 達成、Sprint 12 で個別 verify 完遂)
- BL-0128 (cost eval + `cost_per_completed_task` AC-KPI-05、batch 5e / PR #32)
- BL-0129 (Anti-Gaming Rules dataset metadata enforcement、commit author / timestamp inversion 検出)
- BL-0130 (nightly regression job、batch 5i / PR #38、`cron '0 3 * * *'` public_regression + Gold Task v0 contract)
- BL-0158 (`tenant_isolation_negative_pass` fixture loader、AC-HARD-03)
- BL-0159 (`backup_restore_rpo_rto` fixture skeleton、AC-HARD-04、batch 5j / PR #37、SUT activation は Sprint 11.5 BL-0159b)
- BL-0163 (Gold Task Seed v0 → 30 cases、batch 5h / PR #36、50 件は SP-022 へ defer)

#### 追加 AC-KPI aggregator (Sprint 11 main scope 完遂、line 188 全 5/5 達成)
- AC-KPI-03 `approval_wait_ms` aggregator (batch 5h-pre / PR #35)

**AC-KPI 5/5 達成 (line 188)**:

| KPI | aggregator file | merged PR |
|---|---|---|
| AC-KPI-01 acceptance_pass_rate | `backend/app/services/eval/kpis/acceptance_pass_rate.py` | #33 (batch 5f) |
| AC-KPI-02 time_to_merge | `backend/app/services/eval/kpis/time_to_merge.py` | #34 (batch 5g) |
| AC-KPI-03 approval_wait_ms | `backend/app/services/eval/kpis/approval_wait_ms.py` | #35 (batch 5h-pre) |
| AC-KPI-04 citation_coverage | `backend/app/services/eval/kpis/citation_coverage.py` | #31 (batch 5d) |
| AC-KPI-05 cost_per_completed_task | `backend/app/services/eval/kpis/cost_per_completed_task.py` | #32 (batch 5e) |

**AC-HARD 7/7 fixture registry / loader 経由で測定可能 (line 186)**:

| Hard Gate | fixture source | source Sprint |
|---|---|---|
| AC-HARD-01 policy_block_recall | `eval/security/policy_block/` + loader (`tests/eval/test_policy_block_loader.py`) | Sprint 4 BL-0041 + Sprint 11 BL-0127 統合 |
| AC-HARD-02 secret_canary_no_leak | `eval/security/secret_canary/` + loader + DOM secret scan (BL-0107b) | Sprint 5 BL-0078 + Sprint 11 BL-0107b 統合 |
| AC-HARD-03 tenant_isolation_negative_pass | `eval/security/tenant_isolation/` + loader (`tests/eval/test_hard_gates_tenant_isolation.py`) | **Sprint 11 BL-0158** |
| AC-HARD-04 backup_restore_rpo_rto | `eval/ops/backup_restore/` + skeleton aggregator (`backend/app/services/eval/hard_gates/backup_restore.py`) | **Sprint 11 BL-0159 (skeleton)**、activation は Sprint 11.5 BL-0159b (PITR + 3 drill_kinds 拡張、ADR-00022 候補) |
| AC-HARD-05 forbidden_path_block | `eval/security/forbidden_path/` (Sprint 7 で fixture skeleton 設置済、`private_holdout/adversarial_new/` は README のみ) | Sprint 7 (skeleton)、**BL-0080a (private_holdout/adversarial_new 各 10+ 件拡充) は Sprint 12 へ defer** |
| AC-HARD-06 dangerous_command_block | `eval/security/dangerous_command/` (Sprint 7 で fixture skeleton 設置済、`private_holdout/adversarial_new/` は README のみ) | Sprint 7 (skeleton)、**BL-0081a (private_holdout/adversarial_new 各 10+ 件拡充) は Sprint 12 へ defer** |
| AC-HARD-07 prompt_injection_resist | `eval/security/prompt_injection/` (Sprint 5 BL-0083) | Sprint 5 |

**最終 verify (host migration drill / private staging CI/E2E 含む) は Sprint 12 で個別 verification**。

**Anti-Gaming Rules 防御 4 layer (BL-0129)**:
1. Loader sanitize (raw secret pattern detection、Sprint 11 batch 5b 確立)
2. dataset_version pinning + sha256 anti-gaming guard
3. pytest `-q --tb=short` 集約出力 (個別 fixture 期待値の test stdout 非 export)
4. fixture creation commit と policy / runner / prompt 修正 commit を **別 author / 別 timestamp** で分離 (BL-0129 CI gate)

**nightly regression visibility (BL-0130 / batch 5i / PR #38)**:
- `.github/workflows/nightly-regression.yml`: cron '0 3 * * *' で public_regression + Gold Task v0 contract を main 限定で自動実行
- `.github/workflows/ci-smoke.yml workflow-lint` job 追加: `.github/workflows/**` 全件を PR 時点で actionlint syntax check
- private_holdout monthly decryption + failure notification は Sprint 11.5 / SP-022 へ defer

#### Deferred 移送

| 項目 | 移送先 | 理由 |
|---|---|---|
| **BL-0079a** (runner_cancelled / runner_cleanup_completed event_type 拡張) | **Sprint 12** | event_type.py に未追加、Codex F-PR39-004 で発覚 |
| **BL-0080a** (AC-HARD-05 private_holdout/adversarial_new 各 10+ 件拡充) | **Sprint 12** | README 状態、fixture body 未実装、Codex F-PR39-004 で発覚 |
| **BL-0081a** (AC-HARD-06 private_holdout/adversarial_new 各 10+ 件拡充) | **Sprint 12** | README 状態、fixture body 未実装、Codex F-PR39-004 で発覚 |
| **BL-0096a** (RepoProxy 4 整合 binding signature refactor) | **Sprint 12** | repoproxy.py に comment のみ、signature 未 refactor、Codex F-PR39-002 で発覚 |
| **BL-0100** (repo_pr_opened actual emission) | **SP-008 follow-up completed at service boundary 2026-05-24** | event writer + DB append test + `DraftPRRuntime` call-site wrapper 追加済。real GitHub transport 有効化後の外部 API/worker adoption は残存 |
| **BL-0102 endpoint** (`/api/v1/agent_runs/{run_id}/kpi` time_to_merge exposure) | **SP-008 follow-up completed 2026-05-24** | per-run KPI endpoint + service + API/DB tests 追加済。true PR merged timestamp source は future event として残るが、P0 proxy source は明示済 |
| **BL-0103a** (`GET /api/v1/tickets` list+detail) | **Sprint 12** | backend/app/api/tickets.py 不在、Codex F-PR39-004 で発覚 |
| **BL-0106a** (`GET /api/v1/agent_runs` list+detail) | **Sprint 12** | cancel のみ実装、list/detail 不在、Codex F-PR39-004 で発覚 |
| **BL-0107a** (`GET /api/v1/audit_events` route) | **Sprint 12** | backend/app/api/audit_events.py 不在、Codex F-PR39-004 で発覚 |
| **BL-0107b** (RedactedAuditPayloadSchema + DOM secret scan) | **Sprint 12** | frontend schema 不在、AC-HARD-02 enforcement 未着手、Codex F-PR39-003 で発覚 |
| **BL-EnumDrift** (3 source enum drift detection contract test) | **Sprint 12** | tests/contracts/test_frontend_backend_enum_drift*.py 不在、Codex F-PR39-003 で発覚 |
| BL-0125 (coding / review eval suites) | **SP-022 framework intake hardening** | Sprint 5.5 Output Validator + BL-0090 dependency 未解決、本 Sprint で時間不足、batch 5g plan v2 §1.1 HIGH-003 で正当化 |
| BL-0163 Gold Task 50 件拡張 | **SP-022** | 本 Sprint 30 件達成、20 件は monthly refresh schedule で追加 |
| BL-0159b PITR + 3 drill_kinds activation | **Sprint 11.5 (Operational Hardening)** | ADR-00022 候補 (PITR adoption) 起票必要 (ADR Gate Criteria #8 破壊的操作 / #6 secrets) |
| ADR-00011 (GitHub App Permission Matrix) accepted 昇格 | **Sprint 11.5 BL-Permission-CLI 完遂後** | 本 Sprint で 7/8 unblock review 完了、frontmatter `proposed` 維持 (Codex R1 F-R1-004 + R2 F-R2-001 adopt) |
| private_holdout monthly decryption schedule | **Sprint 11.5 / SP-022** | age key + Tailscale GitHub Action 必要、ADR Gate Criteria #6 secrets |
| Failure notification (Slack / Discord / MoltBot) | **Sprint 11.5** | MoltBot / Webhook integration、ADR Gate Criteria #4/#5 |
| `pytest.mark.no_leak` marker (preventive) | **Sprint 11.5** | future batch で fixture 期待値 export test 導入時の guard |
| BL-0163 50 件拡張時の timeout 見直し | **Sprint 11.5 / 12** | nightly cron 頻度緩和 or split job 化判断 |
| 自動再分解 / shadow mode / leaderboard | **P1** | Sprint Pack must_ship × 明示 |
| Grafana / Loki integration | **Sprint 11.5** | observability stack 本格化 |

#### 関連 Sprint Pack status 昇格

- **SP-008 `partial_skeleton` 維持** (Codex F-PR39-002 adopt): 2026-05-24 follow-up で BL-0096a / BL-0101a / BL-0100 / BL-0102 は service-boundary / endpoint level まで前進。real GitHub transport、live Git ref re-fetch、deployment SOPS material resolver、external API/worker adoption が残るため `done` 昇格は時期尚早
- **SP-009 `partial_skeleton` 維持** (2026-05-24 status hygiene): #224/#225 で backend route reconciliation、frontend raw-payload schema guards、backend/frontend enum drift contract tests が追加済。golden E2E、DOM secret scan、PayloadDataClass/future AuditEventType registry drift、SP-009-5 split が残るため `done` 昇格は時期尚早
- **SP-011 `draft` → `completed`** (Eval Harness 本来 scope 12 BL + carry-over 完遂 5 BL = 16 BL scope に縮減): 本 Sprint Exit

#### Risks (residual)

- **Sprint 7-9 carry-over status**: 2026-05-24 follow-up で SP-008/009/007 は複数 service-boundary / contract-test / helper-code PR まで前進したが、external GitHub transport と machine-local hook trust-root install は残存。Sprint 12 完遂後または approval-gated operator step 完了後に再度 status 昇格 review 実施
- **ADR-00011 acceptance pending**: 7/8 unblock review 完了、最終 1 件 (BL-Permission-CLI) は Sprint 11.5 で完成、本 frontmatter `proposed` 維持。Sprint 11.5 Exit で accepted 昇格予定
- **GitHub Actions CI billing infrastructure issue**: 本 Sprint 後半 (batch 5j / batch 5i merge 時) で全 job 1-3 秒即 fail 症状、user-side platform issue (code quality 問題なし)。Sprint 11 内で local pytest / actionlint / ruff / mypy で同等 verification 実施済、Sprint 12 着手前に CI billing 復旧 verify 必要
- **AC-HARD-04 SUT activation Sprint 11.5 依存**: 本 Sprint は fixture contract skeleton のみ、実 PITR drill は Sprint 11.5 BL-0159b で実施 (ADR-00022 候補 accepted 必要)
- **private_holdout 期待値漏えい**: SOPS + age 経由復号で grep 隠蔽 + loader sanitize 4 layer 防御済、Sprint 12 final audit で再 verify

#### 次 Sprint handoff

- **Sprint 11.5 (Operational Hardening)**: Permission Matrix CLI (BL-Permission-CLI) + Observability (OTel + Prometheus + Loki + Grafana) + secret rotation drill + `backup_restore_rpo_rto` SUT activation (BL-0159b、PITR + 3 drill_kinds + ADR-00022 起票) + private_holdout monthly decryption schedule + failure notification + `pytest.mark.no_leak` marker
- **Sprint 12 (P0 Acceptance)**: Sprint 11 carry-over residual (2026-05-24 follow-up 後は BL-0102 endpoint を除外) + Hard Gates 7 + KPIs 5 final verify + host migration drill (Mac/Linux/VPS) + backup/restore drill (RPO ≤24h / RTO ≤4h) + private staging CI/E2E + GitHub Actions CI billing 復旧 verify
- **SP-022 (Framework Intake Hardening)**: BL-0125 coding/review eval suites + BL-0163 Gold Task 50 件拡張 + framework adoption checklist 8 項目 verify

(SP-011 完了時に追記)

### QL-C 拡充 spec landing 記録 (R29 §5 QL-C run、2026-05-15)

- **QL-C run branch**: `quality-loop/QL-C-research-eval-pack` (PR #11、quality-loop/QL-C-research-eval-pack)
- **拡充内容**: P-09 (Pack reuse + alias 整理) + P-18 (Evidence/RAG/Eval metrics acceptance spec) を本 Pack `## 受け入れ条件` に追記
- **doc-only scope** (R29 §5 QL-C verification): no test file / no code change / no DB schema / no migration、acceptance spec のみ
- **既存 27 BL trace 維持**: 本 QL-C 拡充は BL-0079a〜BL-0130 の既存 trace を破壊しない
- **cross-ref**: SP-010 で source schema (SearchRun / EvidenceSearchHit / GroundingSupport / RetrievalEvalRun) を同 PR で追記、SP-011 は集計責務のみ

### Sprint 11 batch 5a 実装進捗

- **batch_5a_implementation_pr**: 本 PR
- **実装 BL**: BL-0122 (`dataset_versions` / `eval_runs` / `eval_cases` / `eval_scores` 4 tables + ORM models + fixture loader service) + BL-0123 (split directory + Anti-Gaming metadata enforcement integration) + BL-0129 (Anti-Gaming Rules dataset metadata enforcement CI gate)
- **新規 file**:
  - `migrations/versions/0018_eval_dataset_versions.py` (4 table 新規作成 + 4 index、複合 FK 3 column enforcement)
  - `backend/app/db/models/{dataset_version,eval_run,eval_case,eval_score}.py` (4 ORM model + FixtureKind Literal + STANDARD_FIXTURE_KINDS frozenset)
  - `backend/app/services/eval/{__init__,loader,anti_gaming}.py` (DB sync loader + Anti-Gaming CI gate helper)
  - `tests/db/test_eval_schema_enum.py` (5+ source 整合 test for `fixture_kind` enum)
  - `tests/db/test_eval_schema_migration.py` (Alembic upgrade/downgrade + cross-tenant FK boundary + 複合 FK enforcement)
  - `tests/eval/test_eval_loader.py` (happy path + tamper detection + spoofed fixture_kind + raw secret scan + duplicate version reject)
  - `tests/eval/test_anti_gaming.py` (author inversion + timestamp inversion + subprocess mock)
- **修正 file**:
  - `backend/app/db/models/__init__.py` (4 新 model + FixtureKind + STANDARD_FIXTURE_KINDS 追加)
- **5+ source 整合**: DB CHECK + ORM CheckConstraint + Python Literal + frozenset + pytest EXPECTED constants
- **既存 batch (Sprint 1-10) invariant 維持**: AgentRun 16 状態 / ContextSnapshot 10 列 / SecretBroker / Approval 4 整合 / RFC 8785 / Research/Evidence schema / Sprint 10 cross-tenant fixtures
- **PR #28 Codex R1 review (R1 / 5 inline findings)**:
  - **F-PR28-R1-001 P1 adopt**: `dataset_versions` の unique key を `(tenant_id, dataset_key, version, fixture_kind)` に拡張。spec の "1 dataset version は 3 splits (public/private/adversarial) を持ち得る" 要件を DB enforce。migration 0018 + ORM `__table_args__` + test expected + DD-02 §dataset_versions cross-ref を同期更新。
  - **F-PR28-R1-002 P2 defer → Sprint 11 BL-0127**: 現 loader の hard-coded `_REQUIRED_FIXTURE_KEYS` は tenant_isolation 特化、他 Hard Gate / KPI fixtures (policy_block / secret_canary / citation_coverage 等) は異 expected_* field を使う。schema-driven required keys の generic 化は **Sprint 11 BL-0127 (Hard Gates 7 fixture registry / loader 統合)** で実装。本 batch 5a の scope は tenant_isolation 専用。
  - **F-PR28-R1-003 P2 adopt**: `_RAW_SECRET_KEY_NAMES` から `"value"` を削除。`threshold.value` 等の generic KPI field を spurious reject していた。defense-in-depth は引き続き `_RAW_SECRET_VALUE_PATTERNS` (sk-/ghp_/AKIA prefix) で確保。
  - **F-PR28-R1-004 P2 adopt**: `verify_fixture_commit_separation()` の timestamp_inversion を再設計。**latest policy commit per path** vs fixture creation の比較に変更、direction を spec の "fixture 作成後に policy を緩めた疑い" align (policy_commit > fixture_commit AND policy_lag ≤ window)。旧 ordinary policy history vs new fixture の false positive を除去、`test_verify_fixture_commit_separation_ignores_old_policy_history` で regression 防止。
  - **F-PR28-R1-005 P2 adopt**: redacted splits (private_holdout / adversarial_new) の prohibited keys を `"expected_*"` prefix + `"assertions"` 全部 reject に拡張。他 corpora の `expected_block` / `expected_aggregate` / `expected_pattern_hit_kind` 等の漏えいも fail-closed で防御。
- **PR #28 Codex R3 review (R3 / 6 new inline findings 累計 11)**:
  - **F-PR28-R3-001 P1 adopt**: `sync_dataset_version_to_db` の pre-insert SELECT lookup が R1-001 の新 unique key `(tenant_id, dataset_key, version, fixture_kind)` と不一致だったため、SELECT に `fixture_kind` を追加。複数 split を同 version で順次 sync 可能に。
  - **F-PR28-R3-002 P1 adopt (R1-002 P2 escalation 対応)**: tenant_isolation-specific な `_PUBLIC_EXPECTED_KEYS` を generic な `_is_expectation_key()` 述語 (expected_* prefix + `_KNOWN_NON_PREFIXED_EXPECTATION_KEYS={"pattern_hit_kind","assertions"}`) に置換。`_REQUIRED_PUBLIC_FIXTURE_KEYS` から TI-specific keys を削除、per-corpus required は `expected_schema.json` (jsonschema Draft 7 required) で enforce。他 Hard Gate / KPI corpora (policy_block / secret_canary / citation_coverage / cost_per_completed_task) でも `expected_aggregate` / `expected_pattern_hit_kind` 等の dataset-specific expectation keys を generic に case_json / expected_json split に振り分け可能。
  - **F-PR28-R3-003 P1 partial adopt**: `tests/eval/test_anti_gaming_ci_gate.py` を新規追加、real-git による `verify_fixture_commit_separation` invocation を pytest 経由で実行可能に。`TASKMANAGEDAI_RUN_ANTI_GAMING_GATE=1` 環境変数で opt-in (P0 期間中は単一作者 = `t-ohga` のため `author_inversion` が常時 fire する制約を doc 化)。multi-actor scenario (Sprint 11.5+ multi-agent orchestration) で常時 ON 化予定。
  - **F-PR28-R3-004 P2 defer → Sprint 11 BL-0127**: 既存 corpora (`eval/security/{prompt_injection,dangerous_command,forbidden_path}`、`eval/ops/backup_restore`) の `fixture_immutable_index` backfill + `require_immutable_index=False` opt-in flag は BL-0127 generic loader integration で実装。本 batch 5a の tenant_isolation 対象 corpus は immutable_index 完備済。
  - **F-PR28-R3-005 P2 adopt**: `eval_runs` table に新 composite unique key `(tenant_id, id, run_id)` を追加 (`eval_runs_uq_tenant_id_run`)。SP-010 QL-C cross-ref の RetrievalEvalRun spec で必要となる 3-column composite FK `(tenant_id, eval_run_id, agent_run_id) references eval_runs(tenant_id, id, run_id)` の forward-compat 確保。
  - **F-PR28-R3-006 P2 adopt**: `GitCommit` に `author_email: str` field 追加、`author_identity` property で安定的 contributor 識別を実現。`%H%x1f%an%x1f%ae%x1f%ct` git format に拡張、author_inversion の比較は `author_identity` ベース。同名別 author の誤検出 + author name 変更によるバイパスを防御。
- **PR #28 Codex R4 review (R4 / 5 new inline findings 累計 16)**:
  - **F-PR28-R4-001 P1 defer → Sprint 11 BL-0127**: `eval/quality/citation_coverage` 等の corpora は `expected_schema.json` で **non-prefixed expectation key** (`threshold` 等) を required 化している。現 `_is_expectation_key()` 述語は `expected_*` prefix + 既知非 prefix set のみ recognise するため、これらは case_json に混入し expected_json から落ちる。**schema-driven expectation extraction** (manifest-level `expectation_keys` override or schema.properties metadata 駆動) は本 batch 5a scope (tenant_isolation only) 外、generic loader integration BL-0127 で対応。
  - **F-PR28-R4-002 P2 adopt**: R3-006 で導入した `author_identity` を `author<email>` → **email alone** に refine。Git ``user.name`` 変更だけで author_inversion バイパス可能だった脆弱性を fix (`author_email` が空の場合のみ `author` にフォールバック)。
  - **F-PR28-R4-003 P1 defer → Sprint 11 BL-0127**: 既存 KPI corpora (`approval_wait_ms` / `citation_coverage` / `cost_per_completed_task`) は `kpi_id` field を使い `gate_id` を持たない。`_REQUIRED_FIXTURE_KEYS` は `gate_id` を必須化しているため、これらの corpora は本 loader で sync 不可。**`gate_id` ↔ `kpi_id` either-or required** は BL-0127 の generic loader integration で対応。
  - **F-PR28-R4-004 P1 adopt**: `_manifest_version()` で `dataset_version_id: null` (JSON explicit null) を fallback target にできていなかった bug を fix。`dict.get(key, default)` は key が存在し値が null の場合 default を返さないため、明示的に isinstance check + 空チェックを行い legacy `dataset_version` field に fallback。
  - **F-PR28-R4-005 P2 defer → Sprint 11 BL-0127**: `tests/eval/test_anti_gaming_ci_gate.py` の real-git CI gate が現状 `policy` + `runner` paths のみ scan、prompt construction code (`backend/app/services/output_validator/repair_prompt_builder.py` / `backend/app/services/policy_pack`) を含めていない。本 gate は P0 期間中 opt-in、policy_paths extension は BL-0127 の CI gate 本格化で対応。
- **PR #28 Codex R5 review (R5 / 5 new inline findings 累計 21、全 P2 in-scope defense improvements)**:
  - **F-PR28-R5-001 P2 adopt**: `_assert_index_split_consistency()` で malformed `fixture_immutable_index` entry を silently omit していたため、削除/改竄検出能力が弱まる可能性 (entry を non-object に書き換えれば missing_files から外れる)。malformed entry / invalid split / 不正 fixture_id を up-front で reject、append-only immutable index の tamper detection invariant を強化。
  - **F-PR28-R5-002 P2 adopt**: `_fixture_paths_for_split()` が `*.json` glob の結果を symlink check なしに返していたため、corpus 外の file を fixture source として読み込む経路が存在。split_dir + 各 fixture file に対し `is_symlink()` reject + `is_file()` 確認を追加、`source_path` provenance bypass を防御。
  - **F-PR28-R5-003 P2 adopt**: redacted splits (private_holdout / adversarial_new) は `expected_schema.json` validation を完全に skip していたため、`input` field が任意の string/object shape で persist 可能。新 `_validate_redacted_input_schema()` で `schema.properties.input` (定義されている場合) を抽出し input field 単独で Draft 7 validation。expectation 部分は引き続き validation 外 (holdout expectations は external vault)。
  - **F-PR28-R5-004 P2 adopt**: `author_identity` property に email casing + whitespace normalization 追加 (`strip().lower()`)。`User@Example.com` ↔ `user@example.com` の casing 変更で `author_inversion` を bypass されないように R4-002 を強化。
  - **F-PR28-R5-005 P2 adopt**: `tests/eval/test_anti_gaming_ci_gate.py` の real-git gate が `public_regression` のみ glob していたため、`private_holdout` / `adversarial_new` (expectation leakage が最も sensitive な split) を未 scan。`_FIXTURE_SPLIT_ROOTS` に 3 split 全部含めて glob 統一。
- **PR #28 Codex R6 review (R6 / 5 new inline findings 累計 26、3 ADOPT + 2 DEFER)**:
  - **F-PR28-R6-001 P2 defer → Sprint 11 BL-0127**: real-git CI gate が `eval/security/tenant_isolation` のみ scan、他 corpora (`eval/security/policy_block`, `eval/security/secret_canary`, `eval/quality/*`, `eval/ops/*`) は未 cover。本 batch 5a scope = tenant_isolation only、他 corpora の gate 統合は BL-0127 generic loader integration で対応。
  - **F-PR28-R6-002 P2 adopt**: `verify_fixture_commit_separation` の timestamp_inversion を **latest policy commit only** から **window 内の全 post-fixture policy commit を scan** に変更。最新 policy commit が window 外であっても、過去に window 内で suspicious relaxation があれば検出可能に。
  - **F-PR28-R6-003 P2 adopt (partial)**: `_POLICY_PATHS` に `backend/app/services/output_validator` + `backend/app/domain/policy` 追加。BL-0129 の "policy / runner / prompt construction code を分離" invariant を P0 で実現可能な範囲で拡大、registry-driven enumeration は BL-0127 で対応。
  - **F-PR28-R6-004 P2 adopt**: R5-002 (fixture file symlink reject) follow-up、`_read_json_object()` で **manifest.json + expected_schema.json も symlink reject**。`Path.is_file()` は symlink を follow するため、manifest が symlink で repo 外 file を指していたら provenance bypass された。全 JSON file 共通の symlink check に統一。
  - **F-PR28-R6-005 P2 defer → Sprint 11 BL-0127**: `tests/eval/test_anti_gaming_ci_gate.py` の `TASKMANAGEDAI_RUN_ANTI_GAMING_GATE=1` opt-in 化は **P0 期間中 single-author (`t-ohga` のみ)** の制約による意図的な設計 (author_inversion 常時 fire 回避)。CI workflow への wire-in は multi-actor scenario (Sprint 11.5+ multi-agent orchestration) で BL-0127 経由実施。

### Sprint 11 batch 5b 実装進捗 (PR #?? merge 後に commit hash 追記)

- **batch_5b_implementation_pr**: 本 PR (BL-0158 AC-HARD-03 aggregator + tenant_isolation fixture loader integration)
- **実装 BL**: BL-0158 (tenant_isolation_negative_pass fixture loader を Eval Harness Hard Gate aggregator に接続)
- **新規 file**:
  - `backend/app/services/eval/hard_gates/__init__.py`
  - `backend/app/services/eval/hard_gates/tenant_isolation.py` (~250 LOC、AC_HARD_03_* constants + TenantIsolationFixtureResult + TenantIsolationMetricResult + evaluate_tenant_isolation_negative_pass())
  - `tests/eval/test_hard_gates_tenant_isolation.py` (~300 LOC、5+ source enum integrity + 13+ test cases including 17-fixture happy path / sut_results integration / spec violation detection / edge cases / raw secret non-leakage)
- **5+ source 整合 (AC_HARD_03_* enum)**: Python Literal + Final constants + module-level `__all__` export + pytest EXPECTED constants + 実 fixture (17 件 raw_json) 内の値 cross-check
- **forward-compat for BL-0127 SUT integration**: `sut_results: Mapping[str, bool] | None = None` optional parameter で programmatic SUT 実行結果を注入可能、batch 5b では spec compliance のみで metric 計算
- **server-owned boundary §1+§3 invariants 維持**: loader-validated corpus only、caller-supplied path 経路なし、pure function (side effect なし)、raw secret 非展開 (reason_code + fixture_id のみ)
- **既存 batch 1-10 + batch 5a invariant 維持**: AgentRun 16 状態 / ContextSnapshot 10 列 / SecretBroker / Approval 4 整合 / RFC 8785 / Research/Evidence schema / fixture loader / Anti-Gaming CI gate

### Sprint 11 batch 5c 実装進捗 (PR #?? merge 後に commit hash 追記)

- **batch_5c_implementation_pr**: 本 PR (BL-0127a generic loader expansion)
- **実装 BL**: BL-0127a (PR #28 R1-R6 defer 4 finding 中 core 3 解消、全 10 eval corpora load 可能化)
- **修正 file**:
  - `backend/app/services/eval/loader.py` (gate_id ↔ kpi_id either-or required + manifest-level expectation_keys override + optional fixture_immutable_index with WARN)
- **新規 file**:
  - `tests/eval/test_eval_loader_generic.py` (~400 LOC、10 corpora load + kpi_id acceptance + expectation_keys override + immutable_index optional)
- **PR #28 R1-R6 defer 解消**:
  - F-PR28-R4-003 P1 (kpi_id either-or): ADOPT
  - F-PR28-R4-001 P1 (non-prefix expectation): ADOPT (manifest expectation_keys override)
  - F-PR28-R3-004 P2 (immutable_index backfill): ADOPT (warn instead of fail)
  - F-PR28-R1-002/R3-002 escalation P1 (`_REQUIRED_PUBLIC_FIXTURE_KEYS` TI-specific): ADOPT (gate_id removal + kpi_id support 経由 generic 化)
- **BL-0127b に残 defer** (本 batch 対象外):
  - F-PR28-R4-005/R6-003/R6-005 (prompt paths registry / CI wire-in / opt-in env var の workflow 統合)
  - F-PR28-R6-001 (CI gate が他 corpora を scan する registry)
- **5+ source 整合維持**: `_KNOWN_NON_PREFIXED_EXPECTATION_KEYS` + `_VALID_EXPECTATION_KEY_PATTERN`
- **既存 batch 1-10 + batch 5a/5b invariant 維持**: ContextSnapshot 10 列 / AgentRun 16 状態 / SecretBroker / Approval 4 整合 / RFC 8785 / batch 5a loader (gate_id removal は backwards-compat) / batch 5b aggregator

### Sprint 11 batch 5d 実装進捗 (PR #?? merge 後に commit hash 追記)

- **batch_5d_implementation_pr**: 本 PR (BL-0126 AC-KPI-04 citation_coverage aggregator)
- **実装 BL**: BL-0126 (research eval suite + citation_coverage 判定、batch 5c generic loader 上に構築)
- **新規 file**:
  - `backend/app/services/eval/kpis/__init__.py`
  - `backend/app/services/eval/kpis/citation_coverage.py` (~290 LOC、AC_KPI_04_* constants + ClaimCoverageEntry + CitationCoverageFixtureResult + CitationCoverageMetricResult + evaluate_citation_coverage)
  - `tests/eval/test_kpis_citation_coverage.py` (~640 LOC、40 test cases including 5+ source enum cross-check + happy path against live corpus + manifest drift × 6 + spec violations × 11 + edge cases + sut_results integration × 9 + Anti-Gaming raw-content non-leakage + frozen dataclass + weighted average correctness)
- **実装手法**: 新 workflow に従い **Claude が直接実装** (Codex は計画 review 用、本 batch では Codex の draft output を design reference として使用後、Claude が Write tool で書き起こし)
- **Anti-Gaming invariant**: manifest `anti_gaming_rules.kpi_specific[0]` "citation_coverage is recomputed from input.sample_claims, not copied from expected_aggregate" を厳格遵守。recomputed_coverage_ratio が canonical、expected_aggregate.coverage_ratio は drift-detection oracle としてのみ使用 (`math.isclose(rel_tol=1e-6, abs_tol=1e-9)` を超える drift → `spec_violation:expected_aggregate_drift`、F-CR-003 P1 + F-PR31-R3-002 P3 adopt: 固定 1e-9 では float64 round-trip noise の安全 margin を割るため緩和)。`expected_aggregate.total_claims` / `claims_with_citation` は **strict `int` instance 必須** + recomputed と exact 一致 (F-PR31-R1-002 + R2-003 P2 adopt)。
- **server-owned boundary §1+§3**: caller-supplied `list[Fixture]` 直接受け取り signature なし、sut_results は read-only `Mapping[str, bool] | None`、pure function (DB / file system / network access なし)
- **5+ source enum integrity**: 4 AC_KPI_04_* constants (KPI_ID / METRIC_KEY / THRESHOLD / THRESHOLD_OPERATOR) が Python Literal + Final + `__all__` export + pytest EXPECTED constants + 実 manifest values + 実 fixture envelope の 5 source で exact set 比較
- **BL-0127b / SP-012 forward-compat**: optional `sut_results: Mapping[str, bool] | None` parameter で programmatic SUT 実行結果を注入可能、batch 5d では spec compliance + Anti-Gaming recomputation で metric 計算
- **redacted splits skip**: `_SUPPORTED_FIXTURE_KINDS=("public_regression",)` 限定、private_holdout / adversarial_new は SP-022+ で encrypted-holdout decryption path 追加後に対応
- **threshold semantics**: AC_KPI_04_THRESHOLD=0.9、AC_KPI_04_THRESHOLD_OPERATOR=">="、threshold_met=True iff `metric_value >= 0.9 AND fixture_count > 0 AND spec_violation 0 AND manifest_violation None AND sut_failure_present=False`。F-PR31-R1-001 + R2-001 + R3-003 P2 adopt: SUT failure (`sut_result_missing` / `sut_result_invalid_type` / `sut_result_false`) を threshold_reason に反映、`threshold_reason ∈ {no_fixtures, manifest_violation, spec_violation, sut_failure, threshold_met, below_threshold}` 優先順序で priority enforcement。`CitationCoverageFixtureResult` には spec / SUT 失敗を physically 分離した **`spec_violation_reason` + `sut_failure_reason`** 2 field を持たせ、downstream consumer の dashboard が SUT 障害を fixture spec defect に誤分類する経路を遮断 (F-PR31-R3-001 P2 adopt)。
- **既存 batch 1-10 + batch 5a/5b/5c invariant 維持**: ContextSnapshot 10 列 / AgentRun 16 状態 / SecretBroker / Approval 4 整合 / RFC 8785 / batch 5a loader / batch 5b tenant_isolation aggregator / batch 5c generic loader

### Sprint 11 batch 5e 実装進捗 (PR #?? merge 後に commit hash 追記)

- **batch_5e_implementation_pr**: 本 PR (BL-0128 AC-KPI-05 cost_per_completed_task aggregator)
- **実装 BL**: BL-0128 (cost eval suite + cost_per_completed_task aggregator、batch 5d patterns 拡張)
- **新規 file**:
  - `backend/app/services/eval/kpis/cost_per_completed_task.py` (~480 LOC、AC_KPI_05_* constants + SampleRun + CostPerCompletedTaskFixtureResult + CostPerCompletedTaskMetricResult + evaluate_cost_per_completed_task)
  - `tests/eval/test_kpis_cost_per_completed_task.py` (~720 LOC、64 test cases including 5+ source enum + happy path (live 5 runs / 3 completed / $0.6 / $0.2 per task) + Anti-Gaming completed-only filter × 1 + manifest drift × 7 + spec violations × 18 + edge cases × 4 + sut_results × 6 + raw content non-leakage)
- **実装手法**: Claude が Write tool で直接実装 (新 workflow、Codex は plan-review / code-review に専念)
- **Anti-Gaming invariants** (manifest kpi_specific):
  1. `cost_per_completed_task is calculated from normalized provider usage after BudgetGuard accounting` — aggregator が canonical recomputed metric を生成、expected_aggregate.cost_per_completed_task_usd は drift-detection oracle のみ
  2. `only AgentRun status=completed contributes to numerator and denominator` — failed / cancelled / refused / repair-exhausted / non-terminal runs を numerator + denominator から filter out。完全 AgentRun 16 状態 enum (_KNOWN_AGENT_RUN_STATUSES) で status validation、unknown status は spec_violation:status で fail-closed
- **server-owned boundary §1+§3**: caller-supplied `list[Fixture]` 直接受け取り signature なし、sut_results は read-only Mapping、pure function (DB / file system / network access なし)
- **5+ source enum integrity**: 4 AC_KPI_05_* constants (KPI_ID / METRIC_KEY / THRESHOLD_USD / CURRENCY) が Python Literal + Final + `__all__` export + pytest EXPECTED constants + 実 manifest values + 実 fixture envelope の 5 source で exact set 比較
- **BL-0127b / SP-012 forward-compat**: optional `sut_results: Mapping[str, bool] | None` parameter、batch 5d patterns 継承 (sut_failure_reason 分離 / spec_violation skip SUT / non-boolean strict reject / stale fixture_id warn log)
- **redacted splits skip**: `_SUPPORTED_FIXTURE_KINDS=("public_regression",)` 限定、private_holdout / adversarial_new は SP-022+ で encrypted-holdout decryption path 追加後に対応
- **threshold semantics**: AC_KPI_05_THRESHOLD_USD=0.5、AC_KPI_05_CURRENCY="USD"、**LOWER is better** ("<=" operator)。threshold_met=True iff `metric_value <= 0.5 AND fixture_count > 0 AND total_completed_runs_across_corpus > 0 AND spec_violation 0 AND manifest_violation None AND sut_failure_present=False`。`threshold_reason ∈ {no_fixtures, manifest_violation, spec_violation, sut_failure, no_completed_runs, threshold_met, above_threshold}` 優先順序で priority enforcement。新 `no_completed_runs` reason は corpus に completed AgentRun が 1 件もない場合 (KPI 未定義) — failed / cancelled fixtures のみの corpus を threshold pass 扱いしない fail-closed
- **per-run structural validation**: run_id (RFC 4122 lowercase UUID v1-5 + RFC variant nibble + UUID() parseability)、tenant_id (non-bool int >= 1)、project_id (non-bool int >= 1、F-PR32-R1-004 + R2-002 P3 adopt: schema minimum 1 と整合)、status (AgentRun 16 状態 enum)、cost_usd (non-bool finite float >= 0.0)、tokens_input + tokens_output (non-bool int >= 0、F-PR32-R2-001 P2 adopt) を strict 検査。`sample_runs` 自体は `minItems=1` を要求 (F-PR32-R2-003 P2 adopt)。
- **expected_aggregate drift detection**: total_completed_runs / total_cost_usd / cost_per_completed_task_usd / threshold_usd / threshold_passed の 5 field 全てを recomputed と一致を要求 (5 reason_code: expected_aggregate_{completed_drift,total_cost_drift,ratio_drift,threshold_drift,passed_drift})
- **既存 batch 1-10 + batch 5a〜5d invariant 維持**: ContextSnapshot 10 列 / AgentRun 16 状態 / SecretBroker / Approval 4 整合 / RFC 8785 / batch 5a loader / batch 5b tenant_isolation aggregator / batch 5c generic loader / batch 5d citation_coverage aggregator

### Sprint 11 batch 5f 実装進捗 (PR #?? merge 後に commit hash 追記)

- **batch_5f_implementation_pr**: 本 PR (BL-0124 AC-KPI-01 acceptance_pass_rate aggregator)
- **実装 BL**: BL-0124 (decomposition eval suite + acceptance_pass_rate aggregator、batch 5d / 5e patterns 拡張)
- **新規 file**:
  - `backend/app/services/eval/kpis/acceptance_pass_rate.py` (~590 LOC、AC_KPI_01_* constants + SampleAcceptanceCriterion + AcceptancePassRateFixtureResult + AcceptancePassRateMetricResult + evaluate_acceptance_pass_rate)
  - `eval/quality/acceptance_pass_rate/{manifest.json, expected_schema.json, README.md, public_regression/skeleton.json, private_holdout/.gitkeep+README.md, adversarial_new/.gitkeep+README.md, __init__.py}` (live skeleton 5 criteria / 3 satisfied / 1 rejected / 1 pending → pass_rate=0.75)
  - `tests/eval/test_kpis_acceptance_pass_rate.py` (~970 LOC、66 test cases: 5+ source enum × 6 / happy path × 2 / Anti-Gaming × 4 / manifest drift × 4 / spec violations × 12 / expected_aggregate violations × 14 / edge cases × 7 / SUT integration × 5 / overflow + frozen × 2 / log warning × 1)
- **実装手法**: plan-reviewer R1 (14 finding adopt) → R2 (READY 0 finding) で plan v2 を 0 件 clean まで polish 後、Claude が Write tool で直接実装 (Codex は PR auto-review + multi-round で品質保証 phase に専念)
- **Anti-Gaming invariants** (manifest kpi_specific):
  1. `acceptance_pass_rate is recomputed from input.sample_acceptance_criteria, not copied from expected_aggregate`
  2. `only criteria with status in {satisfied, rejected} contribute to numerator and denominator` (plan v2 §2.2 / §2.2.1 候補比較 + §2.2.2 deferred 悪用への counter-defense)
  3. `pending` (yet-to-be-evaluated、no opinion) と `deferred` (explicit out-of-scope、`defer_if_over_budget` Sprint Pack pattern と semantic 一致) は分子 / 分母 両方から exclude
  4. unknown status は `spec_violation:status` で fail-closed (5+ source enum drift bypass を遮断)
- **server-owned boundary §1+§3**: caller-supplied `list[Fixture]` 直接受け取り signature なし、sut_results は read-only `Mapping[str, bool] | None`、pure function (DB / file system / network access なし)
- **5+ source enum integrity (HIGH-003 adopt)**: 4 AC_KPI_01_* constants + AcceptanceCriteriaStatus 4-element enum (Python Literal `AcceptanceCriteriaStatus`、DB CHECK constraint `acceptance_criteria_ck_status`、aggregator `_KNOWN_ACCEPTANCE_STATUSES` frozenset、pytest `EXPECTED_KNOWN_STATUSES` + `EXPECTED_PASS_NUMERATOR` + `EXPECTED_PASS_DENOMINATOR`、fixture `expected_schema.json properties.input.items.properties.status.enum`) を **exact name set 比較** で 5+ source 整合 enforce。partition invariant `_PASS_NUMERATOR_STATUSES ⊊ _PASS_DENOMINATOR_STATUSES ⊆ _KNOWN_ACCEPTANCE_STATUSES` は import 時 runtime raise でも catch (S101 回避のため `assert` ではなく `if not ...: raise RuntimeError`)
- **BL-0127b / SP-012 forward-compat**: optional `sut_results: Mapping[str, bool] | None` parameter、batch 5d/5e patterns 完全継承 (sut_failure_reason 分離 / spec_violation skip SUT / non-boolean strict reject / stale fixture_id warn log / sut_returned_false reason)
- **redacted splits skip**: `_SUPPORTED_FIXTURE_KINDS=("public_regression",)` 限定、private_holdout / adversarial_new は SP-022+ で encrypted-holdout decryption path 追加後に対応
- **threshold semantics**: AC_KPI_01_THRESHOLD=0.6、AC_KPI_01_THRESHOLD_OPERATOR=">="、**HIGHER is better**。threshold_met=True iff `metric_value >= 0.6 - epsilon AND fixture_count > 0 AND evaluated_criteria_across_corpus > 0 AND spec_violation 0 AND manifest_violation None AND sut_failure_present=False`。`threshold_reason ∈ {no_fixtures, manifest_violation, spec_violation, sut_failure, no_evaluated_criteria, threshold_met, below_threshold}` 7 priority enforcement (plan v2 §4.2.1)
- **per-row structural validation**: criterion_id / project_id / ticket_id (RFC 4122 lowercase UUID v1-5 + RFC variant + UUID() parseability)、tenant_id (non-bool int ≥ 1)、status (4-element enum)。**全 ID field は PG_UUID** (plan v2 HIGH-004: batch 5e `SampleRun.project_id: int` (synthetic fixture identifier) と異なり、AC-KPI-01 は acceptance_criteria DB schema の column 型と直接一致)
- **expected_aggregate drift detection (MEDIUM-004 adopt)**: total / evaluated / satisfied / rejected / pending / deferred + acceptance_pass_rate の 7 field 全てを recomputed と一致を要求 (8 reason_code: expected_aggregate_{total/evaluated/satisfied/rejected/pending/deferred/pass_rate}_drift + closure_violation)。**closure invariant**: `total == satisfied + rejected + pending + deferred` を partition で enforce
- **Anti-Gaming defense matrix (HIGH-005 + batch 5e R3-R6 carry-over)**: 11 defense (cross-fixture duplicate criterion_id late-commit / non-negative non-bool int / ratio in [0,1] before tolerance / null vs 0.0 sentinel / overflow guard `OverflowError` catch / spec_violation vs sut_failure 物理分離 / spec_violation 時 SUT skip / duplicate within-fixture early reject / envelope/aggregate-invalid fixture corpus state poisoning 回避 / closure invariant / partition invariant)
- **既存 batch 1-10 + batch 5a〜5e invariant 維持**: ContextSnapshot 10 列 / AgentRun 16 状態 / SecretBroker / Approval 4 整合 / RFC 8785 / batch 5a loader / batch 5b tenant_isolation aggregator / batch 5c generic loader / batch 5d citation_coverage aggregator / batch 5e cost_per_completed_task aggregator R6 lessons (corpus_seen_run_ids late-commit / ROUND_HALF_UP / negative declared reject / overflow guard)

### Sprint 11 batch 5g 実装進捗 (PR #?? merge 後に commit hash 追記)

- **batch_5g_implementation_pr**: 本 PR (AC-KPI-02 time_to_merge aggregator)
- **Pivot rationale**: BL-0125 リテラル「coding/review eval suites」は SP-022 framework intake hardening へ移送し、本 batch は Sprint 11 受け入れ条件 line 186「AC-KPI 5 件すべて aggregator 経由」達成のため AC-KPI-02 time_to_merge aggregator を実装。BL-0125 SP-022 移送は plan v2 §1.1 HIGH-003 で正当化 (Sprint Exit ## Review で must_ship 表 line 167 を 6 領域 → 5 領域 + SP-022 carry-over に update、受け入れ条件 line 181 を「26 BL すべて Codex multi-round で `verdict=clean` 到達 (BL-0125 は SP-022 移送)」へ更新予定)
- **実装 BL**: AC-KPI-02 time_to_merge aggregator → **4/5 件目達成** (5d=AC-KPI-04, 5e=AC-KPI-05, 5f=AC-KPI-01, **5g=AC-KPI-02**, 残 AC-KPI-03 は batch 5h-pre)
- **新規 file**:
  - `backend/app/services/eval/kpis/time_to_merge.py` (~700 LOC、AC_KPI_02_* constants + SamplePullRequest + TimeToMergeFixtureResult + TimeToMergeMetricResult + evaluate_time_to_merge)
  - `eval/quality/time_to_merge/{manifest.json, expected_schema.json, README.md, public_regression/skeleton.json, private_holdout/.gitkeep+README.md, adversarial_new/.gitkeep+README.md, __init__.py}` (live skeleton 5 PRs / 3 merged @ 30m/60m/90m / median 1.0h)
  - `tests/eval/test_kpis_time_to_merge.py` (~1000 LOC、69 test cases)
- **実装手法**: plan-reviewer R1 (10 finding adopt: HIGH×3 + MEDIUM×4 + LOW×3) → R2 (READY 0 finding) → Claude direct (Codex review に専念)
- **Anti-Gaming invariants** (manifest kpi_specific 7 件):
  1. `time_to_merge is recomputed from input.sample_pull_requests, not copied from expected_aggregate`
  2. `only PRs with status="merged" contribute to the median`
  3. `open / draft / closed_without_merge are excluded from numerator (no opinion)`
  4. **`merged_at >= ticket_created_at` causality invariant rejected at parse time (no `max(0,...)` clamping、HIGH-001 single source of truth)**
  5. **corpus-wide uniqueness key is `(ticket_id, repository_id)` so one ticket may have multiple repos (Draft re-open / squash、MED-004)**
  6. **mock-only contract: aggregator does NOT pull from live tickets table (SP-012 wire-up、defense #13)**
  7. fixture_id and dataset_version_id are persisted to EvalResult
- **server-owned boundary §1+§3**: caller-supplied `list[Fixture]` 直接受け取り signature なし、sut_results は read-only Mapping、pure function (DB / file system / network access なし)
- **4+ source enum integrity (HIGH-003 partial、5th source SP-012 で追加)**: 5 AC_KPI_02_* constants + PR status 4-element enum (aggregator `_KNOWN_PR_STATUSES` frozenset、`_MERGED_STATUS` literal、fixture `expected_schema.json` enum、pytest `EXPECTED_KNOWN_PR_STATUSES`) を **exact name set 比較** + import-time partition invariant runtime raise。**Timestamp format cross-source contract (MED-001)**: fixture schema `date-time` + aggregator `_parse_timestamp_ms` で naive datetime reject / non-UTC normalize / `Z` suffix → `+00:00` / OverflowError catch
- **BL-0127b / SP-012 forward-compat**: optional `sut_results: Mapping[str, bool] | None` parameter、batch 5d/5e/5f patterns 完全継承
- **redacted splits skip**: `_SUPPORTED_FIXTURE_KINDS=("public_regression",)` 限定、private_holdout / adversarial_new は SP-022+
- **threshold semantics (HIGH-002 adopt)**: AC_KPI_02_THRESHOLD_HOURS=2.0、**LOWER is better** ("<=" operator)。`threshold_reason ∈ {no_fixtures, manifest_violation, spec_violation, sut_failure, no_merged_pulls, threshold_met, above_threshold}` 7 priority + 各 `threshold_met` boolean 値を §4.2.2 matrix で明文化。`no_merged_pulls` は KPI 未充足 = `threshold_met=false` 単一経路で扱う (Anti-Gaming silent-pass 防止)
- **median strategy (MED-002 adopt)**: 「pooled (un-weighted) corpus-wide median」for SP-012 live DB pooling と整合。NOT median-of-medians
- **boundary equality (MED-003 adopt)**: `merged_at == ticket_created_at` (duration=0) は valid。Anti-Gaming counter-defense: 5+ merged で全 duration=0 は `_LOGGER.warning` 観測ログ (reject なし)
- **per-PR structural validation**: ticket_id / project_id RFC 4122 UUID v1-5 strict、repository_id UUID OR null (merged 時 non-null 必須、LOW-R2-001)、tenant_id non-bool int >= 1、status enum、ticket_created_at + merged_at ISO-8601 with tzinfo (naive reject)
- **expected_aggregate drift detection**: pulls_count / merged_count / open_count / draft_count / closed_without_merge_count / median_hours の 6 field 全てを recomputed と一致を要求 (5+1=6 reason_code: expected_aggregate_{pulls/merged/open/draft/closed}_drift + median_drift) + closure invariant `pulls_count == merged + open + draft + closed`
- **Anti-Gaming defense matrix (HIGH-005 + batch 5e/5f 教訓 carry-over)**: 13 defense (cross-fixture duplicate `(ticket_id, repository_id)` late-commit / negative declared reject / null vs 0.0 sentinel / overflow guard / closure invariant / partition invariant + **timestamp causality (新規 #12)** + **mock-only contract (新規 #13)**)
- **既存 batch 1-10 + batch 5a〜5f invariant 維持**: ContextSnapshot 10 列 / AgentRun 16 状態 / SecretBroker / Approval 4 整合 / RFC 8785 / batch 5a loader / batch 5b tenant_isolation / batch 5c generic loader / batch 5d citation_coverage / batch 5e cost_per_completed_task R6 lessons / batch 5f acceptance_pass_rate F-PR33-001 closure defense-in-depth comment pattern carry-over

### Sprint 11 batch 5h-pre 実装進捗 (PR #?? merge 後に commit hash 追記)

- **batch_5h_pre_implementation_pr**: 本 PR (AC-KPI-03 approval_wait_ms aggregator)
- **実装 BL**: AC-KPI-03 approval_wait_ms aggregator → **5/5 件目達成、SP-011 受け入れ条件 line 186 「AC-KPI 5 件すべて aggregator 経由」 100% 充足**
- **新規 file**: `backend/app/services/eval/kpis/approval_wait_ms.py` (~700 LOC) + `tests/eval/test_kpis_approval_wait_ms.py` (~900 LOC、61 test)。既存 Sprint 3 fixture corpus 改変なしで利用
- **plan-reviewer R1 → R2**: 11 finding adopt (HIGH×4 + MEDIUM×4 + LOW×3) → READY
- **5+ source enum integrity FULL (HIGH-H3)**: DB CHECK `approval_requests_ck_status` + ORM Literal `ApprovalStatus` + aggregator frozenset + pytest EXPECTED + fixture schema enum の 5 source exact set 比較
- **causality semantic alignment (HIGH-H4)**: 既存 loader silent-skip + aggregator reject の two-layer defense-in-depth
- **per-fixture all-pending by-construction (HIGH-H2)**: schema 上 `median_ms: number minimum 0` required ⇒ decided_count==0 per-fixture は内部矛盾、`expected_aggregate_median_drift` で reject
- **per-fixture threshold scope (HIGH-H1)**: 既存 schema は `additionalProperties: false` で reject 済だが、persisted corpus path 防御として aggregator side で reject (`spec_violation:threshold_unexpected`)
- **Anti-Gaming defense matrix**: 15 defense (batch 5e/5f/5g 13 defense carry-over + #14 decided_at required/null per status + #15 per-fixture threshold reject)
- **既存 batch 1-10 + batch 5a〜5g invariant 維持**: ContextSnapshot 10 列 / AgentRun 16 状態 / SecretBroker / Approval 4 整合 / RFC 8785 / 全 KPI aggregator pattern carry-over

### Sprint 11 AC-KPI 5 件 aggregator 達成サマリ (line 186 100% 充足)

| KPI | aggregator file | merged PR |
|---|---|---|
| AC-KPI-01 acceptance_pass_rate | `backend/app/services/eval/kpis/acceptance_pass_rate.py` | #33 (batch 5f) |
| AC-KPI-02 time_to_merge | `backend/app/services/eval/kpis/time_to_merge.py` | #34 (batch 5g) |
| AC-KPI-03 approval_wait_ms | `backend/app/services/eval/kpis/approval_wait_ms.py` | this PR (batch 5h-pre) |
| AC-KPI-04 citation_coverage | `backend/app/services/eval/kpis/citation_coverage.py` | #31 (batch 5d) |
| AC-KPI-05 cost_per_completed_task | `backend/app/services/eval/kpis/cost_per_completed_task.py` | #32 (batch 5e) |

**Sprint 11 受け入れ条件 line 186 「AC-HARD 7 件 + AC-KPI 5 件 fixture registry / aggregator 経由」**: AC-KPI 5/5 達成。残 AC-HARD 7 件は SP-012 で個別計測。

frontmatter `status: draft` 維持。

### Sprint 11 batch 5h 実装進捗 (PR #?? merge 後に commit hash 追記)

- **batch_5h_implementation_pr**: 本 PR (BL-0163 Gold Task Seed v0 → 30 cases expansion)
- **実装 BL**: BL-0163 (private gold task 30-50 件への拡張、`must_ship` 30 件達成、50 件は SP-022 へ defer)
- **変更 file**:
  - `eval/provider/gold_task_v0/dataset.py` (3 cases → **30 cases**: 3 original + 15 simple-schema success variants + 12 structured-schema success variants)
  - `tests/runtime/test_gold_task_v0_contract.py` (`_structured_output_for` を schema-aware に refactor、case_id 別 dispatch を廃止)
  - 既存 `eval/provider/gold_task_v0/runner.py` 不変
- **実装手法**: Claude direct (data extension only、no plan-reviewer round needed per CLAUDE.md §6.5.0 簡単な pattern-follow)
- **Anti-Gaming considerations**:
  - 全 case は existing `GoldTaskCase` Pydantic contract に準拠 (request_template + expected_status + expected_artifact_shape + expected_redacted_summary_shape)
  - `payload_data_class_by_provider` 各 case に必須 (Sprint Pack BL-0163 line 147 「payload_data_class 付与」充足)
  - `_simple_success_case` / `_structured_success_case` factory で boilerplate を一元化、case_id 衝突防止
  - test helper `_structured_output_for` を schema-aware (required-keys signature lookup) にして case_id 別 dispatch 不要、将来の case 追加時に test 側変更不要
- **diverse domain coverage**: code review / debug / classify / extract / summarize / plan / risk assessment / postmortem / API contract / dependency upgrade / performance / security / outage / rate limit / migration rollback / feature flag / approval workflow / audit log — 18+ diverse domains
- **5+ source enum integrity 維持**: ProviderResultKind enum + GoldTaskCase Pydantic + Sprint 5 existing dataset.py contract、新規 case はそれらの集合に閉じる
- **server-owned boundary §1+§3**: data only、no new function signature、aggregator pure function 不変
- **Verification**:
  - ruff clean (本 batch 新規 file)、mypy clean (200 source files)
  - pytest tests/runtime/test_gold_task_v0_contract.py: 126 passed (30 cases × 4 providers + 6 module-level contract / metadata / oracle / uniqueness / minimum / share tests; R1 で 4 新規 test 追加後の最終値)
  - 残 23 件 `ANN401` warning は Sprint 3/5 era 既存 file (runner.py / loader.py)、本 batch scope 外

### Sprint 11 batch 5h SP-011 受け入れ条件 contribution

- line 181 (26 BL Codex multi-round verdict=clean): BL-0163 はこの PR
- line 186 (AC-HARD 7 + AC-KPI 5 aggregator): N/A (BL-0163 は Gold Task Seed expansion、AC-KPI/AC-HARD aggregator 直接 contribute なし)
- must_ship 表 line 171 (private gold task 30-50 件): **30 件達成**、50 件は SP-022

### Sprint 11 batch 5j 実装進捗 (PR #?? merge 後に commit hash 追記)

- **batch_5j_implementation_pr**: 本 PR (BL-0159 backup_restore_rpo_rto skeleton aggregator)
- **実装 BL**: BL-0159 (AC-HARD-04 fixture contract skeleton、SUT execution + PITR activation は Sprint 11.5 BL-0159b へ defer per SP-011 must_ship table line 173)
- **新規 file**:
  - `backend/app/services/eval/hard_gates/backup_restore.py` (~430 LOC)
  - `tests/eval/test_hard_gates_backup_restore.py` (~600 LOC、46 tests)
- **既存 Sprint 0 fixture infrastructure 不変**: `eval/ops/backup_restore/{manifest.json, expected_schema.json, public_regression/sample.json}` を改変なしで利用
- **plan-reviewer R1 → R2**: 9 finding adopt (HIGH×2 + MEDIUM×4 + LOW×3) → R2 READY (0 BLOCKER / 0 HIGH)
- **PITR P0 vs Sprint 11.5 境界 (HIGH-1 adopt)**: PRD-01 §10.3 Phase H PH-F-010 fix 准拠で「P0 では PITR は要求しない」明示。既存 schema の `expected_pitr_success: const true` を **Sprint 11.5 BL-0159b 用 forward-looking declaration** として P0 では accept、aggregator は fixture envelope 申告のみ validate (実 PITR 実行なし)
- **metric layer 分離 (HIGH-2 adopt)**: aggregator は **per-fixture pass-rate** (`backup_restore_rpo_rto`、threshold=1.0、batch 5b pattern)。`hard-gates-and-kpis.md` の 2 numeric metric (`backup_restore_rpo_hours` / `backup_restore_rto_hours`) は SP-022+ Grafana 別 layer (Sprint 11.5 BL-0159b SUT 実行 で `measured_*` 計測)
- **ADR Gate Criteria #8 (backup/restore/PITR、MED-3 adopt)**: 本 batch は aggregator のみで対象外、Sprint 11.5 BL-0159b で **ADR-00022 候補 (PITR adoption)** を起票予定
- **5+ source enum integrity**: 5 source (`_KNOWN_DRILL_KINDS` frozenset + `_REQUIRED_SKELETON` ({"dev_restore"}) + `_FUTURE_REQUIRED` (3 kinds) + pytest EXPECTED + fixture schema enum)、partition `_REQUIRED_SKELETON ⊆ _REQUIRED_FUTURE ⊆ _KNOWN` import-time runtime check (S101-safe RuntimeError raise)
- **threshold_reason priority (MED-4 adopt)**: spec_violation > missing_drill_kinds (corruption is deeper root cause than coverage gap)
- **Anti-Gaming defense matrix (15 defenses)**: batch 5b carry-over (envelope / RPO / RTO / PITR / checksum_match / drill_kind enum / encrypted / isolated / sha256 / required_drill_kinds / manifest drift / spec_violation hard reset / sut_results / late-commit gate / redacted splits skip) + 新 **#14 fixture-level anti_gaming envelope** (append_only_refresh + separate_fixture_and_policy_commits、MED-1) + **#15 payload_data_class ∈ {public, internal}** (no PII / confidential backup descriptors、MED-2)
- **skeleton scope**: 1 fixture (`dev_db_restore_checksum`)、1 drill_kind ({"dev_restore"}) required。Sprint 11.5 BL-0159b で 3 fixtures / 3 drill_kinds (`dev_restore`, `private_staging_restore`, `pitr`) 拡張
- **Verification**: ruff clean / mypy clean (201 source files) / pytest tests/eval/test_hard_gates_backup_restore.py: **46 passed** / pytest tests/eval/: **1093 passed, 4 skipped**

### Sprint 11 batch 5j SP-011 受け入れ条件 contribution

- line 181 (26 BL Codex multi-round verdict=clean): BL-0159 はこの PR
- line 186 (AC-HARD 7 + AC-KPI 5 aggregator / fixture registry 経由で測定可能): **AC-HARD-04 fixture skeleton 達成** (SUT execution 経由は Sprint 11.5 BL-0159b)
- must_ship 表 line 173 (`backup_restore_rpo_rto` fixture contract skeleton): **達成**、activation は Sprint 11.5 BL-0159b

### batch 5i (BL-0130 / 2026-05-17 session)

#### Changed
- `.github/workflows/nightly-regression.yml` (新規、~110 LOC、`cron '0 3 * * *'` で public_regression + Gold Task v0 nightly run、main 限定 + concurrency `nightly-regression-${{ github.ref }}` / cancel-in-progress=false)
- `.github/workflows/ci-smoke.yml` (`workflow-lint` job 新規追加、~14 LOC、`docker://rhysd/actionlint:1.7.7` で `.github/workflows/**` 全件を PR 時点で syntax check)
- `docs/sprints/SP-011_eval_harness.md` (本 ## Review section)

#### Verified
- BL-0130 acceptance: nightly cron `0 3 * * *` + public_regression 自動実行 + Gold Task v0 contract 統合 ✅
- Anti-Gaming boundary: 既存 loader sanitize (Sprint 11 batch 5b) + dataset_version pinning + sha256 anti-gaming guard + pytest `-q --tb=short` で集約出力 (個別 fixture 期待値の非 export 設計を継承) + `--strict-markers` で unknown marker reject (preventive guard) ✅
- deny-by-default (`.claude/rules/core.md §6`): permissions `contents: read` only / main 限定 if / secrets 不要 ✅
- concurrency: `nightly-regression-${{ github.ref }}` + `cancel-in-progress: false` (ci-smoke.yml の commit SHA 単位 push group とは別方針、nightly は last-write-wins ではなく全件 run) ✅
- workflow YAML self-lint: ci-smoke.yml `workflow-lint` job (actionlint 1.7.7) が `.github/workflows/**` を PR 時点で validate ✅
- Local actionlint validation: `docker run --rm -v $(pwd):/repo --workdir /repo rhysd/actionlint:1.7.7 -color` → exit=0 (両 workflow file syntax clean) ✅
- main 限定二重保証: schedule trigger の GitHub Actions default branch 限定仕様 + job level `if: github.ref == 'refs/heads/main'` ✅
- plan-reviewer R1 → R2 READY: HIGH×2 + MEDIUM×3 + LOW×2 全 7 件 adopt → R2 で BLOCKER=0 / HIGH=0、MEDIUM=1 (doc-only factual drift、本 ## Review で訂正済) ✅

#### Deferred (Sprint 11.5 / SP-022)
- `private_holdout` monthly decryption (age key + Tailscale GitHub Action、ADR Gate Criteria #6 secrets management)
- Failure notification (Slack / Discord / MoltBot Webhook integration、ADR Gate Criteria #4/#5 external integration)
- `pytest.mark.no_leak` marker (future batch で fixture 期待値 export test 導入時の preventive guard)
- BL-0163 Gold Task 50 件拡張時の timeout 見直し (cron 頻度緩和 or split job 化、Sprint 11.5/12 で fixture サイズに応じ判断)
- Grafana / Loki integration

#### Risks
- workflow_dispatch 経由で repository write 権限保持者が手動 trigger 可能 (mitigated: main 限定 if + permissions deny-by-default + secrets 不要)
- BL-0163 Gold Task v0 が将来 50+ cases に拡張時 (Sprint 11.5/SP-022)、20 min timeout が不足する可能性 → Sprint 11.5/12 で再評価
- GitHub Actions billing infrastructure issue (CI 失敗時の cascade、本 batch では code clean を local actionlint + pytest tests/eval/ で local 確認)

#### Plan-reviewer R2 訂正 (M-NEW-1 adopt)
- plan v2 §3 line 76 で "`test_anti_gaming_ci_gate.py` は public_regression のみに gate を限定" と記載したが、実際の `tests/eval/test_anti_gaming_ci_gate.py:33-41` は 3 splits (public_regression / private_holdout / adversarial_new) 全件を gate 対象にしている。ただし当該 gate は `TASKMANAGEDAI_RUN_ANTI_GAMING_GATE=1` opt-in (default skip) で、本 nightly では env 設定なし → run 動作には影響なし。Anti-Gaming defense の主体は loader sanitize + dataset_version pinning + pytest 集約出力 + `--strict-markers` の 4 layer。

### Sprint 11 batch 5i SP-011 受け入れ条件 contribution

- line 181 (26 BL Codex multi-round verdict=clean): BL-0130 はこの PR
- line 188 (acceptance: nightly schedule で public_regression を自動実行): **達成** (cron + workflow_dispatch + main 限定 + concurrency / actionlint syntax guard)
- must_ship 表 line 174 (BL-0130 nightly regression job): **達成**、private_holdout monthly は Sprint 11.5 / SP-022

## QL-B cross-reference (R29 §5 QL-B、2026-05-15 doc-only、F-PR12-004 P2 adopt)

本 Pack の acceptance spec として、QL-B Quality Loop run で記録された future implementation gate を以下の通り cross-reference する:

- `docs/基本設計/03_AIオーケストレーション設計.md §13.2` BudgetGuard pre-spend gate (max cost / max session cost / `cost_per_completed_task` AC-KPI-05 計測元、provider call 前 estimated cost check)
- `docs/基本設計/03_AIオーケストレーション設計.md §13.3` Quality Loop status 物理分離宣言 (AgentRun.status 16 状態に Quality Loop vocabulary を追加しない、Quality Loop schema 化は P0.1 **SP-023 候補**で別 ADR + Sprint Pack)
- `docs/adr/00025_autonomy_policy_profiles.md` (proposed) §10.3 不変条件 #3 auto-allow path でも AgentRunEvent + audit event に `policy_profile` / `policy_version` / `applied_level` を必ず残す (eval metrics 集計の trace source)
