# task-01 完了報告 (2026-05-23)

## summary

- task: SP-014 batch 0 orchestrator agent core
- start: 2026-05-22 JST
- end: 2026-05-23 JST
- 完了 ticket: SP014-T01 から SP014-T09
- scope: orchestrator service module、lease / heartbeat / failover / kill switch、
  progress lease、review_artifacts 4 重防御、policy_profile seed、Tool
  Registry network enum、remote_agent_gateway deny-only stub、KPI rollup、
  SecretBroker multi-agent negative、AgentRunEvent 28 -> 37
- 累計 PR: #145 から #150 merged、review residual fix #171 merged

## PR list

- #145 `9b0c6ad796ed152fbf86dd3e648a4c650aba3c7a`
  - batch 0a: orchestrator service module, lease primitives, event_type 37
    prerequisite
  - Codex finding: inline 5 件、#171 で all adopt
- #146 `8975e96fec69a0dec99a1c94d1e703adebf8cc1f`
  - batch 0b: review_artifacts 4-layer defense
  - Codex finding: inline 3 件、#171 で all adopt
- #147 `91a7ef2caed89a6d481b23b3c50fcd9a4752570d`
  - batch 0c: policy_profile + 14 row seed + ADR-00009 update
  - Codex finding: inline 2 件、#171 で all adopt
- #148 `d71b1b204a67cf5e7bacd6989f258d8f92eea621`
  - batch 0d: Tool Registry network enum + tool_network_policies + ADR-00030
  - Codex finding: inline 3 件、#171 で all adopt
- #149 `ec4a4ebbd18dbe4ba3fa15dcd2e9bb11771f834f`
  - batch 0e: remote_agent_gateway deny-only stub
  - Codex finding: clean
- #150 `3409388626ed1958dc9db3d8b0521300de133902`
  - batch 0f: KPI rollup + SecretBroker negative
  - Codex finding: inline 1 件、#171 で all adopt
- #171 `316dcd3c4adf0abe2cc17bd2f70bf360a10e7191`
  - task-01 residual fixes across #145-#150 plus regression tests
  - Codex finding: clean after 2 Codex review requests

## Codex finding 採否判定

- #145 P1/P2: kill switch / lease / progress / dispatch が non-running run に
  mutation 可能。
  - judgment: adopt。service UPDATE / lookup を running-only に制限。
  - follow-up PR: #171。
- #145 P1: kill switch actor が human-only に固定されていない。
  - judgment: adopt。actor_type=`human` を DB で解決して enforcement。
  - follow-up PR: #171。
- #146 P2: requester / reviewer separation と reviewer payload binding が
  service guard で不足。
  - judgment: adopt。service guard と DB negative tests を追加。
  - follow-up PR: #171。
- #146 P2: policy binding が top-level payload 由来になり得る。
  - judgment: adopt。nested `policy_input` のみを正本化。
  - follow-up PR: #171。
- #147 P1: legacy project `policy_profile` を FK 追加前に normalize していない。
  - judgment: adopt。migration 0027 で default normalize。
  - follow-up PR: #171。
- #147 P2: missing tenant seed が固定 tenant name を再利用する。
  - judgment: adopt。tenant id based unique default name。
  - follow-up PR: #171。
- #148 P1/P2: malformed domain allowlist / invalid payload class / blank
  provider が fail-closed でない。
  - judgment: adopt。deny reason を返す fail-closed guard と regression tests。
  - follow-up PR: #171。
- #150 P1: recursive run tree が parent cycle で loop し得る。
  - judgment: adopt。recursive CTE visited path guard + cycle test。
  - follow-up PR: #171。

## defer / carry-over

- SP014-DEFER-001: `repo_pr_merged` event_type と formal `time_to_merge`
  metric は ADR-00004 / SP-018+ scope。現行 KPI は `repo_pr_opened`
  -> completed proxy として明示。
- SP014-DEFER-002: `citation_coverage` の final adopted artifact attribution
  は adopted_artifacts link table が必要なため SP-018 / Phase F scope。
- SP014-DEFER-003: full remote adapter / Codex app-server / Claude SDK adapter
  integration は ADR-00013 proposed/full integration scope。task-01 は
  deny-only stub まで。
- SP014-DEFER-004: `uv run alembic check` は既存
  `migrations/env.py target_metadata` infrastructure debt。PR #171 では fresh
  DB の `upgrade head -> downgrade -1 -> upgrade head` を PASS 済み。

## blocker

- No CRITICAL / HIGH / MEDIUM blocker remains for task-01 owned scope.
- Hosted GitHub Actions are not quality signal in this period because the repo
  is monthly-quota blocked. Local verification and Codex review baseline were
  used for admin bypass merge.

## verification

- [x] SP014-T01〜T09 implemented across PR #145-#150
- [x] AgentRunEvent 28 -> 37 implemented by `0025_sp014_event_type_37.py`
- [x] review_artifacts 4 defense migration/model/service/tests implemented
- [x] policy_profile 14 action-effect rows and tenant trigger implemented
- [x] Tool Registry network enum + `tool_network_policies` implemented
- [x] remote_agent_gateway deny-only stub implemented
- [x] orchestrator KPI rollup + SecretBroker multi-agent negative tests implemented
- [x] PR #171 regression tests cover all actionable Codex inline residuals
- [x] PR #171 verification: `uv run ruff check backend tests`
- [x] PR #171 verification: `uv run mypy backend`
- [x] PR #171 verification: targeted DB pytest `53 passed`
- [x] PR #171 verification: fresh DB Alembic upgrade / downgrade / upgrade PASS
- [x] PR #171 verification: `.claude/scripts/codex_pr_full_review.sh 171`
  actionable 0
- [x] Sprint Pack SP-014 frontmatter `status: completed` + Review 章 updated by task-08

## Claude verification 依頼項目

1. `backend/app/services/orchestrator/*` の running-only mutation boundary が
   AgentRun state machine invariant と整合するか確認。
2. `review_artifact_guard.py` の nested `policy_input` binding が Tier 2 human
   review invariant と整合するか確認。
3. `orchestrator_kpi_rollup.py` の provider_responded usage source 限定と
   cycle guard が ADR-00014 §10 と整合するか確認。
