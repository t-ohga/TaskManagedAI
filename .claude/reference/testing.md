---
paths:
  - "backend/**"
  - "frontend/**"
  - "migrations/**"
  - "eval/**"
  - "**/tests/**"
  - "**/test_*.py"
  - "**/*.spec.ts"
  - "**/*.test.ts"
  - "package.json"
  - "pnpm-lock.yaml"
  - "pyproject.toml"
  - "uv.lock"
  - "Dockerfile*"
  - "docker-compose*.yml"
  - ".github/**"
  - "scripts/**"
  - "Makefile"
  - "*.config.*"
---

# Testing Rules

TaskManagedAI のテスト規律。  
Vitest、pytest、Playwright、contract test、state machine test、Eval fixture を仕様ベースで扱う。

## 1. 基本方針

- テストは実装詳細ではなく、観測できる振る舞いを検証する。
- 仕様は PRD-01、DD-02、DD-03、DD-04、DD-06、Sprint Pack、ADR から導出する。
- Hard Gates 7 件は全件 pass が P0 必須条件。
- Quality KPIs 5 件は計測可能でなければならない。
- AI 出力、Provider、SecretBroker、Runner、PostgreSQL boundary は negative test を必須にする。
- テストで見つけた bug は抑制せず、根本原因を直す。

## 2. テスト種類

| 種類 | 主対象 | 代表ツール |
|---|---|---|
| unit | pure function、validator、policy helper | Vitest / pytest |
| component | P0 UI の表示・操作 | Vitest + Testing Library |
| API contract | FastAPI request / response / OpenAPI | pytest / httpx |
| DB contract | tenant / project invariant、複合 FK | pytest / test DB |
| state machine | AgentRun 16 状態、blocked サブ 3 | pytest / Vitest |
| provider contract | ProviderAdapter、Structured Outputs、preflight | pytest |
| SecretBroker contract | capability token、atomic claim、one-time redeem | pytest |
| runner security | forbidden path、dangerous command | pytest / integration |
| E2E | Ticket -> Approval -> AgentRun -> mock PR | Playwright |
| Eval | Hard Gates / Quality KPIs | eval harness |

## 3. 弱い assertion 禁止

| パターン | 判定 | 代替 |
|---|---|---|
| `expect(screen.getByRole(...)).toBeDefined()` | 禁止 | `toBeInTheDocument()` |
| `expect(screen.getByText(...)).toBeDefined()` | 禁止 | `toBeVisible()` など |
| `expect(result).toBeTruthy()` | 原則禁止 | 具体的な値、状態、error code |
| snapshot だけ | 禁止 | 重要な文言、role、state、event を明示 |
| `expect(fn).not.toThrow()` だけ | 弱い | 戻り値、DB event、audit payload も確認 |
| `expect(status).toBe(200)` だけ | 弱い | response schema と副作用を確認 |
| `toContain("error")` だけ | 弱い | structured `error_code` を確認 |
| `as any` で fixture を通す | 禁止 | 最小 typed fixture / factory |

## 4. 仕様ベース設計手順

1. 関連する Sprint Pack と設計文書を読む。
2. 正常系、異常系、境界値、権限境界、retry / resume を列挙する。
3. 実装コードの branch / state / catch / validation path と照合する。
4. 仕様にあるが実装にない branch は実装漏れとして扱う。
5. 実装にあるが仕様にない branch は防御コードとしてテストする。
6. 各 branch に最低 1 つのテストを対応させる。
7. 状態機械は全状態と主要遷移を表にする。
8. テスト名は「期待する振る舞い」を書く。

## 5. Vitest

- UI は role / label / accessible name を優先して query する。
- P0 UI は Ticket 一覧、Ticket 詳細、Approval Inbox、Agent Runs、Audit Log、Project Settings、Eval Dashboard を対象にする。
- `payload_data_class` と `allowed_data_class` は表示上も混同しないことを確認する。
- Client Component は browser API や event handler を local に閉じる。
- Server Actions をテストする場合は schema validation と policy decision を検証する。
- UI の optimistic update は audit / event と矛盾しないことを確認する。

## 6. pytest

- FastAPI endpoint は request validation、response model、auth / actor context、error code を検証する。
- repository test は `tenant_id` 条件が抜けた場合に落ちる fixture を持つ。
- DB contract test は SELECT / INSERT / UPDATE / DELETE の越境 negative を含める。
- 同一 tenant・別 project の parent 参照も negative test に含める。
- provider test は provider 未送信の deny path を確認する。
- SecretBroker test は並行 redeem を再現し、atomic claim の one-time 保証を確認する。
- runner test は forbidden path と dangerous command を実際の gateway 境界で確認する。

## 7. AgentRun State Machine Contract

- status enum は次の 16 状態から逸脱しない:
  - `queued`
  - `gathering_context`
  - `running`
  - `generated_artifact`
  - `schema_validated`
  - `policy_linted`
  - `diff_ready`
  - `waiting_approval`
  - `blocked`
  - `provider_refused`
  - `provider_incomplete`
  - `validation_failed`
  - `repair_exhausted`
  - `completed`
  - `failed`
  - `cancelled`
- `blocked_reason` は `blocked` のときだけ必須。
- `blocked_reason` は `policy_blocked`, `budget_blocked`, `runtime_blocked` のみ。
- terminal state から別状態へ遷移しない。
- `provider_incomplete` は retry / resume 可。
- `provider_refused` は terminal。
- `validation_failed` は repair retry 上限後に `repair_exhausted`。
- status update と AgentRunEvent append は同一 transaction で確認する。

## 8. Provider Compliance Test

- `payload_data_class` 未設定は deny。
- Matrix にない provider / feature は deny。
- `allowed_data_class` を caller 入力で渡す設計は test で失敗させる。
- data class ordinal は `public < internal < confidential < pii`。
- `payload_data_class > allowed_data_class` は `blocked` + `policy_blocked`。
- `condition_status != verified` の conditional ZDR へ `confidential` 以上を送らない。
- `provider_request_preflight` が secret canary を provider call 前に止める。
- deny event の audit payload は raw secret を含まない。

## 9. SecretBroker Test

- `secret_ref` URI は `secret://<backend>/<scope>/<name>#<version>` (backend=`sops`|`local`、ADR-00058) を許可、未知 backend は fail-closed。
- raw secret を DB、log、artifact、AI prompt、runner env に保存しない。
- capability token TTL は 5-30 分。
- token 生値は DB に保存せず hash のみ。
- redeem は atomic claim UPDATE で 1 件だけ成功する。
- actor mismatch、run mismatch、request_fingerprint mismatch、operation mismatch は deny。
- 同一 token の二重 redeem は deny。
- operation 失敗後の retry は新 token を要求する。
- `secret_capability_issued` / `redeemed` / `denied` の audit event を確認する。

## 10. Eval Anti-Gaming

- fixture kind は `public_regression`, `private_holdout`, `adversarial_new` に分ける。
- `private_holdout` の期待値を見ながら policy / prompt を調整しない。
- monthly refresh は append-only。
- fixture 作成 commit と policy / prompt 修正 commit を分ける。
- fixture ID と dataset version を AgentRun / EvalRun / EvalResult に保存する。
- Hard Gate fixture は期待値の漏えいを避ける。
- `adversarial_new` は prompt injection、secret canary、dangerous command、forbidden path を強化する。

## 11. 実行コマンド目安

- Frontend unit: `pnpm test`
- Frontend coverage: `pnpm test -- --coverage`
- Frontend E2E: `pnpm test:e2e`
- Frontend lint: `cd frontend && pnpm exec eslint . --max-warnings=0`
- Backend unit / contract: `uv run pytest`
- Backend lint: `uv run ruff check backend tests`
- Backend type: `uv run mypy backend`
- DB migration check: `uv run alembic check`
- DB migration apply: `uv run alembic upgrade head`
- Full local smoke: `docker compose up --build`

## 12. Sprint 着手前 prerequisite

- main push / PR 作成前に CI Smoke と同等の local verification を実行する。
- dependency 追加時は lockfile を更新し、`uv sync --locked` または `pnpm install --frozen-lockfile` 相当で確認する。
- 新規 migration commit 前に `uv run alembic upgrade head` を local で実行し、fresh DB で全 migration apply が成功することを確認する。
- migration `revision` は **30 chars 以内** にする (Alembic default の `alembic_version.version_num` が `varchar(32)` のため、project convention として 30 chars を上限)。`migrations/env.py` の `assert_revision_ids_within_limit()` で fail-fast、hook `.claude/hooks/migration/check-revision-id-length.sh` で PreToolUse BLOCK。
- frontend 変更時は `cd frontend && pnpm exec eslint . --max-warnings=0` を local で実行する。
- backend 変更時は `uv run ruff check backend tests` と `uv run mypy backend` を local で実行する。
- 実行できない検証がある場合は、理由、代替確認、残リスクを Sprint Pack / 最終報告に明記する。

## 13. 完了条件

- [ ] 変更範囲に対応する unit / contract / E2E がある。
- [ ] 弱い assertion だけのテストがない。
- [ ] AgentRun 16 状態と ContextSnapshot 10 カラムを壊していない。
- [ ] Provider Compliance と SecretBroker の negative test がある。
- [ ] private / public / adversarial fixture が混ざっていない。
- [ ] CI Smoke と同等の local verification を main push / PR 前に実行している。
- [ ] 実行できなかった検証は最終報告に理由付きで残す。

