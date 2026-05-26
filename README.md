# TaskManagedAI

TaskManagedAI is an AI-native task management tool for managing research, evidence, approvals, execution logs, cost, review results, and implementation PR flow.

This repository is currently in Sprint 1 Project Foundation. The foundation now covers Docker Compose, FastAPI, PostgreSQL, Redis, Alembic, an arq worker skeleton, the Next.js admin shell, development login, CI smoke, seed data, and integration/E2E skeletons.

## Dependency Lock

Docker builds require `uv.lock`. The lockfile keeps dependency resolution reproducible and is copied into both API and worker images.

1. Install uv on the development machine.
2. Generate or refresh the lockfile before dependency changes:

   uv lock

3. Commit `uv.lock` with backend dependency changes.

The Dockerfiles run `uv sync --locked --no-dev --no-install-project --python 3.12`. If `uv.lock` is missing or empty, the build fails before dependency installation.

Frontend dependencies are locked by `frontend/pnpm-lock.yaml`. Use `pnpm install --frozen-lockfile` for reproducible local and CI installs.

## Sprint 1 Local Start

1. Copy `.env.example` to `.env.local`.
2. Select the development case in `.env.local` by setting `TASKMANAGEDAI_ENVIRONMENT=development`, then replace every `REPLACE_ME` value.
3. Set `TASKMANAGEDAI_DEV_LOGIN_TOKEN` for development login. This token is required in development and test only. Production does not require it because the backend disables `/auth/dev-login`.
4. Initialize the development environment:

   scripts/dev/init.sh

5. Start the Sprint 1 services for local development:

   TASKMANAGEDAI_ENVIRONMENT=development docker compose -f docker-compose.yml -f docker-compose.dev.yml --env-file .env.local up -d

6. Check the API liveness endpoint:

   curl -fsS http://127.0.0.1:8000/healthz

7. Check the API readiness endpoint, including PostgreSQL and Redis:

   curl -fsS http://127.0.0.1:8000/readyz

8. Open the admin shell:

   cd frontend
   pnpm dev

The local frontend runs on `http://127.0.0.1:3900`. Use the development login token from `.env.local` on `/login`.

## Sprint 1 Seed Data

Sprint 1 keeps the Alembic migration framework alive but intentionally leaves the production data model for Sprint 2. The initial Alembic migration creates a seed-only placeholder table named `sprint1_seed_records` so it does not collide with the upcoming tenants, users, actors, workspaces, and projects schema. The seed itself is data-only and must run after `alembic upgrade head`.

The seed inserts these records idempotently:

- tenant: `tenant_id=1`, `name=default-tenant`
- user actor placeholder: `actor_id=human:default`, `actor_type=human`, `name=dev-user`
- project placeholder: `name=default-project`

Run the seed after migrations:

   uv run alembic upgrade head
   uv run python -m backend.app.seeds.runner

## CI Smoke

The Sprint 1 CI smoke workflow is `.github/workflows/ci-smoke.yml`.

It runs three 15 minute jobs and one 30 minute Playwright job:

- backend-quality: `uv sync --locked`, `ruff`, `mypy`, and `pytest`
- frontend-quality: `pnpm install --frozen-lockfile`, TypeScript, ESLint, and Vitest
- frontend-e2e: Python 3.12 + Node 22 setup, backend migration/seed, Playwright Chromium install, and `pnpm exec playwright test`
- docker-smoke: `docker compose config` plus healthcheck spec validation

CI uses fixed test values only. The workflow always writes `.env.ci` from literal Sprint 1 test values and never restores secrets for pull requests. Real production secrets must not be stored in `.env.ci`. Trusted-event secret restore is deferred to Sprint 11.5 and must be limited to trusted events such as push to `main` or release tags with Tailscale GitHub Action and private staging.

## Local Checks

Run lint and type checks:

   scripts/dev/lint.sh

Run backend, frontend unit, and frontend Playwright checks:

   scripts/dev/test.sh

Use fail-fast when you want the first failing section to stop the script:

   scripts/dev/test.sh --fail-fast

Backend DB-dependent tests require PostgreSQL. `scripts/dev/init.sh` starts the local `postgres` and `redis` services before running Alembic and seed.

## Compose Modes

Base Compose requires `TASKMANAGEDAI_ENVIRONMENT` for the `api`, `frontend`, and `worker` services. The value must be selected explicitly as `production`, `development`, or `test`; the base file does not silently fall back to development.

Local development uses the opt-in `docker-compose.dev.yml` file. It enables `TASKMANAGEDAI_ENVIRONMENT=development`, API reload, and development-only FastAPI docs. Pass the variable in the command environment or set it in `.env.local` so Compose can validate the required environment before merging overrides.

   TASKMANAGEDAI_ENVIRONMENT=development docker compose -f docker-compose.yml -f docker-compose.dev.yml --env-file .env.local up -d

Development and test login require `TASKMANAGEDAI_DEV_LOGIN_TOKEN`. The frontend login form sends the submitted token to the backend `/auth/dev-login` endpoint; the backend is the only component that issues signed session cookies.

VPS production uses only the base Compose file. Before running it, `.env.local` must select the production case and include `TASKMANAGEDAI_ENVIRONMENT=production`, production database credentials, the internal Redis URL (`redis://redis:6379/0`), a production cookie secret, and no `REPLACE_ME` values.

   TASKMANAGEDAI_ENVIRONMENT=production docker compose -f docker-compose.yml --env-file .env.local config
   TASKMANAGEDAI_ENVIRONMENT=production docker compose -f docker-compose.yml --env-file .env.local up -d --build

`TASKMANAGEDAI_DEV_LOGIN_TOKEN` is intentionally omitted from the production case. In production, `/auth/dev-login` returns 404 and request-level authentication middleware returns 401 for protected requests without an authenticated actor. Liveness and readiness remain available through `/healthz` and `/readyz`.

`docker-compose.override.yml` is intentionally not used. Keeping development overrides in `docker-compose.dev.yml` prevents Docker Compose from automatically applying development settings to production starts.

## Network Boundary

Host publish binds must stay on `127.0.0.1`. Public ingress must not target container ports directly.

Public ingress is gated by the host publish rules in `docker-compose.yml`:

   127.0.0.1:8000:8000
   127.0.0.1:3900:3000
   127.0.0.1:5432:5432
   127.0.0.1:6379:6379

Container processes may listen on `0.0.0.0` only inside the Docker bridge network so other Compose services and Docker's published-port proxy can reach the container interface. For example, `uvicorn --host 0.0.0.0` is acceptable inside the API container because host reachability still goes through `127.0.0.1:8000:8000`.

The host binds frontend, API, PostgreSQL, and Redis only to `127.0.0.1`. The Compose network remains internal. On the VPS, Tailscale Serve or another approved local-loopback bridge can target the host loopback ports without publishing container services on a public interface.

P0 intentionally allows unauthenticated Redis inside this boundary. API and worker application traffic use the Docker internal endpoint `redis://redis:6379/0`, and the Redis server runs without `requirepass` so it matches the unauthenticated Compose healthcheck. The Redis host publish remains `127.0.0.1` only for local and VPS operations; remote access must stay inside the Tailscale closed network and local-loopback path, never through public ingress.

If P1 introduces multi-tenant operation, public ingress, support access, or any shared deployment model, Redis authentication and exposure must be re-evaluated through the ADR Gate before that deployment is enabled.

The detailed requirements, ADRs, and Sprint Pack are under `docs/`.

