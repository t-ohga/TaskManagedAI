# Codex Usage Policy

TaskManagedAI ハーネスにおける Codex 利用方針。  
Claude 側の Codex skill 運用、Codex 自身の chain 禁止、3 連続失敗停止、採否判定、`workspace-write` 承認条件を定義する。

## 1. 基本方針

- Codex は実装支援・計画レビュー・敵対レビュー・救援に使う。
- Codex 出力は正本ではない。PRD / DD / rules / reference / Sprint Pack / ADR と照合する。
- Codex chain の並列起動は禁止。
- Codex 自身が実行主体のときは、さらに Codex を呼ぶ chain を作らない。
- Claude 固有の Skill / AskUserQuestion / hook 記法は Codex 側へそのまま移植しない。
- Codex mirror は `.codex/config.toml`, `.codex/hooks.json`, `.codex/agents/*.toml` の実行可能性を重視する。

## 2. 起動方針

| 経路 | 主用途 | 起動判断 |
|---|---|---|
| `codex-task` | bounded implementation / background 調査 | 5-60 分程度で独立できる作業 |
| `codex-second-opinion` | 汎用セカンドオピニオン | 判断が割れそうな設計・レビュー |
| `codex-plan-review` | Sprint Pack / ADR / 計画レビュー | high-risk 計画、広範囲変更 |
| `codex-adversarial-review` | 敵対レビュー | security / provider / runner / DB boundary |
| `codex-rescue` | 救援 | Claude 側が 2 回以上失敗、または詰まりが明確 |

## 3. Codex を使うべき領域

- DB schema、migration、tenant / project invariant。
- API 契約、OpenAPI、event schema。
- AgentRun 16 状態、state machine contract。
- Provider Compliance、`payload_data_class` / `allowed_data_class` 境界。
- SecretBroker、capability token、atomic claim。
- Runner sandbox、forbidden path、dangerous command。
- GitHub App permission、RepoProxy、Draft PR flow。
- Tailscale grants、network exposure。
- 広範囲 refactor、複数 module 横断変更。
- Sprint Pack / ADR の構造レビュー。

## 4. Codex が不要な領域

- 明確な typo / wording 修正。
- 1 ファイル内の低リスク docs 追記。
- 既存 pattern に沿う小さな UI 文言変更。
- ユーザーが Codex 利用を明示的に不要とした作業。
- Codex 自身が現在の作業主体で、同等観点を通常レビューで扱える場合。

## 5. 並列禁止

- Claude から複数 Codex chain を同時起動しない。
- 1 つの Codex 結果を採否判定してから次へ進む。
- 同じ scope に対する `codex-plan-review` round を重複起動しない。
- Codex failure guard が作動している間は再試行しない。
- Subagent からさらに Codex skill を呼ばせない。
- Codex 側 `.codex/agents` に Skill 再帰前提を残さない。

## 6. 失敗検知

| 検知 | 扱い |
|---|---|
| exit code != 0 | failure |
| timeout | failure |
| rate limit / quota / 429 | failure |
| unauthorized / 401 | failure |
| output schema invalid | logical failure |
| output empty / too small | logical failure |
| 同じ指摘の堂々巡り | logical failure |
| TaskManagedAI invariant 違反 | reject または retry |
| read-only sandbox で書込要求 | blocked として扱う |

## 7. 3 連続失敗停止

- Codex / external agent / reviewer 連携が 3 連続で失敗したら自動停止する。
- 停止時は次を整理してユーザー確認に戻る:
  - 失敗回数
  - 失敗種別
  - 影響範囲
  - 継続案
  - 停止案
  - 手作業 fallback
- 3 連続失敗後に同じ command / skill を再実行しない。
- rate limit の場合は時間を空けるか、Codex なしで通常レビューへ切り替える。
- failure counter を手動で無視しない。

## 8. 採否判定

| 判定 | 意味 | 必須処理 |
|---|---|---|
| `adopt` | 採用 | 参照 docs と実ファイルで確認して反映 |
| `reject` | 不採用 | 理由を残し、該当案を再利用しない |
| `defer` | 後回し | Sprint Pack の deferred / risk に残す |

## 9. 採用前 Checklist

- [ ] TaskManagedAI rules と矛盾しない。
- [ ] PRD / DD / Sprint Pack / ADR と整合する。
- [ ] `payload_data_class` / `allowed_data_class` の境界を壊していない。
- [ ] `tool_mutating_gateway_stub` / `runner_mutation_gateway` を混同していない。
- [ ] AgentRun 16 状態と ContextSnapshot 10 カラムを壊していない。
- [ ] SecretBroker atomic claim と raw secret 非保存を壊していない。
- [ ] tenant / project invariant を壊していない。
- [ ] 検証方法が実行可能。
- [ ] 既存ユーザー変更を上書きしない。

## 10. `workspace-write` 承認要件

`workspace-write` が有効でも、次は実装前に承認条件を明確にする。

- 認証・認可。
- DB schema / migration。
- API 契約 / event schema。
- AI エージェント権限。
- MCP / tool 権限。
- Secrets。
- 外部公開設定。
- 破壊的操作。
- 広範囲 refactor。
- Provider 追加 / 切替 / Matrix 引き上げ。
- GitHub App permission。
- 既存差分への上書き。
- `.codex/agents/*.toml` の生成・更新。

## 11. `.codex/agents/*.toml` 手動確認

- Claude-only field が残っていない。
- Claude-only tool 名が残っていない。
- `$CLAUDE_PROJECT_DIR` 前提がない。
- AskUserQuestion 前提がない。
- Skill 再帰起動前提がない。
- 存在しない path がない。
- shell command として hook が実行できる。
- `codex hooks` または実 hook で code 127 を起こさない。

## 12. Codex 出力の扱い

- patch はそのまま採用せず diff を読む。
- migration は DB invariant と rollback を確認する。
- test 追加は弱い assertion がないか見る。
- provider / secret / runner / repo write は high-risk として再確認する。
- 不明な外部仕様を断定していたら公式 docs に戻す。
- TaskManagedAI 用語が drift していたら reject する。
- ieshima 固有語や Supabase 前提が混ざっていたら reject する。


<!-- Phase E 圧縮 (2026-05-17 PR #?): 末尾 verify checklist 削除、plan §3.1.1 invariant trace matrix で自動 verify -->
