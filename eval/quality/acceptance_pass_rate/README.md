# AC-KPI-01 acceptance_pass_rate

This dataset skeleton defines the AC-KPI-01 `acceptance_pass_rate` quality KPI.

## Metric definition

```
acceptance_pass_rate = count(status = "satisfied") /
                       count(status in {"satisfied", "rejected"})
```

with `pending` and `deferred` **excluded** from both numerator and denominator
(see batch 5f plan v2 §2.2 for the full rationale and candidate comparison).

| status | DB definition | numerator | denominator | rationale |
|---|---|---|---|---|
| `satisfied` | AC met | ✓ | ✓ | counted |
| `rejected` | AC unmet | — | ✓ | counted as fail |
| `pending` | not yet evaluated | — | — | no opinion |
| `deferred` | explicit out-of-scope | — | — | matches `defer_if_over_budget` pattern |

## Anti-Gaming rules

- The aggregator **always recomputes** the metric from
  `input.sample_acceptance_criteria`; the fixture's declared
  `expected_aggregate.acceptance_pass_rate` is consumed as a drift-detection
  oracle only.
- Unknown status values reject as `spec_violation:status` to prevent enum-drift
  bypass (5+ source enum integrity per `.claude/rules/cross-source-enum-integrity.md`).
- Keep fixture hashes immutable through `manifest.json`.
- Keep private holdout and adversarial expectations out of implementation,
  prompt, and policy tuning.
- The `adversarial_new` split will be appended monthly (SP-022) with
  counter-defense fixtures against the "flip-to-deferred" attack
  (plan v2 §2.2.2).

## Threshold

`acceptance_pass_rate >= 0.6` (PRD-00-KPI-1).

## Related Sprint / PRD references

- PRD-00-KPI-1 (`docs/要件定義/00_プロダクト要求定義.md` line 139)
- SP-011 Pack BL-0124 (`docs/sprints/SP-011_eval_harness.md` line 138)
- SP-011 受け入れ条件 line 186 (AC-KPI 5 件すべて aggregator 経由)
- batch 5f plan v2 (`.claude/jobs/<job-id>/batch5f-plan.md`)
