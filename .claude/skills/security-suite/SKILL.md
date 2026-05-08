---
name: security-suite
description: "TaskManagedAI の OWASP/Provider/SecretBroker/Runner/Hard Gates 7 を集中監査する pipeline。Triggers: security-suite, AC-HARD"
when_to_use: |
  Hard Gate 監査、Provider Compliance、SecretBroker、runner sandbox、prompt injection、dangerous command、forbidden path を集中確認する時。
  トリガーフレーズ: 'security-suite で', 'AC-HARD を監査', 'セキュリティ監査', 'Hard Gate 確認'
argument-hint: "[<SP-NNN>] [--gate=AC-HARD-NN|all]"
allowed-tools: Skill Agent Bash Read Edit Write AskUserQuestion
---

# security-suite — セキュリティ監査 pipeline

## 目的

TaskManagedAI の P0 Hard Gates 7 件と、OWASP LLM 系リスク、Provider Compliance、SecretBroker、runner sandbox、AI Output Boundary を集中監査する。

この suite は Main Agent orchestration 用である。Skill / Agent の出力は Main Agent が採否判定し、AC-HARD-01〜07 ごとの PASS/FAIL に集約する。

## 必読資料

- `.claude/rules/core.md`
- `.claude/rules/ai-output-boundary.md`
- `.claude/rules/provider-compliance.md`
- `.claude/rules/secretbroker-boundary.md`
- `.claude/rules/agentrun-state-machine.md`
- `.claude/rules/testing.md`
- `.claude/reference/hard-gates-and-kpis.md`
- `.claude/reference/audit-ownership-matrix.md`
- `.claude/reference/provider-compliance-matrix.md`
- `.claude/reference/secretbroker-contract.md`
- `.claude/agents/taskmanagedai/security-specialist.md`
- `.claude/agents/taskmanagedai/hard-gate-fixture-reviewer.md`
- `.claude/agents/taskmanagedai/runner-security-reviewer.md`

## Main Agent への指示

`--gate=all` では AC-HARD-01〜07 を全件確認する。単一 gate 指定では対象 gate と依存境界だけを確認する。Hard Gate は fixture-based eval が正本であり、hook や static check は補助に留める。

## Step 0: 状態初期化

### Shell Prelude

```bash
# === TaskManagedAI Shell Prelude (SUITE_NAME=security-suite) ===
SUITE_NAME="security-suite"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
SESSION_ID="${CLAUDE_SESSION_ID:-fallback-$(date +%s)}"
STATE_DIR="$HOME/.claude/local/${SUITE_NAME}-state"
RESULTS_DIR="$HOME/.claude/local/${SUITE_NAME}-results/${SESSION_ID}"
mkdir -p "$STATE_DIR" "$RESULTS_DIR"

GATE="$(printf '%s\n' "$ARGUMENTS" | grep -oE -- '--gate=(AC-HARD-[0-9]{2}|all)' | sed 's/--gate=//' | head -1)"
GATE="${GATE:-all}"
case "$GATE" in
  all|AC-HARD-01|AC-HARD-02|AC-HARD-03|AC-HARD-04|AC-HARD-05|AC-HARD-06|AC-HARD-07) ;;
  *) echo "ERROR: --gate must be AC-HARD-NN|all" >&2; exit 1 ;;
esac

# Sprint Pack ID 解決 (AC-HARD-04 / `--gate=all` で release-suite delegate に必要)
SP_ID="$(printf '%s\n' "$ARGUMENTS" | grep -oE -- 'SP-[0-9]{3}' | head -1)"
if [ -z "$SP_ID" ]; then
  # current branch から推定 (git branch --show-current が SP-NNN 形式の場合)
  SP_ID="$(git branch --show-current 2>/dev/null | grep -oE 'SP-[0-9]{3}' | head -1 || true)"
fi
# AC-HARD-04 / all で SP_ID 未解決なら BLOCK
if { [ "$GATE" = "all" ] || [ "$GATE" = "AC-HARD-04" ]; } && [ -z "$SP_ID" ]; then
  echo "ERROR: AC-HARD-04 / --gate=all needs <SP-NNN>; pass it as 1st arg or run from a SP-NNN branch (release-suite delegate requires Sprint Pack ID)" >&2
  exit 1
fi

git status --short > "$RESULTS_DIR/git-status.txt"
git diff --name-only > "$RESULTS_DIR/changed-files.txt"
```

Gate map:

| Gate | metric | fixture path |
|---|---|---|
| AC-HARD-01 | `policy_block_recall` | `eval/security/policy_block/*` |
| AC-HARD-02 | `secret_canary_no_leak` | `eval/security/secret_canary/*` |
| AC-HARD-03 | `tenant_isolation_negative_pass` | `eval/security/tenant_isolation/*` |
| AC-HARD-04 | `backup_restore_rpo_rto` | `eval/ops/backup_restore/*` |
| AC-HARD-05 | `forbidden_path_block` | `eval/security/forbidden_path/*` |
| AC-HARD-06 | `dangerous_command_block` | `eval/security/dangerous_command/*` |
| AC-HARD-07 | `prompt_injection_resist` | `eval/security/prompt_injection/*` |

## Step 1: Provider Compliance audit

Main Agent は次を呼ぶ。

```text
Skill(
  skill="provider-compliance-audit",
  args="config/provider_compliance.toml <optional provider call sites>"
)
```

重点:

- `payload_data_class` 必須。
- `allowed_data_class` は Matrix 由来のみ。
- `training_use != no` の fail-closed。
- conditional ZDR の `condition_status=verified`。
- provider_request_preflight。
- audit payload に raw secret なし。

Trace: AC-HARD-01、AC-HARD-02、AC-HARD-07、AC-KPI-05。

## Step 2: SecretBroker atomic claim audit

Main Agent は次を呼ぶ。

```text
Skill(
  skill="atomic-claim-validator",
  args="<DDL path> <service code path> <migration path>"
)
```

重点:

- one-time atomic claim UPDATE。
- actor / run / expected_request_fingerprint / requested_operation binding。
- check -> execute -> mark used の逐次 redeem 検出。
- OperationContext fingerprint は broker 側計算。
- raw secret / token / canary raw value 非露出。

Trace: AC-HARD-02、AC-KPI-03。

## Step 3: Runner / tool gateway audit

Main Agent は次を呼ぶ。

```text
Skill(
  skill="runner-gateway-audit",
  args="<runner code path> <tool registry path> <policy decision path>"
)
```

重点:

- `tool_mutating_gateway_stub` と `runner_mutation_gateway` の分離。
- forbidden path。
- dangerous command。
- resource cap。
- approval bypass の有無。
- runner stdout / stderr secret canary。

Trace: AC-HARD-05、AC-HARD-06、AC-HARD-07。

## Step 3.5: Gate routing (AC-HARD-03 / AC-HARD-04 への delegation)

`security-suite` が **直接 owner** になる gate は **AC-HARD-01 (policy_block_recall)** と **AC-HARD-07 (prompt_injection_resist)** のみ。AC-HARD-02 / 05 / 06 は他 owner skill (`hard-gate-fixture-create` / `runner-gateway-audit`) の結果を **補助 check + Step 7 集約**として扱い、AC-HARD-03 (tenant_isolation_negative_pass) と AC-HARD-04 (backup_restore_rpo_rto) は他 owner skill / agent へ **明示 delegate** する。

`--gate=all` または `--gate=AC-HARD-03` 指定時、Main Agent は次を呼ぶ:

```text
Skill(
  skill="postgres-boundary-audit",
  args="<migrations 一覧> <models> <pytest DB tests>"
)
```

```text
Agent(
  subagent_type="tenant-project-isolation-reviewer",
  prompt="tenant_id / project_id 複合 FK、cross-project negative test、AgentRun parent_run_id project 内閉包、ticket_relations project 越境禁止を確認してください。"
)
```

`--gate=all` または `--gate=AC-HARD-04` 指定時、Main Agent は次を呼ぶ:

```text
Skill(
  skill="release-suite",
  args="${SP_ID} --mode=p0-acceptance"
)
```

`release-suite` 内の `release-auditor` が `eval/ops/backup_restore/*` の RPO ≤24h / RTO ≤4h / PITR drill 結果を確認する。本 suite では集約のみ受け取る。

本表は `.claude/reference/audit-ownership-matrix.md` §2 の owner skill / owner agent を正本とし、本 suite 内での補助 check を別列で示す:

| Gate | Owner skill (正本) | Owner agent (正本) | 本 suite 内補助 check |
|---|---|---|---|
| AC-HARD-01 | `security-suite` | `security-specialist` | Step 1-2 で本 suite が owner として実行 |
| AC-HARD-02 | `hard-gate-fixture-create` | `security-specialist` | Step 4 で fixture 整備、Step 1 で provider preflight 補助 |
| AC-HARD-03 | `postgres-boundary-audit` | `tenant-project-isolation-reviewer` | **delegate** (本 suite では補助なし、Step 7 集約のみ) |
| AC-HARD-04 | `release-suite` | `release-auditor` | **delegate** (本 suite では補助なし、Step 7 集約のみ) |
| AC-HARD-05 | `runner-gateway-audit` | `runner-security-reviewer` | Step 3 で runner gateway audit 実行 |
| AC-HARD-06 | `runner-gateway-audit` | `runner-security-reviewer` | Step 3 で dangerous command 補助 |
| AC-HARD-07 | `security-suite` | `security-specialist` | Step 3 / Step 5 で prompt injection / untrusted_content 確認 |

Trace: 全 AC-HARD-01〜07 を集約対象に。delegate 結果は Step 7 集約で `verdict` を反映。

## Step 4: Hard Gate fixture 整備

対象 gate の fixture が不足している場合、Main Agent は次を呼ぶ。

```text
Skill(
  skill="hard-gate-fixture-create",
  args="<AC-HARD-NN> --split public/private/adversarial --expected-decision <block|pass> --dataset-version <version>"
)
```

fixture 作成時は anti-gaming rule を必ず明記する。private holdout の期待値を prompt / policy tuning に使わない。

## Step 5: 専門 agent 監査

Main Agent は対象 gate に応じて agent を起動する。

```text
Agent(
  subagent_type="security-specialist",
  prompt="TaskManagedAI の Hard Gates、AI Output Boundary、Provider Compliance、SecretBroker、Runner、OWASP LLM 系リスクを AC-HARD ごとに監査してください。"
)
```

```text
Agent(
  subagent_type="hard-gate-fixture-reviewer",
  prompt="対象 Hard Gate fixture の public/private/adversarial 分離、dataset version、expected decision、anti-gaming rule、raw secret 非露出を確認してください。"
)
```

```text
Agent(
  subagent_type="runner-security-reviewer",
  prompt="Runner sandbox、forbidden path、dangerous command、resource cap、gateway separation、approval bypass を確認してください。"
)
```

## Step 6: 必要時 Codex 敵対レビュー

次の条件では Main Agent が user global skill `codex-adversarial-review` を呼ぶ。

- AC-HARD-01 / 02 / 05 / 06 / 07 に影響する変更。
- provider_request_preflight、SecretBroker、runner gateway を変更した。
- security-specialist が HIGH / BLOCK を出した。
- P0 Acceptance 前の final guard。

```text
Skill(
  skill="codex-adversarial-review",
  args="<security scope> --session-id <session_id> --output <results_dir>/step_6_adversarial.json"
)
```

## Step 7: AC-HARD 集約

各 gate を PASS/FAIL/WARN/NOT_APPLICABLE で集約する。Hard Gate は 1 件でも FAIL なら P0 承認不可。

## 出力 contract

```json
{
  "suite": "security-suite",
  "gate": "all|AC-HARD-NN",
  "verdict": "PASS|WARN|BLOCK",
  "hard_gates": {
    "AC-HARD-01": {
      "metric": "policy_block_recall",
      "status": "PASS|FAIL|WARN|NOT_APPLICABLE",
      "evidence": [],
      "fixture_path": "eval/security/policy_block/*"
    },
    "AC-HARD-02": {
      "metric": "secret_canary_no_leak",
      "status": "PASS|FAIL|WARN|NOT_APPLICABLE",
      "evidence": []
    },
    "AC-HARD-03": {
      "metric": "tenant_isolation_negative_pass",
      "status": "PASS|FAIL|WARN|NOT_APPLICABLE",
      "evidence": []
    },
    "AC-HARD-04": {
      "metric": "backup_restore_rpo_rto",
      "status": "PASS|FAIL|WARN|NOT_APPLICABLE",
      "evidence": []
    },
    "AC-HARD-05": {
      "metric": "forbidden_path_block",
      "status": "PASS|FAIL|WARN|NOT_APPLICABLE",
      "evidence": []
    },
    "AC-HARD-06": {
      "metric": "dangerous_command_block",
      "status": "PASS|FAIL|WARN|NOT_APPLICABLE",
      "evidence": []
    },
    "AC-HARD-07": {
      "metric": "prompt_injection_resist",
      "status": "PASS|FAIL|WARN|NOT_APPLICABLE",
      "evidence": []
    }
  },
  "findings": [
    {
      "severity": "BLOCK|WARN|INFO",
      "gate": "AC-HARD-NN",
      "reason_code": "<code>",
      "path": "<path|null>",
      "message": "<summary>"
    }
  ],
  "anti_gaming_notes": [],
  "external_review_decisions": []
}
```

## 失敗時の挙動

- Hard Gate fixture 不足は WARN。P0 acceptance mode では BLOCK。
- raw secret / token / canary raw value の露出は即 BLOCK。
- private holdout の期待値漏えいは BLOCK。
- Security agent と Codex が矛盾する場合は Main Agent が根拠を比較し、採否を明記する。
- 修正不能または判定不能な HIGH risk は AskUserQuestion に戻す。

## TaskManagedAI 不変条件 trace

- AC-HARD-01: policy deny、AI Output Boundary、provider preflight。
- AC-HARD-02: SecretBroker、secret canary、raw secret 非露出。
- AC-HARD-03: tenant / project isolation。
- AC-HARD-04: backup / restore evidence。
- AC-HARD-05: forbidden path block。
- AC-HARD-06: dangerous command block。
- AC-HARD-07: prompt injection、untrusted_content、excessive agency 防止。
- Provider Compliance / SecretBroker / AgentRun / tenant boundary を audit event と fixture metadata に接続する。

