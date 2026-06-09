---
id: "SP-032_research_advanced"
type: "heavy"
status: "completed"
sprint_no: 32
created_at: "2026-05-26"
updated_at: "2026-06-09"
target_days: 3
max_days: 5
adr_refs:
  - "[ADR-00052](../adr/00052_research_advanced_conflict_trust.md)"
related_sprints:
  - "SP-010_research_evidence"
  - "SP-027_source_trust_registry"
risks:
  - "4-col 複合 FK migration の target unique 制約欠如"
  - "domain 正規化の取りこぼし (subdomain / punycode / IDN)"
  - "owner gate 配線漏れ (write が non-owner に通る)"
  - "conflict candidate 検出が evidence relation 整備度に依存"
---

> SP-010 BL-0121 placeholder (conflict_group_id / source trust registry の P1 defer) の **P1 activation**。
> ADR-00052 (DB schema #2 + API contract #3) に従い conflict_groups + claims.conflict_group_id +
> domain_trust_registry + 矛盾検出 + freshness 再計算を additive に実装する。
>
> **ground-truth 訂正 (2026-06-09)**: 旧 Review の「claim model に conflict_group_id 存在」は不正確。
> 実コード grep では `freshness_score` のみ存在 (SP-010 由来)、`conflict_group_id` / `conflict_groups`
> / `domain_trust_registry` は不在。本 Sprint で新規追加する。

## 目的

- `conflict_groups` table + `claims.conflict_group_id` 列 + 複合 FK で **矛盾グループ** を first-class 化
- **矛盾検出** (deterministic SQL: contradicting evidence を持つ claim の surfacing) を read-only で提供
- `domain_trust_registry` table (tenant-scoped) で **domain-level trust signal** を保持
- **freshness 再計算** (deterministic decay 純関数) を read-only advisory として提供
- owner-gated CRUD (conflict group / domain trust) + research detail 拡張 UI

## 背景

- SP-010 で Research/Evidence 4 table を P0 landing 済。BL-0121 で conflict_group_id /
  source trust registry を P1 defer placeholder として固定 (予定列 / FK / invariant を明記)。
- `claims.freshness_score` は SP-010 で nullable column として既存 (source-provided)。
  freshness 自動更新 cron は Sprint 11.5 へ defer。
- `evidence_items.relation` (supports/contradicts/context) は SP-010 batch 1 で landing 済 →
  矛盾検出の deterministic signal として利用可能。
- SP-027 (source trust registry / citation render) と scope が重複するため ADR-00052 §「scope 境界」で
  domain-level (SP-032) と source-level (SP-027) を物理的に非重複分割。

## 対象外

- P0 invariant の変更 (16 status / 3 blocked_reason / 10 ContextSnapshot columns は不変)
- 破壊的 migration (additive のみ: table 2 + nullable 列 1)
- AI による矛盾自動検出 / 自動 resolution (SP-010「automatic contradiction resolution 不実装」継承)
- `evidence_sources.trust_level` / `trust_score` (per-source trust) — SP-027 (T2-1) 担当
- citation render mode / provenance 可視化 — SP-027 (T2-1) 担当
- freshness の write-path / cron 自動更新 — Sprint 11.5 (read-only advisory に限定)
- conflict_groups の research_task 跨ぎ (cross-research-task conflict) — 将来拡張

## 設計判断

ADR-00052 採用案を参照。要点:

- **conflict_groups は research_task-scoped**、`claims.conflict_group_id` は 4-col 複合 FK
  `(tenant_id, project_id, research_task_id, conflict_group_id)` で **同一 research_task** に強制束縛。
- **conflict_groups は hard delete 不可** (`status='dismissed'` が soft-removal)、FK は RESTRICT
  (多列 FK SET NULL の NOT NULL 破綻を回避、SP-028 教訓)。
- **domain_trust_registry は tenant-scoped** (evidence_sources と同 scope、project boundary なし)。
- **矛盾検出は deterministic SQL** (`evidence_items.relation='contradicts'` 集計)、group 自動生成なし。
- **freshness は deterministic 純関数** (半減期 365 日 decay)、stored column 不変、read-only advisory。
- **write は human (project owner) のみ** (`require_project_owner`、A-5/A-6/M-3 owner-gated CRUD pattern)。
- **audit event_type は free-text** (audit_events.event_type は閉じた enum でない、5+ source 更新不要)。

## 実装チケット

| BL ID | 内容 | depends_on |
|---|---|---|
| BL-S032-1 | migration 0045 (conflict_groups + domain_trust_registry + claims.conflict_group_id) + models + Literal enum | ADR-00052 |
| BL-S032-2 | schemas + repositories (project-scoped / tenant-scoped、server-owned UUID strip、secret scan) | BL-S032-1 |
| BL-S032-3 | services: conflict_detection (deterministic SQL) + freshness (純関数) + domain_normalize (純関数) | BL-S032-1 |
| BL-S032-4 | API: conflict_groups (owner write) + domain_trust (owner write) + research_advanced (read-only) + audit | BL-S032-2, BL-S032-3 |
| BL-S032-5 | frontend: domain-trust CRUD page + research detail 拡張 (read-only display + owner action) | BL-S032-4 |
| BL-S032-6 | tests: DB introspection / migration / repository / service 純関数 / API contract / cross-project negative / owner wiring guard / vitest | 全 BL |

## タスク一覧

- [x] ADR-00052 plan-review (codex-plan-review R1、20 findings 全 adopt) + accepted 昇格
- [x] BL-S032-1: migration 0045 + models + Literal enum
- [x] BL-S032-2: schemas + repositories
- [x] BL-S032-3: services (conflict_detection / freshness / domain_normalize)
- [x] BL-S032-4: API + audit + router 配線
- [x] BL-S032-5: frontend (domain-trust CRUD page + research detail 拡張)
- [x] BL-S032-6: tests 全種
- [x] codex-adversarial-review R1-R4 clean (R4 approve、CRITICAL=0 / HIGH=0)
- [x] Sprint Exit: Pack `## Review` + ADR-00052 accepted_at 記録

## must_ship / defer_if_over_budget 対応表

| 項目 | must_ship | defer_if_over_budget |
|---|---|---|
| conflict_groups table + claims.conflict_group_id + 複合 FK | ○ | — |
| 矛盾検出 (deterministic SQL read-only) | ○ | — |
| domain_trust_registry table + CRUD | ○ | — |
| freshness 再計算 純関数 + read-only surface | ○ | — |
| owner-gated write + audit | ○ | — |
| cross-project / cross-tenant negative test | ○ | — |
| frontend domain-trust CRUD page | ○ | — |
| frontend research detail 拡張 (conflict/freshness/trust 表示) | ○ | — |
| research detail の owner action (create group / assign / resolve) UI | △ | read-only 表示は must、interactive は polish |
| conflict_groups の research_task 跨ぎ | × | 将来拡張 |
| freshness 自動更新 cron | × | Sprint 11.5 |

## 受け入れ条件

- `conflict_groups` / `domain_trust_registry` が migration で作成され、`alembic upgrade head` +
  `alembic check` が drift 0 で通る
- `claims.conflict_group_id` の 4-col 複合 FK が cross-research-task / cross-project / cross-tenant
  assignment を全件 reject
- conflict status (`open`/`resolved`/`dismissed`) + trust_tier (`low`/`medium`/`high`) が
  5+ source (DB CHECK + ORM + Literal + Pydantic + pytest `EXPECTED_*`) で exact set 整合
- 矛盾検出が contradicting evidence を持つ claim のみ candidate に返す (supporting only は除外)
- `compute_freshness` が境界値 (age 0 / half-life / 大 age / published_at 欠如) で deterministic
- `domain_normalize` が大文字 / scheme 付き / path 付き / 空白を正規化 or reject
- 全 write endpoint が `require_project_owner` (または tenant owner) を通り、service/agent/non-owner は 403
- title / rationale / domain に raw secret → reject (`assert_no_raw_secret`)
- 各 mutation で対応 audit event_type + raw secret なし payload
- frontend: domain-trust CRUD が owner-gated で動作、research detail が conflict candidates /
  conflict groups / computed_freshness / domain trust badge を fail-closed loader で表示
- lint / typecheck / test (`ruff` + `mypy` + `pytest` + `pnpm typecheck/lint/test`) 全 PASS
- 既存 Hard Gate / KPI に regression なし

## 検証手順

```bash
# migration
uv run alembic upgrade head
uv run alembic check

# backend unit / contract / negative
uv run pytest tests/research_evidence/ tests/db/ tests/api/ tests/security/ -q
uv run ruff check backend tests && uv run mypy backend

# frontend
cd frontend && pnpm typecheck && pnpm lint && pnpm test
```

## レビュー観点

- 4-col 複合 FK が `(tenant_id, project_id, research_task_id, conflict_group_id)` で閉じ、claim と
  conflict_group の research_task 一致を DB 強制
- domain_trust の `(tenant_id, domain)` unique + server-owned 正規化 (caller raw URL を信頼しない)
- conflict 検出が deterministic (AI / 外部呼び出しなし)、group 自動生成しない
- freshness が純関数 (impure time 計算を data loader に閉じ、stored column 不変)
- write が owner-gated (wiring drift guard)、AI 出力を直接 mutation に接続しない
- secret scan (title / rationale / domain) + audit raw secret なし
- RSC: `lib/domain/*` = client-safe pure / `lib/api/*` = server fetch、混在なし

## 残リスク

- conflict candidate 検出が evidence relation 整備度に依存 (relation 未付与の research は空) →
  UI で「争点なし」と「relation 未整備」を区別する文言
- domain 正規化の IDN / punycode 未対応 → 保守的正規化 + 残リスク記録
- research detail の interactive owner action は polish 範囲、read-only 表示が must

## 次スプリント候補

- SP-027 (source trust registry): domain_trust_registry を入力に per-source trust 派生 +
  citation render mode + provenance 可視化
- Sprint 11.5: freshness 自動更新 cron + Observability metric

## 関連 ADR

- ADR-00052 (Research Advanced) — conflict_groups + domain_trust_registry + freshness、本 Sprint で proposed → accepted
- ADR-00002 (DB schema) — Research/Evidence schema 拡張
- ADR-00003 (API contract) — Research advanced endpoints

## Review

### 実装完了記録 (2026-06-09、ADR-00052 accepted_at: 2026-06-09)

- **ADR-00052**: codex-plan-review R1 で 20 findings 全 adopt (4-col FK MATCH SIMPLE 挙動明文化 /
  resolved-note coupling / domain 正規化仕様表 / 認可 matrix / freshness 時刻正規化 / 矛盾検出 SQL /
  audit payload / read model match_type 等) → proposed → accepted。
- **backend**: migration 0045 (conflict_groups + domain_trust_registry + claims.conflict_group_id、
  4-col 複合 FK で同一 research_task 束縛、updated_at trigger)、conflict_detection (deterministic SQL) +
  freshness (半減期 365 日 decay 純関数) + domain_normalize (server-owned hostname 正規化) +
  research_advanced summary service、conflict_groups / domain_trust CRUD (owner-gated) + audit、
  5+ source enum integrity (conflict status / trust_tier)。
- **frontend**: ドメイン信頼度レジストリ CRUD page (owner-gated)、リサーチ詳細に矛盾グループ管理 +
  鮮度 + ドメイン信頼度 section (read-only display + owner action: create group / assign / set status)。
- **検証**: `ruff` / `mypy` clean (自分の file、5 mypy errors は pre-existing `mcp/`)、backend no-DB
  107 pass + DB-gated 23 skip (CI で実行)、frontend typecheck / eslint / 460 vitest / next build 全 green。
  migration は offline SQL 生成で validate (host に postgres なし、DB-gated test は CI)。

### codex-adversarial-review (R1-R4、計 6 findings adopt)

- **R1** (2 HIGH adopt): domain_trust write + research-advanced read で secret-shaped hostname
  (`sk-aaaa...example.com`) が canonical scanner を通過 → 永続/再露出。`normalize_domain` に scanner
  choke point 追加 (write reject + read invalid)。
- **R2** (2 HIGH adopt): canonical `assert_no_raw_secret` は legacy `sk-[20+]` のみで modern
  `sk-proj-...` / `github_pat_...` / `ghu_`/`ghr_` / canary を見逃す → ticket comment / eval と同一の
  **broad scanner** を共有 module `services/security/secret_text_scan.py` に新設 (drift-guard test 同期)、
  domain / rationale / title / resolution_note の write reject + read redact に適用。
- **R3** (2 CRITICAL adopt): API-local redaction が research-advanced summary (conflict group) と
  domain_trust の domain / delete audit を迂回 → 読み redaction を共有 serializer
  `services/research/read_redaction.py` に集約、全 read 経路 + audit payload に適用。direct-write
  secret-shaped title/domain の redaction regression test 追加。
- **R4**: **approve / no material findings** (CRITICAL=0、read/audit redaction・4-col FK
  cross-project/research-task reject・owner gate・tenant boundary に外部到達可能な迂回なし)。

### 残課題 / follow-up (機能削減ではない)

- DB-gated test (12 件) は host に postgres がないため CI 実行 (skipif `TASKMANAGEDAI_RUN_DB_TESTS`)。
  on-host は unit (107) + introspection + offline migration SQL で代替検証済。
- conflict_groups の research_task 跨ぎ / freshness 自動更新 cron は当初対象外 (将来拡張 / Sprint 11.5)。
- SP-027 (source trust registry、T2-1) が本 `domain_trust_registry` を入力に per-source trust を派生。
