---
id: "ADR-00053"
title: "Source Trust Registry — per-source trust + citation render mode + provenance visualization"
status: "accepted"
created_at: "2026-06-09"
updated_at: "2026-06-09"
related_sprints:
  - "SP-027_source_trust_registry"
  - "SP-032_research_advanced"
  - "SP-010_research_evidence"
supersedes: []
amends:
  - "ADR-00002 (DB schema) — evidence_sources に per-source trust 列追加"
  - "ADR-00003 (API contract) — source trust / provenance read + trust set endpoint"
  - "ADR-00052 (Research Advanced) — domain_trust_registry を入力に per-source trust 派生"
---

# ADR-00053: Source Trust Registry

## 背景

SP-010 BL-0121 placeholder で `evidence_sources.trust_level` / `trust_score` (source-level trust) を
P1 defer と明記していた。SP-032 (ADR-00052) で **domain-level** の `domain_trust_registry` (tenant-scoped) を
landing 済。SP-027 はその上に **per-source (per-EvidenceSource) trust** を載せ、さらに citation の表示
モードと provenance の可視化を追加する。ADR-00052 §scope 境界で domain-level=SP-032 / source-level=SP-027 と
分割済。

## 決定対象

per-source trust の DB schema (ADR Gate #2) + read/write API (ADR Gate #3) + provenance 構造化 read +
citation render mode (frontend device-local)。

## 前提 / 制約

- P0 invariant 不変。additive migration のみ (`evidence_sources` への nullable 列 2 件追加)。
- `evidence_sources` は **tenant-scoped** (project_id を持たない、SP-010/ADR-00002)。trust write は
  tenant owner (`require_project_owner` = 構成済み P0 owner) のみ。
- `trust_level` は SP-032 の `TrustTier` (low/medium/high) を **reuse** (enum 重複追加しない)。
- per-source trust の **effective 値** は deterministic に解決: manual override > domain 由来 (SP-032
  registry) > 未設定。AI / 外部呼び出しなし。
- provenance 可視化は **raw provenance_json を展開しない** (SP-010 invariant)。`prov_validator.ProvBundle`
  で validate 済の構造を抽出し、id 等を broad secret scanner で redact した安全な構造のみ返す。
- citation render mode は device-local UI preference (localStorage、cookie 化せず server 非依存、
  M-2/P-2 の SecurityError-safe accessor 踏襲)。DB を持たない。

## 採用案

### 1. evidence_sources additive 列 (migration 0046)

| column | 型 | 制約 |
|---|---|---|
| `trust_level` | Text | NULL、CHECK (null or in low/medium/high) — manual override (TrustTier reuse) |
| `trust_score` | Double | NULL、CHECK (null or 0.0-1.0) — manual numeric score |

- 5+ source enum integrity: `trust_level` は `TrustTier` (DB CHECK + ORM + Literal + Pydantic + pytest)。
- 既存 row は全 null (= 未設定、domain 由来 fallback)。backward compat 破壊なし。

### 2. effective source trust 派生 (read-side deterministic)

`resolve_effective_source_trust(source, domain_registry)` → `EffectiveSourceTrust`:
- `source.trust_level` が non-null → `{trust_level, trust_score, origin: "manual"}`。
- else `domain_from_url(canonical_url)` → registry lookup:
  - hit → `{trust_level: tier, trust_score: null, origin: "domain", domain, match_type: "exact"}`。
  - miss → `{trust_level: null, origin: "none", domain, match_type: "none"}`。
- domain 正規化不能 → `{trust_level: null, origin: "invalid", domain: null, match_type: "invalid"}`。
- `origin` enum: `manual` / `domain` / `none` / `invalid`。`domain_from_url` は SP-032 の secret-shaped
  reject を継承 (secret-shaped host は invalid)。

### 3. provenance 構造化 view (read-side、raw 非展開)

`build_provenance_view(provenance_json)` → `ProvenanceView`:
- `prov_validator.ProvBundle` で validate。invalid → `{valid: false}` (raw を返さない)。
- valid → activities / entities / agents (id + type) + relations (5 種: wasGeneratedBy / used /
  wasAttributedTo / wasInformedBy / wasDerivedFrom、各 from/to) を構造として抽出。
- 全 id を `redact_if_secret` (SP-032 broad scanner) で redact してから返す (PROV id への secret 混入を
  read で再露出しない defense-in-depth)。

### 4. API (ADR Gate #3)

- `PATCH /api/v1/evidence-sources/{id}/trust` (owner-gated、tenant-scoped): manual `trust_level` /
  `trust_score` の set/clear。audit `evidence_source_trust_set` (raw secret なし)。
- `GET /api/v1/projects/{p}/research-tasks/{rt}/source-trust`: research task の各 evidence source の
  effective trust list (read、認証 actor)。
- `GET /api/v1/projects/{p}/research-tasks/{rt}/claims/{claim_id}/provenance`: claim の構造化 PROV view
  (read、認証 actor、claim が research_task に属することを 404 で確認)。
- research-advanced summary (ADR-00052) は **変更しない** (契約安定、SP-027 は別 endpoint で追加)。

### 5. citation render mode (frontend device-local)

`lib/citation-render-mode.ts`: `compact` / `detailed` / `provenance` の device-local preference
(localStorage、SecurityError-safe accessor)。research 詳細の evidence/citation 表示モードを制御:
- `compact`: source 件数 + trust tier サマリ。
- `detailed`: source ごとに trust badge (origin: 手動/ドメイン由来/未設定) + locator。
- `provenance`: detailed + claim ごとの構造化 PROV view。

### 6. frontend

- research 詳細に citation render mode トグル + per-source effective trust badge + owner-gated
  「信頼度を設定」(manual override) + (mode=provenance 時) PROV 構造 viz。
- `lib/domain/source-trust.ts` (client-safe zod) / `lib/api/source-trust.ts` (server fetch fail-closed)。

### 7. audit (free-text event_type)

- `evidence_source_trust_set` / `evidence_source_trust_cleared`。payload: ID + trust_level + origin、
  raw secret なし。

## R1 plan-review 反映 (codex-plan-review R1、18 findings 全 adopt、2026-06-09)

実装着手前に契約・invariant を固定する (採用案を上書き / 補足する正本)。

### 認可 / tenant boundary (F-001 / F-002 / F-009)

- `require_project_owner` は project_id を取らない **global P0-owner gate** (構成済み P0 owner = tenant
  owner、P0 では単一)。tenant-scoped `evidence_sources` の trust write に対し project ambiguity は無い
  (domain_trust = SP-032 と同一)。multi-owner (P1+) で tenant-admin gate に分離する forward-compat 注記は ADR-00052 §認可 matrix を継承。
- **lookup は actor tenant 内に限定**。別 tenant の `evidence_source_id` / `research_task_id` / `claim_id`
  は **404** (存在秘匿)、owner 不足は **403**。read endpoint 2 種は認証 actor (tenant) +
  `research_task` が `(tenant, project)` に属することを確認 (`_require_research_task` 再利用、404)、
  provenance は claim が research_task に属することを確認 (404)。
- 認可 negative test: service/agent/non-owner の trust write → 403、cross-tenant source/claim → 404、
  wiring drift guard (`inspect.signature(...).default.dependency`)。

### manual trust invariant (F-004 / F-005 / F-016)

- manual override は **`trust_level` 必須**、`trust_score` は任意 (0.0-1.0)。両 null = 未設定/clear。
  **`trust_score` 単独 (level null + score 非 null) は 400** + DB CHECK
  `trust_level IS NOT NULL OR trust_score IS NULL`。
- domain 由来 origin は **常に `trust_score = null`** (registry は score を持たない)。`trust_score` は
  manual-only。
- PATCH request: `{trust_level: "low"|"medium"|"high"|null, trust_score?: number|null}`。
  clear = `{trust_level: null, trust_score: null}`。response = **effective trust** (origin 含む)。

### domain fallback semantics (F-006 / F-007)

- lookup input は `evidence_sources.canonical_url` (NOT NULL)。`domain_from_url` (SP-032、secret-shaped
  host reject 継承) で hostname 抽出 → 正規化不能は `origin: "invalid"`。
- registry lookup は SP-032 と同じ **exact hostname match** (eTLD+1 / subdomain / wildcard 畳み込みなし)。
  `match_type`: `exact` / `none` / `invalid`。subdomain registry を無視する理由は SP-032 exact 仕様の継承。

### source-trust list 導出 (F-008 / F-017 / F-018)

- 導出経路: `research_task → claims → evidence_items → evidence_sources` の **distinct** (SP-032
  research-advanced の evidence join と同一)。順序は **source id asc** で stable。
- research_task の source 数は bounded のため pagination なし (P1)。
- frontend が research-advanced (ADR-00052) と source-trust を合成する際、**source-trust fetch 失敗は
  fail-closed** (trust UI を unavailable 表示)、summary 自体は成功扱い (独立 degrade)。

### provenance view (F-010 / F-011 / F-012)

- `ProvBundle` validate。invalid → **HTTP 200 `{valid: false, reason: "invalid_schema"}`** (固定 reason
  enum、raw path / raw id / validator detail は返さない)。
- valid → activities / entities / agents (id + type) + relations (5 種 enum: wasGeneratedBy / used /
  wasAttributedTo / wasInformedBy / wasDerivedFrom、from/to)。**返却する全 string field (id / type) を
  `redact_if_secret` (SP-032 broad scanner) で redact**。relation 種別は 5-enum 固定。
- size 上限: nodes ≤ 200、relations ≤ 500、id/type ≤ 128 chars。超過時は切り捨て + `truncated: true`。
  large input の view builder test を追加。

### citation render mode (F-013 / F-014)

- default mode = **`detailed`**。SSR は default を描画、client mount 後に localStorage 値へ反映
  (hydration mismatch 回避)。localStorage **SecurityError-safe** (M-2/P-2 同型: accessor 自体 throw でも
  crash しない)、storage 不可時は in-memory / default。invalid stored value は default。
- render mode は **非監査・非権限・非契約の表示 preference** (証跡 / レビュー結果の意味を変えない)。将来
  per-actor / per-project へ拡張する場合も localStorage key は初期値として扱う。

### audit allowlist (F-003)

- audit payload は **固定 allowlist**: `evidence_source_id` / `action` (`set`|`clear`) / `trust_level` /
  `trust_score` / `origin` のみ。**domain / canonical_url / locator / raw request body / previous raw
  value / provenance_json を含めない**。`AuditEventRepository.append` の `assert_no_raw_secret` で二重防御。

### 用語 (F-015)

- 「5+ source enum integrity」= **5 箇所以上の enum source (DB CHECK / ORM CheckConstraint / Python
  Literal / Pydantic / pytest `EXPECTED_*`) で `TrustTier` の 3 値 (low/medium/high) を exact set 一致**
  させる (cardinality でなく source 数)。`trust_level` は SP-032 `TrustTier` を reuse。

## 却下案

- **research-advanced summary を拡張して source trust を載せる**: 直近 ship した ADR-00052 endpoint の
  契約 (frontend zod) を破壊する。別 endpoint で追加し契約を安定させる。
- **citation render mode を per-project DB 設定**: device-local UI preference で十分 (個人ごとの表示
  好み)。DB schema を増やさない。将来 multi-user で per-actor 設定が要れば再検討。
- **provenance の raw JSON dump 表示**: SP-010 invariant 違反。validate 済の構造 + redact のみ。
- **trust_level に独自 enum**: SP-032 `TrustTier` を reuse (重複 enum の drift 回避)。
- **AI による source trust 自動スコアリング**: AI 出力直結禁止。manual + domain 由来の deterministic のみ。

## リスク

- domain 由来 trust の精度は domain_trust_registry の整備度に依存 → UI で origin (手動/ドメイン由来/未設定)
  を明示。
- provenance id redaction の過剰 redaction (正当な id が secret-shaped) → 影響は表示のみ (機能破壊なし)、
  残リスク記録。
- evidence_sources の trust write が owner gate 漏れ → `require_project_owner` + wiring drift guard test。

## rollback 手順

- migration `0046_sp027_source_trust` を down で revert (`evidence_sources.trust_level` / `trust_score`
  列 drop)。trust データは消えるが、未設定 = domain 由来 fallback のため機能継続。service/API/frontend は
  code 削除のみ。

## 実装対象ファイル

- `migrations/versions/0046_sp027_source_trust.py`
- `backend/app/db/models/evidence_source.py` (列追加) + `backend/app/schemas/evidence_source.py`
- `backend/app/schemas/source_trust.py` / `provenance_view.py`
- `backend/app/repositories/evidence_source.py` (trust set method)
- `backend/app/services/research/source_trust.py` (effective 派生) / `provenance_view.py` (構造抽出)
- `backend/app/api/evidence_source_trust.py` (PATCH trust) + `source_trust.py` (read) + router 配線
- `frontend/lib/domain/source-trust.ts` / `lib/api/source-trust.ts` / `lib/citation-render-mode.ts`
- `frontend/app/(admin)/research/[id]` 拡張 + components
- tests: DB introspection / migration / repository / service (effective 派生 + provenance 純関数) /
  API contract / owner gate wiring / secret redaction / frontend vitest

## テスト指針

- effective trust: manual > domain > none > invalid の全分岐 + secret-shaped host → invalid。
- provenance view: valid PROV → 構造抽出、invalid → `{valid: false}` (raw 非露出)、secret-shaped id → redact。
- trust_level 5+ source enum (TrustTier) 整合。trust_score 範囲 CHECK。
- owner gate: service/agent/non-owner の trust write → 403、wiring drift guard。
- cross-tenant: 別 tenant の evidence_source trust set → reject。
- citation render mode: localStorage SecurityError-safe (M-2/P-2 同型) + mode 切替。
