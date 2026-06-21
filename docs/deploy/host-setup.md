# host-setup.md — clean Mac から TaskManagedAI を起動する runbook (SP-PHASE0 S3)

> 大元計画 (PLAN-10) Phase 0「初回起動して使い始められる」土台層。clean な Mac で
> docker compose up → alembic upgrade → seed → /healthz green → MCP stdio → host worker start
> までを再現する最小 runbook。
>
> **重要 (SP-PHASE0 S3 制約)**:
> - 固定 migration head revision を **hardcode しない**。常に `alembic upgrade head` を使い、
>   到達確認は `alembic current` == repo の最新 `alembic heads` で行う (revision id をベタ書きしない)。
> - port は docker-compose の実値を使う: **frontend 3900 / api 8000 / postgres 5432 / redis 6379**
>   (すべて `127.0.0.1` loopback bind、ADR-00059。0.0.0.0 へ変更しない)。
> - secret 実値 (API key / token / age key) を本 doc やコマンド履歴に書かない (SecretBroker rules)。
>
> 関連 SOP: 詳細な検証 evidence 収集は `docs/deploy/mac-single-host-smoke-sop.md`、
> seed 詳細は `docs/deploy/dogfooding-seed-sop.md`、運用は `docs/deploy/operator-runbook.md`。

## 0. 前提 (clean Mac)

| 項目 | 確認 / 導入 |
|---|---|
| macOS | Darwin 13+ |
| Docker Desktop | running (compose v2) |
| port 空き | 3900 / 8000 / 5432 / 6379 (loopback) |
| uv | `curl -LsSf https://astral.sh/uv/install.sh \| sh` (Python ランタイム + 依存) |
| repo | `git clone` 済 (本 runbook の cwd = repo root) |
| age / jq | `brew install age jq` (backup / status 補助) |

CLI サブスク認証 (host-ambient、ADR-00058): host worker が `claude -p` / `codex exec` を
サブスク認証で起動するため、`claude` / `codex` CLI が **ログイン済**であること
(`~/.claude` / `~/.codex` の OAuth は CLI が所有・refresh、TaskManagedAI は raw token に触れない)。
Phase 0 では CLI 実行エンジン本体 (CLIAgentAdapter) は未配線 (大元計画 Phase 2)、本 runbook は起動土台のみ。

## 1. 環境ファイル (.env.local)

`.env.local` は **gitignored**。raw secret を commit しない (`.env.example` 等には placeholder のみ)。

```bash
cp .env.example .env.local   # 無ければ手動作成
# 最低限の設定 (development、loopback):
#   TASKMANAGEDAI_ENVIRONMENT=development
#   POSTGRES_PASSWORD=<dev-only-password>          # raw 値は .env.local のみ (gitignored)
#   TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET=<32+ chars>
#   TASKMANAGEDAI_DEV_LOGIN_TOKEN=<dev token>
```

- broker-managed provider API key は raw env で渡さない。`secret-create` で `secret_ref`
  (`secret://local/...`) として登録し、SecretBroker が in-process で消費する (§7 参照)。

## 2. docker compose up (postgres / redis / api / frontend)

base compose (`internal: true`、production 境界) + dev override (`internal: false`、loopback 公開) を重ねる。

起動 service は **明示列挙**し、`worker` は起動しない (Phase 0 既定で worker は §6 で host 起動するため、
docker worker を上げると二重稼働になる)。

```bash
export TASKMANAGEDAI_ENVIRONMENT=development
# worker は除外 (§6 で host 起動)。postgres/redis/api/frontend のみ。
docker compose -f docker-compose.yml -f docker-compose.dev.yml --env-file .env.local \
  up -d --build postgres redis api frontend
docker compose -f docker-compose.yml -f docker-compose.dev.yml --env-file .env.local ps
# expected: postgres / redis / api / frontend が healthy (worker は未起動)
```

> Phase 0 既定では **worker は docker でなく host で起動** する (§6、OAuth refresh の自然動作)。
> 上の `up` で `worker` を列挙しないことで docker worker と host worker の二重稼働を防ぐ。
> docker `worker` service は broker-managed / 非 CLI 経路向け (Phase 2+ で使用)。

## 3. alembic upgrade head (固定 revision を hardcode しない)

```bash
# api container 内で migration 適用 (alembic_wrapper が host-side DATABASE_URL override を strip)
bash scripts/alembic_wrapper.sh upgrade head
bash scripts/alembic_wrapper.sh current
bash scripts/alembic_wrapper.sh heads
# expected: current == heads (固定 revision id はここに書かない)
```

到達確認は CLI でも可能 (§8 の `taskhub status --local` の `alembic_up_to_date: true`)。

## 4. seed (initial default actor + dogfooding fixtures)

```bash
# dry-run で内容確認 → apply
docker compose -f docker-compose.yml -f docker-compose.dev.yml --env-file .env.local \
  exec api uv run python -m backend.app.cli.dogfooding_seed --dry-run
docker compose -f docker-compose.yml -f docker-compose.dev.yml --env-file .env.local \
  exec api uv run python -m backend.app.cli.dogfooding_seed --apply
```

詳細は `docs/deploy/dogfooding-seed-sop.md`。

## 5. /healthz green (起動確認)

```bash
curl -fsS http://127.0.0.1:8000/healthz | jq .          # expected: {"status":"ok",...}
curl -fsS http://127.0.0.1:3900 | head -20              # expected: Next.js HTML
docker compose -f docker-compose.yml -f docker-compose.dev.yml --env-file .env.local \
  exec redis redis-cli PING                             # expected: PONG
docker compose -f docker-compose.yml -f docker-compose.dev.yml --env-file .env.local \
  exec postgres psql -U taskmanagedai -d taskmanagedai -c "select version();" | head -3
```

## 6. host worker 起動 (Phase 0 既定)

worker は docker 外・host で起動 (CLI サブスク OAuth refresh の自然動作、`~/.claude` / `~/.codex` 直読)。
host から container へは loopback (`127.0.0.1`) で到達するため `TASKMANAGEDAI_DATABASE_URL` を
`127.0.0.1:5432` に向ける (docker internal hostname `postgres` は host から解決不可)。

```bash
# host shell (repo root)。raw secret は env に置かず .env.local 由来の dev 値のみ。
export TASKMANAGEDAI_ENVIRONMENT=development
export TASKMANAGEDAI_DATABASE_URL="postgresql+asyncpg://taskmanagedai:<dev-pwd>@127.0.0.1:5432/taskmanagedai"
export TASKMANAGEDAI_REDIS_URL="redis://127.0.0.1:6379/0"
uv run arq backend.app.workers.main.WorkerSettings
# expected: worker が queue を pickup (job 受信ログ)
```

## 7. MCP stdio (Claude Code / Codex から接続)

MCP server は stdio transport。host で起動し DB は `127.0.0.1:5432` に向ける (`.mcp.json` 参照)。

```bash
# 単発起動確認 (通常は MCP client = Claude Code / Codex が .mcp.json 経由で spawn)
TASKMANAGEDAI_DATABASE_URL="postgresql+asyncpg://taskmanagedai:<dev-pwd>@127.0.0.1:5432/taskmanagedai" \
  uv run python -m backend.app.mcp
```

`.mcp.json` の `taskmanagedai` server entry (`uv run python -m backend.app.mcp`) を Claude Code /
Codex が読む。DB URL は host 上実行のため `127.0.0.1` 固定 (Docker internal hostname 不可)。

## 8. secret 登録 (broker-managed local backend)

CLI サブスク credential は host-ambient (登録不要、§0)。broker-managed な static secret
(例: GitHub token、provider API key) は `taskhub secret-create` で登録する。raw material は
**getpass (対話) / stdin のみ** で入力し、argv には一切渡さない (`ps` で world-visible 防止)。

```bash
# 対話 (getpass、TTY echo なし)
uv run python scripts/taskhub_admin.py secret-create \
  --tenant-id 1 --scope project --name github-token \
  --allowed-consumers repo-proxy --allowed-operations repo.push,repo.pr_open
#   -> "secret material (input hidden): " で raw token を入力 (echo されない)

# stdin (pipe / 自動化)
printf '%s' "$RAW_TOKEN" | uv run python scripts/taskhub_admin.py secret-create \
  --tenant-id 1 --scope project --name github-token --material-stdin \
  --allowed-consumers repo-proxy --allowed-operations repo.push
```

rotate / revoke:

```bash
# rotate (新 version を pending+present で配置、active 化しない)
uv run python scripts/taskhub_admin.py secret-rotate \
  --tenant-id 1 --old-secret-ref-id <UUID> --new-version v2 \
  --allowed-consumers repo-proxy --allowed-operations repo.push   # material は getpass/stdin

# revoke (DESTRUCTIVE: signed approval gate)。material 削除は revoke 後 + secret-gc-orphans 収束。
uv run python scripts/taskhub_admin.py secret-revoke --tenant-id 1 --secret-ref-id <UUID> \
  --approval-id <signed-approval-id>
uv run python scripts/taskhub_admin.py secret-gc-orphans --tenant-id 1   # purge backstop
```

成功時は **非機密 metadata (secret_uri / status / material_state) のみ** 出力。raw material は echo しない。

## 9. local 起動状態の確認 (minimal-but-real)

```bash
uv run python scripts/taskhub_admin.py status --local
# JSON: environment / db_reachable / alembic_head_in_db / alembic_head_expected /
#       alembic_up_to_date (固定 head は hardcode せず ScriptDirectory から runtime 取得)
uv run python scripts/taskhub_admin.py init --local
# 同上 + next_step ガイド (alembic_up_to_date=false なら 'alembic upgrade head')
```

## 10. 停止 / 片付け (docker-stack-hygiene)

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml --env-file .env.local down
# 実運用 volume (taskmanagedai_postgres_data / _redis_data) は保持 (down -v は禁止、
# docker-stack-hygiene §3)。検証 stack のみ専用 project/port/throwaway volume で立て down -v。
```

## 参照

- ADR-00058 (LocalSecretStore + URI scheme + CLI 認証境界=案C hybrid)
- ADR-00059 (loopback bind 決着 + revoke material 削除 + durable reconciliation)
- ADR-00021 §3 (host-portable deployment CLI table) / DD-05 (network) / DD-06 (secret)
- `docs/deploy/mac-single-host-smoke-sop.md` (詳細検証 evidence)
- `docs/deploy/dogfooding-seed-sop.md` (seed) / `docs/deploy/operator-runbook.md` (運用)
- `docs/sprints/SP-PHASE0_local_bootstrap.md` (本 Sprint Pack)
