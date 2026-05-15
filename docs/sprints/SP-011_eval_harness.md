---
id: "SP-011_eval_harness"
type: "heavy"
status: "draft"
sprint_no: 11
created_at: "2026-05-13"
updated_at: "2026-05-13"
target_days: 5.6
max_days: 10
adr_refs:
  - "[ADR-00002](../adr/00002_db_schema.md) # accepted、Sprint 11 で update"
  - "[ADR-00003](../adr/00003_api_contract.md) # accepted、backend route 追加で update"
  - "[ADR-00004](../adr/00004_agentrun_state_machine.md) # accepted、event_type 拡張で update"
  - "[ADR-00006](../adr/00006_secrets_management.md) # accepted、SecretBroker allowed_operations 拡張"
  - "[ADR-00009](../adr/00009_action_class_taxonomy.md) # accepted、repo.push / repo.pr_open enforcement"
planned_adr_refs:
  - "[ADR-00011](../adr/00011_github_app_permission_matrix.md) # Sprint 11 で 7/8 blocker 解消 review (frontmatter proposed 維持)、Sprint 11.5 BL-Permission-CLI 完了後に accepted 昇格 (F-R1-004 adopt)"
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

- Sprint 9 完了時点で SP-008 `partial_skeleton` / SP-009 `skeleton_pending_backend` の carry-over 残あり (2026-05-13 audit で 25 adopt + 6 backlog tracking + 1 Phase 5 defer)
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
| BL-0100 | AgentRunEvent `repo_pr_opened` actual emission (MockRepoProxy → AgentRuntime 経路結線 + payload schema) |
| BL-0102 | AC-KPI-02 `time_to_merge` 計測 endpoint (`/api/v1/agent-runs/{id}/kpi`) + Draft PR created_at → merged_at median 計算 |

### batch 3: Sprint 8 refactor (2 BL)

| BL ID | 内容 |
|---|---|
| BL-0096a | RepoProxy 4 整合 binding server-side 再計算 refactor (`create_draft_pr(approval_id, agent_run_id)` signature + DB / ContextSnapshot / Git ref から 4 hash 再計算 + 1 mismatch per case negative test) |
| BL-0101a | Webhook HMAC SecretBroker-mediated service layer (`verify_github_webhook(request, secret_ref_current, secret_ref_previous, delivery_id)` 公開境界 + `secret_refs.status` in `(active, deprecated)` 検証 + Redis SETNX replay) |

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

- 27 BL すべて Codex multi-round で `verdict=clean` 到達 (CRITICAL=0 / HIGH ≤ 2、全 finding adopt / reject 判定済)
- Sprint 7-9 audit clean (2026-05-13) を本 Sprint で破壊しない (regression test PASS)
- SP-008 status `partial_skeleton` → `done` 昇格
- SP-009 status `skeleton_pending_backend` → `done` 昇格
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
  - P0 で `claim-level citation_coverage >= 0.9` (Sprint 12 AC-KPI-04 final verify)
  - **null evidence_set_hash AgentRun の扱い (SP-010 F-QLC-007 と整合)**: 分母に含め、分子は 0 として uncovered として数える (除外しない)
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
- 既存 BL trace 維持 (Sprint 11 本来 scope 12 BL + carry-over 15 BL = 27 BL は R29 §5 QL-C verification で破壊不可)。

## 検証手順

```bash
# 全 carry-over verify (15 BL)
uv run pytest tests/secrets/test_repo_operations.py tests/repoproxy/test_github_app_adapter.py \
              tests/agent_runtime/test_repo_pr_opened_event.py tests/contracts/test_kpi_time_to_merge.py \
              tests/repoproxy/test_4integrity_negative.py tests/repoproxy/test_webhook_service_layer.py \
              tests/api/test_tickets_route.py tests/api/test_agent_runs_list.py \
              tests/api/test_audit_events_route.py tests/contracts/test_ac_hard_02_frontend_redaction.py \
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
- ADR-00009 (Action class taxonomy) — repo.push / repo.pr_open enforcement で update
- **ADR-00011 (GitHub App Permission Matrix) — proposed → accepted 化**

## Review

(SP-011 完了時に追記)

### QL-C 拡充 spec landing 記録 (R29 §5 QL-C run、2026-05-15)

- **QL-C run branch**: `quality-loop/QL-C-research-eval-pack` (PR #11、quality-loop/QL-C-research-eval-pack)
- **拡充内容**: P-09 (Pack reuse + alias 整理) + P-18 (Evidence/RAG/Eval metrics acceptance spec) を本 Pack `## 受け入れ条件` に追記
- **doc-only scope** (R29 §5 QL-C verification): no test file / no code change / no DB schema / no migration、acceptance spec のみ
- **既存 27 BL trace 維持**: 本 QL-C 拡充は BL-0079a〜BL-0130 の既存 trace を破壊しない
- **cross-ref**: SP-010 で source schema (SearchRun / EvidenceSearchHit / GroundingSupport / RetrievalEvalRun) を同 PR で追記、SP-011 は集計責務のみ

frontmatter `status: draft` 維持。
