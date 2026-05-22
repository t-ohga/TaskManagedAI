# task-05: SP-0045 Tool Registry 本体

**優先**: P1、**計画必須**: 必須 (heavy)、**self-review**: Plan 2 round + Impl 1 round 必須、**想定 effort**: 1.5-2 day、**依存**: task-01 SP-014 batch 0d 完遂後

> `codex-all-loops` は Claude 専用 skill (`00-codex-behavior-guide.md` §3.0)。Codex は §3 Self-Review Protocol で同等観点を確保。

## 1. 目的

P0/P0.1 で扱う MCP / external tool / local stdio tool を **機械可読 registry** で一元管理。`allowed_actions` / `trust_tier` / `payload_data_class` の boundary を不変条件として強制 + ContextSnapshot.tool_manifest との lockfile binding を完成させる。

**SP-014 batch 0d との関係**: SP-014 で `tool_network_policies` table + network_access enum 化 (web_fetch/docs_search) を先行実装、本 SP-0045 はその上に **Tool Registry 本体** (tools table + allowed_actions + trust_tier + version lock) を完成。

## 2. 起動 protocol

### 2.1 Read order

1-5. `00-codex-behavior-guide.md` 全文 + `01-current-state.md` + `02-task-priority-matrix.md` + `README.md`
6. **本 file**
7. `docs/sprints/SP-0045_tool_registry.md` (heavy Sprint Pack)
8. `docs/adr/00027_tool_registry_security_boundary.md` (proposed、本 task で accepted 化)
9. `docs/adr/00012_hook_trust_boundary.md` (proposed、本 task で accepted 化)
10. `docs/adr/00013_remote_agent_extension.md` (proposed、参照のみ)
11. SP-014 task-01 完遂後の `tool_network_policies` 実装 (新 table、本 task から拡張)
12. `.claude/rules/server-owned-boundary.md` (trust_tier server-resolved only invariant)

### 2.2 worktree

```bash
cd /Users/tohga/repo/TaskManagedAI
git worktree add .claude/worktrees/codex-task-05-sp0045 origin/main
cd .claude/worktrees/codex-task-05-sp0045
bash scripts/worktree_setup.sh
```

**重要**: task-01 (SP-014 batch 0d) の merge 後に rebase。

## 3. 計画 phase (§3.1 Self-Plan-Review 2 round)

Round 1: 構造 review (tools table schema / allowed_actions 5+ source enum / trust_tier server-resolved / Lockfile design)
Round 2: 敵対視点 (mutating tool 混入 / trust_tier escape / allowed_actions drift / lockfile race condition)

Readiness Gate: CRITICAL=0/HIGH≤2 達成後着手。

## 4. 実装 phase

### 4.1 batch A: tools table + ADR-00027 accepted

- migration: `00NN_p0_1_tool_registry.py` (tools table + tool_versions table)
- ADR-00027 proposed → accepted (`sprint-pack-adr-gate.md` §12)
- ADR-00012 (Hook Trust Boundary) proposed → accepted (本 task で同時)

### 4.2 batch B: allowed_actions + trust_tier 5+ source

- Literal + frozenset + Pydantic + pytest + DB CHECK
- trust_tier は server-resolved only (caller-supplied 経路 signature レベル削除)

### 4.3 batch C: ContextSnapshot.tool_manifest lockfile binding

- tool_registry_version → ContextSnapshot.tool_manifest との binding 実装
- 既存 ContextSnapshot 10 列の `tool_manifest` 列を活用

### 4.4 batch D: contract test + Self-Impl-Review

- tests/tool_registry/ 配下 contract test
- §3.2 Self-Impl-Review 1 round + Readiness Gate (CRITICAL=0)

## 5. 検証手順

```bash
uv run pytest tests/tool_registry/ tests/multi_agent/test_tool_network_policy_integration.py -q
uv run alembic check && uv run alembic upgrade head
uv run alembic downgrade -1 && uv run alembic upgrade head
```

## 6. DoD checklist

- [ ] tools + tool_versions table 完成 (allowed_actions / trust_tier / version)
- [ ] ADR-00027 + ADR-00012 accepted 昇格
- [ ] 5+ source enum integrity (allowed_actions + trust_tier)
- [ ] ContextSnapshot.tool_manifest lockfile binding 完成
- [ ] mutating tool 混入 negative test PASS
- [ ] Sprint Pack SP-0045 `status: completed` + Review 章
- [ ] 完了報告 `completion/task-05-completed.md` 起票

## 7. 関連

- `docs/sprints/SP-0045_tool_registry.md`
- task-01 (SP-014 batch 0d、依存 source)
