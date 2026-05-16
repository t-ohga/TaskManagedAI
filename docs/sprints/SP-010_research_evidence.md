---
id: "SP-010_research_evidence"
type: "heavy"
status: "completed"
sprint_no: 10
created_at: "2026-05-13"
updated_at: "2026-05-16"
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

最終更新: 2026-05-16

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

## P1 defer placeholder (BL-0121)

本 section は Sprint 10 batch 4 で追加する **BL-0121 placeholder**。P0 では schema / runtime behavior を変更せず、P1 で activate する DB / service / UI contract を先に固定する。batch 4 では migration 実列追加なし、comment-only migration も作成しない。P1 実装時に ADR-00002 / ADR-00003 の update と alembic migration を同時に行う。

- `conflict_group_id` (矛盾解決グループ):
  - 予定列: `claims.conflict_group_id UUID NULL`
  - 予定親 table: `conflict_groups`
  - 予定 FK: `(tenant_id, project_id, conflict_group_id) -> conflict_groups(tenant_id, project_id, id)`
  - 目的: 同一 ResearchTask 内または同一 project 内で contradictory claims を束ね、reviewer が採用 / 保留 / reject を判断できる単位にする
  - P0 invariant: `claims` の project boundary は既存 `(tenant_id, project_id, research_task_id)` と `(tenant_id, project_id, id)` のまま維持し、P0 UI は contradiction grouping を表示しない
  - P1 activation TODO: `conflict_groups` table、`claims.conflict_group_id` nullable column、composite FK、cross-project negative test、read-only admin UI filter を同一 batch で追加

- `source_trust_registry` (EvidenceSource trust):
  - 予定列: `evidence_sources.trust_level TEXT NULL`
  - 予定列: `evidence_sources.trust_score DOUBLE PRECISION NULL`
  - 予定 enum/check: `trust_level in ('low','medium','high')`、`trust_score is null or trust_score between 0.0 and 1.0`
  - 目的: tenant-shared EvidenceSource に対し、source registry / manual review / future evaluator 由来の trust signal を保持する
  - P0 invariant: `evidence_sources` は project_id を持たない tenant-scoped table のまま。project binding は `claims` / `evidence_items` 経由で保証し、trust registry は citation_coverage source と混同しない
  - P1 activation TODO: registry adapter、trust_level / trust_score columns、source trust update audit event、UI read-only badge、trust registry drift test を Sprint 11 以降で追加

- Migration TODO comment:
  - P1 migration では `claims` / `evidence_sources` table comment に BL-0121 activation note を残す
  - P0 batch 4 では DB comment も追加しない。P0 DB schema drift を避け、Sprint 10 batch 0〜3 の migration chain を変更しないため

- 非ゴール:
  - P0 では automatic contradiction resolution を実装しない
  - P0 では source trust を citation_coverage, research_evidence_attachment_rate, evidence_set_hash の入力にしない
  - P0 では `allowed_data_class` / `payload_data_class` と trust_level を混同しない

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

- [x] batch 0: ADR-00002 update + ADR-00003 update proposed → BL-0113 (research_tasks) + BL-0114 (evidence_sources) schema DDL + migration
- [x] batch 1: BL-0115 (claims / evidence_items) DDL + BL-0116 PROV validation
- [x] batch 2: BL-0117 evidence_set_hash 正規化アルゴリズム + ContextSnapshot 結線
- [x] batch 3: BL-0118 Research-to-Ticket adapter + BL-0119 citation_coverage metric source
- [x] batch 4: BL-0120 read-only UI + BL-0121 P1 defer placeholder
- [x] batch 5: BL-0029c cross-project negative fixture
- [x] Sprint Exit: ADR-00002 update accepted 化 + Sprint Pack ## Review

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
- BL-0120: `(admin)/research/` と `(admin)/research/[id]/` が read-only で ResearchTask / Claim / EvidenceItem / EvidenceSource を表示し、POST/PATCH/DELETE UI を持たない
- BL-0120: secret_ref / capability token / raw api_key / provider raw payload は DOM に表示しない
- BL-0121: conflict_group_id / source trust registry は P1 defer placeholder として本 Pack に記録され、P0 DB schema には列追加しない

### QL-C 拡充 acceptance spec (R29 §5 QL-C、P-09 + P-18 反映、doc-only)

本 section は **QL-C run (2026-05-15、quality-loop/QL-C-research-eval-pack)** で追記した修正まとめ拡充 spec。**本 SP-010 では schema 追加なし** (acceptance spec のみ)、実 DDL / model / API は別 batch で landing する。

- **SearchRun acceptance spec** (Sprint 10 BL-0119 source / Sprint 11 BL-0126 consumer 共通 contract):
  - 必須 column: `tenant_id` / `project_id` / `research_task_id` / `id (UUID primary key)` / `query_canonical_hash (sha256)` / `retrieval_policy_version` / `hit_count` / `latency_ms` / `started_at` / `completed_at`
  - **column 名統一 (Codex R4 F-QLC-R4-001 P2 adopt)**: SearchRun の primary key は `id` (project convention: research_tasks / claims / evidence_sources と同じ)。外部参照側 (EvidenceSearchHit / RetrievalEvalRun 等) では `search_run_id` 列名で `search_runs.id` を参照。本 acceptance spec 全体で **table primary key = `id`、参照側 column = `<table>_id`** で統一。
  - **複合 FK (Codex F-QLC-001 P1 adopt)**: `(tenant_id, project_id)` だけでは不足。`(tenant_id, project_id, research_task_id) references research_tasks(tenant_id, project_id, id)` で **research_task が同一 project に属することを DB 境界で強制** (cross-project research_task 紐付け reject、BL-0029c 整合)。cross-project SELECT も全件 reject。
  - server-owned-boundary: `query_canonical_hash` は caller-supplied 不可、server 側で query 文字列を NFC + lower 化後 sha256 して生成
- **EvidenceSearchHit acceptance spec** (検索結果 ↔ Evidence 紐付け):
  - 必須 column: `tenant_id` / `project_id` / `search_run_id` / `claim_id` / `evidence_source_id` / `rank (int)` / `relevance_score (float [0,1])` / `ndcg_contribution (float)` / `is_grounding (bool)`
  - **rank constraint (Codex F-QLC-006 P2 adopt)**: `(tenant_id, project_id, search_run_id, rank)` unique + `CHECK (rank >= 1)`。同一 SearchRun 内の rank duplicate / 0 / 負値を全件 reject、top-k 集計 (recall@k / precision@k / nDCG) の安定再計算を保証。
  - 複合 FK (Codex R3 F-QLC-R3-002 P2 adopt: `evidence_sources` は **tenant-scoped** (`project_id` 列なし、既存 schema + ADR-00002 §7)、project-level FK は DDL 不可。`evidence_source` への FK は tenant-level、project binding は `search_run` / `claim` 経由で間接保証):
    - `(tenant_id, project_id, search_run_id) -> search_runs(tenant_id, project_id, id)` — project-scoped
    - `(tenant_id, project_id, claim_id) -> claims(tenant_id, project_id, id)` — project-scoped
    - `(tenant_id, evidence_source_id) -> evidence_sources(tenant_id, id)` — tenant-level only (evidence_sources は tenant-shared、project binding は claim 経由)
- **GroundingSupport acceptance spec** (生成 artifact ↔ Evidence 関連付け、citation_coverage source):
  - 必須 column: `tenant_id` / `project_id` / `generated_artifact_id` / `agent_run_id` / `claim_id` / `evidence_source_id` / `support_type (cite|paraphrase|quote)` / `confidence_score`
  - **複合 FK (Codex F-QLC-002 P1 + R2 F-QLC-R2-001 P2 adopt)**: `generated_artifact_id` だけでは不足 — `artifacts` table は project を直接持たず `agent_runs` 経由で project が決まる。FK column 数 mismatch を避けるため **2 段 FK** に明確分離:
    - `(tenant_id, project_id, agent_run_id) references agent_runs(tenant_id, project_id, id)` — run が同 project に属することを DB 強制 (3 col → 3 col)
    - `(tenant_id, run_id, generated_artifact_id) references artifacts(tenant_id, run_id, id)` — artifact が同 run に属することを DB 強制 (3 col → 3 col、Codex R4 F-QLC-R4-002 P2 adopt: 既存 `artifacts` schema の column 名は **`run_id`** (not `agent_run_id`)、既存 unique key `artifacts_uq_tenant_run_id` を直接参照。GroundingSupport の `agent_run_id` 列 (project binding 用、agent_runs 経由) と GroundingSupport の `run_id` 列 (artifact 同 run 強制用) が **同値** であることは追加 CHECK constraint で verify、または GroundingSupport で `agent_run_id` 単一列にし agent_runs 側で `id` = `run_id` を保証する設計を ADR-00002 update で議論)
    
    注: 単一 4-col FK `(tenant_id, project_id, agent_run_id, generated_artifact_id) -> artifacts(tenant_id, agent_run_id, id)` は **PostgreSQL の FK column 数一致制約 (4→3)** に違反、本 spec では採用しない。`artifacts` table に project_id 列を追加する代替案は ADR-00002 update で議論可能、現状 spec は agent_runs 経由の間接 binding を採用 (既存 artifacts schema 変更なし)。
  - **claim ↔ source binding through evidence_items (Codex R3 F-QLC-R3-003 + R4 F-QLC-R4-003 P2 adopt)**: `evidence_sources` が tenant-shared のため、unrelated source を valid claim に attach して citation_coverage を inflation する経路がある。**claim_id + evidence_source_id ペアが `evidence_items` table に存在する verify が必須**。ただし `evidence_items` の既存 unique key は `(claim_id, source_id, locator)` で 4-col `(tenant_id, project_id, claim_id, evidence_source_id)` 複合 FK は DDL 不可:
    - **代替設計**: GroundingSupport に `evidence_item_id (UUID)` 列追加 + `(tenant_id, project_id, evidence_item_id) references evidence_items(tenant_id, project_id, id)` 単一 FK
    - 加えて **CHECK constraint or trigger**: `evidence_items.claim_id == GroundingSupport.claim_id AND evidence_items.source_id == GroundingSupport.evidence_source_id` を verify (同 evidence_item が GroundingSupport の claim / source と一致することを DB 強制)
    - これで「project A の claim に project A の別 claim 用 evidence_source を attach」経路を reject (citation_coverage 信頼性確保)、かつ `evidence_items` の既存 multi-locator semantics (同 claim/source に複数 locator 保持可能) を破壊しない
  - 越境 negative test: 別 project の generated_artifact_id / claim_id / agent_run_id を関連付ける insert は全件 reject (artifact の run binding 経由 + claim ↔ source の evidence_items verify 経由で project 一致を二重 verify)
- **RetrievalEvalRun baseline acceptance spec** (Sprint 11 BL-0126 で集計、本 Sprint 10 では skeleton schema のみ documenting):
  - 必須 column: `tenant_id` / `project_id` / `eval_run_id` / `dataset_version_id (UUID FK)` / `agent_run_id` / `recall_at_k (json: {5: float, 10: float})` / `precision_at_k (json)` / `ndcg_at_k (json: {10: float})` / `citation_coverage (float [0,1])` / `grounded_answer_rate (float [0,1])` / `tool_trajectory_match (float [0,1])` / `metric_metadata (jsonb)`
  - **dataset_version_id FK 必須 (Codex F-QLC-003 P1 adopt)**: 文字列 `dataset_version` のみだと別 dataset の `eval_run_id` と任意 version 文字列の組合せが保存可能 → Anti-Gaming fixture/policy 分離 + AC-KPI 集計 trace 破壊。既存 eval schema (Sprint 11 BL-0122/0123) の `dataset_versions` table への `dataset_version_id UUID FK` 必須、`(tenant_id, eval_run_id, dataset_version_id)` 複合制約で run ↔ case dataset 一致を DB で強制。
  - **eval_run project binding (Codex R2 F-QLC-R2-002 + R3 F-QLC-R3-004 P2 adopt)**: `eval_runs` table は `project_id` を直接持たない (既存 schema)、`agent_runs(tenant_id, project_id, id)` 経由で project が決まる。RetrievalEvalRun に **`agent_run_id` 列追加** + 2 段複合 FK で project binding を DB 境界で強制:
    - `(tenant_id, project_id, agent_run_id) references agent_runs(tenant_id, project_id, id)` — project binding 強制
    - `(tenant_id, eval_run_id, agent_run_id) references eval_runs(tenant_id, id, agent_run_id)` — **eval_run と agent_run の同一性を強制** (R3 adopt + R4 F-QLC-R4-004 P2 adopt 追加):
      - `eval_runs` table に `agent_run_id` 列追加が必須 (ADR-00002 update で `eval_runs.agent_run_id` 追加 — eval_run が **single AgentRun に紐付く** semantics)
      - **加えて `eval_runs` に `unique (tenant_id, id, agent_run_id)` 制約追加が必須** (Codex R4 F-QLC-R4-004 P2 adopt): PostgreSQL FK 参照先は primary/unique key を要求、既存 `unique (tenant_id, id)` と `unique (tenant_id, id, dataset_version_id)` だけでは 3-col FK 不可。本 unique 制約追加で RetrievalEvalRun migration が `no unique constraint matching given keys` エラー回避
      - これで「project B の valid agent_run_id + project A の eval_run_id」混合経路を reject
    
    注: 上記 `eval_runs.agent_run_id` 列追加 + `unique (tenant_id, id, agent_run_id)` 制約追加は Sprint 11 BL-0122 (eval_runs schema) の前提条件、SP-011 受け入れ条件で別途明示する。
  - **metric_metadata 列必須 (Codex R2 F-QLC-R2-005 P2 adopt)**: `tool_trajectory_metric_kind` (`edit_distance` / `lcs_ratio` / `prefix_ratio`) を `metric_metadata jsonb` 列に保存。consumers が `tool_trajectory_match` 値の metric kind を区別可能にする (SP-011 で記録要求している metadata を SP-010 source contract 側に明示)。
  - **Anti-Gaming invariant 強化 (Codex R2 F-QLC-R2-003 P2 adopt)**: `dataset_versions.created_at` だけでは fixture creation commit author / timestamp を立証できない。`dataset_versions` table に **追加列必須**:
    - `fixture_commit_sha (varchar 40)` (fixture creation commit の git SHA)
    - `fixture_commit_author (text)` / `fixture_commit_authored_at (timestamptz)`
    - `policy_commit_sha (varchar 40)` (policy / runner 修正 commit の git SHA)
    - `policy_commit_author (text)` / `policy_commit_authored_at (timestamptz)`
    
    Sprint 11 BL-0129 CI gate は **fixture_commit_author != policy_commit_author** AND **fixture_commit_authored_at < policy_commit_authored_at** を DB-level invariant として verify (永続化された author/timestamp evidence から audit 可能)。
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

# frontend BL-0120
cd frontend
pnpm typecheck
pnpm lint
pnpm test -- research
```

## レビュー観点

- evidence_set_hash の **caller-supplied hash 経路がない** (server-owned-boundary §1)
- URL 正規化 invariant が NFC + percent-encoding + trailing slash + protocol downgrade をカバー
- PROV bundle hash が W3C PROV-DM minimal subset の 5 relation (wasGeneratedBy / used / wasAttributedTo / wasInformedBy / wasDerivedFrom) を含む (P0 では minimal でも extensibility 維持)
- 複合 FK が `(tenant_id, project_id, claim_id)` / `(tenant_id, project_id, evidence_source_id)` で閉じている
- ContextSnapshot.evidence_set_hash の nullable backward compat を破壊していない
- BL-0120 UI は GET-only client だけを使い、mutation button / form / Server Action を追加していない
- BL-0120 UI は secret_ref / capability token / raw api_key / raw provenance_json dump を DOM に出していない
- BL-0121 placeholder は P1 の conflict_group_id / source trust registry を明示しつつ、P0 DB migration chain を変更していない

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
- BL-0120 frontend は default dev project (`00000000-0000-4000-8000-000000000004`) を server env から解決する暫定 P0 admin surface。multi-project selector は P1 以降の Project Settings / route design で扱う

## 次スプリント候補

- Sprint 11 (Eval Harness + Sprint 7-9 carry-over) — AC-KPI-04 citation_coverage の Eval 統合
- P1 (post-P0): conflict_group_id / source trust registry / 自動矛盾解決

## 関連 ADR

- ADR-00002 (DB schema) — Research/Evidence schema 追加で update
- ADR-00003 (API contract) — Research-to-Ticket adapter API contract で update proposed → accepted

## Review

(SP-010 完了時に追記)

### QL-C 拡充 spec landing 記録 (2026-05-15、PR #11)

- **QL-C run branch**: `quality-loop/QL-C-research-eval-pack` (PR #11)
- **拡充内容**: P-09 (Pack reuse) + P-18 (Evidence/RAG/Eval metrics acceptance spec)
- **Codex multi-round adoption (累計 21 件、PR #11)**:
  - R1: 8 件 adopt (P1×5 + P2×3) — Anti-Gaming + AC-KPI 整合性
  - R2: 5 件 adopt (P2×5) — DDL reality + edge case
  - R3: 4 件 adopt (P2×4) — DDL reality + multi-agent rule + Anti-Gaming
  - R4: 4 件 adopt (P2×4) — DDL unique key + 既存 column 名整合
- **P0 / P1 全件 fix** (Anti-Gaming citation_coverage inflation 防御 + AC-KPI 既存 contract 整合 + cross-project DDL boundary)
- **doc-only scope 維持**: acceptance spec only、no test / code / DB schema / migration changes
- **defer note (R5+ で続く可能性のある DDL minor edge case)**: 残る minor edge case (Codex は毎 R で `evidence_items` unique key の細部 / artifacts の column 名 alias 等 minor DDL adjustment を発見する性質) は **Sprint 10 batch 1+ で実 DDL/migration 化時に Codex review 経由で adopt**。本 acceptance spec は P0 / P1 全件 + 主要 P2 fix で品質基準達成、minor DDL adjustment は実装時に確実に発覚する layer (DDL migration が `no unique constraint matching given keys` 等のエラーで止まるため fail-safe)。

### Sprint 10 batch 0 実装進捗 (R29 §5 QL-C R22 T-P2R1-013 反映)

- **batch_0_completed_commit**: `314b5bb` (BL-0113 research_tasks DDL/model/migration + BL-0114 evidence_sources DDL/model/migration、Codex R1-R2 clean)
- **既実装 BL**: `BL-0113` (research_tasks)、`BL-0114` (evidence_sources)
- **未着手 BL**: BL-0117〜BL-0130 (evidence_set_hash / Research-to-Ticket adapter / cross-project FK / UI 等、Sprint 10 batch 2+ で順次着手)
- **ADR 状態**: ADR-00002 + ADR-00003 は commit `3f11d00` で proposed 起票済 (frontmatter `status: proposed`)、accepted 化は Sprint 10 全 batch 完了時に別 run で実施

### Sprint 10 batch 1 実装進捗 (PR #19、2026-05-16、merge commit `5e6a38d`)

- **batch_1_merged_pr**: PR #19 (squash merge at 2026-05-16T00:02:47Z)
- **実装 BL**:
  - `BL-0115` (claims + evidence_items DDL/model/schemas/repositories/API)
  - `BL-0116` (PROV validation: W3C PROV-DM minimal subset、Counter O(N) unique id check + refs existence + id disjointness)
  - `BL-0029c (partial)` — cross-project negative test fixture の **claims + evidence_items 部分のみ** coverage 完了:
    - `test_claims_cross_project_select_and_insert_rejected`
    - `test_evidence_items_cross_project_select_and_insert_rejected`
    - `test_same_tenant_other_project_research_task_attach_rejected` (claims→research_tasks の cross-project attach negative)
    - `test_same_tenant_other_project_claim_attach_rejected` (evidence_items→claims の cross-project attach negative)
  - **BL-0029c の残作業 (Sprint 10 batch 2+ defer)**: `research_tasks` 自身への cross-project SELECT/INSERT/UPDATE/DELETE coverage は batch 2 で BL-0029c-b として実装する (ADR-00002 + P0 backlog AC-HARD-03 で要求される coverage の完全性は batch 2 完遂で達成)
- **新規 file (主要)**:
  - `migrations/versions/0017_claims_evidence_items.py` (composite FK + CHECK enum `relation` supports/contradicts/context + updated_at trigger + supporting index)
  - `backend/app/db/models/{claim,evidence_item}.py`
  - `backend/app/schemas/{claim,evidence_item}.py` (`Literal["supports","contradicts","context"]` relation + rls_ready force True validators)
  - `backend/app/repositories/{claim,evidence_item}.py` (project-scoped methods、server-owned UUID strip、secret scan UUID exclude、PROV validation in create + update、generic `create/update/list/get/delete` 全 override で `NotImplementedError`)
  - `backend/app/services/research/prov_validator.py`
  - `backend/app/api/{claims,evidence_items}.py` (`/api/v1/projects/{project_id}/...` prefix、`_TRACE_ID_RE` narrowed hex/UUID only、`sk-` prefix bypass 遮断)
  - `tests/db/test_schema_introspection.py` (4 new test methods including relation column check)
  - `tests/security/test_research_cross_project_negative.py`
  - `tests/contracts/test_provenance_json_schema.py`
  - `tests/services/research/test_prov_validator.py`
  - `tests/repositories/test_{claim,evidence_item}_repository.py`
- **Codex multi-round adoption (累計 46 件、R1-R13 全 round)**:
  - R1-R12 累計: P1×12 + P2×34 = 46 件 adopt
  - R13: reaction-only clean (👍 at 2026-05-16T00:01:13Z、新規 finding 0、新規 top-level review 0)
  - **主要 finding カテゴリ**:
    - server-owned-boundary: caller-supplied UUID / timestamp 削除 (`id` / `created_at` / `updated_at` strip)
    - generic `create/list/get/update/delete` 全 override で project-scoped 経路強制
    - `metadata` ↔ `metadata_` Pydantic alias rename 対応 (for/else loop + fallback assign)
    - secret scan with UUID type exclusion (`assert_no_raw_secret` is dict[str, JsonValue])
    - `_TRACE_ID_RE` narrowed to hex/UUID (block `sk-` prefix OpenAI key bypass)
    - PROV validation in create + update (bypass 経路遮断)
    - `relation` column in schema introspection test (R9 schema addition trace)
    - `rls_ready: true` invariant enforcement at schema + repository layer (4-layer defense)
- **CRITICAL invariant 維持**: AgentRun 16 状態 / ContextSnapshot 10 列 / SecretBroker atomic claim / Provider Compliance / actor/principal/approval / 5+ source enum integrity / composite FK `(tenant_id, project_id, id)` / RLS-ready metadata

### Sprint 10 batch 5 実装進捗 (PR #?? merge 後に commit hash 追記)

- **batch_5_merged_pr**: Sprint 10 batch 5 (本 PR)
- **実装 BL**: BL-0029c full integration (cross-tenant negative fixture 10 件追加)
- **新規 file**:
  - `eval/security/tenant_isolation/public_regression/research_tasks_cross_tenant_*.json` (4 件)
  - `eval/security/tenant_isolation/public_regression/claims_cross_tenant_*.json` (2 件)
  - `eval/security/tenant_isolation/public_regression/evidence_items_cross_tenant_select_app_role.json`
  - `eval/security/tenant_isolation/public_regression/evidence_sources_cross_tenant_select_app_role.json`
  - `eval/security/tenant_isolation/public_regression/research_to_ticket_cross_tenant_approval_request_id_rejected.json`
  - `eval/security/tenant_isolation/public_regression/citation_coverage_cross_tenant_research_task_id_rejected.json`
- **修正 file**:
  - `eval/security/tenant_isolation/manifest.json` — expected_count 1 → 11 + immutable_index 10 件追加
- **既存 cross-project 11 tests と本 cross-tenant 10 fixtures の併用で AC-HARD-03 coverage 完全化**
- **Sprint 11 BL-0158 で aggregator が消費**
- **frontmatter `status: completed` 化**: Sprint 10 batch 0-5 全 BL clean 達成、Sprint 10 closure 完了
