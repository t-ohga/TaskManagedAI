---
paths:
  - "**/*.py"
  - "**/*.ts"
  - "**/*.tsx"
  - "**/*.js"
  - "**/*.jsx"
  - "**/*.go"
  - "**/*.rs"
  - "**/*.sh"
  - "**/*.md"
  - "**/*.json"
  - "**/*.yml"
  - "**/*.yaml"
  - "**/*.toml"
  - "Dockerfile*"
  - "Makefile"
---

# Code Search Rules

調査・実装・レビュー時の検索ルール。  
LSP を優先し、未対応・テキスト検索・ファイル名検索では `rg` / `rg --files` を使い、最後は実コンパイラで確認する。

## 1. 優先順位

| 目的 | 優先ツール |
|---|---|
| 定義元 | LSP go-to-definition -> `rg` |
| 参照箇所 | LSP find-references -> `rg` |
| 型情報 | LSP hover / compiler |
| symbol 一覧 | LSP document symbols |
| workspace symbol | LSP workspace symbol -> `rg` |
| 実装箇所 | LSP implementation -> `rg` |
| テキスト pattern | `rg` |
| ファイル名 | `rg --files` |
| JSON key | `jq` |
| YAML / TOML | parser / structured query を優先 |

## 2. 基本原則

- 最初に関連 docs を読む。
- 実装を見る前に、PRD / DD / Sprint Pack / ADR の正本を確認する。
- LSP の結果が怪しい場合は `rg` と compiler で確認する。
- 大きいファイルを丸読みしない。見出し、symbol、必要範囲を絞る。
- JSON は `jq` で必要 key を抽出する。
- YAML / TOML は schema / parser を優先する。
- 行番号付きの主張は、その行を直接確認してから書く。
- 外部 agent の報告は実ファイルで検証する。

## 3. TaskManagedAI の正本優先順

| 用途 | 参照先 |
|---|---|
| P0 scope / Hard Gates / KPIs | `docs/要件定義/01_P0要求定義.md` |
| tenant / project / DB invariant | `docs/基本設計/02_データモデル.md` |
| AgentRun / ContextSnapshot | `docs/基本設計/03_AIオーケストレーション設計.md` |
| Provider / Security / Audit | `docs/基本設計/04_セキュリティ_権限_監査設計.md` |
| SecretBroker | `docs/基本設計/06_秘密管理設計.md` |
| Sprint Pack | `docs/sprints/*.md` |
| ADR | `docs/adr/*.md` |
| Harness mapping | `docs/設計検討/harness-phase0-mapping.md` |
| Codex guide | `AGENTS.md` |
| Claude guide | `.claude/CLAUDE.md` |

## 4. よく使う検索 pattern

```sh
rg -n "payload_data_class|allowed_data_class|ProviderAdapter|provider_request_preflight" .
rg -n "tool_mutating_gateway_stub|runner_mutation_gateway" .
rg -n "secret_ref|SecretBroker|secret_capability_tokens|atomic claim" .
rg -n "queued|gathering_context|provider_incomplete|repair_exhausted" .
rg -n "ContextSnapshot|prompt_pack_version|provider_request_fingerprint" .
rg -n "tenant_id|project_id|foreign key|unique \\(tenant_id" .
rg -n "AC-HARD|AC-KPI|private_holdout|adversarial_new" docs eval
```

## 5. LSP キャッシュ不整合

| 発生条件 | 対応 |
|---|---|
| `tsconfig` 変更 | `pnpm typecheck` |
| package update | `pnpm install` 後に `pnpm typecheck` |
| generated types 変更 | generator 実行後に typecheck |
| Python dependency 変更 | `uv sync` 後に `uv run mypy backend` |
| migration 変更 | `uv run alembic check` と DB contract test |
| 大規模 rename | LSP references と `rg` を併用 |
| stale diagnostics | 実 compiler / test を地上真実にする |

## 6. 実コンパイラ確認

| 領域 | コマンド |
|---|---|
| TypeScript | `pnpm typecheck` |
| Frontend lint | `pnpm lint` |
| Frontend test | `pnpm test` |
| E2E | `pnpm test:e2e` |
| Python lint | `uv run ruff check backend tests` |
| Python type | `uv run mypy backend` |
| Python test | `uv run pytest` |
| Alembic | `uv run alembic check` |
| Docker smoke | `docker compose up --build` |

## 7. 調査フロー

1. 変更対象に対応する docs を読む。
2. Sprint Pack / ADR の有無を確認する。
3. LSP で定義と参照を確認する。
4. `rg` で text / tests / docs / config を横断確認する。
5. 関連 test を読む。
6. 実装候補の最小変更範囲を決める。
7. 変更後に compiler / test で確認する。
8. まだ不明な場合は、確認事項と選択肢をユーザーへ出す。

## 8. 分析結果の検証

- 「未使用」と言う前に `rg` と LSP references を見る。
- 「未テスト」と言う前に `tests/`, `eval/`, `frontend/**/__tests__`, `backend/tests` を見る。
- 「DB 制約あり」と言う前に migration / model / test を見る。
- 「provider に送信されない」と言う前に ProviderAdapter path と preflight test を見る。
- 「secret は漏れない」と言う前に SecretBroker、redaction、audit payload、canary test を見る。
- 「状態遷移が正しい」と言う前に AgentRun status enum と transition test を見る。
- 「project boundary がある」と言う前に `(tenant_id, project_id, id)` の複合 FK を見る。

## 9. 禁止する調査

- LLM の記憶だけで Next.js / FastAPI / provider API の仕様を断定する。
- docs を読まずに既存実装だけから設計意図を推測する。
- `grep -R` など遅い検索を最初に使う。
- 巨大 JSON / lockfile を丸読みする。
- 外部 agent の要約を検証なしに採用する。
- 行番号を確認せずにレビュー finding を出す。
- `allowed_data_class` を caller 入力として扱う code path を見逃す。
- `tool_mutating_gateway_stub` と `runner_mutation_gateway` を同じものとして検索する。

## 10. 完了条件

- [ ] 関連 docs を確認した。
- [ ] LSP または `rg` で定義・参照を確認した。
- [ ] test / compiler / migration check の地上真実を確認した。
- [ ] 不確実な外部仕様は日付付きで公式情報を確認した。
- [ ] 変更が高リスクなら Sprint Pack / ADR Gate に戻した。

