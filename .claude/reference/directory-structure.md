# Directory Structure

TaskManagedAI の想定ディレクトリ構成。  
backend / frontend / docs / config / migrations / eval を中心に、P0 の境界と成果物の置き場所を整理する。

## 1. Top Level

| path | 役割 |
|---|---|
| `backend/` | FastAPI、domain service、worker、ProviderAdapter |
| `frontend/` | Next.js 16 App Router UI |
| `config/` | Provider Matrix、policy、runtime config |
| `migrations/` | Alembic migration |
| `eval/` | Hard Gates / KPI / fixture / reports |
| `docs/` | PRD、DD、Sprint Pack、ADR、実装計画 |
| `.claude/` | Claude harness |
| `.codex/` | Codex mirror / hooks / agents |
| `scripts/` | repo-local helper scripts |
| `docker-compose.yml` | P0 local / VPS baseline |
| `pyproject.toml` | backend Python project |
| `package.json` | frontend scripts |
| `pnpm-lock.yaml` | frontend lockfile |
| `uv.lock` | backend lockfile |

## 2. Backend

```text
backend/
  app/
    main.py
    api/
    core/
    domain/
    services/
    repositories/
    providers/
    policy/
    secrets/
    runners/
    workers/
    audit/
    eval/
  tests/
    unit/
    contract/
    integration/
    db/
    provider/
    secrets/
    agentrun/
    runner/
```

| subdir | 役割 |
|---|---|
| `api/` | FastAPI routers / dependency |
| `core/` | settings、logging、tenant / actor context |
| `domain/` | domain model / enums / value objects |
| `services/` | application service |
| `repositories/` | DB access、tenant / project invariant |
| `providers/` | ProviderAdapter、Structured Outputs |
| `policy/` | Policy Engine、Approval |
| `secrets/` | SecretBroker、`secret_ref` |
| `runners/` | RunnerAdapter、sandbox |
| `workers/` | arq jobs |
| `audit/` | audit event helper |
| `eval/` | Eval integration |

## 3. Frontend

```text
frontend/
  app/
    tickets/
    approvals/
    agent-runs/
    audit/
    settings/
    eval/
  components/
  lib/
  hooks/
  styles/
  tests/
  playwright/
```

| path | 役割 |
|---|---|
| `app/tickets/` | Ticket list / detail |
| `app/approvals/` | Approval Inbox |
| `app/agent-runs/` | AgentRun trace |
| `app/audit/` | Audit Log |
| `app/settings/` | Project / provider / repo settings |
| `app/eval/` | Eval Dashboard |
| `components/` | UI component composition（採用 library は Sprint 9 ADR で確定。Phase 0 mapping §6 で shadcn/ui は除外明記） |
| `lib/api/` | API client |
| `lib/types/` | generated / shared types |
| `tests/` | Vitest |
| `playwright/` | E2E |

## 4. Config

```text
config/
  provider_compliance.toml
  policy/
    policy_pack.toml
  prompts/
    prompt_pack.toml
  tailscale/
    grants.example.json
  runner/
    forbidden_paths.toml
    dangerous_commands.toml
```

注意:

- `provider_compliance.toml` は Provider Matrix の機械判定正本。
- secret 値を config に置かない。
- `secret_ref` URI と metadata のみ扱う。
- Tailscale auth key は `secret_ref` で扱う。
- runner allowlist / denylist は AC-HARD-05 / AC-HARD-06 と同期する。

## 5. Migrations

```text
migrations/
  env.py
  script.py.mako
  versions/
    0001_initial.py
```

原則:

- DB schema 変更は ADR Gate。
- tenant / project invariant を migration で強制する。
- SecretBroker DDL は raw secret 保存禁止。
- AgentRun status enum は 16 状態に固定。
- ContextSnapshot 10 カラムを維持。
- rollback と negative test を同時に用意する。
- destructive migration は backup / restore 方針を Sprint Pack に書く。

## 6. Eval

```text
eval/
  security/
    policy_block/
    secret_canary/
    tenant_isolation/
    forbidden_path/
    dangerous_command/
    prompt_injection/
  ops/
    backup_restore/
  quality/
    acceptance/
    citation/
    cost/
  datasets/
    public_regression/
    private_holdout/
    adversarial_new/
  reports/
```

原則:

- `public_regression` は開発中に参照可。
- `private_holdout` は期待値を見て tuning しない。
- `adversarial_new` は月次 append-only。
- fixture ID と dataset version を保存する。
- Hard Gates と Quality KPIs を dashboard metric に接続する。

## 7. Docs

```text
docs/
  要件定義/
    00_プロダクト要求定義.md
    01_P0要求定義.md
  基本設計/
    00_全体アーキテクチャ.md
    02_データモデル.md
    03_AIオーケストレーション設計.md
    04_セキュリティ_権限_監査設計.md
    06_秘密管理設計.md
  実装計画/
    P0_バックログ.md
  sprints/
    _template_light.md
    _template_heavy.md
    SP-000_bootstrap.md
  adr/
    _template.md
    README.md
  設計検討/
    harness-phase0-mapping.md
```

## 8. Claude Harness

```text
.claude/
  CLAUDE.md
  rules/
  reference/
  agents/
  hooks/
  skills/
```

| path | 役割 |
|---|---|
| `rules/` | 常時制約 |
| `reference/` | 詳細参照 |
| `agents/` | Claude subagent |
| `hooks/` | Claude hooks |
| `skills/` | Claude skills / suites |

## 9. Codex Mirror

```text
.codex/
  config.toml
  hooks.json
  agents/
```

注意:

- Claude-only field を持ち込まない。
- AskUserQuestion 前提を持ち込まない。
- `$CLAUDE_PROJECT_DIR` を持ち込まない。
- hook は実 shell command として動くこと。
- Codex からさらに Codex chain を起動しない。

## 10. Boundary Placement

| invariant | 置き場所 |
|---|---|
| `payload_data_class` | artifact metadata / provider request |
| `allowed_data_class` | `config/provider_compliance.toml` |
| data class ordinal | provider compliance module |
| `tool_mutating_gateway_stub` | backend tool registry |
| `runner_mutation_gateway` | backend runners |
| AgentRun 16 状態 | backend domain / DB / frontend type |
| ContextSnapshot 10 カラム | DB / backend domain |
| atomic claim | backend secrets / migration |
| tenant / project invariant | migrations / repositories |
| Hard Gates | eval / tests / release suite |

## 11. Naming

- Python module は `snake_case`。
- TypeScript file は existing frontend convention に合わせる。
- DB table は `snake_case` plural。
- enum は docs の文字列と一致させる。
- ADR は `ADR-NNNNN`。
- Sprint Pack は `SP-000_<feature-name>`。
- fixture は dataset version と case key を持つ。
- secret は logical name のみ。実 secret 値を名前に含めない。

## 12. Review Checklist

- [ ] 新規 file は directory structure と責務が一致する。
- [ ] secret / provider / runner / DB 変更は正しい boundary に置かれている。
- [ ] `config/provider_compliance.toml` と reference が同期する。
- [ ] migration と DB contract test が同期する。
- [ ] eval fixture が public / private / adversarial に分離されている。
- [ ] Codex mirror に Claude-only 前提がない。

