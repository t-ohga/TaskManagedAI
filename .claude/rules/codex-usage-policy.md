# Codex Usage Policy

> **2026-05-27 Codex プラグイン移行**: Codex 呼び出しは公式プラグイン (`codex@openai-codex`) に移行。
> - `/codex:review` — コードレビュー (working tree / branch diff)
> - `/codex:adversarial-review` — 敵対レビュー (focus text 指定可能)
> - `/codex:rescue` — タスク委譲 (調査・修正・バックグラウンド)
> - `/codex:status` / `/codex:result` / `/codex:cancel` — ジョブ管理
> 旧 `codex exec` + `launch-codex.sh` は互換として残すが、新規利用は非推奨。


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



## 14. Mandatory Codex review gates (Codex F-PR44-001 + F-PR44-002 fix、必須経路)

以下のいずれかに該当する変更は **Codex review (最低 R1) 経路必須**。Claude 単独 commit 禁止 (CLAUDE.md §6.5.0 の Codex-first ポリシー恒久化、PR #42 Phase A 圧縮で消失リスク指摘の正本化):

### 14.1 mandatory Codex pre-commit gates

| trigger | 必須 review pass |
|---|---|
| **CRITICAL invariant 直結変更** (AgentRun 16 状態 / ContextSnapshot 10 列 / Provider Compliance 13 reason_code / SecretBroker raw secret 非保存 / Tenant boundary / actor / principal / approval 4 整合 / runner_mutation_gateway / tool_mutating_gateway_stub / PostgreSQL CHECK / 複合 FK) | minimum codex-adversarial-review R1 + 採否判定 |
| **3 file 横断以上の変更** | minimum codex-review-loop R1 + 採否判定 |
| **migration (Alembic) 追加・変更** | minimum codex-adversarial-review R1 + plan-reviewer agent 確認 |
| **新 ADR proposed → accepted 昇格** | minimum codex-plan-review R1 + 採否判定 (§sprint-pack-adr-gate.md §12 ADR accepted promotion と連動) |
| **Sprint Exit (Sprint Pack `## Review` 書き出し)** | minimum codex-review-loop R1 + release-suite skill 通過 |
| **Codex 委譲した実装の write back** | minimum 1 round adversarial review + clean (CRITICAL=0 + HIGH≤2) |

### 14.2 Claude 単独 commit が許される条件 (上記 14.1 のいずれにも該当しない場合のみ)

- 1-2 file / 30 行未満 の微修正
- typo / コメント / wording / frontmatter ledger 更新 / test fixture の expected 値追従
- 既存 pattern に沿った定型作業 (import 追加 / type ignore コメント / retry expected count 修正)
- 全条件で `uv run mypy backend` + `uv run ruff check backend tests` + 該当 `pytest` PASS が前提

### 14.3 Codex-first 実装経路 (Sprint batch 実装)

新 feature / Sprint batch 実装は **Codex `codex-task` skill 経由が第一選択** (CLAUDE.md §6.5.1 役割分担恒久化):
- Claude が batch 分割 (5-10 file / 1500-3000 行 per batch) + Codex prompt 作成
- Codex `codex-task` で background 実装 (read-only sandbox、Claude が write back)
- Claude が `adopt` / `reject` / `defer` 判定 → adopted のみ Edit/Write で反映
- Phase D (本 plan stage 2) 完了後の skill `branch-pr-workflow` invoke も含む

Claude 直接 fix が許されるのは:
- 1-2 file / 30 行未満の typo / lint fix
- 既存 pattern 適用の定型作業
- Codex 3 連続失敗 (AskUserQuestion で「Claude 単独続行」選択時)
- user が明示的に「Claude で実装」と指示した場合
- worktree setup / git operation / 環境変数読込


<!-- Phase E-2 圧縮 + PR #52 F-PR52-001 fix: 旧 §13 完了条件 checklist は削除済 (plan §3.1.1 trace matrix で代替)、§14 (Codex F-PR44-001/002 fix で追加した Mandatory Codex review gates) は本 PR で復元 -->
