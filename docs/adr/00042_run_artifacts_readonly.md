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
- 手順:
  1. **run 可視性 + active-scope 確認**: 既存 run 詳細経路と同じ active-scope (soft-deleted ticket
     run の不可視) で run を取得。不存在 / tenant 外 / soft-deleted ticket bound → **404** (200-empty と区別)。
  2. `ArtifactRepository.list_for_run(...)` で artifact を取得。**この SELECT 自体が `AgentRun` と join し、
     `tenant_id` + `run_id` + `soft_deleted_ticket_run_exclusion()` 相当を同一 statement で満たす場合だけ返す**
     (R1 F-HIGH-1: 可視性確認と取得を分離せず、artifact query 単体でも fail-closed。step 1 後の
     soft-delete / 将来 preflight なし再利用でも不可視 run の body を返さない)。`provider_continuation_ref`
     除外、created_at 昇順。
- response (`RunArtifactListResponse`): `{ "artifacts": [RunArtifact, ...] }`
  - **content_jsonb を無条件で返さない (R1 F-HIGH-2)**。API layer で **display projection** を適用する。

### display projection (R1 F-HIGH-2)

各 artifact は **metadata は常時** 返す: `id` / `kind` / `content_hash` / `payload_data_class` /
`trust_level` / `exportable` / `parent_artifact_id` / `created_at` / `content_redacted` (bool) /
`redaction_reason` (str|null)。

`content`(表示用 body)は projection で決める:

1. **kind 除外**: `provider_continuation_ref` は repository query で除外済 (返却対象に出ない)。
2. **data class redaction**: `payload_data_class` が `confidential` / `pii` (ordinal >= 2) の artifact は
   **content を返さない** (`content=null` / `content_redacted=true` / `redaction_reason="data_class_confidential_or_pii"`)。
   metadata + content_hash のみ表示し、本文は出さない (PII / confidential 非拡散、badge 表示を
   access control の代替にしない)。privileged reveal は P0 では実装せず将来拡張余地。
3. **recursive key denylist scrub**: `public` / `internal` の content は、表示前に **再帰 denylist scrub** を
   適用する。別 kind の content_jsonb に混入し得る continuation / session / thread / provider ref 系の
   キーを除去する。denylist (再帰、object key 一致):
   `provider_continuation_ref` / `continuation_ref` / `continuation_id` / `provider_continuation` /
   `session_ref` / `session_id` / `session_token` / `thread_ref` / `thread_id` /
   `provider_request` / `provider_request_body` / `provider_response` / `raw_response` /
   `continuation`。hit key は再帰的に drop し、`content_redacted=true` /
   `redaction_reason="forbidden_keys_scrubbed"` を立てる。
4. 上記を満たした残りを `content` として返す (`public`/`internal` のみ、scrub 済)。

> projection は **API layer (response 構築)** で行い、`content_jsonb` raw は API 境界を越えない。

### repository read method

`ArtifactRepository.list_for_run(tenant_id: int, project_id: UUID, run_id: UUID) -> list[Artifact]`
(R1 F-HIGH-1: `project_id` を受け取り、active-scope を同一 statement で enforce):

```sql
select a.* from artifacts a
  join agent_runs r
    on a.tenant_id = r.tenant_id
   and a.project_id = r.project_id
   and a.run_id = r.id
 where a.tenant_id = :tenant_id
   and a.project_id = :project_id
   and a.run_id = :run_id
   and a.kind <> 'provider_continuation_ref'
   and not exists (
     select 1 from tickets dt
      where dt.tenant_id = r.tenant_id
        and dt.project_id = r.project_id
        and dt.id = r.ticket_id
        and dt.deleted_at is not null
   )
 order by a.created_at, a.id;
```

- tenant + project + run の複合境界 + soft-deleted ticket run 除外を **同一 statement** で enforce。
  `_ensure_tenant_context` 経由。`project_id` は step 1 で解決した run の project_id を渡す
  (run 不可視なら step 1 で 404、artifact query も join で fail-closed)。

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
| 可視性確認と artifact 取得の分離による active-scope TOCTOU (R1 F-HIGH-1) | `list_for_run` が `AgentRun` join + `tenant_id`/`project_id`/`run_id`/soft-delete 除外を同一 statement で enforce。SQL introspection test + soft-deleted run 404/empty negative |
| content_jsonb の非露出データ漏洩 (continuation/session/thread ref、confidential/pii 本文) (R1 F-HIGH-2) | API layer の display projection: kind 除外 + confidential/pii redaction + 再帰 key denylist scrub。fixture (継続 ref 風 key 混入 / confidential / pii) で negative test |
| `provider_continuation_ref` の UI 露出 (ContextSnapshot rule 違反) | repository query で kind 除外 + projection denylist の二重防御 + endpoint test で固定 |
| route 衝突 (`/{run_id}` と `/{run_id}/artifacts`) | route-order test (`/{run_id}/artifacts` → 200、run 詳細に飲み込まれない) |
| tenant/project 越境 | repository 複合境界 + run 可視性確認 (404)。seed-based negative は CI Compose |
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
  - route 登録 (`/{run_id}/artifacts`) + route-order (run 詳細 `/{run_id}` に飲み込まれない、`?` 等)。
  - **active-scope SQL introspection (R1 F-HIGH-1)**: `list_for_run` の生成 SQL が `agent_runs` join +
    `tenant_id` + `project_id` + `run_id` + `kind <> 'provider_continuation_ref'` +
    soft-delete 除外 (`tickets ... deleted_at is not null` の NOT EXISTS) を **同一 statement** に含む
    (compile SQL に全 predicate が出ることを assert)。
  - run 不存在 / tenant 外 / soft-deleted ticket run → **404** (capturing session で run 取得 None → 404)。
  - **display projection (R1 F-HIGH-2)** — fake rows を capturing session に返して response を検証:
    - `payload_data_class` ∈ {confidential, pii} の artifact → `content=null` / `content_redacted=true` /
      `redaction_reason="data_class_confidential_or_pii"`。
    - public/internal の content に denylist key (例 `continuation_id` / `session_token` / `provider_response`)
      を混入 → 再帰 scrub で除去 + `content_redacted=true` / `redaction_reason="forbidden_keys_scrubbed"`。
    - clean な public/internal content → そのまま返る (`content_redacted=false`)。
  - response schema が secret / raw provider field を持たない。`provider_continuation_ref` 除外を固定。
  - seed-based tenant/project 越境 + soft-delete negative は CI Compose postgres で検証 (host 不可を明記)。
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
