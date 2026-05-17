# AC-KPI-02 adversarial new

This split is intentionally empty in the public repository and grows by **append-only monthly refresh** (SP-022).

Counter-defense fixtures planned for this split:

- `merged_at == ticket_created_at + 1ms` boundary (defends defense #12 causality check)
- `merged_at` exactly equal to `ticket_created_at` (boundary valid per plan v2 §2.1 / MED-003)
- 100% `merged` with all `duration=0` (informational warn only, plan v2 §7.10)
- >50% `closed_without_merge` ratio (informational warn only, plan v2 §7.10)
- cross-fixture duplicate `(ticket_id, repository_id)` (defends defense #1 corpus-wide uniqueness)
- non-UTC offset normalized to UTC (defends defense MED-001 timestamp contract)
- naive datetime reject (defends defense MED-001 timestamp contract)

`expected_count: 0` in `manifest.json` enforces emptiness until SP-022 fixture seeding lifts the gate.
