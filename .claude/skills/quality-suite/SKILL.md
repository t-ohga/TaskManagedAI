---
name: quality-suite
description: "TaskManagedAI の typecheck/lint/test/contract/Provider/SecretBroker/AgentRun/runner 品質 gate。Triggers: quality-suite, 品質確認"
when_to_use: |
  実装後、PR 前、Sprint Exit 前に型、lint、unit、contract、state machine、Provider、SecretBroker、runner contract を一括確認する時。
  トリガーフレーズ: '品質確認', 'quality-suite で', 'commit 前確認', 'Sprint 品質 gate'
argument-hint: "[--target=backend|frontend|both] [--scope=changed|all]"
allowed-tools: Skill Agent Bash Read Edit Write AskUserQuestion
---

# quality-suite — 品質確認 pipeline

## 目的

TaskManagedAI の変更が型安全、lint、unit / contract test、AgentRun 状態機械、Provider Compliance、SecretBroker contract、runner contract を満たすかを集約判定する。

この suite は Main Agent orchestration 用である。専門 Skill / Agent の呼び出しは Main Agent が行い、未実装の Batch 2 skill は Bash fallback または WARN として扱う。

## 必読資料

- `.claude/rules/core.md`
- `.claude/rules/testing.md`
- `.claude/rules/provider-compliance.md`
- `.claude/rules/secretbroker-boundary.md`
- `.claude/rules/agentrun-state-machine.md`
- `.claude/reference/dev-commands.md`
- `.claude/reference/hard-gates-and-kpis.md`
- `.claude/reference/provider-compliance-matrix.md`
- `.claude/reference/secretbroker-contract.md`
- `.claude/reference/db-schema-notes.md`
- `.claude/agents/taskmanagedai/provider-compliance-reviewer.md`
- `.claude/agents/taskmanagedai/actor-binding-reviewer.md`
- `.claude/agents/taskmanagedai/agentrun-state-reviewer.md`

## Main Agent への指示

各 Step を PASS/WARN/BLOCK で記録し、最後に集約 verdict を出す。`--scope=changed` では変更ファイルに対応する最小コマンドを優先し、`--scope=all` では `.claude/reference/dev-commands.md` の Local Full Check に近い範囲まで広げる。

## Step 0: 状態初期化

### Shell Prelude

```bash
# === TaskManagedAI Shell Prelude (SUITE_NAME=quality-suite) ===
SUITE_NAME="quality-suite"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
SESSION_ID="${CLAUDE_SESSION_ID:-fallback-$(date +%s)}"
STATE_DIR="$HOME/.claude/local/${SUITE_NAME}-state"
RESULTS_DIR="$HOME/.claude/local/${SUITE_NAME}-results/${SESSION_ID}"
mkdir -p "$STATE_DIR" "$RESULTS_DIR"

TARGET="$(printf '%s\n' "$ARGUMENTS" | grep -oE -- '--target=(backend|frontend|both)' | sed 's/--target=//' | head -1)"
SCOPE="$(printf '%s\n' "$ARGUMENTS" | grep -oE -- '--scope=(changed|all)' | sed 's/--scope=//' | head -1)"
TARGET="${TARGET:-both}"
SCOPE="${SCOPE:-changed}"

DRY_RUN_MODE="$(printf '%s\n' "$ARGUMENTS" | grep -oE -- '--dry-run[= ][^ ]+' | sed -E 's/--dry-run[= ]//' | head -1 || true)"
case "${DRY_RUN_MODE:-false}" in
  false|"") DRY_RUN=false ;;
  shallow|expanded) DRY_RUN=true ;;
  *) echo "ERROR: --dry-run must be shallow|expanded" >&2; exit 1 ;;
esac

git status --short > "$RESULTS_DIR/git-status.txt"
git diff --name-only > "$RESULTS_DIR/changed-files.txt"
```

## Step 1: Typecheck / lint

Main Agent は Batch 2 skill が存在する場合は次を呼ぶ。

```text
Skill(
  skill="quality-type-safety",
  args="--target=<backend|frontend|both> --scope=<changed|all>"
)
```

未実装の場合は Bash fallback を使う。

Backend fallback:

```bash
uv run ruff check backend tests
uv run mypy backend
```

Frontend fallback:

```bash
pnpm typecheck
pnpm lint
```

判定:

- 型エラー、lint error、`any` / `type: ignore` / broad suppression の新規混入は BLOCK。
- ツール未整備で実行不能の場合は WARN とし、代替確認と residual risk を記録する。
- 高リスク境界の型 drift は BLOCK。

## Step 2: Unit / contract / coverage

Main Agent は Batch 2 skill が存在する場合は次を呼ぶ。

```text
Skill(
  skill="quality-test-coverage",
  args="--target=<backend|frontend|both> --scope=<changed|all>"
)
```

必要に応じて Batch 2 skill `testing-patterns` を参照し、弱い assertion を検出する。

Fallback commands:

```bash
uv run pytest
pnpm test
```

対象別 contract:

- API contract: FastAPI request / response / OpenAPI drift。
- DB contract: tenant / project negative test。
- Provider contract: missing payload deny、Matrix row deny、preflight deny。
- SecretBroker contract: atomic claim、one-time redeem、mismatch deny。
- Runner contract: forbidden path、dangerous command、resource cap。
- Eval contract: fixture ID / dataset version metadata。

## Step 3: AgentRun state machine

Main Agent は `agentrun-state-reviewer` agent を起動する。

```text
Agent(
  subagent_type="agentrun-state-reviewer",
  prompt="変更範囲が AgentRun 16 状態、blocked サブ 3、terminal state、provider result mapping、ContextSnapshot 10 カラム、AgentRunEvent ordering を壊していないか確認してください。"
)
```

可能なら次の test を実行する。

```bash
uv run pytest backend/tests/agentrun/test_state_machine.py
```

BLOCK 条件:

- 16 状態の増減や alias 追加。
- `blocked_reason` を status と混同。
- terminal state から resume / retry 可能。
- ContextSnapshot 10 カラム欠落。
- status update と AgentRunEvent append の transaction 不整合。

## Step 4: Provider Compliance

Main Agent は `provider-compliance-audit` skill と `provider-compliance-reviewer` agent を使う。

```text
Skill(
  skill="provider-compliance-audit",
  args="config/provider_compliance.toml <optional call sites>"
)
```

```text
Agent(
  subagent_type="provider-compliance-reviewer",
  prompt="Provider Compliance Matrix と provider call sites を確認してください。payload_data_class、allowed_data_class、ordinal、conditional ZDR、training_use、preflight、audit payload を重点確認してください。"
)
```

BLOCK 条件:

- `payload_data_class` 未設定を allow。
- `allowed_data_class` を caller 入力として受ける。
- ordinal が `public < internal < confidential < pii` 以外。
- `training_use != no` で internal 以上送信経路がある。
- unverified / conditional ZDR を fail-closed にしていない。

## Step 5: SecretBroker / actor binding

Main Agent は `actor-binding-reviewer` agent を起動する。

```text
Agent(
  subagent_type="actor-binding-reviewer",
  prompt="SecretBroker capability token、atomic claim、OperationContext fingerprint、actor/principal、approval self-approval、audit event を確認してください。"
)
```

可能なら次を実行する。

```bash
uv run pytest backend/tests/secrets/test_atomic_claim.py
```

BLOCK 条件:

- redeem が check -> execute -> mark used。
- raw secret、token、canary raw value が DB / log / artifact / audit に出る。
- actor / run / expected_request_fingerprint / requested_operation が同一 claim にない。
- self-approval が可能。

## Step 6: Runner / tool contract

確認対象:

- `tool_mutating_gateway_stub` は P0 deny-only。
- `runner_mutation_gateway` は policy / approval / forbidden path / command gate 後のみ patch 適用。
- forbidden path: `.env`, `.git/config`, secrets, high-risk workflow path。
- dangerous command: destructive delete、pipe-to-shell、permission broadening、fork bomb pattern。
- resource cap: timeout、memory、CPU、pids、network / egress。

可能なら次を実行する。

```bash
uv run pytest backend/tests/runner
```

BLOCK 条件:

- tool gateway と runner gateway の混同。
- approval bypass。
- forbidden path write が通る。
- dangerous command が拒否されない。
- runner stdout / stderr に secret canary raw value が残る。

## Step 7: 集約 verdict

集約規則:

- BLOCK が 1 件以上: suite verdict は BLOCK。
- BLOCK なし、WARN が 1 件以上: suite verdict は WARN。
- 全 Step PASS / SKIPPED with reason のみ: PASS。
- SKIPPED は未実装理由、代替確認、残リスクを必ず持つ。

## 出力 contract

```json
{
  "suite": "quality-suite",
  "target": "backend|frontend|both",
  "scope": "changed|all",
  "verdict": "PASS|WARN|BLOCK",
  "steps": [
    {
      "name": "typecheck_lint",
      "status": "PASS|WARN|BLOCK|SKIPPED",
      "commands": [],
      "findings": [
        {
          "severity": "WARN|BLOCK",
          "path": "<path|null>",
          "reason_code": "<code>",
          "message": "<summary>"
        }
      ]
    }
  ],
  "aggregate": {
    "pass": 0,
    "warn": 0,
    "block": 0,
    "skipped": 0
  },
  "verification_gaps": [
    {
      "command": "<command>",
      "reason": "<why not run>",
      "alternative": "<manual/static check>",
      "residual_risk": "<risk>"
    }
  ]
}
```

## 失敗時の挙動

- コマンド失敗は出力を保存し、根本原因を修正対象にする。
- test flake が疑われる場合も、再実行だけで PASS にせず、再現条件と影響を記録する。
- contract test 未整備は WARN。ただし高リスク境界では BLOCK。
- raw secret / canary raw value / private fixture 期待値露出は即 BLOCK。
- 3 回連続で同じ Step が失敗する場合は、原因、失敗回数、継続案、停止案を AskUserQuestion に戻す。

## TaskManagedAI 不変条件 trace

- Provider Compliance: AC-HARD-01、AC-HARD-02、AC-KPI-05。
- SecretBroker: AC-HARD-02、AC-KPI-03。
- tenant/project boundary: AC-HARD-03。
- Runner: AC-HARD-05、AC-HARD-06。
- AgentRun state: AC-KPI-01、AC-KPI-02、AC-KPI-05 の計測基盤。
- Evidence / tests: AC-KPI-01、AC-KPI-04。

