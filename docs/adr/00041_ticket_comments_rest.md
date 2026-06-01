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
  は path param、author は `get_current_actor_id` で server resolve (caller payload で上書き不可)。
- **read / write の guard を分離 (Codex ADR R1-1)**: ADR-00037 は archived project を
  **child-write 凍結 = read-only** と定義し、GET ticket は archived を拒否しない。よって:
  - **GET comments**: tenant / project / ticket 境界 + `Ticket.deleted_at IS NULL` のみ確認し、
    **archived project は許可** (archive 後もチケット本文同様にコメント履歴を read 可能)。
  - **POST comment**: `TicketRepository.assert_ticket_actionable(tenant_id, project_id, ticket_id)` で
    soft-deleted / archived ticket への write を拒否 (bridge_ticket_comment と統一)。
- **message の raw secret / canary 拒否 (Codex ADR R1-2、fail-closed)**: `CreateTicketCommentRequest.message`
  は永続化前に既存 `assert_no_raw_secret` 相当 (secret canary / provider token / private key marker pattern)
  に通し、hit 時は **422 で reject** (DB / UI へ raw secret を流さない、AC-HARD-02 系)。
- **notification inbox 非汚染 (Codex ADR R1-3)**: comment event の author を payload (`actor_id`) に
  server-owned で保存する。`notification_events` の inbox query (`list_unread` / `list_for_recipient` /
  `count_unread`) に **`event_type != 'ticket_comment'`** を追加し、comment が投稿者の未読通知 / badge /
  triage に混入しないようにする (既存 bridge_ticket_comment 由来の汚染も同時に解消)。
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
  `payload['ticket_id'].astext == ticket_id` で select、`created_at` 昇順。GET は `deleted_at IS NULL`
  のみ確認 (archived 許可、R1-1)。
- `actor_id` = payload の author (server-owned、R1-3)。

### N-1 write: `POST .../comments`

```
Request: { "message": "<1-4000 chars>" }
Response: TicketComment (作成された 1 件)
```

- message を `assert_no_raw_secret` 相当に通し、secret canary / token hit 時は **422 reject** (R1-2)。
- `assert_ticket_actionable` guard 後、`NotificationEventRepository.append(event_type='ticket_comment',
  payload={project_id, ticket_id, message, actor_id}, recipient_actor_id=actor_id)` + commit。
- `bridge_ticket_comment` と同一の保存形式 (MCP / REST どちらからでも同じ event 形)。bridge 側も
  payload に actor_id を持たせ inbox 除外を共有 (重複ロジック回避のため共通 helper に寄せる)。

### N-2 timeline (Codex ADR R1-4 修正)

- **既存 audit event を含める**: `update_ticket_endpoint` は status 差分時に `ticket_status_changed`
  (それ以外は `ticket_updated`) **audit_events** を payload `{ticket_id, previous_status, new_status,
  updated_fields, ...}` で append 済。「未記録」は誤りだったため修正し、これらを timeline に含める。
- `GET /api/v1/projects/{project_id}/tickets/{ticket_id}/activity` で **merged timeline** を返す:
  - comment (notification_events `ticket_comment`)
  - status 変更 / 更新 (audit_events `ticket_status_changed` / `ticket_updated`、payload.ticket_id filter)
  - ticket 作成 (`created_at`)
  を `created_at` 昇順にマージし、frontend `activity-timeline` がそのまま描画する。
- audit_events read も tenant + payload.ticket_id で絞り、`deleted_at IS NULL` の ticket に対してのみ
  (archived 許可)。raw secret 非混入。

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
  `list_ticket_activity` (GET、merged timeline) + 各 schema。read は deleted_at のみ guard、POST は
  assert_ticket_actionable + message secret scan。
- `backend/app/repositories/notification_event.py`: ticket コメント list query (tenant + event_type +
  payload ticket_id filter) + **inbox query 3 種に `event_type != 'ticket_comment'` 追加** (R1-3)。
- `backend/app/repositories/audit_event.py`: ticket activity (ticket_status_changed / ticket_updated) の
  payload.ticket_id filter list query (R1-4)。
- `backend/app/mcp/api_bridge.py`: `bridge_ticket_comment` の payload に actor_id 追加 (共通 helper 化)。
- `tests/api/test_ticket_comments.py`: route 登録 + schema no-secret + SQL introspection
  (tenant / event_type / payload ticket_id filter) + message 長さ validation。
- `frontend/lib/api/tickets.ts` (or comments.ts): `fetchTicketComments` + `createTicketComment`。
- `frontend/components/comment-form.tsx`: write endpoint に配線 (orphan 解消)。
- `frontend/app/(admin)/tickets/[id]/page.tsx`: comment 一覧 + comment-form + activity-timeline を
  実 comment に配線。mutation 後 revalidate。

## テスト指針

- read: tenant 越境 negative (別 tenant のコメントが混入しない) + ticket_id filter (別 ticket の
  コメントが出ない) + 空配列。
- **archived 許可 / write 拒否 (R1-1)**: archived project の GET comments / GET activity は **200**
  (履歴 read 可)、POST comment は **拒否** (assert_ticket_actionable)。soft-deleted ticket は read/write とも拒否。
- **message raw secret 422 (R1-2)**: message に secret canary / provider token / private key marker を
  含む POST は 422 で reject し、notification_events に永続化されないこと (assert_no_raw_secret negative)。
- write: message 長さ validation (空 / 超過は 422) + author server-resolve (caller payload で上書き不可) +
  作成後に read で取得できる。
- **inbox 非汚染 (R1-3)**: ticket_comment event 作成後、投稿者の `list_unread` / `count_unread` /
  `list_for_recipient` に当該 comment が **出ない**こと。
- **timeline に status event (R1-4)**: ticket status を変更すると activity に `ticket_status_changed`
  (previous/new status) が出ること。comment + status + created が created_at 昇順でマージされること。
- SQL introspection (no-DB): comment list / activity query の compile SQL に tenant 境界 / `event_type` /
  payload ticket_id filter が含まれること。
- frontend: comment-form の write (orphan 解消) + activity-timeline の実 comment / status 表示 +
  取得失敗 degraded。
