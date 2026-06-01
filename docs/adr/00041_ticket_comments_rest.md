---
id: "ADR-00041"
title: "Ticket コメント REST エンドポイント + activity timeline 実データ化 (N-1 / N-2)"
status: "accepted"
date: "2026-06-01"
accepted_at: "2026-06-01"
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
- **共通 comment creation helper + 両経路 secret scan (Codex ADR R1-2 + R2-1、fail-closed)**:
  REST `POST` と既存 MCP `bridge_ticket_comment` の **両方が通る共通 helper**
  (`create_ticket_comment_event(session, tenant_id, project_id, ticket_id, message, actor_id)`) を設け、
  **永続化前に message (および payload 全体) を `assert_no_raw_secret` 相当に通す**。secret canary /
  provider token / private key marker hit 時は reject (REST=422、MCP=error)。REST だけに scan を置くと
  MCP 経由のコメントが secret を notification_events に残し GET で UI 再露出するため、両経路必須。
  read 側も defensive に redaction (legacy row に secret が残っていても raw 表示しない)。
- **author 保存 + legacy 互換 (Codex ADR R1-3 + R2-2)**: 新規 comment は payload `actor_id` に
  author を server-owned 保存する。**既存 (legacy) ticket_comment row は payload.actor_id を持たない**
  ため、GET の author は **`payload.actor_id ?? recipient_actor_id`** で fallback する (legacy row も
  200 で read 可能、no-migration と後方互換を両立)。
- **notification 全 read surface で非汚染 (Codex ADR R1-3 + R2-3)**: comment が投稿者の通知に混入しない
  よう、`notification_events` の **全 inbox / triage read query** に `event_type != 'ticket_comment'` を
  追加する: `list_unread` / `list_for_recipient` / `count_unread` / **`list_triage`** (`/api/v1/notifications/triage`)。
  既存 bridge_ticket_comment 由来の汚染も同時解消。
- **direct notification-id endpoint も非対象 (Codex ADR R3-1、迂回封鎖)**: ticket_comment は
  notification_events 行として残るため、list 除外だけでは
  `POST /api/v1/notifications/{notification_id}/mark_read` 等の **direct-id endpoint** が `_to_item` で
  payload を raw 返却し迂回経路になる。ticket_comment event を direct notification endpoint から
  **404 で拒否** (comment は notification ではない) し、加えて `_to_item` 変換は ticket_comment payload を
  **keys-only / redacted** にする (legacy secret comment の id を mark_read しても raw message を返さない)。
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
- `actor_id` = `payload.actor_id ?? recipient_actor_id` (legacy row fallback、R2-2)。
- read は message を defensive redaction (legacy secret 残留を raw 表示しない、R2-1)。

### N-1 write: `POST .../comments`

```
Request: { "message": "<1-4000 chars>" }
Response: TicketComment (作成された 1 件)
```

- `assert_ticket_actionable` guard 後、**共通 helper** `create_ticket_comment_event(...)` を呼ぶ。
  helper は message/payload を `assert_no_raw_secret` に通し (hit→reject、R2-1)、
  `append(event_type='ticket_comment', payload={project_id, ticket_id, message, actor_id},
  recipient_actor_id=actor_id)` + commit。REST=secret hit で 422。
- `bridge_ticket_comment` (MCP) も同じ helper を呼び、両経路で secret scan + actor_id 保存を共有
  (重複ロジック回避、MCP 経路の secret bypass を塞ぐ、R2-1)。

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
- backend 共通 helper (`services/ticket/comment.py` 等): `create_ticket_comment_event(...)` —
  secret scan + actor_id payload 保存 + append。REST `create_ticket_comment` と
  `bridge_ticket_comment` の両方が呼ぶ (R2-1)。
- `backend/app/repositories/notification_event.py`: ticket コメント list query (tenant + event_type +
  payload ticket_id filter、author fallback) + **inbox/triage query 4 種に `event_type != 'ticket_comment'`
  追加** (`list_unread` / `list_for_recipient` / `count_unread` / `list_triage`、R1-3 + R2-3)。
- `backend/app/repositories/audit_event.py`: ticket activity (ticket_status_changed / ticket_updated) の
  payload.ticket_id filter list query (R1-4)。
- `backend/app/mcp/api_bridge.py`: `bridge_ticket_comment` を共通 helper 呼び出しに変更 (R2-1)。
- `backend/app/api/notifications.py`: `mark_read` 等 direct-id endpoint で ticket_comment を 404 拒否 +
  `_to_item` が ticket_comment payload を keys-only/redacted 化 (R3-1、迂回封鎖)。
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
- **inbox / triage 非汚染 (R1-3 + R2-3)**: ticket_comment event 作成後、投稿者の `list_unread` /
  `count_unread` / `list_for_recipient` / **`list_triage` (`/api/v1/notifications/triage`)** に当該
  comment が **出ない**こと (全 notification read surface)。
- **MCP bridge secret reject (R2-1)**: `bridge_ticket_comment` も message に secret/canary を含むと
  reject し、notification_events に永続化されないこと (REST と同じ共通 helper)。
- **legacy payload 読取 (R2-2)**: payload.actor_id が無い旧 ticket_comment row も GET comments /
  activity で **200**、author は recipient_actor_id fallback で返ること。
- **direct-id 迂回封鎖 (R3-1)**: legacy secret 入り ticket_comment の notification id を
  `POST /api/v1/notifications/{id}/mark_read` に渡しても **404** (or redacted) で、payload.message の
  raw が返らないこと。`_to_item` が ticket_comment payload を keys-only/redacted にする regression。
- **timeline に status event (R1-4)**: ticket status を変更すると activity に `ticket_status_changed`
  (previous/new status) が出ること。comment + status + created が created_at 昇順でマージされること。
- SQL introspection (no-DB): comment list / activity query の compile SQL に tenant 境界 / `event_type` /
  payload ticket_id filter が含まれること。
- frontend: comment-form の write (orphan 解消) + activity-timeline の実 comment / status 表示 +
  取得失敗 degraded。
