---
name: agentrun-state-machine-test
description: "TaskManagedAI AgentRun 16 状態遷移の pytest contract test を生成する。Triggers: AgentRun status, state machine"
when_to_use: |
  AgentRun status enum、transition table、provider result mapping、blocked_reason、repair exhaustion、ContextSnapshot contract の test を作る時。
  トリガーフレーズ: 'AgentRun state machine', '16 状態', 'state machine test', 'blocked_reason'
argument-hint: "<status enum path> <transition table path> [--output backend/tests/agentrun/test_state_machine_contract.py]"
allowed-tools: Bash Read Write Edit AskUserQuestion
---

# agentrun-state-machine-test — 16 状態遷移 contract test 生成

## 目的

AgentRun 16 状態、blocked サブ 3、terminal state immutability、repair exhaustion、provider result mapping、ContextSnapshot 10 カラムを pytest contract test として固定する。

## 必読資料

- `.claude/rules/agentrun-state-machine.md` §7-§12
- `.claude/rules/testing.md` §7
- `.claude/reference/db-schema-notes.md`
- `.claude/reference/dev-commands.md`

## Main Agent への指示

この skill は test fixture の生成・更新だけを行う。実装コードの状態遷移を変更しない。既存 test がある場合は重複を避け、差分を最小にする。

## Step 1: enum / transition source の確認

1. status enum path と transition table path を読む。
2. 次の 16 状態と完全一致するか確認する。

```python
EXPECTED_STATUSES = {
    "queued",
    "gathering_context",
    "running",
    "generated_artifact",
    "schema_validated",
    "policy_linted",
    "diff_ready",
    "waiting_approval",
    "blocked",
    "provider_refused",
    "provider_incomplete",
    "validation_failed",
    "repair_exhausted",
    "completed",
    "failed",
    "cancelled",
}
```

3. `blocked_reason` は次の 3 種だけにする。

```python
EXPECTED_BLOCKED_REASONS = {
    "policy_blocked",
    "budget_blocked",
    "runtime_blocked",
}
```

4. terminal state:

```python
TERMINAL_STATUSES = {
    "completed",
    "failed",
    "cancelled",
    "provider_refused",
    "repair_exhausted",
}
```

## Step 2: pytest skeleton 生成

default output:

```text
backend/tests/agentrun/test_state_machine_contract.py
```

test skeleton:

```python
import pytest

EXPECTED_STATUSES = {
    "queued",
    "gathering_context",
    "running",
    "generated_artifact",
    "schema_validated",
    "policy_linted",
    "diff_ready",
    "waiting_approval",
    "blocked",
    "provider_refused",
    "provider_incomplete",
    "validation_failed",
    "repair_exhausted",
    "completed",
    "failed",
    "cancelled",
}

EXPECTED_BLOCKED_REASONS = {
    "policy_blocked",
    "budget_blocked",
    "runtime_blocked",
}

TERMINAL_STATUSES = {
    "completed",
    "failed",
    "cancelled",
    "provider_refused",
    "repair_exhausted",
}

VALID_TRANSITIONS = {
    ("queued", "gathering_context"),
    ("gathering_context", "running"),
    ("running", "generated_artifact"),
    ("generated_artifact", "schema_validated"),
    ("schema_validated", "policy_linted"),
    ("policy_linted", "diff_ready"),
    ("diff_ready", "waiting_approval"),
    ("waiting_approval", "running"),
    ("running", "completed"),
    ("running", "provider_refused"),
    ("running", "provider_incomplete"),
    ("running", "blocked"),
    ("running", "failed"),
    ("running", "cancelled"),
    ("generated_artifact", "validation_failed"),
    ("validation_failed", "running"),
    ("validation_failed", "repair_exhausted"),
    ("policy_linted", "blocked"),
    ("diff_ready", "blocked"),
    ("waiting_approval", "blocked"),
    ("blocked", "waiting_approval"),
    ("blocked", "running"),
    ("blocked", "failed"),
    ("provider_incomplete", "running"),
    ("provider_incomplete", "failed"),
}

PROVIDER_RESULT_MAPPING = {
    "refusal": ("provider_refused", None),
    "safety_refusal": ("provider_refused", None),
    "max_token_incomplete": ("provider_incomplete", None),
    "unsupported_schema": ("validation_failed", None),
    "schema_mismatch": ("validation_failed", None),
    "provider_request_preflight_deny": ("blocked", "policy_blocked"),
    "data_class_deny": ("blocked", "policy_blocked"),
    "budget_exceeded": ("blocked", "budget_blocked"),
    "success_structured_output": ("generated_artifact", None),
}

CONTEXT_SNAPSHOT_COLUMNS = {
    "prompt_pack_version",
    "prompt_pack_lock",
    "policy_version",
    "policy_pack_lock",
    "repo_state",
    "tool_manifest",
    "evidence_set_hash",
    "provider_continuation_ref",
    "provider_request_fingerprint",
    "snapshot_kind",
}


def test_status_enum_is_exact(agentrun_status_values):
    assert set(agentrun_status_values) == EXPECTED_STATUSES


def test_blocked_reason_enum_is_exact(blocked_reason_values):
    assert set(blocked_reason_values) == EXPECTED_BLOCKED_REASONS


@pytest.mark.parametrize("status", EXPECTED_STATUSES - {"blocked"})
def test_blocked_reason_only_allowed_for_blocked(status, make_agent_run):
    run = make_agent_run(status=status, blocked_reason="policy_blocked")
    assert not run.is_valid()


@pytest.mark.parametrize("reason", EXPECTED_BLOCKED_REASONS)
def test_blocked_requires_blocked_reason(reason, make_agent_run):
    run = make_agent_run(status="blocked", blocked_reason=reason)
    assert run.is_valid()


@pytest.mark.parametrize("from_status,to_status", VALID_TRANSITIONS)
def test_valid_transitions_are_allowed(from_status, to_status, state_machine):
    assert state_machine.can_transition(from_status, to_status)


@pytest.mark.parametrize("terminal_status", TERMINAL_STATUSES)
@pytest.mark.parametrize("next_status", EXPECTED_STATUSES)
def test_terminal_state_is_immutable(terminal_status, next_status, state_machine):
    assert not state_machine.can_transition(terminal_status, next_status)


def test_repair_exhaustion_is_terminal(state_machine, repair_policy):
    status = state_machine.after_validation_failure(repair_attempts=repair_policy.max_attempts)
    assert status == "repair_exhausted"
    assert state_machine.is_terminal(status)


@pytest.mark.parametrize("provider_result,expected", PROVIDER_RESULT_MAPPING.items())
def test_provider_result_mapping(provider_result, expected, provider_mapper):
    assert provider_mapper.map(provider_result) == expected


def test_context_snapshot_columns_are_present(context_snapshot_columns):
    assert set(context_snapshot_columns) >= CONTEXT_SNAPSHOT_COLUMNS
```

`agentrun_status_values`, `make_agent_run`, `state_machine`, `provider_mapper` などは既存実装に合わせて fixture 名を調整する。存在しない場合は `pytest.skip("wire to implementation fixture")` ではなく、TODO を残しすぎない最小 adapter fixture を作る。

## Step 3: 実行と gap 記録

可能なら次を実行する。

```bash
uv run pytest backend/tests/agentrun/test_state_machine_contract.py
```

実装が未整備で RED になる場合は、それを期待 RED として記録する。テストを弱めて GREEN にしない。

## 出力 contract

```json
{
  "skill": "agentrun-state-machine-test",
  "status": "PASS|WARN|BLOCK",
  "output_path": "backend/tests/agentrun/test_state_machine_contract.py",
  "generated_tests": [
    "status enum exact",
    "blocked_reason consistency",
    "valid transitions",
    "invalid transitions",
    "terminal immutability",
    "repair exhaustion",
    "provider result mapping",
    "ContextSnapshot 10 columns"
  ],
  "red_expected": true,
  "verification": {
    "command": "uv run pytest backend/tests/agentrun/test_state_machine_contract.py",
    "result": "pass|fail|not_run",
    "gap": "<reason>"
  }
}
```

## 失敗時の挙動

- status enum source が読めない: BLOCK。
- 16 状態と異なる source を検出: BLOCK。
- output path が既存 test と衝突する場合: 上書きせず Edit 方針を提示する。
- implementation fixture が未整備: WARN。ただし test skeleton は生成する。
- terminal state から遷移可能な実装を見つけた場合: BLOCK。

## TaskManagedAI 不変条件 trace

- AgentRun 16 状態を DB / backend / frontend / eval で同期する。
- `blocked` サブ 3 を status enum に混ぜない。
- terminal state immutability を守る。
- Provider Compliance deny を `blocked` + `policy_blocked` に trace する。
- BudgetGuard deny を `blocked` + `budget_blocked` に trace する。
- ContextSnapshot 10 カラムを再現性 contract として守る。

