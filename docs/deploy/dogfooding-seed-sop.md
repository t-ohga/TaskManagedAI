# Dogfooding Seed SOP

最終更新: 2026-05-22 (SP-012-10 Batch D 起票)

## 0. 目的

TaskManagedAI 自身の残作業 (Sprint Pack / ADR / BL) を **Ticket として DB に seed 投入**し、TaskManagedAI を **TaskManagedAI 自身で管理** する dogfooding 運用試験の操作手順書。

実装: `backend/app/cli/dogfooding_seed.py` (SP-012-10 Batch A/B/C で完成、PR #113/#114/#116)。

## 1. 投入対象

dogfooding seed CLI は次の 3 source から Ticket を生成し、`tenant_id=1` + `project_id=00000000-0000-4000-8000-000000000004` (default project、`seeds/initial.py` 由来) に投入する:

| source | location | 件数 (2026-05-22) | slug prefix |
|---|---|---:|---|
| Sprint Pack | `docs/sprints/SP-*.md` | 27 | `dogfooding-sprint-` |
| ADR | `docs/adr/*.md` | 29 | `dogfooding-adr-` |
| BL (P0 バックログ) | `docs/実装計画/P0_バックログ.md` Markdown table | 211 | `dogfooding-bl-` |
| **合計** | | **267** | |

各 Ticket は `metadata.dogfooding_source = {type, id, ...}` を持ち、re-run idempotency 識別に使う。

## 2. 前提条件

- Mac local docker compose stack (api + worker + postgres + redis + frontend) が起動済
- alembic upgrade head 完了 (`0019_artifacts_project_id` 含む最新 migration apply 済)
- 基本 seed (`backend/app/seeds/runner.py`) 適用済 (default actor + workspace + project + welcome ticket)

## 3. CLI 起動方法

### 3.1 dry-run (DB 変更なし、計画 only)

```bash
# host から (uv installed):
uv run python -m backend.app.cli.dogfooding_seed --dry-run

# docker compose 経由 (api container):
docker compose -f docker-compose.yml -f docker-compose.dev.yml --env-file .env.local exec api \
  uv run python -m backend.app.cli.dogfooding_seed --dry-run
```

期待出力:

```
Discovered 27 Sprint Pack files (27 parsed), 29 ADR files (29 parsed), 211 BL rows parsed from P0 backlog.
DRY-RUN Sprint Pack: {'rows_added': 27, 'rows_updated': 0, 'rows_unchanged': 0, 'failures': []}
DRY-RUN ADR: {'rows_added': 29, 'rows_updated': 0, 'rows_unchanged': 0, 'failures': []}
DRY-RUN BL: {'rows_added': 211, 'rows_updated': 0, 'rows_unchanged': 0, 'failures': []}
```

### 3.2 apply (DB に投入)

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml --env-file .env.local exec api \
  uv run python -m backend.app.cli.dogfooding_seed --apply
```

期待出力: 同上 (DRY-RUN → APPLIED、failures: [])

## 4. idempotent re-run

CLI を再 apply しても重複 row は投入されない (`slug` 一意性 + `metadata.dogfooding_source.id` 識別)。Sprint Pack の frontmatter status / title / description 変更時のみ `rows_updated` に反映。

```bash
# 2 回目 apply (変更なしの場合)
docker compose exec api uv run python -m backend.app.cli.dogfooding_seed --apply
# expected: rows_added=0, rows_updated=0 (or 変更分だけ), rows_unchanged=267
```

## 5. UI 上での visualize

apply 後、`http://localhost:3900/tickets` で 267 Ticket を一覧表示 (`limit=200` で 200 件 + remaining)。

各 Ticket は:

- **slug**: `dogfooding-{sprint,adr,bl}-<id-kebab>`
- **title**: `Sprint Pack: SP-NNN_xxx` / `ADR: ADR-NNNNN - title` / `BL: BL-NNNN - title (80 chars)`
- **status**: open / in_progress / closed / cancelled (source の status から map)
- **description**: 各 source の summary + frontmatter / row meta

UI で Ticket 詳細 (`/tickets/<id>`) で `description` 全文 + `metadata.dogfooding_source` 内訳確認可能。

## 6. cleanup (seed 削除、運用 reset 用)

dogfooding seed Ticket をすべて削除する場合:

```sql
-- docker compose exec postgres psql -U taskmanagedai -d taskmanagedai
delete from tickets
 where tenant_id = 1
   and slug like 'dogfooding-%';
-- expected: DELETE 267
```

注意: `tickets` テーブルは production 運用前提のため、本 SQL は **dev / test 環境専用**。production deployment 前には dogfooding seed を完全削除推奨 (P3+ で production-ready 化時の前提)。

## 7. drift 検出

Sprint Pack / ADR / BL 追加・更新時に CLI を re-run し、`rows_added` / `rows_updated` で drift を確認:

- `rows_added > 0`: 新規 Sprint Pack / ADR / BL が追加された (要 review、Sprint 着手前 prerequisite)
- `rows_updated > 0`: 既存の frontmatter status / title / description / metadata 変更検出 (rotate 等)
- `failures > 0`: parse 失敗 (frontmatter schema drift)、`docs/sprints/` / `docs/adr/` / `docs/実装計画/P0_バックログ.md` の正本確認

## 8. trace

- 実装 PR: #113 (Batch A Sprint Pack) + #114 (Batch B ADR) + #116 (Batch C BL)
- Sprint Pack: `docs/sprints/SP-012-10_dogfooding_seed.md` (SP-012-10 light Sprint Pack)
- CLI: `backend/app/cli/dogfooding_seed.py`
- test: `tests/cli/test_dogfooding_seed.py` (19 contract test、frontmatter parse 整合性 verify)

## 9. P0.1+ 拡張 (defer)

将来予定 (SP-012-10 Batch D 外、別 Sprint Pack):

- BL → Sprint Pack の `ticket_relations` parent/child link 投入 (現状は metadata 内で表現)
- Sprint Pack `## Review` 章の change-log を `audit_events` に投入 (履歴 visualize)
- Ticket UI 編集 → docs/sprints/*.md reverse update 自動化 (read-only seed のみ現状)
- P0.1+ backlog (`docs/実装計画/00_ロードマップ.md`) 別 file から seed 投入
