# task-07: Backend test coverage expansion

**優先**: P2、**計画必須**: 不要 (light、scope 明確)、**self-review**: Plan 1 round + Impl 1 round 推奨、**想定 effort**: 0.5-1 day、**依存**: なし (独立並行可)

> `codex-all-loops` は Claude 専用 skill (`00-codex-behavior-guide.md` §3.0)。Codex は §3 Self-Review Protocol で同等観点を確保。

## 1. 目的

PR #100-#143 で merge された **新 endpoint / service / migration の untested branch** を追加。`testing.md` §13 完了条件「変更範囲に対応する unit / contract / E2E がある」を遡及的に補強する。

## 2. 起動 protocol

### 2.1 Read order

1-5. handoff 共通 file
6. **本 file**
7. `.claude/rules/testing.md` (全文、特に §3 弱い assertion 禁止 + §13 完了条件)
8. `.claude/rules/cross-source-enum-integrity.md` (5+ source 整合 test pattern)
9. 既存 test fixture pattern: `tests/multi_agent/test_*.py` + `tests/tickets/test_*.py`

### 2.2 worktree

```bash
git worktree add .claude/worktrees/codex-task-07-test-coverage origin/main
```

## 3. 計画 phase (§3.1 Round 1 のみ)

Round 1: 構造 review = untested branch inventory

```bash
# 既存 test coverage 確認
uv run pytest --collect-only tests/ -q | wc -l
# coverage report (option)
uv run pytest --cov=backend tests/ --cov-report=term-missing
```

scope は **PR #100-#143 で追加された branch のうち test cover が弱い箇所** に限定。**100% coverage は目的ではない** (testing.md §3 弱い assertion 禁止)。

### 3.1 inventory (本 task の対象範囲、目安)

- `backend/app/api/tickets.py` の `create_ticket_endpoint` + `update_ticket_endpoint` で抜けがちな branch
- `backend/app/api/dev_login.py` の session resolve path
- `backend/app/services/orchestrator/` (task-01 で実装、本 task で追加 negative test)
- `backend/app/db/models/project_agent_role.py` + `standard_role_ids_mirror.py` (migration 0020/0021 で追加)
- `backend/app/services/policy/` (policy_profile 14 rows seed の cross-source 整合)
- `tests/multi_agent/` の matrix-based fix coverage (PR #137 教訓、case ごと別 test function)

## 4. 実装 phase

### 4.1 batch A: tickets API negative test (untested branch)

- `update_ticket_endpoint` で `description` explicit clear (空文字 vs null) の 2 case 別 test
- `create_ticket_endpoint` で server-owned-boundary §1 違反 caller-supplied 入力 reject test
- `tickets.py` の `404` vs `409` (concurrent update) race test

### 4.2 batch B: dev_login + session resolve test

- `get_current_actor_id` / `get_tenant_id` Depends が抜けた場合 reject test
- session cookie expired vs invalid vs missing 3 case 別 test
- multi-project switching test (SP-012-11.1 で導入 path)

### 4.3 batch C: policy_profile 14 rows seed 整合 test

- exact 14 rows 維持 negative test (15 rows / 13 rows で assert reject)
- profile × action_class matrix 完全 coverage
- effect 値 (allow / require_review / deny) の 5+ source 整合

### 4.4 batch D: cross-source-enum-integrity contract test

- standard role 10 種 (Literal + frozenset + DB seed + Pydantic + pytest) 5+ source 整合 fail-fast test
- AgentRun 16 状態 + blocked_reason 3 種 + event_type 28 種 (P0 baseline) / 37 種 (SP-014 完遂後 current) の cross-source 整合 test

### 4.5 Self-Impl-Review (§3.2)

各 batch 末で:
- 弱い assertion (toBeDefined / toBeTruthy / `expect(fn).not.toThrow()` だけ) なし confirm
- snapshot 単独なし confirm
- 各 branch 最低 1 test 対応 (testing.md §4)

## 5. 検証手順

```bash
uv run ruff check tests/
uv run mypy tests/ --strict
uv run pytest tests/ -q

# coverage 確認 (option)
uv run pytest --cov=backend tests/ --cov-report=term-missing | tail -30
```

regression test を必ず追加 (testing.md §3 + §4)。

## 6. PR 起票 + admin bypass merge

batch ごと別 PR or 2-3 batch まとめて 1 PR:

```bash
git push -u origin feat/sp-handoff-test-coverage-batch-a-2026-05-24
gh pr create --base main --title "test(backend): tickets API negative test (untested branch coverage)" --body "..."
```

## 7. Codex auto-review baseline 確認 (必須)

```bash
sleep 60
.claude/scripts/codex_pr_full_review.sh <PR_NUM> 2>&1 | head -100
```

## 8. DoD checklist

- [ ] 各 batch の Untested branch 確実に cover (testing.md §13 完了条件)
- [ ] 弱い assertion 禁止 (testing.md §3) 遵守
- [ ] 5+ source enum integrity test 追加 (cross-source-enum-integrity §1)
- [ ] 既存 contract test regression なし
- [ ] 完了報告 `completion/task-07-completed.md` 起票

## 9. blocker / 緊急停止

- 既存 endpoint の **仕様不明** で test を書けない場合 → STOPPED.md + Claude verification 待ち
- test 追加で新 invariant 違反検出 (regression) → fix PR 起票 (test 追加 PR とは別)、defer 判定で carry-over

## 10. 関連

- `.claude/rules/testing.md` (本 task の base contract)
- `.claude/rules/cross-source-enum-integrity.md` §5 (23 invariant fixture pattern)
- 過去類似 PR: PR #125 (clearableField helper + regression test 追加)、PR #137 (matrix-based fix + case ごと別 test function)
