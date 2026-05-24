# task-01 SP-008 Batch C2 Self Review

Date: 2026-05-24

## Scope

Batch C2 wires the concrete webhook route/adapters around the Batch C verifier:

- `POST /webhooks/github`
- SecretRef-backed current/previous candidate resolver
- Redis `SET ... NX EX` replay store
- audit sink
- Tailscale/loopback ingress guard

It does not implement deployment-specific SOPS decryption. Raw webhook HMAC material is resolved through `app.state.github_webhook_secret_material_resolver`.

## Findings

| severity | finding | disposition |
|---|---|---|
| HIGH | Making `/webhooks/github` public to session auth could create an unauthenticated mutation endpoint. | adopt: the route applies its own internal-network guard using `request.client.host` and then HMAC verification; tests confirm production requests without cookies are accepted only through the route guard. |
| HIGH | Trusting `X-Forwarded-For` would let public callers spoof Tailscale ingress. | adopt: the guard ignores forwarded headers and reads only ASGI `request.client.host`; regression test sends a Tailscale-looking forwarded header from a public client and receives 403. |
| HIGH | SecretRef resolver could accidentally store or expose raw HMAC material. | adopt: resolver requires injected material resolver; DB query reads only `secret_refs` metadata, and API response contains no raw payload/signature/secret fields. |
| MEDIUM | Deprecated previous secret selection could choose the wrong rotation row. | adopt: resolver prefers `current.rotated_from_id` when present, otherwise uses the latest allowed deprecated row. |
| MEDIUM | Resolver could fetch deprecated raw material even when no active current secret exists. | adopt: previous candidate resolution is skipped unless an allowed active current row exists; regression test covers no material resolver call. |
| MEDIUM | Replay defense could degrade to non-atomic check-then-set. | adopt: Redis adapter uses one `SET key 1 EX ttl NX` call; tests assert `nx=True` and TTL are passed. |

## Checklist

- [x] Tailscale/loopback ingress boundary uses `request.client.host`.
- [x] Production auth bypass is limited to `/webhooks/github`; route owns HMAC/network guard.
- [x] SecretRef resolver requires `api:repo_proxy` + `secret.verify` allowlists.
- [x] Deprecated previous material is not resolved unless an allowed active current row exists.
- [x] Raw HMAC material stays out of DB, audit, API response, and test fixture rows.
- [x] Invalid signature maps to 401; duplicate replay maps at service layer to 409.
- [x] Deployment SOPS material resolver residual is explicitly documented.

## Verification

- `uv run ruff check backend/app/api/github_webhooks.py backend/app/services/repoproxy/webhook_adapters.py backend/app/api/router.py backend/app/middleware/dev_actor.py backend/app/services/repoproxy/__init__.py tests/api/test_github_webhooks.py tests/repoproxy/test_webhook_adapters.py tests/api/test_sp012_9_ui_wiring_routes.py`
- `PYTHONPATH=cli uv run mypy backend/app/api/github_webhooks.py backend/app/services/repoproxy/webhook_adapters.py tests/api/test_github_webhooks.py tests/repoproxy/test_webhook_adapters.py`
- `uv run pytest tests/api/test_github_webhooks.py tests/repoproxy/test_webhook_adapters.py tests/api/test_sp012_9_ui_wiring_routes.py -q`
- `uv run pytest tests/repoproxy -q`
- `TASKMANAGEDAI_RUN_DB_TESTS=1 TASKMANAGEDAI_DATABASE_URL='postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:55434/taskmanagedai_test' uv run pytest tests/repoproxy -q`
