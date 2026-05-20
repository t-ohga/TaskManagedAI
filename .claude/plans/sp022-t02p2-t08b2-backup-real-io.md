# SP022-T02 Phase 2 + T08 batch 2: backup real I/O orchestration

最終更新: 2026-05-20 (r4、R1 14 + R2 2 + R3 1 = 17 findings 全件 adopt: R3 CRITICAL×1 (env allowlist の secret 経路廃止、.pgpass file approach))

`plan_status`: 🟥 heavy + phase/batch 分割の atomic 単位 (T02 Phase 2 = T08 batch 2 = backup orchestration、scope 重複部分を一体化で実装)

## 1. 目的 (Goal)

ADR-00021 §3 + §4 (taskhub admin CLI spec + backup file 構造) で明文化された **`taskhub backup --output <path>.tar.age`** の real I/O orchestration を実装。

T02 Phase 1 (PR #75) で確立済 security boundary (signed approval gate + Ed25519 verify + automation detection) を継承しつつ、skeleton 出力を **実 backup orchestration logic** に置き換える。

具体的に本 batch で:

1. `scripts/taskhub_backup_orchestrator.py` (NEW): backup orchestration logic
   - `meta.json` builder (host / timestamp / postgres_version / redis_version / alembic_head)
   - `checksums.txt` builder (各 file の SHA-256 hex)
   - subprocess wrapper layer (pg_dump / redis-cli BGSAVE + RDB read / tar / age encrypt)
   - file layout builder (ADR-00021 §4 structure: postgres/ + redis/ + artifacts/ + env.encrypted + meta.json + checksums.txt)
   - **pure-function 部 vs subprocess 部の分離** (testability + autonomous verification)
2. `scripts/taskhub_admin.py` `_cmd_backup` integration: skeleton 出力を実 orchestration に置き換え
3. unit tests: pure 部 100% test、subprocess 部は `unittest.mock.patch` で mock
4. integration tests stub: `@pytest.mark.skipif(not _tools_installed())` で actual tool 利用時のみ run、本 autonomous session では skip、SP022-T09 実機 drill で覆われる
5. ADR-00021 §4 backup file 構造との bidirectional contract (restore は T02 Phase 3 / T08 batch 3 で実装、本 batch は backup 出力側のみ)

## 2. 背景 (Background)

- T02 Phase 1 (PR #75 merged): signed approval Ed25519 gate + default deny + automation detection 確立、`_cmd_backup` は gate 通過後に skeleton output
- T08 batch 1 (PR #76 merged): signed journal verification CLI (offline JSONL)、別 scope の operational tool
- ADR-00021 §3 backup spec (本 batch で実装):
  - 入力: `--output <path>` (`.tar.age` 拡張子) + `[--include-sops-env]` (option)
  - 出力: age 暗号化 tar (内容は ADR-00021 §4 structure)
  - 動作: 全 service stop (graceful) → pg_dump + Redis BGSAVE + artifacts tar + (option) `.env.encrypted` → age 公開鍵で暗号化
  - **age private key は backup に含めない** (CRITICAL invariant)
- 本 autonomous session の制限:
  - pg_dump / pg_restore / redis-cli / age tools が **not installed** (CLI smoke test 不可)
  - Docker / pg / Redis service が **not running** (actual backup integration test 不可)
  - 対応: subprocess wrapping を `unittest.mock.patch` で 100% mock、actual drill validation を SP022-T09 carry-over として明文化
- Phase 分割 (`.claude/reference/task-planning-matrix.md` §2):
  - **本 batch (T02 Phase 2 = T08 batch 2)**: backup orchestration only (出力側)
  - T02 Phase 3 = T08 batch 3: restore orchestration (入力側、`taskhub restore`)
  - T02 Phase 4 = T08 batch 5: migrate orchestration (backup + transfer + remote restore)、freeze-thaw

## 3. Scope (実装範囲)

### 3.1 must_ship (本 PR 内)

| # | 対象 | 種別 |
|---|---|---|
| 1 | `scripts/taskhub_subprocess_runner.py` (NEW) | F-009 adopt: 共通 subprocess runner (`run_safe_subprocess`) — timeout / shell=False / cwd / env allowlist / stdin closed / capture_output / sanitized stderr mapping / argv logging policy (raw password / secret は argv / stderr / audit に出さない) |
| 2 | `scripts/taskhub_backup_orchestrator.py` (NEW) | backup orchestration module: pure `BackupLayoutBuilder` (meta.json + checksums.txt + archive allowlist) + subprocess wrapper `BackupOrchestrator` (pg_dump / Redis `--rdb` mode / tar / age) + 専用例外型 (`BackupUsageError` exit 2 / `BackupRuntimeError` exit 1 / `BackupToolNotFoundError` exit 2) + **reason_code 整理 (terminal 14 + warning 3 別 field)** (F-010 adopt) |
| 3 | `scripts/taskhub_admin.py` `_cmd_backup` (MODIFY) | skeleton 出力を real orchestration 呼出に置き換え、signed approval gate (T02 Phase 1) を維持 + **新引数全件を approval claim payload に含める** (F-004 adopt: output_path / include_sops_env / skip_service_stop / overwrite / age_public_key_fingerprint / timestamp_window) |
| 4 | `scripts/taskhub_signed_approval.py` (MODIFY) | F-004 adopt: ApprovalRecord schema 拡張 — `backup_claim` optional sub-record (output_path / include_sops_env / skip_service_stop / overwrite / age_public_key_fingerprint)、`taskhub backup` の signed approval gate で claim mismatch を deny |
| 5 | `tests/scripts/test_taskhub_subprocess_runner.py` (NEW) | F-009 adopt: subprocess runner contract tests (timeout / env allowlist / stderr sanitize / fake tool fixture) |
| 6 | `tests/scripts/test_taskhub_backup_orchestrator.py` (NEW) | unit fixtures (pure + mock) + **fake tool fixtures** (F-013 adopt: PATH override で fake `pg_dump` / `redis-cli` / `age` executable) で argv contract verify |
| 7 | `tests/scripts/test_taskhub_admin.py` (MODIFY) | `taskhub backup` CLI integration fixture を skeleton 期待から real orchestration mock 期待に更新 + approval claim mismatch negative |
| 8 | `tests/deploy/test_taskhub_backup_integration.py` (NEW) | F-014 adopt: `@pytest.mark.skipif` で actual tool 不在時 skip、SP022-T09 drill での actual execution mandatory checklist marker |
| 9 | `.claude/plans/sp022-t02p2-t08b2-backup-real-io.md` (本計画、commit 含む) | - |
| 10 | `docs/sprints/SP-022_framework_intake_hardening.md` (MODIFY) | `## Review` に completion record、`plan_status` を "Phase 2 / batch 2 完了済 PR #77" annotation |
| 11 | `docs/deploy/half-yearly-drill-sop.md` (MODIFY) | F-014 adopt: §3 + **新 §11 SP022-T09 mandatory drill checklist** (actual `taskhub backup` 実行 / age decrypt dry-run / tar listing / checksums verify / pg_restore 互換 / private key 非混入 / cleanup verify) — T09 がこの checklist なしに完了不可 |
| 12 | `docs/adr/00021_host_portable_deployment.md` (MODIFY、optional) | F-008 adopt: §3 backup spec に meta.json 取得 source の明文化 (pg query / Redis INFO / alembic table) 追記、ADR-00021 既存テキスト追補 |

### 3.2 対象外 (本 batch では実装しない)

- **`taskhub restore` real I/O** (age decrypt / pg_restore / volume move / rollback): T02 Phase 3 / T08 batch 3 で実装
- **`taskhub migrate` orchestration** (backup → Tailscale transfer → target restore): T02 Phase 4 / T08 batch 5
- **`taskhub freeze` / `taskhub thaw` signed marker + 2-party-control**: T02 Phase 4
- **age key rotation 自動化**: T08 batch 別 (age-rotate subcommand)
- **service stop / start automation (Docker Compose)**: 本 batch では `--skip-service-stop` flag を提供 (Docker 不在環境で test 用)、actual `docker compose stop` invocation は SP022-T09 drill で覆う
- **actual pg_dump / age tool 利用 integration test**: 本 autonomous session では mock のみ、real tool execution は `tests/deploy/test_taskhub_backup_integration.py` (NEW、本 batch で skip stub) で SP022-T09 drill phase に carry-over
- **Tailscale transfer** (backup file の remote host 転送): T02 Phase 4 / T08 batch 5
- **Pure signed_journal_core.py 抽出** (T08 batch 1 R2-F-001 carry-over): 本 batch では touch しない

## 4. アーキテクチャ設計

### 4.1 Module 構造

```
scripts/taskhub_backup_orchestrator.py
├── BackupOptions (dataclass): host name / timestamp / output path / include_sops_env / skip_service_stop / ...
├── BackupResult (dataclass): output_path / sha256 / entry_count / postgres_version / ...
├── BackupUsageError / BackupRuntimeError / BackupToolNotFoundError (exception types)
│
├── ── pure functions (testable without subprocess) ──
├── build_meta_json(...) -> dict[str, Any]
├── build_checksums_text(file_paths) -> str
├── resolve_backup_temp_layout(output_path) -> BackupLayout (tmp dir + sub-paths)
├── ── subprocess wrappers (test-mocked) ──
├── invoke_pg_dump(host, user, db, output_path, ...) -> None | raises BackupRuntimeError
├── invoke_redis_bgsave(host, port, output_dir, ...) -> Path
├── create_artifacts_tar(source_dir, output_path) -> None
├── invoke_age_encrypt(input_path, output_path, public_key_path) -> None
├── ── orchestration layer ──
├── run_backup(options: BackupOptions) -> BackupResult
```

### 4.2 Pure vs subprocess 分離

**Pure functions (100% testable autonomously、Docker/pg/age 不要):**
- `build_meta_json`: dict 構築のみ、subprocess 呼ばない
- `build_checksums_text`: 与えられた file paths から SHA-256 hex 集約、actual file read は test fixture file で OK (subprocess 不要)
- `resolve_backup_temp_layout`: pathlib のみ、subprocess 呼ばない

**Subprocess wrappers (test-mocked):**
- `invoke_pg_dump`: `subprocess.run(["pg_dump", ...])` を mock で `MagicMock` 化、output file は test fixture が pre-place
- `invoke_redis_bgsave`: 同上、Redis BGSAVE → `dump.rdb` を mock pre-place
- `create_artifacts_tar`: tarfile (Python stdlib、subprocess 不要) で実装、actual tar tool 不要
- `invoke_age_encrypt`: `subprocess.run(["age", "-r", public_key, ...])` を mock

**Orchestration layer:**
- `run_backup`: 上記 wrappers を順次呼ぶ、各 step の failure は `BackupRuntimeError` / `BackupToolNotFoundError` で structured deny

### 4.3 Failure handling — reason_code (F-010 adopt: terminal vs warning 別 field)

**terminal reason_codes** (orchestration の exit 判定の主理由、result `reason_code` field):

| reason_code | trigger | exit code |
|---|---|---|
| `backup_completed` | 全 step PASS | 0 |
| `backup_output_path_invalid` | `--output` が `.tar.age` 拡張子でない / parent dir 不在 / write 不能 | 2 |
| `backup_output_already_exists` | `--output` file が既に存在 (`--overwrite` flag 未指定) | 2 |
| `backup_temp_dir_creation_failed` | tmp working dir 作成失敗 | 2 |
| `backup_archive_allowlist_violation` | F-001 adopt: archive 対象が allowlist 外 (private key pattern / symlink 経由 外部参照 / .sops/age/keys.txt 等) | 1 |
| `backup_meta_json_acquisition_failed` | F-008 adopt: PostgreSQL version / Redis version / alembic head 取得不能 (runtime/config error として、usage error から再分類) | 1 |
| `backup_pg_dump_tool_not_found` | `pg_dump` command 不在 | 2 |
| `backup_pg_dump_failed` | pg_dump exit != 0 | 1 |
| `backup_redis_rdb_tool_not_found` | `redis-cli` command 不在 | 2 |
| `backup_redis_rdb_failed` | F-006 adopt: `redis-cli --rdb <path>` 失敗 (server-side BGSAVE → local copy 経路の方式選択) | 1 |
| `backup_artifacts_tar_failed` | tarfile creation 失敗 (Python stdlib `tarfile` 経由、permission / disk space / 大 file) | 1 |
| `backup_age_tool_not_found` | `age` command 不在 | 2 |
| `backup_age_encrypt_failed` | age exit != 0 / age public key 不在 / output file 生成失敗 | 1 |
| `backup_checksum_calculation_failed` | sha256 file read error (`checksums.txt` 生成失敗) | 1 |
| `backup_tmp_cleanup_failed` | F-002 adopt: cleanup OSError、tmp dir に secret-bearing content が残った場合は CRITICAL audit event emit + exit 1 (silent ignore しない) | 1 |
| `backup_approval_claim_mismatch` | F-004 adopt: approval record の `backup_claim` と CLI 引数 (output_path / include_sops_env / skip_service_stop / overwrite / age_public_key_fingerprint) 不一致 | 2 |
| `backup_unexpected_error` | uncaught exception (CRITICAL: stderr に raw exc message 出さない、sanitized message のみ) | 1 |

**warning-only codes** (`result["warnings"]` array、terminal ではない):

| warning_code | trigger | result への影響 |
|---|---|---|
| `backup_sops_env_skipped` | `--include-sops-env` 指定 + `.env.encrypted` 不在 → warning (backup 継続、env.encrypted を archive から除外) | result["warnings"] 追加、reason_code は backup_completed 維持 |
| `backup_service_stop_skipped` | `--skip-service-stop` 指定 (test/dev env 用、production drill では使用禁止) | 同上 |
| `backup_artifacts_dir_empty` | artifacts_dir 不在 / 空 → 空 directory を archive に含める | 同上 |

### 4.4 BackupOptions (引数) + defaults source-of-truth (F-007 adopt)

```python
@dataclasses.dataclass(frozen=True)
class BackupOptions:
    output_path: Path           # --output <path>.tar.age
    host_name: str              # socket.gethostname() default
    include_sops_env: bool      # --include-sops-env (option)
    skip_service_stop: bool     # --skip-service-stop (test env only)
    overwrite: bool             # --overwrite (default False)
    age_public_key_path: Path   # ~/.taskhub/keys/age.pub default
    pg_host: str                # PostgreSQL host
    pg_port: int                # PostgreSQL port
    pg_user: str
    pg_db: str
    redis_host: str
    redis_port: int
    artifacts_dir: Path
    sops_env_path: Path
    pg_dump_timeout_sec: int    # default 1800
    redis_rdb_timeout_sec: int  # default 300
    age_encrypt_timeout_sec: int  # default 600
```

**F-007 adopt — defaults source-of-truth precedence** (highest priority に降順):

1. CLI argument 明示指定 (`--output` 等)
2. environment variable (`TASKHUB_BACKUP_PG_HOST` / `TASKHUB_BACKUP_REDIS_PORT` 等、prefix `TASKHUB_BACKUP_*`)
3. `docker-compose.yml` parse (`services.postgres.ports` / `services.redis.ports` を YAML-parse、env-file substitution 不要)
4. hardcoded defaults: `pg_host=127.0.0.1`, `pg_port=5432`, `pg_user=taskhub`, `pg_db=taskhub`, `redis_host=127.0.0.1`, `redis_port=6379`, `artifacts_dir=<repo_root>/data/artifacts`, `sops_env_path=<repo_root>/.env.encrypted`, `age_public_key_path=~/.taskhub/keys/age.pub`

`BackupOptions.from_environment(repo_root: Path) -> BackupOptions` 関数を提供、precedence chain を 1 箇所で実装、verifiable test (env override / docker-compose.yml parse / hardcoded fallback の 3 path)。

### 4.5 backup sequence (11 step、F-003 + F-005 + F-006 + F-008 adopt)

1. validate `BackupOptions` (output path / overwrite / age public key existence)
2. **approval claim verification** (F-004 adopt): signed approval record の `backup_claim` と全 CLI 引数 + age public key fingerprint を照合、mismatch なら `backup_approval_claim_mismatch` で deny
3. resolve backup temp layout: **R2-F-002 adopt** — `tempfile.mkdtemp()` は `mode` 引数を受け取らない (Python stdlib 仕様)、`tempfile.mkdtemp(prefix="taskhub-backup-", dir=<parent>)` で作成後 `os.chmod(tmp_dir, 0o700)` + `stat.S_IMODE(tmp_dir.stat().st_mode) == 0o700` verify、不一致は `backup_temp_dir_creation_failed` で fail-closed (F-002 adopt 反映)
4. **F-003 adopt — service stop policy**: 本 batch では PostgreSQL / Redis は **稼働維持** (dump 完了まで required)、app/API/worker は本 batch で stop しない (T02 Phase 4 freeze で実施、ADR-00021 §3 「全 service stop」表現は app-layer freeze を指すと再解釈)。`--skip-service-stop` は no-op flag として残す (test 用、production drill では使用禁止 warning を audit に emit)
5. **meta.json data acquisition** (F-008 adopt):
   - PostgreSQL version: `pg_dump --version` 出力 parse (or `pg_query SELECT version()` 経由)
   - Redis version: `redis-cli INFO server` 出力から `redis_version` parse
   - alembic head: `alembic current` CLI 出力 parse (or DB の `alembic_version` table 直接 query)
   - 取得不能は `backup_meta_json_acquisition_failed` で deny (runtime error 分類)
6. invoke `pg_dump --format=custom --no-acl --no-owner --single-transaction -h <host> -p <port> -U <user> -d <db> -f tmp/postgres/pg_dump.dump` (F-011 adopt: `.dump` 拡張子、custom format binary、`--single-transaction` で consistent snapshot)
7. write `tmp/postgres/alembic_version.txt` from acquired alembic head
8. **F-006 adopt — Redis backup mechanism**: `redis-cli --rdb tmp/redis/dump.rdb -h <host> -p <port>` を使用 (server-side BGSAVE の LASTSAVE poll は複雑、`--rdb` flag が client side で直接 dump file を pull する Redis 5+ standard mechanism)
9. **F-001 adopt — artifacts copy with allowlist enforcement**:
   - artifacts_dir 配下を walk、`_ARCHIVE_ALLOWLIST` (whitelist regex set) に match する file のみ copy
   - **明示 reject patterns** (private key / SSH key / age identity / SOPS age key):
     - file name pattern: `**/id_rsa`, `**/id_ed25519`, `**/id_ecdsa`, `**/age*.txt`, `**/age*.pem`, `**/.sops/age/keys.txt`, `**/age-key*`, `**/*.age-identity`, `**/*.private.pem`, `**/*-private.pem`, `**/*.key.pem`
     - content sniff: 最初の 4KB を read、`-----BEGIN OPENSSH PRIVATE KEY-----` / `-----BEGIN PRIVATE KEY-----` / `-----BEGIN RSA PRIVATE KEY-----` / `AGE-SECRET-KEY-` prefix を contains なら reject
     - symlink: 全 reject (allowlist 経由 외 file 参照 unconditional deny)
10. (optional) copy `.env.encrypted` → `tmp/env.encrypted` (`--include-sops-env` 指定時のみ、SOPS-encrypted のまま、decrypt しない)
11. build `meta.json` + `checksums.txt` (F-012 adopt: spec § 4.7)
12. tar `tmp/` (Python stdlib `tarfile`、symlink dereference false、deterministic order) → age encrypt: `age -r <public_key> -o <output>.tar.age.part` (F-005 adopt: `output.name + ".part"` で同 dir、success 後 `os.replace` で atomic rename to final name) → 元 part 削除
13. cleanup tmp dir: `shutil.rmtree(tmp_dir, ignore_errors=False)`、OSError は `backup_tmp_cleanup_failed` audit event + exit 1 (F-002 adopt: silent ignore しない、secret-bearing tmp が残った場合 CRITICAL)

### 4.6 raw secret leakage 0 invariant (CRITICAL、F-001 + F-002 + F-009 adopt 反映)

- age **private key** は本 batch で touch しない (`age` subprocess は `-r <public_key>` のみ受け取る)
- archive allowlist で private key pattern を物理 reject (filename + content sniff + symlink reject)
- tmp dir は `mkdtemp(mode=0o700)` で **0700 private permission**、所有者以外 read 不可
- tmp dir cleanup 失敗は **audit event emit + exit 1**、silent ignore しない (F-002 adopt)
- SOPS-encrypted `.env.encrypted` はそのまま tar (decrypt しない、age + SOPS 二重暗号化 invariant)
- pg_dump output には DB raw value 含まれる可能性、age 暗号化前は 0700 tmp dir 内のみ、success 後即 cleanup
- F-009 adopt — subprocess runner contract:
  - `shell=False` 固定 (shell injection 防止)
  - `stdin=subprocess.DEVNULL` (interactive password prompt hang 防止)
  - `timeout=<configured>` 必須 (default 30 min for pg_dump、5 min for others)
  - `env=<allowlist>` (PATH / HOME / LANG など最小限のみ pass through、credentials env は明示 list)
  - **argv に raw password を含めない** invariant: pg credentials は **temp `.pgpass` file** (0600 permission、`tempfile.NamedTemporaryFile` + `os.chmod(0o600)`) を作成、child env には `PGPASSFILE=<temp-path>` のみ渡す (R3-F-001 adopt: `PGPASSWORD` env は **禁止**、secret-via-env 経路を廃止)
  - Redis 認証は本 batch では **fail-closed** (Redis AUTH 必須環境では別 batch で redis config file 経由を実装、`REDISCLI_AUTH` env は **禁止**、R3-F-001 adopt)
  - subprocess env allowlist: `PATH`, `HOME`, `LANG`, `LC_ALL`, `TZ`, `PGPASSFILE` (temp 経由のみ、絶対 path)、その他 secret-like env (`PGPASSWORD`, `REDISCLI_AUTH`, `AWS_SECRET_*`, `*_TOKEN`, `*_KEY`, `*_PASSWORD`) は **明示 reject** (regex-based exclusion + audit warning)
  - stderr capture + sanitization: secret pattern (`-----BEGIN`, `AGE-SECRET-KEY-`, password=, etc.) は stderr 出力から redact、stdout は sanitize しない (pg_dump binary output)
  - argv logging policy: argv 全体は audit に含めず、`command_name` + `arg_count` + `sanitized_flags` のみ記録

### 4.7 checksums.txt spec (F-012 adopt)

Format: `<sha256-hex>  <relative-posix-path>\n` (line ごと、GNU `sha256sum` 互換、`<hash><two-spaces><path>` で `sha256sum -c` 直接 verify 可能)。

- Path: relative POSIX path、backup tmp root を基準 (例: `postgres/pg_dump.dump`, `redis/dump.rdb`, `meta.json`)
- Sort order: byte-lexicographical (POSIX path string、deterministic、`sorted(paths)` ベース)
- 対象から除外: `checksums.txt` 自身 (self-reference recursion 防止)
- symlink: archive allowlist で全 reject なので checksums にも含めず
- empty dir: tarfile に含めるが checksums には登場しない (file のみ hash 対象)
- file permission: hash 対象は content のみ (permission / xattr は対象外、cross-platform deterministic)
- tar entry path normalization: archive 作成時に `name=relative_posix_path` を指定、tarfile デフォルトは absolute path resolution を含むため明示 override

restore Phase 3 では `checksums.txt` を読み、各 file の sha256 を再計算して deterministic verify (`sha256sum -c checksums.txt` 互換)。

### 4.8 Archive allowlist (F-001 adopt)

`_ARCHIVE_ALLOWLIST_PATTERNS` (relative path glob) — 本 batch で archive 対象として許可される path:

```python
_ARCHIVE_ALLOWLIST_PATTERNS = (
    "meta.json",
    "checksums.txt",
    "postgres/pg_dump.dump",
    "postgres/alembic_version.txt",
    "redis/dump.rdb",
    "redis/appendonly.aof",  # optional, present only if Redis AOF enabled
    "env.encrypted",         # optional, present only if --include-sops-env
    "artifacts/**",          # recursive、但し下記 deny patterns で filter
)
```

`_ARCHIVE_DENY_PATTERNS` (artifacts/ 配下にも適用、F-001 adopt):

```python
_ARCHIVE_DENY_FILENAME_PATTERNS = (
    "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa",
    "age-key*", "*age-identity*", "keys.txt",   # age identity / SOPS age key
    "*.private.pem", "*-private.pem", "*.key.pem",
    "*.gpg", "*.pgp",                            # PGP keys
)

_ARCHIVE_DENY_CONTENT_PREFIXES = (
    b"-----BEGIN OPENSSH PRIVATE KEY-----",
    b"-----BEGIN RSA PRIVATE KEY-----",
    b"-----BEGIN PRIVATE KEY-----",
    b"-----BEGIN EC PRIVATE KEY-----",
    b"-----BEGIN DSA PRIVATE KEY-----",
    b"-----BEGIN PGP PRIVATE KEY BLOCK-----",
    b"AGE-SECRET-KEY-",
)
```

`_check_archive_allowed(relative_path, abs_path) -> tuple[bool, str | None]`:
- relative_path が allowlist glob にいずれも match しない → reject
- abs_path が symlink → reject
- filename が deny pattern match → reject  
- 最初の 4KB content が deny content prefix match → reject
- 全 pass で True

reject 時は `BackupRuntimeError("backup_archive_allowlist_violation", detail="path=<sanitized>, reason=<filename_pattern|symlink|content_prefix>")` raise (raw filename を sanitize、`_sanitize_token` 経由)。

### 4.9 Approval claim coverage (F-004 adopt)

T02 Phase 1 の `ApprovalRecord` schema を拡張、`backup_claim` optional sub-field を追加:

```python
@dataclasses.dataclass(frozen=True)
class BackupApprovalClaim:
    output_path: str           # exact match (absolute path string after normpath)
    include_sops_env: bool
    skip_service_stop: bool
    overwrite: bool
    age_public_key_fingerprint: str  # SHA-256 of age public key bytes
```

`verify_signed_approval()` で subcommand == "backup" の場合、record.backup_claim と CLI 引数 + age public key fingerprint を比較、一致しないと `backup_approval_claim_mismatch` deny。

approval record schema (RFC 8785 canonical payload) も拡張、signature 対象に backup_claim を含める。

**R2-F-001 adopt (CRITICAL) — API extension + backwards compat 厳密化**:

1. `require_approval_for_destructive()` の signature を拡張:
   ```python
   def require_approval_for_destructive(
       subcommand: str, approval_id: str | None, from_automation: bool,
       allow_unsigned_manual_skeleton: bool,
       target_host: str | None = None,
       backup_claim: BackupApprovalClaim | None = None,  # NEW
   ) -> tuple[bool, ReasonCode, dict[str, object]]:
   ```
2. `verify_signed_approval()` も同様に `backup_claim` 受領、record.backup_claim と比較
3. **backup subcommand では `--allow-unsigned-manual-skeleton` を明示 deny**: `_cmd_backup` 冒頭で `if args.allow_unsigned_manual_skeleton: return 2` (T02 Phase 1 escape は backup real I/O 化後に backup 経路から削除、他 destructive (restore/migrate/freeze/thaw/age-rotate) は Phase 2 carry-over として escape を維持)
4. **backup_claim 必須化 logic**:
   - subcommand == "backup" AND approval_id provided → record の backup_claim 必須、不在は `backup_approval_claim_mismatch` deny
   - subcommand != "backup" → backup_claim 不在 OK (backwards compat)
   - subcommand == "backup" AND approval_id 未指定 (`--allow-unsigned-manual-skeleton` も既に deny 済) → automation env 必須 + approval_id 必須
5. T02 Phase 1 既存 ApprovalRecord (backup_claim 不在) は **backup 以外の subcommand では従来通り verify**、backup では deny (新 record format 必須)
6. test fixture:
   - backup_claim 不在 record で backup → deny verify
   - backup_claim 不在 record で restore / migrate 等 → 従来 verify pass (T02 Phase 1 fixture 維持)
   - backup_claim 存在で backup → claim mismatch (output_path 違反等) negative test + 完全一致 positive test
   - `--allow-unsigned-manual-skeleton` + backup → explicit deny (新 fixture)

## 5. 実装詳細 (詳細は R2-R3 で確定後に最終 skeleton 化)

### 5.1 `scripts/taskhub_backup_orchestrator.py` skeleton structure

(plan-review R1 後に具体化、本 plan §4 architecture を base に)

### 5.2 `scripts/taskhub_admin.py` `_cmd_backup` integration

T02 Phase 1 の signed approval gate を維持しつつ、skeleton 出力を `BackupOrchestrator.run_backup` 呼出に置き換え:

```python
def _cmd_backup(args: argparse.Namespace) -> int:
    allowed, reason = _run_approval_gate("backup", args)
    if not allowed:
        # ... (T02 Phase 1 既存 logic 維持)
        return 2
    # T02 Phase 2 / T08 batch 2: real orchestration
    from scripts.taskhub_backup_orchestrator import (
        BackupOptions, BackupUsageError, BackupRuntimeError, run_backup,
    )
    options = BackupOptions(
        output_path=Path(args.output),
        host_name=socket.gethostname(),
        include_sops_env=args.include_sops_env,
        skip_service_stop=args.skip_service_stop,
        overwrite=args.overwrite,
        # ... (defaults from env / config)
    )
    try:
        result = run_backup(options)
    except BackupUsageError as exc:
        print(exc.stderr_message(), file=sys.stderr)
        return 2
    except BackupRuntimeError as exc:
        print(exc.stderr_message(), file=sys.stderr)
        return 1
    print(json.dumps(result.summary(), sort_keys=True))
    return 0
```

新引数:
- `--skip-service-stop`: Docker 不在環境 (test) で `docker compose stop` を skip
- `--overwrite`: 既存 `--output` file 上書き許可 (default False、accidental overwrite 防止)

### 5.3 Test strategy (3 layer: pure / fake tool / mock)

**Layer 1 — Pure function tests (subprocess 不要、fully autonomous-verifiable):**
- `test_build_meta_json_includes_required_fields`
- `test_build_meta_json_postgres_version_acquisition` (mock pg_dump --version 出力 parse)
- `test_build_checksums_text_deterministic` (固定 fixture file から固定 SHA-256 出力、`sha256sum -c` 互換 format verify)
- `test_build_checksums_text_excludes_self` (`checksums.txt` 自身は除外)
- `test_build_checksums_text_sort_order_byte_lex` (sort 順固定)
- `test_resolve_backup_temp_layout_creates_0700_dir` (mode 0o700 verify、F-002 adopt)
- `test_backup_options_validation_rejects_invalid_extension`
- `test_backup_options_from_environment_precedence_chain` (CLI / env / docker-compose / hardcoded、F-007 adopt)
- `test_check_archive_allowed_rejects_private_key_filename` (F-001 adopt: id_rsa / age-key.txt 等)
- `test_check_archive_allowed_rejects_private_key_content_prefix` (`-----BEGIN OPENSSH PRIVATE KEY-----` 等)
- `test_check_archive_allowed_rejects_symlink` (symlink 全 reject)
- `test_check_archive_allowed_accepts_artifacts_normal_file`
- `test_backup_approval_claim_validation_field_match` (F-004 adopt)

**Layer 2 — Fake tool fixtures (F-013 adopt、PATH override で argv contract verify):**
- `conftest.py` で `fake_pg_dump` / `fake_redis_cli` / `fake_age` shell script を tmp/bin に置き、monkeypatch.setenv("PATH", f"{tmp/bin}:{os.environ['PATH']}") で先頭に挿入
- fake tool は argv を `tmp/argv-log.json` に記録、指定 output path に minimal valid file を pre-place、配色 exit code を出力
- `test_invoke_pg_dump_argv_contract` (fake `pg_dump --version` で minimal banner、`pg_dump -h <host> ... -f <output>` で argv を JSON 記録、output path に dummy bytes)
- `test_invoke_pg_dump_failure_propagates_runtime_error` (fake で exit 1、stderr に error message、orchestrator が BackupRuntimeError raise)
- `test_invoke_pg_dump_timeout_terminates` (fake が sleep、timeout で `subprocess.TimeoutExpired` → BackupRuntimeError、F-009 adopt)
- `test_invoke_pg_dump_tool_not_found_raises_tool_not_found` (PATH に fake pg_dump 不在、FileNotFoundError → BackupToolNotFoundError)
- `test_invoke_redis_cli_rdb_argv_contract` (`redis-cli --rdb <path>` argv 記録、F-006 adopt の方式選択 verify)
- `test_invoke_age_encrypt_argv_uses_public_key_only` (argv に `-r <public_key>` のみ、private key path / decryption flag を含まない、F-001 + raw secret leakage 0 invariant)
- `test_invoke_age_encrypt_failure_no_partial_output` (fake age exit 1 → final `.tar.age` 不在、`.part` も削除、F-005 adopt)
- `test_subprocess_runner_stdin_devnull_no_password_prompt_hang` (F-009 adopt: stdin=DEVNULL で hang しない)
- `test_subprocess_runner_env_allowlist_excludes_secrets` (`PGPASSWORD` / `REDISCLI_AUTH` / `AWS_SECRET_*` / `*_TOKEN` / `*_KEY` / `*_PASSWORD` 全 reject、`PGPASSFILE` のみ pg credentials 経路として allow、F-009 + R3-F-001 adopt)
- `test_pgpass_temp_file_created_with_0600_permission` (R3-F-001 adopt: temp .pgpass で credentials を file 経由 + 0600 verify)
- `test_pgpass_temp_file_cleanup_on_exit` (backup orchestration の cleanup 経路で temp .pgpass も削除)
- `test_subprocess_runner_stderr_sanitization_redacts_secrets` (fake が `password=hunter2` を stderr に出す、runner が `[REDACTED]` で置換、F-009 adopt)

**Layer 3 — Orchestration mock tests (`subprocess.run` mock、step sequencing 確認):**
- `test_run_backup_full_sequence_success` (all 13 steps mocked、`.tar.age` file existence + final reason_code=backup_completed)
- `test_run_backup_pg_dump_failure_cleans_tmp_dir` (cleanup 確実 + tmp dir 不在 verify)
- `test_run_backup_redis_failure_cleans_tmp_dir`
- `test_run_backup_age_encrypt_failure_does_not_leave_partial_output` (no `.part` + no final `.tar.age`、F-005 adopt)
- `test_run_backup_output_already_exists_without_overwrite_rejected`
- `test_run_backup_with_sops_env_includes_in_archive`
- `test_run_backup_with_skip_service_stop_emits_warning` (warning code in result["warnings"])
- `test_run_backup_approval_claim_mismatch_rejected` (F-004 adopt: backup_claim.output_path 不一致 → deny)
- `test_run_backup_archive_allowlist_violation_in_artifacts_aborts` (F-001 adopt: artifacts/ 配下に private key file → abort)
- `test_run_backup_tmp_cleanup_failure_emits_audit_event` (F-002 adopt: shutil.rmtree raise OSError → audit + exit 1)
- `test_run_backup_keyboard_interrupt_cleans_tmp` (F-002 adopt: SIGINT 経路でも cleanup)
- `test_run_backup_partial_output_atomic_rename` (F-005 adopt: success path で `.part` → final、failure 路で `.part` 削除)

**Layer 4 — Real tool integration stubs (skip if not installed、SP022-T09 carry-over):**
- `tests/deploy/test_taskhub_backup_integration.py` (NEW): `@pytest.mark.skipif(not (shutil.which("pg_dump") and shutil.which("age") and shutil.which("redis-cli")), reason="real tools not installed; SP022-T09 mandatory checklist")` で stub
- SP022-T09 mandatory checklist marker test (F-014 adopt): test docstring に "SP022-T09 drill で覆われる" を明示

## 6. 検証手順

```bash
# 1. module syntax
uv run python -m py_compile scripts/taskhub_backup_orchestrator.py

# 2. pure + mock unit tests
uv run pytest tests/scripts/test_taskhub_backup_orchestrator.py -v

# 3. CLI integration (mock 経由)
uv run pytest tests/scripts/test_taskhub_admin.py::test_cli_backup -v

# 4. regression: T01/T02 Phase 1/T03/T04/T07/T08 batch 1 全 fixture PASS
uv run pytest tests/ -q

# 5. ruff + mypy
uv run ruff check backend tests
uv run mypy backend

# 6. (SP022-T09 carry-over: actual tool execution validation は drill phase)
# 本 autonomous session では pg_dump / age 不在のため skip
```

## 7. レビュー観点 (codex-plan-review trigger 必須)

mandatory Codex gate (`.claude/rules/codex-usage-policy.md §14.1`、CRITICAL invariant 直結 = age key + raw secret leakage 0):
- `codex-plan-review R1-R3` minimum + 採否判定

### 7.1 期待される review focus

1. age private key を backup に含めない invariant の test 観点 (subprocess mock では public key path のみ argv に含まれる verify)
2. pg_dump output に DB raw value が含まれる前提での tmp dir cleanup 確実性 (exception path でも tmp dir 削除)
3. `--overwrite` default False の妥当性 (accidental data loss 防止)
4. `--skip-service-stop` の operational 意図 (test env only であり production drill では使用禁止の明示)
5. subprocess mock strategy が actual tool behavior と乖離するリスク (real drill validation を T09 で必須化)
6. `BackupOptions` の defaults が ADR-00021 §3 / docker-compose.yml と整合
7. raw exc message を stderr に出さない invariant (BackupRuntimeError.stderr_message が sanitized)
8. backup output file が age 暗号化前の tmp 状態で disk に残らない (partial output 防止)
9. tarfile (Python stdlib) と actual `tar` CLI の出力差異 (cross-platform deterministic)
10. ADR-00021 §4 file structure との bidirectional contract (restore Phase 3 で読める形式か)

## 8. リスク / Rollback

| リスク | 影響 | mitigation |
|---|---|---|
| Subprocess mock と actual tool 挙動の乖離 | T09 drill で fail | T09 で real execution validation を必須化、本 batch carry-over として明示 |
| Tmp dir cleanup 失敗で disk space 圧迫 | host degradation | try/finally + `shutil.rmtree(tmp_dir, ignore_errors=True)`、全 exception path で cleanup |
| age public key 不在 / 改竄 | backup の暗号化失敗 / 不正 verify | public key path validation + fingerprint check は将来 SecretBroker integration で対応 (batch 5 carry-over) |
| pg_dump 中の DB write による inconsistent snapshot | restore で integrity loss | `--single-transaction` + `--no-acl` flag (T02 Phase 3 restore で integrity verify)、actual drill は T09 で確認 |
| partial output (age encrypt 中断で .tar.age 半端 file) | restore で読めない / DoS | `output_path.with_suffix(".part")` で write、success 後 atomic rename、failure 時は part file 削除 |
| Codex review delayed | merge 遅延 | 30 min polling、admin merge bypass (CI billing failure 継続) |

### Rollback (3 階層)

- Tier 1 (pre-merge local): `git restore`
- Tier 2 (post-merge): `taskhub backup` を T02 Phase 1 skeleton に revert (`--skip-real-orchestration` flag 等の escape は本 batch で実装しない、revert PR が直接 path)
- Tier 3 (break-glass): PR revert + ADR で alternative backup strategy 再設計

## 9. commit 戦略

single commit。SP022-T01〜T08 batch 1 pattern 踏襲。

## 10. PR workflow

確立 pattern: plan draft → codex-plan-review R1-R3 → 実装 → pre-commit verify → commit/push/PR → Codex auto-review polling + multi-round adopt + admin merge bypass。

## 11. DoD

### 11.1 必須 DoD (R1 14 件全件 adopt 反映後)

- [ ] `scripts/taskhub_subprocess_runner.py` 新規 (F-009 adopt: 共通 subprocess runner with timeout / stdin=DEVNULL / env allowlist / stderr sanitization / argv logging policy)
- [ ] `scripts/taskhub_backup_orchestrator.py` 新規 (pure + subprocess wrappers + orchestration、§4 構造)
- [ ] `scripts/taskhub_admin.py` `_cmd_backup` を skeleton 出力から real orchestration 呼出に置き換え + 2 新引数 (`--skip-service-stop` / `--overwrite`)
- [ ] `scripts/taskhub_signed_approval.py` `ApprovalRecord` を `backup_claim` 拡張 (F-004 adopt: output_path / include_sops_env / skip_service_stop / overwrite / age_public_key_fingerprint)
- [ ] `tests/scripts/test_taskhub_subprocess_runner.py` 新規 (F-009 contract tests、~10 fixture)
- [ ] `tests/scripts/test_taskhub_backup_orchestrator.py` 新規 (Layer 1 pure ~13 + Layer 2 fake tool ~11 + Layer 3 orchestration ~12 ≈ **36 fixture 全 PASS**)
- [ ] `tests/scripts/test_taskhub_admin.py` `taskhub backup` fixture を skeleton 期待から real orchestration mock 期待に更新 + approval claim mismatch negative test
- [ ] `tests/deploy/test_taskhub_backup_integration.py` 新規 (skipif stub、SP022-T09 mandatory checklist marker)
- [ ] **F-001 adopt CRITICAL**: archive allowlist (filename + content prefix + symlink reject) で age private key / SSH private key / SOPS age key の archive 混入を物理 reject、test で 4 種以上の private key pattern verify
- [ ] **F-002 adopt CRITICAL**: tmp dir は `mkdtemp(mode=0o700)`、cleanup 失敗は audit event emit + exit 1 (silent ignore しない)、pg_dump/redis/age/tar/KeyboardInterrupt/cleanup OSError 6 path test
- [ ] **F-003 adopt HIGH**: service stop policy 明文化 (PostgreSQL / Redis は稼働維持、app/API/worker は本 batch では stop しない、`--skip-service-stop` は warning emit)
- [ ] **F-004 adopt HIGH**: signed approval claim coverage (backup_claim schema 拡張 + 全 flag を payload に含む + claim mismatch deny)
- [ ] **F-005 adopt HIGH**: partial output 防止 (`output.name + ".part"` 同 dir、`os.replace` atomic rename、failure 時 part 削除、test で `.part` 残存しないこと verify)
- [ ] **F-006 adopt HIGH**: Redis backup = `redis-cli --rdb <path>` 方式選択 + argv contract test
- [ ] **F-007 adopt HIGH**: BackupOptions defaults source-of-truth precedence (CLI / env / docker-compose.yml / hardcoded)、`BackupOptions.from_environment(repo_root)` で実装、3 path test
- [ ] **F-008 adopt HIGH**: meta.json data acquisition (pg_dump --version / redis-cli INFO / alembic current) + 取得不能時 runtime error 分類
- [ ] **F-009 adopt HIGH**: 共通 subprocess runner contract (timeout / shell=False / stdin=DEVNULL / env allowlist / stderr sanitization / argv logging policy)、raw password は argv / audit / stderr に出さない
- [ ] **F-010 adopt MEDIUM**: terminal reason_code (17) と warning_code (3) を別 field、result schema 明確化
- [ ] **F-011 adopt MEDIUM**: pg_dump 出力 = `pg_dump.dump` (custom format、`.sql` 拡張子不使用)
- [ ] **F-012 adopt MEDIUM**: checksums.txt spec (sha256sum 互換 format / byte-lex sort / self-exclude / symlink reject / file-only)
- [ ] **F-013 adopt MEDIUM**: fake tool fixtures (PATH override で fake pg_dump / redis-cli / age executable、argv contract verify)
- [ ] **F-014 adopt MEDIUM**: SP022-T09 mandatory drill checklist を `docs/deploy/half-yearly-drill-sop.md` 新 §11 に追加 (actual `taskhub backup` 実行 / age decrypt dry-run / tar listing / checksums verify / pg_restore 互換 / private key 非混入 / cleanup verify)
- [ ] T02 Phase 1 signed approval gate 維持 (既存 31 + 8 fixture PASS、approval claim 拡張で backwards compat)
- [ ] **R2-F-001 adopt CRITICAL**: backup subcommand では `--allow-unsigned-manual-skeleton` を deny、`require_approval_for_destructive` / `verify_signed_approval` に `backup_claim` 引数追加、Phase 1 既存 record backup_claim 不在 → backup では deny / 他 subcommand では従来通り verify
- [ ] **R2-F-002 adopt HIGH**: tmp dir 作成は `tempfile.mkdtemp(prefix=...)` + `os.chmod(0o700)` + permission verify、`mode=0o700` 引数は使用しない
- [ ] **R3-F-001 adopt CRITICAL**: subprocess runner env allowlist から `PGPASSWORD` / `REDISCLI_AUTH` / `AWS_SECRET_*` / `*_TOKEN` / `*_KEY` / `*_PASSWORD` 等 secret-bearing env を全 reject、PostgreSQL credentials は temp `.pgpass` (0600) + `PGPASSFILE` env のみ、Redis AUTH は本 batch では fail-closed (別 batch で config file 経由)、test で env reject + .pgpass file 0600 + cleanup verify
- [ ] regression: tests/ 全 PASS (3469 + 新規 ≈ 36 + 10 + 6 + backup_claim test 5 ≈ 3526+)、ruff backend tests clean、mypy strict 230 file pass
- [ ] codex-plan-review R{N} findings triaged adopt/defer/reject, all adopted CRITICAL/HIGH resolved before implementation

### 11.2 任意 DoD (回帰確認)

- [ ] PR Codex auto-review R{N} clean (採否判定 + multi-round polish)
- [ ] SP022-T09 carry-over marker: `docs/deploy/half-yearly-drill-sop.md` §3 で real tool execution validation を T09 で必須化

## 12. 関連

- ADR-00021 §3 + §4 (taskhub backup spec + file structure)
- SP-022 line 62 (T02) + line 68 (T08 SP-012 carry-over)
- `.claude/reference/task-planning-matrix.md` §2 (T02 = 🟥 heavy + phase 分割、T08 = 🟥 heavy + batch 分割、本 PR は両者の atomic 単位)
- SP022-T01 PR #70 / T03 PR #71 / T04 PR #72 / T07 PR #73 / planning matrix PR #74 / T02 Phase 1 PR #75 / T08 batch 1 PR #76 (確立 pattern)
- Sprint 12 batch 7 `scripts/taskhub_admin.py` (本 batch が integrate する skeleton)
- `backend/app/services/audit/signed_journal.py` (T08 batch 1 で wrap した pure pipeline、本 batch では touch しない)

## 13. R1 plan-review findings adoption log

R1 (2026-05-20, codex-plan-review): 14 findings, **全件 adopt** (CRITICAL×2 / HIGH×7 / MEDIUM×5)。User directive 「根本的解決をしてください。どれだけ時間かかってもいいのでしっかりしたものにしてほしい」を受け、scope 縮小せず全件深掘り反映。

| ID | severity | category | summary | adopted location |
|---|---|---|---|---|
| F-001 | CRITICAL | missing | archive layout allowlist で age/SSH/SOPS private key pattern (filename + content prefix + symlink) reject | §3.1 #6, §4.5 step 9, §4.8, §11.1 DoD |
| F-002 | CRITICAL | risk | tmp dir 0700 + cleanup 失敗 audit event + exit 1 (silent ignore 廃止)、6 exception path test | §3.1 #1, §4.5 step 3 + step 13, §4.6, §11.1 DoD |
| F-003 | HIGH | inconsistency | service stop policy 明文化 (DB/Redis 稼働維持、app freeze は T02 Phase 4 carry-over)、`--skip-service-stop` は warning emit | §3.1 #3, §4.5 step 4, §11.1 DoD |
| F-004 | HIGH | missing | signed approval claim coverage (output_path / include_sops_env / skip_service_stop / overwrite / age_public_key_fingerprint を payload に)、claim mismatch deny | §3.1 #4, §4.5 step 2, §4.9, §11.1 DoD |
| F-005 | HIGH | risk | partial output 防止 fix (`output.name + ".part"` 同 dir、atomic rename、failure 時 part 削除)、test で `.part` 残存しない verify | §4.5 step 12, §5.3 Layer 3, §11.1 DoD |
| F-006 | HIGH | missing | Redis backup = `redis-cli --rdb <path>` 方式選択 (server-side BGSAVE → local copy 経路の正確な実方式) | §3.1 #2, §4.5 step 8, §5.3 Layer 2, §11.1 DoD |
| F-007 | HIGH | inconsistency | BackupOptions defaults source-of-truth precedence (CLI / env / docker-compose / hardcoded)、`BackupOptions.from_environment` 関数 | §4.4, §5.3 Layer 1, §11.1 DoD |
| F-008 | HIGH | missing | meta.json acquisition source 固定 (pg_dump --version / redis-cli INFO / alembic current)、取得不能は runtime error 分類 | §3.1 #12, §4.3, §4.5 step 5, §5.3 Layer 1, §11.1 DoD |
| F-009 | HIGH | risk | 共通 subprocess runner (timeout / shell=False / stdin=DEVNULL / env allowlist / stderr sanitize / argv logging policy)、raw password 不出力 | §3.1 #1, §4.6, §5.3 Layer 2, §11.1 DoD |
| F-010 | MEDIUM | inconsistency | terminal reason_code (17) と warning_code (3) を別 field、result schema 明確化 | §4.3, §11.1 DoD |
| F-011 | MEDIUM | ambiguity | pg_dump 出力 = `pg_dump.dump` (custom format、`.sql` 拡張子は誤誘導) | §4.5 step 6, §11.1 DoD |
| F-012 | MEDIUM | missing | checksums.txt spec (sha256sum 互換 / byte-lex sort / self-exclude / symlink reject / file-only) | §4.7, §11.1 DoD |
| F-013 | MEDIUM | risk | fake tool fixtures (PATH override で fake pg_dump / redis-cli / age executable、argv contract verify) | §3.1 #6, §5.3 Layer 2, §11.1 DoD |
| F-014 | MEDIUM | planning | SP022-T09 mandatory drill checklist を drill SOP §11 に追加 (actual backup / age decrypt / tar listing / checksums verify / pg_restore 互換 / private key 非混入 / cleanup verify) | §3.1 #11, §11.1 DoD |
| R2-F-001 | CRITICAL | security | backup subcommand では `--allow-unsigned-manual-skeleton` を deny、`require_approval_for_destructive` / `verify_signed_approval` に `backup_claim` 引数を渡す API extension、Phase 1 既存 record backup_claim 不在 → backup では deny | §4.9 (新 logic 5 項目), §11.1 DoD |
| R2-F-002 | HIGH | compatibility | `tempfile.mkdtemp()` は `mode` 引数を受け取らない、`mkdtemp` 後に `os.chmod(0o700)` + permission verify | §4.5 step 3, §11.1 DoD |
| R3-F-001 | CRITICAL | security | env allowlist で `PGPASSWORD` / `REDISCLI_AUTH` を許容するのは raw secret leakage 0 invariant 違反、PostgreSQL は temp `.pgpass` (0600) + `PGPASSFILE` env のみ、Redis AUTH は本 batch fail-closed | §4.6 (env allowlist 限定 + .pgpass 経路), §5.3 Layer 2 (新 3 test), §11.1 DoD |
