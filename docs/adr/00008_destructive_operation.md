---
id: "ADR-00008"
title: "Destructive operation boundary in runner sandbox"
status: "accepted"
date: "2026-05-13"
accepted_at: "2026-05-13"
deciders:
  - "TaskManagedAI core"
adr_gate_criteria:
  - "#8 破壊的操作 / migration / tenant data 移行"
  - "#5 MCP / tool 権限"
related_sprints:
  - "SP-007_runner_sandbox"
related_adrs:
  - "ADR-00003 (CLI artifact orchestration API contract)"
  - "ADR-00004 (AI agent permission)"
  - "ADR-00012 (Hook Trust Boundary)"
---

# ADR-00008: Destructive Operation Boundary in Runner Sandbox

## 背景

Sprint 7 で Docker isolated runner と `runner_mutation_gateway` を実装する。runner は AgentRun ごとに分離された container 内で patch を apply / command を execute するが、AI 出力 patch が container を抜けて host や repo の **destructive** な操作 (file delete / migration apply / `.github/workflows/**` 改変 / Docker socket / secrets 読み出し) を実行する経路を物理削除しなければならない。

DD-04 §Hard Gates の `forbidden_path_block` (AC-HARD-05) と `dangerous_command_block` (AC-HARD-06) は本 ADR の正本基準となる。

## 決定対象

- runner sandbox 内で **拒否される操作 (denylist)** の正本一覧
- runner sandbox 内で **許可される操作 (allowlist)** の境界
- rollback 手順
- fixture 方針

## 前提 / 制約

- runner は AgentRun ごとに **run-per-container** で disposable に作る。
- Docker base image は read-only root + non-root user + no privileged。
- network egress は Tailscale 閉域 allowlist (本 Sprint 7 BL-0075 で実装)。
- runner env から raw secret / provider key / installation token / SOPS age key を除外 (BL-0076)。
- `runner_mutation_gateway` (BL-0077) は policy / approval / forbidden path / dangerous command の **全 gate を通過した patch のみ** apply。

## 選択肢

### 採用案: Layered denylist + allowlist + canonical path normalization

**denylist (forbidden path)**:

1. `.env` および `.env.*` (host-level secrets)
2. `.git/config` / `.git/objects/` / `.git/hooks/` / `.git/info/` (git infrastructure)
3. `secrets/` (custom secret directory)
4. `migrations/` (Alembic migration files)
5. `.github/workflows/**` (CI workflow)
6. `.claude/CLAUDE.md` / `.claude/settings.json` / `.claude/settings.local.json`
7. `.claude/hooks/` / `.claude/agents/` / `.claude/skills/` / `.claude/rules/` / `.claude/reference/` / `.claude/commands/`
8. `.claude/local/` (project local state)
9. `.codex/` (Codex CLI configuration)
10. `~/.ssh/` / `~/.aws/` / `~/.kube/` (host secret stores)
11. `/etc/passwd` / `/etc/shadow` / `/etc/sudoers` (system credentials)
12. `/proc/` / `/sys/` (kernel interfaces、container 内では bind-mount 制御)
13. `/var/run/docker.sock` / `/run/docker.sock` (Docker socket、host control)

**denylist (dangerous command)**:

1. `rm -rf` / `rm -fr` / `find ... -delete` (mass deletion)
2. `curl ... | sh` / `wget ... | sh` (remote execution)
3. `chmod 777` / `chmod -R 777` (privilege expansion)
4. `chown -R` to non-owner (privilege transfer)
5. `dd of=/dev/...` (disk overwrite)
6. `mkfs.*` (filesystem creation)
7. `docker run --privileged` / `docker exec` (container escape)
8. `mount` / `umount` (filesystem manipulation)
9. fork bomb pattern `:(){:|:&};:` (resource exhaustion)
10. `eval` / `source` から base64 decode された script の実行
11. Docker socket / Kubernetes API への curl
12. `sudo` / `su` (privilege escalation)
13. `iptables` / `ufw` (network policy 改変)
14. `kill -9 1` / `killall -9 init` (PID 1 termination)
15. `:&` background fork + 制限なし再帰

**allowlist (write-permitted path)**:

1. `${RUN_WORKDIR}/**` (per-run workdir、mode=0o700、uid=runner-user)
2. `${ARTIFACT_OUTBOX}/**` (artifact output dir)
3. `${TEMP_DIR}/**` (per-run temp、`/tmp/run-<id>/`)

これ以外への write は **canonical path resolution 後** に denylist に該当しなくても reject (fail-closed)。

**canonical path normalization**:

- `..` parent ref を `os.path.realpath` で resolve
- symlink を `Path.resolve(strict=False)` で follow
- URL encoded (`%2F` → `/`) / unicode escape を decode
- hardlink を `stat().st_ino` で同一性検証
- 大文字小文字を case-insensitive 比較 (macOS HFS+ 対応)

**command parser**:

- shell metachar (`;` `&&` `||` `|` `` ` `` `$(...)`) を構文解析
- pipe / subshell / heredoc / process substitution を分解
- `base64 -d | sh` パターンを decode してから denylist 適用
- env variable expansion を再現 (`$VAR` / `${VAR}`)
- ANSI escape / Unicode default-ignorable を Sprint 6 redaction.py と同じ strategy で strip

### 却下案: container 全機能 read-only (chroot-only)

- 利点: 簡潔
- 却下理由: legitimate な patch apply / test 実行が困難。container 内 workdir への write は許可する必要がある。

### 却下案: denylist のみ (allowlist 不要)

- 利点: 柔軟
- 却下理由: 新規 path / 新規 command が増えるたびに denylist update が必要、未知の attack surface に対し fail-open。allowlist と組み合わせて defense-in-depth。

## リスク

- **path normalization bypass**: Unicode confusable / mojibake / 多重 encoding。Sprint 6 redaction.py の Cc/Cf carpet-bomb pattern を共有して対応。Sprint 11 eval harness で adversarial fixture 追加。
- **command parser limit**: 全 shell syntax を正確に parse することは難しい。shell=False + argv array 入力を強制し、shell string 受領経路を signature レベル削除 (Sprint 6 batch 1 launcher で実装済 pattern を runner にも適用)。
- **container escape (kernel exploit)**: Docker base image 更新 + non-root user + seccomp profile で軽減。残: CRITICAL exploit は ADR-00008 scope 外、CVE 監視と base image rebuild に依存。

## rollback 手順

1. **runner_mutation_gateway を全 deny に切替**: feature flag `RUNNER_MUTATION_GATEWAY_FORCE_DENY=true` で全 patch apply 拒否。
2. **container 自体を停止**: `docker stop $(docker ps -q -f label=taskmanagedai-runner)` で全 runner container 停止。
3. **workdir cleanup**: per-run workdir を `rm -rf /var/lib/taskmanagedai/runs/*` で削除 (allowlisted path 内のみ、host fs に影響なし)。
4. **denylist / allowlist 戻し**: 本 ADR が proposed → accepted 化された commit を revert。

## 実装対象ファイル

- `backend/app/services/runner/forbidden_path.py` (BL-0072)
- `backend/app/services/runner/dangerous_command.py` (BL-0073)
- `backend/app/services/runner/mutation_gateway.py` (BL-0077)
- `tests/runner/test_forbidden_path.py` (BL-0080)
- `tests/runner/test_dangerous_command.py` (BL-0081)
- `eval/fixtures/ac_hard_05/` (BL-0080 fixture)
- `eval/fixtures/ac_hard_06/` (BL-0081 fixture)

## テスト指針

- public_regression / private_holdout / adversarial_new の 3 split。
- forbidden_path: 100 path × 3 split = 300 fixture。Sprint 11 で expand。
- dangerous_command: 100 command pattern × 3 split = 300 fixture。
- adversarial fixture には Unicode bypass / encoding tricks / chained command を含む。
- raw secret / canary 値は fixture に含めず、pattern 種別と redacted expected result のみ。
