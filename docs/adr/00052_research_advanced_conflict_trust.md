---
id: "ADR-00052"
title: "Research Advanced — Conflict Groups + Domain Trust Registry + Freshness"
status: "accepted"
created_at: "2026-06-09"
updated_at: "2026-06-09"
related_sprints:
  - "SP-032_research_advanced"
  - "SP-010_research_evidence"
  - "SP-027_source_trust_registry"
supersedes: []
amends:
  - "ADR-00002 (DB schema) — Research/Evidence schema 拡張"
  - "ADR-00003 (API contract) — Research advanced read/write endpoints"
---

# ADR-00052: Research Advanced — Conflict Groups + Domain Trust Registry + Freshness

## 背景

SP-010 (Research/Evidence) で `research_tasks` / `claims` / `evidence_sources` / `evidence_items`
の 4 table と `evidence_set_hash` / PROV validation / Research-to-Ticket adapter を P0 first-class
として landing した。その際 SP-010 BL-0121 で **conflict_group_id (矛盾グループ)** と
**source/domain trust registry** を「P1 defer placeholder」として明記し、P0 では DB schema を
変更せず、P1 で activate する DB / service / UI contract を先に固定していた。

SP-032 はその BL-0121 placeholder の **P1 activation** である。具体的には:

1. **conflict_group_id + conflict_groups** — 同一 ResearchTask 内で互いに矛盾する claim を束ね、
   reviewer が `open` / `resolved` / `dismissed` を判断できる単位を作る。
2. **矛盾検出 (conflict detection)** — claim 単位の「反証 evidence を持つ claim (= 争点)」を
   **deterministic な SQL 集計** で surface する (AI 自動判定ではない)。
3. **domain trust registry** — tenant-scoped に domain → trust_tier (`low` / `medium` / `high`)
   を登録し、evidence source の信頼度評価の **domain-level signal** を保持する。
4. **freshness** — `claims.freshness_score` は SP-010 で nullable column として既存。SP-032 では
   **deterministic な freshness 再計算 helper** (evidence の published_at からの decay) を read-only
   advisory として surface する。stored column 自体は source-provided 値のまま (write-path / cron は不変)。

## 決定対象

Research advanced の DB schema (ADR Gate #2) + read/write API contract (ADR Gate #3)。

### SP-032 ↔ SP-027 の scope 境界 (重複回避)

両 Pack が "trust" に触れるため、以下で **物理的に非重複** に分割する:

| 項目 | 担当 Pack | 粒度 |
|---|---|---|
| `domain_trust_registry` (domain → tier) | **SP-032 (本 ADR)** | domain-level (tenant-scoped registry) |
| `evidence_sources.trust_level` / `trust_score` (per-source) | **SP-027 (将来 T2-1)** | source-level (domain registry から派生) |
| citation render mode / provenance 可視化 | **SP-027 (将来 T2-1)** | UI render |
| conflict_groups / 矛盾検出 / freshness 再計算 | **SP-032 (本 ADR)** | research_task-level |

SP-027 は本 ADR の `domain_trust_registry` を入力に **per-source trust** を派生させる
(将来 ADR で `evidence_sources` への列追加 + 派生ロジックを定義)。本 ADR では
`evidence_sources` schema を変更しない。

## 前提 / 制約

- P0 invariant 不変: AgentRun 16 状態 / 3 blocked_reason / ContextSnapshot 10 列 / Provider
  Compliance 13 reason_code / SecretBroker raw secret 非保存 / tenant・project 複合 FK。
- additive migration のみ (table 2 件追加 + `claims` への nullable 列 1 件追加)。破壊的変更なし。
- `audit_events.event_type` は **free-text (`sa.Text`)** であり閉じた enum ではない (cf.
  `agent_run_events.event_type` は閉じた enum)。新 audit event_type 追加は 5+ source enum
  integrity 更新を要しない。
- write は **human (project owner) actor のみ**。AI 出力を直接 mutation に接続しない
  (これは reviewer の判断 metadata であり artifact pipeline を経由しない project metadata 操作。
  A-5 tags / A-6 assignee / M-3 settings と同じ owner-gated CRUD pattern)。
- conflict 検出は **deterministic SQL** であり AI 自動 resolution ではない (SP-010「P0 では
  automatic contradiction resolution を実装しない」を継承、検出は争点 surfacing に限定)。
- domain trust は project boundary を持たない **tenant-scoped** registry (evidence_sources と同じ scope)。

## 採用案

### 1. `conflict_groups` table (research_task-scoped、project 複合 FK で閉じる)

| column | 型 | 制約 |
|---|---|---|
| `id` | UUID PK | server-owned (`uuid_generate_v4()`) |
| `tenant_id` | BigInteger | NOT NULL DEFAULT 1、FK→tenants RESTRICT |
| `project_id` | UUID | NOT NULL |
| `research_task_id` | UUID | NOT NULL |
| `title` | Text | NOT NULL、CHECK length 1-200 |
| `status` | Text | NOT NULL DEFAULT `'open'`、CHECK in (`open`,`resolved`,`dismissed`) |
| `resolution_note` | Text | NULL、CHECK (status<>`resolved` OR resolution_note IS NOT NULL) — **resolved のみ note 必須**、dismissed は任意。length 1-2000 when present (R1 F-002) |
| `created_by_actor_id` | UUID | NOT NULL |
| `metadata` | JSONB | rls_ready default |
| `created_at` / `updated_at` | timestamptz | now() default + updated_at trigger |

制約:
- FK `(tenant_id, project_id, research_task_id) → research_tasks(tenant_id, project_id, id)` RESTRICT
- unique `(tenant_id, id)`
- unique `(tenant_id, project_id, id)`
- **unique `(tenant_id, project_id, research_task_id, id)`** — claims の 4-col FK target
- CHECK status enum (5+ source 整合: DB CHECK + ORM CheckConstraint + Python Literal + Pydantic + pytest)
- CHECK title length / resolution_note length + status coupling
- index `(tenant_id, project_id, research_task_id)` — list by research_task

hard delete は提供しない (`status='dismissed'` が soft-removal)。append-only/audit 姿勢を維持。

### 2. `claims.conflict_group_id UUID NULL` (additive 列)

- FK `(tenant_id, project_id, research_task_id, conflict_group_id) →
  conflict_groups(tenant_id, project_id, research_task_id, id)` **ON DELETE RESTRICT**
- 4-col 複合 FK により、claim の conflict_group は **同一 (tenant, project, research_task)** に
  強制束縛される (cross-research-task / cross-project assignment を DB 境界で reject)。
- nullable = 未 assign。1 claim は最大 1 group に所属。
- conflict_groups は hard delete しないため orphan / SET NULL 問題は発生しない (RESTRICT で十分)。

### 3. `domain_trust_registry` table (tenant-scoped、project boundary なし)

| column | 型 | 制約 |
|---|---|---|
| `id` | UUID PK | server-owned |
| `tenant_id` | BigInteger | NOT NULL DEFAULT 1、FK→tenants RESTRICT |
| `domain` | Text | NOT NULL、CHECK length 1-253 + hostname format (lowercase, scheme/path なし) |
| `trust_tier` | Text | NOT NULL、CHECK in (`low`,`medium`,`high`) |
| `rationale` | Text | NULL、CHECK length 1-1000 when present |
| `created_by_actor_id` | UUID | NOT NULL |
| `metadata` | JSONB | rls_ready default |
| `created_at` / `updated_at` | timestamptz | now() default + updated_at trigger |

制約:
- unique `(tenant_id, id)`
- unique `(tenant_id, domain)` — domain ごとに最大 1 entry
- CHECK trust_tier enum (5+ source 整合)
- CHECK domain format (server 側で NFC + lowercase 正規化、scheme/path/空白を reject)

domain は **server-owned 正規化** (caller 自由入力の raw URL ではなく registrable hostname に正規化)。
DELETE はあり (registry entry、FK 依存なし)。

### 4. 矛盾検出 (deterministic、read-only)

`ConflictDetectionService.list_candidates(tenant, project, research_task)`:
- claim ごとに `evidence_items.relation='contradicts'` の件数を集計。
- `contradicting_evidence_count > 0` の claim を **conflict candidate** として返す
  (supporting / contradicting / context の各件数も付与)。
- 純 SQL aggregation。AI / 外部呼び出しなし。group の自動生成はしない (reviewer が判断)。

### 5. freshness 再計算 (deterministic、read-only advisory)

純関数 `compute_freshness(published_at, retrieved_at, as_of) -> float`:
- evidence の age (日数) から半減期 decay: `0.5 ** (age_days / HALF_LIFE_DAYS)`、clamp [0,1]。
- `HALF_LIFE_DAYS = 365` (定数、ADR 固定)。published_at 欠如時は retrieved_at に fallback。
- claim の computed_freshness = supporting evidence の最も新しい published_at (なければ retrieved_at)
  を基準に算出。supporting evidence ゼロなら null。
- read-only advisory として research-advanced summary に付与。stored `claims.freshness_score`
  (source-provided) は **不変** (write-path / cron は SP-010 通り未実装、本 ADR でも追加しない)。

### 6. API contract (ADR Gate #3、project-scoped、write は owner-gated)

conflict groups (`/api/v1/projects/{project_id}/research-tasks/{research_task_id}/conflict-groups`):
- `POST ""` create (owner) → ConflictGroupRead
- `GET ""` list
- `PATCH "/{group_id}"` update title/status/resolution_note (owner)
- `POST "/{group_id}/claims/{claim_id}"` assign claim (owner)
- `DELETE "/{group_id}/claims/{claim_id}"` unassign claim (owner)

conflict candidates + freshness (read-only):
- `GET "/conflict-candidates"` deterministic detection
- `GET "/research-advanced"` summary: conflict_groups + candidates + per-claim computed_freshness +
  evidence source ごとの domain_trust 適用結果

domain trust (`/api/v1/domain-trust`、tenant-scoped、write は owner-gated):
- `POST ""` register (owner、domain server 正規化 + upsert reject on duplicate) → DomainTrustRead
- `GET ""` list
- `PATCH "/{id}"` update trust_tier/rationale (owner)
- `DELETE "/{id}"` remove (owner)

全 write endpoint は `require_project_owner` (project-scoped) または tenant owner gate を通す。
self-service AI agent / service actor は write 不可 (human owner only)。

### 7. audit events (free-text event_type)

- `conflict_group_created` / `conflict_group_updated`
- `conflict_group_claim_assigned` / `conflict_group_claim_unassigned`
- `domain_trust_registered` / `domain_trust_updated` / `domain_trust_removed`

payload に `tenant_id` / `actor_id` / 対象 id / `correlation_id` / `trace_id` / `timestamp`。
raw secret なし。`title` / `rationale` / `domain` は secret scan を通してから保存 (claims と同じ
`assert_no_raw_secret` 経路)。

### 8. frontend

- `(admin)/domain-trust` — owner-gated CRUD (tags pattern、list + create + edit + delete)。
- `(admin)/research/[id]` 拡張 — read-only 表示 (conflict candidates / conflict groups /
  per-claim computed_freshness / evidence domain trust badge) + owner action (create group / assign /
  set status)。`lib/domain/*` = client-safe pure zod、`lib/api/*` = server fetch fail-closed `{ok}`。

## R1 plan-review 反映 (codex-plan-review R1、20 findings 全 adopt、2026-06-09)

実装着手前に edge-case 仕様を固定する (採用案を上書き / 補足する正本)。

### 複合 FK / DB 制約

- **(F-001) MATCH SIMPLE + nullable FK 挙動**: `claims.conflict_group_id IS NULL` = 未割当 →
  PostgreSQL 既定 `MATCH SIMPLE` で FK 検査 skip。non-NULL 時のみ 4 列全体で
  `(tenant_id, project_id, research_task_id, conflict_group_id)` を強制。`claims` の
  `tenant_id` / `project_id` / `research_task_id` は既に NOT NULL のため、nullable は
  `conflict_group_id` のみ。DB introspection + assign API negative test の期待値に明記。
- **(F-002) resolution_note coupling**: CHECK は `status <> 'resolved' OR resolution_note IS NOT NULL`。
  `resolved` のみ note 必須、`dismissed` は任意 (誤作成の dismiss に prose 強制を避ける)。
  present 時は char_length 1-2000。API / UI / test に「resolved は note 必須、dismissed は任意」を反映。
- **(F-011) created_by_actor_id FK**: 既存 pattern (`research_tasks` 等) に合わせ
  `(tenant_id, created_by_actor_id) → actors(tenant_id, id)` FK (ON DELETE RESTRICT) を張る。
  conflict_groups / domain_trust_registry 双方。
- **(F-014) 文字列正規化**: title / resolution_note / rationale は server 側で **NFC 正規化 + 前後 trim**
  後に検証、whitespace-only は reject。length は **char_length (文字数)**、DB CHECK は `char_length(...)`
  (tags pattern 準拠)、Pydantic と DB で同単位。境界値 test (空白のみ / 改行 / 200/201) を入れる。
- **(F-012) metadata contract**: `metadata` JSONB は **server-owned** (`rls_ready=true` default)、
  client mutation で受け付けない (request schema に含めない)。P0 では RLS 無効、`rls_ready` は
  RLS-ready metadata invariant の維持目的。SP-032 では user data を metadata に入れない。
- **(F-015) updated_at trigger test**: DB introspection / repository test に created_at/updated_at
  default + update trigger (更新時刻が進む) の確認を追加。

### domain 正規化 (server-owned)

- **(F-003 / F-010 / F-018) 正規化仕様**: `domain` は **hostname-level (exact match)**、eTLD+1 畳み込みなし
  (`www.example.com` と `example.com` は別 entry)。SP-027 の per-source lookup で parent fallback は
  将来検討。`domain_normalize(input)` 仕様:

  | 入力 | 挙動 |
  |---|---|
  | 大文字 | lowercase 化 |
  | 前後空白 | trim |
  | 末尾 dot (`example.com.`) | 除去 |
  | scheme 付き (`https://...`) | reject (`invalid_domain`) |
  | path / query / fragment / `@` userinfo | reject |
  | port (`example.com:8080`) | reject |
  | 空 / label 過長 (>63) / 全体 >253 / 連続 dot / 先頭末尾 hyphen | reject |
  | 非 ASCII (IDN) | **P1 では reject** (punycode 変換は将来拡張、残リスク記録) |
  | IPv4 / IPv6 / localhost | reject (hostname registry の対象外) |
  | 許可 char set | `^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$` |

  DB CHECK は length + 緩い char set (`domain = lower(domain)` + hostname char)、厳密 format は
  service 層の `domain_normalize` で enforce (純関数 + 全ケース unit test)。
- **(F-013) POST duplicate / PATCH immutable**: POST は **正規化後 domain** で uniqueness 判定、
  既存と衝突は **409 Conflict** (`error_code: domain_trust_duplicate`)。PATCH は `trust_tier` /
  `rationale` のみ変更可、**domain 変更不可** (request schema に domain を含めない)。

### freshness 純関数 (deterministic)

- **(F-006 / F-009) 時刻正規化 + fallback 単位**:
  - 全 datetime を **aware UTC** に正規化。naive datetime は **UTC とみなす** (stored timestamps は
    tz-aware のため通常発生しないが、純関数の防御として固定)。
  - evidence ごとに `effective_at = published_at ?? retrieved_at`。`published_at` と `retrieved_at`
    両方欠如の evidence は除外。
  - claim の `computed_freshness` = supporting evidence の **`max(effective_at)`** を基準に decay。
    supporting evidence ゼロ (または全除外) → **null**。
  - `age_days = max(0, (as_of - effective_at).days)`。**未来日付** (`effective_at > as_of`) は
    `age_days = 0` → freshness `1.0` (clamp)。`HALF_LIFE_DAYS = 365`、`freshness = 0.5 ** (age_days / 365)`、
    clamp [0,1]。境界値 test: age 0 / 365 (=0.5) / 大 age / published_at 欠如 / 未来日付 / supporting ゼロ。

### 矛盾検出 (deterministic SQL)

- **(F-008) candidate query 論理仕様**: claim ごとに `evidence_items` を join し
  `relation='contradicts'` の件数 (`contradicting_count`) と `supports` / `context` の件数を集計。
  **`contradicting_count > 0` のみ candidate**、supporting/context-only は除外。research_task 内に
  evidence はあるが relation 全 NULL/未付与のケースは、summary に **`relation_coverage`**
  (= relation 付き evidence_item を持つ claim 比率) を返し、UI が「争点なし」と「relation 未整備」を
  区別できるようにする。

### 認可 matrix (F-004 / F-005 / F-017)

P0 では owner は単一 (構成済み P0 owner = tenant owner)。`require_project_owner` は project_id を取らない
**global P0-owner gate** (構成済み P0 owner のみ、service/agent/provider/github_app/別 human/未認証は
401/403)。

| endpoint | read | write |
|---|---|---|
| conflict_groups (project route) | 認証 actor (tenant) | `require_project_owner` + `require_active_project` |
| conflict-candidates / research-advanced (project route、read-only) | 認証 actor (tenant) | — |
| domain_trust (tenant route) | 認証 actor (tenant) | `require_project_owner` (tenant-level P0 owner) |

- **forward-compat 注記**: P0 は単一 owner のため project owner = tenant owner で escalation なし。
  multi-project / multi-owner (P1+) では domain_trust を **tenant-admin gate** (per-project owner と
  区別) に分離する必要がある。本 ADR で明記し SP-027 / 将来 ADR の前提とする。
- negative test: cross-project (assign / read / list / update に別 project id)、cross-tenant、
  service/agent/non-owner の write 403、wiring drift guard (`inspect.signature(...).default.dependency`)。
- **(F-017) frontend 認可 UX**: non-owner は owner action UI を非表示 + server も 403 (二重)。
  domain trust badge は取得失敗時 `match_type='invalid'` / `trust_tier=null` で **unknown 表示**
  (画面全体 fail-closed ではなく badge 単位で degrade)、conflict groups / candidates loader は
  fail-closed `{ok}` で全体 degrade。

### audit (F-007 / F-020)

- audit payload は **ID + 変更フィールド名 + 正規化済み domain** のみ。**raw title / resolution_note /
  rationale 本文は payload に含めない**。secret scan (`assert_no_raw_secret`) は **request body 保存前**
  に実行、scan failure は 400 (`error_code: ...payload_validation_failed`)。
- **(F-020) event_type 同期 test**: audit_events.event_type は free-text (閉じた enum 化しない) だが、
  各 mutation test で **期待 event_type 文字列の exact match** を検証 (typo 防止)。ADR §7 の event_type
  一覧と service emitted value を軽量 test で同期。

### read model (F-018)

- research-advanced summary の evidence trust 適用結果: `{evidence_source_id, domain,
  trust_tier: low|medium|high|null, match_type: exact|none|invalid}`。`none` = 未登録、`invalid` =
  domain 正規化不能 (URL parse 失敗等)、`exact` = registry hit。tenant mismatch は構造上発生しない
  (tenant-scoped query)。

### 運用 (F-016 / F-019)

- **(F-019) migration head**: 実装開始時に `alembic heads` を確認 (現在 head `0044_sp028_webhook_events`、
  次 `0045_sp032_research_advanced` = 28 chars ≤ 30)。並行 worktree で番号衝突した場合は revision id +
  down_revision を調整。
- **(F-016) rollback 補足**: `claims.conflict_group_id` に書込済みデータがある状態の downgrade は
  assignment 情報を喪失する。rollback 前に (1) API write 停止 → (2) conflict assignment を export/backup
  → (3) migration down。audit_events の event 履歴は残るが参照先 (conflict_groups row) は消える点を許容。

## 却下案

- **AI auto-detection / auto-resolution of conflicts**: AI 出力直結禁止 + SP-010「P0 では automatic
  contradiction resolution を実装しない」に反する。検出は deterministic SQL に限定、resolution は
  reviewer 判断。
- **conflict_groups を project-scoped (research_task 跨ぎ)**: P1 first increment では research_task 内に
  限定し FK を 4-col で締める方が boundary が明確。cross-research-task conflict は将来拡張。
- **domain trust を project-scoped**: evidence_sources が tenant-scoped のため domain trust も
  tenant-scoped が自然。project ごとの override は将来 SP-027 で検討。
- **freshness の write-path / cron 自動更新**: SP-010 が Sprint 11.5 へ defer 済。本 ADR は read-only
  advisory に限定し stored column を変更しない (drift / 性能リスク回避)。
- **conflict_group hard delete + SET NULL FK**: 多列 FK の SET NULL は NOT NULL 列 (research_task_id)
  も null 化して破綻 (SP-028 で実証済)。hard delete を提供せず `dismissed` status で代替、FK は RESTRICT。

## リスク

- conflict candidate 検出が evidence relation に依存するため、relation 未付与の research では空になる
  (現状の research adapter が relation を付与する範囲に依存)。→ candidate ゼロは「争点なし」と
  「relation 未整備」を UI で区別する文言を付ける。
- domain 正規化の取りこぼし (subdomain / punycode / IDN)。→ server 正規化を保守的に (lowercase +
  hostname char set + length)、未対応 IDN は将来拡張として残リスク記録。
- 4-col 複合 FK の migration 失敗 (target unique 制約欠如)。→ conflict_groups に
  `(tenant_id, project_id, research_task_id, id)` unique を先に作成してから claims FK を追加。
- owner gate 配線漏れ (write が non-owner に通る)。→ `require_project_owner` を全 write に適用 +
  wiring drift guard test (`inspect.signature(...).default.dependency`、A-6/SP-028 先例)。

## rollback 手順

- migration `0045_sp032_research_advanced` を 1 件 down で revert:
  - `claims.conflict_group_id` FK + 列を drop
  - `domain_trust_registry` table を drop
  - `conflict_groups` table を drop (FK 依存順: claims FK → conflict_groups)
- service / API / frontend は code 削除のみ (DB 影響なし)。
- 運用中 rollback は事前 backup / maintenance window 前提 (新規 table のため既存データ影響は
  `claims.conflict_group_id` 列のみ、全 null なら無害)。

## 実装対象ファイル

- `migrations/versions/0045_sp032_research_advanced.py`
- `backend/app/db/models/conflict_group.py` / `domain_trust.py` / `claim.py` (列追加)
- `backend/app/domain/research/conflict_status.py` / `trust_tier.py` (Literal enum)
- `backend/app/schemas/conflict_group.py` / `domain_trust.py` / `research_advanced.py`
- `backend/app/repositories/conflict_group.py` / `domain_trust.py`
- `backend/app/services/research/conflict_detection.py` / `freshness.py` / `domain_normalize.py`
- `backend/app/api/conflict_groups.py` / `domain_trust.py` / `research_advanced.py` + router 配線
- `frontend/lib/domain/research-advanced.ts` / `frontend/lib/api/research-advanced.ts`
- `frontend/app/(admin)/domain-trust/page.tsx` (+ components) / `(admin)/research/[id]` 拡張
- tests: DB introspection / migration / repository / service (conflict detection + freshness 純関数 +
  domain normalize) / API contract / cross-project negative / owner gate wiring guard / frontend vitest

## テスト指針

- **5+ source enum integrity**: conflict status (`open`/`resolved`/`dismissed`) + trust_tier
  (`low`/`medium`/`high`) を DB CHECK + ORM + Literal + Pydantic + pytest `EXPECTED_*` で exact set 比較。
- **複合 FK 境界**: claim を別 research_task の conflict_group に assign → reject。別 project →
  reject。cross-tenant → reject。
- **owner gate**: service / agent / non-owner actor の write → 403。wiring drift guard。
- **deterministic 純関数**: `compute_freshness` を境界値 (age 0 / half-life / 大 age / published_at
  欠如) で固定。`domain_normalize` を大文字 / scheme 付き / path 付き / 空白で正規化検証 + reject。
- **conflict detection**: contradicting evidence を持つ claim のみ candidate。supporting only は除外。
- **secret scan**: title / rationale / domain に raw secret → reject (`assert_no_raw_secret`)。
- **audit**: 各 mutation で対応 event_type + raw secret なし payload。
- **frontend**: domain-trust CRUD + research detail の conflict/freshness/trust 表示 (fail-closed loader)。
