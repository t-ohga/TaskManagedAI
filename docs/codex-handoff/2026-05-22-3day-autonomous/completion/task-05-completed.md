# task-05 完了報告 (2026-05-22)

## summary

- task: SP-0045 Tool Registry 本体
- start: 2026-05-22 JST
- end: 2026-05-23 JST
- 完了 BL / ticket: SP0045-T01 から SP0045-T05
- scope: Tool Registry TOML config、Pydantic loader、canonical enum、
  frontend enum source、DB hardening、`tool_versions`、ContextSnapshot
  `tool_manifest` binding、contract/adversarial tests、SP-0045 completed 化
- 累計 PR: #163 から #165 merged + batch D completion PR

## PR list

- #163:
  - merge SHA: `a6e7859f67fed8fcd15961801551bdaafa7867e1`
  - scope: Tool Registry loader + ADR/SP ready
  - Codex finding: baseline 0
- #164:
  - merge SHA: `64830e271b14f02b37fb2abe57ee0abc84874ecc`
  - scope: DB hardening + `tool_versions`
  - Codex finding: baseline 0
- #165:
  - merge SHA: `15b0bc67ec00cdb73d9db2602819510bb1fdc415`
  - scope: ContextSnapshot `tool_manifest` binding
  - Codex finding: baseline 0

## Codex finding 採否判定

- batch A / HIGH:
  - finding: raw TOML hash could drift on row ordering.
  - judgment: adopt. Canonical sorted allowlist hash.
- batch A / MEDIUM:
  - finding: duplicate `tool_key` could overwrite loader mapping.
  - judgment: adopt. Duplicate rejection.
- batch A / MEDIUM:
  - finding: experimental tools could carry non-public data.
  - judgment: adopt. Loader rejects above `public`.
- batch B / HIGH:
  - finding: seed trigger would miss SP-0045 columns.
  - judgment: adopt. Migration replaces trigger.
- batch B / HIGH:
  - finding: existing rows needed deterministic backfill.
  - judgment: adopt. Backfill before NOT NULL/CHECK.
- batch B / MEDIUM:
  - finding: `allowed_actions` in manifest was not DB-checkable.
  - judgment: adopt. Explicit JSONB + CHECK.
- batch C / HIGH:
  - finding: caller-supplied `tool_manifest` remained accepted.
  - judgment: adopt. Signature-level removal.
- batch C / HIGH:
  - finding: resume path passed manifest value through caller API.
  - judgment: adopt. Scoped prior snapshot lookup.
- batch C / HIGH:
  - finding: hash and manifest could inherit from different rows.
  - judgment: adopt. Same snapshot ID guard.
- batch D / HIGH:
  - finding: read-only tool actions lacked disjointness contract.
  - judgment: adopt. DB-free contract test.
- batch D / HIGH:
  - finding: mutating tool actions could enter TOML unnoticed locally.
  - judgment: adopt. Config disjointness test.

## defer / carry-over

- SP0045-DEFER-001: Live DB-backed Tool Registry and ContextSnapshot tests are
  skipped locally unless `TASKMANAGEDAI_RUN_DB_TESTS=1` is set with a reachable
  test PostgreSQL. In this worktree the default credentials fail auth.
- SP0045-DEFER-002: Full markdownlint cleanup for existing SP-0045 long lines
  remains docs drift work; new batch review/completion artifacts are clean.
- SP0045-DEFER-003: External MCP server trust-tier promotion path remains
  P0.1+ and requires a future ADR update.

## blocker

- No CRITICAL / HIGH / MEDIUM blocker remains for task-05.
- Hosted GitHub Actions still fail immediately due repository
  billing/spending infrastructure, matching prior batches; local verification
  plus Codex baseline review were used for admin bypass merge.

## verification (DoD checklist 結果)

- [x] `config/tool_registry.toml` validates and produces canonical manifest lock
- [x] `allowed_actions` / `trust_tier` / `max_outgoing_data_class` have
  backend Literal, loader, pytest, docs, migration, and frontend TS coverage
- [x] mutating action injection rejects at loader and DB CHECK levels
- [x] `tool_registry` DB hardening and `tool_versions` migration chain verified
- [x] ContextSnapshot `tool_manifest` is server-owned for normal snapshots
- [x] resume snapshots inherit hash/manifest from the same prior snapshot row
- [x] batch D contract tests clean (`10 passed`)
- [x] targeted ruff/mypy clean for changed Python tests
- [x] Tool Registry loader validate clean
- [x] new review/completion artifacts markdownlint clean
- [x] `git diff --check` clean
- [x] Sprint Pack frontmatter `status: ready -> completed` + Review 章追加
- [x] PR #163/#164/#165 `codex_pr_full_review.sh` baseline clean

## Claude verification 依頼項目

1. `allowed_actions` と policy `action_class` が今後も分離されるか verify。
2. `ContextSnapshot.tool_manifest` の server-owned lock が DD-03 の 10 列
   invariant と整合しているか verify。
3. SP-0045 Review 章が task-05 DoD と ADR-00027 の accepted boundary を
   十分に反映しているか verify。
