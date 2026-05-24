# Codex Behavior Guide

## 起動 protocol

Codex は次の順で読む。

1. `docs/codex-handoff/2026-05-24-sequence-h-sp015-kickoff/README.md`
2. 本 file
3. `01-current-state.md`
4. `02-task-priority-matrix.md`
5. 着手する `tasks/task-NN-*.md`
6. 関連 Sprint Pack / ADR / rules

## 作業環境

- 新しい worktree を `origin/main` から作る。
- 既存 checkout の未コミット差分を混ぜない。
- docs-only task では `scripts/worktree_setup.sh` を省略できる。
- code / migration task では worktree setup 後に検証を実行する。

## 本 handoff の原則

1. task-01 と task-02 が `READY` になるまで SP-015 実装に入らない。
2. SP-015 は DB schema / API contract / audit / SecretBroker に触れる
   heavy Sprint なので Self-Plan-Review 2 round 必須。
3. `codex-all-loops` は Claude 側 skill。Codex 自身は呼ばず、
   同等観点を Self-Review と checklist で代替する。
4. GitHub Actions quota block は品質 failure として扱わない。
   local verify と Codex review helper を品質信号にする。
5. finding は必ず adopt / reject / defer のどれかで記録する。

## Self-Plan-Review

計画必須 task では、実装前に以下を行う。

### Round 1: 構造 review

- Sprint Pack / ADR / rules / previous completion report を読む。
- ticket 順序、migration 順序、依存関係、DoD を点検する。
- 抜け漏れ、曖昧さ、既存 invariant との矛盾を列挙する。

### Round 2: 敵対視点 review

- race condition
- replay / hijack
- tenant / project / parent_run 越境
- raw secret / raw message body 露出
- weak assertion
- cascade pattern
- rollback 不能

### Readiness Gate

- 残存 CRITICAL = 0
- 残存 HIGH <= 2
- HIGH が残る場合は理由と mitigation を task review に明記
- gate 未達なら `STOPPED.md`

## Self-Impl-Review

実装 batch ごとに次を行う。

1. diff を読み直す。
2. invariant checklist を全件確認する。
3. regression test が case ごとに独立しているか確認する。
4. local verify を実行する。
5. PR 起票後 `codex_pr_full_review.sh <PR>` で actionable 0 を確認する。

## 28 項目 checklist

### invariant

- [ ] server-owned-boundary: caller-supplied tenant/project/actor なし
- [ ] 5+ source enum integrity: Literal / frozenset / Pydantic / pytest / DB CHECK
- [ ] AgentRun 16 status を破壊していない
- [ ] blocked_reason 3 種を破壊していない
- [ ] raw secret を DB / log / artifact / audit / ContextSnapshot に保存しない
- [ ] runner_mutation_gateway と tool_mutating_gateway_stub を混同しない
- [ ] Provider Compliance reason_code を drift させない
- [ ] approval 4 整合を維持する
- [ ] self-approval を許可しない
- [ ] atomic claim / consume は UPDATE WHERE RETURNING pattern
- [ ] secret_ref は opaque のまま扱う
- [ ] tenant / project / parent_run boundary を複合 FK または service guard で守る

### test

- [ ] weak assertion 単独禁止
- [ ] regression case ごと別 test
- [ ] negative test を含む
- [ ] enum exact set test を含む
- [ ] DB contract test を含む
- [ ] matrix-based test を含む

### PR description

- [ ] self-review verdict
- [ ] changes table
- [ ] verification result
- [ ] invariant trace
- [ ] ADR Gate 判定

### local verify

- [ ] `uv run ruff check backend tests`
- [ ] `uv run mypy backend`
- [ ] `uv run pytest tests/<scope> -q`
- [ ] frontend 変更時: `pnpm typecheck && pnpm lint && pnpm vitest run`
- [ ] migration 変更時: upgrade / downgrade / upgrade verify

## admin bypass merge 条件

CI quota block 中でも、以下を満たす PR のみ admin bypass merge 可能。

- local verify clean
- Codex review helper actionable 0
- Self-Review gate 達成
- migration rollback path 確認済み
- invariant trace 記載済み
- carry-over が docs に記録済み

## STOPPED.md 起票条件

- gate 未達
- ADR / Sprint Pack / implementation plan の矛盾
- DB migration rollback 不能
- raw secret / raw message body 露出疑い
- tenant / project boundary 破壊疑い
- 3 連続同一 failure
