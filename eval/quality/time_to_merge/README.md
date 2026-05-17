# AC-KPI-02 time_to_merge

This dataset skeleton defines the AC-KPI-02 `time_to_merge` quality KPI.

## Metric definition

```
duration_hours[i] = (merged_at[i] - ticket_created_at[i]) / 3_600_000ms_per_hour
metric_value      = median(duration_hours[i] over status="merged" only)
```

with the strict causality invariant that `merged_at >= ticket_created_at` (boundary equality is valid).

| status | counted in median? | rationale |
|---|---|---|
| `merged` | ✓ | terminal merge event; duration = merged_at - ticket_created_at |
| `open` | — | not yet merged, no opinion |
| `draft` | — | not ready for merge |
| `closed_without_merge` | — | rejected, not a merge time observation |

## Anti-Gaming rules

- The aggregator **always recomputes** the median from
  `input.sample_pull_requests`; the fixture's declared
  `expected_aggregate.median_hours` is consumed as a drift-detection
  oracle only.
- Unknown status values reject as `spec_violation:status`.
- Causality violation (`merged_at < ticket_created_at`) rejects at parse
  time as `spec_violation:merged_at_causality` (no `max(0, …)` clamping
  — single source of truth, plan v2 §2.1).
- Corpus-wide uniqueness key: `(ticket_id, repository_id)` — a single
  ticket may have multiple PR events on different repositories
  (Draft re-open / squash flows).
- The `adversarial_new` split will be appended monthly (SP-022) with
  counter-defense fixtures against causality bypass, all-zero-duration,
  and >50% closed_without_merge attacks.

## Mock-only contract

The aggregator does NOT pull from a live `tickets` table or any mock-merge-events
table. Fixtures are the canonical source for this Sprint. SP-012 P0
Acceptance Test wires the live source.

## Threshold

`time_to_merge median_hours <= 2.0 hours` (PRD-01 AC-KPI-02 line 341).

## Related Sprint / PRD references

- PRD-01 AC-KPI-02 (`docs/要件定義/01_P0要求定義.md` line 341)
- SP-011 Pack 受け入れ条件 line 186 (AC-KPI 5 件すべて aggregator 経由)
- batch 5g plan v2 (`.claude/jobs/<job-id>/batch5g-plan.md`)
