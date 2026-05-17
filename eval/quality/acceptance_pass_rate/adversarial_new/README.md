# AC-KPI-01 adversarial new

This split is intentionally empty in the public repository and grows by
**append-only monthly refresh** (Sprint 11 / SP-022).

Counter-defense fixtures planned for this split:

- "100% deferred → metric_value=None / threshold_met=False" (defends the
  satisfied / (satisfied + rejected) denominator chosen in batch 5f plan
  v2 §2.2 against a "flip-failed-to-deferred" Anti-Gaming attack)
- "all status=pending → no_evaluated_criteria" (defends against the same
  pattern via the no-opinion path)
- "satisfied >> rejected + closure violation" (defends the partition
  invariant in plan v2 §6 #10 — verifies that
  `total = satisfied + rejected + pending + deferred`)
- "cross-fixture criterion_id duplicate" (defends the corpus-wide
  cross-fixture seen-set commit gate in plan v2 §6 #1)

`expected_count: 0` in `manifest.json` enforces emptiness via the generic
loader's split-count check until SP-022 fixture seeding lifts the gate.
