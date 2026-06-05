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

最終更新: 2026-06-05 (Codex plan-review R1: 15 findings 全 adopt、CRITICAL=0)

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
| `repository_id` | UUID **NULLABLE** (verified installation 経由で解決、未登録/mismatch は NULL、F-009) |
| `delivery_id` | text NOT NULL、**DB CHECK length ≤ 100** (GitHub X-GitHub-Delivery、redelivery dedup 用) |
| `payload_hash` | text NOT NULL (signed body の SHA-256 hex、dedup conflict 時の同一性検証 + replay 検知、F-005) |
| `event_kind` | text NOT NULL、**DB CHECK enum** (`pull_request` / `check_run` / `check_suite` / `status` / `push`、F-010) |
| `status` | text NOT NULL、**DB CHECK enum** (`accepted` / `quarantined`、F-004)。`accepted` のみ通常 feed |
| `quarantine_reason` | text NULLABLE、**DB CHECK enum** (`unregistered_repo` / `cross_tenant_mismatch` / `repo_lookup_ambiguous`、status='quarantined' 時のみ NOT NULL、F-004/F-015) |
| `action` | text NULLABLE、**DB CHECK length ≤ 64** (opened / closed / completed / synchronize 等) |
| `external_ref` | text NULLABLE、**DB CHECK length ≤ 255** (PR number / check id / commit sha) |
| `state` | text NULLABLE、**DB CHECK length ≤ 32** (open / closed / merged / success / failure / pending / neutral 等) |
| `title` | text NULLABLE、**DB CHECK length ≤ 512** (PR title 等、redacted、最大長 bound) |
| `sender_login` | text NULLABLE、**DB CHECK length ≤ 64** (GitHub actor login、非機密) |
| `received_at` | timestamptz NOT NULL、**server clock で採番** (payload/header timestamp は使わない、ordering 改竄防止、F-013) |
| `created_at` | timestamptz NOT NULL |

- **unique** `(tenant_id, delivery_id)` で **再配信 dedup** (GitHub は webhook を redeliver する)。conflict 時は
  `payload_hash` 比較: 一致 → idempotent accepted、不一致 → security signal (audit alert + quarantine、F-005)。
- **複合 FK** `(tenant_id, repository_id) → (repositories.tenant_id, repositories.id)` を **`ON DELETE SET NULL
  (repository_id)`** (PostgreSQL 16 の column-list SET NULL、tenant_id は NULL 化しない、F-003)。repo 削除で
  event は残すが紐付け解除、repository_id NULL 許容。**repository は `(tenant_id, provider='github', external_id)`
  の既存 unique で一意解決**、installation_ref 一致を要求 (F-009)。
- DB-level CHECK / length は parser の bound と同一定数で揃え、parser bypass / 将来の bulk import に対する
  最後の防衛線にする (5+ source 整合、F-010)。`event_kind` / `status` / `quarantine_reason` は固定 enum。
- **read index**: `(tenant_id, status, repository_id, received_at DESC, id DESC)` で通常 feed query + cursor
  pagination を支える (F-012)。

### payload 処理 (verification accepted のときのみ、R1 findings 反映)

#### (a) tenant は verified installation から fail-closed 導出 (R1 F-Q1 + Codex F-001/F-009)

- webhook は unauthenticated。tenant を request.state / default / payload 申告値に依存させない。
- **verifier contract (F-001、ADR 明文化)**: HMAC は **署名前 body と候補 webhook secret 群で検証**し、
  **検証成功した `secret_ref` が属する tenant のみ**を `tenant_id` の source of truth にする。payload 内の
  `installation_id` は **HMAC 検証成功後の signed body field としてのみ** mapping に使う (検証前の未信頼値を
  tenant lookup の前提にしない)。`installation_id` 欠落 / 複数 tenant secret match / mapping 不存在は
  **fail-closed reject (event を保存しない)**。
- **repository lookup contract (F-009、concrete)**: payload の `repository.id` (= external_id) を
  **`(tenant_id, provider='github', external_id)` の既存 unique で解決** (`repositories_uq_tenant_provider_external`、
  0 or 1 row)。解決 row の `installation_ref` が **verified installation と一致**することを要求する。
  - 一致 → `status='accepted'`、`repository_id` set。
  - 0 件 (未登録 repo) → `status='quarantined'`, `quarantine_reason='unregistered_repo'`, `repository_id=NULL`
    (verified tenant 下に記録、通常 feed 非表示)。
  - 複数件 / installation 不一致 → `status='quarantined'`, `quarantine_reason='repo_lookup_ambiguous'`。
  - payload repo が **別 tenant** を指す解決になった場合 → verified installation tenant に
    `status='quarantined'`, `quarantine_reason='cross_tenant_mismatch'`, `repository_id=NULL` で記録
    (cross-tenant/project leak 防止、verified tenant 外には一切書かない)。
- quarantine の実体は §(e) 参照。`status='quarantined'` event は通常 read feed に出さない。

#### (b) header validation + dedup payload_hash 比較 + replay guard (R1 F-Q2 + Codex F-005)

- `X-GitHub-Delivery` (delivery_id) は **length/形式 validation**、`X-GitHub-Event` (event_kind) は **enum validation**。
- **payload shape validation**: header の event_kind と payload body の実体 (PR なら pull_request key 存在等)
  が一致しない場合は **保存拒否 / quarantine** (header poisoning 防止)。
- **dedup conflict 時の hash 比較 (F-005)**: `(tenant_id, delivery_id)` unique conflict 時、保存済 row の
  `payload_hash` と新 signed body の hash を比較する:
  - **一致** → 真の GitHub redelivery、idempotent accepted (新規 row 作らない)。
  - **不一致** → 同一 delivery_id で別 body = security signal。**audit alert + quarantine** に倒す
    (`ON CONFLICT DO NOTHING` で握り潰さず、conflict を hash 比較経路に通す)。
- **security replay guard**: delivery_id を差し替えて同一 signed body を再注入する経路は、既存
  `WebhookReplayStore` (Redis、HMAC verify 層) の replay claim が **signed body 単位**で塞ぐ。本 event
  table 側の `payload_hash` は dedup 同一性検証 + 異常検知 (audit) 用途で重複保持する。

#### (c) allowlist field を抽出 (event_kind 別) + 値レベル redaction (R1 F-Q3)

- allowlist 抽出 (event_kind 別):
  - `pull_request`: action, number, state, merged→state='merged', title, sender.login, repository.id
  - `check_run` / `check_suite`: action, id, status/conclusion→state, head_sha→external_ref, repository.id
  - `status`: state, sha→external_ref, repository.id, sender.login
  - `push`: ref→external_ref, after→sha, repository.id, sender.login
- **field 名 allowlist だけでは不十分**。抽出 DTO の **全 string field に既存 raw-secret/canary scanner
  相当を必須適用** (secret-shaped token / GitHub token / age key 等 hit 時は **当該 field を redact**)。
- **全 string field に max length bound + UTF-8 NFC normalize + control-character 除去** (bidi / 制御文字
  injection 防止)。bound 値は DB CHECK length と同一定数。
- **error/audit/log path の redaction invariant (F-007)**: parse failure / quarantine reason / audit detail /
  exception log は **raw payload や抽出前の raw field value を含めない**。audit / log に出してよいのは
  `delivery_id`、`event_kind`、`tenant_id`、`installation_id`、`payload_hash` prefix、`reason_code` のみ
  (allowlist 抽出後の redacted 値以外は出さない)。test で secret-shaped 値が audit/log/exception に出ない
  ことを確認する。
- **frontend は text-only rendering** (`dangerouslySetInnerHTML` / Markdown rendering 禁止、title 等を
  そのまま text node で表示)。

#### (d) 失敗時シーケンスを単一 path に固定し event loss を防ぐ (R1 F-Q4 + Codex F-006)

実装者が選択に迷わないよう、**失敗時の順序と補償を 1 本の path に固定** (F-006、選択式を排除):

```
1. HMAC verify + replay claim (既存 ingress、変更なし)
2. verification audit を commit (この時点で security ingress は成功確定)
3. parse + persist を 1 transaction で実行:
   - parse validation failure (shape 不正 / header mismatch / lookup ambiguous):
       status='quarantined' で row を insert + audit → commit → 202 accepted
       (event は失わず quarantine、verification は維持)
   - persist transient failure (DB timeout / session failure / IntegrityError 以外の一時障害):
       transaction rollback + replay claim を再試行可能状態に戻す + **5xx を返す**
       (GitHub の自動 redelivery を誘発、silent event loss を防ぐ。202 は返さない)
   - dedup conflict ((tenant_id, delivery_id) 既存): §(b) の payload_hash 比較経路 → 202 accepted
   - success: status='accepted' で commit → 202 accepted
```

- **202 accepted は dedup / validation quarantine / 正常 persist のみ**。transient persist failure に 202 を
  返さない (これが silent loss の原因)。
- replay claim を戻せない実装制約がある場合は、replay TTL を短く保ち **manual redelivery 手順** を運用に残す。
- **transaction 境界明示**: step 2 の verification audit は step 3 と別 transaction。step 3 の rollback でも
  verification audit は残り、再処理 (redelivery) 可能。

#### (e) quarantine の実体 (Codex F-004 + F-015)

- quarantine は **別 table ではなく同 `github_webhook_events` table の `status='quarantined'` row** で表現
  (verified tenant 下に記録、§(a) の 3 reason)。`quarantine_reason` enum で原因を保持。
- **owner の定義 (F-015)**: 「owner-only」は GitHub repository owner login ではなく、**TaskManagedAI の
  tenant 内 admin capability を持つ actor** を指す。P0 は単一 user (= tenant admin) なので owner = その user。
  quarantine view は通常 read capability と分離し、admin capability を要求する。
- quarantine view は **非機密 field のみ** (raw payload / 抽出前値は返さない、通常 event と同じ redaction)。

### read endpoint

`GET /api/v1/me/webhook_events?repository_id=<uuid>&cursor=<opaque>&limit=<n>`

- `actor_id = Depends(get_current_actor_id)` (authenticated session)。
- **scope 条件 (F-002、ADR-00041 capability gate 先例)**: tenant scope に加え **actor が閲覧可能な
  project / repository に限定**する。`repository_id` 指定時は `(tenant_id, repository_id)` 解決後に
  **project membership / read capability を検証** (未所属 repo の event を返さない)。未指定時も actor が
  アクセスできる project 配下の repository event のみに絞る (同一 tenant 内 cross-project leak 防止)。
- **通常 feed フィルタ**: `status='accepted' AND repository_id IS NOT NULL`。`status='quarantined'` event は
  通常 feed に出さず、admin 専用 quarantine view (別 capability) でのみ非機密 summary を返す (§(e))。
- **ordering + pagination (F-012)**: `ORDER BY received_at DESC, id DESC` + opaque cursor pagination
  (received_at 同値の順序安定化)。`limit` clamp (≤ 100)。read index は table §参照。
- response: 非機密 field のみ (event_kind / action / external_ref / state / title / sender_login /
  received_at / repository_id)。raw secret なし。

### frontend

- webhook activity view (`lib/api/webhook-events.ts` server fetch + `lib/domain/webhook-event.ts`
  client-safe pure。A-6 / M-2 の RSC server/client 分離規約に従う)。
- **cache 境界 (F-008)**: tenant/user 固有データを扱うため server fetch は **`cache: 'no-store'` +
  session-bound (cookie 転送)**。RSC static cache に乗せず、別ユーザーへの activity leak を防ぐ。
- 表示: CI status は state badge (success/failure/pending)、PR は number + title + state、push は ref + sha。
  全て text-only rendering (§(c))。
- **CI status の集約 scope (F-014)**: 本 ADR は **activity log (event 時系列) を core scope** とする。
  badge は「その event 行の state」を表示するのみ。`event_kind + external_ref` 単位の「最新 CI status」を
  集約する normalized status projection は **follow-up ADR に defer** (read model key 設計が別 concern)。
- live update は client polling (refresh interval、SSE 非結合)。toast は本 scope 外 (follow-up)。

## 却下案

- raw payload 保存 (選択肢 1): secret 混入経路。
- audit_events 流用 (選択肢 2): 責務混在。
- SSE real-time (live update): L-3 SSE は AgentRun 専用、webhook real-time は別 ADR / polling で代替。
- mutation endpoint: 受信は既存 ingress、read-only に限定。

## リスク

- **payload secret 混入** (F-Q3): allowlist 抽出 + raw payload 非保存 + 全 string field の max length bound に
  加え、**抽出 DTO の全 string field に raw-secret/canary scanner を必須適用**し hit 時は当該 field を redact。
  field 名 allowlist だけでは値に混入した token を防げないため、**値レベル redaction を保存前に必ず通す**
  (GitHub payload は外部由来 untrusted、保存 field の allowlist 固定 + 値 scan の二段が核)。
- **cross-tenant / cross-project leak** (F-Q1): tenant は **verified installation の secret_ref が属する
  tenant から fail-closed 導出**。repository binding は `(tenant_id, provider='github', external_id)` +
  installation 一致を要求し、不一致は通常保存せず quarantine + audit のみ。repository_id NULL event も
  owner-only quarantine に分離し read feed に出さない。
- **header poisoning / replay** (F-Q2): `X-GitHub-Delivery` (UUID) + `X-GitHub-Event` (enum) header validation +
  payload shape との一致確認で header 偽装を弾く。`(tenant_id, delivery_id)` unique は **redelivery dedup**、
  別途 `payload_hash + installation_id + tenant_id` の **security replay guard** で delivery_id 差し替えによる
  同一 signed body の再注入を塞ぐ。
- **persist 失敗による silent event loss** (F-Q4 + F-006): §(d) の **単一 failure path に固定**。parse
  validation failure → quarantine + 202 (verification 維持)、**persist transient failure → replay claim 戻し +
  5xx** (GitHub redelivery 誘発、202 は返さない)。dedup / validation quarantine のみ 202。transaction 境界を
  明示し step 3 rollback でも verification audit が残り再処理可能。
- **同一 delivery_id の body すり替え** (F-005): `(tenant_id, delivery_id)` unique conflict 時に `payload_hash`
  比較。一致 → idempotent accepted、不一致 → audit alert + quarantine (`ON CONFLICT DO NOTHING` で握り潰さない)。
- **read endpoint の cross-project leak** (F-002): tenant scope だけでなく **actor の閲覧可能 project /
  repository capability で絞る** (ADR-00041 先例)。
- **repo 未解決 / ambiguous**: `status='quarantined'` + reason で記録 (event は失わない)、通常 feed 非表示。
- **複合 FK SET NULL の tenant_id 巻き込み** (F-003): `ON DELETE SET NULL (repository_id)` (PG16 column-list)
  で repository_id のみ NULL 化、`tenant_id NOT NULL` を保つ。

## rollback 手順

1. **既存 schema / data に対して additive** (新 table + read endpoint + payload parse hook + frontend)。
   既存テーブルへの破壊的変更はない。
2. rollback: revert PR + migration downgrade (新 table drop)。**downgrade は新規蓄積した webhook event
   data を破棄する** (= 既存 data には lossless だが、本機能で貯めた event row は消える、F-011)。必要なら
   downgrade 前に event row を CSV/JSON export する手順を残す。
3. parse hook は verification accepted 後の独立処理 (§(d)) なので、revert で **ingress security (HMAC verify /
   replay claim) は不変**。parse hook を feature flag で無効化すれば table は残したまま受信を止められる。

## 実装対象ファイル

- `migrations/versions/00NN_sp028_github_webhook_events.py` (table + enum/length CHECK + 複合 FK column-list
  SET NULL + read index)
- `backend/app/db/models/github_webhook_event.py` (ORM + CheckConstraint、5+ source 整合)
- `backend/app/domain/...` event_kind / status / quarantine_reason の Python Literal + Pydantic (enum 整合)
- `backend/app/services/repoproxy/webhook_event_parser.py` (verifier-derived tenant + allowlist 抽出 +
  値レベル redaction + repo lookup + dedup hash 比較 + 単一 failure path persist)
- `backend/app/api/github_webhooks.py` (verification accepted 後に parse hook、§(d) failure path)
- 新 `backend/app/api/webhook_events.py` (read endpoint: project/capability scope + cursor + quarantine view)
- `frontend/lib/domain/webhook-event.ts` (client-safe pure) + `frontend/lib/api/webhook-events.ts`
  (server fetch、`cache: 'no-store'` + session-bound)
- `frontend/app/(admin)/...` webhook activity view + nav
- tests: parser (no-DB unit、allowlist/値 redaction/tenant 導出/lookup/audit redaction) + DB-gated
  (persist/dedup hash/FK SET NULL/CHECK/read scope) + frontend vitest (cache/text-only/RSC 境界)

## テスト指針 (must-ship)

- **parse allowlist**: 各 event_kind で allowlist field のみ抽出、raw payload が保存 field に出ない。
- **値レベル redaction (F-Q3)**: title / sender_login 等の allowlist field に **secret-shaped 値 (GitHub
  token / age key / canary) を注入 → 保存値が redact される** (field 名 allowlist を通過した値も scan される
  ことを確認、`assert_no_raw_secret` 相当 + 全 string field の max length / NFC / control-char 除去)。
- **tenant 導出 fail-closed (F-Q1)**: verified installation → tenant_id 導出、installation と payload の
  repository.owner が **別 tenant を指す場合は通常保存せず quarantine + audit**。repository_id NULL event は
  read feed に出ない (owner-only quarantine 分離)。
- **verifier contract / tenant 導出 (F-001)**: tenant は verified secret_ref の tenant のみから導出。
  installation_id 欠落 / 複数 tenant secret match / mapping 不存在 → **fail-closed reject (row 作らない)**。
  検証前 payload の installation_id を tenant lookup に使わない。
- **repo lookup contract (F-009)**: `(tenant_id, 'github', external_id)` unique 解決 + installation_ref 一致 →
  accepted。0 件 → `unregistered_repo` quarantine、複数/不一致 → `repo_lookup_ambiguous`、別 tenant 解決 →
  `cross_tenant_mismatch`。いずれも verified tenant 下にのみ記録。
- **audit/log redaction (F-007)**: parse failure / quarantine / exception path で **raw payload / 抽出前値が
  audit・log・exception message に出ない** (allowlist: delivery_id / event_kind / tenant_id / installation_id /
  payload_hash prefix / reason_code のみ)。secret-shaped 値注入で確認。
- **header poisoning (F-Q2)**: header event_kind と payload 実体の mismatch → 保存拒否 / quarantine。
- **dedup hash 比較 (F-005)**: 同一 `(tenant_id, delivery_id)` で **同一 body → 1 row idempotent accepted**、
  **異なる body → audit alert + quarantine** (silent accept しない)。
- **persist 失敗の単一 path (F-Q4 + F-006)**: parse validation failure → quarantine row + 202 (verification 維持) /
  **persist transient failure → replay claim 戻し + 5xx (202 を返さない)** / dedup conflict → 202。silent loss なし。
- **複合 FK SET NULL (F-003)**: repository 削除で event row の **repository_id のみ NULL 化、tenant_id は保持**
  (DB-gated、PG16 column-list SET NULL)。
- **DB-level 防御 (F-010)**: event_kind / status / quarantine_reason の enum CHECK、各 string field の length
  CHECK が parser bypass insert を reject (5+ source 整合)。
- **received_at server clock (F-013)**: payload/header の timestamp を保存しない。received_at は server 採番
  (外部入力で ordering 操作できない)。
- **read endpoint scope (F-002)**: authenticated 必須、**actor の閲覧可能 project/repository に限定**
  (同一 tenant 内 cross-project の event を返さない)、limit clamp、cursor ordering 安定、非機密 field のみ、
  通常 feed は `status='accepted' AND repository_id IS NOT NULL`、quarantine は admin capability のみ。
- **frontend cache (F-008)**: tenant-scoped server fetch が `cache: 'no-store'` / session-bound で
  static cache に乗らない (別ユーザー leak なし)。
- **frontend 表示**: state badge / PR / push、text-only rendering (dangerouslySetInnerHTML なし)、
  RSC server/client 境界 (next build OK)。

## Hard Gates / KPI への trace

- 既存 Hard Gate / KPI に regression なし (additive read + ingress 不変)。
- DD-04 webhook ingress security 不変 + redaction invariant に整合。
