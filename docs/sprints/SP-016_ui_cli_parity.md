---
id: "SP-016_ui_cli_parity"
type: "heavy"
status: "ready"
sprint_no: 16
created_at: "2026-05-10"
updated_at: "2026-05-24"
target_days: 4
max_days: 6
adr_refs:
  - "[ADR-00015](../adr/00015_ui_cli_parity.md) # accepted 2026-05-24 at SP-016 kickoff blocker closure (Criteria #3 + #7)"
  - "[ADR-00007](../adr/00007_external_exposure.md) # accepted; `tag:taskhub-cli` listed as P0.1 grants minimum, config change remains separate external-exposure gate"
planned_adr_refs: []
related_sprints:
  - "SP-013_multi_agent_orchestration"
  - "SP-014_orchestrator_agent"
  - "SP-015_inter_agent_communication"
risks:
  - "PE-F-006 (CLI capability token を bearer token として扱うリスク)"
  - "PD-F-019 (memory parity を SP-018 まで defer する制約)"
  - "PE-F-014 (CLI token misuse の SecretBroker negative case)"
---

最終更新: 2026-05-24 (SP-016 kickoff blocker closure: ADR-00015 accepted、CLI canonical `tm` 確定、13 capability drift 解消、api_capability_tokens DDL / audit lifecycle 固定)

## 目的

`tm` CLI tool の P0.1 minimum capability (13 項目、memory 除外) を実装し、Web UI ↔ CLI parity を per-feature contract test で機械的に保証する。CLI は **principal-bound API capability token** で認証し、bearer token として扱わない (PE-F-006).

## 背景

- ユーザー vision「UI でできること = CLI でできること」を P0.1 で実現
- SP-013/014/015 で multi-agent backend が完成、本 Sprint で外部界面 (UI / CLI) parity を完成
- 既存 invariant (Tailscale-only / Funnel 不使用 / Approval 4 整合 + decider human-only / SecretBroker capability token TTL 5-30 分) すべて不変

## 対象外

- memory record/search (SP-018 accepted 後に feature flag で追加、PD-F-019)
- AI Society Visualization (board / role icon は SP-017)
- character image generation (SP-021)
- Sprint Pack list / Eval Dashboard write 系 (P1)

## 設計判断

- **principal-bound API capability token DDL** (PE-F-006): SecretBroker と同等 OperationContext binding (actor_id / principal_id / device_id / project_id / allowed_actions / scope_constraint / audience / auth_context_hash / request_binding_hash / expires_at / jti / revoked_at)
- **CLI config に raw token を保存しない**: refresh credential のみ OS keyring / SOPS、operation token は API が短命 (5-30 分) 発行
- **CLI tool 名 = `tm`** (2026-05-24 local/Homebrew conflict check clean、`tmai` は将来 namespace 衝突時の fallback のみ)
- **`tm memory` は 404/disabled contract test のみ** (SP-018 accepted まで)
- **Tailscale grants `tag:taskhub-cli`** は ADR-00007 に accepted 済み。実 config 変更が入る PR では外部公開設定 gate と rollback を別 diff で明示する

## 実装チケット

- SP016-T01: api_capability_tokens table + migration `0031_sp016_api_capability_tokens.py` + DDL (PE-F-006)
- SP016-T02: backend `/api/v1/auth/cli-login` + token issue / refresh / revoke endpoint
- SP016-T03: cli/tm Python CLI (Click / Typer 等) + entry point `tm`
- SP016-T04: cli/tm/commands/{ticket,approval,repo,pr,run,secret,provider,memory}.py (13 capability matrix only; `message` / `audit` / `export` は read-only helper として別 scope、`sprint` は taskhub host/admin scope)
- SP016-T05: cli/tm/auth/capability_token.py + cli/tm/config/profile_loader.py (keyring / SOPS / env)
- SP016-T06: cli/tm/output/{json_formatter,yaml_formatter,human_formatter}.py + TTY 検知
- SP016-T07: parity contract test (13 capability すべてで UI 経路 vs CLI 経路で結果 + DB row + audit event 完全一致)
- SP016-T08: SecretBroker CLI token misuse negative test (PE-F-014 の 6 case のうち CLI 関連 1 つ + scope mismatch deny audit)
- SP016-T09: ADR-00015 accepted / ADR-00007 accepted 前提の gate verification、`tag:taskhub-cli` Tailscale grants config diff は rollback 付きで分離
- SP016-T10: `docs/cli/README.md` (使い方、SP-016 完了で公開)

## タスク一覧

- [ ] SP016-T01-T10 を順次実装
- [ ] migration `0031_sp016_api_capability_tokens.py` + `alembic check` PASS
- [ ] 13 parity contract test 全件 PASS
- [ ] CLI capability token TTL 5-30 分 + scope minimum + raw 保存 reject
- [ ] secret redaction (CLI 出力に raw secret 出ない、SecretBroker 経由のみ)
- [ ] Tailscale-only enforcement (public IP / Funnel reject + backend_url *.ts.net 検証)
- [ ] `tm memory` は 404/disabled contract test PASS

## must_ship / defer_if_over_budget 対応表

| 項目 | must_ship | defer_if_over_budget |
|---|---|---|
| api_capability_tokens DDL + endpoint | ○ | - |
| `tm` CLI 13 capability + parity contract test | ○ | - |
| keyring / SOPS auth_method | ○ | env auth_method は plaintext で残るため SP-022 で再評価 |
| multi-profile config | ○ | - |
| `--json/--yaml/--quiet/TTY` 出力 | ○ | - |
| SecretBroker CLI token misuse negative | ○ | 6 case 全件は SP-014/015 と分担 |
| Tailscale grants `tag:taskhub-cli` | ○ | - |
| `tm memory` 404/disabled contract test | ○ | - |
| `docs/cli/README.md` | ○ | - |
| memory record/search command | × | SP-018 accepted 後に feature flag で追加 |
| Sprint Pack list / Eval Dashboard write | × | P1 |

## 受け入れ条件

- 13 capability すべてで UI 経路 vs CLI 経路の結果 + DB row + audit event 完全一致
- capability token: TTL 5-30 分上限、scope minimum default、profile config に raw 値保存不可、auth_method=plain は service layer reject
- jti replay 検知 (revoked_at NOT NULL → 全件 deny)
- mutating API call で scope mismatch → deny audit (`api_capability_token_scope_mismatch`)
- public IP / Funnel 経由の CLI access reject (Tailscale-only enforcement)
- secret 値が CLI 出力に出ない (SecretBroker 経由のみ)
- `tm memory record/search` 実行時に 404/disabled エラー + audit event

## 検証手順

```bash
uv run pytest tests/parity/test_ui_cli_parity.py \
              tests/cli/test_capability_token_lifecycle.py \
              tests/cli/test_multi_profile.py \
              tests/cli/test_output_formats.py \
              tests/cli/test_secret_redaction.py \
              tests/cli/test_tailscale_only.py \
              tests/cli/test_memory_disabled.py \
              tests/security/test_cli_token_misuse_negative.py \
              tests/security/test_api_capability_token_scope_mismatch.py -q

uv run alembic check && uv run alembic upgrade head

# CLI 自身の installation smoke
uv tool install ./cli && tm --version && tm --profile default ticket list --json
```

## レビュー観点

- api_capability_tokens DDL が SecretBroker 同等 invariant (actor/principal/device/project/scope/audience/auth_context/request_binding/expires/jti/revoked) を満たす
- CLI config の auth_method=plain が service layer で reject (DB level でなくとも 4 重防御の application layer で fail-closed)
- Tailscale grants `tag:taskhub-cli` が最小権限 (read-only API + write 必要 endpoint のみ)
- parity contract test の 13 capability が SP-013-015 で実装した backend と完全整合
- audit_events の `api_capability_token_*` 系 event_type (`issued` / `revoked` / `denied` / `scope_mismatch`) が cross-source-enum-integrity §1 で同期

## 残リスク

- ChatGPT / Codex の OS keyring / SOPS auth_method の cross-platform 互換性 (macOS Keychain / Linux Secret Service / Windows Credential Manager の差異) → SP-022 で運用 review
- CLI tool 名 `tm` の長期 conflict (Homebrew / npm / pypi 等の package name 衝突) → SP-016 着手前に最終確認
- Tailscale grants `tag:taskhub-cli` を P1+ で device approval flow に統合する移行 cost

## 次スプリント候補

- SP-017 AI Society Visualization (board / role icon / dashboard)
- (P1) SP-018 hermes memory integration

## 関連 ADR

- ADR-00015 (UI ↔ CLI Parity Boundary) — accepted 2026-05-24 at SP-016 kickoff blocker closure
- ADR-00007 (network boundary; `tag:taskhub-cli` config change remains external-exposure gate)
- ADR-00014 / 00018 (関連)

## Review

(SP-016 完了時に追記)

## Kickoff Inventory (2026-05-24 task-04 plan-only)

本 section は `docs/codex-handoff/2026-05-24-sequence-h-sp015-kickoff` task-04 の plan-only inventory。**CLI / backend / migration 実装は行わない**。

### SP-015 dependency status

- SP-015 batch 0a-0f は `task-03` で完了。message backend は `inter_agent_messages`、publisher/consumer、audit events、AgentRunEvent refs、SecretBroker token payload negative まで固定済み。
- SP-016 の message-related CLI parity は、SP-015 の `InterAgentPublishRequest` / `InterAgentConsumeRequest` / ref-only audit payload を前提に設計可能。
- SP-015 の raw payload boundary は CLI からも不変: CLI は message body を audit / AgentRunEvent に直接出さず、backend service の sanitizer / writer 経由に限定する。

### pre-implementation blockers

1. **ADR-00015 accepted**: 2026-05-24 に accepted 化済み。principal-bound API capability token DDL / lifecycle / audit event schema は ADR-00015 §3 / §7 を正本にする。
2. **CLI canonical resolved (U-04)**: `tm` 維持を採用。`tmai` は将来 namespace 衝突時の fallback のみ。
3. **13 capability matrix vs command module drift resolved**: A を採用。13 capability matrix にない `message` / `audit` / `export` は parity contract に含めない read-only helper scope、`sprint` は `taskhub` host/admin scope。
4. **api_capability_tokens migration plan fixed**: actor/principal/device/project/scope/audience/auth_context/request_binding/expires/jti/revoked の exact DDL、scope mismatch deny audit、jti replay deny は ADR-00015 §3 / §7 を正本にする。
5. **Tailscale `tag:taskhub-cli` grants gated**: ADR-00007 は accepted 済み。実 config 変更が入る場合は外部公開設定 gate として別 diff / rollback を明示する。

### carry-over to SP-016 implementation plan

- `tm memory` は SP-018 accepted まで 404/disabled contract のみ。message CLI と memory CLI を混ぜない。
- SP-015 の SecretBroker inter-agent token negative は完了済み。SP-016 では別途 CLI token misuse / scope mismatch / raw token profile 保存 reject を実装する。
- `taskhub` host/admin CLI と `tm` project-user CLI の境界を維持し、admin CLI から project mutating command を呼ばない。
- parity contract test は UI result / CLI result / DB row / audit event を 13 capability ごとに比較する。message/audit/export/sprint command は parity 13 件へ追加しない。

## QL-F update (R29 §5 QL-F、2026-05-15 doc-only、CLI ContextResolver + canonical 選択肢 spec)

本 section は QL-F Quality Loop run で R29 plan PARTIAL_ADOPT P-05 + P-06 を **future implementation gate spec として記録**する追記。**code/test/CLI 実装変更を一切行わない**。

### QL-F.1 詳細 spec は docs/cli/README.md に集約

QL-F run で新規起票し、2026-05-24 に accepted 化した `docs/cli/README.md` を本 Pack の CLI 設計 source-of-truth として cross-reference。本 Pack §設計判断 / §実装チケット で記載されている CLI 関連 spec は `docs/cli/README.md` の §2-§7 を参照。

### QL-F.2 13 capability matrix cross-reference

`docs/cli/README.md §4` の 13 capability matrix が本 Pack の must_ship 実装対象 (CLI 経由で expose する操作の網羅性):

| capability category | 該当 capability | 本 Pack must_ship 関連 |
|---|---|---|
| read-only | task_list / task_show / approval_list / repo_status / run_show | 全件 must_ship |
| task mutating | task_create / task_write | autonomy_level 経由で must_ship |
| approval | approval_decide (decider human-only) | autonomy_level 不問で human approval 必須、must_ship |
| repo mutating | repo_push / pr_open | L2/L3 で auto-allow path も、SecretBroker capability 内包 path は除外 (ADR-00025 §10.2) |
| secret / provider | secret_resolve / provider_call | 全 level で human approval 必須 (ADR-00025 §不変条件 #1) |
| run control | run_cancel | requester==operator なら approval 不要、それ以外 approval 必須 |

### QL-F.3 ContextResolver state machine cross-reference

`docs/cli/README.md §3` の 5 状態 (explicit_arg / env / cwd_git_remote / profile / interactive_or_fail) は本 Pack の CLI 起動時 project context 解決の正本 spec、本 Pack must_ship でも本 state machine を実装。

### QL-F.4 ADR-00024 placeholder (project auto-discovery memory boundary)

<!-- ADR-00024 placeholder: project auto-discovery + memory boundary は ADR-00024 (proposed、QL-G で起票予定) で扱う、本 SP-016 は ADR-00024 accepted 後に memory backend 関連の must_ship を追加 -->

本 placeholder は QL-G run で実 ADR 起票後、本 §設計判断 で memory backend 関連の must_ship を追加する future implementation gate。本 QL-F run では marker のみ。

### QL-F.5 taskhub host/admin vs tm project user 境界

`docs/cli/README.md §7` の 2 CLI 境界 (`taskhub` vs `tm`) は本 Pack の admin scope と project user scope の物理分離。本 Pack must_ship では:

- `tm` 経由の 13 capability (上記 §QL-F.2) のみ実装
- `taskhub` 経由の admin scope (`tenant_create` / `sprint_pack_admin_close` / `sops_rotate` 等) は本 Pack scope 外、別 SP-XXX で扱う

`taskhub` 経由で project mutating command を invoke する path は **restricted** (本 SP-016 must_ship 範囲外)。

### QL-F.6 同一 PR 一括更新 future requirement (future rename only)

U-04 は A (`tm` canonical 維持) で確定済み。将来 `tmai` 反転を採用する場合のみ、本 SP-016 + ADR-00015 + SP-012 + docs/cli/README.md + CLI test file を **同一 PR で doc-only 一括更新**。CLI test file 更新は反転実装 Sprint Pack accepted 後の別 run。

### QL-F.7 QL-D 教訓適用

`.claude/CLAUDE.md §6.5.0` (PR #14) の「doc-only future spec と code 品質追求は別軸」教訓を適用。本質目的 (docs/cli/README.md cross-reference + ADR-00024 placeholder + 同一 PR 一括更新 future requirement) は本 run の Phase 0 で達成済、R1-R3 軽い polish で merge ready 判断。
