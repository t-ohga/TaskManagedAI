---
name: dev-suite
description: "TaskManagedAI の Sprint Pack/ADR Gate から TDD、品質、レビュー、Codex 敵対まで進める実装 pipeline。Triggers: SP-NNN, feature実装"
when_to_use: |
  Sprint Pack 単位の機能実装、既存 feature の TDD 実装、ADR Gate を含む Sprint 着手時。
  トリガーフレーズ: 'SP-NNN を実装', 'feature を実装', 'dev-suite で', 'Sprint 実装 pipeline'
argument-hint: "<SP-NNN | feature 名> [--dry-run=shallow|expanded] [--resume <session_id>]"
allowed-tools: Skill Agent Bash Read Edit Write AskUserQuestion
---

# dev-suite — Sprint 実装 pipeline

## 目的

TaskManagedAI の機能単位 Sprint を、Sprint Pack 確認、ADR Gate 判定、計画レビュー、TDD、品質確認、コードレビュー、Codex 敵対レビューまで一続きで進める。

この suite は Main Agent orchestration 用の手順書である。各 Step の Skill / Agent 呼び出しは Main Agent が行い、このファイル自体を子プロセスのように扱わない。

## 必読資料

- `docs/設計検討/harness-phase0-mapping.md` §2.5 / §3.4
- `.claude/CLAUDE.md`
- `.claude/rules/sprint-pack-adr-gate.md`
- `.claude/rules/plan-review.md`
- `.claude/rules/ai-output-boundary.md`
- `.claude/rules/core.md`
- `.claude/reference/hard-gates-and-kpis.md`
- `.claude/reference/audit-ownership-matrix.md`
- `.claude/reference/agent-routing.md`
- `.claude/agents/taskmanagedai/plan-reviewer.md`
- `.claude/agents/taskmanagedai/tdd-orchestrator.md`

## Main Agent への指示

以下の Step を順番に実行する。各 Step の出力を `~/.claude/local/dev-suite-results/<session_id>/` に保存し、最後に PASS/WARN/BLOCK を集約する。Codex / Agent 出力は必ず `adopt` / `reject` / `defer` で採否判定してから反映する。

## Step 0: 状態初期化

### Shell Prelude

```bash
# === TaskManagedAI Shell Prelude (SUITE_NAME=dev-suite) ===
SUITE_NAME="dev-suite"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
SESSION_ID="${CLAUDE_SESSION_ID:-fallback-$(date +%s)}"

RESUME_SESSION_ID="$(printf '%s\n' "$ARGUMENTS" | grep -oE -- '--resume[= ][^ ]+' | head -1 | sed -E 's/--resume[= ]//' || true)"
if [ -n "$RESUME_SESSION_ID" ]; then SESSION_ID="$RESUME_SESSION_ID"; fi

DRY_RUN_MODE="$(printf '%s\n' "$ARGUMENTS" | grep -oE -- '--dry-run[= ][^ ]+' | head -1 | sed -E 's/--dry-run[= ]//' || true)"
case "${DRY_RUN_MODE:-false}" in
  false|"") DRY_RUN=false; DRY_RUN_MODE="false" ;;
  shallow|expanded) DRY_RUN=true ;;
  *) echo "ERROR: --dry-run must be shallow|expanded" >&2; exit 1 ;;
esac

STATE_DIR="$HOME/.claude/local/${SUITE_NAME}-state"
RESULTS_DIR="$HOME/.claude/local/${SUITE_NAME}-results/${SESSION_ID}"
STATE_FILE="$STATE_DIR/${SESSION_ID}.json"
DRY_RUN_MANIFEST="$STATE_DIR/${SESSION_ID}-dry-run.jsonl"
mkdir -p "$STATE_DIR" "$RESULTS_DIR"

TARGET="$(printf '%s\n' "$ARGUMENTS" | sed -E 's/ --.*$//' | xargs)"
if [ -z "$TARGET" ]; then
  echo "ERROR: target must be <SP-NNN | feature name>" >&2
  exit 1
fi

jq -n \
  --arg suite "$SUITE_NAME" \
  --arg session_id "$SESSION_ID" \
  --arg target "$TARGET" \
  --arg dry_run_mode "$DRY_RUN_MODE" \
  --arg started_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  '{suite:$suite, session_id:$session_id, target:$target, dry_run_mode:$dry_run_mode, started_at:$started_at, steps:{step_0:"completed"}}' \
  > "$STATE_FILE"
```

`DRY_RUN_MODE=shallow|expanded` の場合、Main Agent は child Skill / Agent を実行せず、予定呼び出しを `DRY_RUN_MANIFEST` に JSONL で記録する。`expanded` では対象 Sprint Pack / ADR の存在確認だけは Read / Bash で行ってよい。

## Step 1: Sprint Pack 確認と ADR Gate 判定

1. `TARGET` が `SP-NNN` の場合は `docs/sprints/SP-NNN_*.md` を探す。
2. feature 名の場合は既存 Pack を検索し、なければ Main Agent が次を呼ぶ。

```text
Skill(
  skill="sprint-pack-create",
  args="<feature 名> --sprint-no <N> --risk-class <low|medium|high> --adr-gate <yes|no|unknown>"
)
```

3. `.claude/rules/sprint-pack-adr-gate.md` §4 の 11 Criteria に該当するか判定する。
4. 該当する場合は heavy Pack と ADR を必須にする。ADR がなければ Main Agent が次を呼ぶ。

```text
Skill(
  skill="adr-create",
  args="--criteria <1-11> --sprint <SP-NNN> --title <title> --rollback <summary>"
)
```

5. 判断が危険な推測になる場合は AskUserQuestion で、対象 Criteria、推奨案、影響、rollback の前提を確認する。

Hard Gates trace:

| Step | 主な trace |
|---|---|
| Sprint Pack | AC-HARD-01〜07 / AC-KPI-01〜05 の対象有無を宣言 |
| ADR Gate | DB / API / Provider / SecretBroker / Runner / GitHub App permission を実装前に止める |
| Review 欄 | changed / verified / deferred / risks を Sprint Exit で更新可能にする |

## Step 2: 実装計画と計画レビュー

1. Sprint Pack から実装計画を作る。必ず目的、対象外、変更対象、テスト、rollback、audit、Hard Gate / KPI trace を含める。
2. Main Agent は user global skill `codex-plan-review` を呼び、出力を採否判定する。

```text
Skill(
  skill="codex-plan-review",
  args="<plan_file_path> --session-id <session_id> --output <results_dir>/step_2_codex_plan_review.json"
)
```

3. Main Agent は `plan-reviewer` agent を起動する。

```text
Agent(
  subagent_type="plan-reviewer",
  prompt="TaskManagedAI の Sprint 実装計画を .claude/rules/plan-review.md に従って PASS/WARN/BLOCK 判定してください。Sprint Pack、ADR Gate Criteria 11 種、Hard Gates 7、Quality KPIs 5、rollback、audit、Provider Matrix、SecretBroker、AgentRun 16 状態を必ず確認してください。"
)
```

4. BLOCK が残る場合は実装に進まない。WARN は Sprint Pack の残リスクまたは計画修正で扱う。

## Step 3: TDD 実装

Main Agent は `tdd-orchestrator` agent を起動し、RED → GREEN → REFACTOR の順で進める。

```text
Agent(
  subagent_type="tdd-orchestrator",
  prompt="対象 Sprint の実装を TDD で進めてください。Provider、SecretBroker、AgentRun、Runner、tenant boundary を触る場合は contract / negative test を先に設計してください。"
)
```

TDD の最低条件:

- 受け入れ条件が観測可能なテストに落ちる。
- AgentRun 16 状態、ContextSnapshot 10 カラム、Provider Compliance、SecretBroker atomic claim、tenant/project boundary を壊さない。
- 弱い assertion だけで完了しない。
- AI 出力を command / SQL / workflow / external tool に直結させない。

## Step 4: quality-suite

Main Agent は品質確認を実行する。

```text
Skill(
  skill="quality-suite",
  args="--target=both --scope=changed --session-id <session_id> --output <results_dir>/step_4_quality.json"
)
```

BLOCK がある場合は修正して再実行する。WARN は Sprint Pack Review 欄に残すか、修正して消す。

## Step 5: review-suite

Main Agent はコードレビューを実行する。

```text
Skill(
  skill="review-suite",
  args="--scope=current-branch --depth=deep --session-id <session_id> --output <results_dir>/step_5_review.json"
)
```

レビューでは Type Safety、Security、DB、API contract、ADR Gate、Sprint Pack、tenant/project isolation、AI Output Boundary を確認する。

## Step 6: Codex 敵対レビューと完了判定

Main Agent は user global skill `codex-adversarial-review` を呼び、敵対的観点で漏れを確認する。

```text
Skill(
  skill="codex-adversarial-review",
  args="<changed scope> --session-id <session_id> --output <results_dir>/step_6_adversarial.json"
)
```

採否判定:

- `adopt`: 指摘を実装または文書へ反映する。
- `reject`: 根拠を Sprint Review に残す。
- `defer`: defer_if_over_budget または次 Sprint 候補へ移す。

## 出力 contract

```json
{
  "suite": "dev-suite",
  "session_id": "<session_id>",
  "target": "<SP-NNN|feature>",
  "verdict": "PASS|WARN|BLOCK",
  "steps": [
    {
      "step": "step_1_sprint_pack",
      "status": "PASS|WARN|BLOCK|SKIPPED",
      "artifact": "<path|null>",
      "findings": []
    }
  ],
  "hard_gates_trace": {
    "AC-HARD-01": "pass|warn|block|not_applicable",
    "AC-HARD-02": "pass|warn|block|not_applicable",
    "AC-HARD-03": "pass|warn|block|not_applicable",
    "AC-HARD-04": "pass|warn|block|not_applicable",
    "AC-HARD-05": "pass|warn|block|not_applicable",
    "AC-HARD-06": "pass|warn|block|not_applicable",
    "AC-HARD-07": "pass|warn|block|not_applicable"
  },
  "quality_kpis_trace": {
    "AC-KPI-01": "pass|warn|block|not_applicable",
    "AC-KPI-02": "pass|warn|block|not_applicable",
    "AC-KPI-03": "pass|warn|block|not_applicable",
    "AC-KPI-04": "pass|warn|block|not_applicable",
    "AC-KPI-05": "pass|warn|block|not_applicable"
  },
  "external_review_decisions": [
    {
      "source": "codex-plan-review|codex-adversarial-review|agent",
      "decision": "adopt|reject|defer",
      "reason": "<short reason>",
      "follow_up": "<path|ticket|null>"
    }
  ],
  "next_actions": []
}
```

## 失敗時の挙動

- Sprint Pack 不在: `sprint-pack-create` に戻る。
- ADR 必須だが ADR 不在: BLOCK。`adr-create` に戻る。
- 計画レビュー BLOCK: 実装停止。計画を修正する。
- TDD RED 未確認: WARN 以上。安全境界なら BLOCK。
- quality-suite / review-suite BLOCK: 修正して再実行する。
- Codex / Agent が 3 回連続で失敗した場合: 自動継続せず、原因、失敗回数、継続案、停止案を整理して AskUserQuestion に戻す。
- raw secret、private fixture 期待値、実 token らしき文字列が出た場合: 即 BLOCK。artifact quarantine と redaction を要求する。

## TaskManagedAI 不変条件 trace

- Sprint Pack / ADR Gate: 実装前 gate と rollback を固定する。
- AI Output Boundary: artifact → schema_validated → policy_linted → diff_ready → waiting_approval を維持する。
- Provider Compliance: `payload_data_class` と `allowed_data_class` を分離し、Matrix 由来の判定だけを採用する。
- SecretBroker: raw secret 非露出、one-time atomic claim、actor/run/fingerprint/operation binding を維持する。
- AgentRun: 16 状態、blocked サブ 3、terminal state、ContextSnapshot 10 カラムを壊さない。
- tenant boundary: `tenant_id` と project boundary を DB / repository / negative test で維持する。

