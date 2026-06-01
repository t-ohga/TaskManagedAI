---
id: "ADR-00042"
title: "AgentRun Artifact 読み取り専用 REST endpoint (L-2、metadata-only)"
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

# ADR-00042: AgentRun Artifact 読み取り専用 REST endpoint (L-2、metadata-only)

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
- `ArtifactRepository` に **read-by-run method は無い** → 追加が必要。

## 決定対象

run 詳細から artifact を読むための **read-only REST endpoint** と **repository read method** と
**frontend 配線** の契約。AI 権限の追加・mutation は一切含まない (read-only)。

## 設計判断: metadata-only (content body は返さない)

**本 ADR は artifact の `content_jsonb` (本文) を API 境界外に出さない。返すのは metadata
(`kind` / `payload_data_class` / `trust_level` / `exportable` / `parent_artifact_id` / `created_at`) のみ。**

### 根拠 (plan-review R1-R14、2026-06-01)

当初は content_jsonb を display projection (denylist scrub) で表示する設計だったが、codex-plan-review を
14 round 重ねた結果、**任意 content_jsonb を表示しつつ全漏洩経路を denylist で塞ぐのは構造的に fail-open** で
provably 安全にできないと判明した。具体的に塞ぎ切れなかった経路:

- SecretBroker `secret_ref` / `secret_ref_id` / `secret_uri` / `capability_token` (compound key
  `old_secret_ref_id`、camelCase `secretRefId`、hyphen `secret-ref-id`、JSON key 埋め込み、discriminator
  object `{"type":"secretRefId","value":...}` の兄弟 field)。
- provider continuation ref (`secret://` / `provider-continuation:` の URI、自由文埋め込み、shape)。
- PII (`payload_data_class` を信用するしかなく、misclassify した `internal` + `{"customer_email":...}` が露出)。
- raw secret (legacy / import / scanner gap)。

これらは ContextSnapshot UI 非露出 rule / SecretBroker secret_ref 非露出 (R-3 専用 viewer 経由のみ) /
PII 非拡散の不変条件に直結する。**content を返さなければこの漏洩面は構造的にゼロになる**ため、L-2 は
metadata-only に縮小する (user 決定 2026-06-01)。

「AI が何を生成したか」の可視化価値 (生成物の種別・信頼度・分類・系譜・件数) は metadata で達成できる。
**content drill-down は P0.1 に defer** (専用 sanitizer / server-owned `display_safe` provenance を持つ
artifact だけ本文表示を許可する設計が前提。ADR-00042 の scope 外)。

## 前提 / 制約

- P0 個人専用・単一 tenant。ただし tenant / project boundary は schema・repository contract で維持。
- AI 出力直結禁止: 本 endpoint は **read-only**。artifact の生成・昇格・実行は対象外。
- **content_jsonb / content_hash は返さない**。content_hash も SHA-256 hash oracle (低エントロピー PII /
  既知 secret_ref の offline guess) になるため metadata から除外する。artifact 識別は opaque `id`。
- `provider_continuation_ref` kind は内部 continuation 参照 (ContextSnapshot UI 非露出 rule) のため、
  metadata であっても **L-2 表示から除外** する (repository query で除外)。
- `payload_data_class` / `trust_level` は分類 metadata として表示する (caller 入力なし、artifact row 由来)。
- active-scope: soft-deleted ticket に紐づく run は既存 run 詳細経路と同じ可視性に従う。

## 選択肢

### 案 A (採用): 専用 read-only endpoint `GET /agent_runs/{run_id}/artifacts` (metadata-only)

- `GET /api/v1/agent_runs/{run_id}/artifacts` を追加。run 可視性確認 + artifact metadata 一覧を返す。
- repository に `list_run_artifacts(tenant_id, run_id)` を追加 (metadata column のみ select、content_jsonb /
  content_hash は fetch しない、`provider_continuation_ref` 除外、active-scope)。
- frontend: lib client + run 詳細に artifact インベントリ section。

### 案 B (却下): content_jsonb を denylist scrub で表示

- 却下理由: plan-review R1-R14 で fail-open と判明 (上記「設計判断」根拠)。P0.1 で専用 sanitizer 前提に再検討。

### 案 C (却下): run 詳細 `GET /{run_id}` の response に inline 埋め込み

- 却下理由: 既存 `AgentRunDetailResponse` 契約を破壊的拡張 + payload 肥大化 + pagination 余地なし。
  独立 read-only endpoint の方が契約が clean。

### 案 D (却下): MCP のみ

- 却下理由: UI (Next.js Server Component) は内部 REST API 経由でデータ取得する設計 (ticket / run /
  cost_summary 等と同じ)。UI からの read は REST endpoint が正本経路。

## 採用案 (案 A) 詳細契約

### endpoint

`GET /api/v1/agent_runs/{run_id}/artifacts`

- deps: `get_current_actor_id` / `get_tenant_id` / `get_db_session` (既存 run endpoint と同一)。
- route ordering: `/{run_id}/artifacts` は `/{run_id}` より具体的なため衝突しない。静的 route
  (`/cost_summary` 等) と同じ block 近傍に定義し、`/{run_id}` より前に置く (route-order test)。
- 手順: **run 可視性 + artifact 取得を単一 statement** で行う。`agent_runs` 起点の active-scope SELECT に
  `LEFT JOIN artifacts` し、結果を解釈する:
  - **0 rows** (run 行が無い = 不存在 / tenant 外 / soft-deleted ticket bound) → **404**。
  - **run 行あり + artifact null** → run visible・artifact 0 件 → **200 empty**。
  - **run 行あり + artifact** → **200** list。
- response (`RunArtifactListResponse`): `{ "artifacts": [RunArtifact, ...] }`。
  - `RunArtifact` (metadata-only): `id` (opaque UUID) / `kind` (str) / `payload_data_class` (str) /
    `trust_level` (str) / `exportable` (bool) / `parent_artifact_id` (UUID|null) / `created_at` (datetime)。
  - **`content` / `content_jsonb` / `content_hash` は schema に含めない** (content body / hash を一切返さない)。

### repository read method (run-visible sentinel + active-scope 単一 statement、content 非 fetch)

`ArtifactRepository.list_run_artifacts(tenant_id: int, run_id: UUID) -> RunArtifactRows | None`
(`agent_runs` 起点。`None` = run 不可視 → 404、`RunArtifactRows` (空 list 可) = visible):

```sql
select r.id as run_id,
       a.id as artifact_id, a.kind,
       a.payload_data_class, a.trust_level, a.exportable, a.created_at,
       -- parent_artifact_id は parent が「可視 artifact」(= provider_continuation_ref でない) のときだけ返す。
       -- 除外済 provider_continuation_ref を親に持つ child から、その UUID / lineage を漏らさない (R15 F-HIGH)。
       case when pa.id is not null then a.parent_artifact_id else null end as parent_artifact_id
  from agent_runs r
  left join artifacts a
    on a.tenant_id = r.tenant_id
   and a.project_id = r.project_id
   and a.run_id = r.id
   and a.kind <> 'provider_continuation_ref'
  left join artifacts pa
    on pa.tenant_id = a.tenant_id
   and pa.project_id = a.project_id
   and pa.run_id = a.run_id
   and pa.id = a.parent_artifact_id
   and pa.kind <> 'provider_continuation_ref'   -- 親も可視種別のときだけ join 成立
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

- **content_jsonb / content_hash は SELECT しない** (metadata column のみ)。本文を DB から API layer へも
  運ばないことで漏洩面を構造的にゼロにする。
- **parent edge 可視性 (R15 F-HIGH)**: `parent_artifact_id` は parent を self-join (`pa`) し、parent が
  `provider_continuation_ref` でない (= inventory に出る可視 artifact) ときだけ返す。親が除外済
  provider_continuation_ref / 不存在なら `parent_artifact_id=null` (除外 artifact の UUID / lineage を
  child 経由で漏らさない)。
- **run 起点の inner 条件** (`r.tenant_id` + `r.id` + soft-delete NOT EXISTS) が run 可視性を決め、
  `LEFT JOIN artifacts` が artifact を集める。0 rows → run 不可視 → 404。run 行 + artifact null →
  200 empty。**404/200-empty の区別と active-scope を同一 statement** で閉じる (TOCTOU / 将来再利用でも
  fail-closed)。`project_id` は run 行から導出 (caller 入力不要)。`_ensure_tenant_context` 経由。
- runs に ticket_id が無い (null) 場合は NOT EXISTS が真 = visible (既存 active-scope helper と同義)。
- `provider_continuation_ref` 除外で ContextSnapshot 内部 ref を inventory にも出さない。

### frontend

- `lib/api/agent-runs.ts` (or 専用 module): `fetchRunArtifacts(runId)` + Zod schema (strict、content/
  content_hash field は **存在しない**)。
- run 詳細 (`app/(admin)/runs/[id]/`) に「生成物 (Artifact)」インベントリ section。
  - 各 artifact card: kind / trust_level / payload_data_class バッジ + parent 系譜 + created_at。
    **content body / hash は表示しない** (metadata-only。content drill-down は P0.1)。
  - 0 件は空状態文言、取得失敗は section 単位で degrade (run 詳細全体は落とさない)。
  - secret / secret_ref / provider response / continuation ref / content body / hash は DOM に出さない
    (API がそもそも返さない)。

## リスク

| リスク | 対策 |
|---|---|
| active-scope TOCTOU + 404/200-empty 判別不可 | `agent_runs` 起点 LEFT JOIN artifacts の単一 statement で run 可視性 (soft-delete 除外) と artifact 集約を同時に行い、0 rows→404 / run 行+artifact null→200-empty。SQL introspection + 404/empty negative test |
| content_jsonb 経由の SecretBroker ref / continuation ref / PII / raw secret 露出 | **content / content_hash を返さない** ことで漏洩面を構造的にゼロ化 (denylist scrub の fail-open を回避。content drill-down は P0.1 defer) |
| `provider_continuation_ref` の inventory 露出 (ContextSnapshot rule 違反) | repository query で kind 除外 + schema に該当 metadata を出さない |
| 除外済 provider_continuation_ref の `parent_artifact_id` 経由 lineage 露出 (R15 F-HIGH) | parent を self-join し parent.kind が可視種別のときだけ `parent_artifact_id` を返す (provider_continuation_ref 親は null)。child の親が provider_continuation_ref の場合に parent_artifact_id=null の negative test を must-ship |
| route 衝突 (`/{run_id}` と `/{run_id}/artifacts`) | route-order test |
| tenant/project 越境 | run 起点 query の複合境界。seed-based negative は CI Compose |
| inventory の肥大化 | P0 は単一 run の metadata 一覧で実用上問題なし。pagination は独立 endpoint で将来拡張余地 |

## rollback 手順

- 純粋な追加 (新 endpoint + repository read method + frontend section)。migration なし。
- rollback: 追加した endpoint / repository method / frontend section を revert するのみ。既存契約・
  schema・データに影響なし。

## 実装対象ファイル

- `backend/app/repositories/artifact.py`: `list_run_artifacts` read method 追加 (metadata column のみ)。
- `backend/app/api/agent_runs.py`: `GET /{run_id}/artifacts` endpoint + `RunArtifact` /
  `RunArtifactListResponse` Pydantic schema (content/content_hash なし)。
- `frontend/lib/api/agent-runs.ts` (or 新 module): `fetchRunArtifacts` + Zod schema (content/hash なし)。
- `frontend/app/(admin)/runs/[id]/`: artifact インベントリ section component + 配線。
- test: **`tests/api/test_run_artifacts.py` (新)** — repo の pytest は `testpaths=["tests"]` で collect する
  ため **`tests/api/`** 配下に置く (`backend/tests/` は collection 外)。frontend test は
  `frontend/__tests__/run-artifacts.test.tsx`。
- 検証コマンド: `cd backend && uv run pytest ../tests/api/test_run_artifacts.py -q` /
  `cd backend && uv run ruff check ../tests/api/test_run_artifacts.py app/api/agent_runs.py app/repositories/artifact.py` /
  `cd backend && uv run mypy app/api/agent_runs.py app/repositories/artifact.py` /
  `cd frontend && pnpm exec vitest run __tests__/run-artifacts.test.tsx` / `pnpm typecheck`。

## テスト指針

- backend (host は conftest test-password 不一致で seed-based DB 不可 → **SQL introspection + capturing
  session に fake rows** pattern を踏襲、ADR-00039/00040/00041 と同経路):
  - route 登録 (`/{run_id}/artifacts`) + route-order (run 詳細 `/{run_id}` に飲み込まれない)。
  - **active-scope + sentinel SQL introspection**: `list_run_artifacts` の生成 SQL が `agent_runs` 起点 +
    `left join artifacts` + `tenant_id` + `run_id` + `kind <> 'provider_continuation_ref'` + soft-delete 除外
    (`tickets ... deleted_at is not null` の NOT EXISTS) を **同一 statement** に含み、**`content_jsonb` /
    `content_hash` を SELECT しない** (compile SQL に content/hash column が出ないことを assert)。
  - **404 vs 200-empty** — fake rows を capturing session に返して区別を検証: run 0 rows → 404、
    run 行 + artifact null → 200 empty list、run 行 + artifact → 200 list。
  - **metadata-only schema (must-ship)**: `RunArtifact` の field が
    `{id, kind, payload_data_class, trust_level, exportable, parent_artifact_id, created_at}` のみで、
    `content` / `content_jsonb` / `content_hash` を **持たない** (OpenAPI schema / model_fields で assert)。
  - response mapping: fake rows (各 kind / trust_level / data_class) → metadata が正しく写像される。
    `provider_continuation_ref` を含む fake rows でも query 除外により返らない (introspection で固定)。
  - **parent edge 可視性 (R15 F-HIGH、must-ship)**: SQL に parent self-join (`pa`) +
    `pa.kind <> 'provider_continuation_ref'` + `case when pa.id is not null ... else null` が含まれること
    (introspection)。fake rows で「親が provider_continuation_ref の child」→ `parent_artifact_id=null`、
    「親が可視 artifact の child」→ `parent_artifact_id` 非 null を検証。
  - seed-based tenant/project 越境 + soft-delete negative は CI Compose postgres で検証 (host 不可)。
- frontend: `fetchRunArtifacts` の Zod strict (content/content_hash field を持たない) + run 詳細 artifact
  インベントリ section の表示 / 空状態 / degrade。
  - **content/hash 非露出 (must-ship)**: artifact card の DOM に content body / hash 文字列 / digest らしき
    hex 値が **描画されない** ことを assert。

## 不変条件 trace

- AI 出力直結禁止: read-only、mutation/昇格/実行なし。
- secret / 非露出データ非拡散: **content_jsonb / content_hash を API 境界外に一切出さない** ことで、
  SecretBroker secret_ref / continuation ref / PII / raw secret の漏洩面を構造的にゼロ化。ContextSnapshot
  UI 非露出 rule・SecretBroker 非露出・PII 非拡散を artifact 経路でも維持。
- tenant / project boundary: repository が `AgentRun` join で複合境界 + active-scope を同一 statement で enforce。
- active-scope: soft-deleted ticket run は 404、artifact query 単体でも fail-closed。
- `payload_data_class` / `trust_level` は artifact row 由来を表示、caller 入力なし。
- AgentRun 16 状態 / Provider Compliance / SecretBroker に変更なし。migration なし (read のみ)。
- content drill-down は P0.1 defer (専用 sanitizer / `display_safe` provenance 前提)。
