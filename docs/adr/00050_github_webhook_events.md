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

最終更新: 2026-06-05 (Codex plan-review R1 15 + R2 5 findings 全 adopt、CRITICAL=0、best-effort enrichment に reframe)

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

- **DB migration を伴う (ADR Gate #2)**: 新 `github_webhook_events` table。既存 schema/data に additive
  (既存 table 不変)。downgrade は新 table drop = 蓄積 event row は失われる (要 export、F-011、rollback §参照)。
- **read-only API (ADR Gate #3)**: webhook event 一覧 endpoint。mutation は無し (受信は既存 ingress)。
- tenant / project 境界を維持 (複合 FK)。repository は `(tenant_id, id)` で紐付け。
- **raw secret / token を保存・表示しない**: payload から **allowlist した非機密 field のみ**抽出
  (action / number / state / sha / title / sender.login)。raw payload は保存しない (redaction)。
- **既存 ingress security contract を一切変更しない (R2 F-001/F-002/F-005、最重要)**: `GitHubWebhookVerifier` /
  `WebhookSecretResolver` / `WebhookReplayStore` の protocol・replay key・TTL・tenant 解決 (`_tenant_id`) は
  **本 ADR で変更しない**。webhook parse + persist は **verification accepted 後の独立した best-effort
  read-only enrichment** であり、security-critical な replay store の改修 (release 追加等) は本 ADR scope 外
  (それ自体が別 ADR Gate 案件)。読み取り専用の表示機能のために ingress 安全境界を不安定化させない。
- **P0 single-tenant scope (R2 F-001)**: P0 は単一 tenant。tenant は既存 `_tenant_id(request)` (request.state /
  default_tenant_id) を踏襲 = P0 では webhook secret が属する単一 tenant と一致する。installation_id は
  **HMAC 検証成功後**に trusted となった signed body field として使う。**multi-tenant の verifier-derived
  tenant (複数 installation が別 tenant に跨る場合) は forward requirement** として記録し、P0 では実装しない。
- **verification accepted のときのみ** parse + persist。
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
| `quarantine_reason` | text NULLABLE、**DB CHECK enum** (`unregistered_repo` / `repo_lookup_ambiguous` / `payload_shape_mismatch` / `header_event_mismatch` / `parse_validation_failed`、status='quarantined' 時のみ NOT NULL、F-004/F-015/R2-F-004)。全 quarantine 経路を網羅 (repo lookup + parser/header validation)。hash mismatch は audit-only で row 非作成 (R2 F-003) |
| `action` | text NULLABLE、**DB CHECK length ≤ 64** (opened / closed / completed / synchronize 等) |
| `external_ref` | text NULLABLE、**DB CHECK length ≤ 255** (PR number / check id / commit sha) |
| `state` | text NULLABLE、**DB CHECK length ≤ 32** (open / closed / merged / success / failure / pending / neutral 等) |
| `title` | text NULLABLE、**DB CHECK length ≤ 512** (PR title 等、redacted、最大長 bound) |
| `sender_login` | text NULLABLE、**DB CHECK length ≤ 64** (GitHub actor login、非機密) |
| `received_at` | timestamptz NOT NULL、**server clock で採番** (payload/header timestamp は使わない、ordering 改竄防止、F-013) |
| `created_at` | timestamptz NOT NULL |

- **unique** `(tenant_id, delivery_id)` で **再配信 dedup** (GitHub は webhook を redeliver する)。conflict 時は
  `payload_hash` 比較: 一致 → idempotent accepted、不一致 → 既存 row 保持 + audit anomaly のみ (quarantine row
  非作成、unique 衝突回避、F-005 + R2-F-003)。
- **複合 FK** `(tenant_id, repository_id) → (repositories.tenant_id, repositories.id)` を **`ON DELETE SET NULL
  (repository_id)`** (PostgreSQL 16 の column-list SET NULL、tenant_id は NULL 化しない、F-003)。repo 削除で
  event は残すが紐付け解除、repository_id NULL 許容。**repository は `(tenant_id, provider='github', external_id)`
  の既存 unique で一意解決**、installation_ref 一致を要求 (F-009)。
- DB-level CHECK / length は parser の bound と同一定数で揃え、parser bypass / 将来の bulk import に対する
  最後の防衛線にする (5+ source 整合、F-010)。`event_kind` / `status` / `quarantine_reason` は固定 enum。
- **read index**: `(tenant_id, status, repository_id, received_at DESC, id DESC)` で通常 feed query + cursor
  pagination を支える (F-012)。

### payload 処理 (verification accepted のときのみ、R1 findings 反映)

#### (a) tenant は accepted verification 後に確定、repo は fail-closed 解決 (R1 F-Q1 + Codex F-001/F-009 + R2 F-001)

- **P0 の tenant 解決 (R2 F-001、既存 contract 踏襲)**: parse は **HMAC verification accepted 後**に走る。
  この時点で `installation_id` は signed body field として trusted。P0 single-tenant では `tenant_id` は既存
  `_tenant_id(request)` (request.state / default_tenant_id) を使う = webhook secret が属する単一 tenant と一致。
  **既存 verifier / resolver の contract は変更しない** (前提/制約 参照)。
- **forward requirement (multi-tenant)**: 複数 installation が別 tenant に跨る将来は、verifier が検証成功した
  `secret_ref` の tenant を返す contract へ拡張し、未検証 installation_id を tenant lookup に使わない設計へ
  移行する。P0 では single-tenant のため不要、本 ADR では forward note のみ。
- **repository lookup contract (F-009、concrete)**: payload の `repository.id` (= external_id) を
  **`(tenant_id, provider='github', external_id)` の既存 unique で解決** (`repositories_uq_tenant_provider_external`、
  0 or 1 row)。解決 row の `installation_ref` が **verified installation と一致**することを要求する。
  - 一致 → `status='accepted'`、`repository_id` set。
  - 0 件 (未登録 repo) → `status='quarantined'`, `quarantine_reason='unregistered_repo'`, `repository_id=NULL`
    (verified tenant 下に記録、通常 feed 非表示)。
  - 複数件 / installation_ref 不一致 → `status='quarantined'`, `quarantine_reason='repo_lookup_ambiguous'`。
  - **lookup は常に `tenant_id` scope** (P0 single-tenant では別 tenant 解決は構造上発生しない)。`tenant_id` 外の
    repository に書き込む経路は持たない (cross-tenant/project leak 防止)。
- quarantine の実体は §(e) 参照。`status='quarantined'` event は通常 read feed に出さない。

#### (b) header validation + dedup + hash-mismatch anomaly (R1 F-Q2 + Codex F-005 + R2 F-002/F-003)

- `X-GitHub-Delivery` (delivery_id) は **length/形式 validation**、`X-GitHub-Event` (event_kind) は **enum validation**。
- **payload shape validation**: header の event_kind と payload body の実体 (PR なら pull_request key 存在等)
  が一致しない場合は **新 delivery_id の quarantine row として記録** (header poisoning 防止、unique conflict なし)。
- **dedup (R2 F-002 修正、誤った replay claim を撤回)**: 既存 ingress の replay guard は **delivery_id nonce 単位**
  (`github-webhook:{tenant}:{installation}:sha256(delivery_id)`、TTL 3600s) であり、**signed body 単位ではない**。
  本 ADR は **既存 replay store を変更しない** (前提/制約)。event table 側の dedup は `(tenant_id, delivery_id)`
  unique で GitHub の正常 redelivery を冪等化する。
- **dedup conflict 時の hash mismatch (R2 F-003、unique 制約と両立)**: `(tenant_id, delivery_id)` conflict 時は
  既存 row の `payload_hash` と比較する。
  - **一致** → 正常 redelivery、idempotent (新規 row 作らない、202)。
  - **不一致** (同一 delivery_id で別 body、通常は発生しない異常) → **既存 accepted row は保持したまま
    `audit_events` に anomaly record (reason_code のみ、raw payload なし) を残す**。**quarantine row は作らない**
    (unique 制約と衝突するため、anomaly は audit-only forensic trail で表現)。新 body は drop。
- **residual risk (R2 F-002)**: delivery_id を差し替えた同一 signed body の再注入は、既存 delivery_id-nonce
  replay guard を通過し event table に別 row として受理され得る。影響は **read-only 表示の activity-log 行が
  重複する程度** (mutation / secret なし、低影響)。本 ADR scope では replay store を改修せず **residual risk
  として記録** (将来 payload_hash claim 追加で hardening 可能、別 ADR)。

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

#### (d) 失敗時シーケンス (R1 F-Q4 + Codex F-006 + R2 F-005、best-effort enrichment に固定)

R2 F-005 で判明: 既存 `WebhookReplayStore` は `claim_once()` のみ (release なし)、TTL 3600s 固定。よって
「replay claim を戻して 5xx redelivery」は **既存 ingress contract を変えないと実装不能**。read-only 表示機能の
ために security-critical な replay store を改修しない方針 (前提/制約) に従い、**parse + persist を verification
後の best-effort enrichment に固定**する:

```
1. HMAC verify + replay claim (既存 ingress、本 ADR では一切変更しない)
2. verification audit を commit (security ingress 成功確定、本 ADR の責務外で既存どおり)
3. parse + persist (verification accepted の後段、独立 transaction):
   - parse validation failure (shape 不正 / header mismatch / lookup ambiguous):
       新 delivery_id の status='quarantined' row を insert + audit → 202 (event は失わず quarantine)
   - dedup conflict ((tenant_id, delivery_id) 既存): §(b) hash 比較 → 一致は idempotent 202 /
       不一致は audit anomaly + drop (row 追加なし)
   - success: status='accepted' で commit → 202
   - persist transient failure (DB timeout 等): parse/persist 内で **bounded retry**。それでも失敗時は
       error を log (raw payload なし) し 202 を返す。**event は best-effort なので欠落し得る**
       (replay store を戻せないため redelivery で復旧できない、§residual risk)。
```

- **既存 ingress 応答 contract を変えない**: verification 自体の成否は既存どおり。parse/persist は後段の
  best-effort であり、その失敗で ingress (verification) を巻き戻さない。
- **residual risk (R2 F-005、honest scoping)**: transient persist failure が bounded retry でも回復しない稀な
  ケースで、当該 webhook の **activity-log 行が欠落**し得る。GitHub の自動 redelivery は同一 delivery_id が
  replay guard (TTL 3600s) で弾かれるため自動復旧しない。**影響は read-only 表示 1 行の欠落** (mutation /
  secret / 整合性影響なし)。復旧は replay window 経過後の **manual redelivery** で可能。replay store に
  release/compare-delete を足して厳密な no-loss にするのは **別 ADR (ingress security boundary 変更)**。

#### (e) quarantine の実体 (Codex F-004 + F-015)

- quarantine は **別 table ではなく同 `github_webhook_events` table の `status='quarantined'` row** で表現
  (verified tenant 下に記録、新 delivery_id なので unique 衝突なし)。`quarantine_reason` enum (5 種、repo lookup +
  parser/header validation) で原因を保持。**hash mismatch は audit-only** で quarantine row を作らない (R2 F-003)。
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
- **cross-tenant / cross-project leak** (F-Q1 + R2-F-001): P0 single-tenant では tenant は既存
  `_tenant_id(request)` 踏襲 (= webhook secret が属する単一 tenant)。repository lookup は常に
  `(tenant_id, 'github', external_id)` tenant-scope + installation_ref 一致。tenant 外 repository への書込経路を
  持たない。read endpoint は project/capability で更に絞る (F-002、ADR-00041)。multi-tenant verifier-derived
  tenant は forward requirement。
- **header poisoning** (F-Q2): `X-GitHub-Delivery` + `X-GitHub-Event` header validation + payload shape 一致確認で
  header 偽装を弾き、新 delivery_id の quarantine row として記録 (raw payload なし)。
- **dedup と body すり替え** (F-005 + R2-F-002/F-003): event table dedup は `(tenant_id, delivery_id)` unique
  (GitHub 正常 redelivery 冪等化)。conflict 時 `payload_hash` 比較で一致=idempotent、不一致=audit anomaly のみ
  (quarantine row は unique 衝突を避け非作成)。delivery_id 差し替えの同一 body 再注入は既存 delivery_id-nonce
  replay guard を通過し得る → **residual risk** (read-only 表示行の重複、低影響、別 ADR で payload_hash claim hardening)。
- **persist 失敗による event 欠落** (F-Q4 + F-006 + R2-F-005): parse/persist は **verification 後の best-effort
  enrichment**。validation failure → quarantine row + 202、transient failure → bounded retry 後も失敗なら log + 202。
  既存 security-critical replay store (release なし、TTL 3600s) を本 ADR で変更しないため、**transient 失敗時に
  activity-log 行が欠落し得る** (read-only 表示 1 行、mutation/secret 影響なし、manual redelivery で復旧)。
  厳密 no-loss は replay store 改修 = 別 ADR (ingress security boundary)。
- **read endpoint の cross-project leak** (F-002): tenant scope だけでなく **actor の閲覧可能 project /
  repository capability で絞る** (ADR-00041 先例)。通常 feed は `status='accepted' AND repository_id IS NOT NULL`。
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
- `backend/app/services/repoproxy/webhook_event_parser.py` (新規: P0 tenant 踏襲 + allowlist 抽出 +
  値レベル redaction + tenant-scope repo lookup + dedup hash 比較 + best-effort persist)
- `backend/app/api/github_webhooks.py` (verification accepted 後に parse hook を呼ぶ最小追加、§(d) best-effort path)
- 新 `backend/app/api/webhook_events.py` (read endpoint: project/capability scope + cursor + quarantine view)
- **変更しないファイル (R2-F-001/F-002/F-005、ingress security boundary)**: `webhook_service.py` /
  `webhook_adapters.py` の `GitHubWebhookVerifier` / `WebhookSecretResolver` / `WebhookReplayStore` protocol /
  replay key / TTL は **本 ADR で触らない** (別 ADR 案件)。
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
- **tenant 解決 (F-Q1 + R2-F-001、P0)**: parse は verification accepted 後に走り、`tenant_id` は既存
  `_tenant_id(request)` 踏襲、`installation_id` は verified signed body field。tenant-scope を超えた書込が
  発生しないことを確認。既存 verifier/resolver contract を変更しない (回帰なし)。
- **repo lookup contract (F-009 + R2-F-001)**: `(tenant_id, 'github', external_id)` unique 解決 + installation_ref
  一致 → accepted。0 件 → `unregistered_repo` quarantine、複数/不一致 → `repo_lookup_ambiguous`。lookup は
  常に tenant-scope (別 tenant 解決は構造上不可)。
- **audit/log redaction (F-007)**: parse failure / quarantine / exception path で **raw payload / 抽出前値が
  audit・log・exception message に出ない** (allowlist: delivery_id / event_kind / tenant_id / installation_id /
  payload_hash prefix / reason_code のみ)。secret-shaped 値注入で確認。
- **header poisoning (F-Q2 + R2-F-004)**: header event_kind と payload 実体の mismatch → 新 delivery_id の
  `header_event_mismatch` / `payload_shape_mismatch` quarantine row。
- **dedup + hash anomaly (F-005 + R2-F-002/F-003)**: 同一 `(tenant_id, delivery_id)` で **同一 body → idempotent
  202 (1 row)**、**異なる body → 既存 row 保持 + audit anomaly record (quarantine row 非作成、unique 衝突なし)**。
  既存 replay store contract を変更しないこと (回帰なし)。
- **persist best-effort (F-Q4 + F-006 + R2-F-005)**: parse validation failure → quarantine row + 202、success →
  accepted + 202、transient persist failure → bounded retry 後 log (raw payload なし) + 202。**verification
  応答を巻き戻さない**。replay store を変更しないことを確認。
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
