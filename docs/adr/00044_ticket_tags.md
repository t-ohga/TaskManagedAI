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
- **境界語彙 (Codex plan-review R2 MEDIUM)**: `tenant_id` / `actor_id` は server-resolved (auth context)。
  request **body の `project_id` / `tenant_id` は禁止** (extra field reject)。**path の `project_id` は
  caller-selected scope** だが、server が (a) current actor の tenant と一致、(b) 対象 ticket / tag の
  project と一致、を検証する (path / target mismatch は 404)。caller が body で boundary を上書きする経路は
  signature レベルで持たない (server-owned-boundary.md)。

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
| `deleted_at` | timestamptz NULL | **soft-delete** (tag 削除は hard delete cascade でなく deleted_at set、復旧可能。Codex plan-review MEDIUM) |

- PK: `(tenant_id, project_id, id)`。
- **partial UNIQUE**: `(tenant_id, project_id, name) WHERE deleted_at IS NULL` — active tag のみ project 内
  で名前重複禁止 (soft-deleted は除外し、同名 tag の後日再作成を許可。secret_refs active 1 制約と同 pattern)。
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

### REST endpoint (全て既存の project-scoped 契約に揃える、Codex plan-review HIGH-1)

既存 ticket API は `/api/v1/projects/{project_id}/...` 配下で tenant+project 境界を path で強制し、
tenant-wide な `GET /api/v1/tickets` shorthand は実装しない方針 (リポジトリ既定)。tag も同契約に揃え、
unscoped route (`/api/v1/tickets/{id}/tags` 等) は作らない。path の `project_id` と対象 ticket/tag の
project 一致を **service guard + DB 複合 FK の両方**で検証する。

- `GET /api/v1/projects/{project_id}/tags` — project の active tag 一覧 (deleted_at IS NULL、name 昇順)。read-only。
- `POST /api/v1/projects/{project_id}/tags` — tag 作成 (`{name, color}`)。**active-project guard** +
  name secret scan (domain 境界) + palette 検証 + active 重複 409。
- `DELETE /api/v1/projects/{project_id}/tags/{tag_id}` — tag **soft-delete** (deleted_at set)。
  **active-project guard** + 削除前 affected ticket 件数 preflight + `config_changed` audit (actor /
  project / tag_id / affected_ticket_count)。ticket_tags 行は保持 (復旧可能)。
- `POST /api/v1/projects/{project_id}/tags/{tag_id}/restore` — soft-deleted tag の復元 (deleted_at クリア)。
  **active-project guard** + audit。**同名の active tag が既に存在する場合は 409** (名前衝突、先に rename が
  必要、Codex plan-review R2 HIGH)。ticket_tags は保持済のため復元で分類が即座に戻る。partial UNIQUE が
  衝突を DB レベルでも担保。
- `POST /api/v1/projects/{project_id}/tickets/{ticket_id}/tags` — ticket に tag 付与 (`{tag_id}`)。
  **active-project guard** + assert_ticket_actionable + tag が同 project かつ active 検証 (FK + service
  guard) + 重複は idempotent 200。
- `DELETE /api/v1/projects/{project_id}/tickets/{ticket_id}/tags/{tag_id}` — ticket から tag 除去。
  **active-project guard** + assert_ticket_actionable。
- `GET /api/v1/projects/{project_id}/tickets` / `.../tickets/{id}`: response の `tags: [{id, name, color}]`
  を埋め込み (per-ticket、active tag のみ、order by name、単一 join で bulk)。
- `GET /api/v1/projects/{project_id}/tickets?tag_id=<uuid>` — tag による絞り込み (ticket_tags join、
  path project_id scope。tag_id も同 project 検証)。

### archive freeze (Codex plan-review HIGH-2)

tag create / soft-delete / attach / detach の **全 mutation** に active-project guard
(`TicketRepository.assert_project_active` 相当の `FOR UPDATE` guard) を必須化。archived project では
create/delete/attach/detach が **409**。read-only な tag list / ticket tags embed のみ archived 200
(履歴 read)。ADR-00037 archive = project child-write read-only 化と整合。

### secret scan を domain 境界に集約 (Codex plan-review HIGH-3)

tag 作成は API ではなく **domain/repository の単一 create 関数を必ず通す**。その中で正規化後の name と
payload 全体を `assert_no_raw_secret` に通す。base CRUD で直接 INSERT する経路は作らない。MCP / bridge /
seed / 管理 script が repository を直接呼んでも raw secret tag name が DB に入らないよう、
**repository / service direct-call の negative test** も追加 (comment 設計と同方針)。

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
- tag 削除は **soft-delete** (deleted_at) なので ticket_tags は保持され、誤削除しても restore (deleted_at
  クリア) で分類情報を復元可能 (Codex MEDIUM 対応)。削除前に affected ticket 件数を preflight し audit に残す。
- tag filter の N+1 / 大量 tag → per-ticket tags は単一 join query で bulk 取得 (ticket list で tag を
  個別 fetch しない)。active tag のみ embed (deleted_at IS NULL)。

## rollback 手順

- **運用 rollback (誤削除)**: soft-delete なので `deleted_at` クリアで即復元。ticket_tags も保持済。
- **schema rollback (down migration)**: `ticket_tags` → `tags` の順に drop (FK 依存順)。tickets 本体は
  無変更なので tag 情報の喪失のみ (ticket データは保全)。down は tag 全 row を drop するため、運用中の
  rollback は **事前 backup / maintenance window** 前提を明記 (単なる drop で安全と扱わない)。
- frontend は tag UI を feature 非表示に戻せば degrade 可能 (tag chip 非表示)。

## 実装対象ファイル

- `migrations/versions/0042_a5_ticket_tags.py`: tags + ticket_tags 作成 (複合 FK / unique / CHECK /
  index)、down は逆順 drop。revision id ≤30 chars。
- `backend/app/db/models/tag.py` (新規): `Tag` / `TicketTag` ORM (複合 FK + CheckConstraint で
  name 長 / color palette を ORM にも反映)。
- `backend/app/domain/tag/` (新規): color palette enum (5+ source 整合: DB CHECK / ORM / Python Literal /
  Pydantic / pytest EXPECTED)。
- `backend/app/repositories/tag.py` (新規): tag CRUD (create は name secret scan を内包する単一関数) +
  ticket_tags attach/detach + per-ticket bulk tags + tag filter + active-project guard (`FOR UPDATE`) +
  soft-delete + **restore (同名 active 衝突 409)** + 削除 preflight (affected count)。全 query に
  `tenant_id` + project scope、active は deleted_at IS NULL。
- `backend/app/api/tags.py` (新規) or `tickets.py` 拡張: project-scoped endpoint (HIGH-1) + restore endpoint。
  palette 検証 + active-project guard (HIGH-2) + assert_ticket_actionable。**request body は `tag_id` /
  `name` / `color` のみ許可し `project_id` / `tenant_id` を extra field reject** (R2 MEDIUM)。secret scan は
  repository 境界に委譲 (HIGH-3)。
- `backend/app/api/tickets.py`: TicketRead に `tags` (active のみ) 埋め込み + list の `tag_id` filter (同 project)。
- `tests/api/test_ticket_tags.py` (新規): route 登録 + schema no-secret + SQL introspection
  (tenant/project scope + tag filter predicate + deleted_at IS NULL) + cross-project 付与 negative +
  palette 検証 + **name secret 422 (API) + repository direct-call の secret negative (HIGH-3)** +
  **archived project の create/delete/attach/detach 409 (HIGH-2)** + soft-delete/restore + idempotent attach。
- `tests/db/` or introspection: 複合 FK / partial unique / CHECK の DDL 検証。
- `frontend/lib/api/tags.ts` (新規) + ticket 一覧/詳細の tag chip + 付与/除去 UI + tag filter + tag 管理 UI。

## テスト指針

- **cross-project 付与 negative**: project A の ticket に project B の tag を付与する POST → reject
  (FK + service guard、全件 deny)。
- **tenant 越境 negative**: 別 tenant の tag/ticket_tags が list/read に混入しない。
- **palette 検証**: color が palette 外 → 422。5+ source enum 整合 (DB CHECK / ORM / Literal / Pydantic /
  pytest EXPECTED set)。
- **name secret 422**: tag name に secret canary / token marker → 422、永続化されない (assert_no_raw_secret)。
- **重複**: 同 project 同 name の tag 作成 → 409。同 ticket に同 tag 再付与 → idempotent (重複行を作らない)。
- **archive freeze (HIGH-2)**: archived project の tag create / soft-delete / attach / detach → **409**
  (active-project guard)。soft-deleted ticket への付与も拒否 (assert_ticket_actionable)。tag list /
  ticket tags read は archived でも 200 (履歴 read)。
- **secret scan 非 REST 経路 (HIGH-3)**: repository の tag create 関数を直接呼んで secret name →
  reject + DB に入らない (direct-call negative。REST 422 と二重)。
- **soft-delete / restore (MEDIUM + R2 HIGH)**: tag 削除は deleted_at set のみで ticket_tags は保持。
  tag list / ticket tags embed から消えるが restore (deleted_at クリア) で復元。削除前に affected ticket
  件数を preflight し `config_changed` audit に残す (raw secret なし)。**restore 競合**: soft-delete →
  restore で復活 (positive)。soft-delete → 同名 active tag 再作成 → restore は **409** (名前衝突、partial
  UNIQUE 担保)。restore も active-project guard。
- **boundary (R2 MEDIUM)**: request body に `project_id` / `tenant_id` → extra field 422。path の
  `project_id` と対象 ticket / tag の project mismatch → 404 (別 project の ticket/tag を path project
  経由で操作不可)。
- **per-ticket bulk**: ticket 一覧の tags は単一 join query (N+1 無し) を SQL introspection で確認。
  active tag のみ (deleted_at IS NULL) を embed。
