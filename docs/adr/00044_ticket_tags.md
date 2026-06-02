---
id: "ADR-00044"
title: "Ticket タグ/ラベルシステム (A-5)"
status: "proposed"
date: "2026-06-02"
accepted_at: null
deciders: ["t-ohga"]
adr_gate_criteria: [2, 3]
related_adr:
  - "ADR-00041 (N-1/N-2 ticket comments REST)"
  - "ADR-00037 (Q-3 soft-delete / assert_ticket_actionable)"
related_dd:
  - "DD-02 (データモデル / tenant・project 境界)"
related_sprints: []
supersedes: null
superseded_by: null
---

# ADR-00044: Ticket タグ/ラベルシステム (A-5)

最終更新: 2026-06-02

## 背景

UI 改善監査 A-5「タグ/ラベルシステム」。ticket を横断的に整理する手段が無く、status/priority/project
以外の分類軸が存在しない。tag (色付きラベル) を project スコープで管理し ticket に複数付与・絞り込み
できるようにする。

## 決定対象

- tag を保持する DB schema (ADR Gate#2)。
- tag CRUD + ticket への attach/detach REST endpoint (ADR Gate#3)。
- ticket read への tag 埋め込み + ticket 一覧の tag filter。

## 前提 / 制約

- 全 table は `tenant_id` を持ち、親子参照は `tenant_id` を含む複合 FK で閉じる (core.md §8)。
- 同一 tenant でも project 境界をまたぐ参照を禁止する。**ticket は自 project の tag のみ付与可能**。
- tag は human 起点の task metadata 編集 (task_write)。AI 出力直結ではなく approval 不要 (ticket status
  編集と同格)。
- tag name は raw secret を含めない (`assert_no_raw_secret`、comment と同じ境界)。
- P0 は単一 tenant。RLS 無効だが RLS-ready metadata + repository contract test を維持する。
- caller は `tenant_id` / `project_id` を指定不可。server が current project / 対象 ticket から解決する
  (caller-supplied 経路禁止、server-owned-boundary.md)。

## 採用案: 正規化 tags + ticket_tags join (project 境界を複合 FK で強制)

### schema (migration `0042_a5_ticket_tags`)

`tags` table:

| column | 型 | 制約 |
|---|---|---|
| `tenant_id` | bigint NOT NULL DEFAULT 1 | |
| `project_id` | uuid NOT NULL | |
| `id` | uuid NOT NULL | |
| `name` | text NOT NULL | 1-50 chars (CHECK `char_length` 1..50) |
| `color` | text NOT NULL | CHECK in 固定 palette enum (下記) |
| `created_at` | timestamptz NOT NULL DEFAULT now() | |

- PK: `(tenant_id, project_id, id)`。
- UNIQUE: `(tenant_id, project_id, name)` — project 内で tag 名重複禁止 (case 区別)。
- FK: `(tenant_id, project_id)` → `projects(tenant_id, id)` ON DELETE CASCADE。
- `color` palette (固定 enum、UI/caller 自由入力不可): `slate / red / orange / amber / green / teal / blue / purple / pink`。

`ticket_tags` join table:

| column | 型 | 制約 |
|---|---|---|
| `tenant_id` | bigint NOT NULL DEFAULT 1 | |
| `project_id` | uuid NOT NULL | |
| `ticket_id` | uuid NOT NULL | |
| `tag_id` | uuid NOT NULL | |
| `created_at` | timestamptz NOT NULL DEFAULT now() | |

- PK: `(tenant_id, project_id, ticket_id, tag_id)`。
- FK1: `(tenant_id, project_id, ticket_id)` → `tickets(tenant_id, project_id, id)` ON DELETE CASCADE。
- FK2: `(tenant_id, project_id, tag_id)` → `tags(tenant_id, project_id, id)` ON DELETE CASCADE。
- **両 FK が `(tenant_id, project_id)` を共有するため、ticket と tag は必ず同一 project に属する** (DB
  レベルで cross-project 付与を構造的に拒否)。
- index: `(tenant_id, project_id, tag_id)` (tag→ticket 逆引き / tag filter)。

### REST endpoint

- `GET /api/v1/projects/{project_id}/tags` — project の tag 一覧 (name 昇順)。
- `POST /api/v1/projects/{project_id}/tags` — tag 作成 (`{name, color}`)。name secret scan + palette 検証 +
  重複 409。
- `DELETE /api/v1/projects/{project_id}/tags/{tag_id}` — tag 削除 (ticket_tags は ON DELETE CASCADE)。
- `POST /api/v1/tickets/{ticket_id}/tags` — ticket に tag 付与 (`{tag_id}`)。assert_ticket_actionable
  (soft-deleted/archived 拒否) + tag が同 project 検証 (FK + service guard) + 重複は idempotent 200。
- `DELETE /api/v1/tickets/{ticket_id}/tags/{tag_id}` — ticket から tag 除去。
- `GET /api/v1/tickets`/`GET /api/v1/tickets/{id}`: response の `tags: [{id, name, color}]` を埋め込み
  (per-ticket、order by name)。
- `GET /api/v1/tickets?tag_id=<uuid>` — tag による絞り込み (ticket_tags join、同 project scope)。

### frontend

- `lib/api/tags.ts`: list/create/delete tag + attach/detach (zod schema)。
- ticket 一覧 / 詳細に tag chip 表示 (color)。詳細で tag 付与/除去 UI。tags page or settings で tag 管理。
- tickets 一覧に tag filter chip (既存 status/priority filter と並列)。

## 却下案

- **`tickets.tags text[]` 非正規化列**: 実装は軽いが、tag entity (color / rename / project-level 一覧 /
  usage) を持てず「システム」要件を満たさない。重複名・色の一貫性も保てない。却下。
- **`tickets.metadata` JSONB に tag を格納**: 型・FK 境界・検証が無く、cross-project 混入や raw secret
  混入を構造的に防げない。却下。
- **tenant-global な tag (project 非スコープ)**: project 境界を越え、不変条件 (同一 tenant 別 project
  cross reference 禁止) に反する。却下。

## リスク

- join table の複合 FK が 4 列 + 2 FK で複雑 → migration / ORM CheckConstraint の整合を test で固定。
- tag 削除時の ticket_tags cascade → 意図しない一括削除に見えるが、tag entity 削除なので想定内
  (rollback は tag 再作成 + 再付与)。
- tag filter の N+1 / 大量 tag → per-ticket tags は単一 join query で bulk 取得 (ticket list で tag を
  個別 fetch しない)。

## rollback 手順

- down migration: `ticket_tags` → `tags` の順に drop (FK 依存順)。tickets 本体は無変更なので tag 情報の
  喪失のみ (ticket データは保全)。
- frontend は tag UI を feature 非表示に戻せば degrade 可能 (tag chip 非表示)。

## 実装対象ファイル

- `migrations/versions/0042_a5_ticket_tags.py`: tags + ticket_tags 作成 (複合 FK / unique / CHECK /
  index)、down は逆順 drop。revision id ≤30 chars。
- `backend/app/db/models/tag.py` (新規): `Tag` / `TicketTag` ORM (複合 FK + CheckConstraint で
  name 長 / color palette を ORM にも反映)。
- `backend/app/domain/tag/` (新規): color palette enum (5+ source 整合: DB CHECK / ORM / Python Literal /
  Pydantic / pytest EXPECTED)。
- `backend/app/repositories/tag.py` (新規): tag CRUD + ticket_tags attach/detach + per-ticket bulk tags +
  tag filter。全 query に `tenant_id` + project scope。
- `backend/app/api/tags.py` (新規) or `tickets.py` 拡張: 上記 endpoint。name secret scan + palette 検証 +
  assert_ticket_actionable。
- `backend/app/api/tickets.py`: TicketRead に `tags` 埋め込み + list の `tag_id` filter。
- `tests/api/test_ticket_tags.py` (新規): route 登録 + schema no-secret + SQL introspection
  (tenant/project scope + tag filter predicate) + cross-project 付与 negative + palette 検証 +
  name secret 422 + archived/soft-deleted 拒否。
- `tests/db/` or introspection: 複合 FK / unique / CHECK の DDL 検証。
- `frontend/lib/api/tags.ts` (新規) + ticket 一覧/詳細の tag chip + 付与/除去 UI + tag filter。

## テスト指針

- **cross-project 付与 negative**: project A の ticket に project B の tag を付与する POST → reject
  (FK + service guard、全件 deny)。
- **tenant 越境 negative**: 別 tenant の tag/ticket_tags が list/read に混入しない。
- **palette 検証**: color が palette 外 → 422。5+ source enum 整合 (DB CHECK / ORM / Literal / Pydantic /
  pytest EXPECTED set)。
- **name secret 422**: tag name に secret canary / token marker → 422、永続化されない (assert_no_raw_secret)。
- **重複**: 同 project 同 name の tag 作成 → 409。同 ticket に同 tag 再付与 → idempotent (重複行を作らない)。
- **archived / soft-deleted**: archived project / soft-deleted ticket への tag 付与 → 拒否
  (assert_ticket_actionable)。tag 一覧 read は archived でも 200 (履歴 read)。
- **cascade**: tag 削除で ticket_tags が消えるが ticket 本体は残る。
- **per-ticket bulk**: ticket 一覧の tags は単一 join query (N+1 無し) を SQL introspection で確認。
