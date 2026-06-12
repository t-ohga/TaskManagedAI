---
paths:
  - "backend/**"
  - "frontend/**"
  - "**/*.py"
  - "**/*.ts"
  - "**/*.tsx"
  - "**/*.sh"
---

# Code Search (L1 reminder)

> **圧縮 2026-05-31**: 本 rule は L1 reminder。詳細 (LSP 優先順位表 / 正本優先順 / 検索 pattern 集 / LSP キャッシュ不整合 / 実コンパイラ確認 / 8 step 調査フロー / 分析結果の検証 / 禁止する調査 / 完了条件) は **`.claude/reference/code-search.md`** に full 退避済。必要時に Read する。

## 絶対遵守 (最小)

- シンボル検索 (定義 / 参照 / 型 / symbol 一覧 / 実装) は **LSP 優先 → `rg` → 実コンパイラで最終確認**。
- text pattern = `rg` / ファイル名 = `rg --files` / JSON key = `jq` / YAML・TOML = parser。`grep -R` を最初に使わない。巨大 file / lockfile を丸読みしない。
- 実装を見る前に PRD / DD / Sprint Pack / ADR の正本を読む (正本優先順位表は reference §3)。
- 行番号付き finding は **その行を直接確認してから** 書く。外部 agent の報告は実ファイルで検証する。
- 断定の前に実体を見る: 「未使用」→ LSP refs + `rg` / 「未テスト」→ tests・eval / 「DB 制約あり」→ migration・model / 「provider 送信されない」→ ProviderAdapter・preflight / 「secret 漏れない」→ SecretBroker・redaction・canary / 「状態遷移正しい」→ AgentRun enum・transition test / 「project boundary」→ `(tenant_id, project_id, id)` 複合 FK。
- LLM 記憶だけで Next.js / FastAPI / provider API 仕様を断定しない。`allowed_data_class` の caller 入力経路、`tool_mutating_gateway_stub` と `runner_mutation_gateway` の混同を見逃さない。

実コンパイラ確認コマンド・検索 pattern 一式・調査フロー詳細は `.claude/reference/code-search.md` を Read。
