# task-03 完了報告 (2026-05-22)

## summary

- task: SP-022-1 scripts hardening + Layer C SOP polish
- start: 2026-05-22 JST
- end: 2026-05-23 JST
- 完了 BL / ticket: BL-SWH-001 から BL-SWH-007
- scope: backup pg_dump flag cleanup、backup source allowlist helper、
  docker compose healthcheck timing、optional SOPS env skip、stale destructive
  lock cleanup、alembic wrapper、Mac smoke SOP §13 grep coverage、Layer C
  operator runbook
- 累計 PR: #159 から #161 merged + batch 4 completion PR

## PR list

- #159
  - merge SHA: `1303eb7aedeb30f5852e619a89ce16eb19067c41`
  - scope: pg_dump flag / allowlist helper / healthcheck timing
  - Codex finding: baseline 0
- #160
  - merge SHA: `693e8248d7a1e63694b05fd801c6063875e0c0c1`
  - scope: optional SOPS skip / stale destructive lock cleanup
  - Codex finding: baseline 0
- #161
  - merge SHA: `b879fea2937d53aaf847e73ed16334f6dc7b3d29`
  - scope: alembic wrapper / SOP §13 / Layer C runbook
  - Codex finding: baseline 0

## Codex finding 採否判定

- batch 1 / HIGH / #159:
  - finding: `pg_dump --format=custom` still used `--single-transaction`
    in host and compose paths.
  - judgment: adopt. Removed from both paths and tested argv absence.
- batch 1 / MEDIUM / #159:
  - finding: backup source path allowlist was duplicated as local variables.
  - judgment: adopt. Extracted helper and asserted repo_root, `/etc`, and
    `/var/lib` roots in tests.
- batch 1 / MEDIUM / #159:
  - finding: Mac startup healthchecks were too brittle.
  - judgment: adopt. Adjusted retry/start timing without changing commands.
- batch 2 / HIGH / #160:
  - finding: missing `.env.encrypted` with `--include-sops-env` could block
    plaintext-skip drill path.
  - judgment: adopt. Absent file now fingerprints/archives as explicit
    `backup_sops_env_skipped`.
- batch 2 / HIGH / #160:
  - finding: missing verified SOPS copy could hide a Phase 5 binding bug.
  - judgment: adopt. Skip requires `sops_env_missing_at_lock=True`;
    otherwise fail-closed remains.
- batch 2 / HIGH / #160:
  - finding: stale lock cleanup could remove active locks if based only on
    age/pid.
  - judgment: adopt. Cleanup also requires non-blocking flock acquisition.
- batch 3 / HIGH / #161:
  - finding: Alembic wrapper must strip both host and container DB URL
    overrides.
  - judgment: adopt. Wrapper uses `env -u` on both sides and dry-run test
    asserts no secret DSN output.
- batch 3 / MEDIUM / #161:
  - finding: SOP §13 grep coverage missed SSH/network diagnostics.
  - judgment: adopt. Added §13.1-§13.6 with failure/pass/SSH grep patterns.

## defer / carry-over

- SP022-1-DEFER-001: Phase 7b Mac→VPS migration drill execution remains a
  separate user/operator-timed activity.
- SP022-1-DEFER-002: Full markdownlint cleanup for
  `docs/deploy/mac-single-host-smoke-sop.md` is deferred because the file has
  broad pre-existing style debt.
- SP022-1-DEFER-003: Broad scripts ruff/mypy debt outside changed files remains
  deferred to infrastructure/docs drift or follow-up hardening work.

## blocker

- No CRITICAL / HIGH / MEDIUM blocker remains for task-03.
- Hosted GitHub Actions still fail immediately due repository billing/spending
  infrastructure, matching prior batches; local verification + Codex baseline
  were used for admin bypass merge.

## verification (DoD checklist 結果)

- [x] targeted backup orchestrator tests clean (`56 passed` in batch 1)
- [x] targeted SOPS/destructive-lock tests clean (`69 passed` in batch 2)
- [x] related scripts regression suite clean (`74 passed` in batch 3)
- [x] targeted ruff/mypy clean for changed Python files/tests
- [x] `bash -n scripts/alembic_wrapper.sh` clean
- [x] `bash scripts/alembic_wrapper.sh --dry-run upgrade head` clean
- [x] docker compose config check clean with temporary dummy `.env.local`
- [x] new-doc markdownlint clean for Layer C runbook and batch 3 review artifact
- [x] `git diff --check` clean for each implementation batch
- [x] Sprint Pack frontmatter `status: ready → completed` + Review 章追加
- [x] PR #159/#160/#161 `codex_pr_full_review.sh` baseline clean

## Claude verification 依頼項目

1. `scripts/alembic_wrapper.sh` が Phase 7a deviation 3 の host env
   overlay 問題を十分に閉じているか verify。
2. `backup_sops_env_skipped` が plaintext secret inclusion ではなく
   optional encrypted env absence として扱われているか verify。
3. stale destructive lock cleanup が active lock / active pid /
   ambiguous payload を消さないことを verify。
4. `docs/deploy/layer-c-operator-runbook.md` §1-§9 が task-03 handoff の
   要求粒度に足りるか verify。
