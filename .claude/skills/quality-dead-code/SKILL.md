---
name: quality-dead-code
description: "TaskManagedAI の TS/Python 未使用コードを監査する。Triggers: dead code, unused export"
when_to_use: |
  frontend/backend の未使用 export、未参照 enum、未呼び出し service method、古い fixture を削除候補として整理する時。
  トリガーフレーズ: 'dead code', 'unused export', '未使用コード', 'vulture', 'knip'
argument-hint: "[--target=backend|frontend|both] [--scope=changed|all] [--files=<comma-separated>]"
allowed-tools: Read Bash Grep
---

# quality-dead-code — TypeScript / Python 未使用検出

## 目的

TaskManagedAI の `frontend/` と `backend/` にある未使用 export、未参照 enum、未呼び出し service method、古い test helper を削除候補として整理する。

この skill は削除しない。Sprint Pack の `must_ship` / `defer_if_over_budget` と衝突する候補は削除禁止候補として警告する。

## 必読資料

- `.claude/rules/code-search.md`
- `.claude/rules/core.md`
- `.claude/rules/sprint-pack-adr-gate.md`
- `.claude/reference/directory-structure.md`
- `.claude/reference/deliverables.md`
- `.claude/agents/taskmanagedai/code-reviewer.md`

## 対象

- `frontend/`
- `backend/`
- `backend/tests/`
- `frontend/**/__tests__/`
- `docs/sprints/*.md`
- `docs/adr/*.md`

## 検査手順

1. 利用可能な専用ツールを確認する。

```bash
command -v knip
command -v ts-prune
command -v vulture
```

2. TypeScript 未使用 export を確認する。

```bash
pnpm exec knip
pnpm exec ts-prune
rg -n "export (const|function|class|type|interface|enum)|export \{" frontend
```

専用ツールがなければ、export 名を `rg` で参照検索する。`frontend/app/` の route convention、test、generated type は false positive に注意する。

3. Python 未使用候補を確認する。

```bash
uv run vulture backend
rg -n "class |def |async def |Enum|Literal\[" backend
```

専用ツールがなければ、public class/function/method 名を `rg` で参照検索する。

4. TaskManagedAI 固有 enum / service method を重点確認する。

```bash
rg -n "queued|gathering_context|provider_incomplete|repair_exhausted|blocked_reason|payload_data_class|allowed_data_class|tool_mutating_gateway_stub|runner_mutation_gateway|ContextSnapshot|SecretBroker|ProviderAdapter" backend frontend
```

削除禁止に近い候補:

- AgentRun 16 状態
- blocked reason 3 種
- ContextSnapshot 10 カラム
- Provider Compliance enum / ordinal
- SecretBroker status / operation
- gateway kind
- Hard Gate / KPI fixture id

5. Sprint Pack との衝突を確認する。

```bash
rg -n "must_ship|defer_if_over_budget|SP-[0-9]{3}|AC-HARD|AC-KPI|ADR-[0-9]{5}|AgentRun|SecretBroker|Provider|runner" docs/sprints docs/adr
```

削除候補が Sprint Pack `must_ship`、ADR、Hard Gate fixture、Quality KPI の data source に出ている場合は `protected_by_plan` として扱う。

## 出力 contract

```markdown
## Dead Code Audit Result
Verdict: PASS|WARN|BLOCK

## Deletion Candidates
| confidence | file:line | symbol | evidence | risk | recommendation |
|---|---|---|---|---|---|

## Protected Candidates
| file:line | symbol | protected_by | reason |
|---|---|---|---|

## Tooling
| tool | result | note |
|---|---|---|
```

confidence:

- `high`: 専用ツール + `rg` references なし
- `medium`: `rg` references なし、framework convention の可能性あり
- `low`: コメント / docs のみ参照、将来 Sprint 予定あり

## 失敗時の挙動

- 専用ツール未導入なら WARN とし、`rg` fallback のみで判定する。
- LSP が使えない場合は `rg` references を使う。
- AgentRun / Provider / SecretBroker / DB boundary に関わる symbol は high confidence でも削除提案を慎重扱いにする。
- 削除が ADR Gate Criteria 11 種に該当する場合は、削除ではなく ADR 要否を出す。

## TaskManagedAI 不変条件 trace

- Sprint Pack `must_ship` と削除候補の衝突防止
- AgentRun 16 状態 / ContextSnapshot 10 カラム drift 防止
- Provider Compliance enum / data class ordinal 保護
- SecretBroker operation / audit event 保護
- Hard Gate fixture / Quality KPI data source 保護

