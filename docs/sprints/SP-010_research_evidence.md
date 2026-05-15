---
id: "SP-010_research_evidence"
type: "heavy"
status: "draft"
sprint_no: 10
created_at: "2026-05-13"
updated_at: "2026-05-13"
target_days: 4.3
max_days: 7
adr_refs:
  - "[ADR-00002](../adr/00002_db_schema.md) # accepted、Research/Evidence schema 追加で update"
planned_adr_refs:
  - "[ADR-00003](../adr/00003_api_contract.md) # Sprint 10 で update proposed、Research-to-Ticket adapter API contract"
related_sprints:
  - "SP-002_core_data_model"
  - "SP-004_agent_runtime"
  - "SP-011_eval_harness"
upstream_sprints:
  - "SP-001_project_foundation"
  - "SP-002_core_data_model"
  - "SP-003_policy_approval"
  - "SP-004_agent_runtime"
downstream_sprints:
  - "SP-011_eval_harness # AC-KPI-04 citation_coverage source"
  - "SP-012_p0_acceptance"
risks:
  - "evidence_set_hash drift (NFC UTF-8 + JCS canonical の実装差異)"
  - "research_tasks cross-project FK 制約遅延 (Sprint 2 BL-0029c carry-over)"
  - "ContextSnapshot.evidence_set_hash 既存 AgentRun 破壊 (nullable + backfill 必要)"
  - "PROV bundle hash の URL 正規化 invariant 漏れ"
---

このテンプレの使い方: ADR Gate Criteria #2 DB schema + #3 API contract に該当する Sprint。Research / Evidence schema を first-class にし、`evidence_set_hash` を ContextSnapshot 10 column の中核として固定する。Sprint 11 (Eval Harness) の AC-KPI-04 citation_coverage の source ticket を提供する。

最終更新: 2026-05-13

## 目的

- `ResearchTask` / `Claim` / `EvidenceSource` / `EvidenceItem` table + migration を実装
- `canonical_url` / `retrieved_at` / `published_at` / `content_hash` / `relation` / `locator` / `relevance_score` / `freshness_score` / `provenance_json` 列を完成
- `evidence_set_hash` の computation (NFC UTF-8 + JCS canonical JSON + claim_id/source_id 昇順 + URL 正規化 + PROV bundle hash) を確立
- ContextSnapshot.evidence_set_hash を本実装で結線 (Sprint 4 で nullable 確保済の列を必須化)
- Research-to-Ticket artifact contract (server-owned artifact_hash binding) を実装
- AC-KPI-04 `citation_coverage` の metric source ticket (BL-0119 + BL-0126) を提供

## 背景

- PRD-01 F-005 / F-009 / F-018 + NF-009 で Research / Evidence は P0 必須機能
- Sprint 4 (Agent Runtime) で ContextSnapshot 10 column 全列を確保済、`evidence_set_hash` は Sprint 10 まで dummy (空 hash) で動作
- AC-KPI-04 `citation_coverage >= 0.9` を Sprint 12 P0 Acceptance で計測する必要がある
- 本 Sprint で正本 schema + computation + adapter を完成、Sprint 11 で Eval Harness に統合

## 対象外

- conflict_group_id (矛盾解決) — P1 へ defer
- source trust registry — P1 へ defer
- 自動矛盾解決 — P1 へ defer
- freshness_score の自動更新 cron — Sprint 11.5 へ defer (Observability で再計算 metric として可視化)

## 設計判断

- **evidence_set_hash computation**: NFC UTF-8 + JCS (RFC 8785) canonical JSON + claim_id/source_id 昇順 + URL 正規化 (RFC 3986 + RFC 6596 + trailing slash strip) + PROV bundle hash の組み合わせ。一切の caller-supplied hash を信頼しない (server-owned-boundary §1)。
- **provenance_json schema**: W3C PROV-DM minimal subset (Activity / Entity / Agent + wasGeneratedBy + used + wasAttributedTo) を JSON で持つ。Pydantic Schema で validation。
- **ContextSnapshot.evidence_set_hash の null 互換**: Sprint 4 〜 Sprint 10 着手前の AgentRun は `evidence_set_hash IS NULL` を許容 (backfill しない、null = "Research/Evidence 未関連付け" の semantics)。Sprint 10 着手以降の新 AgentRun は必須。
- **research_tasks cross-project FK** (BL-0029c carry-over): Sprint 2 で deferred の `(tenant_id, project_id, research_task_id)` 複合 FK を本 Sprint で完成。

## 実装チケット (正本 BL ID = PLAN-01 docs/実装計画/P0_バックログ.md と同期)

| BL ID | 内容 | depends_on |
|---|---|---|
| BL-0113 | `research_tasks` migration と API (tenant_id + project FK + status enum `queued` / `running` / `completed` / `failed`) | BL-0023 |
| BL-0114 | `evidence_sources` migration と API (canonical_url + content_hash + retrieved_at + published_at) | BL-0113 |
| BL-0115 | `claims` / `evidence_items` migration と API (provenance_json + freshness_score + locator + relevance_score + 複合 FK) | BL-0113, BL-0114 |
| BL-0116 | `provenance_json` PROV validation (W3C PROV-DM minimal subset、5 relation: wasGeneratedBy / used / wasAttributedTo / wasInformedBy / wasDerivedFrom) | BL-0115 |
| BL-0117 | `evidence_set_hash` 正規化アルゴリズム (NFC UTF-8 + JCS canonical JSON + claim_id/source_id 昇順 + URL 正規化 + PROV bundle hash) + ContextSnapshot 結線 | BL-0115, BL-0116 |
| BL-0118 | Research-to-Ticket artifact schema (server-owned artifact_hash binding) + Adapter | BL-0115, BL-0031 |
| BL-0119 | `citation_coverage` metric source (AC-KPI-04 source ticket、Sprint 11 BL-0126 aggregator が消費) | BL-0115 |
| BL-0120 | Research / Claim / Evidence の最小 UI (P0 read-only、API client + page skeleton) | BL-0113, BL-0115 |
| BL-0121 | `conflict_group_id` / source trust registry P1 defer placeholder (doc + migration TODO comment) | BL-0115 |
| BL-0029c | `research_tasks` cross-project negative fixture (Sprint 2 carry-over、`(tenant_id, project_id, research_task_id)` cross-project SELECT/INSERT reject) | BL-0113, BL-0029 |

## タスク一覧

- [ ] batch 0: ADR-00002 update + ADR-00003 update proposed → BL-0113 (research_tasks) + BL-0114 (evidence_sources) schema DDL + migration
- [ ] batch 1: BL-0115 (claims / evidence_items) DDL + BL-0116 PROV validation
- [ ] batch 2: BL-0117 evidence_set_hash 正規化アルゴリズム + ContextSnapshot 結線
- [ ] batch 3: BL-0118 Research-to-Ticket adapter + BL-0119 citation_coverage metric source
- [ ] batch 4: BL-0120 read-only UI + BL-0121 P1 defer placeholder
- [ ] batch 5: BL-0029c cross-project negative fixture
- [ ] Sprint Exit: ADR-00002 update accepted 化 + Sprint Pack ## Review

## must_ship / defer_if_over_budget 対応表

| 項目 | must_ship | defer_if_over_budget |
|---|---|---|
| 4 table DDL + 複合 FK + migration | ○ | — |
| evidence_set_hash computation + ContextSnapshot 結線 | ○ | — |
| PROV validation + provenance_json schema | ○ | — |
| Research-to-Ticket adapter | ○ | — |
| 越境 negative test (cross-tenant + cross-project) | ○ | — |
| BL-0029c research_tasks cross-project FK | ○ | — |
| conflict_group_id (矛盾解決) | × | P1 |
| source trust registry | × | P1 |
| freshness_score 自動更新 cron | × | Sprint 11.5 |

## 受け入れ条件

- 4 table (research_tasks / claims / evidence_sources / evidence_items) が migration で作成され、`(tenant_id, project_id, *)` 複合 FK で閉じている
- ContextSnapshot.evidence_set_hash が新規 AgentRun で必須 (NOT NULL after Sprint 10、既存 AgentRun は nullable backfill default で保護)
- evidence_set_hash (BL-0117) が同一 input で deterministic (NFC + JCS + sorted) — 1000+ test で reproducibility 確認
- PROV bundle hash (BL-0116) が provenance_json の wasGeneratedBy + used + wasAttributedTo を含む
- 越境 SELECT / INSERT / UPDATE / DELETE が全件 reject (BL-0029c)
- 同一 tenant・別 project の cross reference (research_task → ticket / claim → evidence_source) も reject

### QL-C 拡充 acceptance spec (R29 §5 QL-C、P-09 + P-18 反映、doc-only)

本 section は **QL-C run (2026-05-15、quality-loop/QL-C-research-eval-pack)** で追記した修正まとめ拡充 spec。**本 SP-010 では schema 追加なし** (acceptance spec のみ)、実 DDL / model / API は別 batch で landing する。

- **SearchRun acceptance spec** (Sprint 10 BL-0119 source / Sprint 11 BL-0126 consumer 共通 contract):
  - 必須 column: `tenant_id` / `project_id` / `research_task_id` / `search_run_id (UUID)` / `query_canonical_hash (sha256)` / `retrieval_policy_version` / `hit_count` / `latency_ms` / `started_at` / `completed_at`
  - **複合 FK (Codex F-QLC-001 P1 adopt)**: `(tenant_id, project_id)` だけでは不足。`(tenant_id, project_id, research_task_id) references research_tasks(tenant_id, project_id, id)` で **research_task が同一 project に属することを DB 境界で強制** (cross-project research_task 紐付け reject、BL-0029c 整合)。cross-project SELECT も全件 reject。
  - server-owned-boundary: `query_canonical_hash` は caller-supplied 不可、server 側で query 文字列を NFC + lower 化後 sha256 して生成
- **EvidenceSearchHit acceptance spec** (検索結果 ↔ Evidence 紐付け):
  - 必須 column: `tenant_id` / `project_id` / `search_run_id` / `claim_id` / `evidence_source_id` / `rank (int)` / `relevance_score (float [0,1])` / `ndcg_contribution (float)` / `is_grounding (bool)`
  - **rank constraint (Codex F-QLC-006 P2 adopt)**: `(tenant_id, project_id, search_run_id, rank)` unique + `CHECK (rank >= 1)`。同一 SearchRun 内の rank duplicate / 0 / 負値を全件 reject、top-k 集計 (recall@k / precision@k / nDCG) の安定再計算を保証。
  - 複合 FK: `(tenant_id, project_id, search_run_id)` / `(tenant_id, project_id, claim_id)` / `(tenant_id, project_id, evidence_source_id)` で閉じる
- **GroundingSupport acceptance spec** (生成 artifact ↔ Evidence 関連付け、citation_coverage source):
  - 必須 column: `tenant_id` / `project_id` / `generated_artifact_id` / `agent_run_id` / `claim_id` / `evidence_source_id` / `support_type (cite|paraphrase|quote)` / `confidence_score`
  - **複合 FK (Codex F-QLC-002 P1 adopt)**: `generated_artifact_id` だけでは不足 — `artifacts` table は project を直接持たず `agent_runs` 経由で project が決まるため、`(tenant_id, project_id, agent_run_id) references agent_runs(tenant_id, project_id, id)` + `(tenant_id, project_id, agent_run_id, generated_artifact_id) references artifacts(tenant_id, agent_run_id, id)` の 2 段 FK で **artifact の project binding を DB 境界で強制**。
  - 越境 negative test: 別 project の generated_artifact_id / claim_id / agent_run_id を関連付ける insert は全件 reject (artifact の run binding 経由で project 一致を verify)
- **RetrievalEvalRun baseline acceptance spec** (Sprint 11 BL-0126 で集計、本 Sprint 10 では skeleton schema のみ documenting):
  - 必須 column: `tenant_id` / `project_id` / `eval_run_id` / `dataset_version_id (UUID FK)` / `recall_at_k (json: {5: float, 10: float})` / `precision_at_k (json)` / `ndcg_at_k (json: {10: float})` / `citation_coverage (float [0,1])` / `grounded_answer_rate (float [0,1])` / `tool_trajectory_match (float [0,1])`
  - **dataset_version_id FK 必須 (Codex F-QLC-003 P1 adopt)**: 文字列 `dataset_version` のみだと別 dataset の `eval_run_id` と任意 version 文字列の組合せが保存可能 → Anti-Gaming fixture/policy 分離 + AC-KPI 集計 trace 破壊。既存 eval schema (Sprint 11 BL-0122/0123) の `dataset_versions` table への `dataset_version_id UUID FK` 必須、`(tenant_id, eval_run_id, dataset_version_id)` 複合制約で run ↔ case dataset 一致を DB で強制。
  - Anti-Gaming invariant: `dataset_versions.created_at` の fixture creation commit と policy 修正 commit が **別 author / 別 timestamp** であること (Sprint 11 BL-0129 CI gate)
- **citation_coverage の source ticket spec** (AC-KPI-04 計測 contract):
  - **計算式 (Codex F-QLC-004 P1 adopt)**: AC-KPI-04 既存 contract は **claim-level** (`count(distinct claim_id with >= 1 GroundingSupport) / count(distinct claim_id within evaluated AgentRun)`)。**generated_artifact-level は誤り** — 複数 claim を含む artifact に 1 件だけ GroundingSupport があっても artifact 全体が covered と数える歪み発生。Sprint 12 AC-KPI-04 final verify では claim 単位で集計する。
  - 閾値: P0 で `claim-level citation_coverage >= 0.9` (Sprint 12 AC-KPI-04 で final verify)
  - **null evidence_set_hash 扱い (Codex F-QLC-007 P2 adopt)**: null evidence_set_hash の AgentRun は **分母に含め、分子は 0 として uncovered として数える**。除外すると Research/Evidence 結線欠落 run が評価対象から消えて citation_coverage を過大評価する。SP-010 既存リスク欄の「Sprint 11 で null を 0 として扱う仕様統一」と整合。P0 acceptance での `denominator_nonzero` gate を維持。

### Pack reuse + alias map 注記 (R29 P-09 反映)

- 本 SP-010 は前 session commit `369672b` で作成済の **既存 Pack**。本 QL-C run では拡充 spec のみ追記、新規 Pack 作成なし。
- alias map: `BL-0113`〜`BL-0130` (P0 backlog) は本 Pack `## 実装チケット` section に直接 landing 済。registry 経由の indirection なし。
- 既存 BL trace を破壊しない (R29 §5 QL-C verification 必須項目)。

## Audit Event

新規 event_type (Sprint 10 で追加):

- `research_task_created` (research_tasks INSERT)
- `claim_created` (claims INSERT)
- `evidence_source_registered` (evidence_sources INSERT)
- `evidence_item_attached` (evidence_items INSERT)
- `research_to_ticket_promoted` (BL-0118 Research-to-Ticket artifact)

audit_events payload に必須 field: `tenant_id` / `actor_id` / `run_id?` / `research_task_id` / `claim_id?` / `evidence_set_hash` (BL-0117 経由) / `trace_id` / `correlation_id` / `timestamp`。raw provenance_json body は payload に含めず、`provenance_json_hash` (sha256 16-char prefix) のみ記録 (raw content は別 artifact store)。

## 検証手順

```bash
# migration
uv run alembic upgrade head
uv run alembic check  # migration ↔ model drift 0

# unit / contract test
uv run pytest tests/research_evidence/ -q
uv run pytest tests/contracts/test_evidence_set_hash_determinism.py -q  # 1000+ NFC + JCS sample
uv run pytest tests/contracts/test_provenance_json_schema.py -q

# 越境 negative
uv run pytest tests/security/test_research_cross_tenant_negative.py -q
uv run pytest tests/security/test_research_cross_project_negative.py -q

# ContextSnapshot 結線
uv run pytest tests/agent_runtime/test_context_snapshot_evidence_set_hash.py -q

# lint / type
uv run mypy backend
uv run ruff check backend tests
```

## レビュー観点

- evidence_set_hash の **caller-supplied hash 経路がない** (server-owned-boundary §1)
- URL 正規化 invariant が NFC + percent-encoding + trailing slash + protocol downgrade をカバー
- PROV bundle hash が W3C PROV-DM minimal subset の 5 relation (wasGeneratedBy / used / wasAttributedTo / wasInformedBy / wasDerivedFrom) を含む (P0 では minimal でも extensibility 維持)
- 複合 FK が `(tenant_id, project_id, claim_id)` / `(tenant_id, project_id, evidence_source_id)` で閉じている
- ContextSnapshot.evidence_set_hash の nullable backward compat を破壊していない

## Rollback (per batch)

- batch 0 失敗 (research_tasks / evidence_sources DDL): migration revision を 1 件 down で revert、related FK は CASCADE で削除
- batch 1 失敗 (claims / evidence_items + PROV): claims table を down、PROV validator は service code 削除 (DB 変更なし)
- batch 2 失敗 (evidence_set_hash + ContextSnapshot 結線): ContextSnapshot.evidence_set_hash を nullable に戻す、新規 AgentRun は dummy `null` で動作 (Sprint 4 と同等)
- batch 3 失敗 (Research-to-Ticket adapter + citation_coverage source): adapter コード削除、AC-KPI-04 source は Sprint 11 で別 source 提供 (BL-0119 を Sprint 11 へ defer)
- batch 4 失敗 (UI): frontend page を 404 with skeleton 維持、API client 削除 (backend route は維持)
- batch 5 失敗 (BL-0029c cross-project fixture): fixture file 削除、SP-002 BL-0029 fallback で Sprint 12 AC-HARD-03 final verify 時に再評価

## 残リスク

- evidence_set_hash drift (NFC UTF-8 + JCS canonical の Python 実装差異): `jcs` library + `unicodedata.normalize('NFC', ...)` で deterministic 化、ただし claim 数が 10000+ になると hash computation 性能課題が発生する可能性 (Sprint 11.5 で metric 観察)
- research_tasks cross-project FK 制約遅延 (BL-0029c): Sprint 2 から carry-over、本 Sprint で完成しないと AC-HARD-03 cross-project negative が pass しない
- ContextSnapshot.evidence_set_hash backfill 戦略 (null = "未関連付け" semantics で合意): Sprint 11 で Eval Harness が citation_coverage 計算時に null を 0 として扱う仕様統一が必要

## 次スプリント候補

- Sprint 11 (Eval Harness + Sprint 7-9 carry-over) — AC-KPI-04 citation_coverage の Eval 統合
- P1 (post-P0): conflict_group_id / source trust registry / 自動矛盾解決

## 関連 ADR

- ADR-00002 (DB schema) — Research/Evidence schema 追加で update
- ADR-00003 (API contract) — Research-to-Ticket adapter API contract で update proposed → accepted

## Review

(SP-010 完了時に追記)

### Sprint 10 batch 0 実装進捗 (R29 §5 QL-C R22 T-P2R1-013 反映)

- **batch_0_completed_commit**: `314b5bb` (BL-0113 research_tasks DDL/model/migration + BL-0114 evidence_sources DDL/model/migration、Codex R1-R2 clean)
- **既実装 BL**: `BL-0113` (research_tasks)、`BL-0114` (evidence_sources)
- **未着手 BL**: BL-0115〜BL-0130 (claims / evidence_items / evidence_set_hash / Research-to-Ticket adapter / cross-project FK / UI 等、Sprint 10 batch 1+ で順次着手)
- **ADR 状態**: ADR-00002 + ADR-00003 は commit `3f11d00` で proposed 起票済 (frontmatter `status: proposed`)、accepted 化は Sprint 10 全 batch 完了時に別 run で実施

frontmatter `status: draft` 維持 (Pack 全体の Sprint 完了は batch 0〜5 全 BL clean 到達時)。
