# SP022-T03: 半年 drill scheduling SOP

最終更新: 2026-05-19 (codex-plan-review R1 16 + R2 3 + R3 0 = 累計 19 findings 全件 adopt + R3 CRITICAL clean、Readiness Gate READY)

## 1. 目的 (Goal)

SP-022 must_ship Phase G (PGA-F-013、ADR-00021 §14.2 #4 strengthening、`docs/sprints/SP-022_framework_intake_hardening.md` line 178)。半年に 1 回の host migration drill scheduling を **cron / systemd timer の alert-only 強制** + **手動 approval flow** で運用 SOP 化する。

具体的には以下 3 件を本 task で完成する:
1. `scripts/ci/check_drill_timer_alert_only.sh` — systemd timer / cron entry の ExecStart が destructive command (e.g., `taskhub migrate`) を含む場合 CI fail (通知 command のみ allowlist 化)
2. `tests/deploy/test_drill_timer_alert_only.py` — pytest fixture for CI gate (positive deny / negative pass)
3. `docs/deploy/half-yearly-drill-sop.md` — 半年 drill scheduling SOP (cron alert + 手動 approval flow + signed approval record + 異常時 escalation)

## 2. 背景 (Background)

- ADR-00021 §14.2 #4 (PGA-F-013、2026-05-19 accepted): drill timer alert-only enforcement、SP-022 で運用 SOP 化必須
- SP-022 §Phase G adversarial strengthening (line 177-187) で本 file 群を must_ship に明示
- `taskhub migrate --approval-id` 実装は **SP022-T02 (`taskhub migrate` 自動化)** の scope、本 T03 では SOP 内で **仕様明文化のみ** (実装は T02 別 PR)
- 本 T03 scope は CI gate (drill timer scan) + SOP docs に限定 (受け入れ条件 §3.2 参照)
- SP022-T01 PR #70 で確立した CI gate pattern (diff-gate / baseline-scan、emergency disable repository variable、`uv run --no-sync` 等) を本 T03 でも踏襲

## 3. Scope (実装範囲)

### 3.1 must_ship (本 PR 内)

| # | 対象 | 種別 |
|---|---|---|
| 1 | `scripts/ci/check_drill_timer_alert_only.sh` (NEW) | 新規 CI script、systemd timer / cron entry scan + destructive command denylist |
| 2 | `scripts/ci/_drill_timer_scanner.py` (NEW) | Python helper、systemd `.timer` / `.service` / cron file parse + ExecStart 抽出 + allowlist/denylist match |
| 3 | `tests/deploy/__init__.py` + `tests/deploy/test_drill_timer_alert_only.py` (NEW) | pytest fixture (positive 5-7 + negative 2-3) |
| ~~4~~ | ~~`tests/scripts/test_check_drill_timer_alert_only.sh`~~ | **scope 外 (R1 F-012 adopt)**: SP022-T01 で bash + pytest 両方は overkill と確認、本 task では pytest fixture (`tests/deploy/test_drill_timer_alert_only.py`) のみ採用 |
| 5 | `docs/deploy/half-yearly-drill-sop.md` (NEW) | 半年 drill SOP (cron / systemd timer 構成例 + 手動 approval flow + signed approval record SOP + 異常時 escalation) |
| 6 | `.github/workflows/ci-smoke.yml` (MODIFY) | `backend-quality` job に "Drill timer alert-only check" step 追加 |
| 7 | `docs/sprints/SP-022_framework_intake_hardening.md` (MODIFY、`## Review` 章) | SP022-T03 完了記録 + Phase G PGA-F-013 trace marker |

### 3.2 対象外 (本 task では実装しない)

- **`taskhub migrate --approval-id` 実装**: SP022-T02 (`taskhub migrate` 自動化) の scope、本 T03 SOP 内で **仕様明文化のみ** (cron / systemd 環境変数検出、signed approval record `~/.taskhub/approvals/<id>.signed` 等の SOP 記述)。実 CLI 実装は別 PR
- **signed approval record の暗号署名実装**: T02 scope、本 T03 では SOP 内で format 仕様 (Ed25519 / SOPS age 等) のみ記述
- **実機 drill execution**: SP022-T09 (実機 host migration drill Mac→VPS RTO≤4h PASS) の scope
- **既存 cron / systemd timer の retrofit**: 本 task は CI gate (今後の PR で追加される drill timer に対する gate) のみ確立、既存 entry の retrofit は不要 (本 repo に既存 drill timer はなく、SP022-T02 で追加される時点で gate 適用)
- **`taskhub migrate --approval-id` の pytest fixture (`test_taskhub_migrate_approval_required.py`)**: SP-022 §Phase G 追加実装ファイル line 187 に含まれるが、`taskhub migrate` 実装が T02 必要のため本 T03 scope 外、T02 で実装

## 4. CI gate 機械化方針 (ADR-00021 §14.2 #4)

### 4.1 検査対象 file pattern (R1 F-002 / F-003 / F-007 / F-008 adopt 反映済)

scan scope を **drill 関連 path のみ** に限定し、legitimate non-drill service への false-positive を回避する (R1 F-007 adopt):

| pattern | 用途 |
|---|---|
| `**/*drill*.timer` AND `**/*drill*.service` | drill 名で明示された systemd timer / service file |
| `**/*drill*.service` (`.timer` の `[Timer] Unit=<X>` 経由 paired service、R1 F-003 adopt) | timer file が `Unit=` で参照する service file (timer と異なる basename 可) |
| `docs/deploy/**/*.timer` AND `docs/deploy/**/*.service` | docs 内の SOP example file |
| `deploy/**/*.timer` AND `deploy/**/*.service` | ops directory 内 |
| `ops/**/*.timer` AND `ops/**/*.service` | ops directory 内 |
| `**/crontab` AND `**/crontabs/**` AND `**/cron.d/**` AND `etc/cron.d/**` | cron file (drill 関連) |

scan root: repo 全体 (`.`、ただし `.git/` / `.venv/` / `node_modules/` / `frontend/node_modules/` / `__pycache__/` 除外)。**glob match で drill 名 / deploy path のみ対象、それ以外の `.service` (e.g., production app service) は scan 対象外**。

### 4.1.1 systemd `.timer` → `.service` paired resolution (R1 F-003 adopt)

systemd `.timer` file は `ExecStart=` を直接持たず、関連 `.service` を起動する。以下の resolution logic を採用:

1. `.timer` file を発見したら、その content から `^\s*Unit\s*=\s*(.+)\s*$` を parse して explicit `Unit=` directive を抽出
2. `Unit=` が明示されていない場合 → 同 basename の `.service` を fallback で resolve (e.g., `taskhub-drill-alert.timer` → `taskhub-drill-alert.service`)
3. paired `.service` を解決できない場合 → **fail-closed**: violation `drill_timer_paired_service_missing` emit (alert-only enforcement を bypass する可能性を完全排除)
4. paired `.service` は scan 対象に追加 (diff-gate mode で `.timer` のみ変更された PR でも対 service も scan)

### 4.1.2 cron parser robustness (R1 F-008 adopt)

cron file の parser を以下 spec で固定:

- **user crontab** (`crontab` / `~/.crontab` 等): 5-field `<minute> <hour> <day> <month> <weekday> <command>`、user field なし
- **`/etc/cron.d/`** entry: 6-field `<minute> <hour> <day> <month> <weekday> <user> <command>`、user field 含む
- **macro entries**: `@reboot` / `@yearly` / `@annually` / `@monthly` / `@weekly` / `@daily` / `@midnight` / `@hourly` を別 regex で抽出
- **environment variable lines** (`PATH=...` / `MAILTO=...` / `SHELL=...` / `CRON_TZ=...`): scan skip (command ではない)
- **comment line** (`^\s*#`): scan skip
- **empty line**: scan skip
- **continuation line** (`\` で終わる行): cron は line continuation を spec 上 supports しないため、対象外 (検出しても扱わず fail-closed で violation)
- **`%` literal in command field**: cron `%` 以降を stdin 扱いするため、command field は `%` で truncate して `_check_command()` に渡す

### 4.2 ExecStart / cron command 抽出ロジック (Python helper、R1 F-004 / F-009 adopt)

`scripts/ci/_drill_timer_scanner.py` (Python 標準 `re` + `pathlib`):

| step | 内容 |
|---|---|
| 1 | scope 限定 glob (§4.1) で file 収集 |
| 2 | systemd `.service` から **全 Exec*=** directive line 抽出 (line-anchored regex、R1 F-004 adopt): `ExecStartPre=`, `ExecStart=`, `ExecStartPost=`, `ExecReload=`, `ExecStop=`, `ExecStopPost=` 全件 |
| 3 | `.timer` file は paired `.service` resolution (§4.1.1) で service を scan に追加 |
| 4 | cron file から user crontab / `cron.d` を type 判定して command field 抽出 (§4.1.2 robust parser) |
| 5 | 各 command を allowlist / denylist + shell composition check (§4.5、R1 F-005 adopt) |
| 6 | denylist hit OR shell composition detected OR allowlist match なし → **統一 reason_code** emit |

### 4.2.1 統一 reason_code (R1 F-009 adopt)

violation の `reason_code` は以下に統一 (`framework_intake_violation_*` family 命名と整合):

| condition | reason_code |
|---|---|
| denylist pattern hit | `framework_intake_violation_drill_timer_alert_only_destructive_command` |
| shell composition / metacharacter detected (R1 F-005、`$(...)` / backtick / `;` / `&&` / `\|\|` / `\|` / `>` / `<<` / heredoc 等) | `framework_intake_violation_drill_timer_alert_only_shell_composition` |
| allowlist match なし (denylist + shell composition も hit せず) | `framework_intake_violation_drill_timer_alert_only_unknown_command` |
| paired `.service` resolution 失敗 (R1 F-003) | `framework_intake_violation_drill_timer_paired_service_missing` |
| cron parser malformed line (R1 F-008) | `framework_intake_violation_drill_timer_alert_only_cron_parse_failed` |

### 4.3 Allowlist / Denylist (R1 F-001 / F-006 adopt 反映済、ADR-00021 §14.2 #4 から)

#### Allowlist (通知 command、これらのみ ExecStart 許可)

| command head | platform | 例 |
|---|---|---|
| `notify-send` | Linux desktop | `notify-send "Drill alert" "Half-yearly drill due"` |
| `osascript` | macOS | `osascript -e 'display notification "Drill due" with title "TaskManagedAI"'` |
| `slack-cli` / `slack` | cross | `slack chat send --channel ops` |
| `discord-cli` | cross | `discord-cli send --channel drill-alert` |
| `mail` / `sendmail` | cross | `mail -s "Drill due" ops@example.com` |
| `echo` / `printf` (log message のみ) | shell | `echo "Drill due"` (但し shell metacharacter ban、§4.5) |
| `logger` (syslog forward) | Linux | `logger -t taskhub-drill "Drill due"` |

**`curl` は本 task scope の allowlist から除外** (R1 F-001 adopt)。理由: `curl http://target/destroy?id=1` の destructive endpoint POST が pass する risk があり、Slack/Discord webhook host allowlist + method 限定 + 危険 option 禁止は本 task scope 外。SOP では `slack-cli` / `discord-cli` / `mail` を webhook 用途の代替として明示推奨、curl 必要時は post-T03 (SP-022.X) で URL allowlist + method 制限の安全な curl 専用 rule を追加して再導入を判断。

#### Denylist (destructive command、これらが ExecStart 等にあれば fail)

R1 F-006 adopt: denylist を **defense-in-depth として拡張** (完全性ではなく多層防御の追加 layer、main gate は allowlist whitelist):

| command pattern | 理由 |
|---|---|
| `taskhub migrate` | host migration 自動実行禁止 (ADR-00021 §14.2 #4) |
| `taskhub restore` | restore 自動実行禁止 |
| `taskhub age-rotate` | key rotation 自動実行禁止 |
| `taskhub backup` | backup 自動実行は drill 文脈で SOP 違反 |
| `docker compose (down\|stop\|kill\|rm)` | service stop / removal |
| `docker volume (rm\|prune)` | volume destructive (R1 F-006 adopt) |
| `kubectl (delete\|scale)` | k8s destructive (R1 F-006 adopt) |
| `pg_(dump\|restore\|basebackup\|drop)` | DB direct operation |
| `dropdb` / `createdb --template` | DB drop (R1 F-006 adopt) |
| `psql .*\b(DROP\|TRUNCATE\|DELETE)\b` | psql destructive SQL (R1 F-006 adopt) |
| `redis-cli (flushall\|flushdb)` | Redis flush (R1 F-006 adopt) |
| `rm -[a-zA-Z]*[rRfF]` / `find ... -delete` / `unlink` | filesystem destructive |
| `dd` / `mkfs` | low-level destructive |
| `kill -9` / `pkill -9` | process kill |
| `systemctl (stop\|restart\|kill\|disable\|poweroff\|reboot)` | service / power control |
| `shutdown` / `reboot` / `poweroff` / `halt` | host power destructive (R1 F-006 adopt) |
| `truncate` (filesystem level) | file truncation |

**denylist 性質明記**: denylist は完全性 (exhaustive) ではなく、allowlist whitelist の **追加防御 layer** (defense-in-depth)。新 destructive command が登場時は allowlist match なしで `unknown_command` violation emit、安全側 fail-closed (R1 F-006 adopt の expectation 通り)。

#### 判定優先順位 (R1 F-005 + R2 F-R2-003 adopt 反映)

1. **shell composition check** (最優先、§4.5): allowlist match 前に shell metacharacter / composition pattern を check、hit したら **head に関係なく** `shell_composition` violation emit
2. denylist match: 即 violation (reason: `destructive_command`)
3. **path spoofing check** (R2 F-R2-003 adopt、新優先 step): command の先頭 token に `/` が含まれる場合、`TRUSTED_PATH_PREFIXES` (`/usr/bin/`, `/usr/local/bin/`, `/bin/`, `/usr/sbin/`, `/sbin/`) のいずれかで始まる絶対 path のみ pass、それ以外 (`./` relative path / `~/` / `/tmp/` / `/home/<user>/...` 等) は `path_spoofing` violation emit。`/` なし bare command (e.g., `slack-cli`) は PATH-resolved として step 4 へ
4. **PATH spoofing env line check** (R2 F-R2-003 adopt、cron 限定): cron file 内の `PATH=` / `SHELL=` / `BASH_ENV=` / `ENV=` / `LD_PRELOAD=` / `LD_LIBRARY_PATH=` env line は **fail-closed** (旧 R1 F-008 「env line skip」を撤回、`PATH=./ops/bin` 等で arbitrary binary を allowlist 名で実行できる bypass を防ぐ)。violation `path_spoofing_env_line` emit
5. allowlist head match (cmd の先頭 token、`/` 含む場合は §4.3.1 で path 検証済): pass
6. allowlist match なし AND 1-5 全 false: violation (reason: `unknown_command`、安全側 fail-closed)

### 4.3.1 trusted absolute path prefix (R2 F-R2-003 adopt 新設)

```python
TRUSTED_PATH_PREFIXES: tuple[str, ...] = (
    "/usr/bin/",
    "/usr/local/bin/",
    "/bin/",
    "/usr/sbin/",
    "/sbin/",
    # macOS-specific
    "/opt/homebrew/bin/",
    "/opt/local/bin/",
)

def _check_path_spoofing(cmd_head: str) -> tuple[str | None, str | None]:
    """If cmd_head contains `/`, must start with a TRUSTED_PATH_PREFIXES entry.

    Examples:
    - `/usr/bin/slack-cli` → pass (trusted prefix)
    - `slack-cli` (no slash) → pass (PATH-resolved, fall through to allowlist head check)
    - `/tmp/slack-cli` → violation (untrusted absolute path)
    - `./ops/bin/slack-cli` → violation (relative path)
    - `~/.taskhub/bin/slack-cli` → violation (home expansion)
    """
    if "/" not in cmd_head:
        return (None, None)
    if any(cmd_head.startswith(prefix) for prefix in TRUSTED_PATH_PREFIXES):
        return (None, None)
    return ("path_spoofing", f"untrusted_path={cmd_head[:80]}")
```

### 4.3.2 cron env line fail-closed (R2 F-R2-003 adopt 新設)

```python
PATH_SPOOFING_ENV_VARS: frozenset[str] = frozenset({
    "PATH", "SHELL", "BASH_ENV", "ENV",
    "LD_PRELOAD", "LD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES",
})

def _check_cron_env_line(line: str) -> tuple[str | None, str | None]:
    """Cron env line `<VAR>=<value>` (旧 R1 F-008 で skip 扱いだったが、R2 F-R2-003 で
    PATH/SHELL/BASH_ENV 等は fail-closed に変更、PATH spoofing 経路を物理遮断)."""
    match = re.match(r"^\s*([A-Z_][A-Z0-9_]*)\s*=", line)
    if not match:
        return (None, None)
    var_name = match.group(1)
    if var_name in PATH_SPOOFING_ENV_VARS:
        return ("path_spoofing_env_line", f"cron_env_var={var_name}")
    return (None, None)
```

非該当 env (e.g., `MAILTO=ops@example.com`, `CRON_TZ=UTC`) は pass、PATH spoofing 経路に該当する env のみ violation。

### 4.4 CI mode + scanner interface (R1 F-002 / F-010 / F-011 adopt 反映済)

| mode | trigger | scope |
|---|---|---|
| `diff-gate` | `GITHUB_EVENT_NAME=pull_request` AND drill timer file (`*drill*.timer` / `*drill*.service` / paired service / `crontab` / `cron.d/**`) が PR 内で changed | 変更された drill timer file のみ scan (shell から `--paths-from-stdin` 経由で渡す) |
| `baseline-scan` | `GITHUB_EVENT_NAME=push` AND `GITHUB_REF_NAME=main` | scope 限定 glob (§4.1) で全 drill timer / cron file を scan (regression 防止) |
| local / 他 ref | `--mode={diff-gate,baseline-scan}` 引数、default `baseline-scan` (safe side) |

### 4.4.1 scanner CLI interface (R1 F-002 adopt)

`scripts/ci/_drill_timer_scanner.py` の引数:

```
--mode={diff-gate,baseline-scan}   # 必須
--paths-from-stdin                  # diff-gate mode で shell から changed file list を NUL 区切りで stdin から読む
                                    # 形式: `\0` separated path list (git diff --name-only -z 経由)
                                    # 各 path に対して: (a) .timer なら paired .service も resolve、(b) .service なら direct scan、(c) cron file なら direct scan
                                    # rename: 旧 path / 新 path 両方 scan、(d) 削除のみ (deleted) は paired remaining files の scan が必要 (§4.4.2)
```

shell 側 (`check_drill_timer_alert_only.sh`、R2 F-R2-001 adopt: NUL byte は shell `$()` で保持されないため、`git diff -z` の出力を **temp file 経由** で scanner に渡す):

```bash
if [ "$MODE" = "diff-gate" ]; then
    # base ref resolution
    BASE_REF="${GITHUB_BASE_REF:-main}"
    if ! git rev-parse --verify "origin/${BASE_REF}" >/dev/null 2>&1; then
        echo "drill_timer_alert_only_check: ERROR origin/${BASE_REF} not resolvable" >&2
        exit 2
    fi
    # R2 F-R2-001 adopt: NUL list は temp file 経由 (shell command substitution は NUL を潰す)
    CHANGED_FILE=$(mktemp -t drill_timer_changed.XXXXXX)
    git diff --name-only -z --diff-filter=ACMRD "origin/${BASE_REF}...HEAD" > "$CHANGED_FILE"
    if [ ! -s "$CHANGED_FILE" ]; then
        rm -f "$CHANGED_FILE"
        echo "drill_timer_alert_only_check: SKIP (mode=diff-gate, no file changes)"
        exit 0
    fi
    # scanner に temp file 経由で渡す (NUL preserved)
    uv run --no-sync python -m scripts.ci._drill_timer_scanner --mode=diff-gate --paths-from-file="$CHANGED_FILE"
    EXIT_CODE=$?
    rm -f "$CHANGED_FILE"
    exit $EXIT_CODE
else
    uv run --no-sync python -m scripts.ci._drill_timer_scanner --mode=baseline-scan
fi
```

scanner 側 interface: `--paths-from-file=<path>` に変更 (NUL 区切りで file 内容を読み、`.split(b"\0")` で path list 構築)。`--paths-from-stdin` は実行可能性 (subprocess pipe で NUL preserve 可) があるが、temp file 経由が確実 (R2 F-R2-001 adopt)。

### 4.4.2 削除のみ PR (rename / delete) の扱い (R1 F-011 adopt)

- 削除のみで paired `.timer` も存在しない場合: scan skip (`.timer` も `.service` も両方 deleted)
- `.timer` 削除残 `.service` あり (orphan): scan 対象外 (`.timer` 不在で alert-only enforcement の意味なし)
- `.service` 削除残 `.timer` あり (orphan): violation `framework_intake_violation_drill_timer_paired_service_missing` (paired service resolution 失敗)
- rename: old / new path 両方 scan

### 4.4.3 fork PR / shallow clone / workflow_dispatch の挙動 (R1 F-011 adopt)

- **fork PR**: `GITHUB_BASE_REF` は upstream の default branch (`main`)、`origin` は fork repo に向くため `origin/main` 解決失敗の可能性。本 task では `git fetch upstream main` を CI workflow で事前 fetch 推奨だが、本 PR では `fetch-depth: 0` のみ (SP022-T01 と同) で、fork PR で `origin/${GITHUB_BASE_REF}` 解決失敗時は exit 2 (manual investigation 推奨)
- **shallow clone**: SP022-T01 と同、`fetch-depth: 0` 設定済の前提
- **workflow_dispatch / local**: default `baseline-scan` で repo 全 scan
- **`GITHUB_EVENT_NAME`/`GITHUB_BASE_REF` 不在 (local 実行)**: `--mode=` 引数で明示、default `baseline-scan` (safe side)

### 4.4.4 emergency disable (R1 F-010 adopt)

- workflow 側で `if: vars.DRILL_TIMER_ALERT_ONLY_CHECK_DISABLED != '1'` で step 自体を skip (PR author env で上書き不可、admin variable 経由のみ)
- shell 内 defense-in-depth: `if [ "${DRILL_TIMER_ALERT_ONLY_CHECK_DISABLED:-}" = "1" ]` 二重 check (step `if:` 突破時の救済)
- disable 時 audit marker: stderr に `audit_marker: drill_timer_alert_only_check_disabled_at=<UTC>` + `audit_marker: emergency_disable=true` + `audit_marker: requires_retro_pack_within_24h=true` + `audit_marker: ADR_PGA=ADR-00021-§14.2-#4-PGA-F-013`
- repository variable (`vars.DRILL_TIMER_ALERT_ONLY_CHECK_DISABLED`) は GitHub Settings → Variables から admin のみ設定可、PR diff から author が任意で設定不可

### 4.5 shell composition / metacharacter check (R1 F-005 + R2 F-R2-002 adopt)

allowlist head が match した command でも、以下 pattern が含まれていれば **shell composition bypass** として fail-closed (新 violation `framework_intake_violation_drill_timer_alert_only_shell_composition`):

- `$(...)` / `` `...` `` (command substitution)
- `;` (command separator)
- `&&` / `||` (conditional chaining)
- `|` (pipe to other command)
- `>` / `>>` (output redirect)
- **`<` 単独 (input redirect、R2 F-R2-002 adopt: `mail -s drill ops@example.com < ~/.taskhub/approvals/id.signed` 等で secret file を notification 経路で送信される bypass)**
- `<<` / `<<<` (heredoc / herestring)
- `&` (background process)
- newline (`\n`) embedded in command line
- shell expansion `~` `*` `?` (file glob、ただし `echo "Drill due at ${TIMESTAMP}"` の `$var` simple expansion は許可)

検出 logic (Python、R2 F-R2-002 adopt 反映):

```python
SHELL_COMPOSITION_RE = re.compile(
    # backtick / cmdsub / separator / redirect (>, >>, <, <<, <<<) / bg / pipe
    # `<` 単独も検出するため `<<*` で 1 個以上 match (旧 regex `<<+` は 2 個以上だけだった)
    r"(\$\(|`|;|&&|\|\||\||>>?|<+|\s&\s|\s&$)"
)
SHELL_NEWLINE_RE = re.compile(r"\n")  # raw newline in command line

def _check_shell_composition(cmd_line: str) -> tuple[str | None, str | None]:
    if SHELL_COMPOSITION_RE.search(cmd_line) or SHELL_NEWLINE_RE.search(cmd_line):
        return ("shell_composition", "metacharacter_or_composition")
    return (None, None)
```

R2 F-R2-002 negative fixture: `mail -s drill ops@example.com < ~/.taskhub/approvals/id.signed` で `<` redirect 検出 + violation emit verify。

正当な用例 (例: `echo "Drill due at $(date)"`) でも `$(date)` が含まれるため violation。SOP 例では `$(date)` 等 command substitution は避け、systemd timer の `OnCalendar=` schedule + service の simple message に置換 (e.g., `slack-cli chat send --channel ops "Half-yearly drill scheduled"`)。

### 4.6 script 実行 environment

backend-quality job (`.github/workflows/ci-smoke.yml`) 内 `Install backend dependencies` step (uv sync --locked) の後で実行。SP022-T01 の Framework intake check step 直後に配置 (CI gate 群を 1 箇所に集約)。

- 必要 tool: `bash` / `git` / `uv run python3` (3.12)
- `rg` (ripgrep) 不要 (Python scanner で実装、SP022-T01 R2 教訓踏襲)
- Node/pnpm 不要

## 5. 実装詳細

### 5.1 `scripts/ci/check_drill_timer_alert_only.sh` 構造

```bash
#!/usr/bin/env bash
# Drill timer alert-only enforcement (ADR-00021 §14.2 #4 PGA-F-013, SP022-T03).
#
# 2 modes (SP022-T01 と同 pattern):
#   - diff-gate    : pull_request event、drill timer file 変更時のみ scan
#   - baseline-scan: push to main、repo 全 drill timer を scan
#
# Exit codes:
#   0 = PASS / SKIP (no drill timer files in diff-gate)
#   1 = violation found (destructive command in ExecStart or cron command)
#   2 = internal error
set -euo pipefail

# ---- 0. mode determination + emergency disable (SP022-T01 同 pattern) ----
# ---- 1. base ref resolution (diff-gate mode のみ) ----
# ---- 2. diff-gate mode early exit (no drill timer changes) ----
# ---- 3. Python scanner 経由 ----
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
run_scanner() {
    local mode="$1"
    local output exit_code=0
    output=$(uv run --no-sync python -m scripts.ci._drill_timer_scanner --mode="$mode" 2>&1) || exit_code=$?
    case "$exit_code" in
        0) return 0 ;;
        1) printf '%s\n' "$output"; echo "drill_timer_alert_only_check: FAIL (mode=$mode)"; exit 1 ;;
        *) echo "drill_timer_alert_only_check: ERROR scanner crashed (exit=$exit_code)" >&2; echo "$output" >&2; exit 2 ;;
    esac
}
run_scanner "$MODE"
echo "drill_timer_alert_only_check: PASS (mode=$MODE)"
exit 0
```

### 5.2 `scripts/ci/_drill_timer_scanner.py` (Python helper)

```python
"""Drill timer / cron destructive command scanner (ADR-00021 §14.2 #4 PGA-F-013, SP022-T03).

systemd .timer / .service files and cron entries scanned for ExecStart / cron command lines.
Allowlist = notification commands (notify-send / osascript / slack-cli / discord-cli / mail /
sendmail / curl / echo / printf / logger). Denylist = destructive commands (taskhub migrate /
restore / age-rotate / backup / docker compose down / pg_* / rm -rf / dd / mkfs / kill / systemctl).
"""
from __future__ import annotations
import argparse, re, shlex, sys
from pathlib import Path
from typing import Iterable

ALLOWLIST_HEADS: frozenset[str] = frozenset({
    "notify-send", "osascript", "slack-cli", "slack", "discord-cli", "discord",
    "mail", "sendmail", "curl", "echo", "printf", "logger",
})
DENYLIST_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\btaskhub\s+(migrate|restore|age-rotate|backup)\b", "taskhub_destructive_subcommand"),
    (r"\bdocker\s+compose\s+(down|stop|kill)\b", "docker_compose_destructive"),
    (r"\bpg_(dump|restore|basebackup|drop)\b", "postgres_direct_operation"),
    (r"\brm\s+(-[a-zA-Z]*[rRfF][a-zA-Z]*)\b", "rm_destructive"),
    (r"\bfind\s+.*-(delete|exec\s+rm)\b", "find_destructive"),
    (r"\bunlink\b", "unlink"),
    (r"\b(dd|mkfs)(\s|$)", "low_level_destructive"),
    (r"\bkill\s+-9\b", "kill_force"),
    (r"\bpkill\s+-9\b", "pkill_force"),
    (r"\bsystemctl\s+(stop|restart|kill|disable)\b", "systemctl_control"),
)
SYSTEMD_EXEC_RE = re.compile(r"^\s*ExecStart\s*=\s*(.+)$", re.MULTILINE)
CRON_CMD_RE = re.compile(
    r"^\s*[\d\*\-/, \t]+\s+(?:[\w_-]+\s+)?(.+)$",
    re.MULTILINE,
)
EXCLUDE_DIRS: frozenset[str] = frozenset({".git", ".venv", "node_modules", "__pycache__"})

def _iter_files(root: Path, patterns: Iterable[str]) -> list[Path]:
    files: list[Path] = []
    for pattern in patterns:
        for path in root.rglob(pattern):
            if any(part in EXCLUDE_DIRS for part in path.parts):
                continue
            if path.is_file():
                files.append(path)
    return files

def _check_command(cmd_line: str) -> tuple[str | None, str | None]:
    """Return (violation_reason, denylist_label) or (None, None) if pass."""
    # 1. denylist priority
    for pattern, label in DENYLIST_PATTERNS:
        if re.search(pattern, cmd_line):
            return ("destructive_command", label)
    # 2. allowlist: first token == head allowlist
    try:
        tokens = shlex.split(cmd_line)
    except ValueError:
        # malformed quotes → fail-closed
        return ("unknown_command", "shlex_parse_failed")
    if not tokens:
        return ("unknown_command", "empty_command")
    head = tokens[0].rsplit("/", 1)[-1]  # strip leading path
    if head in ALLOWLIST_HEADS:
        return (None, None)
    return ("unknown_command", head)

def check_systemd_files(root: Path) -> list[str]:
    violations: list[str] = []
    for path in _iter_files(root, ("*.timer", "*.service")):
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for match in SYSTEMD_EXEC_RE.finditer(content):
            cmd_line = match.group(1).strip()
            reason, label = _check_command(cmd_line)
            if reason:
                line_num = content[: match.start()].count("\n") + 1
                violations.append(
                    f"VIOLATION reason_code=drill_timer_alert_only_violation_{reason} "
                    f"evidence={path}:{line_num} label={label} command={cmd_line[:80]}"
                )
    return violations

def check_cron_files(root: Path) -> list[str]:
    violations: list[str] = []
    cron_paths = list(_iter_files(root, ("crontab", "crontabs/*", "cron.d/*", "etc/cron.d/*")))
    # also accept any file under */cron.d/
    for path in root.rglob("cron.d/*"):
        if any(part in EXCLUDE_DIRS for part in path.parts): continue
        if path.is_file(): cron_paths.append(path)
    for path in cron_paths:
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for match in CRON_CMD_RE.finditer(content):
            cmd_line = match.group(1).strip()
            if not cmd_line or cmd_line.startswith("#"):
                continue
            reason, label = _check_command(cmd_line)
            if reason:
                line_num = content[: match.start()].count("\n") + 1
                violations.append(
                    f"VIOLATION reason_code=drill_timer_alert_only_violation_{reason} "
                    f"evidence={path}:{line_num} label={label} command={cmd_line[:80]}"
                )
    return violations

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["diff-gate", "baseline-scan"], required=True)
    args = parser.parse_args()
    root = Path(".")
    try:
        violations = check_systemd_files(root) + check_cron_files(root)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR scanner failed: {exc}", file=sys.stderr); return 2
    for line in violations:
        print(line)
    return 1 if violations else 0

if __name__ == "__main__":
    sys.exit(main())
```

### 5.3 `tests/deploy/test_drill_timer_alert_only.py` (pytest fixture)

```python
"""Drill timer alert-only enforcement pytest fixture (SP022-T03 ADR-00021 §14.2 #4 PGA-F-013)."""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCANNER = REPO_ROOT / "scripts/ci/_drill_timer_scanner.py"

def _run_scanner(tmp_path: Path, mode: str = "baseline-scan") -> tuple[int, str]:
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SCANNER), f"--mode={mode}"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout + result.stderr

# positive: destructive command in ExecStart → reject
def test_systemd_taskhub_migrate_rejected(tmp_path: Path) -> None: ...
def test_systemd_docker_compose_down_rejected(tmp_path: Path) -> None: ...
def test_systemd_rm_rf_rejected(tmp_path: Path) -> None: ...
def test_systemd_unknown_command_rejected(tmp_path: Path) -> None: ...
def test_cron_taskhub_restore_rejected(tmp_path: Path) -> None: ...

# positive (allowlist): notification command → pass
def test_systemd_notify_send_passes(tmp_path: Path) -> None: ...
def test_systemd_osascript_passes(tmp_path: Path) -> None: ...
def test_cron_slack_cli_passes(tmp_path: Path) -> None: ...
def test_cron_curl_webhook_passes(tmp_path: Path) -> None: ...

# negative: empty repo (no timer files) → pass
def test_empty_repo_passes(tmp_path: Path) -> None: ...

# additional: shlex parse failure → fail-closed
def test_malformed_quotes_rejected(tmp_path: Path) -> None: ...
```

合計 fixture 数: positive deny 5 + positive pass 4 + negative 1 + edge 1 = **11 fixtures**。

### 5.4 (削除) bash fixture runner は scope 外 (R1 F-012 adopt)

本 task では **pytest fixture (§5.3) のみ採用**、bash runner は省略。理由: SP022-T01 で 47 fixture × 95 assertion 経験、tmp_path 経由 pytest だけで shell I/O / fake repo setup を等価にカバー可、bash + pytest 並走は overkill。

### 5.5 `docs/deploy/half-yearly-drill-sop.md` (新規、半年 drill SOP)

構成 (~200-250 lines、Markdown):

```markdown
# 半年 drill scheduling SOP (ADR-00021 §14.2 #4 PGA-F-013)

最終更新: 2026-05-19 (SP022-T03)

## 1. 目的

TaskManagedAI host migration drill (Mac↔VPS / Linux↔VPS / VPS↔VPS 等) を半年 1 回手動実施するための **scheduling 通知 SOP**。本 SOP の cron / systemd timer は **通知のみ** 担当し、実際の `taskhub migrate` 等 destructive operation は **手動 approval flow** で人間オペレータが kick-off する。

## 2. CI 機械検査 (本 SOP の cron / systemd timer は本 SP-022 で確立した CI gate を通過必須)

- `scripts/ci/check_drill_timer_alert_only.sh` で systemd `.timer` / `.service` / cron entry の ExecStart / command を scan
- allowlist (notify-send / osascript / slack-cli / discord-cli / mail / sendmail / curl / echo / printf / logger) 以外は CI fail
- denylist (taskhub migrate/restore/age-rotate/backup / docker compose down / pg_* / rm -rf / dd / mkfs / kill / systemctl) は **絶対 fail**

## 3. systemd timer 構成例 (Linux / macOS Linux VM、R1 F-015 adopt)

`/etc/systemd/system/taskhub-drill-alert.timer`:
```ini
[Unit]
Description=Half-yearly host migration drill alert

[Timer]
# 毎年 1/1 と 7/1 9:00 (systemd.time(7) calendar event 形式、`Jan,Jul *-1 09:00:00` も等価)
OnCalendar=*-01,07-01 09:00:00
Persistent=true
Unit=taskhub-drill-alert.service

[Install]
WantedBy=timers.target
```

> **検証手順 (R1 F-015 adopt)**: systemd calendar expression は `systemd-analyze calendar '*-01,07-01 09:00:00'` で妥当性確認可能 (next occurrence + iterations 表示)。本 SOP の例は manually verify 済、custom 日時に変更する場合は同 command で次回起動時刻を確認すること。

`/etc/systemd/system/taskhub-drill-alert.service`:
```ini
[Unit]
Description=Half-yearly drill alert sender

[Service]
Type=oneshot
# !! allowlist 内 command のみ、taskhub migrate / restore は絶対禁止 !!
# !! shell composition (`$(...)`, `;`, `&&`, `|`, redirect 等) も禁止 !!
ExecStart=/usr/bin/slack-cli chat send --channel taskhub-ops "Half-yearly host migration drill due. See docs/deploy/half-yearly-drill-sop.md"
```

## 4. cron 構成例 (Mac)

`~/.crontab` (or `crontab -e`):
```
# 半年 drill alert (毎年 1/1 と 7/1 9:00)
0 9 1 1,7 * /usr/bin/osascript -e 'display notification "Half-yearly host migration drill due" with title "TaskManagedAI"'
0 9 1 1,7 * /usr/local/bin/slack-cli chat send --channel taskhub-ops "Half-yearly drill due"
```

## 5. 手動 approval flow (drill 実行時)

1. 通知受領 (Slack / osascript notification)
2. オペレータが `docs/deploy/half-yearly-drill-sop.md` 確認
3. approval ID 生成: `taskhub approval issue --reason "half-yearly drill 2026-07-01" --decider <human-name>`
   → output: `approval_id=drill-2026-07-01-<sha8>`
4. signed approval record 作成: `~/.taskhub/approvals/drill-2026-07-01-<sha8>.signed`
   - 内容: approval_id, decider, reason, signed_at (UTC), drill_kind (host_migration_mac_vps), signature (Ed25519 signing key、SOPS で管理)
5. drill kick-off: `taskhub migrate --target t-ohga-vps --approval-id drill-2026-07-01-<sha8> --from-automation`
   - `--from-automation` 明示で、cron / systemd 環境変数経由でない (手動シェル invoke) ことを confirm
6. drill 実行: `taskhub migrate` が approval ID + signed record verify、Tailscale 経由で backup → restore → smoke → RTO 計測
7. drill 完了報告: Slack channel に結果投稿、`~/.taskhub/drills/<date>/result.json` に記録

## 6. 異常時 escalation

- drill 完了せず → オペレータが Slack channel `#taskhub-ops` で escalation 表明
- rollback 必要 → `taskhub migrate --rollback --approval-id <id>` (T02 で実装)
- approval signature verification 失敗 → drill kick-off reject、SecretBroker audit event 発火

## 7. (planned contract for SP022-T02、本 T03 では仕様明文化のみ、R1 F-013 adopt)

> **Note**: 本 §7 は **SP022-T02 (`taskhub migrate` 自動化) で実装される planned contract**、本 SP022-T03 では SOP 内 reference として明文化のみ。normative spec / 受け入れ条件は SP022-T02 ticket に記載される。

T02 で実装される `taskhub migrate` は本 T03 SOP の手動 approval flow と整合するため、以下 invariant が **T02 implementation contract** として想定される:
- `--approval-id <id>` 必須、signed approval record `~/.taskhub/approvals/<id>.signed` の Ed25519 signature verify (Ed25519 key 管理は SOPS age 経由を T02 で決定)
- cron / systemd 環境変数 (`SYSTEMD_INVOCATION` / `CRON_INVOCATION` 等) 検出時は default deny、`--from-automation` 明示 + signed approval 両方必須
- signature verify 失敗 → exit 2 + audit event 発火 (raw secret なし、SP-004/006 SecretBroker boundary 経由)

詳細仕様 (signature algorithm 選定、approval record schema、audit event payload format 等) は **SP022-T02 ticket で確定**。本 T03 SOP は T02 完了後に正式 invariant に更新する。

## 8. 関連 ADR / docs

- ADR-00021 §3 / §8 / §14.2 #4 (Host-Portable Deployment + drill alert-only enforcement、PGA-F-013)
- ADR-00007 (External Exposure invariant、Tailscale 閉域維持)
- SP-022 §Phase G (must_ship + 追加実装ファイル)
- SP022-T02 (`taskhub migrate` 自動化、approval ID 必須化実装)
- SP022-T09 (実機 host migration drill Mac→VPS RTO≤4h PASS)
- `scripts/ci/check_drill_timer_alert_only.sh` (本 SP022-T03 で実装)
```

## 6. 検証手順 (verification before commit)

```bash
# 1. script syntax + py_compile
bash -n scripts/ci/check_drill_timer_alert_only.sh
uv run --no-sync python -m py_compile scripts/ci/_drill_timer_scanner.py

# 2. local baseline-scan (drill timer file が現 repo に不在なので skip 期待)
bash scripts/ci/check_drill_timer_alert_only.sh
# 期待: PASS (mode=baseline-scan、no timer files)

# 3. pytest deploy fixture
uv run pytest tests/deploy/test_drill_timer_alert_only.py -q
# 期待: 11 fixture passed

# 4. ruff + mypy regression (R1 F-014 adopt: scripts/ci + tests/deploy も scope に含める)
uv run ruff check backend tests scripts/ci tests/deploy
uv run mypy backend
# scripts/ci の Python helper は mypy 対象外 (既存設定で backend のみ)、ruff + py_compile + pytest で担保

# 5. SP022-T01 fixture も regression なく PASS (既存変更なし)
bash tests/scripts/test_check_framework_intake.sh 2>&1 | tail -3
# 期待: 47 fixture × 95 assertion 全 PASS
```

## 7. レビュー観点 (codex-plan-review trigger 必須)

mandatory Codex gate (codex-usage-policy.md §14.1 3+ file 横断 + ADR-00021 §14.2 #4 直接 trace):
- `codex-plan-review R1 minimum + 採否判定` 経路必須
- finding 数 + clean 状態次第で R2 / R3 追加判断 (SP022-T01 R1-R3 22 findings adopt 経験踏襲)

### 7.1 期待される review focus

1. **denylist 網羅性**: ADR-00021 §14.2 #4 で挙げられた `taskhub migrate` 以外に destructive command が追加で必要か (e.g., `pg_dropdb`、`docker volume rm`、`kubectl delete`)
2. **allowlist 過剰**: `curl` は webhook POST 用だが、`curl http://target/destroy?id=1` 等 destructive endpoint も pass する、URL allowlist + method 制限が必要か (本 task では curl 全許可で初版、tightening は post-T03)
3. **systemd / cron parse の robustness**: line continuation (`\`)、environment variable substitution (`${TASKHUB_TARGET}`)、conditional execution (`ExecStartPre`/`ExecStartPost`) 等の edge case
4. **shlex.split() の限界**: bash heredoc、subshell `$(...)`、process substitution `<(...)` で shlex は fail-closed、これが正しい挙動か
5. **diff-gate trigger**: drill timer file (`*.timer` / cron) 変更を `git diff origin/main...HEAD` で検知する logic、PR で削除されるだけのケース (`-/.timer` のみ) も trigger するか
6. **SP022-T01 既存 CI gate との干渉**: ci-smoke.yml の Framework intake check + Drill timer check + 既存 Ruff/Mypy/Pytest 順序、`fetch-depth: 0` は既に SP022-T01 で設定済
7. **`taskhub migrate --approval-id` SOP 仕様の T03/T02 境界**: 本 T03 で SOP に書く範囲と T02 で実装する範囲の明確化
8. **emergency disable repository variable**: `DRILL_TIMER_ALERT_ONLY_CHECK_DISABLED=1` で disable 時の audit 記録、SP022-T01 と同 pattern (admin only)

## 8. リスク / Rollback

| リスク | 影響 | mitigation |
|---|---|---|
| allowlist 過剰 (curl webhook 経由で destructive endpoint POST 可能) | 本 task では curl 全許可、destructive endpoint POST は denylist 不可 | post-T03 SP-022.X で URL allowlist + method 制限拡張、本 task では SOP 内で「curl は webhook POST のみ」と明文化 |
| denylist 漏れ | 新 destructive command が登場時 bypass | unknown command も `framework_intake_violation_drill_timer_alert_only_violation_unknown_command` で fail-closed (allowlist match なし即 violation)、安全側 default |
| pytest fixture が CI で flaky | tmp_path 経由なので独立性高い、flaky risk 低 | CI 上で deterministic、tmp_path は pytest 標準 |
| ADR-00021 §14.2 #4 仕様変更 | 仕様更新で本 implementation の rework | ADR 更新時に本 file 群を同期 update、SP-022.X で対応 |
| Codex review が delayed | merge 遅延 | 30 min max polling、admin merge bypass (CI billing failure 継続中、user 明示指示時) |

### Rollback 手順 (R1 F-016 adopt、3 階層に分離)

#### Tier 1: pre-merge local rollback (本 PR merge 前、開発者操作)

- `git restore` で **対象ファイル限定** に戻す (working tree 全 restore は不可、SP022-T01 と同 pattern)
- 例: `git restore scripts/ci/check_drill_timer_alert_only.sh scripts/ci/_drill_timer_scanner.py tests/deploy/`

#### Tier 2: post-merge emergency mitigation (本 PR merge 後、軽微な問題)

- **option A**: `vars.DRILL_TIMER_ALERT_ONLY_CHECK_DISABLED=1` repository variable を admin が設定 (PR diff から author 任意 disable 不可)
  - 設定すると workflow step `if:` 条件で step skip、shell defense-in-depth も skip
  - audit marker (UTC timestamp + ADR-PGA reference) が CI log に出力
  - **24h 以内に retro Pack 必須** (`docs/sprints/SP-022_framework_intake_hardening.md` `## Review` に disable 日時 / 理由 / 復旧 commit SHA 記録)
- **option B**: workflow step を revert PR で削除 (`if: false` ではなく step 自体を物理削除)
  - PR 起票 → admin merge、Tier 1 (local rollback) 経由不可な post-merge シナリオで採用

#### Tier 3: break-glass (致命的 CI gate failure、本 task 内 CI gate 自体が誤動作)

- `scripts/ci/check_drill_timer_alert_only.sh` を **`exit 0` skeleton に置換** (admin 緊急操作、PR 経由)
- SP-022.X で再実装、retro Pack に rollback rationale + 復旧計画を記録
- ADR-00021 §14.2 #4 rollback として、SP-022 全体 status を `partial_completed` に変更 (T03 のみ defer 扱い)

通常運用では **Tier 1 > Tier 2 option A > Tier 2 option B > Tier 3** の順序で escalation。`exit 0` skeleton は last-resort break-glass のみ。

## 9. commit 戦略: single commit に集約 (SP022-T01 PR #70 pattern 踏襲)

本 PR は **single commit** にまとめる:

| step | file | 種別 |
|---|---|---|
| 1 | `scripts/ci/check_drill_timer_alert_only.sh` | 新規 |
| 2 | `scripts/ci/_drill_timer_scanner.py` | 新規 (Python helper) |
| 3 | `tests/deploy/__init__.py` + `tests/deploy/test_drill_timer_alert_only.py` | 新規 (11 fixtures) |
| 4 | `docs/deploy/half-yearly-drill-sop.md` | 新規 (~200 行 SOP) |
| 5 | `.github/workflows/ci-smoke.yml` | modify (Drill timer check step 追加 + `env.DRILL_TIMER_ALERT_ONLY_CHECK_DISABLED` repository variable 参照) |
| 6 | `docs/sprints/SP-022_framework_intake_hardening.md` | modify (`## Review` に SP022-T03 完了記録) |
| 7 | `.claude/plans/sp022-t03-drill-scheduling-sop.md` | 本計画、commit に含める |

verify 失敗時は **全件 rollback** (`git restore .` で working tree clean → 再 implementation)。**部分 commit は禁止** (SP022-T01 pattern)。

## 10. PR workflow (本 session 確立 pattern 踏襲)

1. ✅ branch `worktree-sp022-t03-drill-scheduling-sop` 作成済 (origin/main 起点)
2. ⏳ 計画書 draft (本 file) 作成
3. ⏳ `Skill(skill="codex-plan-review", args=".claude/plans/sp022-t03-drill-scheduling-sop.md")` 起動 (mandatory gate、R1 minimum)
4. ⏳ findings 採否判定 + 計画書反映 → R2 / R3 必要なら polish (SP022-T01 22 findings adopt 経験踏襲)
5. ⏳ 実装 (Section 9 sequence)
6. ⏳ pre-commit verification (Section 6)
7. ⏳ commit + push + PR 起票 (`gh pr create`)
8. ⏳ Codex auto-review polling (`codex_pr_full_review.sh` baseline 内容確認 + delta polling + 30 min max + multi-round R1-RN polish)
9. ⏳ 採否判定 3 分類 + multi-round polish (R{N} clean まで or diminishing returns 確定で停止)
10. ⏳ user merge or admin merge bypass (CI billing failure 継続中、user 明示指示時)

## 11. 受け入れ条件 (本 task の DoD)

- [ ] `scripts/ci/check_drill_timer_alert_only.sh` が diff-gate / baseline-scan 2 mode で systemd `.timer` / `.service` + cron file の ExecStart / command を scan する
- [ ] denylist (taskhub destructive / docker compose down / pg_* / rm -rf / dd / mkfs / kill / systemctl) を即 violation 検出
- [ ] allowlist (notify-send / osascript / slack-cli / discord-cli / mail / sendmail / curl / echo / printf / logger) は pass
- [ ] allowlist match なし AND denylist match なしも fail-closed (`unknown_command` violation)
- [ ] `scripts/ci/_drill_timer_scanner.py` Python 標準のみで実装 (Node/rg 不要、SP022-T01 同 pattern)
- [ ] `tests/deploy/test_drill_timer_alert_only.py` の **11 fixture 全 PASS** (positive deny 5 + positive pass 4 + negative 1 + edge 1)
- [ ] `.github/workflows/ci-smoke.yml` の `backend-quality` job に "Drill timer alert-only check" step 追加 + `env.DRILL_TIMER_ALERT_ONLY_CHECK_DISABLED` repository variable 参照
- [ ] `docs/deploy/half-yearly-drill-sop.md` ~200 行 SOP で systemd timer 構成例 + cron 構成例 + 手動 approval flow + signed approval record + 異常時 escalation + (任意) T02 仕様明文化
- [ ] `docs/sprints/SP-022_framework_intake_hardening.md` `## Review` 章に SP022-T03 完了記録追加 + Phase G PGA-F-013 trace marker
- [ ] codex-plan-review R{N} clean (CRITICAL=0 + HIGH ≤ 2)
- [ ] PR Codex auto-review R{N} clean (採否判定 3 分類 + multi-round polish 後)
- [ ] SP022-T01 既存 47 fixture × 95 assertion 全 PASS (regression なし)

## 12. 関連 ADR / Sprint Pack / Rules

- ADR-00021 §3 / §8 / §14.2 #4 (Host-Portable Deployment + PGA-F-013) — 本 task の正本
- ADR-00007 (External Exposure invariant) — 半年 drill 中の Tailscale 閉域維持必須
- ADR-00026 (PITR drill) — 既存 drill_kind pattern 参考 (`scripts/pitr_drill.py`)
- SP-022_framework_intake_hardening.md Phase G PGA-F-013 — 本 task scope
- SP022-T02 (`taskhub migrate` 自動化) — `--approval-id` 実装は別 PR、本 T03 で SOP 内仕様明文化のみ
- SP022-T09 (実機 host migration drill) — 本 T03 SOP を実機 drill 実施時に使用
- `.claude/rules/codex-usage-policy.md` §14.1 — mandatory Codex gate trigger (3+ file 横断)
- `.claude/rules/sprint-pack-adr-gate.md` §10 break-glass — 該当なし (実装着手前 ADR-00021 既 accepted)
- SP022-T01 PR #70 確立 pattern — 本 T03 で踏襲 (2 mode / emergency disable / `uv run --no-sync` / Python scanner / commit 戦略 / PR workflow)

## 13. R1 codex-plan-review findings 採否判定 ledger (本 plan polish 起源)

R1 (Phase A 構造レビュー) で計 16 finding (HIGH=5, MEDIUM=8, LOW=3)、**全件 adopt** 反映済。

| ID | severity | symptom (50 字) | 反映先 |
|---|---|---|---|
| F-001 | HIGH | curl 全許可で webhook destructive endpoint POST bypass | §4.3 curl を allowlist から削除、SOP では slack-cli/discord-cli/mail に寄せる |
| F-002 | HIGH | scanner `--paths` interface 未定義 | §4.4.1 `--paths-from-stdin` 追加、shell から NUL 区切りで渡す |
| F-003 | HIGH | systemd `.timer` paired `.service` resolution 不在 | §4.1.1 `[Timer] Unit=` parse + 同名 fallback + fail-closed |
| F-004 | HIGH | `ExecStartPre`/`Post`/`Reload`/`Stop` scan 漏れ | §4.2 全 Exec*= directive scan、reason_code に directive 名 evidence |
| F-005 | HIGH | shell composition (`$()`, `;`, `&&`, `\|`, redirect) bypass | §4.5 新 `_check_shell_composition` regex、allowlist match 前に最優先 check |
| F-006 | MEDIUM | denylist 拡張 (docker volume rm、kubectl delete、redis-cli flushall、shutdown 等) | §4.3 denylist 拡張、defense-in-depth 明記 |
| F-007 | MEDIUM | scanner repo 全 `.service` scan で legitimate service 誤検出 | §4.1 scope を `*drill*` / `docs/deploy/**` / `deploy/**` / `ops/**` 限定 |
| F-008 | MEDIUM | cron parser robustness (5/6-field, @daily macro, env var, comment, %) | §4.1.2 robust parser spec、user crontab / cron.d 分離判定 |
| F-009 | MEDIUM | reason_code naming 揺れ (3 種混在) | §4.2.1 `framework_intake_violation_drill_timer_alert_only_*` family 統一 |
| F-010 | MEDIUM | emergency disable の `if:` 条件・audit marker・PR author 上書き不可保証 不完全 | §4.4.4 `if: vars.DRILL_TIMER_ALERT_ONLY_CHECK_DISABLED != '1'` 明示、二重 check、audit marker format |
| F-011 | MEDIUM | shell mode determination / fork PR / shallow / origin/main 不在 / delete-only 仕様化不在 | §4.4.1-§4.4.3 で各 case 仕様化 |
| F-012 | MEDIUM | bash fixture runner scope 揺れ (must_ship vs 省略) | §3.1 / §5.4 で **scope 外** に統一、pytest fixture のみ採用 |
| F-013 | MEDIUM | SOP の T02 関連部分が normative spec化、T03/T02 境界曖昧 | §7 (SOP) を `planned contract for SP022-T02` と明示 |
| F-014 | LOW | verification scope に `scripts/ci tests/deploy` 不在 | §6 検証手順に `ruff check backend tests scripts/ci tests/deploy` 追加 |
| F-015 | LOW | SOP systemd `OnCalendar` expression syntax 検証手順不在 | §5.5 SOP で `systemd-analyze calendar` 検証手順追加 |
| F-016 | LOW | rollback 手順が粗い (`git restore .` + `exit 0` skeleton 並走) | §8 Rollback を 3 階層 (Tier 1 pre-merge / Tier 2 post-merge / Tier 3 break-glass) に分離 |

reject: 0 / defer: 0 / 全件 adopt。

R1 Readiness Gate: 反映前 = BLOCKED (HIGH=5 > 2)、反映後 = READY 期待 (R2 で確認)。

## 14. R2 codex-plan-review findings 採否判定 ledger

R2 (Phase B 実装可能性レビュー、HIGH+ 限定) で計 3 finding (HIGH=3)、**全件 adopt** 反映済。

| ID | severity | symptom (50 字) | 反映先 |
|---|---|---|---|
| R2-F-001 | HIGH | `git diff -z` の NUL byte を bash `$()` が保持できず diff-gate split 不能 | §4.4.1 shell wrapper を **temp file 経由** に変更、scanner interface も `--paths-from-file=<path>` に変更 |
| R2-F-002 | HIGH | shell composition regex で 単独 `<` (input redirect) 検出漏れ、`mail < secret_file` bypass | §4.5 regex を `<+` で 1 個以上 match に拡張、negative fixture 追加 |
| R2-F-003 | HIGH | `rsplit('/')` basename 化 allowlist で `/tmp/slack-cli` / `PATH=./ops/bin` 経路で arbitrary binary bypass | §4.3.1 `TRUSTED_PATH_PREFIXES` 限定 (path spoofing check)、§4.3.2 cron env line `PATH=/SHELL=/BASH_ENV=` 等 fail-closed |

R2 Readiness Gate: 反映前 = BLOCKED (HIGH=3 > 2)、反映後 = READY 期待 (R3 で CRITICAL final 確認)。

## 15. R3 codex-plan-review (Phase B 最終確認、CRITICAL のみ)

R3 で **CRITICAL=0 件** (findings:[] empty)、致命的論点なし → Readiness Gate **READY 確定**、実装フェーズに移行可能。

R1+R2+R3 累計: **19 findings 全件 adopt** (16+3+0)、R3 で round_max=3 到達 + CRITICAL clean、実装着手 OK。
