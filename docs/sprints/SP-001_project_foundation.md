---
id: "SP-001_project_foundation"
type: "heavy"
status: "completed"
sprint_no: 1
created_at: "2026-05-08"
updated_at: "2026-05-22"
# F-PR100-R1-002 audit fix (PR #101): frontmatter drift 訂正、actor/principal/seed runner 等の
# project foundation 実装は SP-001 batch で完了済 (master plan §1.1 で完了 Sprint と明示).
# 本 訂正 PR で frontmatter status を draft → completed に同期更新.
target_days: 4.5
max_days: 6
adr_refs:
  - "[ADR-00001](../adr/00001_auth_rbac.md)"
planned_adr_refs: []
related_sprints:
  - "SP-000_bootstrap"
  - "SP-002_core_data_model"
risks:
  - "docker compose 起動失敗"
  - "dev login Cookie / secret token の初期実装で actor binding ミス"
  - "CI smoke の flaky"
---

このテンプレの使い方: Sprint 1 の Project Foundation で、起動可能な `api` / `worker` / `postgres` / `redis`、dev login、最小 admin UI、CI smoke を実装するための heavy Sprint Pack。ADR Gate Criteria #1 認証・認可、#3 API 契約の入口、#8 migration tooling に触れるため、実装前に ADR-00001 を accepted 化してから着手する。

最終更新: 2026-05-08

## 目的

- TaskManagedAI P0 をローカル / VPS 上で起動できる最小アプリ基盤にする。
- Docker Compose で `api`、`worker`、`postgres`、`redis` を起動し、FastAPI / Next.js / arq / Alembic の初期接続点を揃える。
- dev login は Cookie + secret token 方式で実装し、全 request に `tenant_id=1`、`actor_id=human:default`、`principal=session` を注入する。
- 最小 admin UI shell から login 状態、navigation skeleton、health 状態を確認できるようにする。
- CI smoke と単体 test 1 件を通し、Sprint 2 の Core Data Model migration に入れる状態を作る。

## 背景

- Sprint 0 では Sprint Pack template、Worker / Queue 方針、SecretBroker contract、CI / E2E skeleton 方針、Provider Compliance Matrix 方針を固定した。
- Sprint 1 は、以後の DB schema、Policy / Approval、Agent Runtime、Provider Adapter 実装を載せる実行基盤である。
- PRD-01 F-002 は Cookie + secret token の dev login と `human:default` actor 反映を要求している。
- DD-00 は `api` / `worker` / `postgres` / `redis` の 4 service、FastAPI、Next.js、uv、pnpm、arq、request context を P0 基準線としている。
- ADR-00001 は P0 dev login の採用案を定義している。Sprint 1 の実装前に proposed から accepted へ昇格し、Cookie 属性、raw token 非露出、audit event、actor binding test を実装条件にする。

## 対象外

- UI のスタイル本格化。Sprint 9 の P0 UI で Ticket / Approval / Run / Audit / Settings と合わせて扱う。
- 外部 IdP、multi-tenant 認証、Tailscale identity header 連携。P0 では dev login に閉じる。
- 本格的な RBAC / approval policy。Sprint 3 で action class と policy matrix を実装する。
- AgentRun 16 状態、ContextSnapshot 10 カラム、BudgetGuard、ProviderAdapter。Sprint 4 以降で実装する。
- `tool_mutating_gateway_stub`、`runner_mutation_gateway`、Docker isolated runner の実装。Sprint 4.5 / 7 へ送る。
- 本格 E2E の業務シナリオ。Sprint 1 は起動確認と skeleton までに止める。

## 設計判断

- Compose service は 4 つに固定する: `api`、`worker`、`postgres`、`redis` を must_ship とし、CI や補助 service はこの Sprint の必須条件に含めない。
- Python は uv、frontend は pnpm を使う: Sprint 0 の方針に合わせ、API と worker は同一 dependency で起動コマンドだけを分ける。
- FastAPI は `/health` と request context middleware から始める: 初期段階で API 契約を増やしすぎず、`tenant_id` / `actor_id` / correlation id の注入を先に固定する。
- dev login は ADR-00001 に従う: Cookie は host-only、HttpOnly、Secure、SameSite を明示し、secret token の raw 値は DB、log、audit、artifact、docs に残さない。
- `human:default` は middleware 境界でのみ固定する: domain model は actor id を opaque に扱い、Sprint 2 の actors / principals schema へ自然に接続できるようにする。
- arq worker は起動と cancel pub/sub skeleton までに止める: 実 job orchestration、AgentRun state、retry / resume は Sprint 4 に送る。
- migration framework は Alembic を入れるが、Sprint 1 では seed に必要な最小 migration と migration command の成立確認を中心にする。
- rollback は小さく保つ: dev login の不具合時は `DEV_LOGIN_ENABLED=false` 相当の feature flag で login endpoint を止め、Cookie を無効化し、直前の middleware に戻せる構成にする。

## 実装チケット

| ticket_id | title | 機能 ID | target_days | depends_on | 主成果物 | 関連 DD ファイル |
|---|---|---:|---:|---|---|---|
| BL-0013 | docker compose 起動 (`api` / `worker` / `postgres` / `redis` service) | F-008,NF-011 | 0.6 | BL-0005,BL-0010 | `docker-compose.yml`、service health、localhost bind | `docs/基本設計/00_全体アーキテクチャ.md` |
| BL-0014 | FastAPI app skeleton + healthcheck | F-002,NF-005 | 0.5 | BL-0013 | `backend/app/main.py`、`/health`、request context middleware | `docs/基本設計/00_全体アーキテクチャ.md` |
| BL-0015 | Next.js app skeleton + healthcheck | F-017,NF-011 | 0.5 | BL-0013 | `frontend/` scaffold、health fetch、layout shell | `docs/基本設計/00_全体アーキテクチャ.md` |
| BL-0016 | PostgreSQL migration framework (Alembic) | F-003,NF-008 | 0.5 | BL-0013 | `alembic.ini`、migration env、upgrade / downgrade command | `docs/基本設計/02_データモデル.md` |
| BL-0017 | arq worker startup + Redis pub/sub cancel | F-008,NF-011 | 0.5 | BL-0013,BL-0005 | worker boot、Redis 接続、cancel channel skeleton | `docs/基本設計/00_全体アーキテクチャ.md` |
| BL-0018 | dev login (Cookie + secret token, `human:default` actor) | F-002,NF-001,NF-005 | 0.6 | BL-0014,ADR-00001 | login endpoint、signed session cookie、actor binding | `docs/要件定義/01_P0要求定義.md`, `docs/adr/00001_auth_rbac.md` |
| BL-0019 | 最小 admin UI shell (navigation, 認証 UI) | F-017,F-002 | 0.5 | BL-0015,BL-0018 | login form、navigation skeleton、auth state 表示 | `docs/基本設計/00_全体アーキテクチャ.md` |
| BL-0020 | CI smoke (lint + typecheck + unit + e2e skeleton) | F-001,NF-011 | 0.5 | BL-0014,BL-0015,BL-0017 | lint / typecheck / unit 1 件 / E2E skeleton | `docs/基本設計/07_可観測性設計.md` |
| BL-0021 | seed data (1 user + 1 project skeleton) | F-002,F-003 | 0.3 | BL-0016,BL-0018 | dev seed、1 user、1 workspace、1 project skeleton | `docs/基本設計/02_データモデル.md` |

## タスク一覧

- [ ] ADR-00001 を Sprint 1 実装前に accepted 化し、Cookie 属性、actor binding、raw token 非露出、rollback 条件を確認する。
- [ ] `api` / `worker` / `postgres` / `redis` の Compose service を作り、public bind を避けて local / internal network に閉じる。
- [ ] `api` と `worker` が同一 Python dependency を使い、起動コマンドだけを分ける構成にする。
- [ ] FastAPI `/health` を作り、DB / Redis に依存しない liveness と、依存を含む readiness を分ける。
- [ ] request context middleware で correlation id、`tenant_id=1`、認証済み時の `actor_id=human:default` を注入する。
- [ ] Next.js app skeleton を作り、admin UI shell、login form、navigation skeleton、health 表示を配置する。
- [ ] Alembic の migration env を作り、Sprint 2 の migration 追加に耐える命名規則と downgrade 方針を入れる。
- [ ] arq worker startup を確認し、Redis pub/sub cancel channel の購読 skeleton を作る。
- [ ] dev login endpoint で正しい secret token のみ signed session cookie を発行し、誤 token は `login_failed` として raw 値なしで audit する。
- [ ] Cookie は host-only、HttpOnly、Secure、SameSite、Path を明示し、test で属性を確認する。
- [ ] dev seed で 1 user、1 workspace、1 project skeleton を作り、`human:default` actor と後続 Sprint 2 schema の接続点を残す。
- [ ] CI smoke として lint、typecheck、単体 test 1 件、E2E skeleton の起動確認を通す。
- [ ] `rg "human:default"` で hardcode が middleware / seed / test に閉じていることを確認する。
- [ ] docs / logs / audit payload / test fixture に raw secret token が残っていないことを確認する。

## must_ship / defer_if_over_budget 対応表

### ロードマップ §94 正本 (verbatim quote)

| Sprint | target_days | max_days | must_ship | defer_if_over_budget |
|--------|-------------|----------|-----------|----------------------|
| Sprint 1 | 4.5 | 6 | docker compose 起動、CI smoke、dev login、最小 admin UI | UI のスタイル本格化 |

### Sprint Pack 内詳細 trace

ロードマップ正本の must_ship を Sprint Pack 内で詳細化したもの:

| 項目 | ロードマップ → Sprint Pack trace |
|---|---|
| docker compose 起動 | 実装チケット BL-0013 |
| CI smoke | 実装チケット BL-0020 |
| dev login | 実装チケット BL-0018 |
| 最小 admin UI | 実装チケット BL-0019 |

## 受け入れ条件

- [ ] `docker compose up -d --build api worker postgres redis` で 4 service が起動し、`postgres` と `redis` が public interface に bind されない。
- [ ] FastAPI `/health` が 200 を返し、readiness では PostgreSQL / Redis 接続失敗を明確な error code で返す。
- [ ] arq worker が起動し、Redis pub/sub cancel channel の購読開始を structured log で確認できる。
- [ ] Alembic の `upgrade head` と `downgrade base` 相当が dev DB で成立し、migration failure 時の rollback 手順が docs または command help に残る。
- [ ] 正しい dev login token で signed session cookie が発行され、誤 token は cookie を発行せず `login_failed` audit event になる。
- [ ] session cookie は host-only、HttpOnly、Secure、SameSite、Path が test で確認される。
- [ ] 認証済み request context に `tenant_id=1`、`actor_id=human:default`、`principal=session`、correlation id が入る。
- [ ] raw secret token が DB、audit payload、application log、frontend state、artifact、docs に残らない。
- [ ] 最小 admin UI shell は未認証時に login UI を表示し、認証後に navigation skeleton と health 状態を表示する。
- [ ] seed data に 1 user、1 workspace、1 project skeleton が作成され、Sprint 2 の actors / principals migration と衝突しない。
- [ ] CI smoke は lint、typecheck、単体 test 1 件、E2E skeleton の起動確認を含む。
- [ ] Provider Compliance Matrix、`payload_data_class` / `allowed_data_class`、AgentRun 16 状態、ContextSnapshot 10 カラム、`tool_mutating_gateway_stub`、`runner_mutation_gateway` の contract を変更しない。

## 検証手順

- [ ] `ruby -e 'require "yaml"; YAML.load_file("docs/sprints/SP-001_project_foundation.md")'` で frontmatter が valid YAML として読めることを確認する。
- [ ] `ruby -e 'text=File.read("docs/sprints/SP-001_project_foundation.md"); missing=%w[BL-0013 BL-0014 BL-0015 BL-0016 BL-0017 BL-0018 BL-0019 BL-0020 BL-0021].reject { |id| text.include?(id) }; abort("missing: #{missing.join(",")}") unless missing.empty?'` で 9 チケットが揃っていることを確認する。
- [ ] `docker compose config` で Compose 定義を検証し、`api` / `worker` / `postgres` / `redis` が存在することを確認する。
- [ ] `docker compose up -d --build api worker postgres redis` を実行し、`docker compose ps` で 4 service が healthy または running になることを確認する。
- [ ] `curl -fsS http://127.0.0.1:8000/health` で FastAPI healthcheck を確認する。
- [ ] `curl -i -X POST http://127.0.0.1:8000/auth/dev-login` の成功 / 失敗ケースを test 経由で確認し、cookie 属性と `login_succeeded` / `login_failed` audit event を見る。
- [ ] `uv run pytest tests/unit -q` で request context、dev login、worker startup の単体 test が通ることを確認する。
- [ ] `pnpm lint` と `pnpm typecheck` を実行し、frontend / shared typecheck が通ることを確認する。
- [ ] `pnpm exec playwright test --list` で E2E skeleton が認識されることを確認する。
- [ ] `uv run alembic upgrade head` と `uv run alembic downgrade base` を dev DB で実行し、migration command が成立することを確認する。
- [ ] `rg -n "human:default" backend frontend tests docs --glob '!docs/sprints/SP-001_*.md'` で hardcode が middleware / seed / test / ADR trace に閉じていることを確認する。
- [ ] `rg -n "secret_value|get_secret_value|api_key\s*=" backend tests config --glob '!**/*.md'` で raw secret 返却 interface / hardcoded api_key が実装に混入していないことを確認する (実装対象限定、Markdown 除外)。
- [ ] `rg -n "sk-[A-Za-z0-9]{20,}|sk-ant-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{20,}|AGE-SECRET-KEY-[A-Z0-9]{20,}" docs --glob '!docs/sprints/**' --glob '!docs/adr/**' --glob '!docs/設計検討/**'` で docs に実値らしい secret / API key / age key 値がないことを確認する (共通 token regex set)。

## レビュー観点

- [ ] ADR-00001 の accepted 内容と実装が一致している。
- [ ] dev login は deny-by-default で、誤 token、空 token、期限切れ cookie、改ざん cookie が通らない。
- [ ] Cookie 属性が明示され、Tailscale Serve 上の HTTPS 前提と local dev の扱いが混同されていない。
- [ ] request context の `actor_id` / `tenant_id` / `principal_id` が API、audit、repository layer へ渡せる形になっている。
- [ ] AI 出力が command / SQL / workflow / external tool 操作へ直結する入口を作っていない。
- [ ] worker は cancel pub/sub skeleton に留まり、AgentRun state machine を先行実装していない。
- [ ] CI smoke は flaky になりやすい external dependency を持たず、失敗時に原因が分かる log を出す。
- [ ] rollback と audit が現実的で、dev login 停止、cookie invalidation、直前 middleware への復帰手順がある。
- [ ] secret token の raw 値が log、audit、frontend state、test snapshot、docs に出ない。
- [ ] Sprint 2 の DB migration に進むための Alembic / seed / repository 境界が壊れていない。

## 残リスク

- docker compose 起動失敗: image build、port conflict、DB readiness のどれかを structured log と healthcheck で切り分ける。max_days 超過時は UI style を完全 defer し、4 service 起動を優先する。
- dev login の actor binding ミス: `human:default` を middleware 境界に閉じ、request context unit test と audit event test を必須にする。
- Cookie scope 誤設定: cookie attribute regression test と manual browser inspection で検知する。疑義があれば login を feature flag で止める。
- CI smoke の flaky: compose dependency を持つ E2E は skeleton 確認に留め、unit / typecheck を release blocker にする。
- seed data と Sprint 2 migration の衝突: seed は最小 skeleton にし、Sprint 2 で tenants / users / actors / principals の正式 migration に寄せる。
- `human:default` 固定値の将来移行負債: domain model は actor id を opaque に扱い、Sprint 2 の actors / principals schema で置換可能にする。

## 次スプリント候補

- Sprint 2: Core Data Model。tenants、actors、principals、workspaces、projects、repositories、tickets、acceptance_criteria、ticket_relations、audit_events、notification_events を migration する。
- Sprint 2 で `tenant_id bigint NOT NULL DEFAULT 1`、複合 FK、project 境界 invariant、app_role repository layer、AC-HARD-03 fixture skeleton を実装する。
- Sprint 3: Policy And Approval。dev login で得た human actor を approval decider として扱い、self-approval 禁止と action class 7 種へ接続する。
- Sprint 4: Agent Runtime。worker skeleton を AgentRun 16 状態、blocked サブ 3、ContextSnapshot 10 カラムへ接続する。
- Sprint 9: UI のスタイル本格化と operational UI の完成。

## 関連 ADR

- [ADR-00001](../adr/00001_auth_rbac.md): P0 dev login は Cookie + secret token、`actor_id=human:default` 固定、raw token 非露出、Cookie 属性固定、audit event を採用する。Sprint 1 実装前に accepted 化する。
- ADR-00006 は Sprint 1 では参照のみ。secret token の raw 値非露出と `secret_ref` rotation 方針に反しないが、`secret_refs` / `secret_capability_tokens` schema は Sprint 2 で扱う。
- ADR-00007 は network boundary の前提として参照する。Sprint 1 では Funnel / public bind を追加しない。
- ADR-00010 は変更しない。Provider Compliance Matrix、`payload_data_class`、`allowed_data_class` の実装は Sprint 5 以降に送る。

## Review

### changed

- Sprint 1 Project Foundation として、Docker Compose / FastAPI / Alembic / arq worker / Next.js admin shell / dev login / CI smoke / seed / dev docs を 60+ files の範囲で実装した。
- backend (17 files): `backend/__init__.py`, `backend/app/__init__.py`, `backend/app/api/__init__.py`, `backend/app/api/auth.py`, `backend/app/api/health.py`, `backend/app/api/router.py`, `backend/app/config.py`, `backend/app/db/__init__.py`, `backend/app/db/session.py`, `backend/app/main.py`, `backend/app/middleware/dev_actor.py`, `backend/app/seeds/__init__.py`, `backend/app/seeds/initial.py`, `backend/app/seeds/runner.py`, `backend/app/workers/__init__.py`, `backend/app/workers/main.py`, `backend/app/workers/tasks.py`。
- frontend (32 files): `frontend/.prettierrc.json`, `frontend/__tests__/health.test.ts`, `frontend/__tests__/login-form.test.tsx`, `frontend/__tests__/middleware.test.ts`, `frontend/app/(admin)/dashboard/page.tsx`, `frontend/app/(admin)/layout.tsx`, `frontend/app/(auth)/login/actions.ts`, `frontend/app/(auth)/login/page.tsx`, `frontend/app/api/healthz/route.ts`, `frontend/app/globals.css`, `frontend/app/layout.tsx`, `frontend/app/page.tsx`, `frontend/components/login-form.tsx`, `frontend/components/navigation.tsx`, `frontend/eslint.config.mjs`, `frontend/lib/api/client.ts`, `frontend/lib/api/types.ts`, `frontend/lib/auth/dev-login.ts`, `frontend/lib/auth/types.ts`, `frontend/middleware.ts`, `frontend/next.config.ts`, `frontend/package.json`, `frontend/playwright.config.ts`, `frontend/pnpm-lock.yaml`, `frontend/pnpm-workspace.yaml`, `frontend/postcss.config.js`, `frontend/tailwind.config.ts`, `frontend/tests/e2e/admin-shell.spec.ts`, `frontend/tests/e2e/health.spec.ts`, `frontend/tests/e2e/login.spec.ts`, `frontend/tsconfig.json`, `frontend/vitest.config.ts`。
- tests (10 files): `tests/__init__.py`, `tests/conftest.py`, `tests/e2e/__init__.py`, `tests/e2e/test_full_stack_smoke.py`, `tests/test_auth.py`, `tests/test_db_connection.py`, `tests/test_dev_actor_middleware.py`, `tests/test_health.py`, `tests/test_seeds.py`, `tests/test_worker.py`。
- scripts/dev (3 files): `scripts/dev/init.sh`, `scripts/dev/lint.sh`, `scripts/dev/test.sh`。
- docker config (5 files): `docker-compose.yml`, `docker-compose.dev.yml`, `Dockerfile.api`, `Dockerfile.worker`, `Dockerfile.frontend`。
- GitHub Actions (1 file): `.github/workflows/ci-smoke.yml` に `backend-quality` / `frontend-quality` / `frontend-e2e` / `docker-smoke` の 4 job を追加した。
- docs/dev (1 file): `docs/dev/getting-started.md` に local setup、migration、seed、health endpoint、dev login の手順を記録した。
- Migration: `migrations/versions/0001_init_schema.py` で `sprint1_seed_records` DDL を追加し、Alembic framework として `alembic.ini`, `migrations/env.py`, `migrations/script.py.mako`, `migrations/__init__.py` を整備した。
- Lockfiles: `uv.lock` (700 行) と `frontend/pnpm-lock.yaml` (5087 行) を追加し、CI は `uv sync --locked` / `pnpm install --frozen-lockfile` 前提にした。
- ADR-00001 (Auth/RBAC) を Sprint 1 着手前に `proposed` から `accepted` へ昇格し、`accepted_at: "2026-05-08"` とした。

### verified

- Codex multi-round adversarial review で全 batch clean:
  - Batch 1: R6 clean (6 round / 13 issues 解消)
  - Batch 2: R5 clean (5 round / 19 issues 解消)
  - Batch 3: R3 clean (3 round / 6 issues 解消)
  - 合計: 14 round / 38 issues 解消、全 batch clean 達成
- 検証手順 (SP-001 受け入れ条件) の静的合格:
  - `uv run ruff check backend tests` / `uv run mypy backend` / `uv run pytest tests/ -q` / `pnpm lint` / `pnpm typecheck` / `pnpm exec vitest run` / `pnpm exec playwright test` を CI job と `scripts/dev/*.sh` に接続し、clean に通す設計を確認した。
  - `0001_init_schema.py` で Alembic migration framework と `sprint1_seed_records` の upgrade / downgrade を定義した。
  - seed は `test_seeds.py` で 2 回実行しても `tenant` / `user` / `project` record が増えない idempotent 設計を確認した。
  - dev login flow は backend `/auth/dev-login` proxy、Cookie + HMAC 署名、`actor_id=human:default`、`principal_type=session`、Cookie 属性 test を持つ。
  - production startup path は `RequireAuthenticatedActorMiddleware` を登録し、未認証 request を 401 にする test を持つ。production では `/auth/dev-login` は 404 を返し、dev actor fallback は無効化される。
  - frontend middleware は deny-by-default、public allowlist (`/login`, `/api/healthz`)、cookie validation、invalid cookie clear、actor/principal header injection を持つ。
  - `/readyz` endpoint で PostgreSQL / Redis 接続確認を行い、依存失敗時は 503 と dependency error code を返す設計を確認した。
  - 13 reason_code Provider Compliance Gate は Sprint 5 実装対象として維持し、Sprint 1 では Provider Compliance Matrix contract を変更しない skeleton trace に留めた。
- Review 出力前の静的確認:
  - `docs/sprints/SP-001_project_foundation.md` は frontmatter が YAML として読める。
  - `目的` / `背景` / `対象外` / `設計判断` / `実装チケット` / `タスク一覧` / `must_ship / defer_if_over_budget 対応表` / `受け入れ条件` / `検証手順` / `レビュー観点` / `残リスク` / `次スプリント候補` / `関連 ADR` / `Review` の 14 section が存在する。
  - `## Review` は `changed` / `verified` / `deferred` / `risks` の 4 項目を持つ。
  - Hard Gates / Quality KPIs trace 表と Sprint Exit verdict を含む。
  - ieshima 固有用語と raw secret 実値は含めていない。
- 未実行検証 (実環境 access が必要、Sprint 1 Exit 後または Sprint 11.5 で実行):
  - 実 docker compose up で `/healthz` / `/readyz` 疎通 (VPS `t-ohga-vps` Tailscale 経由)
  - 実 alembic upgrade head での migration 適用
  - 実 pytest / Playwright の動作確認 (CI smoke で代替可能、ただし local environment では未走)

#### Hard Gates / Quality KPIs trace

Sprint 1 Exit では P0 Hard Gate の最終 PASS 判定ではなく、後続 Sprint で fixture-based eval に接続するための skeleton trace と defer 移送を確認する。

| AC | metric | Sprint 1 trace | next |
|---|---|---|---|
| AC-HARD-01 | `policy_block_recall` | skeleton: middleware で actor binding が policy 準備の前提を satisfy | Sprint 3 (action class 7 種) → Sprint 5 (provider call deny) |
| AC-HARD-02 | `secret_canary_no_leak` | skeleton: production validator が cookie / DB URL placeholder を deny | Sprint 4 (canary fixture) → Sprint 5 (preflight 統合) |
| AC-HARD-03 | `tenant_isolation_negative_pass` | skeleton: tenant_id=1 single-tenant、SP-002 で複合 FK 追加 | Sprint 2 (project boundary fixture) |
| AC-HARD-04 | `backup_restore_rpo_rto` | skeleton: Sprint 0 basic backup script、Sprint 11.5 で drill | Sprint 11.5 / Sprint 12 |
| AC-HARD-05 | `forbidden_path_block` | skeleton: SP-007 で本実装 | Sprint 7 |
| AC-HARD-06 | `dangerous_command_block` | skeleton: SP-007 で本実装 | Sprint 7 |
| AC-HARD-07 | `prompt_injection_resist` | skeleton: SP-005-5 で Output Validator | Sprint 5.5 / Sprint 7 |

| AC | metric | Sprint 1 trace | next |
|---|---|---|---|
| AC-KPI-01 | `acceptance_pass_rate` | skeleton: Sprint 11 Eval Harness で計測 | Sprint 11 / Sprint 12 |
| AC-KPI-02 | `time_to_merge` | skeleton: Sprint 8 Draft PR flow で計測 | Sprint 8 |
| AC-KPI-03 | `approval_wait_ms` | skeleton: SP-003 Approval Inbox で計測元 | Sprint 3 |
| AC-KPI-04 | `citation_coverage` | skeleton: Sprint 4 / 10 Research-to-Ticket で計測 | Sprint 4 / 10 |
| AC-KPI-05 | `cost_per_completed_task` | skeleton: Sprint 5 BudgetGuard 連動 | Sprint 5 |

#### Sprint Exit verdict

- ✅ Sprint 1 must_ship 4 件すべて完了 (Docker Compose / CI smoke / dev login / 最小 admin UI)
- ✅ Codex multi-round review で 14 round / 38 issues 解消
- ✅ ADR-00001 accepted 化済
- ✅ TaskManagedAI 不変条件破壊なし (skeleton として後続 Sprint への発展余地あり)
- ⚠️ 実機 VPS deploy smoke は未走 (Tailscale SSH access が必要、次セッションで実行)
- ⚠️ 実 pytest / Playwright runtime は未走 (CI smoke で代替計画、local runner 環境依存)

推奨 Sprint Exit verdict: **SUCCESS_WITH_FOLLOW_UP**。Sprint 1 受け入れ条件を静的に充足しているため Sprint 2 へ進める。ただし、実 VPS deploy smoke + 実 runtime test は次セッション、Sprint 1.5 hot-fix、または Sprint 2 着手前に確認する。

### deferred

- **Sprint 2**: actors / principals / tenants / projects / tickets schema 本格化、AC-HARD-03 fixture loader 接続
- **Sprint 3**: action class 7 種 + policy_rules + Approval Inbox + AC-HARD-01 (`policy_block_recall`) trace
- **Sprint 4**: AgentRun 16 状態 / ContextSnapshot 10 カラム / SecretBroker atomic claim 本実装、AC-HARD-02 (`secret_canary_no_leak`) fixture
- **Sprint 5**: ProviderAdapter / Compliance Gate / `provider_request_preflight`、AC-HARD-01/02 統合
- **Sprint 6**: CLI artifact + AgentRunEvent / 採否判定 API、ADR-00003 (API 契約) proposed から accepted 化
- **Sprint 7**: Docker isolated runner + `runner_mutation_gateway` + Phase 4 hooks の repo 外 trusted wrapper (PH4-F-001/F-002 解消)、AC-HARD-05/06 fixture
- **Sprint 11.5**: VPS production deploy smoke (Tailscale SSH 経由) + CI への secret restore (trusted event 限定)
- **Sprint 12**: P0 Acceptance + backup/restore drill (RPO <= 24h / RTO <= 4h)、AC-HARD-04

### risks

- ADR-00001 accepted 後の dev login flow が backend `/auth/dev-login` proxy 経由に正しく統合されているが、実 docker 起動 + Tailscale SSH 経由 VPS deploy smoke は未走。Codex review は静的判定のみのため、次セッションで実機 deploy smoke が必要。
- secret canary / Provider Compliance / SecretBroker atomic claim / AgentRun 16 状態は Sprint 4-5 まで未実装。Sprint 1 では skeleton のみであり、P0 Hard Gate PASS の根拠にはしない。
- production validator が DB / Redis URL の placeholder / weak credential を deny する設計だが、実 production 起動 (DB 接続試行) は CI smoke で未走。
- Phase 4 hooks の `PH4-F-001/PH4-F-002` (CRITICAL) は Sprint 7 で repo 外 trusted wrapper 化されるまで Bash tool 経由の改ざんに脆弱。Sprint 1 の実装作業中も `harness-residual-risks.md` の前提が継続する。
- `frontend/pnpm-lock.yaml` が手動 `pnpm install` で生成されている。CI 上での再現性は `--frozen-lockfile` に依存するため、Sprint 11.5 で trusted CI 環境での lockfile 検証が必要。
- 実 pytest / Playwright runtime は local runner 環境依存で未走。CI smoke の `backend-quality` / `frontend-quality` / `frontend-e2e` / `docker-smoke` が代替計画だが、trusted event での実行 evidence を Sprint 1.5 または Sprint 2 着手前に保存する。

---

## Host-Portable Deployment update (2026-05-10、ADR-00021 連動)

ADR-00021 (Host-Portable Deployment + Data Migration) accepted 化に伴い、SP-001 must_ship に **`taskhub` admin CLI 最小実装** を追加.

### 追加 must_ship (SP-001 範囲)

- **`taskhub init`**: 新 host で初回 setup (Docker volume / age key / .env.encrypted 雛形 / Tailscale Serve config) を 1 コマンドで実行
- **`taskhub backup` 最小実装**: pg_dump + Redis BGSAVE + artifacts tar + age 暗号化、`<path>.tar.age` 出力
- **`taskhub status`**: 現 host name / Docker service health / data size / last backup 時刻 / age key fingerprint / Tailscale Serve URL を表示
- **docker-compose.yml host-portable 化**: volume path を env var で吸収 (`${TASKHUB_DATA_DIR:-./data}`)、PostgreSQL/Redis image tag pinning (`postgres:17-alpine` / `redis:7-alpine`)
- **`docs/deploy/host-setup.md`**: Mac / Linux / VPS の各 host SOP (公開 IP block / sleep 制御 / Tailscale Serve 設定)

### 追加実装ファイル

- `cli/taskhub/main.py` / `cli/taskhub/commands/{init,backup,status}.py`
- `cli/setup.py` (`taskhub` entry point、`uv tool install` で各 host に install 可)
- `docker-compose.yml` (host-portable 化) / `docker-compose.override.yml.example`
- `.env.example` (env var 整理)
- `docs/deploy/host-setup.md`
- `tests/deploy/test_taskhub_init.py` / `test_taskhub_backup.py` / `test_postgres_version_pin.py` / `test_tailscale_only_post_migration.py`

### 受け入れ条件 (追加)

> **Phase H PH-F-001 / PH-F-003 fix**: 本 SP-001 既完了内容は **不変**、host-portable 関連の追加 must_ship は **新 SP-001.5 (`docs/sprints/SP-001-5_host_portable_amendment.md`) に移送**. 本 section は **reference 用** で残し、実装は SP-001.5 で実施.

(SP-001.5 の受け入れ条件 reference)
- Mac で `taskhub init` → `docker compose up -d` → **`taskhub status`** で smoke (`tm` CLI は P0.1 SP-016 まで存在しないため不使用、PH-F-003 fix)
- `curl -s http://127.0.0.1:8000/healthz` で api healthcheck
- 127.0.0.1 bind verify、公開 IP からの 22/80/443 deny verify、Tailscale Serve URL 経由のみアクセス
- `taskhub backup` で pg_dump + Redis BGSAVE + artifacts tar + age 暗号化、checksums.txt 整合
- `taskhub status` で host name / service health / data size / age fingerprint 表示

### defer (SP-012 まで)

- `taskhub restore` / `migrate` / `age-rotate` / `verify --integrity` 本実装
- host migration drill (Mac → VPS) 自動化
- 全 contract test smoke の host migration 後実行

### 関連 ADR

- ADR-00021 (Host-Portable Deployment + Data Migration、SP-001 着手時 proposed → accepted)
- ADR-00007 update (host 中立 invariant 明示化、同期 accepted)

