---
id: "ADR-00041"
title: "Ticket コメント REST エンドポイント + activity timeline 実データ化 (N-1 / N-2)"
status: "proposed"
date: "2026-06-01"
deciders: ["t-ohga"]
adr_gate_criteria: [3]
related_adr:
  - "ADR-00037 (Q-3 soft-delete / assert_ticket_actionable)"
related_dd:
  - "DD-02 (データモデル / tenant 境界)"
related_sprints: []
supersedes: null
superseded_by: null
---

# ADR-00041: Ticket コメント REST エンドポイント + activity timeline 実データ化 (N-1 / N-2)

最終更新: 2026-06-01

## 背景

UI 改善監査の **N-1 (コメント、orphan + no backend)** と **N-2 (activity timeline、synthetic)** を実装する。

- `frontend/components/comment-form.tsx` は orphan (どこにも配線されていない)。
- `frontend/components/activity-timeline.tsx` は ticket の `created_at` / `updated_at` だけの合成
  データを表示しており、実際のコメントや活動が出ない。
- backend には MCP 経由の `bridge_ticket_comment` が既存で、コメントを **`notification_events`**
  (`event_type="ticket_comment"`、payload `{project_id, ticket_id, message}`、`recipient_actor_id`) に
  append している (`assert_ticket_actionable` で削除/凍結 ticket を guard)。専用 comment table はなく、
  **migration は不要**。ただし human が UI からコメントを読む / 書く REST 経路が無い。

## 決定対象

ticket コメントの read / write REST エンドポイントを追加し、frontend comment-form と
activity-timeline を実データに配線する。ADR Gate Criteria #3 (API 契約) に該当。

1. `GET /api/v1/projects/{project_id}/tickets/{ticket_id}/comments` — コメント一覧 (read-only)
2. `POST /api/v1/projects/{project_id}/tickets/{ticket_id}/comments` — コメント作成 (human actor の mutation)

## 前提 / 制約

- comment は `notification_events` の `event_type="ticket_comment"` event として保存 (既存機構、migration なし)。
- tenant 境界を強制 (`tenant_id` を session から resolve、caller-supplied 禁止)。`project_id` / `ticket_id`
  は path param、actor_id は `get_current_actor_id` で server resolve (caller payload で上書き不可)。
- **active-scope**: read / write とも `TicketRepository.assert_ticket_actionable(tenant_id, project_id,
  ticket_id)` を通す (soft-deleted ticket / archived project へのコメント read / write を拒否、bridge と統一)。
- write は **human actor の task-write 相当**で、AI 出力ではないため approval pipeline は不要
  (既存 ticket create / update と同じ直接 human mutation)。`message` は長さ上限を持つ。
- read は tenant + `event_type="ticket_comment"` + `payload->>'ticket_id' = ticket_id` で絞り、
  `created_at` 昇順。raw secret は含まない (message / actor_id / created_at のみ)。

## 採用案

### N-1 read: `GET .../comments`

```
Response (TicketCommentListResponse):
{
  "comments": [
    { "id": "<uuid>", "message": "...", "actor_id": "<uuid>", "created_at": "...Z" }
  ]
}
```

- `notification_events` を `tenant_id` + `event_type='ticket_comment'` +
  `payload['ticket_id'].astext == ticket_id` で select、`created_at` 昇順。
- `actor_id` = `recipient_actor_id` (コメント作成者)。

### N-1 write: `POST .../comments`

```
Request: { "message": "<1-4000 chars>" }
Response: TicketComment (作成された 1 件)
```

- `assert_ticket_actionable` guard 後、`NotificationEventRepository.append(event_type='ticket_comment',
  payload={project_id, ticket_id, message}, recipient_actor_id=actor_id)` + commit。
- `bridge_ticket_comment` と同一の保存形式 (MCP / REST どちらからでも同じ event 形)。

### N-2 timeline

- `activity-timeline` を実データに配線: コメント (read endpoint) + ticket `created_at` / `updated_at` を
  時系列マージして表示する。status 変更 event は現状未記録のため本 ADR では対象外
  (ticket PATCH 経路に status_changed event を足すのは別 ADR / mutation 経路変更のため defer)。

## 却下案

- 専用 `ticket_comments` table を新設: comment は既に notification_events event として保存されており、
  二重管理 + migration コストが見合わない。却下 (将来 comment が独立ライフサイクルを持つなら別 ADR)。
- frontend が MCP を直接呼ぶ: UI は REST 経由のみ。MCP は AI / agent 経路。却下。
- write を approval pipeline に乗せる: human の task-write 相当でありコメントは AI 出力ではない。
  既存 ticket create / update と同じ直接 mutation。却下。

## リスク

- LOW-MEDIUM。write は mutation だが human task-write 相当 + assert_ticket_actionable guard + actor
  server-resolve で既存 ticket mutation と同水準。migration なし。
- read の `payload->>'ticket_id'` JSONB filter は index 無し (tenant + event_type で絞った後の scan)。
  P0 規模では軽量。将来必要なら `(tenant_id, event_type)` 複合 index or payload GIN index を検討。
- rollback は endpoint + schema 削除 + frontend 配線 revert で完結 (DB 変更なし)。

## rollback 手順

- ルート定義 (`tickets.py`) と schema の削除、frontend comment-form / activity-timeline 配線の revert。
- 既存コメント event (notification_events) は残るが read 経路が消えるだけ (data loss なし)。

## 実装対象ファイル

- `backend/app/api/tickets.py`: `list_ticket_comments` (GET) + `create_ticket_comment` (POST) +
  `TicketComment` / `TicketCommentListResponse` / `CreateTicketCommentRequest` schema。
  既存 `bridge_ticket_comment` の保存ロジックを共有 (重複回避)。
- `backend/app/repositories/notification_event.py`: ticket コメント list query method (tenant +
  event_type + payload ticket_id filter)。
- `tests/api/test_ticket_comments.py`: route 登録 + schema no-secret + SQL introspection
  (tenant / event_type / payload ticket_id filter) + message 長さ validation。
- `frontend/lib/api/tickets.ts` (or comments.ts): `fetchTicketComments` + `createTicketComment`。
- `frontend/components/comment-form.tsx`: write endpoint に配線 (orphan 解消)。
- `frontend/app/(admin)/tickets/[id]/page.tsx`: comment 一覧 + comment-form + activity-timeline を
  実 comment に配線。mutation 後 revalidate。

## テスト指針

- read: tenant 越境 negative (別 tenant のコメントが混入しない) + ticket_id filter (別 ticket の
  コメントが出ない) + 空配列。
- write: message 長さ validation (空 / 超過は 422) + assert_ticket_actionable (soft-deleted /
  archived ticket への comment は拒否) + actor_id server-resolve (caller payload で上書き不可) +
  作成後に read で取得できる。
- SQL introspection (no-DB): list query の compile SQL に tenant 境界 / `event_type` /
  payload ticket_id filter が含まれること。
- raw secret 非混入 (`assert_no_raw_secret` 相当、message に secret canary が無いことは別途 redaction)。
- frontend: comment-form の write + activity-timeline の実 comment 表示 + 取得失敗 degraded。
