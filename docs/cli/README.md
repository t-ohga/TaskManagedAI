---
id: DOC-CLI-README
title: "TaskManagedAI CLI 使用/設計 (tm canonical + credential source + ContextResolver + capability matrix)"
type: design_doc
status: accepted
revision: R2
created_at: "2026-05-15"
updated_at: "2026-05-24"
source_plan_section: "docs/設計検討/修正まとめ統合計画.md §5 QL-F + §3.2 P-05 + §3.2 P-06"
landing_sprint: "SP-016_ui_cli_parity (既存) + ADR-00015 update + ADR-00024 (proposed、project auto-discovery placeholder)"
adr_gate_criteria_trigger:
  - "#3 (API 契約 / event schema、CLI capability matrix で expose する操作)"
  - "#6 (Secrets 管理、CLI 経由 secret_access)"
  - "#7 (外部公開、CLI バイナリ配布)"
related_documents:
  - "../adr/00015_ui_cli_parity.md"
  - "../sprints/SP-016_ui_cli_parity.md"
  - "../sprints/SP-012_p0_acceptance.md (`tm` / `taskhub` 表記)"
  - "../設計検討/修正まとめ統合計画.md §3.2 P-05 + P-06 (CLI canonical 反転 / ContextResolver)"
risks:
  - "将来 `tm` から `tmai` へ反転する場合の表記 drift (ADR-00015/SP-016/SP-012/本 doc/test file の一括更新が必要)"
  - "ContextResolver の ambiguous resolution で mutating command が実行される (fail-closed 違反)"
  - "ADR-00024 (project auto-discovery、QL-G で起票予定) と memory boundary が CLI context 経路で混入 (deny-by-default 違反)"
---

# TaskManagedAI CLI

## 0. このドキュメントの扱い

本 doc は SP-016 batch 0c/0d 以降の `tm` project-user CLI の使用手順と設計境界の source-of-truth。R1 は doc-only future spec だったが、R2 では実装済み CLI (`./cli` package + root `uv run tm`) と同期する。

本 doc は:

- 修正まとめ統合計画 §5 QL-F の write scope (`ADR-00015 update + SP-016 + 本 docs/cli/README.md + ADR-00024 placeholder`) の core spec を継承
- CLI canonical `tm`、ContextResolver state machine、13 capability matrix、mode matrix、ambiguous mutating command fail-closed acceptance を doc 化
- **U-04 (CLI canonical 反転 `tm`→`tmai` 採否) は 2026-05-24 に A: `tm` canonical 維持で確定**。`tmai` は将来 namespace 衝突時の fallback 名としてのみ残す
- `tm` の install smoke、profile、credential source、output format、disabled memory command を利用手順として固定
- ADR-00024 (project auto-discovery + memory boundary) placeholder を SP-016 で reserve、QL-G run で実 ADR 起票

### 0.1 Install / Smoke

```bash
uv tool install ./cli
tm --version

# repo root からの開発用 smoke
uv run tm --version
uv run --project cli tm --help
```

### 0.2 Runtime Token Boundary

CLI は raw operation token を profile file に保存しない。runtime token は次のいずれかから実行時にのみ解決する:

| source | profile / env | 備考 |
|---|---|---|
| explicit flag | `--operation-token <runtime-token>` | debugging / one-shot のみ。shell history 露出に注意 |
| process env | `TASKMANAGEDAI_OPERATION_TOKEN=<runtime-token>` | default runtime source |
| profile env ref | `auth_method: env` + `operation_token_env: TM_PROFILE_OPERATION_TOKEN` | profile には env var 名だけ保存 |
| keyring | `auth_method: keyring` + `refresh_credential_ref: taskmanagedai/default` | `service/account` ref。CLI package は `keyring` dependency を含む |
| SOPS | `auth_method: sops` + `refresh_credential_ref: ~/.taskmanagedai/profile.enc.json#cli.operation_token` | decrypted JSON の nested string を読む |

`auth_method: plain` は CLI profile loader で fail-closed。`operation_token` / `raw_operation_token` / `access_token` 等の raw token field は selected profile だけでなく inactive profile 内でも reject する。

Backend は CLI request の operation token を `X-TaskManagedAI-Operation-Token` として受け取り、`api_capability_tokens.allowed_actions` と project scope に照合する。action / project mismatch は `api_capability_token_scope_mismatch` として ref-only audit に残し、token を SecretBroker capability token として redeem する経路は `secret_capability_denied:not_found` で拒否する。

13 capability の UI/CLI parity contract は `tests/parity/test_ui_cli_parity.py` が正本。CLI が生成する method / path / capability、backend live/planned route、UI reference、DB row、audit event expectation を同一 matrix で固定する。

### 0.3 Network Boundary

`backend_url` は closed-network 前提で fail-closed 検証する。CLI profile / env override で許可する host は次だけ:

- `localhost` / `127.0.0.1` / loopback address
- Tailscale CGNAT `100.64.0.0/10`
- `*.ts.net`

通常の public hostname (`example.com`) や public IP (`8.8.8.8` 等) は CLI 起動時に reject する。Tailscale grants `tag:taskhub-cli` の実 config 変更は ADR-00007 の外部公開設定 gate として別 diff / rollback 明示で扱う。

### 0.4 Profile Examples

JSON:

```json
{
  "profiles": {
    "default": {
      "backend_url": "https://taskhub.example.ts.net",
      "default_project_id": "00000000-0000-4000-8000-000000000000",
      "auth_method": "keyring",
      "refresh_credential_ref": "taskmanagedai/default"
    }
  }
}
```

YAML:

```yaml
profiles:
  default:
    backend_url: https://taskhub.example.ts.net
    default_project_id: 00000000-0000-4000-8000-000000000000
    auth_method: sops
    refresh_credential_ref: ~/.taskmanagedai/profile.enc.json#cli.operation_token
```

### 0.5 Command / Output Smoke

```bash
TASKMANAGEDAI_PROJECT_ID=<project_id> \
TASKMANAGEDAI_OPERATION_TOKEN=<runtime-token> \
tm --json ticket list

tm --project <project_id> --yaml run show <agent_run_id>
tm --agent-mode ticket create --slug example --title "Example"  # fail-closed
tm memory search "anything"                                     # disabled until SP-018
```

Output formatters (`--json` / `--yaml` / human default) redact secret-shaped keys such as `operation_token`, `secret_value`, `api_key`, and `credential`. Identifier fields like `token_id` remain visible.

## 1. 不変条件 (本 CLI 設計で破ってはならない)

| # | 不変条件 | 根拠 |
|---:|---|---|
| 1 | CLI ContextResolver の **ambiguous / unresolved 状態では mutating command を実行しない** (fail-closed) | `.claude/CLAUDE.md §2 #10` (cross-project memory boundary deny-by-default) の延長、CLI 経由でも同 invariant |
| 2 | CLI canonical は `tm`。将来 `tmai` へ反転する場合のみ、**ADR-00015 + SP-016 + SP-012 + 本 doc + CLI test file** を **同一 PR で doc-only 一括更新** (実装 file の更新は反転実装 Sprint Pack accepted 後の別 run) | R29 plan §5 QL-F 重要制約 + 2026-05-24 U-04 decision |
| 3 | `taskhub` (host / admin) と `tm` (project user) の **CLI 境界明示**、admin CLI から project mutating command を invoke する path は restricted | R29 plan §3.2 P-05 + R5 F-R5-002 反映 |
| 4 | CLI 経由の `secret_access` / `merge` / `deploy` / `provider_call` は **全 autonomy_level で human approval 必須** (ADR-00025 §不変条件 #1 と整合) | ADR-00025 §10.3 不変条件 #1 |
| 5 | CLI memory backend (history / preference / cache) と project / repo context の **boundary 物理分離** (cross-project retrieval deny-by-default) | ADR-00024 候補 (QL-G で起票)、`.claude/CLAUDE.md §2 #10` |
| 6 | R2 以降は実装済み CLI と同期する。将来の large behavior change は SP-016 / ADR-00015 / 本 doc / tests を同一 PR で更新 | R29 plan §5 QL-F 重要制約、SP-016 batch 0c/0d |

## 2. CLI canonical の決定

R29 plan P-05 で提案された CLI canonical `tm` → `tmai` 反転案を比較し、2026-05-24 SP-016 kickoff blocker closure で **A: `tm` canonical 維持**を採用した。

| 選択肢 | 判定 | 概要 | 理由 |
|---|---|---|---|
| A: `tm` canonical | **adopt** | 既存 `tm` をそのまま使う、ADR-00015 / SP-016 / SP-012 が現状の `tm` 表記のまま | reverse 不要、既存 SP / ADR の wording 修正不要。`which -a tm` / Homebrew exact search / local bin check で衝突なし |
| B: `tmai` canonical | reject for SP-016 | `tm` → `tmai` に rename、既存 `tm` alias を soft deprecation (1 sprint period) | semantic alignment は強いが、現時点では rename cost と docs/test drift risk が上回る |

`tmai` は将来 package namespace 衝突または配布 channel 側の予約問題が発生した場合の fallback 名としてのみ残す。SP-016 実装では `tm` のみを canonical entry point とする。

## 3. ContextResolver state machine

R29 plan P-06 で提案された ContextResolver state machine spec (CLI 起動時の project context 解決順序):

```
Entry: CLI command invocation (e.g., `tm ticket list` or `tm decision approve <id>`)

State 1: explicit_arg
  - --project <project_id> 等 explicit CLI flag が指定されている → resolve_complete
  - 指定なし → next State 2

State 2: env
  - `TASKMANAGEDAI_PROJECT_ID` 等 env var が設定されている → resolve_complete
  - 設定なし → next State 3

State 3: cwd_git_remote
  - 現在 cwd の git remote URL から project_id を auto-discovery
  - 解決 success (一意な project が見つかった) → resolve_complete
  - 解決 failure (no remote / multiple project candidates / auth error) → next State 4

State 4: profile
  - user profile (`~/.taskmanagedai/profile.yaml`) の `default_project_id` が設定されている → resolve_complete
  - 設定なし → next State 5

State 5: interactive_or_fail
  - terminal が interactive (stdout=tty) → interactive prompt で user に project 選択を要求
  - terminal が non-interactive (CI / pipe) → **fail-closed**
  - non-interactive で mutating command (task_write / repo_write / pr_open / secret_access 等) なら fail-closed: 「ambiguous project, specify --project explicitly」
  - non-interactive で read-only command (task list / status show 等) なら fall-through with empty project context warning

resolve_complete: project_id 確定、command 実行
fail-closed: error exit (CLI exit code 2)、command 実行しない
```

### 3.1 不変条件 (ContextResolver fail-closed)

- **mutating command + ambiguous/unresolved context = fail-closed**: `task_write` / `repo_write` / `pr_open` / `secret_access` / `merge` / `deploy` / `provider_call` 全 7 action_class で、ContextResolver が State 5 で interactive fallback できない場合は fail-closed (本 doc §1 #1 不変条件)
- **read-only command + unresolved context = best-effort warning**: read-only operation は project context なしでも fall-through 可能、ただし「project_id 未解決」warning を stderr に出力

## 4. 13 capability matrix (CLI 経由 capability の一覧)

P0 で CLI から呼べる capability を 13 種に固定する:

| # | capability | command 例 | action_class | autonomy_level human approval |
|---:|---|---|---|---|
| 1 | task_list | `tm ticket list` | (read-only、no action_class) | 不要 |
| 2 | task_show | `tm ticket show <id>` | (read-only) | 不要 |
| 3 | task_write | `tm ticket update <id> --acceptance-criteria "..."` | task_write | L0=approval / L1-L3=auto-allow (low_risk_profile 通過時) |
| 4 | task_create | `tm ticket create --title "..."` | task_write | 同上 |
| 5 | approval_list | `tm approval list --status pending` | (read-only) | 不要 |
| 6 | approval_decide | `tm approval approve <id> --rationale "..."` (decider human-only) | (approval flow 自体、action_class なし) | **全 level で human only** |
| 7 | repo_status | `tm repo status` | (read-only) | 不要 |
| 8 | repo_push | `tm repo push --branch ...` | repo_write | L0/L1=approval / L2-L3=auto-allow (docs only diff / file count <= 3) |
| 9 | pr_open | `tm pr open --base main --head feat/foo --draft` | pr_open | L0-L2=approval / L3=auto-allow (Draft PR + low_risk_profile、ただし SecretBroker capability 内包は除外) |
| 10 | secret_resolve | `tm secret use <secret_ref>` | secret_access | **全 level で human approval 必須** (ADR-00025 §不変条件 #1) |
| 11 | run_show | `tm run show <agent_run_id>` | (read-only) | 不要 |
| 12 | run_cancel | `tm run cancel <agent_run_id>` | (cancel action、approval なしで OK if requester==operator) | requester==operator なら approval 不要、それ以外は approval 必須 |
| 13 | provider_call | `tm provider call --provider openai --feature chat_completion ...` | provider_call | **全 level で human approval 必須** (ADR-00025 §不変条件 #1) |

merge / deploy は P0 deny (ADR-00009 §採用案準拠)、CLI からも invoke 不可。

### 4.1 Non-parity command policy

SP-016 の parity contract は上記 13 capability のみを対象にする。過去の Sprint Pack 草案にあった `message` / `audit` / `export` / `sprint` command は次の扱いで drift を解消する。

| command | SP-016 扱い | parity contract |
|---|---|---|
| `message` | SP-015 backend を直接 mutate する project-user CLI は SP-016 batch 0 scope 外。将来追加する場合は別 Sprint / ADR update で 13 matrix を拡張 | 含めない |
| `audit` | read-only helper としてのみ許可可能。raw payload / secret / message body は出力しない | 含めない |
| `export` | read-only helper としてのみ許可可能。raw secret / capability token / audit raw body は出力しない | 含めない |
| `sprint` | `taskhub` host/admin CLI scope。project-user CLI `tm` からは expose しない | 含めない |

## 5. mode matrix (interactive / non-interactive / agent-mode)

CLI 実行 mode を 3 種に分離:

| mode | 条件 | mutating command の挙動 |
|---|---|---|
| interactive | stdout=tty AND --no-interactive 不指定 | ContextResolver State 5 で prompt 表示可能、approval 要 command は interactive confirm |
| non-interactive | stdout=pipe OR --no-interactive 指定 (CI / script context) | ContextResolver State 5 で fail-closed、approval 要 command も fail-closed (CI script で approval を簡略化させない) |
| agent-mode | --agent-mode 指定 (AI agent からの subprocess invocation) | 全 mutating command が **fail-closed**、agent からの CLI invocation は直接 mutation 経路を作らない (AI 出力直結禁止 invariant `.claude/CLAUDE.md §2 #1` の延長)、AI agent は AgentRun 経由でのみ mutation を要求する |

## 6. ambiguous mutating command fail-closed acceptance

本 doc §3.1 + §5 の延長として、以下の fail-closed acceptance spec を SP-016 acceptance に cross-reference:

- ContextResolver で project_id が **未解決** (State 1-4 全 fail) + mutating command 指定時 → **fail-closed**、CLI exit code 2、stderr に「ambiguous project context, specify --project explicitly」
- ContextResolver で project_id が **複数候補** (cwd git remote が multi-project の monorepo) + mutating command 指定時 → **fail-closed**、stderr に候補一覧 + 「specify --project explicitly」
- agent-mode で mutating command 指定時 → **fail-closed** (上記 §5)
- non-interactive + approval 要 command (capability matrix #6 / #10 / #13 等) → **fail-closed** (CI script で approval を簡略化させない)

## 7. taskhub host/admin CLI 境界

`taskhub` (host / admin) と `tm` (project user) の CLI 境界:

| CLI | scope | 想定 user | mutating command |
|---|---|---|---|
| `taskhub` | host / admin operation (Sprint Pack / ADR / tenant 設定 / SOPS rotation 等) | host admin (個人運用の場合 user 自身、tenant 運用の場合 admin role) | admin scope (`tenant_create` / `sprint_pack_admin_close` / `sops_rotate` 等)、project mutating command (`task_write` / `repo_write` 等) は **invoke 不可** |
| `tm` | project user operation (ticket / approval / repo / agent run / provider 等) | project user | 上記 13 capability matrix のみ、admin scope は **invoke 不可** |

`taskhub` 経由で project mutating command を直接 invoke する path は **restricted** (本 doc §1 #3 不変条件)。

## 8. CLI rename guard

U-04 は A: `tm` canonical 維持で確定したため、SP-016 kickoff では CLI test file rename は不要。将来 `tmai` へ反転する場合のみ、同一 PR 一括更新対象は次の通り:

- ADR-00015 update (canonical `tm`→`tmai` decision + 反転実装 Sprint Pack の reference)
- SP-016_ui_cli_parity (capability matrix table の `tm` → `tmai` 一括)
- SP-012_p0_acceptance (`tm` / `taskhub` 表記の整合)
- 本 docs/cli/README.md (canonical `tmai` 全置換)
- `taskmanagedai-cli/tests/**/*.test.ts` (CLI test file の `tm` → `tmai` 一括 rename + alias deprecation test 追加)

test file 更新は反転実装 Sprint Pack accepted 後の別 run。SP-016 batch 0 では `tm` canonical tests のみ追加する。

## 9. ADR-00024 placeholder (project auto-discovery memory boundary)

SP-016 で `<!-- ADR-00024 placeholder -->` marker を置く位置を spec:

- SP-016 §設計判断 / §関連 ADR で「project auto-discovery + memory boundary の deny-by-default は ADR-00024 (proposed、QL-G で起票予定) で扱う」と明示
- ADR-00024 実起票は QL-G run、SP-016 placeholder は marker のみで本 QL-F run では実 ADR 起票しない (本 doc §1 #5 不変条件)

## 10. QL-D 教訓適用

R1 では `.claude/CLAUDE.md §6.5.0` (PR #14 で追加) の **「doc-only future spec と code 変更の品質追求は別軸」教訓** を適用し、CLI canonical `tm` + ContextResolver state machine + 13 capability matrix + mode matrix + fail-closed acceptance + taskhub host/admin 境界 + ADR-00024 placeholder spec を固定した。

R2 では SP-016 batch 0c/0d の実装を取り込み、usage docs と implementation surface を同期した。将来 `tmai` 反転を採用する場合のみ、別 Sprint Pack で再議論する。

## 11. 関連 ADR / Sprint Pack

- ADR-00015 (UI/CLI parity、accepted): CLI canonical `tm` + ContextResolver state machine + api_capability_tokens DDL / lifecycle を固定
- ADR-00024 (project auto-discovery + memory boundary、proposed、QL-G で起票): 本 doc §1 #5 + §9 で placeholder reference
- ADR-00025 (autonomy policy profiles、proposed、QL-B PR #12 で起票済): 本 doc §4 capability matrix の autonomy_level column と整合
- SP-016_ui_cli_parity (既存): 本 doc §4 13 capability matrix + §4.1 non-parity command policy + §7 taskhub 境界を cross-reference
- SP-012_p0_acceptance: `tm` / `taskhub` 表記は現状維持。将来 `tmai` 反転時のみ同一 PR 更新対象

## 12. 関連資料

- `docs/設計検討/修正まとめ統合計画.md §5 QL-F` (R29 plan、本 doc の source)
- `docs/設計検討/修正まとめ統合計画.md §3.2 P-05 + P-06` (CLI canonical 反転 + ContextResolver state machine)
- `.claude/CLAUDE.md §6.5.0` (R1 doc-only spec と code 変更の品質追求は別軸、本 doc R2 では実装同期)
