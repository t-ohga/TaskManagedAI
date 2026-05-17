# Core Rules

TaskManagedAI の実装・レビューで常時守る基本制約。  
型安全、AI 出力境界、Provider Compliance、SecretBroker、PostgreSQL / FastAPI 境界を fail-closed で扱う。

## 1. 適用範囲

- 対象は TaskManagedAI P0 の `backend/`, `frontend/`, `config/`, `migrations/`, `eval/`, `docs/`, `.claude/`, `.codex/`。
- 正本は PRD-01、DD-02、DD-03、DD-04、DD-06、Sprint Pack、ADR。
- 高リスク変更は実装前に Sprint Pack と ADR Gate Criteria を確認する。
- AI / Codex / Claude / 外部 agent の出力は採用前に `adopt` / `reject` / `defer` で判定する。

## 2. 型安全

| 領域 | 必須ルール |
|---|---|
| TypeScript | `strict` 前提。`any`、暗黙 `any`、過剰な型 assertion を避ける |
| React / Next.js | Server Component / Client Component の境界を型で分ける |
| API client | OpenAPI または schema から型を生成し、手書き DTO drift を避ける |
| Python | すべての public function / method に type hints を付ける |
| FastAPI | request / response は Pydantic model で検証する |
| DB access | SQLAlchemy / repository 層で型と tenant context を維持する |
| config | TOML / YAML / JSON は schema validation を通す |

## 3. TypeScript / Frontend

- `tsconfig` は strict 系 option を落とさない。
- `unknown` を受けたら Zod / typed guard / discriminated union で絞り込む。
- `as any` は禁止。やむを得ない場合は Sprint Pack の残リスクに理由を書く。
- `payload_data_class` は UI から自由入力させず、Input Trust Layer / artifact metadata から算出された値を表示する。
- `allowed_data_class` は UI / caller から受け取らない。Provider Compliance Matrix からのみ解決する。
- Server Actions を使う場合も、AI 出力を直接 mutation に接続しない。
- UI は policy decision / approval / AgentRunEvent を表示しても、secret 値を表示しない。

## 4. Python / Backend

- `ruff`、`mypy`、`pytest` を品質確認の地上真実にする。
- Pydantic model は API boundary と provider structured output boundary の両方で使う。
- FastAPI dependency は `tenant_id`、`actor_id`、`principal_id` を明示的に解決する。
- service 層は raw request dict に依存せず、validated model を受け取る。
- repository 層は必ず `tenant_id` を条件に含める。
- exception は握りつぶさず、`error_code` と `error_summary` を AgentRun / audit に残す。
- provider / runner / repo / secret 操作は timeout と cancellation 境界を持つ。

## 5. AI 出力境界

- AI 出力を shell command として直接実行しない。
- AI 出力 SQL を DB に直接適用しない。
- AI 出力 workflow を `.github/workflows/**` に直接書き込まない。
- AI 出力 tool call を `tool_mutating_gateway_stub` を経由せず実行しない。
- AI 出力 patch を `runner_mutation_gateway` を経由せず適用しない。
- AI 出力から `secret_ref` を直接 resolve しない。
- 必ず `artifact -> schema_validated -> policy_linted -> diff_ready -> approval_required -> waiting_approval` の段階を通す。
- `approval_required` は pipeline stage であり、AgentRun status では `waiting_approval` に対応する。

## 6. Deny By Default (= deny-by-default)

**deny-by-default** = 明示許可がなければ拒否。Tailscale / Tool / Repo / Secret / merge / deploy / backup_restore_rpo_rto (Hard Gate AC-HARD-04 / RPO ≤ 24h / RTO ≤ 4h / PITR drill) すべてに適用。

| 境界 | P0 default |
|---|---|
| network | Tailscale 閉域のみ。Funnel / public bind は deny |
| tool | local / stdio / read-only search・fetch 中心 |
| external mutating tool | `tool_mutating_gateway_stub` で deny-only |
| runner mutation | `runner_mutation_gateway` 通過後のみ |
| repo write | approval 必須 |
| merge | P0 deny |
| deploy | P0 deny |
| secret access | SecretBroker mediated operation のみ |
| provider call | Provider Compliance Matrix 通過後のみ |

## 7. Provider Compliance

- Provider call は `ProviderAdapter.execute()` の入口で enforcement する。
- request は `payload_data_class` を必須で持つ。
- `payload_data_class` 未設定は即 deny。
- `allowed_data_class` は `config/provider_compliance.toml` からのみ解決する。
- caller が `allowed_data_class` を渡す設計は禁止。
- data class ordinal は `public < internal < confidential < pii` に固定する。
- ordinal 実装は `{public:0, internal:1, confidential:2, pii:3}` とする。
- `payload_data_class > allowed_data_class` は provider へ送信せず `blocked` + `policy_blocked`。
- conditional ZDR は `condition_status=verified` でなければ `confidential` 以上を許可しない。
- `provider_request_preflight` は provider call 前に必須実行する。
- preflight は secret canary、token pattern、raw secret、`secret_ref` 展開違反を raw 値なしで検出する。

## 8. PostgreSQL Invariant

- 全主要テーブルは `tenant_id bigint NOT NULL DEFAULT 1` を持つ。
- 親子参照は `tenant_id` を含む複合 FK で閉じる。
- 同一 tenant 内でも project 境界をまたぐ参照を禁止する。
- tickets / research_tasks / agent_runs / repositories は `(tenant_id, project_id, id)` の複合 unique / FK を使う。
- actor / principal は分離する。
- `actors.actor_type` は `human`, `service`, `agent`, `provider`, `github_app` を扱う。
- AgentRunEvent、AuditEvent、PolicyDecision は append-only event を正本にする。
- P0 では RLS を有効化しないが、RLS-ready metadata と app repository contract test を維持する。

## 9. AgentRun / ContextSnapshot

- AgentRun status は 16 状態に固定する。
- `blocked` は単一 status であり、`blocked_reason` は `policy_blocked`, `budget_blocked`, `runtime_blocked` の 3 種。
- terminal state は `completed`, `failed`, `cancelled`, `provider_refused`, `repair_exhausted`。
- `blocked` と `provider_incomplete` は terminal ではない。
- ContextSnapshot 必須 10 カラムを欠かさない:
  - `prompt_pack_version`
  - `prompt_pack_lock`
  - `policy_version`
  - `policy_pack_lock`
  - `repo_state`
  - `tool_manifest`
  - `evidence_set_hash`
  - `provider_continuation_ref`
  - `provider_request_fingerprint`
  - `snapshot_kind`
- secret 値や provider key を ContextSnapshot に含めない。

## 10. SecretBroker Boundary

- DB に raw secret を保存しない。
- DB には `secret_ref` URI と metadata のみ保存する。
- `secret_ref` 形式は `secret://sops/<scope>/<name>#<version>`。
- AI、runner、artifact export に secret 値を渡さない。
- SecretBroker は secret 値を返す API ではなく、operation を broker-mediated に実行する境界。
- capability token は TTL 5-30 分、one-time redeem、hash 保存のみ。
- redeem は atomic claim UPDATE で actor / run / request_fingerprint / operation を同一文で binding する。
- check -> execute -> mark used の逐次 redeem は禁止。

## 11. FastAPI Boundary

- request body は Pydantic で検証する。
- response model を明示し、secret / internal error / provider raw response を漏らさない。
- mutation endpoint は actor / principal / tenant context を必須にする。
- API 契約変更は ADR Gate Criteria に該当する。
- OpenAPI drift は CI で検出する。
- DB transaction の境界を service 層で明示する。
- AgentRun status update と AgentRunEvent append は同一 transaction で整合させる。
- Audit event は raw secret なしで append-only にする。

## 12. 実装前チェック

- [ ] Sprint Pack が存在する。
- [ ] ADR Gate Criteria 11 種に該当しない、または ADR がある。
- [ ] `payload_data_class` / `allowed_data_class` の信頼境界が分離されている。
- [ ] `tool_mutating_gateway_stub` と `runner_mutation_gateway` を混同していない。
- [ ] AgentRun 16 状態と ContextSnapshot 10 カラムを壊していない。
- [ ] SecretBroker atomic claim と raw secret 非保存を壊していない。
- [ ] tenant / project invariant を DB と repository test で確認できる。
- [ ] rollback、audit、verification が計画に書かれている。

