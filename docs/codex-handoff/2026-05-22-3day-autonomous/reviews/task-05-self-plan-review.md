# task-05 Self-Plan-Review (SP-0045 Tool Registry)

Date: 2026-05-22 JST

## Scope

- task: SP-0045 Tool Registry 本体
- dependency status: task-01 batch 0d+ merged; `tool_registry` and
  `tool_network_policies` already exist from SP-014.
- implementation shape: extend the existing `tool_registry` table instead of
  creating a duplicate `tools` table.

## Round 1: structural review

### Planned batches

- batch A: accept ADR-00027 / ADR-00012, add canonical Tool Registry enums,
  `config/tool_registry.toml`, Pydantic schemas, TOML loader, and frontend enum
  source.
- batch B: add explicit DB columns for `allowed_actions`,
  `max_outgoing_data_class`, `registry_version`, and `tool_versions`; keep
  `tool_network_policies` as the network-specific extension table.
- batch C: add server-owned tool manifest lock builder and wire
  `ContextSnapshot.tool_manifest` to server-recomputed
  `(registry_version, allowlist_hash)`.
- batch D: add contract/adversarial tests, Sprint Pack completion review, and
  completion artifact.

### Structural decisions

- Existing `tool_registry` is the canonical tools table. A second `tools` table
  would create two sources of truth and break SP-014 network-policy foreign keys.
- `allowed_actions` belongs on `tool_registry`; `tool_network_policies` remains
  responsible only for domain allowlist and network payload maximums.
- `trust_tier` remains provenance only. Runtime data-class authorization uses
  `max_outgoing_data_class`, never `trust_tier`.
- Tool manifest hashing uses canonical JSON over a sorted allowlist projection,
  not raw TOML bytes, so equivalent table ordering cannot change hashes.
- The public ContextSnapshot column count stays fixed at 10; the lockfile tuple
  is stored inside the existing `tool_manifest` JSON object.

## Round 1 findings

- T05-PLAN-R1-F001 / HIGH / adopt:
  - finding: Creating a new `tools` table would split SP-014 network policies
    from SP-0045 registry ownership.
  - planned fix: Extend existing `tool_registry`; create only `tool_versions`
    as history.
- T05-PLAN-R1-F002 / HIGH / adopt:
  - finding: Existing ContextSnapshot repository still accepts caller-supplied
    `tool_manifest`.
  - planned fix: Batch C will replace public snapshot creation with a server
    recompute path and add signature tests.
- T05-PLAN-R1-F003 / MEDIUM / adopt:
  - finding: Existing `manifest->allowed_actions` JSON is not DB-checkable
    enough for 5+ source integrity.
  - planned fix: Batch B adds explicit `allowed_actions` JSONB + DB CHECK and
    backfills from manifest.

## Round 2: adversarial review

### Attack checks

- Mutating tool injection: TOML containing `repo_write`, `tool_write`, or
  `command_exec` must fail validation before DB/runtime.
- Trust-tier promotion: untrusted caller input must never select
  `trust_tier`; only the registry config/DB row can provide it.
- Data-class bypass: `official` must not permit confidential/PII by itself.
- Lockfile race: AgentRun snapshots must keep the manifest hash from run start
  even if registry config changes later.
- Network bypass: `network_access='internet'` stays representable but denied in
  P0 unless a later ADR changes policy.

## Round 2 findings

- T05-PLAN-R2-F001 / HIGH / adopt:
  - finding: Hashing raw TOML could let formatting or row order create false
    lockfile drift.
  - planned fix: Hash a canonical sorted allowlist projection.
- T05-PLAN-R2-F002 / HIGH / adopt:
  - finding: Allowing `experimental` with confidential or PII data-class output
    would silently weaken ADR-00027.
  - planned fix: Loader rejects experimental tools above `public`; future
    changes require ADR update.
- T05-PLAN-R2-F003 / MEDIUM / adopt:
  - finding: Existing network policy tests can pass while `allowed_actions`
    drifts from action_class separation.
  - planned fix: Add enum integrity tests comparing Python Literal, constants,
    TOML, docs, migration check, and frontend TS.
- T05-PLAN-R2-F004 / MEDIUM / adopt:
  - finding: A caller could try to smuggle `tool_manifest_hash` in request
    payload or artifacts.
  - planned fix: ContextSnapshot contract keeps required keys only and
    secret-scan still rejects prohibited payload keys.

## Readiness gate

- CRITICAL: 0
- HIGH: 0 open after planned adoption
- status: READY for batch A
