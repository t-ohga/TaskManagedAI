---
id: "SP-016_ui_cli_parity"
type: "heavy"
status: "draft"
sprint_no: 16
created_at: "2026-05-10"
updated_at: "2026-05-10"
target_days: 4
max_days: 6
adr_refs: []
planned_adr_refs:
  - "[ADR-00015](../adr/00015_ui_cli_parity.md) # SP-016 着手時に proposed → accepted (Criteria #3 + #7)"
  - "[ADR-00007 update](../adr/00007_external_exposure.md) # network boundary 拡張 (tag:taskhub-cli) (Criteria #7)"
related_sprints:
  - "SP-013_multi_agent_orchestration"
  - "SP-014_orchestrator_agent"
  - "SP-015_inter_agent_communication"
risks:
  - "PE-F-006 (CLI capability token を bearer token として扱うリスク)"
  - "PD-F-019 (memory parity を SP-018 まで defer する制約)"
  - "PE-F-014 (CLI token misuse の SecretBroker negative case)"
---

最終更新: 2026-05-10

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

- **principal-bound API capability token DDL** (PE-F-006): SecretBroker と同等 OperationContext binding (actor_id / principal_id / device_id / project_id / allowed_actions / audience / expires_at / jti / revoked_at)
- **CLI config に raw token を保存しない**: refresh credential のみ OS keyring / SOPS、operation token は API が短命 (5-30 分) 発行
- **CLI tool 名 = `tm`** (衝突確認後採用、衝突時 `tmai` fallback)
- **`tm memory` は 404/disabled contract test のみ** (SP-018 accepted まで)
- **Tailscale grants `tag:taskhub-cli`** を ADR-00007 update で追加

## 実装チケット

- SP016-T01: api_capability_tokens table + migration + DDL (PE-F-006)
- SP016-T02: backend `/api/v1/auth/cli-login` + token issue / refresh / revoke endpoint
- SP016-T03: cli/tm Python CLI (Click / Typer 等) + entry point `tm`
- SP016-T04: cli/tm/commands/{ticket,approval,run,message,audit,export,provider,sprint}.py
- SP016-T05: cli/tm/auth/capability_token.py + cli/tm/config/profile_loader.py (keyring / SOPS / env)
- SP016-T06: cli/tm/output/{json_formatter,yaml_formatter,human_formatter}.py + TTY 検知
- SP016-T07: parity contract test (13 capability すべてで UI 経路 vs CLI 経路で結果 + DB row + audit event 完全一致)
- SP016-T08: SecretBroker CLI token misuse negative test (PE-F-014 の 6 case のうち CLI 関連 1 つ + scope mismatch deny audit)
- SP016-T09: ADR-00015 + ADR-00007 update を proposed → accepted、`tag:taskhub-cli` Tailscale grants 設定
- SP016-T10: `docs/cli/README.md` (使い方、SP-016 完了で公開)

## タスク一覧

- [ ] SP016-T01-T10 を順次実装
- [ ] migration `00NN_p0_1_api_capability_tokens.py` + `alembic check` PASS
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

- api_capability_tokens DDL が SecretBroker 同等 invariant (actor/principal/device/project/scope/audience/expires/jti/revoked) を満たす
- CLI config の auth_method=plain が service layer で reject (DB level でなくとも 4 重防御の application layer で fail-closed)
- Tailscale grants `tag:taskhub-cli` が最小権限 (read-only API + write 必要 endpoint のみ)
- parity contract test の 13 capability が SP-013-015 で実装した backend と完全整合
- audit_events の `api_capability_token_*` 系 event_type が cross-source-enum-integrity §1 で同期

## 残リスク

- ChatGPT / Codex の OS keyring / SOPS auth_method の cross-platform 互換性 (macOS Keychain / Linux Secret Service / Windows Credential Manager の差異) → SP-022 で運用 review
- CLI tool 名 `tm` の長期 conflict (Homebrew / npm / pypi 等の package name 衝突) → SP-016 着手前に最終確認
- Tailscale grants `tag:taskhub-cli` を P1+ で device approval flow に統合する移行 cost

## 次スプリント候補

- SP-017 AI Society Visualization (board / role icon / dashboard)
- (P1) SP-018 hermes memory integration

## 関連 ADR

- ADR-00015 (UI ↔ CLI Parity Boundary) — proposed → accepted at SP-016 kickoff
- ADR-00007 update (network boundary 拡張)
- ADR-00014 / 00018 (関連)

## Review

(SP-016 完了時に追記)
