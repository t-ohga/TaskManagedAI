---
id: "ADR-00034"
title: "tickets.due_date カラム追加 (期限設定)"
status: "accepted"
date: "2026-05-28"
deciders: ["t-ohga"]
adr_gate_criteria: [2, 8]
---

# ADR-00034: tickets.due_date カラム追加 (期限設定)

## 背景

UI 改善計画 A-7 (期限設定) を実装するため、`tickets` テーブルに期限 (`due_date`) を保持する
カラムが必要。現状 `tickets` には期限フィールドがない。

ADR Gate Criteria #2 (DB schema 変更) + #8 (破壊的操作 = migration) に該当。

## 決定対象

`tickets.due_date` (nullable **date**) を追加する Alembic migration を作成する。
既存の Ticket model / TicketRead schema / 作成・更新 API / frontend 編集フォームに反映する。

## 前提 / 制約

- `due_date` は **nullable** (既存データに影響なし、backfill 不要)。
- `tenant_id` / project boundary の複合 FK には影響しない (カラム追加のみ)。
- caller-supplied 経路: `due_date` は user が UI で入力する正当なフィールド (status/priority と同じ扱い)。`server-owned-boundary` の対象外 (tenant_id / created_by_actor_id とは異なる)。
- 期限は **時刻概念のないカレンダー日付** として扱う (`date`)。HTML `<input type="date">` の `YYYY-MM-DD` と SQL `date` が 1:1 対応し、timezone 変換が一切不要。

## 選択肢

1. **nullable date カラム追加 (採用)**: 最小変更、rollback 単純、既存データ無影響。期限は暦日のみで時刻を持たないため timezone ずれが構造的に発生しない。
2. nullable timestamptz カラム追加: timezone-aware だが、UI date input (`YYYY-MM-DD`) ⟷ DB の往復で表示 (JST) と編集フォーム (`.slice(0,10)` = UTC 日付) が 1 日ずれ、無編集保存で暦日が破損する。Codex adversarial review (HIGH) で検出し却下。
3. metadata JSONB に due_date を入れる: 型安全性が落ち、index/sort 不可。却下。
4. 別テーブル (ticket_due_dates): 1:1 関係に過剰、JOIN コスト。却下。

## 採用案

```sql
ALTER TABLE tickets ADD COLUMN due_date date NULL;
```

- Alembic migration `0037_a7_ticket_due_date` (revision ID ≤ 30 chars)。
- `upgrade()`: `op.add_column("tickets", sa.Column("due_date", sa.Date(), nullable=True))`
- `downgrade()`: `op.drop_column("tickets", "due_date")`
- Ticket ORM model に `due_date: Mapped[date | None]` 追加。
- TicketRead schema / TicketCreateRequest / TicketUpdateRequest に `due_date: date | None` 追加。
- frontend 詳細表示は `YYYY-MM-DD` 文字列を直接整形 (`new Date()` / `toLocaleDateString` を使わず timezone ずれを排除)。

## 却下案

- timestamptz (選択肢 2): timezone ずれで暦日が破損する (Codex adversarial review HIGH)。
- metadata JSONB (選択肢 3): index/sort 不可、型安全性低下。
- 別テーブル (選択肢 4): 1:1 に過剰。

## リスク

- LOW-MEDIUM。
- nullable カラム追加なので既存 row への影響なし、NOT NULL 制約による table rewrite なし。
- rollback は `drop_column` で完結。data loss は due_date 値のみ (新規フィールドなので既存運用に影響なし)。
- index は P0 では不要 (期限ソートが要件化したら別 migration で partial index 追加)。

## Deferred follow-up (Codex adversarial R2/R4 指摘、A-7 scope 外)

ticket 編集フォームは title / description / status / priority / due_date を **常に full-state で
PATCH** する設計 (PR #121 以来の既存挙動)。dirty 判定や `updated_at` / If-Match 楽観ロックがないため、
stale form を開いた状態で保存すると、その間に別経路で変更されたフィールドを巻き戻す lost-update が
理論上発生しうる (due_date も同経路に乗る)。

P0 では **defer (non-blocking)** とする:

- P0 は個人専用 (single-user、Tailscale 閉域) のため並行 multi-user の lost-update は P0 シナリオ外。
- full-state PATCH は due_date 固有ではなく title / description / status / priority 共通の既存特性。
  A-7 が新規に作り込んだ欠陥ではない。
- 正しい恒久対策はフォーム全体の楽観的並行制御 (PATCH に `expected_updated_at` / If-Match を要求し
  mismatch を 409) であり、**API 契約変更 (ADR Gate #3) を伴う別 feature**。チーム運用 (P0.1+) で
  edit form 全体を対象に専用 ADR で扱う。

## rollback 手順

1. `uv run alembic downgrade -1` で `0036` に戻す (`drop_column tickets.due_date`)。
2. ORM model / schema / API / frontend の `due_date` 参照を revert。
3. data loss は due_date 列の値のみ (他テーブル・他列に影響なし)。

## 実装対象ファイル

- `migrations/versions/0037_a7_ticket_due_date.py`: add_column / drop_column
- `backend/app/db/models/ticket.py`: `due_date` Mapped column
- `backend/app/schemas/ticket.py`: TicketRead に `due_date`
- `backend/app/api/tickets.py`: TicketCreateRequest / TicketUpdateRequest に `due_date`
- frontend: 編集フォーム + 詳細表示 + チケットカードに期限表示

## テスト指針

- `alembic upgrade head` を fresh DB で成功 (migration apply)
- `alembic downgrade -1` → `upgrade head` の round-trip
- due_date=null の作成 (デフォルト)
- due_date 設定 → 更新 → 取得の整合
- `YYYY-MM-DD` 文字列 PATCH が暦日をずらさず persist する round-trip test (timezone ずれ回帰防止)
- explicit None による due_date clear の persist
- tenant 越境 negative (既存 ticket boundary test が due_date 追加で壊れないこと)
