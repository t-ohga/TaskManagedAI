# task-01 SP-008 Batch C Self Review

Date: 2026-05-24

## Scope

Batch C implements the webhook service boundary only. It does not claim the concrete Redis adapter, concrete SecretBroker resolver, Tailscale ingress route, or `repo_pr_opened` runtime emission. KPI endpoint exposure was completed later in Batch E.

## Findings

| severity | finding | disposition |
|---|---|---|
| HIGH | Invalid signatures could consume the replay nonce if replay was claimed before HMAC verification. | adopt: `GitHubWebhookVerifier` claims replay only after a current or previous secret validates. |
| HIGH | A previous secret with `active` / `pending` / `revoked` status could be accepted as a rotation fallback. | adopt: fallback is accepted only when previous status is `deprecated`; invalid previous status denies. |
| MEDIUM | Audit payload could leak delivery id, raw signature header, or raw HMAC secret. | adopt: payload stores delivery hash, signature presence, payload hash, secret ref metadata only; tests assert no raw values. |
| MEDIUM | The new service boundary could overclaim concrete infrastructure. | adopt: docs explicitly defer concrete SecretBroker resolver, Redis adapter, and FastAPI route wiring. |
| MEDIUM | Low-level helper docstring still described the service layer as pending. | adopt: updated `webhook_hmac.py` contract to point production callers to `webhook_service.py`. |
| MEDIUM | Malformed signatures could reach previous-secret status checks and disclose rotation misconfiguration. | adopt: previous fallback is attempted only for `signature_mismatch`; invalid format / unsupported algorithm / empty payload deny immediately. |

## Checklist

- [x] Current active secret accepted.
- [x] Previous deprecated secret accepted during rotation.
- [x] Previous non-deprecated secret denied.
- [x] Signature mismatch denied without replay claim.
- [x] Replay duplicate denied after valid signature.
- [x] Malformed signature denies before previous-secret status fallback.
- [x] Missing delivery id denied before secret resolution.
- [x] Audit payload redacts raw delivery id, signature header, and HMAC secret.
- [x] Service result remains JSON-serializable.

## Verified

- `uv run pytest tests/repoproxy/test_webhook_service.py -q`
- `TASKMANAGEDAI_RUN_DB_TESTS=1 TASKMANAGEDAI_DATABASE_URL='postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:55434/taskmanagedai_test' uv run pytest tests/repoproxy -q`
- `PYTHONPATH=cli uv run mypy backend/app/services/repoproxy tests/repoproxy/test_webhook_service.py`

## Deferred

- Concrete SecretBroker-backed HMAC secret resolver.
- Concrete Redis SETNX replay adapter.
- FastAPI `/webhooks/github` route with Tailscale-only ingress check.
- Runtime `repo_pr_opened` automatic call-site wiring.
