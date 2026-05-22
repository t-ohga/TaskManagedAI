# task-06 完了報告 (2026-05-22)

## summary

- task: ADR/Sprint Pack frontmatter drift fix
- start: 2026-05-22 JST
- end: 2026-05-22 JST
- scope: ADR lifecycle inventory、Sprint Pack `completed_at` 補完、
  `adr_refs` / `planned_adr_refs` 整合、Wave 13 amendment 実在確認、
  self-review artifact 起票
- code change: none

## completed changes

- completed Sprint Pack の `completed_at` 欠落を補完。
- accepted 済み ADR が `planned_adr_refs` に残っていた Sprint Pack を修正。
- `planned_adr_refs` に残すべき future / proposed ADR は維持。
- Wave 13 amendment files は current tree に存在しないことを確認し、
  retroactive promotion 対象なしとして記録。

## Codex finding 採否判定

- HIGH:
  - finding: completed Sprint Pack に `completed_at` がなく、完了順序と
    handoff invariant が曖昧だった。
  - judgment: adopt. 欠落分を frontmatter に追加。
- HIGH:
  - finding: accepted ADR が `planned_adr_refs` に残り、ADR Gate §12 の
    normal-flow と frontmatter が drift していた。
  - judgment: adopt. accepted ADR を `adr_refs` へ移送。
- MEDIUM:
  - finding: proposed ADR の一部は task brief で accepted 化候補だったが、
    current tree では acceptance prerequisites が満たされていない。
  - judgment: defer. `proposed` を維持。
- MEDIUM:
  - finding: Wave 13 amendment 2 件は task brief にあるが、実ファイルがない。
  - judgment: defer. 実在しないファイルの promotion は行わない。
- MEDIUM:
  - finding: Sprint Pack 本文中に歴史的な proposed-state 記述が残る。
  - judgment: defer. task-08 Documentation drift fix で本文 drift として扱う。

## defer / carry-over

- T06-DEFER-001: ADR-00013 / ADR-00015 / ADR-00016 / ADR-00017 /
  ADR-00018 / ADR-00023 / ADR-00024 / ADR-00025 は promotion 条件未充足
  または future sprint 所有のため proposed 維持。
- T06-DEFER-002: `docs/adr/wave-13-amendment-*.md` は存在せず、Wave 13
  amendment promotion は実施不可。
- T06-DEFER-003: Sprint Pack 本文の historical wording drift は task-08
  Documentation drift fix へ送る。

## blocker

- No CRITICAL / HIGH / MEDIUM blocker remains for task-06 frontmatter scope.
- Hosted GitHub Actions は repo billing/spending infrastructure の既知問題により
  引き続き不安定な前提。docs-only のため local verification と Codex baseline
  review を merge 判断に使う。

## verification

- [x] ADR status inventory reviewed
- [x] completed Sprint Pack `completed_at` presence check clean
- [x] accepted ADR frontmatter references moved from `planned_adr_refs`
      to `adr_refs` where applicable
- [x] proposed / future ADRs left in `planned_adr_refs` where applicable
- [x] Wave 13 amendment absence confirmed
- [x] `git diff --check` clean
- [x] new review/completion artifacts markdownlint clean

## Claude verification 依頼項目

1. task-08 で Sprint Pack 本文の historical proposed-state wording を精査。
2. proposed 維持 ADR の acceptance prerequisites が future sprint kickoff 時に
   再評価されるか確認。
3. Wave 13 amendment の正本が別 branch / archived artifact にある場合は、
   dedicated docs drift PR で復旧可否を判断。
