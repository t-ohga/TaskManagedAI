---
name: adr-audit
description: "TaskManagedAI ADR Gate Criteria 11 種の不足と drift を監査する。Triggers: ADR audit"
when_to_use: |
  docs/adr、Sprint Pack、git diff/log を照合し、ADR Gate Criteria 11 種の不足、status drift、retro ADR 漏れを監査する時。
  トリガーフレーズ: 'ADR audit', 'ADR Gate', 'Criteria 11', 'retro ADR', 'break-glass'
argument-hint: "[--scope=changed|branch|all] [--since=<git-ref>] [--sprint=SP-NNN]"
allowed-tools: Read Bash Grep
---

# adr-audit — ADR Gate Criteria 11 種 audit

## 目的

TaskManagedAI の変更が ADR Gate Criteria 11 種に該当する場合に、実装前 ADR、Sprint Pack heavy、ADR status、retro ADR 24h rule、break-glass 対象外ルールを満たしているか監査する。

この skill は監査だけを行う。ADR 作成や status 変更は行わない。

## 必読資料

- `.claude/rules/sprint-pack-adr-gate.md`
- `.claude/rules/plan-review.md`
- `.claude/rules/core.md`
- `.claude/reference/deliverables.md`
- `.claude/reference/governance-cycle.md`
- `.claude/reference/audit-ownership-matrix.md`
- `.claude/agents/taskmanagedai/plan-reviewer.md`
- `.claude/agents/taskmanagedai/sprint-pack-reviewer.md`

## 対象

- `docs/adr/*.md`
- `docs/sprints/*.md`
- `docs/基本設計/`
- `docs/実装計画/`
- `backend/`
- `frontend/`
- `migrations/`
- `.claude/`
- `.codex/`
- git diff / git log

## 検査手順

1. ADR 一覧と status を確認する。

```bash
rg --files docs/adr
rg -n "ADR-[0-9]{5}|status:|proposed|accepted|superseded|rejected|date:|criteria|rollback|関連 Sprint" docs/adr docs/sprints
```

2. 変更ファイルを取得する。

```bash
git diff --name-only
git diff --name-only --cached
git log --name-only --oneline --since="24 hours ago"
```

3. Criteria 11 種の該当を判定する。

```bash
rg -n "auth|actor|principal|tenant_id|project_id|migration|OpenAPI|APIRouter|AgentRunEvent|tool registry|trust_tier|SecretBroker|secret_ref|capability|public bind|Funnel|delete|rollback|ProviderAdapter|provider_compliance|GitHub App|permission|runner_mutation_gateway|tool_mutating_gateway_stub" .
```

Criteria:

1. 認証・認可
2. DB schema
3. API 契約 / event schema
4. AI エージェント権限
5. MCP / tool 権限
6. Secrets 管理方式
7. 外部公開設定
8. 破壊的操作
9. 広範囲リファクタ
10. Provider 追加 / 切替
11. GitHub App permission

4. Sprint Pack heavy と ADR refs を照合する。

```bash
rg -n "type: heavy|adr_refs|planned_adr_refs|must_ship|defer_if_over_budget|ADR-[0-9]{5}|Criteria|high-risk" docs/sprints
```

BLOCK:

- Criteria 11 種に該当する変更で ADR がない
- heavy Pack ではない
- `adr_refs` / `planned_adr_refs` が空
- rollback / audit / verification が ADR にない
- break-glass で Criteria 11 種を先行実装している

5. ADR status drift を確認する。

```bash
rg -n "status:\s*proposed|status:\s*accepted|accepted_at|date:|Review|Decision" docs/adr
```

WARN/BLOCK:

- 実装済みなのに `proposed` のまま
- `accepted` なのに rollback / risk / tests が空
- superseded ADR が index / Sprint Pack に残る
- retro ADR が 24h 以内に作成されていない

6. 過去変更履歴を確認する。

```bash
git log --oneline --decorate --max-count=50
git log --name-only --pretty=format:'%H %ad %s' --date=iso --max-count=30
```

直近変更に Criteria 11 種が含まれる場合、対応 ADR が同じ時期にあるか確認する。

## 出力 contract

```markdown
## ADR Audit Result
Verdict: PASS|WARN|BLOCK

## Missing ADRs
| severity | criterion | evidence | required ADR | suggested owner |
|---|---|---|---|---|

## ADR Drift
| severity | adr | issue | evidence | fix |
|---|---|---|---|---|

## Break-Glass Violations
| severity | change | reason | action |
|---|---|---|---|
```

## 失敗時の挙動

- `docs/adr/` が未作成なら BLOCK。ただし repo 初期化直後で template のみの場合は WARN とし、対象変更有無を分ける。
- git history が浅い場合は current diff を優先し、history 不足を gap に書く。
- Criteria 11 種に該当するか不明な場合は WARN ではなく `NEEDS_DECISION` として整理する。
- 破壊的操作、DB schema、API 契約、Secrets、Provider、GitHub App permission は保守的に BLOCK 寄りで扱う。

## TaskManagedAI 不変条件 trace

- Sprint Pack 必須ゲート
- ADR Gate Criteria 11 種
- Criteria 11 種は break-glass 対象外
- Provider / SecretBroker / AgentRun / DB invariant への影響明記
- Hard Gates / Quality KPIs trace
- rollback / audit / verification 必須

