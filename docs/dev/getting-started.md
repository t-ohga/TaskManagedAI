# Getting Started

This guide sets up the Sprint 1 TaskManagedAI development environment on a local machine.

## Prerequisites

Install these tools before starting:

- Python 3.12
- uv
- Node.js 22
- pnpm 10
- Docker with Docker Compose v2

The repository uses `uv.lock` for backend dependencies and `frontend/pnpm-lock.yaml` for frontend dependencies. Do not delete or regenerate lockfiles unless you are intentionally changing dependencies.

## 1. Configure Local Environment

Create `.env.local` from the example file:

   cp .env.example .env.local

Edit `.env.local` and select the development case:

   TASKMANAGEDAI_ENVIRONMENT=development

Replace every `REPLACE_ME` value. At minimum, set:

   TASKMANAGEDAI_DATABASE_URL=postgresql+asyncpg://taskmanagedai:<local-password>@postgres:5432/taskmanagedai
   TASKMANAGEDAI_REDIS_URL=redis://redis:6379/0
   TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET=<local-cookie-secret>
   TASKMANAGEDAI_DEV_LOGIN_TOKEN=<local-dev-login-token>

Do not put production secrets in `.env.local` on a development machine.

## 2. Initialize Dependencies and Seed

Run the idempotent init script:

   scripts/dev/init.sh

The script performs these steps:

- installs backend dependencies with `uv sync --locked`
- installs frontend dependencies with `pnpm install --frozen-lockfile`
- pulls PostgreSQL and Redis images
- starts local PostgreSQL and Redis
- runs `alembic upgrade head`
- runs the Sprint 1 initial seed

If `.env.local` does not exist, the script creates it from `.env.example` and stops before running services.

## 3. Start the Application

Start all local services:

   TASKMANAGEDAI_ENVIRONMENT=development docker compose -f docker-compose.yml -f docker-compose.dev.yml --env-file .env.local up -d

The main local URLs are:

- frontend: `http://127.0.0.1:3900`
- backend liveness: `http://127.0.0.1:8000/healthz`
- backend readiness: `http://127.0.0.1:8000/readyz`

The admin shell redirects unauthenticated users to `/login`. Use the `TASKMANAGEDAI_DEV_LOGIN_TOKEN` value from `.env.local`.

## 4. Run Checks

Run backend lint, backend typing, frontend lint, and frontend typing:

   scripts/dev/lint.sh

Run backend pytest, frontend Vitest, and frontend Playwright:

   scripts/dev/test.sh

Use fail-fast mode when debugging the first failure:

   scripts/dev/test.sh --fail-fast

Backend DB-dependent tests expect PostgreSQL to be reachable. `scripts/dev/init.sh` starts the required local database and applies the current Alembic head before seeding.

## 5. Seed Data

Sprint 1 seed data is intentionally minimal because the full tenants, users, actors, workspaces, and projects schema starts in Sprint 2.

The initial Alembic migration creates a placeholder table named `sprint1_seed_records`. The seed then idempotently inserts:

- `default-tenant`
- `human:default` / `human` / `dev-user`
- `default-project`

Run the seed manually when needed:

   uv run alembic upgrade head
   uv run python -m backend.app.seeds.runner

## 6. CI Smoke Parity

The CI smoke workflow uses test-only values and does not require production secrets. It always writes `.env.ci` from fixed literals; trusted-event secret restore is deferred to Sprint 11.5 for private staging.

Local equivalent commands are:

   uv sync --locked
   uv run ruff check backend tests
   uv run mypy backend
   uv run pytest tests/ -q -x

   cd frontend
   pnpm install --frozen-lockfile
   pnpm exec tsc --noEmit
   pnpm exec eslint . --max-warnings=0
   pnpm exec vitest run
   pnpm exec playwright install --with-deps chromium
   pnpm exec playwright test

Playwright starts the backend and frontend through `frontend/playwright.config.ts`. Keep PostgreSQL and Redis running, and run `uv run alembic upgrade head` plus the seed before Playwright when the database has been reset.

Validate Compose without starting services:

   cp .env.ci .env.local
   docker compose -f docker-compose.yml --env-file .env.ci config

## 7. Network Boundary

Sprint 1 is designed for a single VPS behind Tailscale. Host publish binds stay on `127.0.0.1`; public ingress must not target container ports directly.

Container processes may listen on `0.0.0.0` only inside the Docker bridge network so Docker can route traffic to the container interface. Host reachability still goes through the publish mapping, such as `127.0.0.1:8000:8000` for an API container running uvicorn with `--host 0.0.0.0`.

The Compose network remains internal. On the VPS, Tailscale Serve or another approved local-loopback bridge may target the host loopback ports without exposing the container services on a public interface.

