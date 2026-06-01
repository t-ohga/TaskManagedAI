---
id: "ADR-00042"
title: "AgentRun Artifact 読み取り専用 REST endpoint (L-2)"
status: "proposed"
created_at: "2026-06-01"
updated_at: "2026-06-01"
deciders:
  - "t-ohga"
related_sprints:
  - "UI 改善監査 (catalog L-2)"
gate_criteria:
  - "3: API 契約 / event schema"
supersedes: []
---

# ADR-00042: AgentRun Artifact 読み取り専用 REST endpoint (L-2)

## 背景

UI 改善 catalog の **L-2「AgentRun Artifact 表示」**。AgentRun が生成する artifact (AI 出力の
plan / patch / evidence / citation / CLI 出力等) は `artifacts` table に保存されているが、UI から
参照する経路が無い。run 詳細ページで「AI が何を生成したか」を確認できないため、再現可能・評価可能な
開発プロセスという本プロダクトの価値 (証拠・判断の可視化) が UI 上で欠落している。

### 既存資産 (P0 実在、調査済 2026-06-01)

- `artifacts` table (`backend/app/db/models/artifact.py`): immutable row。主要 column:
  `id` / `tenant_id` / `project_id` / `run_id` (複合 FK → `agent_runs`) / `kind` / `content_hash`
  (SHA-256) / `content_jsonb` / `payload_data_class` / `trust_level` / `exportable` /
  `parent_artifact_id` / `created_at`。
- `ArtifactKind` (11 種): `plan` / `patch` / `evidence` / `citation` / `provider_continuation_ref` /
  `other` / `cli_input` / `cli_stdout` / `cli_stderr` / `cli_exit` / `cli_result_summary`。
- `TrustLevel` (3 種): `untrusted_content` / `validated_artifact` / `trusted_instruction`。
- **write 時 contract** (`ArtifactRepository._assert_artifact_contract`): `assert_no_raw_secret(content_jsonb)` +
  21 prohibited key + content_hash 一致検証。**保存済 artifact は raw secret 非含有が保証される**。
- `ArtifactRepository` に **read-by-run method は無い** → 追加が必要。

## 決定対象

run 詳細から artifact を読むための **read-only REST endpoint** と **repository read method** と
**frontend 配線** の契約。AI 権限の追加・mutation は一切含まない (read-only)。

## 前提 / 制約

- P0 個人専用・単一 tenant。ただし tenant / project boundary は schema・repository contract で維持。
- AI 出力直結禁止: 本 endpoint は **read-only**。artifact の生成・昇格・実行は対象外。
- secret 非露出: artifact content_jsonb は write contract で raw secret 非含有保証済だが、
  **`provider_continuation_ref` は内部 continuation 参照 (exportable=false、ContextSnapshot UI 非露出 rule)**
  のため、L-2 表示からは **除外** する。
- `payload_data_class` は表示する (sensitivity の明示)。caller からは受け取らない (Matrix / metadata 由来)。
- active-scope: soft-deleted ticket に紐づく run は既存 run 詳細経路と同じ可視性に従う。

## 選択肢

### 案 A (採用): 専用 read-only endpoint `GET /agent_runs/{run_id}/artifacts`

- `GET /api/v1/agent_runs/{run_id}/artifacts` を追加。run の可視性を確認 → artifact 一覧を返す。
- repository に `list_for_run(tenant_id, run_id)` を追加 (`provider_continuation_ref` 除外、created_at 昇順)。
- frontend: lib client + run 詳細に artifact section。

### 案 B (却下): run 詳細 endpoint (`GET /{run_id}`) の response に artifacts を inline 埋め込み

- 既存 `AgentRunDetailResponse` に `artifacts: [...]` を追加。
- 却下理由: ① 既存 run 詳細契約 (AgentRunDetailResponse) を破壊的に拡張する。② artifact が多い run で
  run 詳細 payload が肥大化し、artifact 不要な呼出にもコストが乗る。③ pagination / 段階取得の余地が無い。
  read 専用の独立 endpoint の方が契約が clean で SSE/段階ロードにも将来拡張しやすい。

### 案 C (却下): MCP のみ (REST endpoint なし)

- 既存 MCP `run_show` 等の拡張で済ませる。
- 却下理由: UI (Next.js Server Component) は内部 REST API 経由でデータ取得する設計 (既存 ticket / run /
  cost_summary 等と同じ)。UI からの read は REST endpoint が正本経路。

## 採用案 (案 A) 詳細契約 (plan-review R1 反映: active-scope 単一 query + display projection)

### endpoint

`GET /api/v1/agent_runs/{run_id}/artifacts`

- deps: `get_current_actor_id` / `get_tenant_id` / `get_db_session` (既存 run endpoint と同一)。
- route ordering: `/{run_id}/artifacts` は `/{run_id}` より具体的なため衝突しない。静的 route
  (`/cost_summary` 等) と同じ block 近傍に定義し、`/{run_id}` より前に置く (route-order test)。
- 手順: **run 可視性 + artifact 取得を単一 statement** で行う (R2 F-HIGH-3)。`agent_runs` 起点の
  active-scope SELECT に `LEFT JOIN artifacts` し、結果を解釈する:
  - **0 rows** (run 行が無い = 不存在 / tenant 外 / soft-deleted ticket bound) → **404**。
  - **run 行あり + artifact null** → run visible・artifact 0 件 → **200 empty**。
  - **run 行あり + artifact** → **200** list。
- response (`RunArtifactListResponse`): `{ "artifacts": [RunArtifact, ...] }`
  - **content_jsonb を無条件で返さない (R1/R2 F-HIGH-2)**。API layer で **display projection** を適用する。

### display projection (R1/R2 F-HIGH-2 + R2 F-HIGH-1)

各 artifact は **metadata** を返す: `id` (opaque UUID) / `kind` / `payload_data_class` /
`trust_level` / `exportable` / `parent_artifact_id` / `created_at` / `content_redacted` (bool) /
`redaction_reason` (str|null)。

**`content_hash` は `content_redacted=false` のときだけ返す (R6 F-HIGH-2)**。`content_hash` は保存済み raw
`content_jsonb` の SHA-256 であり、redaction (exportable=false / confidential/pii / scrub hit) しても同一 hash を
返すと、低エントロピー PII や既知候補の SecretBroker 参照を offline guess で確認できる hash oracle になる。
よって **redacted artifact では `content_hash=null`** とし、deterministic digest を side-channel にしない
(artifact 識別は opaque `id` で行う。監査用 raw hash が必要なら owner-only の別経路で分離、本 endpoint では出さない)。

`content`(表示用 body)は次の **優先順** projection で決める:

1. **kind 除外**: `provider_continuation_ref` は repository query で除外済 (返却対象に出ない、二重防御)。
2. **`exportable == false` → 全面 redaction (R2 F-HIGH-1)**: kind / data_class に関係なく content を
   返さない (`content=null` / `content_redacted=true` / `redaction_reason="non_exportable"`)。
   inter-agent message body / memory store / memory retrieval は `kind="other"` + `exportable=false` +
   public/internal で保存され得るため、これらの raw body を `exportable` flag で一律遮断する
   (ref-only / raw message body 非露出の境界。data_class 判定では防げない)。
3. **data class redaction**: `payload_data_class` が `confidential` / `pii` (ordinal >= 2) →
   `content=null` / `content_redacted=true` / `redaction_reason="data_class_confidential_or_pii"`。
4. **再帰 shape/value-aware scrub (R2 F-HIGH-2 / R3 F-HIGH / R4 F-HIGH)**: 残り (`exportable=true` かつ
   public/internal) の content は表示前に **再帰 scrub** を適用。別 artifact の content_jsonb に混入し得る
   continuation/session/thread/provider ref / secret_ref を、**object key と string value の両方** で除去する。
   - **前処理 (R4 F-HIGH / R5 F-HIGH)**: 判定前に **NFKC 互換正規化** + trim + **制御 / format 文字 (Cc/Cf)
     除去** + **casefold (大文字小文字無視)** を行う (全角 / 互換幅 / zero-width / 大小文字のすり抜け防止)。
   - **name denylist** — **object key と string value の両方** に同一判定 (R3 F-HIGH: key 経由露出も封鎖):
     - continuation/session/thread/provider 系 (正規化後 casefold 一致): `provider_continuation_ref` /
       `continuation_ref` / `continuation_id` / `provider_continuation` / `session_ref` / `session_id` /
       `session_token` / `thread_ref` / `thread_id` / `provider_request` / `provider_request_body` /
       `provider_response` / `raw_response` / `continuation` (+ camelCase variants)。
     - **SecretBroker 参照系 (R5 F-HIGH)**: `secret_ref` / `secret_ref_id` / `secret_uri` /
       `secret_capability` / `capability_token` (+ camelCase variants `secretRef` / `secretRefId` /
       `secretUri` / `capabilityToken`)。SecretBroker 識別子 / トポロジは専用 secret_refs viewer
       (R-3、owner-only gate) 経由のみで、artifact endpoint からは露出させない。
   - **forbidden URI token scan (R4 F-HIGH)** — **object key と string value の両方** に対し、正規化後の文字列の
     **任意位置 (substring)** で次の token を検出: `secret://` / `provider-continuation:`
     (自由文 cli_stdout/stderr/evidence に `failed to resolve secret://...` のように埋め込まれた場合も
     先頭でなく途中を検出して捕捉)。hit した key は key-value ごと drop、hit した string value は値全体を
     redaction marker (`"[redacted: forbidden URI token]"`) に置換。
   - **自由文 token=value scan (R6 F-HIGH-1)** — string value 中に、denylist token
     (`secret_ref_id` / `secret_ref` / `secret_uri` / `capability_token` / `secret_capability` /
     `continuation_id` / `session_id` / `session_token` / `thread_id` 等) が `[:=]` または空白を挟んで
     値を伴う自由文 (例 `failed to resolve secret_ref_id=sr_project_openai_v1` / `capability_token abc123`)
     を正規化済み regex で検出し、**値全体を redaction marker に置換** (key 名でも shape でも URI でもない
     ログ文字列経由の SecretBroker / continuation 識別子露出を封鎖)。
   - **shape denylist** (nested object 形状、再帰): ① `artifact_ref`/`artifactRef` + (`sha256` または
     `expires_at`/`expiresAt`) を持つ object (continuation ref 形状)、② `secret_ref_id` を持つ object、
     または `scope` + `name` + `version` を併せ持つ object (secret_ref メタデータ形状、R5 F-HIGH) を drop。
   - いずれか hit で `content_redacted=true` / `redaction_reason="forbidden_content_scrubbed"`。
5. 上記を全て満たした残りを `content` として返す (`exportable=true` + public/internal + scrub 済)。

> projection は **API layer (response 構築)** で行い、`content_jsonb` raw は API 境界を越えない。

### repository read method (R2 F-HIGH-3: run-visible sentinel + active-scope 単一 statement)

`ArtifactRepository.list_run_artifacts(tenant_id: int, run_id: UUID) -> RunArtifactRows | None`
(`agent_runs` 起点。`None` = run 不可視 → 404、`RunArtifactRows` (空 list 可) = visible):

```sql
select r.id as run_id,
       a.id as artifact_id, a.kind, a.content_hash, a.content_jsonb,
       a.payload_data_class, a.trust_level, a.exportable, a.parent_artifact_id, a.created_at
  from agent_runs r
  left join artifacts a
    on a.tenant_id = r.tenant_id
   and a.project_id = r.project_id
   and a.run_id = r.id
   and a.kind <> 'provider_continuation_ref'
 where r.tenant_id = :tenant_id
   and r.id = :run_id
   and not exists (
     select 1 from tickets dt
      where dt.tenant_id = r.tenant_id
        and dt.project_id = r.project_id
        and dt.id = r.ticket_id
        and dt.deleted_at is not null
   )
 order by a.created_at, a.id;
```

- **run 起点の inner 条件** (`r.tenant_id` + `r.id` + soft-delete NOT EXISTS) が run 可視性を決め、
  `LEFT JOIN artifacts` が artifact を集める。0 rows → run 不可視 → 404。run 行 + artifact null →
  200 empty。**404/200-empty の区別と active-scope を同一 statement** で閉じる (TOCTOU / 将来再利用でも
  fail-closed)。`project_id` は run 行から導出 (caller 入力不要)。`_ensure_tenant_context` 経由。
- runs に ticket_id が無い (null) 場合は NOT EXISTS が真 = visible (既存 active-scope helper と同義)。

### frontend

- `lib/api/agent-runs.ts` (or 専用 module): `fetchRunArtifacts(runId)` + Zod schema (strict、content は
  optional/nullable、`content_redacted` / `redaction_reason` を持つ)。
- run 詳細 (`app/(admin)/runs/[id]/`) に「生成物 (Artifact)」section。
  - 各 artifact: kind / trust_level / payload_data_class バッジ + content (redacted 時は「機密分類のため
    非表示 (hash: ...)」等の説明)。
  - 取得失敗は section 単位で degrade。run 詳細全体は落とさない。
  - secret / raw provider response / continuation ref は DOM に出さない (projection で除去済)。

## リスク

| リスク | 対策 |
|---|---|
| active-scope TOCTOU + 404/200-empty 判別不可 (R1 F-HIGH-1 / R2 F-HIGH-3) | `agent_runs` 起点 LEFT JOIN artifacts の単一 statement で run 可視性 (soft-delete 除外) と artifact 集約を同時に行い、0 rows→404 / run 行+artifact null→200-empty を判定。SQL introspection + 404/empty negative |
| `exportable=false` artifact (inter-agent message / memory body) の raw body 露出 (R2 F-HIGH-1) | projection 優先順 2 で `exportable=false` を kind/data_class 問わず全面 redaction。`kind="other"` + `exportable=false` + public/internal fixture を必須 negative test |
| continuation ref / SecretBroker secret_ref の key/value/shape/埋め込み すり抜け (R2-R5 F-HIGH) | 再帰 scrub を **object key と string value の両方** に適用 (continuation/session/provider + **SecretBroker 参照 (`secret_ref`/`secret_ref_id`/`secret_uri`/`capability_token`)** name 一致 + camelCase + `secret://`/`provider-continuation:` を **任意位置 substring** + shape (`artifact_ref`+`sha256`/`expires_at`、`secret_ref_id`、`scope`+`name`+`version`))。前処理 **NFKC + trim + Cc/Cf 除去 + casefold**。key 経由 / 埋め込み / 全角 / secret_ref 構造 fixture を negative test |
| confidential/pii 本文の拡散 | projection 優先順 3 で content=null + redacted。badge 表示を access control の代替にしない |
| 自由文ログ経由の secret_ref/continuation token 露出 (R6 F-HIGH-1) | string value の token=value 自由文 (`secret_ref_id=...` / `capability_token ...`) を regex で whole-value redaction。log 形式 fixture を must-ship negative test |
| redacted artifact の content_hash hash-oracle side-channel (R6 F-HIGH-2) | `content_redacted=true` では `content_hash=null` (raw content の deterministic digest を出さない)。redacted response で hash 非露出の test |
| `provider_continuation_ref` の UI 露出 (ContextSnapshot rule 違反) | repository query で kind 除外 + projection (exportable=false redaction + shape scrub) の三重防御 |
| route 衝突 (`/{run_id}` と `/{run_id}/artifacts`) | route-order test |
| tenant/project 越境 | run 起点 query の複合境界。seed-based negative は CI Compose |
| content の肥大化 | P0 は単一 run の artifact 一覧で実用上問題なし。pagination は独立 endpoint で将来拡張余地 |

## rollback 手順

- 純粋な追加 (新 endpoint + repository read method + frontend section)。migration なし。
- rollback: 追加した endpoint / repository method / frontend section を revert するのみ。既存契約・
  schema・データに影響なし。

## 実装対象ファイル

- `backend/app/repositories/artifact.py`: `list_for_run` read method 追加。
- `backend/app/api/agent_runs.py`: `GET /{run_id}/artifacts` endpoint + `RunArtifact` /
  `RunArtifactListResponse` Pydantic schema。
- `frontend/lib/api/agent-runs.ts` (or 新 module): `fetchRunArtifacts` + Zod schema。
- `frontend/app/(admin)/runs/[id]/`: artifact section component + 配線。
- test: `backend/tests/api/test_run_artifacts.py` (新) + frontend test。

## テスト指針

- backend (host は conftest test-password 不一致で seed-based DB 不可 → **SQL introspection + capturing
  session に fake rows** pattern を踏襲、ADR-00039/00040/00041 と同経路):
  - route 登録 (`/{run_id}/artifacts`) + route-order (run 詳細 `/{run_id}` に飲み込まれない)。
  - **active-scope + sentinel SQL introspection (R1 F-HIGH-1 / R2 F-HIGH-3)**: `list_run_artifacts` の生成
    SQL が `agent_runs` 起点 + `left join artifacts` + `tenant_id` + `run_id` +
    `kind <> 'provider_continuation_ref'` + soft-delete 除外 (`tickets ... deleted_at is not null` の
    NOT EXISTS) を **同一 statement** に含む (compile SQL に全 predicate が出ることを assert)。
  - **404 vs 200-empty (R2 F-HIGH-3)** — fake rows を capturing session に返して区別を検証:
    run 0 rows → 404、run 行 + artifact null → 200 empty list、run 行 + artifact → 200 list。
  - **display projection (R2 F-HIGH-1/2)** — fake rows を返して response を検証:
    - `exportable=false` (kind=other / public) → `content=null` / `content_redacted=true` /
      `redaction_reason="non_exportable"` (inter-agent / memory body の遮断)。
    - `payload_data_class` ∈ {confidential, pii} → `content=null` / `redaction_reason="data_class_confidential_or_pii"`。
    - public/internal + exportable=true の content に次を混入 → 再帰 scrub で除去 + `content_redacted=true` /
      `redaction_reason="forbidden_content_scrubbed"` (must-ship negative fixtures):
      - denylist key (`session_token` / `provider_response` / **`secret_ref_id`** / **`secret_uri`**) /
        camelCase (`providerResponse` / **`secretRefId`**)。
      - **URI token を持つ JSON key (R3 F-HIGH)**: `{"secret://sops/project/openai-api-key#v1": true}` /
        `{"provider-continuation:openai:abcd": {...}}` (key 経由の secret_ref / continuation 露出)。
      - **埋め込み URI token を持つ自由文 value (R4 F-HIGH、先頭でない位置)**:
        `cli_stdout: "failed to resolve secret://sops/project/openai-api-key#v1"` /
        `cli_stderr: "retry provider-continuation:openai:abcd"` → 値全体を redaction marker に置換。
      - **全角 / 互換幅 / zero-width / 大小文字 variant** の URI token (NFKC + Cc/Cf 除去 + casefold)。
      - **SecretBroker 参照 key / 構造 (R5 F-HIGH)**: `{"secret_ref_id":"..."}` /
        `{"target":{"secret_ref_id":"..."}}` / `{"secret_ref":{"scope":"project","name":"openai-api-key","version":"v1"}}`
        / camelCase (`secretRefId`)。
      - **自由文 token=value ログ (R6 F-HIGH-1)**: `cli_stdout: "failed to resolve secret_ref_id=sr_project_openai_v1"` /
        `cli_stderr: "use capability_token abc123"` → 値全体を redaction marker に置換。
      - shape (`{artifact_ref, sha256, expires_at}` / `{scope, name, version}`)。
    - clean な public/internal + exportable=true content → そのまま返る (`content_redacted=false`)。
  - **redacted 時の hash 非露出 (R6 F-HIGH-2)**: `content_redacted=true` の全ケース (exportable=false /
    confidential/pii / scrub hit) で response の `content_hash` が `null` (raw hash を side-channel として出さない)。
    `content_redacted=false` のときだけ `content_hash` が非 null。
  - response schema が secret / raw provider / continuation field を持たない。`provider_continuation_ref` 除外固定。
  - seed-based tenant/project 越境 + soft-delete + non-exportable negative は CI Compose postgres で検証 (host 不可)。
- frontend: `fetchRunArtifacts` の Zod strict (content nullable + redaction フラグ) + run 詳細 artifact
  section の表示 / redacted 表示 / degrade。

## 不変条件 trace

- AI 出力直結禁止: read-only、mutation/昇格/実行なし。
- secret / 非露出データ非拡散: content_jsonb raw を API 境界外に出さない。display projection で
  confidential/pii redaction + 再帰 denylist scrub + `provider_continuation_ref` kind 除外。
  ContextSnapshot UI 非露出 rule と PII 非拡散を artifact 経路でも維持。
- tenant / project boundary: repository が `AgentRun` join で複合境界 + active-scope を同一 statement で enforce。
- active-scope: soft-deleted ticket run は 404、artifact query 単体でも fail-closed。
- `payload_data_class` は Matrix/metadata 由来を表示、caller 入力なし。
- AgentRun 16 状態 / Provider Compliance / SecretBroker に変更なし。migration なし (read + projection のみ)。
