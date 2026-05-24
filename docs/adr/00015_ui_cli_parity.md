---
id: "ADR-00015"
title: "UI ↔ CLI Parity Boundary: 共通 FastAPI backend + 13 capability matrix + Tailscale-only + principal-bound API capability token (TTL 5-30 分) + multi-profile config + parity contract test"
status: "accepted"
date: "2026-05-10"
updated_at: "2026-05-24"
authors:
  - "t-ohga"
related_sprints:
  - "SP-016_ui_cli_parity"
related_research:
  - "docs/設計検討/phase-c-multi-agent-spec-draft.md §C-4 + §11.3 PE-F-006"
acceptance_history:
  - "2026-05-10: proposed (Phase E PE-F-006 反映、SP-016 planned ADR として起票)"
  - "2026-05-24: accepted at SP-016 kickoff blocker closure (ADR-00014 accepted、P0 Exit / Sprint 9 Web UI foundation 完了済み、CLI canonical `tm` local/Homebrew conflict check clean)"
---

最終更新: 2026-05-24 (SP-016 kickoff blocker closure: accepted 化、CLI canonical `tm` 確定、13 capability drift と api_capability_tokens DDL / audit lifecycle を固定)

## 背景

- 決定対象: TaskManagedAI の **「UI ↔ CLI parity = どっちでやっても変わらない動き」** を実装するため、(1) CLI tool 名候補 (`tm`)、(2) 13 capability matrix (memory 除外、PD-F-019 fix)、(3) **principal-bound API capability token DDL** (PE-F-006 fix)、(4) multi-profile config、(5) parity contract test を固定.
- 前提: ADR-00007 (Tailscale-only, Funnel 不使用) / DD-05 / SecretBroker capability token TTL 5-30 分 / Approval 4 整合.
- ADR Gate Criteria #3 (API 契約) + #7 (外部公開) 該当.

## 採用案

### §1: CLI tool 名 = `tm` (SP-016 kickoff で確定)

2026-05-24 SP-016 kickoff blocker closure で **`tm` を canonical** として採用する。

採用時の衝突確認:

- `which -a tm` → `tm not found`
- `ls /usr/local/bin /opt/homebrew/bin | grep -E '^tm$'` → hit なし
- `brew search '/^tm$/'` → formula / cask hit なし

`tmai` は将来 package namespace 衝突または配布 channel 側の予約問題が発生した場合の fallback 名として残すが、SP-016 実装対象ではない。既存 docs / tests / examples は `tm` 表記に統一する。

### §2: 13 capability matrix (memory 除外、PD-F-019 fix)

ADR-00014 §11.4 + Phase C §4.3 参照。memory record/search は SP-018 accepted 後に feature flag で追加。SP-016 では `tm memory` の 404/disabled contract test のみ. SP-020 で追加する `tm memory insights` は read-only non-parity helper とし、`ALL_CAPABILITIES` の 13 行には含めない。

`memory insights` / `message` / `audit` / `export` command は 13 capability parity matrix に含めない。実装する場合でも read-only helper として扱い、UI ↔ CLI parity contract の 13 件には数えない。`sprint` command は `taskhub` host/admin CLI scope に属し、project-user CLI (`tm`) からは expose しない。

### §3: principal-bound API capability token DDL (PE-F-006 fix、CRITICAL strengthening)

CLI 用 token を **bearer token として扱わず**、SecretBroker と同等の OperationContext binding:

```sql
create table api_capability_tokens (
    id uuid primary key default gen_random_uuid(),
    tenant_id bigint not null default 1 references tenants(id),
    project_id uuid,                                       -- NULL = tenant-wide read-only only
    token_hash text not null,                              -- raw token は保存しない
    actor_id uuid not null,
    principal_id uuid not null,                            -- session/principal binding
    device_id text,                                        -- CLI client device 識別
    allowed_actions jsonb not null,                        -- non-empty string array
    scope_constraint jsonb not null default '{}'::jsonb,    -- project / repo / command binding
    audience text not null check (audience = 'taskmanagedai-api'),
    auth_context_hash text not null,                       -- keyring/SOPS/env profile binding hash
    request_binding_hash text not null,                    -- OperationContext fingerprint
    status text not null check (status in ('issued','expired','revoked')),
    issued_at timestamptz not null default now(),
    expires_at timestamptz not null,                       -- TTL 5-30 分
    jti text not null,                                     -- JWT-style unique id (replay 検知)
    revoked_at timestamptz,
    last_used_at timestamptz,
    metadata jsonb not null default '{"rls_ready": true}'::jsonb,
    check (token_hash ~ '^[a-f0-9]{64}$'),
    check (auth_context_hash ~ '^[a-f0-9]{64}$'),
    check (request_binding_hash ~ '^[a-f0-9]{64}$'),
    check (jsonb_typeof(allowed_actions) = 'array' and jsonb_array_length(allowed_actions) > 0),
    check (not jsonb_path_exists(allowed_actions, '$[*] ? (@.type() != "string")'::jsonpath)),
    check (jsonb_typeof(scope_constraint) = 'object'),
    check (jsonb_typeof(metadata) = 'object'),
    check (expires_at >= issued_at + interval '5 minutes' and expires_at <= issued_at + interval '30 minutes'),
    check ((status = 'revoked') = (revoked_at is not null)),
    foreign key (tenant_id, actor_id) references actors(tenant_id, id),
    foreign key (tenant_id, actor_id, principal_id) references principals(tenant_id, actor_id, id),
    foreign key (tenant_id, project_id) references projects(tenant_id, id),
    unique (tenant_id, id),
    unique (tenant_id, token_hash),
    unique (tenant_id, jti)
);

create index ix_api_capability_tokens_active
    on api_capability_tokens (tenant_id, actor_id, status, expires_at);

create index ix_api_capability_tokens_project
    on api_capability_tokens (tenant_id, project_id, status, expires_at)
    where project_id is not null;
```

Service layer は `principals.principal_type = 'capability_token'` を必須確認する。raw token / refresh credential / auth secret は `api_capability_tokens`、audit payload、AgentRunEvent payload、CLI profile のいずれにも保存しない。

### §4: 認証境界 (Tailscale-only)

| 経路 | profile config 保存 | API 経由 |
|---|---|---|
| Web UI → FastAPI (HTTPS over Tailscale) | session token (cookie、12h) | (cookie 直接) |
| `tm` CLI → FastAPI (HTTPS over Tailscale) | **refresh credential のみ** (OS keyring / SOPS) | login で session establish → operation ごとに 5-30 分短命 token を取得 |
| CLI → FastAPI (local Unix socket、optional) | local socket peer credential | (socket 直接) |
| secret_access (CLI 経由含む) | (常に SecretBroker 経由) | SecretBroker atomic claim で別 token (既存 invariant) |

**禁止 (PE-F-006 strict)**:
- profiles.toml に capability_token raw 保存 (refresh credential も `auth_method=plain` は service layer reject)
- public IP / Funnel / Cloudflare 経由の CLI access (ADR-00007 / DD-05 維持)

### §5: multi-profile config

`~/.config/taskmanagedai/profiles.toml`:

```toml
[default]
backend_url = "https://taskhub.tail-xxxxx.ts.net"
actor_id = "user-1"
auth_method = "keyring"                        # keyring (default) / sops / env
scope_default = "ticket:rw,run:rw,approval:r"  # operation token 取得時の最大 scope

[work]
# 同様に refresh credential のみ
```

切替: `tm --profile work ticket list`. 環境変数: `TM_PROFILE=work`.

### §6: parity 検証 contract test

`tests/parity/test_ui_cli_parity.py` で 13 capability すべてを per-feature contract test (UI 経路 vs CLI 経路で結果 + DB row + audit event 完全一致).

### §7: scope policy decision 連動 (PE-F-006 strengthening)

mutating API call (Tier 2/3) では:
- capability token の `allowed_actions` と request の `action_class` を照合
- policy decision / approval target fingerprint と照合 (Approval 4 整合)
- scope mismatch は deny audit (`api_capability_token_scope_mismatch`)
- revoked / expired / replayed `jti` は deny audit (`api_capability_token_denied` with reason_code `revoked` / `expired` / `jti_replay`)
- issue / revoke / deny / scope mismatch は ref-only audit payload に限定し、raw token / raw request body / profile credential を含めない

### §8: 実装 Sprint と対象ファイル

- SP-016 (target 4/max 6 days)
- 実装対象: `cli/tm/main.py` / `cli/tm/commands/*.py` / `cli/tm/config/profile_loader.py` / `cli/tm/auth/capability_token.py` / `cli/tm/output/*.py` / `backend/app/db/models/api_capability_token.py` / `migrations/versions/0031_sp016_api_capability_tokens.py` / `tests/parity/test_ui_cli_parity.py` / `tests/cli/*` / `docs/cli/README.md`

### §9: テスト指針

- 13 parity contract (UI vs CLI 結果一致)
- capability token lifecycle (TTL / scope / actor binding / revocation)
- multi-profile (3 profile + env override + keyring/SOPS)
- 出力形式 (--json/--yaml/--quiet/TTY 検知)
- secret redaction (CLI 出力に raw secret 出ない、SecretBroker 経由のみ)
- Tailscale-only (public IP / Funnel reject)
- scope mismatch deny + audit

## リスク

| リスク | 軽減 |
|---|---|
| `tm` 名衝突 | Sprint 16 着手前に衝突確認、`tmai` fallback |
| capability token leak | OS keyring / SOPS 必須 + auth_method=plain reject + jti replay 検知 + revocation |
| parity drift | capability 追加時に CLI command + contract test を Sprint Pack DoD に明記 (CI fail enforcement) |
| scope 過剰 | TTL 5-30 分 + scope minimum default + tenant_config |
| public IP 経由 access | Tailscale grants `tag:taskhub-cli` 拡張 + UFW + backend_url *.ts.net 検証 |

## rollback

1. CLI 全停止: profiles.toml 移動
2. capability token 全 revoke
3. API path block (`/api/v1/auth/cli-login` 503)
4. UI 単独継続
5. migration rollback: `alembic downgrade -1`

## 関連

- ADR-00014 / ADR-00007 update / Phase C §C-4 / §11.3 PE-F-006

## QL-F update (R29 §5 QL-F、2026-05-15 doc-only、CLI ContextResolver + canonical 選択肢 spec)

本 section は QL-F Quality Loop run で R29 plan PARTIAL_ADOPT P-05 (CLI canonical `tm`→`tmai` 反転) + P-06 (ContextResolver state machine) を **future implementation gate spec として記録**した追記。2026-05-24 SP-016 kickoff blocker closure で U-04 は **A: `tm` canonical 維持**を採用済み。

### QL-F.1 詳細 spec は docs/cli/README.md に集約

QL-F run で新規起票した `docs/cli/README.md` に CLI canonical `tm` + ContextResolver state machine + 13 capability matrix + mode matrix + fail-closed acceptance + taskhub 境界を集約。

### QL-F.2 同一 PR 一括更新の future requirement (U-04 decision)

U-04 は A (`tm` canonical 維持) で確定したため、本 ADR-00015 + SP-016 + docs/cli/README.md の doc-only 同期で完了。将来 `tmai` へ反転する場合のみ、ADR-00015 + SP-016 + SP-012 + docs/cli/README.md + CLI test file を同一 PR で一括更新する。

### QL-F.3 ADR-00024 placeholder 関係

ADR-00024 (project auto-discovery + memory boundary、proposed、QL-G で起票予定) との cross-reference: SP-016 に `<!-- ADR-00024 placeholder -->` marker のみ、実 ADR 起票は QL-G run。

### QL-F.4 QL-D 教訓適用

`.claude/CLAUDE.md §6.5.0` (PR #14) の「doc-only future spec と code 品質追求は別軸」教訓を適用。本質目的 (CLI canonical 選択肢 spec + ContextResolver state machine spec + capability matrix spec + 同一 PR 一括更新 future requirement + ADR-00024 placeholder) は本 run の Phase 0 で達成済、R1-R3 軽い polish で merge ready 判断。
