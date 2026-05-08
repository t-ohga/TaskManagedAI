---
name: review-suite
description: "TaskManagedAI の Type Safety/Security/DB/API/ADR/Sprint Pack を統合レビューする pipeline。Triggers: review-suite, PR前レビュー"
when_to_use: |
  current branch、指定ファイル、PR 前差分を Type Safety / Security / DB / API contract / ADR Gate / Sprint Pack 観点でレビューする時。
  トリガーフレーズ: 'review-suite で', 'PR 前レビュー', 'current branch をレビュー', '指定ファイルをレビュー'
argument-hint: "[--scope=current-branch|specified-files] [--depth=fast|deep]"
allowed-tools: Skill Agent Bash Read Edit Write AskUserQuestion
---

# review-suite — コードレビュー pipeline

## 目的

TaskManagedAI の変更差分を、多層レビューで実装バグ、回帰、セキュリティ、DB 境界、API contract、ADR Gate、Sprint Pack 整合性の観点から確認する。

この suite は Main Agent orchestration 用である。各 review skill / agent の出力は Main Agent が採否判定し、重複指摘をまとめる。

## 必読資料

- `.claude/rules/core.md`
- `.claude/rules/ai-output-boundary.md`
- `.claude/rules/sprint-pack-adr-gate.md`
- `.claude/rules/plan-review.md`
- `.claude/rules/testing.md`
- `.claude/reference/audit-ownership-matrix.md`
- `.claude/reference/db-schema-notes.md`
- `.claude/reference/provider-compliance-matrix.md`
- `.claude/reference/secretbroker-contract.md`
- `.claude/agents/taskmanagedai/sprint-pack-reviewer.md`
- `.claude/agents/taskmanagedai/tenant-project-isolation-reviewer.md`
- `.claude/agents/taskmanagedai/code-reviewer.md`

## Main Agent への指示

レビュー結果は findings first でまとめる。重大度順に BLOCK、WARN、INFO を並べ、各 finding は file / line / 再現条件 / 修正方針に紐づける。

## Step 0: 状態初期化

### Shell Prelude

```bash
# === TaskManagedAI Shell Prelude (SUITE_NAME=review-suite) ===
SUITE_NAME="review-suite"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
SESSION_ID="${CLAUDE_SESSION_ID:-fallback-$(date +%s)}"
STATE_DIR="$HOME/.claude/local/${SUITE_NAME}-state"
RESULTS_DIR="$HOME/.claude/local/${SUITE_NAME}-results/${SESSION_ID}"
mkdir -p "$STATE_DIR" "$RESULTS_DIR"

SCOPE="$(printf '%s\n' "$ARGUMENTS" | grep -oE -- '--scope=(current-branch|specified-files)' | sed 's/--scope=//' | head -1)"
DEPTH="$(printf '%s\n' "$ARGUMENTS" | grep -oE -- '--depth=(fast|deep)' | sed 's/--depth=//' | head -1)"
SCOPE="${SCOPE:-current-branch}"
DEPTH="${DEPTH:-fast}"

git status --short > "$RESULTS_DIR/git-status.txt"
git diff --name-only > "$RESULTS_DIR/changed-files.txt"
git diff --stat > "$RESULTS_DIR/diff-stat.txt"
```

## Step 1: 差分と Sprint Pack / ADR trace

1. `git diff --name-only` と指定ファイルを確認する。
2. 変更が high-risk path に触るか判定する。
3. `docs/sprints/` に関連 Sprint Pack があるか確認する。
4. ADR Gate Criteria 11 種に該当する変更で ADR がない場合は BLOCK。

High-risk examples:

- DB schema、migration、tenant / project boundary。
- API contract、event schema、OpenAPI。
- ProviderAdapter、Provider Matrix、`payload_data_class`。
- SecretBroker、capability token、atomic claim。
- AgentRun status、ContextSnapshot。
- runner / tool gateway。
- external exposure、GitHub App permission、workflow path。

## Step 2: Type Safety review

Batch 3 skill が存在する場合、Main Agent は次を呼ぶ。

```text
Skill(
  skill="review-type-safety",
  args="--scope=<current-branch|specified-files> --depth=<fast|deep>"
)
```

未実装の場合は Bash / Read fallback:

```bash
rg -n "as any|@ts-ignore|type: ignore|Any\\]|dict\\[str, Any\\]|allowed_data_class|payload_data_class" backend frontend config docs 2>/dev/null
```

BLOCK 条件:

- `allowed_data_class` caller 入力。
- Provider / API / DB boundary の unchecked raw dict。
- AgentRun status enum drift。
- suppression で error を隠す実装。

## Step 3: Security / DB / API contract review

Main Agent は存在する Batch 3 / Batch 2 skill を順に呼ぶ。

```text
Skill(skill="review-security", args="--scope=<scope> --depth=<depth>")
Skill(skill="review-db", args="--scope=<scope> --depth=<depth>")
Skill(skill="api-contract-audit", args="--scope=<scope> --depth=<depth>")
```

未実装 skill は SKIPPED ではなく、対応する agent / Bash fallback で最低限確認する。

DB fallback:

```bash
rg -n "tenant_id|project_id|foreign key|unique \\(tenant_id|parent_run_id|ticket_relations" migrations backend 2>/dev/null
```

API fallback:

```bash
rg -n "APIRouter|response_model|BaseModel|AgentRunEvent|payload_data_class|allowed_data_class" backend 2>/dev/null
```

Security fallback:

```bash
rg -n "secret_ref|SecretBroker|token_hash|expected_request_fingerprint|runner_mutation_gateway|tool_mutating_gateway_stub|provider_request_preflight" backend config migrations 2>/dev/null
```

## Step 4: 専門 agent review

Main Agent は変更範囲に応じて agent を起動する。

```text
Agent(
  subagent_type="sprint-pack-reviewer",
  prompt="関連 Sprint Pack の frontmatter、light/heavy、must_ship/defer、ADR refs、Review 欄、Hard Gate/KPI trace を確認してください。"
)
```

```text
Agent(
  subagent_type="tenant-project-isolation-reviewer",
  prompt="DB migration、model、repository、DB tests を tenant/project boundary と AC-HARD-03 観点で確認してください。"
)
```

```text
Agent(
  subagent_type="code-reviewer",
  prompt="TaskManagedAI の current branch 差分を、バグ、回帰、セキュリティ、DB、Provider、SecretBroker、AgentRun、Runner、テスト不足の順でレビューしてください。"
)
```

`--depth=fast` では明らかに該当する agent だけ起動する。`--depth=deep` では高リスク境界に関連する agent を広げる。

## Step 5: 必要時 codex-second-opinion

次の条件では Main Agent が user global skill `codex-second-opinion` を呼ぶ。

- BLOCK の修正案が複数あり、採否判断が難しい。
- Security / DB / API contract の指摘が high-impact。
- Agent 出力同士が矛盾する。
- ユーザーが明示的に second opinion を求めた。

```text
Skill(
  skill="codex-second-opinion",
  args="<review summary or diff scope> --session-id <session_id> --output <results_dir>/step_5_second_opinion.json"
)
```

Codex 出力は `adopt` / `reject` / `defer` で判定する。

## Step 6: 集約と再レビュー条件

集約規則:

- BLOCK 1 件以上: `verdict=BLOCK`。
- WARN 1 件以上、BLOCK なし: `verdict=WARN`。
- 全件 PASS / not_applicable: `verdict=PASS`。
- `--depth=fast` で高リスク変更を検出した場合は、deep 再レビューを推奨する。

## 出力 contract

```json
{
  "suite": "review-suite",
  "scope": "current-branch|specified-files",
  "depth": "fast|deep",
  "verdict": "PASS|WARN|BLOCK",
  "findings": [
    {
      "severity": "BLOCK|WARN|INFO",
      "category": "type-safety|security|db|api-contract|adr-gate|sprint-pack|testing",
      "path": "<path>",
      "line": 0,
      "issue": "<what is wrong>",
      "impact": "<why it matters>",
      "recommendation": "<fix direction>",
      "trace": ["AC-HARD-03", "Sprint Pack", "ADR Gate"]
    }
  ],
  "open_questions": [],
  "external_review_decisions": [
    {
      "source": "agent|codex-second-opinion",
      "decision": "adopt|reject|defer",
      "reason": "<short reason>"
    }
  ],
  "verification_gaps": []
}
```

## 失敗時の挙動

- 重大 finding がある場合は summary より先に findings を出す。
- path / line が不明な指摘は WARN 以下に留め、再調査対象にする。
- skill 未実装時は `not_implemented` として記録し、Bash / agent fallback を行う。
- 高リスク領域で fallback もできない場合は BLOCK。
- raw secret、private fixture 期待値、token 生値らしきものを見つけた場合は即 BLOCK。

## TaskManagedAI 不変条件 trace

- Sprint Pack / ADR Gate: high-risk 変更の実装前 gate を確認する。
- AI Output Boundary: AI 出力直結、approval bypass、gateway bypass を検出する。
- Provider Compliance: `payload_data_class` / `allowed_data_class` / Matrix / preflight を確認する。
- SecretBroker: atomic claim と raw secret 非露出を確認する。
- AgentRun: 16 状態、blocked サブ 3、ContextSnapshot 10 カラムを確認する。
- tenant boundary: AC-HARD-03 と cross-project negative test を確認する。

