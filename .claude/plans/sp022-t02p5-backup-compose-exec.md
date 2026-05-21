# SP022-T02 Phase 5 — backup pg_dump compose exec 切替 + service stop/restart consistency + destructive_lock 統合 + TOCTOU re-verify (T09 unblock hard gate)

## メタデータ

- **slug**: sp022-t02p5-backup-compose-exec
- **base**: origin/main (`07d08ef` post-PR #79)
- **owning sprint**: SP-022 framework intake hardening (T02 Phase 5、T09 unblock hard gate の最終 phase)
- **related ADRs**: ADR-00021 §11.2 (split-brain + service stop barrier) / §14.1 PGA-F-002 (detached signature) / §14.1 PGA-F-013 (drill timer alert-only)
- **risk_classification**: CRITICAL invariant 直結 (PR #77 host TCP port-collision attack surface 残存の retro-fix、Phase 3 restore で確立した compose exec + container 内 unix socket 経路を backup direction にも対称適用、ADR §11.2 backup-時 consistency boundary 確立)
- **must_ship**:
  1. `backup_orchestrator.invoke_pg_dump_via_compose_exec` 新規 (docker compose exec + container 内 unix socket `/var/run/postgresql`、host TCP 排除)
  2. `backup_orchestrator.invoke_redis_save_via_compose_exec` + `backup_orchestrator.invoke_redis_dump_via_compose_cp` 新規 (Redis SAVE blocking + `docker compose cp redis:/data/dump.rdb` で host path 経由を撤回、Docker Desktop for Mac 互換、ADV R1 F-005 adopt)
  3. `BackupOptions` に Compose binding field 追加 (`target_compose_project_name`, `target_compose_file_path`) + `from_environment` で `expanduser().resolve()` 正規化 (ADV R1 F-010 adopt)
  4. **backup 時 service stop/restart boundary** (`stop_app_services` → pg_dump + redis SAVE + artifacts copy → `start_app_services_wait_healthy`、ADR-00021 §11.2 consistency boundary、ADV R1 F-001 CRITICAL adopt)
  5. `_cmd_backup` に destructive_lock 統合 + **lock 取得後 age_public_key_fingerprint 再 verify** (TOCTOU 排除、Phase 4 R5 F-001 pattern、ADV R1 F-003 adopt)
  6. `pg_hba_preflight` via compose exec (`psql -c 'select 1'` で trust auth 前提を pg_dump 前に検証、ADV R1 F-007 adopt)
  7. `BackupOptions.pgpassfile_path` を Phase 5 compose exec 経路では未使用に + 旧 host TCP `invoke_pg_dump` は **削除** (PR #77 retro-fix、ADV R1 F-002 adopt)
  8. `DEFAULT_ENV_ALLOWLIST` から `PGPASSFILE` を **削除** (Phase 5 では不要、ADV R1 F-008 adopt)
  9. `BackupOptions.from_environment` default を docker-compose.yml と整合 (`pg_user=taskmanagedai`, `pg_db=taskmanagedai`、ADV R1 F-006 adopt)
  10. ADV R3 F-002 + R4 F-001/F-002 + R5 F-001 CRITICAL adopt: BackupApprovalClaim を 6-field 化 (`backup_runtime_binding_fingerprint` 追加)、PR #77 既存 5-field legacy record は `signed_approval.py` の signature root verify レベルでは互換維持 (parse OK + signature verify OK)、ただし `_cmd_backup` Phase 5 real I/O redeem では **常に `backup_claim_legacy_runtime_binding_unsupported` で reject** + 再 issue 必須 (operator runbook §11 SOP)。env override allowlist で Compose binding を server-owned validate (ADV R1 F-004 adopt)。
- **defer_if_over_budget**:
  - 全 must_ship は本 PR scope 内で完遂 (Phase 5 = T09 unblock hard gate、defer 不可)
  - `acquire_alembic_head(repo_root)` の compose exec 化 (現状は repo の alembic.ini パース、container 内 alembic head と乖離する可能性、Phase 6 carry-over)
  - `acquire_postgres_version` / `acquire_redis_version` の compose exec 切替 (meta.json 用、本 PR scope では host 経由維持、Phase 6 carry-over)
- **rollback**: 本 PR を revert すると backup は host TCP pg_dump / redis-cli --rdb に戻る (PR #77 動作)。BackupApprovalClaim は 6 field 化されるが、`backup_runtime_binding_fingerprint` は optional field のため revert 後の PR #77 互換 record (5 field) も `signed_approval.py` parser で読める (forward compat)。`_cmd_backup` Phase 5 reject 路は本 PR にしか存在しないため revert で自動消滅。Compose binding は optional + env override allowlist 経由、`stop_app_services` 経路は revert 後不要 (PR #77 は skip_service_stop default false で既に対応)。

---

## §1 目的

PR #77 (Phase 2 backup real I/O) で残った **host TCP port-collision attack surface** + **backup consistency boundary 不在** を、Phase 3 restore (PR #78) + Phase 4 (PR #79) で確立した pattern に対称適用する形で排除する。

### 1.1 PR #77 backup direction 残存リスク (T09 unblock の hard gate)

PR #77 で backup_orchestrator.invoke_pg_dump は:
- `pg_host=127.0.0.1, pg_port=5432, -U taskhub` を host TCP 経由で呼ぶ
- PGPASSFILE 環境変数経由でパスワード渡し
- 攻撃者が同一 host で port 5432 に別 postgres listener を立てる port-collision attack の余地
- **pg_dump + Redis SAVE 中に api/worker が DB / Redis に write し続けることで backup 不整合 (split-state)** の risk (ADR-00021 §11.2 consistency boundary 未確立)

Phase 3 restore (PR #78) では `pg_restore_via_compose_exec` で port-collision を排除、`stop_app_services` で consistency 確保済。**Phase 5 で backup direction にも同 pattern を適用しないと SP022-T09 drill が脆弱な backup file を生成**。

### 1.2 destructive_lock 統合 + TOCTOU re-verify (PR #79 R5/R6 carry-over)

PR #79 R6 F-001 で `_cmd_restore --input` と `--rollback` に destructive_lock を統合 + R5 F-001 で lock 内 TOCTOU re-verify を導入したが、**backup には未統合**。Phase 5 で `_cmd_backup` にも:
- destructive_lock (`subcommand="backup"`、cross-subcommand mutual exclusion)
- lock 取得後の age_public_key_fingerprint **再 verify** (file 差し替え race 排除、TOCTOU)

を統合。

### 1.3 Sprint Pack carry-over 1 件 trace (PR #79 §1.1 carry-over より)

| # | Sprint Pack carry-over | 本 PR 内 status |
|---|---|---|
| 6 | backup_orchestrator pg_dump compose exec 切替 | ✅ **this PR closure** (本 Phase 5) |
| 4 | age 秘密鍵 SecretBroker integration | ❌ explicit out-of-scope (P0 manual 運搬で OK、SP-012 carry-over 維持) |

---

## §2 背景 / 制約

### 2.1 既存 Phase 3 restore pattern (PR #78、対称適用の根拠)

```python
# scripts/taskhub_restore_orchestrator.py:1132 (pg_restore via compose exec)
def invoke_pg_restore_via_compose_exec(options, dump_file, *, timeout_sec):
    argv = (
        _compose_argv_prefix(options)
        + ["exec", "-T", "postgres", "pg_restore"]
        + [f"--username={options.target_pg_dsn_components['user']}"]
        + [f"--dbname={options.target_pg_dsn_components['db']}"]
        + ["--clean", "--if-exists", "--single-transaction",
           "--no-owner", "--no-privileges", "--exit-on-error",
           "--no-password",
           "-h", "/var/run/postgresql"]  # container 内 unix socket
    )
    with dump_file.open("rb") as f:
        return run_safe_subprocess(argv, config=SafeSubprocessConfig(timeout_sec=timeout_sec, stdin_file=f))
```

### 2.2 Redis backup: host path copy → docker compose cp 切替 (ADV R1 F-005 adopt)

**変更**: PR #77 の `redis-cli --rdb` (host TCP) → Phase 5 では:
1. `redis-cli SAVE` via compose exec (blocking、race-free)
2. `docker compose cp redis:/data/dump.rdb <tmp_dir>/dump.rdb.tmp` (container 内 file を host へ stream)
3. atomic rename (`.tmp` → final、ADV R1 F-012 adopt)

`acquire_redis_data_host_path` (Phase 3 restore で使用) は backup direction では **使わない** (Docker Desktop for Mac の named volume Source path が host から直接 read 不可能な場合の互換性問題を排除、ADV R1 F-005)。`docker compose cp` は Docker Engine の標準 API、Mac/Linux/VPS 全環境で動作保証。

### 2.3 BackupOptions の Compose binding 追加 (R2 server-owned boundary 遵守 + ADV R1 F-010 path normalize)

新規 field:
- `target_compose_project_name: str` (env `TASKHUB_BACKUP_COMPOSE_PROJECT`、default `"taskmanagedai"`)
- `target_compose_file_path: Path` (env `TASKHUB_BACKUP_COMPOSE_FILE`、default `<repo>/docker-compose.yml`、`Path(raw).expanduser().resolve(strict=False)` で正規化)

**ADV R3 F-002 + R5 F-001 + R9 F-001 CRITICAL adopt**: `BackupApprovalClaim` に **`backup_runtime_binding_fingerprint` を追加** (6 field 化)。**R5 F-001 統一ルール**: PR #77 既存 5-field legacy record は `signed_approval.py` の signature-root parse + verify レベルでは互換維持 (record の存在自体は accept、parse 失敗にしない)、しかし `_cmd_backup` Phase 5 real I/O redeem では **常に `backup_claim_legacy_runtime_binding_unsupported` で reject** + 再 issue 必須。「canonical default binding 完全一致時 allow」のような fragile な path-content 互換は **plan 全体で削除**。

**ADV R9 F-001 + ADV2 R1 F-009 + R3 F-001 CRITICAL adopt: record-claim データフロー** (verify_signed_approval API backward compat 維持 + single full-helper 統一):

`verify_signed_approval` は **既存 3-tuple shape `(allowed: bool, reason: ReasonCode, extras: dict[str, object])` を維持** (現行 contract、ADV2 R13 F-002 MEDIUM adopt で修正) + `extras` dict に `record_backup_claim` (deserialized + signature root verify 済 BackupApprovalClaim) を格納して返す。legacy 5-field record は signed_approval.py レベルでは `allowed=True` (format-level 互換)、runtime reject (`backup_claim_legacy_runtime_binding_unsupported`) は `_cmd_backup` 側で実施 (namespace 分離)。`_cmd_backup` は **record 側 claim** (`extras["record_backup_claim"]`) と **CLI 側 expected claim** (`expected_backup_claim`) を別変数として保持し、次の順で判定:
1. signature root verify (signed_approval.py、record 側 claim) PASS
2. legacy check: `record_backup_claim.backup_runtime_binding_fingerprint is None` → `backup_claim_legacy_runtime_binding_unsupported` で reject (再 issue 必須)
3. record-vs-expected 4 整合 verify: output_path / include_sops_env / skip_service_stop / overwrite / age_public_key_fingerprint exact match → mismatch なら `backup_claim_mismatch`
4. **ADV2 R3 F-001 CRITICAL adopt**: lock 内 verified copy bind 完了後に **`compute_full_backup_runtime_binding_fingerprint(backup_options, mode="redeem")` のみを呼ぶ** (private helper `compute_backup_runtime_binding_fingerprint` は plan 擬似コードから削除)。record 側 fingerprint と exact match → mismatch なら `backup_claim_mismatch`

これにより、6-field new record は **issue 時に broker が signature root に含めた fingerprint** (= `compute_full_backup_runtime_binding_fingerprint(mode="issue")`) と **redeem 時に lock 内で再計算した fingerprint** (= `compute_full_backup_runtime_binding_fingerprint(mode="redeem")`) の 2 経路 server-owned 再計算が一致する場合のみ allow。`compute_backup_runtime_binding_fingerprint` (private helper) は `compute_full_*` の内部実装としてのみ存在、外部から直接呼出できない (plan 擬似コードに直接呼出例を残さない、ADV2 R3 F-001 で issue/redeem algorithm drift 物理閉鎖)。

env override は **allowlist 化** (ADV R1 F-004 adopt: server-owned validation):
- `target_compose_project_name` regex `^[a-z0-9][a-z0-9_-]*$` (Docker Compose 公式仕様、Phase 4 R3 F-002 同等)
- `target_compose_file_path` は **repo_root 配下 or system path (/etc, /var/lib) のみ allow** (`Path.is_relative_to(repo_root)` or `str(path).startswith(("/etc/", "/var/lib/"))`)

#### 2.3.A `backup_runtime_binding_fingerprint` canonical schema (ADV R3 F-002 CRITICAL adopt)

approval issue 時 / lock 内 verify 時の両方で **broker / CLI が server 側で再計算** する canonical OperationContext:

```python
def compute_backup_runtime_binding_fingerprint(
    options: BackupOptions, *,
    compose_file_sha256: str,
    sops_env_sha256: str | None,
    compose_config_canonical_sha256: str,
    env_file_sha256: str | None,
    artifacts_dir_manifest_sha256: str,
) -> str:
    """SP022-T02 Phase 5 R3 F-002 + R6 F-001 + ADV2 R1 F-001/F-003 + R2 F-001 + R5 F-001/F-002 adopt:
    BackupApprovalClaim 4 整合に Compose binding + payload source binding (env_file + artifacts_dir manifest) を含める fingerprint.

    canonical OperationContext (JCS canonical JSON + NFC UTF-8 + SHA-256):
    - target_compose_project_name (resolved string)
    - target_compose_file_realpath (Path.resolve(strict=True) absolute, str)
    - target_compose_file_sha256 (file bytes の SHA-256, hex)
    - target_compose_project_directory (str(target_compose_file_realpath.parent)、ADV R6 F-001)
    - **artifacts_dir_realpath** (ADV2 R1 F-001 CRITICAL adopt: backup payload source path 固定)
    - **artifacts_dir_manifest_sha256** (ADV2 R5 F-002 CRITICAL adopt: artifacts_dir tree の
      file path + content sha256 + mode のソート済 manifest 全体を sha256 化、payload TOCTOU 物理閉鎖)
    - **sops_env_path_realpath** (ADV2 R1 F-001 CRITICAL adopt: include_sops_env=true 時のみ非 None)
    - **sops_env_sha256** (ADV2 R1 F-001 CRITICAL adopt: include_sops_env=true 時のみ非 None)
    - **env_file_realpath** (ADV2 R5 F-001 CRITICAL adopt: env_file_path is not None 時のみ非 None、
      None 時は両方 None で固定)
    - **env_file_sha256** (ADV2 R2 F-001 + R5 F-001 CRITICAL adopt: env_file_path is not None 時のみ非 None)
    - **compose_config_canonical_sha256** (ADV2 R1 F-003 HIGH adopt)
    - pg_user / pg_db (resolved string)
    - postgres_service_name / redis_service_name (固定)

    **ADV2 R5 F-001 CRITICAL**: env_file_realpath と env_file_sha256 を canonical schema 必須要素として明記。
    env_file_path is None 時は両方 None で固定 (drift 不可)。

    **ADV2 R5 F-002 CRITICAL**: artifacts_dir manifest を canonical schema に含めて payload TOCTOU 防御。
    artifacts_dir は directory tree のため、file path + content sha256 + mode の sorted manifest を
    JCS canonical JSON 化 → SHA-256 で artifacts_dir_manifest_sha256 を計算 (lock 内で manifest 取得 +
    fingerprint binding、archive 作成は lock 内 manifest path から直接読み込む verified staging に固定)。
    """
    realpath = options.target_compose_file_path.resolve(strict=True)
    context = {
        "target_compose_project_name": options.target_compose_project_name,
        "target_compose_file_realpath": str(realpath),
        "target_compose_file_sha256": compose_file_sha256,
        "target_compose_project_directory": str(realpath.parent),
        # ADV2 R1 F-001 + R5 F-002 + R6 F-002 CRITICAL adopt: artifacts_dir realpath は immutable snapshot から
        # (都度 resolve すると caller-controlled rename/symlink swap の影響を受ける、issue 時に snapshot 化、
        # redeem 時は lock 内 snapshot を使う)
        "artifacts_dir_realpath": str(
            options.artifacts_dir_realpath_snapshot
            if options.artifacts_dir_realpath_snapshot is not None
            else options.artifacts_dir.resolve(strict=True)  # issue 時の fallback (lock 取得前は snapshot=None)
        ),
        "artifacts_dir_manifest_sha256": artifacts_dir_manifest_sha256,
        # ADV2 R1 F-001 CRITICAL adopt: sops_env_path binding
        "sops_env_path_realpath": (
            str(options.sops_env_path.resolve(strict=True)) if options.include_sops_env else None
        ),
        "sops_env_sha256": sops_env_sha256 if options.include_sops_env else None,
        # ADV2 R5 F-001 CRITICAL adopt: env_file_realpath + env_file_sha256 を canonical schema 必須要素化
        "env_file_realpath": (
            str(options.env_file_path.resolve(strict=True)) if options.env_file_path is not None else None
        ),
        "env_file_sha256": env_file_sha256 if options.env_file_path is not None else None,
        # ADV2 R1 F-003 HIGH adopt: env_file / build.context / bind mount closure binding
        "compose_config_canonical_sha256": compose_config_canonical_sha256,
        "pg_user": options.pg_user,
        "pg_db": options.pg_db,
        "postgres_service_name": "postgres",
        "redis_service_name": "redis",
    }
    canonical = canonicalize_jcs(context)  # 既存 _rfc8785 helper
    return sha256(canonical.encode("utf-8")).hexdigest()
```

`compute_full_backup_runtime_binding_fingerprint` も `artifacts_dir_manifest_sha256` を mode 別に計算:
- mode="issue": `_compute_artifacts_dir_manifest_sha256(options.artifacts_dir)` (source tree)
- mode="redeem": `_compute_artifacts_dir_manifest_sha256(options.verified_artifacts_staging_dir)` (lock 内 staged tree)

**`_compute_artifacts_dir_manifest_sha256` + `_verified_copy_tree_no_follow` contract (ADV2 R6 F-003 CRITICAL adopt)**:

両 helper は次の file type contract で動作 (fail-closed):

- **regular file (`stat.S_ISREG`)**: chunked streaming SHA-256 (default chunk 64 KiB)、per-file max size = `MAX_ARTIFACT_FILE_BYTES` (default 256 MiB、env override `TASKHUB_BACKUP_MAX_ARTIFACT_FILE_BYTES`)、超過は `backup_artifacts_file_too_large` fail-closed
- **directory (`stat.S_ISDIR`)**: 再帰 walk (os.scandir、no-follow)、manifest entry は `{path, type="dir", mode}`
- **symlink (`stat.S_ISLNK`)**: ADV2 R11 F-002 CRITICAL adopt で **常に reject**、`backup_artifacts_source_unsupported_file_type` fail-closed (artifact directory に symlink を含めない方針、外部 path 読込 + source swap + dereference 攻撃を物理閉鎖)。symlink を含めたい運用は明示禁止、必要なら symlink を直接 hard copy / 同 dir の relative path に変換してから artifact に保存する SOP を operator runbook §X に記載
- **special file (FIFO `stat.S_ISFIFO` / socket `stat.S_ISSOCK` / block device `stat.S_ISBLK` / char device `stat.S_ISCHR`)**: **常に reject**、`backup_artifacts_source_unsupported_file_type` fail-closed
- **total tree size**: `MAX_ARTIFACT_TREE_BYTES` (default 4 GiB)、超過は `backup_artifacts_tree_too_large`

`_verified_copy_tree_no_follow` は walk 中に `os.open(O_RDONLY | O_NOFOLLOW)` で source 読込 + `os.open(O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0o400)` で staging 書込 (chunked、tmp file 経由禁止、直接 destination)。lstat 結果 (dev/ino/uid/mode) を copy 後に再検証 (copy 中の swap 検知)。

manifest dict structure (JCS canonical、ADV2 R11 F-002 CRITICAL adopt で symlink entry 削除):
```python
{
    "files": [  # sorted by path、regular file + directory のみ
        {"path": "data/foo.txt", "type": "file", "sha256": "...", "mode": 0o644, "size": 1234},
        {"path": "data/sub", "type": "dir", "mode": 0o755},
    ],
    "total_files": 2,
    "total_bytes": 1234,
    "manifest_version": 1,
}
```

**symlink は manifest entry に含めない**: source tree に symlink があれば `_verified_copy_tree_no_follow` 内で `backup_artifacts_source_unsupported_file_type` fail-closed。manifest helper も `os.lstat()` で symlink を検知したら同 reason で reject。

**ADV2 R7 F-003 + R8 F-001/F-002 CRITICAL adopt: mode 正規化方針**:

`_compute_artifacts_dir_manifest_sha256` は **source lstat mode を canonical entry として保持** (issue/redeem 共通)。staging copy 時の destination file mode (0o400) は実行時安全のため別扱い (manifest には含めない)。

**ADV2 R8 F-001 CRITICAL adopt**: `mode_source` は **必須 keyword-only 引数** (default なし)。各 callsite で明示的に指定:

- `mode_source="lstat"` (issue 経路): source tree を直接 walk し、各 entry の `os.lstat().st_mode` を canonical mode として使う。
- `mode_source="source_lstat"` (redeem 経路 + run_backup archive 直前 staging re-verify): staging tree を walk するが、各 entry の mode は **source side で記録した sidecar** (`_artifacts_source_mode.json`、後述) から読み込む。

両 mode で **source lstat の mode** が manifest に入る (staging 0o400 は反映されない)。これにより issue mode (`0o644` source) と redeem mode (`0o400` staging だが sidecar に保存された source `0o644`) で fingerprint が一致。

**ADV2 R8 F-002 CRITICAL adopt**: sidecar `_artifacts_source_mode.json` は **`verified_temp_dir / "artifacts_source_mode.json"` に保存** (staging tree namespace の **外**)。理由:
- staging tree 内に置くと archive payload に未署名 infrastructure file が混入
- source tree に同名 file (`_artifacts_source_mode.json`) が存在する場合の衝突 / 上書きを排除
- `_verified_copy_tree_no_follow` は `source_mode_sidecar_path` 引数で sidecar 書込先を受け取り、staging tree とは別 dir に書き出す
- `_compute_artifacts_dir_manifest_sha256` は `source_mode_sidecar_path` 引数で sidecar 読込先を受け取る
- archive builder は **manifest entries だけを走査して archive 作成** (manifest path で源泉駆動)、sidecar は走査範囲外
- source tree に `_artifacts_source_mode.json` ファイル名が存在する場合: copy helper は source-side で reserved-name check → `backup_artifacts_source_reserved_name` で fail-closed

`_verified_copy_tree_no_follow` が copy 中に source `os.lstat()` の `(path, type, mode, size, sha256)` を sorted dict として sidecar に書き出す (staging tree とは別 dir、`verified_temp_dir / "artifacts_source_mode.json"`)。

**ADV2 R14 F-004 LOW adopt**: sidecar contract から `symlink_target` を **削除** (symlink は `_verified_copy_tree_no_follow` 内で `backup_artifacts_source_unsupported_file_type` で fail-closed されるため、sidecar serialization に到達しない)。type は `"file"` / `"dir"` のみ (symlink は manifest / sidecar の両方から除外、symlink 全面 reject 方針との一貫性)。

**ADV2 R1 F-001 + F-003 + R2 F-002/F-003 fingerprint helpers** (issue 用 / redeem 用分離 + 単一 fingerprint helper):

```python
def _compose_argv_prefix_for_issue(
    options: BackupOptions, *,
    source_compose_path: Path,
    source_env_file_path: Path | None,
    source_project_dir: Path,
) -> list[str]:
    """ADV2 R2 F-003 HIGH adopt: approval issue 時専用、verified copy 未 bind 段階で docker compose を呼ぶ.

    issue 段階では lock 未取得 + verified copy 未作成のため、_compose_argv_prefix の verified bind
    必須 check を回避する。引数で source path を直接受け、issue 段階の compose config canonical hash 計算用。
    redeem (lock 内) では _compose_argv_prefix (verified copy bind 済) を使う。
    """
    argv = [
        "docker", "compose",
        "-p", options.target_compose_project_name,
        "-f", str(source_compose_path),
        "--project-directory", str(source_project_dir),
    ]
    if source_env_file_path is not None:
        argv.extend(["--env-file", str(source_env_file_path)])
    return argv


def compute_compose_config_canonical_sha256_for_issue(
    options: BackupOptions, *,
    source_compose_path: Path,
    source_env_file_path: Path | None,
    source_project_dir: Path,
    timeout_sec: int = 30,
) -> str:
    """ADV2 R1 F-003 + R2 F-003 HIGH adopt: approval issue 用 canonical hash.

    issue 段階では source compose realpath を直接読む (verified copy 未作成)。
    docker compose config は env_file / build.context / bind mount / 相対 path を解決した
    normalized YAML を出力。secret env value は redact してから sha256。
    """
    argv = _compose_argv_prefix_for_issue(
        options,
        source_compose_path=source_compose_path,
        source_env_file_path=source_env_file_path,
        source_project_dir=source_project_dir,
    ) + ["config", "--resolve-image-digests"]
    result = _run_subprocess_with_tool_check(
        argv, SafeSubprocessConfig(timeout_sec=timeout_sec),
        "backup_compose_config_failed",
    )
    if result.returncode != 0:
        raise BackupRuntimeError(
            "backup_compose_config_failed",
            detail=f"docker compose config failed (issue): exit={result.returncode}",
        )
    return sha256(_redact_compose_env_values(result.stdout).encode("utf-8")).hexdigest()


def compute_compose_config_canonical_sha256_for_redeem(
    options: BackupOptions, *, timeout_sec: int = 30,
) -> str:
    """ADV2 R1 F-003 + R2 F-003 HIGH adopt: lock 内 redeem 用 canonical hash.

    redeem 段階では _compose_argv_prefix (verified copy bind 済) を使う = lock 内で確定した
    verified compose copy + verified env file copy + signed project directory に限定。
    """
    argv = _compose_argv_prefix(options) + ["config", "--resolve-image-digests"]
    result = _run_subprocess_with_tool_check(
        argv, SafeSubprocessConfig(timeout_sec=timeout_sec),
        "backup_compose_config_failed",
    )
    if result.returncode != 0:
        raise BackupRuntimeError(
            "backup_compose_config_failed",
            detail=f"docker compose config failed (redeem): exit={result.returncode}",
        )
    return sha256(_redact_compose_env_values(result.stdout).encode("utf-8")).hexdigest()


def compute_full_backup_runtime_binding_fingerprint(
    options: BackupOptions, *,
    mode: Literal["issue", "redeem"],
    source_compose_path: Path | None = None,
    source_env_file_path: Path | None = None,
    source_project_dir: Path | None = None,
) -> str:
    """ADV2 R2 F-002 HIGH adopt: 単一 fingerprint helper (issue / redeem 両モードで同 algorithm).

    fail-closed 条件 (両 mode 共通):
    - compose_file_sha256 計算失敗 → backup_compose_file_unreadable
    - sops_env_sha256 計算失敗 (include_sops_env=true 時) → backup_payload_source_unreadable
    - env_file_sha256 計算失敗 (env_file_path != None 時) → backup_compose_env_file_unreadable
    - compose_config_canonical_sha256 計算失敗 → backup_compose_config_failed

    issue mode は source path を引数で受け、redeem mode は options.verified_* を使う。
    両 mode で同じ canonical schema (compute_backup_runtime_binding_fingerprint) を返す。
    """
    if mode == "issue":
        assert source_compose_path is not None and source_project_dir is not None
        # ADV2 R9 F-002 CRITICAL adopt: env_file cross-field invariant (issue mode)
        # env_file_path is not None なら source_env_file_path 必須、None なら source_env_file_path も None 必須
        if options.env_file_path is not None and source_env_file_path is None:
            raise BackupRuntimeError(
                "backup_compose_binding_not_initialized",
                detail="options.env_file_path is set but source_env_file_path missing for issue fingerprint",
            )
        if options.env_file_path is None and source_env_file_path is not None:
            raise BackupRuntimeError(
                "backup_compose_binding_not_initialized",
                detail="source_env_file_path passed but options.env_file_path is None (invariant violation)",
            )
        compose_file_sha256 = sha256(source_compose_path.read_bytes()).hexdigest()
        sops_env_sha256 = (
            sha256(options.sops_env_path.read_bytes()).hexdigest()
            if options.include_sops_env else None
        )
        env_file_sha256 = (
            sha256(source_env_file_path.read_bytes()).hexdigest()
            if source_env_file_path is not None else None
        )
        compose_config_canonical = compute_compose_config_canonical_sha256_for_issue(
            options,
            source_compose_path=source_compose_path,
            source_env_file_path=source_env_file_path,
            source_project_dir=source_project_dir,
        )
        # ADV2 R7 F-001 + R8 F-001 CRITICAL adopt: issue mode で artifacts_dir_manifest_sha256 を明示計算 (source tree)
        # `mode_source="lstat"` を必須 keyword-only 引数で明示 (source tree を直接 walk)
        artifacts_dir_manifest_sha256 = _compute_artifacts_dir_manifest_sha256(
            options.artifacts_dir,
            mode_source="lstat",
        )
    else:  # redeem
        assert options.verified_compose_execution_input is not None
        compose_file_sha256 = sha256(options.verified_compose_execution_input.read_bytes()).hexdigest()
        # ADV2 R6 F-001 CRITICAL adopt: redeem mode では sops_env を **verified copy から** 読む必須
        # (source path 再読込は caller-controlled swap の影響を受ける、verified staging 設計と不整合)
        if options.include_sops_env:
            if options.verified_sops_env_execution_input is None:
                raise BackupRuntimeError(
                    "backup_compose_binding_not_initialized",
                    detail="verified_sops_env_execution_input must be bound before redeem fingerprint",
                )
            _verify_metadata_snapshot(
                options.verified_sops_env_execution_input,
                options.verified_sops_env_metadata_snapshot,
                tamper_reason="backup_payload_source_tampered",
            )
            sops_env_sha256 = sha256(options.verified_sops_env_execution_input.read_bytes()).hexdigest()
        else:
            sops_env_sha256 = None
        # ADV2 R9 F-002 CRITICAL adopt: env_file cross-field invariant (redeem mode)
        # env_file_path is not None なら verified_env_file_execution_input + snapshot 必須
        if options.env_file_path is not None:
            if options.verified_env_file_execution_input is None or options.verified_env_file_metadata_snapshot is None:
                raise BackupRuntimeError(
                    "backup_compose_binding_not_initialized",
                    detail="options.env_file_path is set but verified_env_file_execution_input / metadata_snapshot not bound for redeem",
                )
            env_file_sha256 = sha256(options.verified_env_file_execution_input.read_bytes()).hexdigest()
        else:
            if options.verified_env_file_execution_input is not None:
                raise BackupRuntimeError(
                    "backup_compose_binding_not_initialized",
                    detail="verified_env_file_execution_input bound but options.env_file_path is None (invariant violation)",
                )
            env_file_sha256 = None
        compose_config_canonical = compute_compose_config_canonical_sha256_for_redeem(options)
        # ADV2 R7 F-001 CRITICAL adopt: redeem mode で artifacts_dir_manifest_sha256 を verified staging から計算
        # + lock 内 snapshot 値と一致確認 (staging tree の post-bind tamper 検知)
        if options.verified_artifacts_staging_dir is None or options.verified_artifacts_manifest_sha256 is None:
            raise BackupRuntimeError(
                "backup_compose_binding_not_initialized",
                detail="verified_artifacts_staging_dir / verified_artifacts_manifest_sha256 must be bound before redeem fingerprint",
            )
        # ADV2 R8 F-001/F-002 CRITICAL adopt: mode_source="source_lstat" 必須 + sidecar path 必須
        # (default なし、issue 経路と異なり sidecar から source mode を読む、verified_temp_dir 直下の sidecar)
        artifacts_dir_manifest_sha256 = _compute_artifacts_dir_manifest_sha256(
            options.verified_artifacts_staging_dir,
            mode_source="source_lstat",
            source_mode_sidecar_path=options.verified_artifacts_source_mode_sidecar_path,
        )
        if artifacts_dir_manifest_sha256 != options.verified_artifacts_manifest_sha256:
            raise BackupRuntimeError(
                "backup_artifacts_staging_tampered",
                detail=f"verified artifacts manifest mismatch in redeem: "
                       f"snapshot={options.verified_artifacts_manifest_sha256[:16]}, "
                       f"current={artifacts_dir_manifest_sha256[:16]}",
            )

    # ADV2 R7 F-001 CRITICAL adopt: artifacts_dir_manifest_sha256 を必須引数として明示渡し
    return compute_backup_runtime_binding_fingerprint(
        options,
        compose_file_sha256=compose_file_sha256,
        sops_env_sha256=sops_env_sha256,
        compose_config_canonical_sha256=compose_config_canonical,
        env_file_sha256=env_file_sha256,
        artifacts_dir_manifest_sha256=artifacts_dir_manifest_sha256,
    )
```

`compute_backup_runtime_binding_fingerprint` も `env_file_sha256` を必須引数に追加 (上記 helper 拡張、canonical schema に `env_file_realpath` + `env_file_sha256` 追加で env_file binding を完成)。

**ADV2 R1 F-001 補強**: BackupOptions の `artifacts_dir` / `sops_env_path` / `env_file_path` は env override allowlist で受け入れるが、approval issue / redeem 両時で server-owned に `resolve(strict=True)` 化 + content sha256 化 + fingerprint binding。env 差し替えは broker 再計算 fingerprint 不一致で `backup_claim_mismatch` fail-closed。

**ADV R4 F-001 CRITICAL adopt: PR #77 legacy 5-field record は Phase 5 real I/O で reject、再 issue 必須** (safe option)。

理由: 5-field legacy record には署名済み `backup_runtime_binding_fingerprint` が存在せず、redeem 時に「current compose file content sha256」を計算しても比較対象が record 内にない (caller が任意の compose file を pin したわけではない、broker が後から runtime resolved する経路は server-owned binding ではない)。これにより legacy compat allow rule を維持すると「default project/path のまま docker-compose.yml の content が issue 後に変わるケース」(content swap 攻撃) を redeem 時に検出できず、署名済み legacy approval ですり替え backup を作れる脆弱性が残る。

**Phase 5 切替時の運用**: PR #77 legacy record は **Phase 5 移行と同時に invalidate**、再 issue が必須:

```bash
# operator runbook §11 SOP (Phase 5 切替時):
# 1. PR #77 旧 record を確認: ls -la ~/.taskhub/approvals/*backup*.json (legacy 5-field)
# 2. Phase 5 へ切替: 新 approval CLI で再 issue (broker が server-owned に backup_runtime_binding_fingerprint 計算)
# 3. 旧 record は keep (audit trail)、新 record で backup 実行 (`taskhub approval issue --backup-output-path ...`)
```

`_cmd_backup` の verify path:

```python
if backup_claim.backup_runtime_binding_fingerprint is None:
    # ADV R4 F-001 CRITICAL adopt: legacy 5-field record は Phase 5 real I/O で reject
    print(
        "ERROR: PR #77 legacy 5-field BackupApprovalClaim is no longer accepted in Phase 5. "
        "Please re-issue with `taskhub approval issue --backup-output-path ...` to obtain "
        "a 6-field record that includes backup_runtime_binding_fingerprint. "
        "[reason=backup_claim_legacy_runtime_binding_unsupported]",
        file=sys.stderr,
    )
    return 2
# 新 6-field record のみ accept、broker が server-owned に再計算した fingerprint と比較
expected_fp = compute_full_backup_runtime_binding_fingerprint(backup_options, mode="redeem")  # ADV2 R3 F-001 CRITICAL adopt: single full-helper のみ呼出 (private helper 直接呼出禁止)
if backup_claim.backup_runtime_binding_fingerprint != expected_fp:
    # 既存 backup_claim_mismatch で fail-closed (4 整合 fingerprint pattern)
    print("ERROR: backup_runtime_binding_fingerprint mismatch [reason=backup_claim_mismatch]", file=sys.stderr)
    return 2
```

### 2.3.B docker compose 環境変数 / env_file 明示 (ADV2 R1 F-002 HIGH adopt)

docker-compose.yml は `${TASKMANAGEDAI_ENVIRONMENT}` / `${DEV_LOGIN_COOKIE_SECRET}` 等の env variable interpolation を持つが、`SafeSubprocessConfig` の DEFAULT_ENV_ALLOWLIST は `PATH/HOME/LANG/TZ/TMPDIR` 等に限定。Phase 5 で docker compose を直接実行する場合、interpolation 解決が無効になり compose validation fail もしくは default value 解決の挙動 drift を起こす。

**fix**:
- `_compose_argv_prefix` で **`--env-file <signed .env file path>`** を必ず明示 (compose の env 解決を repo_root/.env 等 server-owned に固定)
- `BackupOptions.env_file_path: Path | None` を新規 field 追加 + `BackupApprovalClaim` と `backup_runtime_binding_fingerprint` に `env_file_realpath` + `env_file_sha256` 含める (issue 後 swap 防御)
- DEV_LOGIN_COOKIE_SECRET のような secret 値は **fingerprint には key set のみ含め value は redact** (secret 漏洩防止)
- 非 secret env (TASKMANAGEDAI_ENVIRONMENT 等) は extra_env_allowlist で SafeSubprocessConfig に渡す (compose subprocess に必要な env 限定)
- env_file 不存在 / 読込失敗時は `backup_compose_env_file_unreadable` で fail-closed

`docker compose config --resolve-image-digests` (ADV2 R1 F-003 fingerprint helper) は env_file 解決後の canonical YAML を出力するため、env_file 差し替え攻撃は canonical config hash の不一致で同時に検知される (二重防御)。

---

### 2.4 PGPASSFILE 撤回 (ADV R1 F-007 + F-008 adopt: pg_hba preflight + DEFAULT_ENV_ALLOWLIST 削除)

PR #77 では `PGPASSFILE` 経由のパスワード認証。Phase 5 compose exec + unix socket では:

- `--no-password` flag 必須 (interactive password prompt 防止)
- `-h /var/run/postgresql` で unix socket
- container 内 `pg_hba.conf` で `local all all trust` (docker-compose.yml の `postgres:16-alpine` default)

**preflight verify** (ADV R1 F-007 adopt): `pg_dump` 呼出前に `psql -c 'select 1'` を同 argv pattern で実行し、trust auth が effective か確認:

```python
def verify_pg_hba_trust_auth_via_compose_exec(options, *, timeout_sec: int) -> None:
    """pg_dump 前に trust auth 前提を verify (postgres image 仕様変更や mount override で
    pg_hba が trust ではない場合、fail-closed で structured error)."""
    argv = (
        _compose_argv_prefix(options)
        + ["exec", "-T", "postgres", "psql"]
        + [f"--username={options.pg_user}"]
        + [f"--dbname={options.pg_db}"]
        + ["-h", "/var/run/postgresql", "--no-password",
           "-c", "select 1", "-t", "-A"]
    )
    try:
        result = run_safe_subprocess(argv, config=SafeSubprocessConfig(timeout_sec=timeout_sec))
    except (SubprocessNotFoundError, SubprocessTimeoutError) as e:
        raise BackupRuntimeError(
            "backup_pg_dump_failed",
            detail=f"pg_hba_preflight_subprocess_failed: {type(e).__name__}",
        ) from None
    if result.returncode != 0:
        raise BackupRuntimeError(
            "backup_pg_dump_failed",
            detail=f"pg_hba_preflight_failed: exit={result.returncode}, "
            f"likely trust auth not enabled (image override / pg_hba.conf modified)",
        )
```

**`DEFAULT_ENV_ALLOWLIST` から `PGPASSFILE` 削除** (ADV R1 F-008 adopt): `scripts/taskhub_subprocess_runner.py:28` の `DEFAULT_ENV_ALLOWLIST` から `PGPASSFILE` を外し、旧 host TCP `invoke_pg_dump` の `extra_env_allowlist=("PGPASSFILE",)` 経由のみ allow (Phase 5 で旧経路を **削除** するため、結果として PGPASSFILE は全 path で env propagate されない)。

**ADV R2 F-002 adopt: 既存 test 更新 + 他 caller grep impact list**

- 既存 `tests/scripts/test_taskhub_subprocess_runner.py::test_filter_env_allows_pgpassfile` (default allow を期待) を **2 test に置換**:
  1. `test_filter_env_default_does_not_allow_pgpassfile` (DEFAULT で渡らない)
  2. `test_filter_env_extra_allowlist_allows_pgpassfile` (`extra_env_allowlist=("PGPASSFILE",)` 指定時のみ渡る)
- §5 file change 一覧に `tests/scripts/test_taskhub_subprocess_runner.py` を追加
- production caller の grep impact: `rg PGPASSFILE scripts/ backend/ tests/` で旧 host TCP `invoke_pg_dump` 以外に PGPASSFILE 依存 caller が存在しないことを確認 (本 PR で旧 path 削除のため、結果として PGPASSFILE は dev tooling 以外で使われない)

### 2.5 destructive_lock 統合 + TOCTOU re-verify (Phase 4 R5/R6 pattern)

`_cmd_backup` に PR #79 で確立した destructive_lock context manager を統合 + **lock 取得後の age_public_key_fingerprint 再 verify** (ADV R1 F-003 adopt):

```python
# scripts/taskhub_admin.py _cmd_backup 末尾 (approval gate 成功後)
from scripts.taskhub_destructive_lock import acquire_destructive_lock

with acquire_destructive_lock("backup", args.approval_id) as (acquired, lock_reason, blocker):
    if not acquired:
        # blocker info を stderr に出力 + exit 2
        ...

    # ADV R1 F-003 + R3 F-001 CRITICAL adopt: lock 取得後に age_public_key を再読込 + sha256 再計算 +
    # claim fingerprint と一致 verify、**さらに lock 内で読んだ bytes から確定した recipient を
    # backup_options に immutable bind して run_backup → invoke_age_encrypt の path 再読込経路を物理閉鎖**
    # (lock 内検証後から encrypt 直前までの key file 差し替え race を排除)
    if backup_claim is not None:
        try:
            age_pub_bytes_inlock = backup_options.age_public_key_path.read_bytes()
            age_pub_fingerprint_inlock = sha256(age_pub_bytes_inlock).hexdigest()
        except OSError:
            print("ERROR: age public key not readable after lock acquisition", file=sys.stderr)
            return 2
        if age_pub_fingerprint_inlock != backup_claim.age_public_key_fingerprint:
            print(
                f"ERROR: age_public_key fingerprint TOCTOU mismatch "
                f"(pre-lock={backup_claim.age_public_key_fingerprint[:16]}, "
                f"in-lock={age_pub_fingerprint_inlock[:16]}) "
                "[reason=backup_age_key_toctou_mismatch]",
                file=sys.stderr,
            )
            return 2
        # ADV R3 F-001 + ADV2 R1 F-006 adopt: 検証済み bytes から確定した recipient を
        # backup_options.verified_age_recipient に immutable bind (frozen dataclass の replace 利用)
        # ADV2 R1 F-006: UnicodeDecodeError catch + 厳密 regex + 単一行制約 + 最大長
        try:
            verified_recipient = age_pub_bytes_inlock.decode("ascii").strip()
        except UnicodeDecodeError:
            print(
                "ERROR: age public key content not ASCII "
                "[reason=backup_age_recipient_invalid]",
                file=sys.stderr,
            )
            return 2
        # age recipient 厳密 regex: age1[0-9a-z]{58} (age v1 仕様、bech32 base32)
        # 単一行制約 (改行 strip 後に \n / \r 残存禁止) + 最大長 200 chars
        if (
            "\n" in verified_recipient or "\r" in verified_recipient
            or len(verified_recipient) > 200
            or not re.match(r"^age1[0-9a-z]{58}$", verified_recipient)
        ):
            print(
                f"ERROR: age public key content not a valid age recipient "
                f"(prefix={verified_recipient[:8]!r}) [reason=backup_age_recipient_invalid]",
                file=sys.stderr,
            )
            return 2
        backup_options = dataclasses.replace(
            backup_options, verified_age_recipient=verified_recipient,
        )

        # ADV R5 F-002 + ADV2 R4 F-001/F-002 CRITICAL adopt: lock block 実行順序を明確化:
        # (1) source compose bytes 読込 + sha256 計算
        # (2) verified compose copy 作成 + metadata snapshot 取得
        # (3) source env_file bytes 読込 + verified env_file copy 作成 + metadata snapshot 取得 (R4 F-002 並列処理)
        # (4) backup_options に verified copy 4 field + snapshot 2 field を immutable bind (dataclasses.replace)
        # (5) compute_full_backup_runtime_binding_fingerprint(backup_options, mode="redeem") で fingerprint 再計算
        # (6) record claim fingerprint と exact match verify → mismatch なら backup_claim_mismatch fail-closed
        #
        # **R4 F-001 CRITICAL**: redeem helper は verified bind 完了 (4) **後** に呼ぶ必須 (helper 内 assert あり)。
        # **R4 F-002 CRITICAL**: env_file 並列処理が無いと _compose_argv_prefix の `--env-file` が未署名 ambient に
        # 戻る。env_file_path is not None なら必ず verified copy + snapshot + bind を実施。

        # (1) source compose bytes 読込
        try:
            compose_bytes_inlock = backup_options.target_compose_file_path.read_bytes()
        except OSError as exc:
            print(f"ERROR: compose file not readable after lock acquisition: {exc} "
                  "[reason=backup_compose_file_unreadable]", file=sys.stderr)
            return 2
        compose_sha256_inlock = sha256(compose_bytes_inlock).hexdigest()
        # 注: expected_fp 計算と record claim verify は (5)-(6) で実施 (verified bind 完了後)。
        # 旧 plan で本 block 中に直接 compute_backup_runtime_binding_fingerprint() を呼んでいたが、
        # ADV2 R4 F-001 CRITICAL で削除済 (single full-helper + bind 後の順序統一)。
        # 下記 (5)-(6) ブロックを必ず通る順序で実装すること。
        # ADV R6 F-001 CRITICAL adopt: verified copy で `target_compose_file_path` 上書きは
        # **不可** (Docker Compose は compose file の project directory も runtime binding の一部で、
        # `build.context: .` / `env_file: .env.local` / `./data/artifacts` bind mount 等の相対 path が
        # project directory 基準で解決される)。/tmp に copy + replace すると未署名の相対 path 解決 +
        # config hash drift を起こすため、**署名済 source realpath を保持** + verified copy path を
        # **別 field に分離** + `_compose_argv_prefix` で `--project-directory <signed source parent>` を必ず渡す
        # ADV R7 F-001 CRITICAL adopt: verified copy を **audit-only から docker -f の immutable
        # execution input に昇格**させる (post-verify content swap window 物理閉鎖)。
        # 同時に `--project-directory <signed source parent>` で相対 path 解決基準を維持。
        # 結果: docker は (a) lock 内に read した bytes そのもの (verified copy) を読み、
        #        (b) build.context / env_file / bind mount の相対 path 解決は signed source parent で行う。
        # source realpath はもう docker に渡さない、ただし fingerprint には残す (canonical context)。
        verified_source_compose_realpath = backup_options.target_compose_file_path.resolve(strict=True)
        verified_source_project_dir = verified_source_compose_realpath.parent
        # ADV2 R1 F-005 HIGH adopt: 0o700 専用 temp dir + 0o400 file + sha256 再検証 + cleanup は private dir ごと
        # (same-UID tamper window 排除、/tmp directly NamedTemporaryFile では race 残存)
        verified_temp_dir = Path(tempfile.mkdtemp(prefix="taskhub-verified-compose-"))
        try:
            os.chmod(verified_temp_dir, 0o700)  # owner only
        except OSError:
            pass  # best-effort
        verified_compose_execution_input = verified_temp_dir / "compose.yml"
        # os.open with O_CREAT | O_EXCL | O_NOFOLLOW + mode 0o400 (read-only after write)
        fd = os.open(
            str(verified_compose_execution_input),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o400,
        )
        try:
            os.write(fd, compose_bytes_inlock)
            os.fsync(fd)
        finally:
            os.close(fd)
        # ADV2 R1 F-005 HIGH adopt: docker compose に渡す直前に sha256 再検証
        verify_bytes = verified_compose_execution_input.read_bytes()
        if sha256(verify_bytes).hexdigest() != compose_sha256_inlock:
            print(
                "ERROR: verified compose copy sha256 mismatch after write "
                "(same-UID tamper detected) [reason=backup_compose_verified_copy_tampered]",
                file=sys.stderr,
            )
            shutil.rmtree(verified_temp_dir, ignore_errors=True)
            return 2
        # ADV2 R3 F-002 CRITICAL adopt: verified copy 作成直後に metadata snapshot を取得し
        # BackupOptions に **必ず bind** (_compose_argv_prefix の tamper check が skip されないよう保証)
        verified_compose_lstat = os.lstat(str(verified_compose_execution_input))
        verified_compose_metadata_snapshot: dict[str, int | str] = {
            "dev": verified_compose_lstat.st_dev,
            "ino": verified_compose_lstat.st_ino,
            "uid": verified_compose_lstat.st_uid,
            "mode": stat.S_IMODE(verified_compose_lstat.st_mode),
            "sha256": compose_sha256_inlock,
        }
        # `target_compose_file_path` は引き続き **署名済 source realpath で immutable bind** (fingerprint と
        # audit identity 用; docker argv には verified copy が渡る、source realpath は dec)。
        # `verified_source_project_dir` は --project-directory に渡す (signed source parent、相対 path 解決基準)。
        # `verified_compose_execution_input` は docker compose `-f` の **実行入力** (lock 内 read bytes、immutable)。
        # (3) ADV2 R4 F-002 CRITICAL adopt: env_file 並列処理 (compose file と同 O_NOFOLLOW/O_EXCL/0o400 pattern)
        verified_env_file_execution_input: Path | None = None
        verified_env_file_metadata_snapshot: dict[str, int | str] | None = None
        if backup_options.env_file_path is not None:
            try:
                env_file_bytes_inlock = backup_options.env_file_path.read_bytes()
            except OSError as exc:
                print(f"ERROR: env file not readable after lock acquisition: {exc} "
                      "[reason=backup_compose_env_file_unreadable]", file=sys.stderr)
                shutil.rmtree(verified_temp_dir, ignore_errors=True)
                return 2
            env_file_sha256_inlock = sha256(env_file_bytes_inlock).hexdigest()
            verified_env_file_execution_input = verified_temp_dir / "env.env"  # 同一 private dir に配置
            env_fd = os.open(
                str(verified_env_file_execution_input),
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o400,
            )
            try:
                os.write(env_fd, env_file_bytes_inlock)
                os.fsync(env_fd)
            finally:
                os.close(env_fd)
            # sha256 再検証 (compose と同 same-UID tamper detection)
            verify_env_bytes = verified_env_file_execution_input.read_bytes()
            if sha256(verify_env_bytes).hexdigest() != env_file_sha256_inlock:
                print(
                    "ERROR: verified env file copy sha256 mismatch after write "
                    "[reason=backup_env_file_verified_copy_tampered]",
                    file=sys.stderr,
                )
                shutil.rmtree(verified_temp_dir, ignore_errors=True)
                return 2
            # metadata snapshot 取得 (compose と並列)
            env_lstat = os.lstat(str(verified_env_file_execution_input))
            verified_env_file_metadata_snapshot = {
                "dev": env_lstat.st_dev,
                "ino": env_lstat.st_ino,
                "uid": env_lstat.st_uid,
                "mode": stat.S_IMODE(env_lstat.st_mode),
                "sha256": env_file_sha256_inlock,
            }

        # (3.5) ADV2 R5 F-002 CRITICAL adopt: sops_env 並列 verified copy (compose と同 pattern)
        verified_sops_env_execution_input: Path | None = None
        verified_sops_env_metadata_snapshot: dict[str, int | str] | None = None
        if backup_options.include_sops_env:
            try:
                sops_env_bytes_inlock = backup_options.sops_env_path.read_bytes()
            except OSError as exc:
                print(f"ERROR: sops_env not readable after lock: {exc} "
                      "[reason=backup_payload_source_unreadable]", file=sys.stderr)
                shutil.rmtree(verified_temp_dir, ignore_errors=True)
                return 2
            sops_env_sha256_inlock = sha256(sops_env_bytes_inlock).hexdigest()
            verified_sops_env_execution_input = verified_temp_dir / "sops_env.bin"
            sops_fd = os.open(
                str(verified_sops_env_execution_input),
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o400,
            )
            try:
                os.write(sops_fd, sops_env_bytes_inlock)
                os.fsync(sops_fd)
            finally:
                os.close(sops_fd)
            if sha256(verified_sops_env_execution_input.read_bytes()).hexdigest() != sops_env_sha256_inlock:
                print("ERROR: verified sops_env copy sha256 mismatch [reason=backup_payload_source_tampered]",
                      file=sys.stderr)
                shutil.rmtree(verified_temp_dir, ignore_errors=True)
                return 2
            sops_lstat = os.lstat(str(verified_sops_env_execution_input))
            verified_sops_env_metadata_snapshot = {
                "dev": sops_lstat.st_dev, "ino": sops_lstat.st_ino, "uid": sops_lstat.st_uid,
                "mode": stat.S_IMODE(sops_lstat.st_mode), "sha256": sops_env_sha256_inlock,
            }

        # (3.6) ADV2 R11 F-001 CRITICAL adopt: artifacts staging は **service-stop window の内側** で実行する
        # → ここでは realpath snapshot + sidecar path **だけ** を準備 (snapshot 自体は cheap、staging copy は post-stop)
        # _verified_copy_tree_no_follow + manifest 計算は run_backup() 内の stop_app_services_via_compose_exec
        # **後** で実行される (api/worker 稼働中の artifacts snapshot を排除、DB/Redis stop 状態と
        # artifacts staging の時間整合性確保、ADR-00021 §11.2 consistency boundary 完全実装)。
        # snapshot / sidecar path は backup_options に bind するが、verified_artifacts_staging_dir と
        # verified_artifacts_manifest_sha256 は post-stop 段階で run_backup() 内で計算 + dataclasses.replace
        artifacts_dir_realpath_snapshot = backup_options.artifacts_dir.resolve(strict=True)
        verified_artifacts_source_mode_sidecar_path = verified_temp_dir / "artifacts_source_mode.json"
        # NOTE: verified_artifacts_staging_dir は **lock block 段階では未作成**、run_backup() 内で作成 + bind

        # (4) lock block 内 partial bind: compose / env_file / sops_env verified copy は **service-stop 前**
        # に作成 OK (config 系で payload ではない、stop 前後で content 不変)。
        # **artifacts_dir staging + manifest + fingerprint verify は run_backup() 内 post-stop**。
        # 4 整合 verify (output_path / include_sops_env / skip_service_stop / overwrite / age_public_key_fingerprint)
        # は record claim level で stop 前に実施可能 (caller-controlled metadata、payload content とは独立)。
        backup_options = dataclasses.replace(
            backup_options,
            target_compose_file_path=verified_source_compose_realpath,
            verified_source_project_dir=verified_source_project_dir,
            verified_compose_execution_input=verified_compose_execution_input,
            verified_compose_metadata_snapshot=verified_compose_metadata_snapshot,
            verified_env_file_execution_input=verified_env_file_execution_input,
            verified_env_file_metadata_snapshot=verified_env_file_metadata_snapshot,
            verified_sops_env_execution_input=verified_sops_env_execution_input,
            verified_sops_env_metadata_snapshot=verified_sops_env_metadata_snapshot,
            # artifacts: snapshot + sidecar path のみ bind、staging dir + manifest は run_backup 内 post-stop で bind
            artifacts_dir_realpath_snapshot=artifacts_dir_realpath_snapshot,
            verified_artifacts_source_mode_sidecar_path=verified_artifacts_source_mode_sidecar_path,
        )

        # (5) ADV2 R11 F-001 CRITICAL adopt: record claim level の 4 整合 verify は post-stop 前に実施 OK
        # (caller-controlled metadata、payload とは独立)。**fingerprint exact match verify は run_backup 内 post-stop**
        # (artifacts staging が必須入力のため、stop 後に staging → manifest → fingerprint compute → claim 比較)。
        # 4 整合 verify (output_path / age_public_key_fingerprint etc.) を別 helper に分離 + ここで呼出:
        _verify_backup_claim_4_field_match(record_backup_claim, expected_backup_claim)
        # → mismatch なら backup_claim_mismatch fail-closed (output_path / include_sops_env 等の caller metadata 不一致)

        # (6) **run_backup() に record_backup_claim を渡し、post-stop で artifacts staging + manifest + fingerprint verify**
        # run_backup signature 拡張 (ADV2 R11 F-001 CRITICAL adopt):
        # `run_backup(options, *, record_backup_claim, verified_temp_dir) -> BackupResult`
        # 実行順序 (consistency boundary 完全実装):
        #   (a) stop_app_services_via_compose_exec (api/worker stop)
        #   (b) _verified_copy_tree_no_follow (artifacts_dir_realpath_snapshot → verified_artifacts_staging_dir)
        #   (c) _compute_artifacts_dir_manifest_sha256 → verified_artifacts_manifest_sha256
        #   (d) backup_options = dataclasses.replace(options, verified_artifacts_staging_dir=..., verified_artifacts_manifest_sha256=...)
        #   (e) compute_full_backup_runtime_binding_fingerprint(backup_options, mode="redeem")
        #   (f) record_backup_claim.backup_runtime_binding_fingerprint vs expected exact match → mismatch なら raise BackupRuntimeError("backup_claim_mismatch")
        #   (g) verify_pg_hba + pg_dump + Redis SAVE + compose cp + archive (verified staging から、stop window 内)
        #   (h) finally で start_app_services_wait_healthy (R2 F-003 / R6 F-002 fatal)

    try:
        result = run_backup(
            backup_options,
            record_backup_claim=record_backup_claim,
            verified_temp_dir=verified_temp_dir,
        )
        # ... existing exception handling
    finally:
        # ADV R7 F-001 + ADV2 R1 F-005 fix: verified copy private dir 全体を cleanup
        # (best-effort、runbook §13 で manual SOP も併記)
        if 'verified_temp_dir' in dir():
            try:
                shutil.rmtree(verified_temp_dir, ignore_errors=True)
            except OSError:
                pass
```

**ADV R3 F-001 CRITICAL adopt 詳細**:

`invoke_age_encrypt` は次のように改修して **recipient override が指定された場合は path 再読込しない**:

```python
def invoke_age_encrypt(
    plaintext_path: Path,
    output_path: Path,
    public_key_path: Path,
    *,
    verified_recipient: str | None = None,  # ADV R3 F-001 CRITICAL adopt
    timeout_sec: int = 1800,
) -> None:
    """SOPS+age で plaintext_path を encrypt して output_path に書き出す.

    ADV R3 F-001 CRITICAL adopt: verified_recipient が指定された場合は
    public_key_path を再読込せず、検証済み recipient string をそのまま使う
    (lock 内 fingerprint verify 後の TOCTOU race を排除)。
    """
    if verified_recipient is not None:
        recipient = verified_recipient
    else:
        # legacy 経路 (PR #77 互換、verified_recipient 未指定時のみ)
        recipient = public_key_path.read_text(encoding="ascii").strip()
        if not recipient.startswith("age1"):
            raise BackupRuntimeError(
                "backup_age_recipient_invalid",
                detail=f"public_key prefix invalid: {recipient[:8]!r}",
            )
    argv = ["age", "--encrypt", "--recipient", recipient, "--output", str(output_path), str(plaintext_path)]
    # ... 既存 subprocess invocation (timeout / SafeSubprocessConfig)
```

`run_backup` は受け取った `backup_options.verified_age_recipient` を `invoke_age_encrypt` に伝播する (lock 内で bind 済みの場合、path 再読込を抑止して fingerprint 検証時の bytes を確定 recipient として使用)。

これにより `backup`, `restore`, `restore-rollback` の 3 destructive subcommand が同一 host で mutual exclusion + age key file の TOCTOU 排除。

### 2.6 backup 時 service stop/restart consistency boundary (ADV R1 F-001 CRITICAL adopt)

ADR-00021 §11.2 split-brain prevention + backup 時の **全 service consistency boundary** が PR #77 では未確立。Phase 5 で:

1. `stop_app_services(options)` (api / worker stop、container 内 DB / Redis write 停止)
2. postgres / redis healthy 確認 (`start_postgres_wait_healthy` / `start_redis_service_wait_healthy` を skip して既存 running を利用)
3. **pg_dump + Redis SAVE + artifacts copy** を同一 service-stop window 内で実行
4. backup file 完成 (atomic rename 後)
5. `start_app_services_wait_healthy(options)` (api / worker restart)
6. 失敗時の rollback: app stop 状態のまま structured error、operator manual recovery

`options.skip_service_stop=True` の場合は (test/dev env 用)、`stop_app_services` を skip + warning audit emit (PR #77 既存 invariant 維持)。

これにより backup 中の DB / Redis write 不整合を排除、ADR-00021 §11.2 consistency boundary を確立。

### 2.7 BackupOptions default 修正 (ADV R1 F-006 adopt)

`BackupOptions.from_environment` default:
- 旧: `pg_user="taskhub", pg_db="taskhub"` (PR #77 default、docker-compose.yml と乖離)
- 新: `pg_user="taskmanagedai", pg_db="taskmanagedai"` (docker-compose.yml `POSTGRES_USER` / `POSTGRES_DB` default 整合)

旧 default を必要とする legacy host は env override (`TASKHUB_BACKUP_PG_USER` / `TASKHUB_BACKUP_PG_DB`) で明示。

---

## §3 scope (4 batches)

### Batch A: BackupOptions に Compose binding field 追加 + 既存 default 修正 + 旧 invoke_pg_dump 削除

#### 3.A.1 BackupOptions 拡張 (`scripts/taskhub_backup_orchestrator.py`)

```python
@dataclasses.dataclass(frozen=True)
class BackupOptions:
    # ... existing fields ...
    pg_host: str
    pg_port: int
    pg_user: str
    pg_db: str
    redis_host: str
    redis_port: int
    artifacts_dir: Path
    sops_env_path: Path
    # ADV R1 F-002 adopt: Phase 5 compose exec 経路では pgpassfile は使わない、optional 化
    pgpassfile_path: Path | None = None  # PR #77 では必須、Phase 5 では None 許容
    # SP022-T02 Phase 5 新規 field (Compose binding、ADV R1 F-010 path normalize)
    target_compose_project_name: str = "taskmanagedai"
    target_compose_file_path: Path = Path("/dev/null")  # sentinel、from_environment で必ず override
    # ADV R3 F-001 CRITICAL adopt: lock 内 fingerprint verify 後に bind される確定 recipient
    # (path 再読込経路を物理閉鎖、TOCTOU 排除)。CLI 起動 → lock 取得 → fingerprint OK 後の
    # dataclasses.replace で immutable bind。default=None は legacy 経路 (PR #77 互換) を保つ
    verified_age_recipient: str | None = None
    # ADV R6 F-001 CRITICAL adopt: 署名済 compose file source の project directory
    # (build.context / env_file / bind mount の相対 path 解決基準)。
    # docker compose CLI で `--project-directory` に必ず渡す。default=None は CLI 起動直後の bind 前
    verified_source_project_dir: Path | None = None
    # ADV R7 F-001 CRITICAL adopt: verified copy path (lock 内 read した compose bytes の immutable copy)。
    # docker compose `-f` に **必ず渡す** (post-verify content swap window 物理閉鎖)。
    # default=None は CLI 起動直後の bind 前、R6 で audit-only にしたが R7 で execution input に昇格。
    verified_compose_execution_input: Path | None = None
    # ADV2 R2 F-001 HIGH adopt: env_file binding (source path + verified copy + sha256 fingerprint)
    # docker compose の env interpolation を未署名 ambient .env / process env に解決させない
    env_file_path: Path | None = None  # source realpath、env override TASKHUB_BACKUP_ENV_FILE 経由
    verified_env_file_execution_input: Path | None = None  # lock 内 verified copy、_compose_argv_prefix で --env-file
    # ADV2 R2 F-004 HIGH adopt: verified copy の作成時 metadata snapshot
    # (各 docker compose 呼出直前に再検証して unlink/rename swap を検知)
    verified_compose_metadata_snapshot: dict[str, int | str] | None = None  # {dev, ino, uid, mode, sha256}
    verified_env_file_metadata_snapshot: dict[str, int | str] | None = None
    # ADV2 R5 F-002 CRITICAL adopt: payload source TOCTOU 防御 (sops_env + artifacts_dir verified staging)
    # sops_env は O_NOFOLLOW read + private temp verified copy + sha256/metadata snapshot
    verified_sops_env_execution_input: Path | None = None  # docker compose env_file 兼用ではない、archive 用 sops_env
    verified_sops_env_metadata_snapshot: dict[str, int | str] | None = None
    # artifacts_dir は directory tree のため、lock 内で no-follow tree copy → manifest hash 再検証 →
    # run_backup が staged tree のみ読込 (caller-controlled symlink swap を完全に閉鎖)
    verified_artifacts_staging_dir: Path | None = None  # lock 内 staging copy 先 (private dir 配下)
    verified_artifacts_manifest_sha256: str | None = None  # manifest hash (re-verify 用)
    # ADV2 R6 F-002 CRITICAL adopt: source artifacts_dir realpath を lock 内で一度 snapshot 化、
    # fingerprint helper は都度 resolve せずこの immutable snapshot を使う (caller-controlled
    # rename/symlink swap の TOCTOU 経路を canonical context から排除)
    artifacts_dir_realpath_snapshot: Path | None = None
    # ADV2 R8 F-002 CRITICAL adopt: source mode sidecar path (verified_temp_dir 直下、staging tree の外)
    # archive payload には混入せず、manifest helper で mode_source="source_lstat" 経路から読込
    verified_artifacts_source_mode_sidecar_path: Path | None = None

    @classmethod
    def from_environment(cls, *, output_path, repo_root, include_sops_env=False,
                         skip_service_stop=False, overwrite=False) -> BackupOptions:
        # ADV R1 F-006 adopt: docker-compose.yml default 整合 (taskhub → taskmanagedai)
        pg_user = os.environ.get("TASKHUB_BACKUP_PG_USER", "taskmanagedai")
        pg_db = os.environ.get("TASKHUB_BACKUP_PG_DB", "taskmanagedai")

        # ADV R1 F-010 adopt: Compose binding を expanduser + resolve(strict=False) で正規化
        target_compose_project = os.environ.get(
            "TASKHUB_BACKUP_COMPOSE_PROJECT", "taskmanagedai",
        )
        target_compose_file_raw = os.environ.get(
            "TASKHUB_BACKUP_COMPOSE_FILE",
            str(repo_root / "docker-compose.yml"),
        )
        target_compose_file = Path(target_compose_file_raw).expanduser().resolve(strict=False)

        # ADV R1 F-004 adopt: server-owned validation (env override allowlist)
        if not re.fullmatch(r"^[a-z0-9][a-z0-9_-]*$", target_compose_project):
            raise BackupUsageError(
                "backup_output_path_invalid",
                detail=f"target_compose_project_name invalid: {target_compose_project!r}",
            )
        # ADV R2 F-001 adopt: prefix string match は sibling escape (e.g., /srv/taskhub-evil/...) を
        # 許容するため、`Path.is_relative_to()` で厳密判定
        target_compose_file_resolved = target_compose_file
        repo_root_resolved = repo_root.expanduser().resolve(strict=False)
        allowed_roots = [repo_root_resolved, Path("/etc"), Path("/var/lib")]
        if not any(
            target_compose_file_resolved.is_relative_to(root) for root in allowed_roots
        ):
            raise BackupUsageError(
                "backup_output_path_invalid",
                detail=(
                    f"target_compose_file_path not in allowed root "
                    f"(repo_root / /etc / /var/lib): {target_compose_file_resolved}"
                ),
            )

        # ADV2 R9 F-001 CRITICAL adopt: env_file_path を server-owned に解決 + allowlist 検証 + 必須 bind
        # default `<repo>/.env.local` (docker-compose.yml 仕様、TASKMANAGEDAI_ENVIRONMENT / *_COOKIE_SECRET 等 interpolation 用)
        env_file_raw = os.environ.get(
            "TASKHUB_BACKUP_ENV_FILE",
            str(repo_root / ".env.local"),
        )
        env_file_path = Path(env_file_raw).expanduser().resolve(strict=False)
        # allowlist validation (target_compose_file_path と同じ pattern)
        if not any(env_file_path.is_relative_to(root) for root in allowed_roots):
            raise BackupUsageError(
                "backup_output_path_invalid",
                detail=(
                    f"env_file_path not in allowed root (repo_root / /etc / /var/lib): {env_file_path}"
                ),
            )
        # 存在確認 (Phase 5 では env_file は server-owned required、不存在は fail-closed)
        if not env_file_path.is_file():
            raise BackupUsageError(
                "backup_compose_env_file_unreadable",
                detail=f"env_file_path not found: {env_file_path}",
            )

        return cls(
            # ... existing field assignment ...
            pg_user=pg_user, pg_db=pg_db,
            pgpassfile_path=None,  # Phase 5 では None default、env override 廃止
            target_compose_project_name=target_compose_project,
            target_compose_file_path=target_compose_file,
            env_file_path=env_file_path,  # ADV2 R9 F-001 CRITICAL adopt: signed env file binding
        )
```

#### 3.A.2 _compose_argv_prefix helper (`scripts/taskhub_backup_orchestrator.py`)

```python
def _compose_argv_prefix(options: BackupOptions) -> list[str]:
    """docker compose に -p <project> + -f <verified_compose_execution_input> + --project-directory 明示
    (ADV R6 F-001 + R7 F-001 CRITICAL adopt).

    ADV R7 F-001 CRITICAL adopt: `-f` には **verified_compose_execution_input** を渡す
    (lock 内に read した compose bytes の immutable copy、post-verify content swap window 物理閉鎖)。
    署名済 source realpath は fingerprint と audit identity 用に保持され、docker argv には渡らない。

    ADV R6 F-001 CRITICAL adopt: `--project-directory` には **verified_source_project_dir**
    (= signed source realpath の parent) を渡す。docker compose は --project-directory 未指定時、
    `build.context: .` / `env_file: .env.local` / `./data/artifacts` bind mount 等の相対 path を
    **compose file の親 directory** から解決するため、ここを固定して別 directory への drift を物理閉鎖。
    """
    # lock 取得 + in-lock verify 後の bind 完了状態を前提 (admin.py _cmd_backup の lock block 内呼出)
    if options.verified_compose_execution_input is None or options.verified_source_project_dir is None:
        # Pre-lock 段階で docker compose を呼ぶ経路は本 Phase 5 では存在しない (PR #77 host TCP 経路は削除)。
        # fallback で signed source realpath を直接渡すと post-verify content swap window が開くため、
        # ここでは fail-closed に Raises (R7 F-001 防御策)。
        raise BackupRuntimeError(
            "backup_compose_binding_not_initialized",
            detail="verified_compose_execution_input / verified_source_project_dir must be bound before _compose_argv_prefix",
        )
    # ADV2 R2 F-004 + R3 F-002 CRITICAL adopt: 各 docker compose 呼出直前に verified copy の metadata snapshot 再検証
    # (作成時の dev/inode/uid/mode/sha256 と一致しなければ same-UID unlink/rename swap として fail-closed)
    # snapshot 未設定は **未初期化 = fail-closed** (verified_compose_execution_input が set でも snapshot が None なら拒否)
    if options.verified_compose_metadata_snapshot is None:
        raise BackupRuntimeError(
            "backup_compose_binding_not_initialized",
            detail="verified_compose_metadata_snapshot must be bound alongside verified_compose_execution_input",
        )
    st = os.lstat(str(options.verified_compose_execution_input))
    current_sha = sha256(options.verified_compose_execution_input.read_bytes()).hexdigest()
    snapshot = options.verified_compose_metadata_snapshot
    if (
        st.st_dev != snapshot["dev"]
        or st.st_ino != snapshot["ino"]
        or st.st_uid != snapshot["uid"]
        or stat.S_IMODE(st.st_mode) != snapshot["mode"]
        or current_sha != snapshot["sha256"]
    ):
        raise BackupRuntimeError(
            "backup_compose_verified_copy_tampered",
            detail=f"verified compose metadata mismatch before docker compose call: "
                   f"dev/ino/uid/mode/sha mismatch (same-UID unlink/rename swap detected)",
        )
    # env file がある場合も同様に再検証
    # ADV2 R4 F-002 + R9 F-002 CRITICAL adopt: cross-field invariant 強化
    # - env_file_path is not None なら verified_env_file_execution_input 必須 (option set + verified missing 禁止)
    # - env_file_path is None なら verified_env_file_execution_input も None 必須 (逆方向 invariant)
    if options.env_file_path is not None and options.verified_env_file_execution_input is None:
        raise BackupRuntimeError(
            "backup_compose_binding_not_initialized",
            detail="options.env_file_path set but verified_env_file_execution_input not bound (invariant violation)",
        )
    if options.env_file_path is None and options.verified_env_file_execution_input is not None:
        raise BackupRuntimeError(
            "backup_compose_binding_not_initialized",
            detail="verified_env_file_execution_input bound but options.env_file_path is None (invariant violation)",
        )
    if options.verified_env_file_execution_input is not None:
        if options.verified_env_file_metadata_snapshot is None:
            raise BackupRuntimeError(
                "backup_compose_binding_not_initialized",
                detail="verified_env_file_metadata_snapshot must be bound alongside verified_env_file_execution_input",
            )
        st = os.lstat(str(options.verified_env_file_execution_input))
        current_sha = sha256(options.verified_env_file_execution_input.read_bytes()).hexdigest()
        snapshot = options.verified_env_file_metadata_snapshot
        if (
            st.st_dev != snapshot["dev"] or st.st_ino != snapshot["ino"]
            or st.st_uid != snapshot["uid"]
            or stat.S_IMODE(st.st_mode) != snapshot["mode"]
            or current_sha != snapshot["sha256"]
        ):
            raise BackupRuntimeError(
                "backup_env_file_verified_copy_tampered",
                detail="verified env file metadata mismatch before docker compose call",
            )
    argv = [
        "docker", "compose",
        "-p", options.target_compose_project_name,
        "-f", str(options.verified_compose_execution_input),
        "--project-directory", str(options.verified_source_project_dir),
    ]
    if options.verified_env_file_execution_input is not None:
        argv.extend(["--env-file", str(options.verified_env_file_execution_input)])
    return argv
```

#### 3.A.3 旧 invoke_pg_dump (host TCP) 削除 + invoke_redis_rdb (host TCP --rdb) 削除

PR #77 の `invoke_pg_dump` (host TCP + PGPASSFILE) と `invoke_redis_rdb` (host TCP --rdb) を **削除** (ADV R1 F-002 adopt)。`run_backup` 内呼出も新 compose exec 関数に切替 (Batch B)。

#### 3.A.4 DEFAULT_ENV_ALLOWLIST から PGPASSFILE 削除 (`scripts/taskhub_subprocess_runner.py`)

```python
DEFAULT_ENV_ALLOWLIST = frozenset({
    # PGPASSFILE 削除 (ADV R1 F-008 adopt: Phase 5 compose exec 経路では不要)
    "PATH", "LANG", "LC_ALL", "LC_CTYPE", "HOME", "TZ", "TMPDIR",
    # ... existing other entries
})
```

旧 host TCP `invoke_pg_dump` が削除されるため、PGPASSFILE の env propagate path は完全消滅。

### Batch B: invoke_pg_dump_via_compose_exec + Redis SAVE + docker compose cp + verify_pg_hba_trust_auth + service stop/restart

#### 3.B.1 verify_pg_hba_trust_auth_via_compose_exec (`scripts/taskhub_backup_orchestrator.py`)

§2.4 参照。pg_dump 前に trust auth 前提を verify、fail-closed で `backup_pg_dump_failed`。

#### 3.B.2 invoke_pg_dump_via_compose_exec (`scripts/taskhub_backup_orchestrator.py`)

```python
def invoke_pg_dump_via_compose_exec(
    options: BackupOptions, output_path: Path, *, timeout_sec: int,
) -> SubprocessResult:
    """SP022-T02 Phase 5: pg_dump via docker compose exec + container 内 unix socket.

    Phase 3 restore invoke_pg_dump_via_compose_exec と対称 (snapshot 用)、--no-acl / --no-owner
    で identical argv (ADV R1 F-014 adopt).
    """
    argv = (
        _compose_argv_prefix(options)
        + ["exec", "-T", "postgres", "pg_dump"]
        + [f"--username={options.pg_user}"]
        + [f"--dbname={options.pg_db}"]
        # ADV R1 F-014 adopt: Phase 3 restore snapshot 同 argv (--no-acl + --no-owner)
        + ["--format=custom", "--no-acl", "--no-owner",
           "--single-transaction",
           "--no-password",
           "-h", "/var/run/postgresql"]
    )
    with output_path.open("wb") as f:
        # ADV R1 F-011 adopt: _run_subprocess_with_tool_check wrapper で error 正規化
        return _run_subprocess_with_tool_check(
            argv,
            SafeSubprocessConfig(
                timeout_sec=timeout_sec,
                capture_stdout=False,
                stdout_file=f,
            ),
            "backup_pg_dump_tool_not_found",
        )
```

#### 3.B.3 invoke_redis_save_via_compose_exec (`scripts/taskhub_backup_orchestrator.py`)

```python
def invoke_redis_save_via_compose_exec(
    options: BackupOptions, *, timeout_sec: int,
) -> SubprocessResult:
    """SP022-T02 Phase 5: redis-cli SAVE (blocking) via compose exec.

    Phase 3 restore SAVE と対称、race-free.
    """
    argv = _compose_argv_prefix(options) + ["exec", "-T", "redis", "redis-cli", "SAVE"]
    return _run_subprocess_with_tool_check(
        argv,
        SafeSubprocessConfig(timeout_sec=timeout_sec),
        "backup_redis_rdb_tool_not_found",
    )
```

#### 3.B.4 invoke_redis_dump_copy_via_compose_cp (`scripts/taskhub_backup_orchestrator.py`、ADV R1 F-005 + F-012 adopt)

```python
def invoke_redis_dump_copy_via_compose_cp(
    options: BackupOptions, output_path: Path, *, timeout_sec: int,
) -> SubprocessResult:
    """SP022-T02 Phase 5: docker compose cp redis:/data/dump.rdb <output>.

    ADV R1 F-005 adopt: Docker Desktop for Mac の named volume host path 不確実性を回避、
    docker compose cp で container 内 file を stream copy.
    ADV R1 F-012 + ADV2 R1 F-008 + R14 F-001 adopt: tmp file を **output_path.parent 直下の
    predictable name ではなく、private temp directory 配下** に作成 (`tempfile.mkdtemp` で 0o700)。
    docker compose cp は private dir 内 tmp file に出力 → regular file / fsync 検証 → os.replace で
    output_path に rename → private dir 全体を cleanup。external symlink swap を物理閉鎖
    (post-check 検出ではなく「外部 symlink へ書けない」を担保)。
    """
    # ADV2 R14 F-001 HIGH adopt: private dir に tmp file を作成 (predictable path での symlink swap 防御)
    private_tmp_dir = Path(tempfile.mkdtemp(dir=output_path.parent, prefix=".taskhub-redis-rdb-"))
    try:
        os.chmod(private_tmp_dir, 0o700)
    except OSError:
        pass
    tmp_path = private_tmp_dir / "dump.rdb.tmp"
    tmp_fd = os.open(
        str(tmp_path),
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    os.close(tmp_fd)  # docker compose cp が書く前に close (file 自体は存在)
    try:
        # docker compose cp 前: tmp_path が regular file (no symlink) であることを再確認
        st_before = os.lstat(str(tmp_path))
        if not stat.S_ISREG(st_before.st_mode):
            raise BackupRuntimeError(
                "backup_redis_rdb_tmp_not_regular_file",
                detail=f"tmp_path is not regular file: mode={oct(st_before.st_mode)}",
            )
        argv = _compose_argv_prefix(options) + [
            "cp", "redis:/data/dump.rdb", str(tmp_path),
        ]
        result = _run_subprocess_with_tool_check(
            argv,
            SafeSubprocessConfig(timeout_sec=timeout_sec),
            "backup_redis_rdb_tool_not_found",
        )
        if result.returncode != 0:
            tmp_path.unlink(missing_ok=True)
            return result
        # docker compose cp 後: regular file 再確認 (symlink swap 検知)
        st_after = os.lstat(str(tmp_path))
        if not stat.S_ISREG(st_after.st_mode):
            tmp_path.unlink(missing_ok=True)
            raise BackupRuntimeError(
                "backup_redis_rdb_tmp_not_regular_file",
                detail="tmp_path mutated to non-regular file after docker compose cp",
            )
    except (OSError, BackupRuntimeError):
        # ADV2 R1 F-008 + R14 F-001 adopt: 全 OSError path で private dir 全体 cleanup
        shutil.rmtree(private_tmp_dir, ignore_errors=True)
        raise
    # fsync 可能なら fsync + atomic rename + parent dir fsync (ADV2 R1 F-008 adopt)
    try:
        with tmp_path.open("rb+") as f:
            os.fsync(f.fileno())
    except OSError:
        pass
    os.replace(str(tmp_path), str(output_path))
    # ADV2 R1 F-008 MEDIUM adopt: parent directory fsync で rename を durable に
    try:
        parent_fd = os.open(str(output_path.parent), os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except OSError:
        pass  # best-effort、tmpfs 等 fsync 不可な fs では continue
    # ADV2 R14 F-001 HIGH adopt: private dir 全体を cleanup (success path も)
    shutil.rmtree(private_tmp_dir, ignore_errors=True)
    return result
```

#### 3.B.5 stop_app_services / start_app_services_wait_healthy helpers (ADV R1 F-001 CRITICAL adopt)

Phase 3 restore_orchestrator.py の同名関数を **backup direction でも実装** (BackupOptions 受取版):

```python
# ADV R2 F-003 adopt: 新 ReasonCode 2 種を ReasonCode Literal に追加
# - "backup_service_stop_failed" (api/worker stop 失敗、致命的)
# - "backup_service_start_failed" (api/worker restart 失敗、致命的、recovery SOP runbook 参照)
# stop / restart failure は **両方 致命的** (warning 流用は WarningCode Literal 3 種制約 + mypy gate 違反)


def stop_app_services_via_compose_exec(options: BackupOptions, *, timeout_sec: int = 60) -> None:
    """SP022-T02 Phase 5: backup 中の DB/Redis write 停止 (api/worker stop).

    ADV R1 F-001 + R2 F-003 adopt: ADR-00021 §11.2 consistency boundary 確立、stop 失敗は致命的.
    """
    argv = _compose_argv_prefix(options) + ["stop", "--timeout=30", "api", "worker"]
    result = _run_subprocess_with_tool_check(
        argv,
        SafeSubprocessConfig(timeout_sec=timeout_sec),
        "backup_service_stop_failed",  # ADV R2 F-003 adopt: 専用 reason_code
    )
    if result.returncode != 0:
        raise BackupRuntimeError(
            "backup_service_stop_failed",  # ADV R2 F-003 adopt
            detail=f"stop_app_services failed: exit={result.returncode}",
        )


def start_app_services_wait_healthy_via_compose_exec(
    options: BackupOptions, *, timeout_sec: int = 180,
) -> None:
    """SP022-T02 Phase 5: backup 完了後の api/worker 再起動 + healthy 確認.

    ADV R2 F-003 adopt: restart 失敗は致命的 (api/worker down 状態のまま success 扱いは
    consistency boundary violation、warning 降格不可).
    """
    up_argv = _compose_argv_prefix(options) + ["up", "-d", "api", "worker"]
    up_result = _run_subprocess_with_tool_check(
        up_argv,
        SafeSubprocessConfig(timeout_sec=timeout_sec // 3),
        "backup_service_start_failed",
    )
    if up_result.returncode != 0:
        raise BackupRuntimeError(
            "backup_service_start_failed",
            detail=f"start_app_services up failed: exit={up_result.returncode}",
        )
    # ADV2 R1 F-010 MEDIUM adopt: healthcheck polling 詳細を明記 (Phase 3 restore を移植):
    # - `docker compose ps --format json --status running api worker` を 2 秒ごと polling
    # - 各 service の `Health` field を確認 (compose v2.27+ は `Health="healthy"`、v2.26 以下は
    #   `Status` に `healthy`/`unhealthy` substring を含む。両方の format を受け入れる parser)
    # - JSON-lines / JSON-array 両形式に対応 (compose v2 系で出力形式 fluctuation あり)
    # - target service filter: **`Service` field** に対する exact match `{api, worker}` (ADV2 R2 F-005 HIGH adopt:
    #   Compose v2 の `Name` field は `taskmanagedai-api-1` のような container name で service 名と乖離。
    #   `Service` field が service 名 (api / worker) の primary key)。Name は fallback の suffix pattern まで許容
    # - accepted state: Health == "healthy" の場合のみ accept、None / "starting" / "unhealthy" は wait
    # - timeout: timeout_sec // 2 (default 90 秒)、超過時 BackupRuntimeError("backup_service_start_failed")
    # - backoff: 2 秒固定 (Phase 3 restore と同 pattern)
    deadline = time.monotonic() + timeout_sec // 2
    while time.monotonic() < deadline:
        ps_argv = _compose_argv_prefix(options) + [
            "ps", "--format", "json", "--status", "running", "api", "worker",
        ]
        ps_result = _run_subprocess_with_tool_check(
            ps_argv, SafeSubprocessConfig(timeout_sec=10),
            "backup_service_start_failed",
        )
        if ps_result.returncode == 0 and _parse_compose_ps_healthy(ps_result.stdout, {"api", "worker"}):
            return
        time.sleep(2)
    raise BackupRuntimeError(
        "backup_service_start_failed",
        detail=f"api/worker not healthy within {timeout_sec // 2}s polling",
    )
```

#### 3.B.6 run_backup の pg_dump + redis 部分を compose exec 経路 + service stop/restart に切替

```python
def run_backup(
    options: BackupOptions,
    *,
    record_backup_claim: BackupApprovalClaim,  # ADV2 R11 F-001 + R13 F-001 HIGH adopt: Phase 5 では必須
    verified_temp_dir: Path,  # ADV2 R13 F-001 HIGH adopt: 必須化 (Phase 5 real I/O の security 入力)
) -> BackupResult:
    # ADV2 R13 F-001 + R14 F-002 HIGH/MEDIUM adopt: Phase 5 では record_backup_claim / verified_temp_dir 必須
    # 加えて入口で legacy claim (backup_runtime_binding_fingerprint=None) を明示的に reject
    # (型レベル必須化だけでは BackupApprovalClaim.backup_runtime_binding_fingerprint: str | None の
    # parser 互換性が残り、_cmd_backup 側 reject に依存しすぎる。run_backup 自体が defense-in-depth で reject)
    if record_backup_claim.backup_runtime_binding_fingerprint is None:
        raise BackupRuntimeError(
            "backup_claim_legacy_runtime_binding_unsupported",
            detail="run_backup received legacy 5-field BackupApprovalClaim (fingerprint=None). "
                   "Phase 5 requires 6-field record. Re-issue via taskhub approval issue.",
        )
    # ... existing validation ...
    primary_exc: Exception | None = None
    stopped_or_attempted = False

    # ADV2 R1 F-004 HIGH adopt: stop も try 内に移動 + stopped_or_attempted flag で restart 保証
    try:
        # ADV R1 F-001 CRITICAL adopt: consistency boundary、skip_service_stop=False で app stop
        if not options.skip_service_stop:
            stopped_or_attempted = True  # stop 試行を記録 (partial stop 失敗時も restart 試行)
            stop_app_services_via_compose_exec(options)
        else:
            warnings_list.append("backup_service_stop_skipped")

        # ADV2 R11 F-001 + R13 F-001 CRITICAL/HIGH adopt: artifacts staging を **post-stop window 内** で実行
        # (record_backup_claim / verified_temp_dir は型レベルで必須、None check は signature が排除)
        verified_artifacts_staging_dir = verified_temp_dir / "artifacts"
        if True:  # 型レベル必須化のため条件分岐は除去 (旧 None check は signature 必須化で不要)
            os.makedirs(verified_artifacts_staging_dir, mode=0o700, exist_ok=False)
            _verified_copy_tree_no_follow(
                src=options.artifacts_dir_realpath_snapshot,
                dst=verified_artifacts_staging_dir,
                root_lstat_anchor=os.lstat(str(options.artifacts_dir_realpath_snapshot)),
                source_mode_sidecar_path=options.verified_artifacts_source_mode_sidecar_path,
            )
            verified_artifacts_manifest_sha256 = _compute_artifacts_dir_manifest_sha256(
                verified_artifacts_staging_dir,
                mode_source="source_lstat",
                source_mode_sidecar_path=options.verified_artifacts_source_mode_sidecar_path,
            )
            options = dataclasses.replace(
                options,
                verified_artifacts_staging_dir=verified_artifacts_staging_dir,
                verified_artifacts_manifest_sha256=verified_artifacts_manifest_sha256,
            )
            # ADV2 R11 F-001 CRITICAL adopt: post-stop で fingerprint verify (artifacts manifest 含む)
            expected_fp = compute_full_backup_runtime_binding_fingerprint(options, mode="redeem")
            if record_backup_claim.backup_runtime_binding_fingerprint != expected_fp:
                raise BackupRuntimeError(
                    "backup_claim_mismatch",
                    detail=(
                        f"backup_runtime_binding_fingerprint post-stop mismatch "
                        f"(claim={record_backup_claim.backup_runtime_binding_fingerprint[:16]}, "
                        f"computed={expected_fp[:16]})"
                    ),
                )

        # ADV R1 F-007 adopt: pg_hba trust auth preflight
        verify_pg_hba_trust_auth_via_compose_exec(
            options, timeout_sec=30,
        )

        # pg_dump (Phase 5: compose exec 経路)
        result = invoke_pg_dump_via_compose_exec(
            options,
            output_path=pg_dump_output,
            timeout_sec=options.pg_dump_timeout_sec,
        )
        if result.returncode != 0:
            raise BackupRuntimeError("backup_pg_dump_failed", detail=f"exit={result.returncode}")

        # Redis SAVE + compose cp (Phase 5: ADV R1 F-005 adopt)
        save_result = invoke_redis_save_via_compose_exec(
            options, timeout_sec=options.redis_rdb_timeout_sec,
        )
        if save_result.returncode != 0:
            raise BackupRuntimeError(
                "backup_redis_rdb_failed",
                detail=f"redis_save_exit={save_result.returncode}",
            )
        copy_result = invoke_redis_dump_copy_via_compose_cp(
            options, output_path=redis_rdb_output,
            timeout_sec=options.redis_rdb_timeout_sec,
        )
        if copy_result.returncode != 0:
            raise BackupRuntimeError(
                "backup_redis_rdb_failed",
                detail=f"compose_cp_exit={copy_result.returncode}",
            )

        # ADV2 R12 F-001 CRITICAL adopt: post-stop staging で dataclasses.replace された `options` を archive 経路
        # でも単一正本として使用 (`backup_options` ではなく `options`、run_backup signature の引数名に統一)
        # **必ず options.verified_artifacts_staging_dir から archive 作成** (caller-controlled source path を一切読まない)
        # archive 作成直前に manifest hash 再検証 (options.verified_artifacts_manifest_sha256 と staging tree 再計算 hash を比較)
        current_manifest_sha = _compute_artifacts_dir_manifest_sha256(
            options.verified_artifacts_staging_dir,
            mode_source="source_lstat",  # ADV2 R8 F-001 必須 keyword-only
            source_mode_sidecar_path=options.verified_artifacts_source_mode_sidecar_path,  # ADV2 R8 F-002
        )
        if current_manifest_sha != options.verified_artifacts_manifest_sha256:
            raise BackupRuntimeError(
                "backup_artifacts_staging_tampered",
                detail=f"verified_artifacts_staging_dir manifest mismatch: expected={options.verified_artifacts_manifest_sha256[:16]}, got={current_manifest_sha[:16]}",
            )
        # sops_env copy 経路も同様、verified_sops_env_execution_input のみ読込 (metadata snapshot 再検証あり)
        if options.include_sops_env:
            if options.verified_sops_env_metadata_snapshot is None:
                raise BackupRuntimeError(
                    "backup_compose_binding_not_initialized",
                    detail="verified_sops_env_metadata_snapshot must be bound when include_sops_env=true",
                )
            # _verify_metadata_snapshot helper で dev/ino/uid/mode/sha256 比較 (compose / env_file と同 pattern)
            _verify_metadata_snapshot(
                options.verified_sops_env_execution_input,
                options.verified_sops_env_metadata_snapshot,
                tamper_reason="backup_payload_source_tampered",
            )
        # ... (age encrypt / atomic rename / final artifact write、`options.*` を使う、`backup_options.*` 残存禁止)

    except BackupRuntimeError as exc:
        # ADV2 R1 F-007 MEDIUM adopt: primary failure reason を保持
        primary_exc = exc
        raise
    finally:
        # ADV R1 F-001 + R2 F-003 + ADV2 R1 F-004/F-007 adopt: backup 完了 / 失敗 / partial stop 失敗
        # どちらでも app restart 試行 (stopped_or_attempted flag で stop 試行があれば必ず restart)
        if stopped_or_attempted:
            try:
                start_app_services_wait_healthy_via_compose_exec(options)
            except BackupRuntimeError as restart_exc:
                # ADV2 R1 F-007 MEDIUM adopt: primary failure と restart failure の両方を audit
                if primary_exc is not None:
                    # primary failure があれば primary を優先して raise、restart 失敗は detail に含める
                    sys.stderr.write(
                        f"[backup_service_start_failed during recovery] {restart_exc.detail}\n"
                        f"[primary_reason] {primary_exc.reason_code}: {primary_exc.detail}\n"
                    )
                    raise primary_exc  # primary を呼出側へ伝播 (audit には両方記録)
                else:
                    raise  # backup 成功 → restart 失敗のみ propagate
```

### Batch C: _cmd_backup に destructive_lock 統合 + TOCTOU re-verify

#### 3.C.1 _cmd_backup lock 統合 + age fingerprint 再 verify (`scripts/taskhub_admin.py`、ADV R1 F-003 adopt)

§2.5 参照。approval gate 成功後に destructive_lock 取得 + lock 内で age_public_key_fingerprint 再 verify + run_backup を lock 内で実行。

新規 reason_code `backup_age_key_toctou_mismatch` を `BackupOptions` の error path に追加 (ReasonCode Literal 拡張)。

### Batch D: tests + docs

#### 3.D.1 新規 test fixtures (`tests/scripts/test_taskhub_backup_orchestrator.py`)

| # | test | scope |
|---|---|---|
| 1 | test_invoke_pg_dump_via_compose_exec_argv_uses_unix_socket | argv に `-h /var/run/postgresql` + `--no-password` + `compose exec -T postgres pg_dump` + `--no-acl` + `--no-owner` + `--single-transaction` |
| 2 | test_invoke_pg_dump_via_compose_exec_pgpassfile_not_in_env | PGPASSFILE env injection なし (Phase 5 では不要) |
| 3 | test_invoke_pg_dump_via_compose_exec_stdout_streaming | stdout_file 経由でファイル直接書込 (memory load 回避) |
| 4 | test_verify_pg_hba_trust_auth_via_compose_exec_select1 | preflight psql -c 'select 1' argv 検証 |
| 5 | test_verify_pg_hba_trust_auth_fail_raises_backup_runtime_error | mock exit 非 0 で BackupRuntimeError("backup_pg_dump_failed") raise |
| 6 | test_invoke_redis_save_via_compose_exec_blocking | redis-cli SAVE (blocking、--rdb ではない) |
| 7 | test_invoke_redis_dump_copy_via_compose_cp_atomic_rename | .tmp suffix → atomic rename pattern |
| 8 | test_invoke_redis_dump_copy_via_compose_cp_failure_cleans_tmp | mock exit 非 0 で .tmp file が残らない |
| 9 | test_backup_options_compose_binding_env_override | TASKHUB_BACKUP_COMPOSE_PROJECT / _FILE env 反映 |
| 10 | test_backup_options_compose_binding_defaults | env 未設定で default (taskmanagedai + repo_root/docker-compose.yml) |
| 11 | test_backup_options_compose_project_invalid_pattern_rejected | `; rm -rf /` 等の invalid project name で BackupUsageError |
| 12 | test_backup_options_compose_file_outside_allowed_root_rejected | repo_root / /etc / /var/lib 外 path で BackupUsageError |
| 13 | test_backup_options_pg_user_db_default_taskmanagedai | docker-compose.yml integration、default 整合 |
| 14 | test_backup_options_pgpassfile_optional | pgpassfile_path=None default OK (Phase 5 では使わない) |
| 15 | test_default_env_allowlist_pgpassfile_removed | DEFAULT_ENV_ALLOWLIST に PGPASSFILE 不在 |
| 16 | test_run_backup_compose_exec_pg_dump_called | run_backup 内で invoke_pg_dump_via_compose_exec が呼ばれる (mock) |
| 17 | test_run_backup_compose_exec_redis_flow_called | run_backup 内で SAVE + compose cp が呼ばれる (mock) |
| 18 | test_run_backup_stop_app_services_called_when_skip_false | skip_service_stop=False で stop_app_services / start_app_services 両方呼ばれる |
| 19 | test_run_backup_stop_app_services_skipped_when_skip_true | skip_service_stop=True で stop_app_services は呼ばれない + warning 追加 |
| 20 | test_run_backup_app_restart_failure_is_fatal (ADV R2 F-003 + R6 F-002 CRITICAL adopt) | `start_app_services_wait_healthy_via_compose_exec` が exit !=0 で BackupRuntimeError("backup_service_start_failed") を propagate → `_cmd_backup` 全体 non-zero exit (warning 流用は禁止、stop/restart 失敗はいずれも致命的、consistency boundary 維持) |

#### 3.D.2 _cmd_backup lock 統合 + TOCTOU test (`tests/scripts/test_taskhub_admin.py`)

| # | test | scope |
|---|---|---|
| 1 | test_cli_backup_acquires_destructive_lock | _cmd_backup で acquire_destructive_lock("backup") が呼ばれる (mock) |
| 2 | test_cli_backup_concurrent_busy_returns_exit_2 | 並列 backup で 2 番目が busy reject (mock) |
| 3 | test_cli_backup_restore_rollback_mutual_exclusion | backup running + 並列 restore-rollback で 2 番目が busy reject |
| 4 | test_cli_backup_age_key_toctou_mismatch_rejected | approval gate 後 + lock 取得前に age_public_key 書換 → lock 内 fingerprint mismatch + exit 2 |
| 5 | test_cli_backup_age_key_unreadable_after_lock_rejected | lock 取得後 age key file 削除/permission 0o000 で OSError catch + exit 2 |
| 6 | test_cli_backup_age_recipient_post_verify_swap_rejected (ADV R3 F-001 CRITICAL adopt) | lock 内 fingerprint verify OK 後に age_public_key file 書換 → `verified_age_recipient` immutable bind により invoke_age_encrypt が path 再読込せず検証済 recipient で encrypt (差し替え content が反映されない、または invalid recipient で fail-closed) |
| 7 | test_cli_backup_age_recipient_invalid_prefix_rejected | age public key が `age1` prefix 以外 → `backup_age_recipient_invalid` + exit 2 |

#### 3.D.3 backward compat + runtime binding test (`tests/scripts/test_taskhub_signed_approval.py` または admin、ADV R1 F-009 + R2 F-004 + R3 F-002 adopt)

| # | test | scope |
|---|---|---|
| 1 | test_pr77_legacy_record_signed_approval_signature_root_verify_only (ADV R5 F-001 統一) | PR #77 形式 5-field signed record を `verify_signed_approval` (signed_approval.py level) が parse + signature-root verify OK で accept (`backup_runtime_binding_fingerprint=None` は parser で許容)。**Phase 5 _cmd_backup level の reject とは scope を分離** (signed_approval.py は signature 互換、_cmd_backup は real I/O redeem reject) |
| 2 | test_phase5_cmd_backup_rejects_legacy_5_field_record_unconditionally (ADV R4 F-001 + R5 F-001 統一) | PR #77 形式 5-field signed record + canonical default env (project=taskmanagedai, file=<repo>/docker-compose.yml) でも `_cmd_backup` Phase 5 redeem は **常に reject** → exit 2 + `backup_claim_legacy_runtime_binding_unsupported`。default-binding 一致でも fragile compat allow しない統一ルール |
| 3 | test_phase5_cmd_backup_rejects_legacy_record_with_env_override (ADV R4 F-001 + R5 F-001 統一) | PR #77 形式 5-field signed record + `TASKHUB_BACKUP_COMPOSE_FILE=/etc/foo/docker-compose.yml` env でも _cmd_backup Phase 5 redeem は reject (理由は env override の有無に依存せず unsupported 統一) |
| 4 | test_phase5_new_approval_with_runtime_binding_fingerprint_allow | Phase 5 新規 approval (6 field、`backup_runtime_binding_fingerprint` 含む) + 同一 env → broker 再計算 fingerprint 一致 → verify allow |
| 5 | test_phase5_new_approval_runtime_binding_mismatch_after_issue_rejected (ADV R3 F-002 CRITICAL adopt) | Phase 5 新規 approval issue 後に `TASKHUB_BACKUP_COMPOSE_FILE` 変更 → redeem 時 broker 再計算 fingerprint 不一致 → `backup_claim_mismatch` で fail-closed (caller-controlled env での署名済み approval すり替え攻撃 fixture) |
| 6 | test_phase5_compose_file_swap_after_lock_uses_verified_copy_argv (ADV R5 F-002 + R7 F-001 CRITICAL adopt) | lock 取得 + in-lock verify 完了後 + run_backup 前に署名済 source realpath content を差し替え → docker compose argv は `-f <verified_compose_execution_input>` (lock 内 read bytes copy) + `--project-directory <signed source parent>` で exact match (差し替え content は execution input に反映されない、source 側 file 差し替えは docker に流れない) + 全 5 docker compose 呼出 (exec / cp / stop / up / ps) の argv に同一 verified copy path が含まれる exact assertion |
| 6.1 | test_phase5_compose_argv_prefix_raises_before_lock_bind (ADV R7 F-001 CRITICAL adopt) | _cmd_backup の lock 取得前に `_compose_argv_prefix(options)` を呼出 (verified copy 未 bind) → `BackupRuntimeError("backup_compose_binding_not_initialized")` で fail-closed (post-verify content swap window 物理閉鎖) |
| 7 | test_backup_output_path_exact_binding_allow (ADV R2 F-004 adopt) | 同一 absolute output_path + include_sops_env + skip_service_stop + overwrite + age_public_key_fingerprint + backup_runtime_binding_fingerprint → verify allow |
| 8 | test_backup_output_path_changed_deny (ADV R2 F-004 adopt) | output_path のみ変更 (timestamp 違い 等) → `backup_claim_mismatch` で fail-closed |
| 9 | test_phase5_artifacts_dir_swap_after_issue_rejected (ADV2 R1 F-001 + R13 F-003 CRITICAL/MEDIUM adopt) | approval issue 後に TASKHUB_BACKUP_ARTIFACTS_DIR 変更 → broker 再計算 fingerprint 不一致 → `backup_claim_mismatch` で fail-closed (R13 F-003 で `backup_payload_source_mismatch` 削除 → `backup_claim_mismatch` に統一) |
| 10 | test_phase5_sops_env_path_swap_after_issue_rejected (ADV2 R1 F-001 + R13 F-003 CRITICAL/MEDIUM adopt) | include_sops_env=true 時、approval issue 後に TASKHUB_BACKUP_SOPS_ENV_PATH 変更 or sops_env content 差し替え → broker 再計算 fingerprint 不一致 → `backup_claim_mismatch` で fail-closed (R13 F-003 で reason 統一) |
| 11 | test_phase5_compose_config_canonical_hash_swap_after_issue_rejected (ADV2 R1 F-003 HIGH adopt) | approval issue 後に compose env_file / build.context / bind mount を差し替え → `docker compose config` canonical hash 不一致 → `backup_claim_mismatch` で fail-closed |
| 12 | test_phase5_env_file_swap_after_issue_rejected (ADV2 R1 F-002 HIGH adopt) | approval issue 後に env_file content 差し替え → env_file_sha256 fingerprint 不一致 → `backup_claim_mismatch` で fail-closed |
| 13 | test_phase5_partial_stop_failure_still_attempts_restart (ADV2 R1 F-004 HIGH adopt) | api stop 成功 + worker stop 失敗で例外発生 → finally で start_app_services_wait_healthy 必ず呼ばれる (stopped_or_attempted flag) + partial stop 状態のままにしない |
| 14 | test_phase5_verified_compose_copy_same_uid_tamper_detected (ADV2 R1 F-005 HIGH adopt) | verified compose copy 書込後 + sha256 再検証前に same-UID で content 差し替え → `backup_compose_verified_copy_tampered` で fail-closed (private dir 0o700 + file 0o400 + O_NOFOLLOW で attacker process は書けないが、最悪 case の検知 fixture として実装) |
| 15 | test_phase5_age_public_key_non_ascii_rejected (ADV2 R1 F-006 MEDIUM adopt) | age public key file が non-ASCII bytes → UnicodeDecodeError catch → `backup_age_recipient_invalid` で fail-closed |
| 16 | test_phase5_age_public_key_multiline_rejected (ADV2 R1 F-006 MEDIUM adopt) | age public key が age1prefix + 改行 + ゴミ → regex match fail → `backup_age_recipient_invalid` |
| 17 | test_phase5_primary_failure_preserved_when_restart_also_fails (ADV2 R1 F-007 MEDIUM adopt) | backup_pg_dump_failed 発生 + restart 失敗 → primary_exc (backup_pg_dump_failed) を raise、restart failure detail も stderr/audit に記録 |
| 18 | test_phase5_redis_tmp_symlink_swap_detected (ADV2 R1 F-008 MEDIUM adopt) | docker compose cp 前後で tmp file を symlink に swap → lstat regular file check で fail-closed → `backup_redis_rdb_tmp_not_regular_file` |
| 19 | test_phase5_healthy_polling_starting_state_waits (ADV2 R1 F-010 MEDIUM adopt) | docker compose ps が `Health="starting"` 返す → wait 継続、timeout 内に "healthy" 返れば accept |
| 20 | test_phase5_healthy_polling_timeout_fatal (ADV2 R1 F-010 MEDIUM adopt) | timeout 内に healthy にならない → `backup_service_start_failed` で fatal |
| 21 | test_phase5_env_file_path_bound_in_compose_argv (ADV2 R2 F-001 HIGH adopt) | env_file_path 設定時、_compose_argv_prefix 出力に `--env-file <verified copy>` が必ず含まれる exact assertion |
| 22 | test_phase5_env_file_swap_after_issue_rejected (ADV2 R2 F-001 HIGH adopt) | approval issue 後に TASKHUB_BACKUP_ENV_FILE 変更 or content 差し替え → broker 再計算 fingerprint 不一致 → `backup_claim_mismatch` で fail-closed |
| 23 | test_phase5_compute_full_backup_runtime_binding_fingerprint_issue_vs_redeem_match (ADV2 R2 F-002 HIGH adopt) | compute_full_backup_runtime_binding_fingerprint(mode="issue") と (mode="redeem") が同一 BackupOptions + 同一 file content で完全に同 hash を返す (canonical algorithm 一致確認) |
| 24 | test_phase5_compose_config_canonical_hash_issue_vs_redeem_match (ADV2 R2 F-003 HIGH adopt) | compute_compose_config_canonical_sha256_for_issue と _for_redeem が同 file content + 同 env_file で同 hash を返す (verified copy bind 後と source path 入力で結果一致) |
| 25 | test_phase5_compose_argv_prefix_detects_same_uid_unlink_rename_swap (ADV2 R2 F-004 + R3 F-002 CRITICAL adopt) | (a) verified compose copy 作成 + metadata snapshot 記録 → 同 UID プロセスが unlink + 同名 file 再作成 → _compose_argv_prefix 呼出時に dev/ino/uid/mode/sha256 mismatch → `backup_compose_verified_copy_tampered` で fail-closed、(b) **verified_compose_execution_input set + verified_compose_metadata_snapshot=None** → `backup_compose_binding_not_initialized` で fail-closed (snapshot 未初期化は実行不可、defense-in-depth) |
| 25.1 | test_phase5_full_helper_only_in_cmd_backup_and_admin_issue (ADV2 R3 F-001 CRITICAL adopt) | `_cmd_backup` + approval issue 経路の grep / static analysis で `compute_backup_runtime_binding_fingerprint(` の直接呼出が 0 件 (= `compute_full_backup_runtime_binding_fingerprint` のみ呼出)、private helper への直接 callsite が存在しないことを確認 |
| 25.2 | test_phase5_env_file_realpath_sha256_in_canonical_schema (ADV2 R5 F-001 CRITICAL adopt) | `compute_backup_runtime_binding_fingerprint` の canonical schema dict が `env_file_realpath` + `env_file_sha256` を含む (env_file_path=None 時は両方 None、設定時は resolved path + sha256)。fingerprint computation で env_file binding が drift していないこと |
| 25.3 | test_phase5_sops_env_swap_after_lock_detected (ADV2 R5 F-002 CRITICAL adopt) | lock 取得 + verified sops_env copy 作成後に source sops_env content 差し替え → verified copy 経由で archive される → swap 内容は反映されない (verified copy が immutable execution input)、source 側 swap は audit 記録 |
| 25.4 | test_phase5_artifacts_staging_manifest_swap_detected (ADV2 R5 F-002 CRITICAL adopt) | lock 取得 + verified_artifacts_staging_dir 作成後に staging tree 内の file content 差し替え → archive 作成直前 manifest hash 再計算で mismatch → `backup_artifacts_staging_tampered` で fail-closed |
| 25.5 | test_phase5_artifacts_source_swap_after_lock_isolated (ADV2 R5 F-002 CRITICAL adopt) | lock 取得 + verified_artifacts_staging_dir 作成後に source artifacts_dir (caller-controlled) を差し替え → archive は verified staging から読込のため source swap 内容は **反映されない** (caller-controlled source swap が backup payload に届かない) |
| 25.6 | test_phase5_redeem_fingerprint_reads_verified_sops_env_copy (ADV2 R6 F-001 CRITICAL adopt) | redeem fingerprint 計算が source sops_env_path ではなく verified_sops_env_execution_input から sha256 を取得することを assert (caller-controlled source swap が redeem 経路で fingerprint に影響しないこと) |
| 25.7 | test_phase5_artifacts_dir_realpath_snapshot_immutable (ADV2 R6 F-002 CRITICAL adopt) | lock 取得 + artifacts_dir_realpath_snapshot 設定後に source artifacts_dir を rename/symlink swap → canonical schema の artifacts_dir_realpath は snapshot 値 (旧 source realpath) のままで fingerprint drift なし |
| 25.8 | test_phase5_artifacts_unsupported_file_type_rejected (ADV2 R6 F-003 CRITICAL adopt) | artifacts_dir に FIFO (mkfifo) / socket (mksock) / block device を含む → `backup_artifacts_source_unsupported_file_type` で fail-closed (regular/dir/symlink 以外を reject) |
| 25.9 | test_phase5_artifacts_per_file_size_limit_enforced (ADV2 R6 F-003 CRITICAL adopt) | artifacts_dir 内に 257 MiB file (per-file limit 超) → `backup_artifacts_file_too_large` で fail-closed |
| 25.10 | test_phase5_artifacts_tree_total_size_limit_enforced (ADV2 R6 F-003 CRITICAL adopt) | artifacts_dir tree total が 4 GiB+1 byte → `backup_artifacts_tree_too_large` で fail-closed |
| 25.11 | test_phase5_artifacts_manifest_mode_normalization_issue_vs_redeem_match (ADV2 R7 F-003 CRITICAL adopt) | source artifacts/foo.txt mode=0o644、staging copy mode=0o400 で fixture を作り、compute_full_backup_runtime_binding_fingerprint(mode="issue") と (mode="redeem") が **同 hash** を返す (source mode が canonical entry、staging mode は反映されない) |
| 25.12 | test_phase5_artifacts_copy_source_is_snapshot_anchor (ADV2 R7 F-002 CRITICAL adopt) | _verified_copy_tree_no_follow に渡される src 引数が **artifacts_dir_realpath_snapshot** であること (caller-controlled options.artifacts_dir ではない) を mock 経由で assert + root lstat anchor が walk 開始時に取得され、root rename swap が copy 中に検知される |
| 25.13 | test_phase5_full_helper_passes_artifacts_dir_manifest_sha256 (ADV2 R7 F-001 CRITICAL adopt) | compute_full_backup_runtime_binding_fingerprint(mode="issue") と (mode="redeem") が compute_backup_runtime_binding_fingerprint に **artifacts_dir_manifest_sha256 引数を必須で渡す** ことを mock 経由で assert (signature 不整合の regression 検知) |
| 25.14 | test_phase5_mode_source_required_keyword_only (ADV2 R8 F-001 CRITICAL adopt) | _compute_artifacts_dir_manifest_sha256 を mode_source 引数なしで呼び出す → TypeError (keyword-only required)。issue callsite が `mode_source="lstat"`、redeem / archive 直前 re-verify callsite が `mode_source="source_lstat"` で呼ばれていることを mock 経由で assert |
| 25.15 | test_phase5_sidecar_path_outside_staging (ADV2 R8 F-002 CRITICAL adopt) | sidecar (_artifacts_source_mode.json) が verified_temp_dir 直下 (staging tree の **外**) に作成され、archive 作成時に staging tree から sidecar が読まれない (archive payload に sidecar 混入なし)。`tar tf` 相当で archive 内容を列挙して assert |
| 25.16 | test_phase5_source_reserved_name_rejected (ADV2 R8 F-002 CRITICAL adopt) | source artifacts_dir に `_artifacts_source_mode.json` ファイルが存在する状態で _verified_copy_tree_no_follow を呼ぶ → `backup_artifacts_source_reserved_name` で fail-closed (source-side reserved-name check) |
| 25.17 | test_phase5_env_file_resolved_from_environment_default (ADV2 R9 F-001 CRITICAL adopt) | TASKHUB_BACKUP_ENV_FILE 未設定で BackupOptions.from_environment(repo_root=X) → env_file_path == X/.env.local (resolved) + .env.local 不存在時は `backup_compose_env_file_unreadable` で fail-closed |
| 25.18 | test_phase5_env_file_path_outside_allowlist_rejected (ADV2 R9 F-001 CRITICAL adopt) | TASKHUB_BACKUP_ENV_FILE=/srv/evil-host/.env で from_environment → repo_root / /etc / /var/lib 配下のいずれでもないため `backup_output_path_invalid` で fail-closed |
| 25.19 | test_phase5_env_file_cross_field_invariant_violation_fingerprint_helper (ADV2 R9 F-002 CRITICAL adopt) | fingerprint helper の 3 ケース exact assertion: (a) issue で options.env_file_path=None + source_env_file_path=Path("/x") → `backup_compose_binding_not_initialized` fail-closed (message: "source_env_file_path passed but options.env_file_path is None")、(b) issue で options.env_file_path=Path("/x") + source_env_file_path=None → 同 fail-closed (message: "options.env_file_path is set but source_env_file_path missing")、(c) redeem で options.env_file_path=Path("/x") + verified_env_file_execution_input=None → 同 fail-closed (message: "verified_env_file_execution_input / metadata_snapshot not bound") |
| 25.19.A | test_phase5_env_file_cross_field_invariant_violation_compose_argv (ADV2 R10 F-001 CRITICAL adopt) | _compose_argv_prefix の 3 ケース exact assertion: (a) options.env_file_path=Path("/x") + verified_env_file_execution_input=None → `backup_compose_binding_not_initialized` fail-closed (message: "options.env_file_path set but verified_env_file_execution_input not bound")、(b) options.env_file_path=None + verified_env_file_execution_input=Path("/x") → 同 fail-closed (message: "verified_env_file_execution_input bound but options.env_file_path is None")、(c) verified_env_file_execution_input=Path("/x") + verified_env_file_metadata_snapshot=None → 同 fail-closed (message: "verified_env_file_metadata_snapshot must be bound alongside") |
| 25.20 | test_phase5_artifacts_staging_after_stop_consistency_boundary (ADV2 R11 F-001 + R12 F-001 CRITICAL adopt) | run_backup 呼出 trace で `stop_app_services_via_compose_exec` → `_verified_copy_tree_no_follow` → `_compute_artifacts_dir_manifest_sha256` → `dataclasses.replace(options, verified_artifacts_staging_dir=..., verified_artifacts_manifest_sha256=...)` → `compute_full_backup_runtime_binding_fingerprint(options, mode="redeem")` → claim verify → pg_dump の **順序** を mock_calls の index で assert (artifacts staging が stop **後** であること、stop 前に呼ばれない)。さらに **post-stop dataclasses.replace 後の同一 `options`** が archive 経路 (manifest re-verify / sops_env verify / age encrypt / atomic rename) に渡されることを assert (旧 `backup_options.*` 残存禁止) |
| 25.21 | test_phase5_artifacts_symlink_rejected (ADV2 R11 F-002 CRITICAL adopt) | artifacts_dir 内に symlink (`os.symlink` で作成、外部 path を指す) → _verified_copy_tree_no_follow で `backup_artifacts_source_unsupported_file_type` で fail-closed (manifest からも除外) |
| 26 | test_phase5_compose_argv_prefix_detects_env_file_swap (ADV2 R2 F-004 HIGH adopt) | verified env file copy も同様の swap detection (dev/ino/uid/mode/sha256) → `backup_env_file_verified_copy_tampered` で fail-closed |
| 27 | test_phase5_healthy_polling_service_field_primary_key (ADV2 R2 F-005 HIGH adopt) | docker compose ps JSON が `Name: taskmanagedai-api-1, Service: api, Health: healthy` の format で出力 → Service field exact match で healthy 判定、Name の suffix pattern は fallback のみ |

#### 3.D.4 docs update

- `docs/sprints/SP-022_framework_intake_hardening.md`: Phase 5 completion section 追加 + T09 unblock 状況 (SP-012 残のみ)
- `docs/deploy/operator-runbook.md`: §8 destructive lock backup 追記 + §9 backup direction compose exec 整合

---

## §4 invariant chain (must_ship 完全列)

### 4.1 ADR-00021 invariants 遵守

- §11.2 split-brain default deny + **backup 時 service stop boundary**: Phase 5 で `stop_app_services` → backup → `start_app_services_wait_healthy` の consistency window 確立 (ADV R1 F-001 CRITICAL adopt)
- §14.1 PGA-F-002 detached signature: **ADV R3 F-002 + R5 F-001 + R14 F-003 CRITICAL/MEDIUM adopt で `BackupApprovalClaim` に `backup_runtime_binding_fingerprint` field を 1 件追加** (6 field 化)。canonical OperationContext (§2.3.A の最新 schema と完全同期、ADV2 R14 F-003 adopt) = `target_compose_project_name + target_compose_file_realpath + target_compose_file_sha256 + target_compose_project_directory + artifacts_dir_realpath + artifacts_dir_manifest_sha256 + sops_env_path_realpath + sops_env_sha256 + env_file_realpath + env_file_sha256 + compose_config_canonical_sha256 + pg_user + pg_db + postgres_service_name + redis_service_name` を JCS canonical JSON → SHA-256 で fingerprint 化、approval issue 時に broker / CLI が server 側で再計算して signature root に含める。PR #77 既存 5-field legacy record は `signed_approval.py` signature-root verify レベルでは互換維持、`_cmd_backup` Phase 5 real I/O redeem では **常に reject** (`backup_claim_legacy_runtime_binding_unsupported`、再 issue 必須)。R5 F-002 で lock 内に compose file content sha256 を再計算 + verified copy bind の TOCTOU 排除も統合。env_file / sops_env / artifacts manifest / compose config canonical hash を含む payload-source binding が ADR-00021 §11.2 consistency boundary を完全に閉じる。
- §14.1 PGA-F-013 drill timer alert-only: `taskhub backup` も signed approval 必須 (本 PR は backup の compose exec 切替のみ、approval gate path 不変)

### 4.2 SecretBroker boundary 遵守

- container 内 PostgreSQL は peer/trust auth (no password)、host PGPASSFILE 撤回 + DEFAULT_ENV_ALLOWLIST からも削除
- age public key path のみ access (private key は touch しない、既存 PR #77 invariant 維持) + **lock 取得後の TOCTOU re-verify** (ADV R1 F-003 adopt)
- audit / log / artifact に raw password を出さない

### 4.3 server-owned boundary 遵守

- Compose binding (`target_compose_project_name`, `target_compose_file_path`) は **env 経由 runtime resolve + allowlist validation** (ADV R1 F-004 adopt: project name regex + file path repo_root/etc/var/lib 配下のみ)
- **ADV R3 F-002 + R5 F-001 CRITICAL adopt**: 新規 approval は `BackupApprovalClaim.backup_runtime_binding_fingerprint` で Compose binding + pg_user/db + service identity を signature root に含める (caller-controlled env で別 project の backup を正規成果物として作るすり替え攻撃を物理閉鎖)。PR #77 既存 5-field legacy record は `signed_approval.py` signature root verify レベルでは互換維持、`_cmd_backup` Phase 5 real I/O では常に reject。「default binding 完全一致時 allow」のような fragile path-content 互換は plan 全体で削除済。
- approval issue CLI に新 backup-* 引数追加なし。**ただし backward compat は「同一の絶対 output_path / include_sops_env / skip_service_stop / overwrite / age_public_key_fingerprint」の場合のみ verify allow**。output_path mismatch (timestamp 違い / 相対 path 入力 等) は既存 backup_claim_mismatch で deny される (PR #77 invariant 維持、ADV R1 F-009 + R2 F-004 adopt)。
- ADV R2 F-004 adopt: runbook §2 に "backup 実行前に最終 output path を決め、その exact absolute path で `taskhub approval issue --backup-output-path ...` を発行する" SOP を明示。test §3.D.3 に同一 path allow + changed output deny の両方を含む。

### 4.4 cross-source enum integrity 遵守

ReasonCode 拡張は **19 件** (ADV2 R13 F-003 で `backup_payload_source_mismatch` 削除済、R10 F-002 + R13 F-003 集計同期):
- `backup_age_key_toctou_mismatch` (ADV R1 F-003 adopt、TOCTOU re-verify reason)
- `backup_age_recipient_invalid` (ADV R3 F-001 CRITICAL adopt、age public key の content が `age1` prefix 不一致 + R1 F-006 で非 ASCII / multi-line / regex 違反含む)
- `backup_service_stop_failed` (ADV R2 F-003 adopt、api/worker stop 失敗)
- `backup_service_start_failed` (ADV R2 F-003 adopt、api/worker restart 失敗、致命的)
- `backup_claim_legacy_runtime_binding_unsupported` (ADV R4 F-001 + R5 F-001 CRITICAL adopt、PR #77 legacy 5-field record を Phase 5 real I/O で常に reject)
- `backup_compose_file_unreadable` (ADV R5 F-002 CRITICAL adopt、lock 内 compose file 再読込失敗)
- `backup_compose_binding_not_initialized` (ADV R7 F-001 CRITICAL adopt、_compose_argv_prefix が lock 内 bind 前に呼ばれた場合の fail-closed)
- `backup_compose_verified_copy_tampered` (ADV2 R1 F-005 HIGH adopt、verified compose copy 書込後 sha256 mismatch = same-UID tamper)
- `backup_compose_config_failed` (ADV2 R1 F-003 HIGH adopt、docker compose config canonical hash 計算失敗)
- `backup_redis_rdb_tmp_not_regular_file` (ADV2 R1 F-008 MEDIUM adopt、Redis tmp file が docker compose cp 前後で regular file ではない = symlink swap 検知)
- ~~`backup_payload_source_mismatch`~~ → ADV2 R13 F-003 MEDIUM adopt で **削除**、`backup_claim_mismatch` に統一 (artifacts_dir / sops_env_path / sops_env_sha256 等の fingerprint mismatch も全て `backup_claim_mismatch` で fail-closed、独立 reason 不要)
- `backup_compose_env_file_unreadable` (ADV2 R2 F-001 HIGH adopt、env_file 不存在 / 読込失敗)
- `backup_payload_source_unreadable` (ADV2 R2 F-002 HIGH adopt、sops_env_sha256 計算用 file 読込失敗)
- `backup_env_file_verified_copy_tampered` (ADV2 R2 F-004 HIGH adopt、env_file verified copy の metadata snapshot 再検証で mismatch)
- `backup_payload_source_tampered` (ADV2 R5 F-002 CRITICAL adopt、sops_env verified copy の sha256/metadata mismatch)
- `backup_artifacts_staging_tampered` (ADV2 R5 F-002 CRITICAL adopt、artifacts_dir verified staging tree の manifest sha256 mismatch)
- `backup_artifacts_source_unsupported_file_type` (ADV2 R6 F-003 CRITICAL adopt、FIFO/socket/block/char device 等の non-regular/dir/symlink を artifacts_dir で検知)
- `backup_artifacts_file_too_large` (ADV2 R6 F-003 CRITICAL adopt、per-file 256 MiB 超)
- `backup_artifacts_tree_too_large` (ADV2 R6 F-003 CRITICAL adopt、tree total 4 GiB 超)
- `backup_artifacts_source_reserved_name` (ADV2 R8 F-002 CRITICAL adopt、source tree に `_artifacts_source_mode.json` 等の reserved name file が存在)

既存 `backup_pg_dump_failed` / `backup_redis_rdb_failed` / `backup_claim_mismatch` ReasonCode を **そのまま使用** (implementation detail 変更のみ、外部 contract 不変)。

**新規 approval は `backup_runtime_binding_fingerprint` 必須**: 不一致時 (issue 後 env 変更 + lock 内 compose file content swap 両方) は既存 `backup_claim_mismatch` で fail-closed (新 reason_code 追加せず、4 整合 fingerprint pattern を踏襲)。

### 4.5 testing.md §3 弱 assertion 禁止 遵守

全 **43 test functions + 24 subcase** (ADV R9 F-003 + R13 F-004 LOW adopt: 集計更新、test function = 43 個の def test_*、subcase = 25.x のような同一 test function 内の parametrized / scenario branches。Batch B orchestrator 24 + Batch C admin 8 + Batch D signed_approval 8 + approval_cli 1 + subprocess_runner 2 = 43 functions、Phase 1+2 review-loop の追加 25.1-25.21 = 24 subcase) で:
- argv は exact match (specific tokens 検証、not just length)
- file mode / permission は `stat.S_IMODE(...) == 0o<mode>` の exact
- subprocess result は returncode + stdout content 両方
- 弱 assertion (`toBeDefined` / `toBeTruthy` 同等) 全件回避

---

## §5 ファイル変更一覧

### 修正 (5 scripts + 5 tests + 2 docs = **12 file**、ADV R9 F-003 LOW adopt 集計同期)

| path | 影響範囲 | 行数 |
|---|---|---|
| `scripts/taskhub_backup_orchestrator.py` (ADV R9 F-002 MEDIUM + ADV2 R10 F-002 CRITICAL adopt 集計同期) | BackupOptions Compose binding + verified_source_project_dir + verified_compose_execution_input (R7) + verified_env_file_* (R4/R9) + verified_sops_env_* (R5) + verified_artifacts_staging_dir + manifest_sha256 + realpath_snapshot + source_mode_sidecar_path (R5/R6/R7/R8) + metadata snapshots (R3/R4/R6) + _compose_argv_prefix (verified copy bind 必須 + env_file cross-field invariant、R6/R7/R8/R9/R10) + invoke_pg_dump_via_compose_exec + invoke_redis_save_via_compose_exec + invoke_redis_dump_copy_via_compose_cp (O_EXCL, R8 F-008) + verify_pg_hba_trust_auth_via_compose_exec + stop_app_services_via_compose_exec + start_app_services_wait_healthy_via_compose_exec (Service field primary key, R2 F-005) + 旧 invoke_pg_dump + invoke_redis_rdb 削除 + default pg_user/pg_db 変更 + pgpassfile_path None default + `compute_backup_runtime_binding_fingerprint` (private helper、R3 F-002 / R6 F-001 / R5 F-001/F-002 / R6 F-002/F-003 / R7 F-001/F-002/F-003 / R8 F-001/F-002 / R9 F-002 で env_file/artifacts_manifest/sops_env/canonical_config field 追加) + `compute_full_backup_runtime_binding_fingerprint` (single full-helper、R3 F-001 / R4 F-001 / R7 F-001 / R9 F-002 cross-field invariant) + `compute_compose_config_canonical_sha256_for_issue/for_redeem` (R3 F-003) + `_verified_copy_tree_no_follow` + `_compute_artifacts_dir_manifest_sha256` (R5 F-002 / R6 F-003 / R7 F-002/F-003 / R8 F-001/F-002) + **`ReasonCode` Literal に 20 件追加** (backup_age_key_toctou_mismatch / backup_age_recipient_invalid / backup_service_stop_failed / backup_service_start_failed / backup_claim_legacy_runtime_binding_unsupported / backup_compose_file_unreadable / backup_compose_binding_not_initialized / backup_compose_verified_copy_tampered / backup_compose_config_failed / backup_redis_rdb_tmp_not_regular_file / backup_payload_source_mismatch / backup_compose_env_file_unreadable / backup_payload_source_unreadable / backup_env_file_verified_copy_tampered / backup_payload_source_tampered / backup_artifacts_staging_tampered / backup_artifacts_source_unsupported_file_type / backup_artifacts_file_too_large / backup_artifacts_tree_too_large / backup_artifacts_source_reserved_name; **all backup runtime reasons live in backup_orchestrator namespace、signed_approval.py には新規 reason 追加なし**) + invoke_age_encrypt(verified_recipient=...) 改修 (R3 F-001) | +750 / -100 |
| `scripts/taskhub_subprocess_runner.py` | DEFAULT_ENV_ALLOWLIST から PGPASSFILE 削除 | +0 / -1 |
| `tests/scripts/test_taskhub_subprocess_runner.py` | 既存 `test_filter_env_allows_pgpassfile` → 2 test に置換 (default not allow + extra_env_allowlist override allow)、ADV R2 F-002 adopt | +30 / -10 |
| `scripts/taskhub_admin.py` (ADV R9 F-001 record-claim データフロー adopt) | _cmd_backup で **`record_backup_claim` (verify_signed_approval から return) と `expected_backup_claim` (CLI options から構築) を別変数保持** + signature root verify → legacy null check → record-vs-expected 4 整合 verify → lock 内 compose sha256 再計算 + record 側 fingerprint exact match の 4 段判定。destructive_lock 統合 + age fingerprint TOCTOU re-verify + `verified_age_recipient` immutable bind (R3 F-001) + lock 内 compose file sha256 再計算 + verified copy bind (R5 F-002) + verified_source_project_dir / verified_compose_execution_input bind (R6/R7) + legacy 5-field 常時 reject (R4/R5) + ReasonCode は backup_orchestrator namespace から import (R9 F-002 namespace 統一) | +200 |
| `scripts/taskhub_signed_approval.py` (ADV R3 F-002 + R4 F-002 + R9 F-001/F-002 CRITICAL adopt) | `BackupApprovalClaim` dataclass に `backup_runtime_binding_fingerprint: str \| None` field 追加 (6-field 化、legacy 5-field との parser 分岐は record 内 field 存在判定で実装) + canonical signing payload (`_rfc8785` を経由する claim 用 dict 構築箇所、PR #77 既存) に新 fingerprint field を **`None` 以外のとき含める** (legacy 5-field record は新 field なしで既存 signature root を維持 = backward compat) + `verify_signed_approval` が record 側 deserialized `BackupApprovalClaim` を呼出側に return する戻り値拡張 (`record_backup_claim`、R9 F-001 record-claim データフロー固定) + **本 file は signed approval gate 固有 reason のみ保持** (`taskhub_signed_approval_*` 系)、**backup runtime reason は backup_orchestrator namespace に集約 = signed_approval.py には新規 reason 追加なし** (R9 F-002 namespace 整理) | +60 |
| `scripts/taskhub_approval_cli.py` (ADV R4 F-002 CRITICAL adopt) | `taskhub approval issue` subcommand の backup variant で、CLI 引数 (`--backup-output-path` 等の既存 5 引数) から解決した `BackupOptions` + 実 `compose_file_sha256` を **server-owned に再計算** して `BackupApprovalClaim(backup_runtime_binding_fingerprint=computed)` を構築 + CLI 引数で caller-supplied fingerprint を受け取る経路を physically 削除 (signature レベル削除、server-owned-boundary.md §1-2 遵守) + 新 6-field record を `_rfc8785` canonical signing で write + ts/ttl/scope 既存 invariant 維持 | +50 |
| `tests/scripts/test_taskhub_backup_orchestrator.py` | 20 fixture 追加 (compose exec / mock / env override / service stop / pg_hba preflight) + `verified_age_recipient` immutable bind test 2 件 (R3 F-001) + `compute_backup_runtime_binding_fingerprint` canonical schema test 2 件 (R3 F-002) | +650 |
| `tests/scripts/test_taskhub_admin.py` | 5 fixture 追加 (lock 統合 / concurrent / mutual exclusion / TOCTOU) + age recipient post-verify swap test (R3 F-001) + age recipient invalid prefix test + legacy 5-field record reject test (R4 F-001) | +200 |
| `tests/scripts/test_taskhub_signed_approval.py` | 8 fixture 追加: legacy 5-field signature-root verify only allow / phase5 _cmd_backup legacy 5-field 常時 reject (default-binding でも) / phase5 _cmd_backup legacy + env override reject / new 6-field allow / new 6-field issue 後 env 変更 mismatch / compose file content swap after lock rejected (R5 F-002) / output_path exact binding allow / output_path changed deny (ADV R3 F-002 + R4 F-001/F-002 + R5 F-001/F-002 + R2 F-004) | +240 |
| `tests/scripts/test_taskhub_approval_cli.py` (ADV R4 F-002 CRITICAL adopt、新規 or 既存) | `taskhub approval issue --backup-output-path ...` で 6-field record 生成 + server-owned fingerprint 再計算 + caller-supplied fingerprint 引数なし (signature レベル削除確認) | +80 |
| `docs/sprints/SP-022_framework_intake_hardening.md` | Phase 5 completion + T09 unblock 状況更新 | +60 |
| `docs/deploy/operator-runbook.md` | §8 destructive lock backup 追記 + §9 backup compose exec + §11 legacy 5-field record re-issue SOP (R4 F-001) + §12 backup approval issue exact output_path SOP (R2 F-004) | +60 |

合計: +2,010 / -101 (12 file、R5 F-001/F-002 polish 反映)

---

## §6 verification 順序

### 6.1 local pre-commit verification

```bash
uv run ruff check scripts/taskhub_backup_orchestrator.py scripts/taskhub_admin.py scripts/taskhub_subprocess_runner.py
uv run mypy scripts/taskhub_backup_orchestrator.py scripts/taskhub_admin.py
uv run pytest tests/scripts/test_taskhub_backup_orchestrator.py tests/scripts/test_taskhub_admin.py tests/scripts/test_taskhub_signed_approval.py -x
uv run pytest tests/scripts/ -x  # full regression
```

### 6.2 受け入れ条件

- [ ] `uv run pytest tests/scripts/` 332+ test PASS (本 PR 後 ~363 想定、43 test functions + 24 subcase 追加 = 67 test runs 追加 + 既存 test 修正 ~7、ADV R9 F-003 + R13 F-004 集計同期)
- [ ] `uv run mypy scripts/` clean
- [ ] `uv run ruff check scripts/ tests/scripts/` clean
- [ ] PR #75/#77/#78/#79 既存 test 全件 PASS 維持 (regression なし、backup_orchestrator pg/redis 内部実装変更のみ、external contract 不変)
- [ ] PR #77 既存 BackupApprovalClaim (5 field、archive_sha256 なし) は `signed_approval.py` signature root verify レベルでは互換維持 (`test_pr77_legacy_record_signed_approval_signature_root_verify_only` allow)、`_cmd_backup` Phase 5 real I/O では常に reject (`test_phase5_cmd_backup_rejects_legacy_5_field_record_unconditionally` で `backup_claim_legacy_runtime_binding_unsupported` exit 2、ADV R4 F-001 + R5 F-001 統一)
- [ ] Phase 5 新規 approval (6 field、`backup_runtime_binding_fingerprint`) は `_cmd_backup` で allow + issue 後 env override / compose file content swap は `backup_claim_mismatch` で fail-closed (ADV R3 F-002 + R5 F-002 統一)
- [ ] **ADV2 R10 F-002 CRITICAL adopt: enum integrity 検証** — `test_phase5_reason_code_enum_integrity` で次の 3 source 完全一致を assert: (a) `ReasonCode` Literal の全 backup_* entries (20 件)、(b) 全 `BackupRuntimeError(reason_code, ...)` callsite で使われる reason_code 文字列 (grep)、(c) test fixture の expected reason_code 文字列。3 source 完全一致 (set 比較で 0 missing / 0 extra)、drift 検知時 fail-closed
- [ ] `_cmd_backup` で destructive_lock acquired (`subcommand="backup"`、cross-subcommand mutual exclusion)
- [ ] lock 取得後 age fingerprint TOCTOU re-verify で mismatch 検出 + structured error (ADV R1 F-003 adopt)
- [ ] backup 時 stop_app_services → run_backup → start_app_services consistency boundary 確立 (ADV R1 F-001 CRITICAL adopt)
- [ ] pg_hba preflight psql -c 'select 1' で trust auth fail-closed (ADV R1 F-007 adopt)

### 6.3 codex-plan-review R1-R{N} polish

`codex-all-loops mode=plan max-rounds=12 clean-criteria=critical_zero` で本 plan を polish、CRITICAL=0 + HIGH ≤ 2 まで loop、全 findings 100% adopt。

---

## §7 Codex multi-round R1-R{N} adoption log

### R1 (Phase A 構造): 15 findings 全件 adopt 反映済

| # | id | severity | adoption |
|---|---|---|---|
| 1 | F-001 | CRITICAL | backup 時 service stop/restart consistency boundary 追加 (§2.6 + §3.B.5/B.6) |
| 2 | F-002 | HIGH | pgpassfile_path optional 化 + 旧 invoke_pg_dump 削除、§2.4 + §3.A.1/A.3 反映 |
| 3 | F-003 | HIGH | lock 取得後 age fingerprint TOCTOU re-verify (§2.5 + §3.C.1)、backup_age_key_toctou_mismatch reason 追加 |
| 4 | F-004 | HIGH | Compose binding env override allowlist (project regex + file path repo_root/etc/var/lib 配下のみ)、§2.3 + §3.A.1 |
| 5 | F-005 | HIGH | Redis dump 取得を `docker compose cp redis:/data/dump.rdb` に変更 (Docker Desktop for Mac 互換、acquire_redis_data_host_path 廃止)、§2.2 + §3.B.4 |
| 6 | F-006 | HIGH | BackupOptions default pg_user/pg_db を docker-compose.yml 整合 (taskhub → taskmanagedai)、§2.7 + §3.A.1 |
| 7 | F-007 | MEDIUM | pg_hba trust auth preflight (psql -c 'select 1') via compose exec、§2.4 + §3.B.1 |
| 8 | F-008 | MEDIUM | DEFAULT_ENV_ALLOWLIST から PGPASSFILE 削除、§2.4 + §3.A.4 |
| 9 | F-009 | MEDIUM | PR #77 BackupApprovalClaim 5 field record backward compat test 明示、§3.D.3 |
| 10 | F-010 | MEDIUM | target_compose_file_path expanduser().resolve(strict=False) 正規化、§2.3 + §3.A.1 |
| 11 | F-011 | MEDIUM | compose exec helper も _run_subprocess_with_tool_check wrapper 経由、§3.B.2 |
| 12 | F-012 | MEDIUM | Redis dump copy .tmp + atomic rename + fsync、§3.B.4 |
| 13 | F-013 | LOW | TASKHUB_BACKUP_COMPOSE_* と TASKHUB_RESTORE_COMPOSE_* env 分離理由を runbook に明記 (誤操作防止、本 PR では fallback 採用なし) |
| 14 | F-014 | LOW | pg_dump argv の --no-acl + --no-owner で Phase 3 restore snapshot pg_dump と identical、§3.B.2 |
| 15 | F-015 | LOW | §3 見出しを scope (4 batches) に修正 |

---

## §8 ADR proposed → accepted 化 trigger

本 PR で touch する ADR:
- ADR-00021 (host_portable_deployment): 既に `accepted` 状態。本 PR は §11.2 backup consistency boundary + §14.1 PGA-F-002 detached signature の **実装範囲**、ADR 本文修正なし。
- 新規 ADR proposed の必要性: なし。Phase 5 は Phase 3/4 既存 pattern の対称適用 + service stop barrier、設計新規追加なし。

---

## §9 PR title + commit message format

```
feat(sp022-t02p5): SP022-T02 Phase 5 — backup pg_dump / redis SAVE compose exec 切替 + service stop/restart consistency + destructive_lock + TOCTOU re-verify (T09 unblock hard gate)

- Batch A: BackupOptions に Compose binding field + default pg_user/pg_db taskmanagedai + pgpassfile_path optional + 旧 invoke_pg_dump/invoke_redis_rdb 削除 + DEFAULT_ENV_ALLOWLIST から PGPASSFILE 削除
- Batch B: invoke_pg_dump_via_compose_exec + verify_pg_hba_trust_auth_via_compose_exec + invoke_redis_save_via_compose_exec + invoke_redis_dump_copy_via_compose_cp (docker compose cp で host path 撤回、Docker Desktop for Mac 互換) + stop_app_services / start_app_services_wait_healthy (consistency boundary、ADV R1 F-001 CRITICAL adopt)
- Batch C: _cmd_backup に destructive_lock 統合 (3 destructive subcommand mutual exclusion) + lock 取得後 age fingerprint TOCTOU re-verify (Phase 4 R5 F-001 pattern)
- Batch D: tests (43 test functions + 24 subcase = 67 test runs、ADV R9 F-003 + R13 F-004 集計同期) + docs

PR #77 backup direction の host TCP port-collision attack surface 排除完了、Phase 3 restore (PR #78) の compose exec pattern を backup direction に対称適用、ADR-00021 §11.2 backup-時 consistency boundary 確立.
SP022-T02 全 Phase (1/2/3/4/5) 完遂、SP022-T09 unblock hard gate (Phase 5) 達成 (残: SP-012 split-brain second line + keyring rotation).

codex-all-loops + PR R1-R{N} polish: {N1+N2} findings 全件 adopt + Readiness Gate READY

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
```

---

## §10 PR 後の SP-022 task progress (post-本 PR)

| Task | status |
|---|---|
| SP022-T01 framework intake CI 機械化 | ✅ 完了 (PR #70) |
| SP022-T02 `taskhub migrate` 自動化 | 🟥 heavy: Phase 1 ✅ (PR #75) + Phase 2 ✅ (PR #77) + Phase 3 ✅ (PR #78) + Phase 4 ✅ (PR #79) + **Phase 5 ✅ (本 PR)** → **全 Phase 完遂** |
| SP022-T03 半年 drill SOP | ✅ 完了 (PR #71) |
| SP022-T04 Phase E trace audit | ✅ 完了 (PR #72) |
| SP022-T05 AC-HARD multi-agent re-verify | ⛔ deferred (blocked_by: SP-013) |
| SP022-T06 KPI baseline 3 host | 🟨 light (Mac 単独可) |
| SP022-T07 production checklist skeleton | ✅ 完了 (PR #73) |
| SP022-T08 SP-012 carry-over 9 件 | 🟥 heavy: batch 1-4 ✅ (PR #76/#77/#78/#79) / batch 5-6 carry-over |
| SP022-T09 実機 host migration drill | 🟡 **partial unblock** (blocked_by: SP-012 split-brain second line + SP-012 keyring rotation のみ。SP022-T02 全 Phase hard gate 解消) |

### T09 unblock 残条件 (post-本 PR)

本 PR で SP022-T02 全 Phase 完遂。**T09 unblock 残条件 = SP-012 must_ship 2 件のみ**:
1. SP-012 active.signed marker chain + thaw 2-party-control + 同 migration_epoch reject negative test (ADR-00021 §11.2 + §14.1 PGA-F-003)
2. SP-012 keyring rotation (`approval-verify-keys.d/<fingerprint>.pub` keyring + overlap period dual-trust、PR #79 ADV R2 F-004 adopt)

---

## §11 risk summary

| risk | mitigation |
|---|---|
| compose exec 経由で container 内 PostgreSQL に接続不可 (container down) | pg_hba_preflight psql -c 'select 1' で fail-closed、service stop/restart で healthy 確認 |
| Phase 5 切替で PR #77 既存 backup record が `_cmd_backup` で reject (ADV R4 F-001 + R5 F-001 統一) | operator runbook §11 SOP で再 issue 必須 (`taskhub approval issue --backup-output-path ...` で 6-field record 生成)。`signed_approval.py` parse + signature root verify レベルでは互換維持のため audit trail / migration tool は影響なし。runbook §11 で既存 record 一覧確認 + 移行手順を明示。 |
| approval issue 後 + lock 取得後 + run_backup 前に compose file content 差し替えで signature 済 binding と乖離 (ADV R5 F-002 CRITICAL) | lock 内 compose bytes 再読 + sha256 再計算 + 6-field fingerprint 再 verify + verified copy bind で TOCTOU 物理閉鎖 (test_phase5_compose_file_swap_after_lock_rejected_or_verified_copy_used で実証) |
| container 内 unix socket `/var/run/postgresql` が存在しない (postgres:16-alpine 以外 image) | docker-compose.yml の image pin (postgres:16-alpine) + pg_hba_preflight で fail-closed |
| destructive_lock 統合で既存 _cmd_backup test が race condition で fail | mock acquire_destructive_lock context manager + 既存 test を sequential 実行で regression 防止 |
| backup 時 service stop で operator が想定外 downtime | skip_service_stop=True で escape (test/dev、warning audit emit)、production drill では default false で consistency 優先 |
| docker compose cp redis:/data/dump.rdb の権限不足 | `docker compose cp` は Docker Engine 標準、root権限不要 (container は user redis で動作、host docker.sock access 経由) |
| age_public_key_path race (approval gate 後 + lock 取得前に file 差し替え) | lock 取得後 fingerprint 再 verify で TOCTOU 排除 (ADV R1 F-003 adopt) |

---

## §12 既存 PR #79 carry-over consideration

PR #79 で issue 5 (age secret broker integration) + 6 (backup pg_dump compose exec) を carry-over として明記。本 PR で **#6 backup pg_dump compose exec 全件 closure**、#5 age secret broker は別 PR (Phase 6 or SP-012) carry-over 維持。

PR #79 で記載した R2 F-004 keyring rotation も SP-012 carry-over として維持 (本 PR scope 外、T09 unblock 残条件として §10 に明記)。
