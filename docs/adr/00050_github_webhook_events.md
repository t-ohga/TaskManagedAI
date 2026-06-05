---
id: "ADR-00050"
title: "GitHub webhook event processing + UX (SP-028: payload parse + persist + read API + activity view)"
status: "proposed"
date: "2026-06-05"
accepted_at: null
deciders: ["t-ohga"]
adr_gate_criteria: [2, 3]
related_adr:
  - "ADR-00026 (MCP Server Gateway / repository chokepoint 先例)"
  - "ADR-00041 (read-only enrichment endpoint + capability gate の先例)"
related_dd:
  - "DD-02 (データモデル / tenant・project 境界、複合 FK)"
  - "DD-04 (セキュリティ / webhook ingress、HMAC verify、audit、redaction)"
related_sprints:
  - "SP-028_webhook_ux (partial_skeleton。本 ADR で webhook event 処理 + 表示の未実装部分を実装)"
supersedes: null
superseded_by: null
---

# ADR-00050: GitHub webhook event processing + UX (SP-028)

最終更新: 2026-06-05

## 背景

2026-06-04 台帳監査 (PR #321) で **SP-028 webhook UX が partial_skeleton** と確定。現状の GitHub
webhook 実装 (`backend/app/services/repoproxy/webhook_service.py` + `backend/app/api/github_webhooks.py`)
は **ingress security 層のみ**:

- HMAC 署名検証 (`GitHubWebhookVerifier.verify`)
- replay 防止 (`WebhookReplayStore.claim_once`、Redis)
- 検証結果の audit (`audit_event_type` = `hmac_verified` 等の **verification reason code**)

つまり **webhook payload (pull_request / check_run / check_suite / status / push) を一切 parse せず**、
SP-028 の目的「PR/CI イベントの toast 通知 + CI status live update + PR timeline 統合」(SP-028 Pack 行 14)
の payload 処理 + 保存 + repo 紐付け + frontend 表示が**まるごと未実装**。

## 決定対象

verification 済 webhook payload を **parse + persist + repository 紐付け** し、read endpoint + frontend で
PR/CI イベントを surface する。real-time push (SSE) / toast は本 ADR scope 外 (read view + polling refresh)。

## 前提 / 制約

- **DB migration を伴う (ADR Gate #2)**: 新 `github_webhook_events` table。additive、downgrade lossless。
- **read-only API (ADR Gate #3)**: webhook event 一覧 endpoint。mutation は無し (受信は既存 ingress)。
- tenant / project 境界を維持 (複合 FK)。repository は `(tenant_id, id)` で紐付け。
- **raw secret / token を保存・表示しない**: payload から **allowlist した非機密 field のみ**抽出
  (action / number / state / sha / title / sender.login)。raw payload は保存しない (redaction)。
- 既存 ingress security (HMAC verify / replay) を変えない。**verification accepted のときのみ** parse + persist。
- live update (real-time) は SSE 結合せず frontend polling refresh (L-3 SSE は AgentRun 専用、別 concern)。

## 選択肢

1. **raw payload を JSONB で丸ごと保存** — ❌ 却下。GitHub payload に token/secret が混入する経路を残す
   (redaction 困難)、肥大化。allowlist 抽出が安全。
2. **既存 audit_events に webhook content を載せる** — ❌ 却下。audit_events は verification ingress
   audit 専用。content (PR/CI state) を載せると責務混在 + query しづらい。専用 table が clean。
3. **専用 `github_webhook_events` table に allowlist 抽出した非機密 field を保存** — ✅ 採用。repository
   紐付け + read endpoint + frontend で surface。

## 採用案 (詳細)

### `github_webhook_events` table

| column | 内容 |
|---|---|
| `id` | UUID PK |
| `tenant_id` | bigint NOT NULL |
| `repository_id` | UUID **NULLABLE** (payload の repository.id を repositories.external_id で解決、未登録 repo は NULL) |
| `delivery_id` | text NOT NULL (GitHub X-GitHub-Delivery、dedup 用) |
| `event_kind` | text NOT NULL (`pull_request` / `check_run` / `check_suite` / `status` / `push`) |
| `action` | text NULLABLE (opened / closed / completed / synchronize 等) |
| `external_ref` | text NULLABLE (PR number / check id / commit sha) |
| `state` | text NULLABLE (open / closed / merged / success / failure / pending / neutral 等) |
| `title` | text NULLABLE (PR title 等、redacted、最大長 bound) |
| `sender_login` | text NULLABLE (GitHub actor login、非機密) |
| `received_at` | timestamptz NOT NULL |
| `created_at` | timestamptz NOT NULL |

- **unique** `(tenant_id, delivery_id)` で **再配信 dedup** (GitHub は webhook を redeliver する)。
- **複合 FK** `(tenant_id, repository_id) → (repositories.tenant_id, repositories.id)` ondelete SET NULL
  (repo 削除で event は残すが紐付け解除)。repository_id NULL 許容 (未登録 repo の event も記録)。
- `event_kind` は固定 enum (5+ source 整合)。

### payload 処理 (verification accepted のときのみ)

- endpoint で `X-GitHub-Event` header から `event_kind` を取得。
- verification accepted 後、payload JSON を parse し **allowlist field のみ抽出** (event_kind 別):
  - `pull_request`: action, number, state, merged→state='merged', title, sender.login, repository.id
  - `check_run` / `check_suite`: action, id, status/conclusion→state, head_sha→external_ref, repository.id
  - `status`: state, sha→external_ref, repository.id, sender.login
  - `push`: ref→external_ref, after→sha, repository.id, sender.login
- repository.id を `repositories.external_id` (provider='github', tenant) で解決 → repository_id。未解決は NULL。
- `(tenant_id, delivery_id)` で INSERT ON CONFLICT DO NOTHING (再配信 dedup)。
- parse / persist 失敗は ingress を壊さない (best-effort、verification 自体は成功扱い)。失敗は audit log。

### read endpoint

`GET /api/v1/me/webhook_events?repository_id=<uuid>&limit=<n>`

- `actor_id = Depends(get_current_actor_id)` (authenticated session)。
- tenant scope + 任意 repository_id filter。`limit` clamp (≤ 100)。
- response: 非機密 field のみ (event_kind / action / external_ref / state / title / sender_login /
  received_at / repository_id)。raw secret なし。

### frontend

- webhook activity / CI status view (`lib/api/webhook-events.ts` server fetch + `lib/domain/webhook-event.ts`
  client-safe pure。A-6 / M-2 の RSC server/client 分離規約に従う)。
- CI status は state badge (success/failure/pending)、PR は number + title + state、push は ref + sha。
- live update は client polling (refresh interval、SSE 非結合)。toast は本 scope 外 (follow-up)。

## 却下案

- raw payload 保存 (選択肢 1): secret 混入経路。
- audit_events 流用 (選択肢 2): 責務混在。
- SSE real-time (live update): L-3 SSE は AgentRun 専用、webhook real-time は別 ADR / polling で代替。
- mutation endpoint: 受信は既存 ingress、read-only に限定。

## リスク

- **payload secret 混入**: allowlist 抽出 + raw payload 非保存 + title 長さ bound + redaction で防ぐ。
  `provider_request_preflight` 相当の canary check は webhook には不要 (GitHub payload は外部由来 untrusted、
  保存 field を allowlist で固定するのが核)。
- **repo 未解決**: repository_id NULL で記録 (event は失わない、後で repo 登録時に手動再解決は scope 外)。
- **再配信重複**: `(tenant_id, delivery_id)` unique + ON CONFLICT DO NOTHING。
- **parse 失敗で ingress 破壊**: best-effort、verification 成功は維持、parse 失敗は audit。

## rollback 手順

1. additive (新 table + read endpoint + payload parse hook + frontend)。
2. rollback: revert PR + migration downgrade (table drop、lossless)。
3. parse hook は verification accepted 後の best-effort なので、revert で ingress security は不変。

## 実装対象ファイル

- `migrations/versions/00NN_sp028_github_webhook_events.py`
- `backend/app/db/models/github_webhook_event.py`
- `backend/app/services/repoproxy/webhook_event_parser.py` (allowlist 抽出 + repo 解決 + persist)
- `backend/app/api/github_webhooks.py` (verification accepted 後に parse hook)
- `backend/app/api/me.py` or 新 `backend/app/api/webhook_events.py` (read endpoint)
- `frontend/lib/domain/webhook-event.ts` (client-safe pure) + `frontend/lib/api/webhook-events.ts` (server fetch)
- `frontend/app/(admin)/...` webhook activity view + nav
- tests: parser (no-DB unit、allowlist/redaction/repo 解決) + DB-gated (persist/dedup/read) + frontend vitest

## テスト指針 (must-ship)

- **parse allowlist**: 各 event_kind で allowlist field のみ抽出、raw payload / secret-shaped 値が
  保存 field に出ない (`assert_no_raw_secret` 相当)。
- **repo 解決**: repository.id → repositories.external_id 解決、未登録は repository_id NULL。
- **再配信 dedup**: 同一 delivery_id 2 回 → 1 row。
- **tenant 境界**: 別 tenant の event / repo を混ぜない。read endpoint の tenant scope。
- **ingress 不破壊**: parse 失敗でも verification accepted は維持。
- **read endpoint**: authenticated 必須、limit clamp、非機密 field のみ、repository_id filter。
- **frontend**: state badge / PR / push の表示、RSC server/client 境界 (next build OK)。

## Hard Gates / KPI への trace

- 既存 Hard Gate / KPI に regression なし (additive read + ingress 不変)。
- DD-04 webhook ingress security 不変 + redaction invariant に整合。
