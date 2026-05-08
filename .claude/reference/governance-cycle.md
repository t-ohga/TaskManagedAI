# Governance Cycle

TaskManagedAI ハーネスの catalog sync、四半期レビュー、deprecate 規約。  
rules / reference / agents / hooks / skills / Codex mirror の drift を抑えるための運用メモ。

## 1. 対象

| 対象 | パス |
|---|---|
| Claude project guide | `.claude/CLAUDE.md` |
| Codex project guide | `AGENTS.md` |
| rules | `.claude/rules/*.md` |
| reference | `.claude/reference/*.md` |
| agents | `.claude/agents/*.md` |
| codex agents | `.codex/agents/*.toml` |
| hooks | `.claude/hooks/**/*.sh` |
| codex hooks | `.codex/hooks.json` |
| skills | `.claude/skills/**/SKILL.md` |
| docs | `docs/**` |
| eval | `eval/**` |
| config | `config/provider_compliance.toml` |

## 2. Sync Cadence

| cadence | 作業 |
|---|---|
| Sprint 開始時 | Sprint Pack / ADR Gate / owner を確認 |
| Sprint 完了時 | Review 欄、reference、inventory を更新 |
| Provider Matrix 更新時 | TOML / docs / reference / tests を同期 |
| SecretBroker 更新時 | DD-06 / DD-02 / migration / tests を同期 |
| AgentRun 更新時 | DB / API / frontend / eval enum を同期 |
| hook 追加時 | shell 実行可否と inventory 更新 |
| skill 追加時 | routing / inventory / owner matrix 更新 |
| 四半期 | 全 rules / reference / hooks / skills の棚卸し |

## 3. Catalog Sync

- skill を追加したら `harness-inventory.md` と `agent-routing.md` を更新する。
- agent を追加したら owner matrix に責務を載せる。
- hook を追加したら対象 path、event、rollback、noise リスクを書く。
- Codex mirror を追加したら Claude-only field が残っていないか確認する。
- Provider Matrix を更新したら `last_verified_at` と matrix version を更新する。
- Sprint Pack template を変えたら `sprint-pack-adr-gate.md` と backlog の展開ルールを確認する。
- ADR Criteria を変えたら heavy template、rules、reference を同期する。
- Hard Gates / KPIs を変える場合は PRD-01 変更として扱う。

## 4. 四半期レビュー

確認項目:

- rules が現在の P0 scope と一致している。
- reference に古い実装前提が残っていない。
- `.claude/CLAUDE.md` と rules の重複 drift がない。
- `AGENTS.md` と Codex 実行環境の差分が妥当。
- agents が実際の high-risk 領域をカバーしている。
- hooks が noisy / stale になっていない。
- skills が再帰起動や存在しない path を持たない。
- Codex mirror が shell 実行可能。
- Provider Matrix が外部仕様変更を反映している。
- SecretBroker contract が migration / tests と一致している。
- AgentRun 16 状態が全 layer で一致している。
- Eval fixture が Anti-Gaming rule を守っている。

## 5. Deprecate 規約

| 状態 | 意味 | 扱い |
|---|---|---|
| active | 現行利用 | inventory に載せる |
| deprecated | 置換先あり | 置換先と削除予定 Sprint を書く |
| tombstone | 削除済み記録 | 理由だけ残す |
| removed | 完全削除 | inventory から削除 |

## 6. Deprecation 手順

1. 置換理由を Sprint Pack に書く。
2. 置換先 rule / reference / hook / skill を作る。
3. inventory で old -> new を記録する。
4. 1 Sprint 以上 deprecated として残す。
5. hook / skill が起動されていないことを確認する。
6. 削除する。
7. Review 欄に削除理由を残す。

## 7. Drift 種類

| drift | 例 | 検出 |
|---|---|---|
| term drift | `payload_class` など別名化 | `rg` |
| enum drift | AgentRun status が増減 | contract test |
| matrix drift | TOML と docs の列差分 | provider audit |
| hook drift | path 404 / command 127 | shell smoke |
| codex drift | Claude-only field 残留 | manual review |
| docs drift | ADR Criteria と template 不一致 | plan review |
| fixture drift | private_holdout 期待値露出 | eval audit |
| secret drift | raw secret logging | canary test |

## 8. Version / Date

- 日付は `YYYY-MM-DD`。
- Provider Matrix の `last_verified_at` は外部仕様確認日。
- Sprint Pack の `updated_at` は Pack 更新日。
- ADR の `date` は提案日または accepted 日。
- Eval dataset version は append-only。
- policy pack / prompt pack / provider matrix version は ContextSnapshot と AgentRunEvent に保存する。

## 9. Hook Governance

- P0 hooks は Hard Gates に直結するものから始める。
- hooks を大量導入しない。
- false positive / noise は Sprint Review に記録する。
- hook は fail-closed と warning の区別を持つ。
- destructive な auto-fix は hook に入れない。
- Codex hooks は実 shell command として動くことを優先する。
- `hook exited with code 127` を許容しない。
- hook の rollback は「無効化方法」と「対象 gate への影響」を書く。

## 10. Codex Mirror Governance

- Claude agent を先に確定し、必要なものだけ Codex toml へ mirror。
- `.codex/agents/*.toml` は手動確認する。
- Claude-only tool 名を残さない。
- AskUserQuestion 前提を残さない。
- Skill 再帰起動前提を残さない。
- `$CLAUDE_PROJECT_DIR` を残さない。
- 存在しない path を残さない。
- `workspace-write` でも high-risk は承認条件を明確にする。

## 11. Review Output

四半期レビュー結果は次の形で残す。

```md
# Harness Governance Review YYYY-QN

## Summary
- result: pass | needs_work | blocked

## Drift
| area | finding | action |
|---|---|---|

## Deprecated
| item | replacement | removal_sprint |
|---|---|---|

## Risks
| risk | owner | next_check |
|---|---|---|
```

## 12. 完了条件

- [ ] inventory が現行ファイルと一致する。
- [ ] routing が現行 agent / skill と一致する。
- [ ] owner matrix が Hard Gates / KPIs / ADR をカバーする。
- [ ] provider matrix docs と TOML が同期する。
- [ ] SecretBroker / AgentRun / DB invariant が drift していない。
- [ ] deprecated item の置換先が明確。
- [ ] Codex mirror に Claude-only 前提が残っていない。

