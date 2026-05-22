# task-01 batch 0d 完了報告 (2026-05-22)

## summary

- task: SP-014 batch 0d Tool Registry network enum + tool_network_policies + ADR-00030 (SP014-T05)
- start: 2026-05-23 00:45 JST
- end: 2026-05-23 01:30 JST (~0.75h)
- 完了 BL / ticket: SP014-T05 batch 0d slice
- 累計 PR: pending at report creation

## PR list

| PR | merge SHA | scope | Codex finding |
|---|---|---|---|
| pending | pending | tool_registry network enum + tool_network_policies + web_fetch/docs_search deny-only seed + ADR-00030 | Self-Plan HIGH x4 + MEDIUM x4 adopted; Self-Impl HIGH x2 + MEDIUM x2 adopted |

## Codex finding 採否判定

| PR | finding | severity | judgment | follow-up PR |
|---|---|---|---|---|
| pending | ADR-00021 path collision with existing host portable deployment ADR. | HIGH | adopt: create ADR-00030 instead | included |
| pending | tool_registry was only documented, not migrated. | HIGH | adopt: create table with enum directly | included |
| pending | internet enum could become implicit allow. | HIGH | adopt: service guard deny + test | included |
| pending | web_fetch/docs_search seed could be mistaken as allow. | MEDIUM | adopt: deny-only manifest + service deny test | included |
| pending | allowlist could overmatch domain or leak payload class. | MEDIUM | adopt: exact domain + payload/provider negative tests | included |

## defer / carry-over

- SP014-B0D-DEFER-001: Full Tool Registry loader / `config/tool_registry.toml` / frontend UI remains SP-0045 task-05 scope.
- SP014-B0D-DEFER-002: `uv run alembic check` is expected to remain blocked by existing `migrations/env.py target_metadata` infrastructure debt.

## blocker

- No CRITICAL / HIGH blocker remains for batch 0d PR after local verification completes.

## verification (DoD checklist 結果)

- [x] ruff check + mypy backend clean
- [x] pytest `tests/services/tool_registry/test_network_policy.py` PASS (`7 passed`)
- [x] pytest `tests/services/tool_registry/test_network_policy.py tests/policy/test_policy_profile_seed.py` PASS (`15 passed`)
- [x] pytest `tests/db/test_repository_layer.py tests/db/test_schema_introspection.py tests/test_seeds.py` PASS (`37 passed`)
- [x] pytest `tests/multi_agent/` PASS (`47 passed`)
- [x] pytest `tests/runtime/test_agent_run_events.py tests/runtime/test_agentrun_transitions.py` PASS (`51 passed`)
- [x] migration downgrade -1 + upgrade head
- [ ] codex_pr_full_review.sh baseline 確認 + finding 採否判定 (PR 起票後)

## Claude verification 依頼項目

1. ADR-00030 と ADR-00027 の責務分離が妥当か verify。
2. `network_access='internet'` を enum に残しつつ P0 service guard deny にする判断が妥当か verify。
3. allowlist exact-domain / payload_data_class_max / provider_required の 3 条件が Tool Registry network boundary として十分か verify。
4. web_fetch/docs_search deny-only seed が action_class 7 種不変と整合するか verify。
