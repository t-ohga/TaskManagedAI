# Claude Verification Checklist (Codex 3 日間完了後、Claude 戻り時の確認手順)

本 file は **Claude が 2026-05-25 夕方に戻ったときの確認手順 checklist**。Codex が autonomous で進めた 4 task の品質を verify + 必要時 fix PR 起票する path を提供。

## 1. 起動 protocol

### 1.1 即座に Read (5-15 min)

1. `docs/codex-handoff/2026-05-22-3day-autonomous/README.md`
2. **本 file (03-claude-verification-checklist.md)**
3. `docs/codex-handoff/2026-05-22-3day-autonomous/STOPPED.md` (存在確認、もしあれば緊急対応)
4. `docs/codex-handoff/2026-05-22-3day-autonomous/COMPLETION_REPORT.md`
5. `docs/codex-handoff/2026-05-22-3day-autonomous/completion/task-NN-completed.md` 全件

### 1.2 handoff memory rehydrate

```bash
cat ~/.claude/projects/-Users-tohga-repo-TaskManagedAI/memory/project_session_2026_05_25_codex_3day_complete.md
```

なければ Codex が起票 skip した可能性、`COMPLETION_REPORT.md` ベースで再構築。

## 2. 検証 sequence (推奨順序)

### Sequence A: blocker 緊急対応 (5 min)

- [ ] `STOPPED.md` 存在確認
- [ ] 存在する場合: 内容 Read + 即座に Claude が対応 (fix PR or AskUserQuestion)

### Sequence B: PR list 一括 verify (30-60 min)

```bash
# Codex が起票した全 PR list
gh pr list --state merged --search "merged:>=2026-05-23" --json number,title,headRefOid,mergeCommit \
  | jq -r '.[] | "\(.number) \(.title)"'
```

各 PR で:

- [ ] Codex auto-review baseline 確認 (admin bypass merge 後でも残 finding チェック)
  ```bash
  for PR in $(merged_pr_list); do
    .claude/scripts/codex_pr_full_review.sh $PR 2>&1 | head -50
  done
  ```
- [ ] Codex finding 採否判定が `00-codex-behavior-guide.md` §6.3 に従って適切か
- [ ] cascade pattern 防止 (matrix-based fix) が正しく適用されているか

### Sequence C: Mac local stack 状態確認 (10 min)

```bash
# docker compose 5 services healthy
docker compose ps

# alembic head (task-01 完了で 0025_sp014_event_type_37.py + 0026/0027/0028 SP-014 migrations まで進んでいるはず)
docker compose exec postgres psql -U taskmanagedai -d taskmanagedai -c \
  "SELECT version_num FROM alembic_version"

# multi_agent test
docker compose exec fastapi uv run pytest tests/multi_agent/ -q
# 期待: 30 (SP-013 batch 0) + N (SP-014 batch 0 で追加) PASS

# frontend test
cd frontend && pnpm vitest run
# 期待: 70+ (SP-012 累計) + N (SP-012-8 i18n 後の test update) PASS
```

### Sequence D: 各 task の DoD checklist verify (60-120 min)

各 task ファイル `tasks/task-NN-*.md` の §DoD checklist を全件確認:

#### task-01 (SP-014 batch 0)

- [ ] SP014-T01〜T09 全 ticket 実装完了
- [ ] policy_profile_action_effects 14 rows exact seed verify (`SELECT COUNT(*) FROM policy_profile_action_effects` = 14)
- [ ] orchestrator lease/failover stress test PASS
- [ ] Tier 2 で agent decider 経路残存しない (4 重防御 test PASS)
- [ ] SecretBroker 6 negative case 個別 reason_code (cross-source-enum-integrity §1 5+ source 整合)
- [ ] event_type 28→37 拡張 5+ source 整合確認 (`SELECT COUNT(DISTINCT event_type) FROM agent_run_events` ≤ 37)
- [ ] ADR-00009 update accepted + Tool Registry network ADR 新規 accepted
- [ ] Sprint Pack SP-014 frontmatter `status: completed` + Review 章

#### task-02 (SP-012-8)

- [ ] navigation + 7 page 全件日本語化
- [ ] 技術用語 untranslated 維持 (`grep -E "payload_data_class|role_id|tenant_id" frontend/` で hit confirm)
- [ ] accessible-name 維持 (vitest で `getByRole({ name: ... })` PASS)
- [ ] Sprint Pack SP-012-8 frontmatter `status: completed`

#### task-03 (SP-022-1)

- [ ] deviation 1-6 全件実装 (scripts + compose + Dockerfile + dev login)
- [ ] deviation 7 (Layer C runbook §1-§9) 起票完了
- [ ] Sprint Pack SP-022-1 frontmatter `status: completed`

#### task-04 (SP-012-9 残)

- [ ] Approvals / Agent Runs / Audit / Settings 4 page の read-only wiring 完了
- [ ] server-owned-boundary §1: tenant_id / project_id / actor_id session 経由 (`grep -E "Depends\(get_tenant_id|get_current_actor_id" backend/app/api/`)
- [ ] mutation defer TODO comment 確認
- [ ] Sprint Pack SP-012-9 frontmatter `status: completed`

### Sequence E: invariant regression verify (30 min)

Claude が PR #100-#141 で確立した invariant が壊れていないか:

- [ ] **server-owned-boundary §1**: `grep -E "tenant_id: int = Body|project_id: int = Body|actor_id: int = Body" backend/app/api/` で hit zero (caller-supplied 経路なし)
- [ ] **5+ source enum integrity**: `python -c "from backend.app.domain.agent_role.taxonomy import STANDARD_ROLE_IDS; assert len(STANDARD_ROLE_IDS) == 10"` PASS
- [ ] **AgentRun 16 状態**: `python -c "from backend.app.domain.agent_run.statuses import AGENT_RUN_STATUSES; assert len(AGENT_RUN_STATUSES) == 16"` PASS
- [ ] **blocked_reason 3 種**: `python -c "from backend.app.domain.agent_run.statuses import BLOCKED_REASONS; assert len(BLOCKED_REASONS) == 3"` PASS
- [ ] **secret_capability_tokens raw secret 非保存**: `grep -E "secret_value|raw_secret|capability_token_value" backend/app/db/models/` で hit zero
- [ ] **runner_mutation_gateway / tool_mutating_gateway_stub** 混同なし: `grep -E "runner_mutating_gateway|tool_mutation_gateway" backend/` で hit zero (typo の逆順 hit がないか)

### Sequence F: Codex finding cascade pattern verify (30 min)

cascade pattern (PR #133→#135→#137 教訓) が再発していないか:

- [ ] Codex finding の adopt fix が **matrix-based logic** で全 case enforce
- [ ] 1 fix で別 invariant 違反を引き起こしていない (`gh pr list --state merged --search "title:fix/" --json number,title` で fix PR 連鎖確認)
- [ ] regression test が **case ごと別 test function** で追加されている (`grep -E "def test_.*matrix|def test_.*case_[a-z]" tests/multi_agent/` で hit 確認)

### Sequence G: 次 Sprint kickoff 判断 (30 min)

3 日間の Codex work で次 Sprint への path が明確化しているか:

- [ ] SP-014 batch 1 (inter-agent communication、SP-015 prerequisite) の kickoff readiness 確認
- [ ] SP-016 (CLI launcher) / SP-017 (Web UI 拡張) / SP-018 (memory backend) の依存関係確認
- [ ] Wave 13 amendment 2 件 accepted 化 (2026-05-22 deadline 既経過、retroactive accepted 起票必要か確認)
- [ ] P0.1 sealed CI guard 状態確認 (`TASKHUB_P0_1_OPENED` env と sealed path 整合)

### Sequence H: 全 task 主要成果物の codex-all-loops loop (3-6 hour、品質担保補強)

3 日間 Codex work の **全 task 主要成果物** に対し `codex-all-loops` skill で deeper round を実施。Claude Code main session で起動するため AGENTS.md「Codex chain 禁止」整合。

#### H.1 計画書 (plan / Sprint Pack) loop

完遂 Sprint Pack を順次:

```
Skill(skill="codex-all-loops", args="docs/sprints/SP-014_orchestrator_agent.md --mode=plan --max-rounds=8 --clean-criteria=critical_zero")
Skill(skill="codex-all-loops", args="docs/sprints/SP-0045_tool_registry.md --mode=plan --max-rounds=8 --clean-criteria=critical_zero")
Skill(skill="codex-all-loops", args="docs/sprints/SP-012-8_ui_i18n_japanese.md --mode=plan --max-rounds=6")
Skill(skill="codex-all-loops", args="docs/sprints/SP-012-9_ui_wiring_completion.md --mode=plan --max-rounds=6")
Skill(skill="codex-all-loops", args="docs/sprints/SP-022-1_scripts_wrapper_hardening.md --mode=plan --max-rounds=6")
```

各 Sprint Pack で Phase 1 (構造 review) + Phase 2 (敵対視点) を 8 round 程度回す。Codex Self-Review (Round 1+2) で見落とした論点を補強。

#### H.2 実装 dir loop

主要実装 dir で:

```
Skill(skill="codex-all-loops", args="backend/app/services/orchestrator --mode=code --impl-target backend/app/services/orchestrator --impl-files orchestrator.py,lease_manager.py,dispatcher.py,kill_switch.py,progress_lease.py --max-rounds=10 --clean-criteria=critical_zero")

Skill(skill="codex-all-loops", args="backend/app/services/tool_registry --mode=code --impl-target backend/app/services/tool_registry --impl-files network_policy.py,registry.py --max-rounds=8")

Skill(skill="codex-all-loops", args="frontend/app/(admin)/tickets --mode=code --impl-target frontend/app/(admin)/tickets --impl-files page.tsx,new/page.tsx,[id]/page.tsx --max-rounds=6")
```

各 dir で Phase 1 (impl-loop) + Phase 2 (adversarial-loop) + Phase 3 (review-loop) を 10 round 回し、Codex Self-Impl-Review (1 round) で見落とした観点を補強。

#### H.3 findings 採否判定 + fix PR 起票

各 loop で出た findings を 3 分類:

- **adopt**: 真の bug or invariant 違反 → fix PR 起票 (`fix/codex-loop-residual-<scope>-2026-05-25`)
- **reject**: Codex 誤認 or 既存 pattern と意図的差異 → `~/.claude/local/codex-reviews/2026-05-25/<slug>/rejected.md` 記録
- **defer**: 別 Sprint / 別 PR → carry-over Sprint Pack に記録

fix PR の admin bypass merge:

```bash
PR_NUM=$(gh pr list --head fix/codex-loop-residual-<scope>-2026-05-25 --json number -q '.[0].number')
HEAD_SHA=$(gh pr view "$PR_NUM" --json headRefOid -q '.headRefOid')
gh api -X PUT "repos/t-ohga/TaskManagedAI/pulls/$PR_NUM/merge" -f merge_method=squash -f sha="$HEAD_SHA" \
  -f commit_title="fix(codex-loop-residual): <scope> 修正 (#$PR_NUM)" \
  -f commit_message="..."
```

#### H.4 loop 完了判定

全 task 主要成果物で `critical_zero` 達成 (CRITICAL=0、HIGH≤2 で全 loop close) を確認。

cascade pattern 検出時は **matrix-based logic** で fix (PR #133→#135→#137 教訓、cross-source-enum-integrity §1)。

### Sequence I: 残 Sprint kickoff readiness 昇格 + handoff memory 起票

Sequence H 完了後、次 Sprint への kickoff readiness を確定:

- SP-015 inter-agent communication: SP-014 完遂で prerequisite 充足 → `draft` → `ready` 昇格 path 検討
- SP-016 UI CLI parity: SP-014/SP-015 完遂で 部分 prerequisite 充足
- SP-007 phase5 残作業: SP-0045 完遂で hook trust boundary prerequisite 充足
- SP-008 GitHub App RepoProxy: 独立着手可能 (P0.1 開始後)

handoff memory 起票:

```
~/.claude/projects/-Users-tohga-repo-TaskManagedAI/memory/project_session_2026_05_25_claude_verification_with_loop_complete.md
```

内容:
- 完了 task 数 + PR merge 累計 (PR #142 → ~#175 想定)
- Sequence A-I 完遂結果
- 各 task の codex-all-loops loop 結果 (findings 採否件数)
- fix PR 数 (Sequence H で起票分)
- 次 Sprint kickoff path
- carry-over Sprint Pack 一覧

MEMORY.md index 1 行追加。

## 3. fix PR 起票 protocol (必要時)

Codex finding で `defer` 判定された case が **本来 adopt すべき** だった場合や、cascade pattern 漏れ検出時:

```bash
git checkout -b fix/codex-residual-<scope>-2026-05-25 origin/main
# 修正実装
git push -u origin fix/codex-residual-<scope>-2026-05-25
gh pr create --base main --head fix/codex-residual-<scope>-2026-05-25 \
  --title "fix(codex-residual): <scope> 修正" \
  --body "## Summary\nCodex 3-day autonomous work の residual fix\n\n## context\n- Codex PR #N で defer → 採否判定見直し adopt\n- または cascade pattern 検出 fix\n\n## verification\n- ..."
```

admin bypass merge (CI billing-blocked、`00-codex-behavior-guide.md` §4.3 6 条件):

```bash
PR_NUM=$(gh pr list --head <branch> --json number -q '.[0].number')
HEAD_SHA=$(gh pr view "$PR_NUM" --json headRefOid -q '.headRefOid')
gh api -X PUT "repos/t-ohga/TaskManagedAI/pulls/$PR_NUM/merge" \
  -f merge_method=squash \
  -f sha="$HEAD_SHA" \
  -f commit_title="..." \
  -f commit_message="..."
```

## 4. handoff memory 更新

Claude verification 完了後:

```bash
# 新規 memory file 起票
cat > ~/.claude/projects/-Users-tohga-repo-TaskManagedAI/memory/project_session_2026_05_25_claude_verification_complete.md <<EOF
# 2026-05-25 Claude verification complete (Codex 3-day autonomous handoff 完了)

## verified
- task-01 (SP-014 batch 0): ...
- task-02 (SP-012-8): ...
- task-03 (SP-022-1): ...
- task-04 (SP-012-9 残): ...

## fix PR 起票
- fix/codex-residual-* x N

## next session entry
- SP-015 inter-agent communication kickoff
- ...
EOF

# MEMORY.md 1 行追加
```

## 5. 全体総括 (Claude が user に報告する内容)

3 日間の autonomous work 累計:

- 完了 task: N / 4 (4 件全件完遂 or N 件完遂 + M 件 STOPPED)
- 累計 PR merge: M PR (PR #NNN-#MMM、merge SHA 範囲)
- 完遂 Sprint: SP-014 batch 0 + SP-012-8 + SP-022-1 + SP-012-9 残
- 累計 Codex finding: P1×N + P2×M + P3×K = X 件
  - adopt: X 件
  - reject: Y 件
  - defer: Z 件
- multi_agent test: 30 → N PASS (累計 +N)
- frontend test: 70+ → M PASS (累計 +M)
- ADR accepted: ADR-00009 update / ADR-00021 (Tool Registry network)
- Mac local stack: alembic head N に進行
- 残作業 (Claude が次 session で着手):
  - 1. ...
  - 2. ...

## 6. 緊急 escalation (Claude 戻り時に検知時)

以下を検知したら **user に AskUserQuestion で確認** (autonomous full drive 例外 4 条件の 1 つ「reject 確証」):

- 全 task の半数以上が `STOPPED.md` で停止
- invariant violation が 1 件以上 main に merge されている (regression)
- Codex finding cascade pattern 再発 (3 連続 fix で別 invariant 違反)
- Mac local stack 不可逆破壊 (rollback 不能 schema 変更)
