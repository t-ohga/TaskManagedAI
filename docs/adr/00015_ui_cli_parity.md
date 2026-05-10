---
id: "ADR-00015"
title: "UI ↔ CLI Parity Boundary: 共通 FastAPI backend + 13 capability matrix + Tailscale-only + principal-bound API capability token (TTL 5-30 分) + multi-profile config + parity contract test"
status: "proposed"
date: "2026-05-10"
authors:
  - "t-ohga"
related_sprints:
  - "SP-016_ui_cli_parity"
related_research:
  - "docs/設計検討/phase-c-multi-agent-spec-draft.md §C-4 + §11.3 PE-F-006"
acceptance_blocked_by:
  - "ADR-00014 accepted"
  - "P0 完了 + Sprint 9 Web UI foundation 完了"
---

最終更新: 2026-05-10 (proposed 起票、Phase E PE-F-006 反映)

## 背景

- 決定対象: TaskManagedAI の **「UI ↔ CLI parity = どっちでやっても変わらない動き」** を実装するため、(1) CLI tool 名候補 (`tm`)、(2) 13 capability matrix (memory 除外、PD-F-019 fix)、(3) **principal-bound API capability token DDL** (PE-F-006 fix)、(4) multi-profile config、(5) parity contract test を固定.
- 前提: ADR-00007 (Tailscale-only, Funnel 不使用) / DD-05 / SecretBroker capability token TTL 5-30 分 / Approval 4 整合.
- ADR Gate Criteria #3 (API 契約) + #7 (外部公開) 該当.

## 採用案

### §1: CLI tool 名 = `tm` (候補、Phase E 後 SP-016 で確定)

衝突確認 (Sprint 16 着手前): `which tm` / `brew search tm` / `ls /usr/local/bin /opt/homebrew/bin | grep '^tm$'` → 衝突なし確認後採用、衝突時 `tmai` fallback.

### §2: 13 capability matrix (memory 除外、PD-F-019 fix)

ADR-00014 §11.4 + Phase C §4.3 参照。memory record/search は SP-018 accepted 後に feature flag で追加。SP-016 では `tm memory` の 404/disabled contract test のみ.

### §3: principal-bound API capability token DDL (PE-F-006 fix、CRITICAL strengthening)

CLI 用 token を **bearer token として扱わず**、SecretBroker と同等の OperationContext binding:

```sql
create table api_capability_tokens (
    id uuid primary key default gen_random_uuid(),
    tenant_id bigint not null default 1 references tenants(id),
    project_id uuid,                                       -- NULL = tenant-wide
    token_hash text not null,                              -- raw token は保存しない
    actor_id uuid not null,
    principal_id uuid not null,                            -- session/principal binding
    device_id text,                                        -- CLI client device 識別 (optional、user 確認後 enable)
    allowed_actions text[] not null,                       -- scope 最小 (e.g. ['ticket:r','run:rw'])
    audience text not null check (audience = 'taskmanagedai-api'),
    issued_at timestamptz not null default now(),
    expires_at timestamptz not null,                       -- TTL 5-30 分
    jti text not null,                                     -- JWT-style unique id (replay 検知)
    revoked_at timestamptz,
    last_used_at timestamptz,
    foreign key (tenant_id, actor_id) references actors(tenant_id, id),
    foreign key (tenant_id, principal_id) references principals(tenant_id, id),
    foreign key (tenant_id, project_id) references projects(tenant_id, id),
    unique (tenant_id, jti)
);

create index ix_api_capability_tokens_active
    on api_capability_tokens (tenant_id, actor_id)
    where revoked_at is null and expires_at > now();
```

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

### §8: 実装 Sprint と対象ファイル

- SP-016 (target 4/max 6 days)
- 実装対象: `cli/tm/main.py` / `cli/tm/commands/*.py` / `cli/tm/config/profile_loader.py` / `cli/tm/auth/capability_token.py` / `cli/tm/output/*.py` / `backend/app/db/models/api_capability_token.py` / `migrations/versions/0016_p0_1_api_capability_tokens.py` / `tests/parity/test_ui_cli_parity.py` / `tests/cli/*` / `docs/cli/README.md`

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
