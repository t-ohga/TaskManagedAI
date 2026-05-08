---
name: runner-gateway-audit
description: "TaskManagedAI runner/tool gateway の混同、forbidden path、dangerous command、resource cap を監査する。Triggers: runner gateway"
when_to_use: |
  runner code、tool registry、policy decision、forbidden path、dangerous command、resource cap、gateway_kind を確認する時。
  トリガーフレーズ: 'runner gateway', 'tool_mutating_gateway_stub', 'runner_mutation_gateway', 'dangerous command'
argument-hint: "<runner code path> <tool registry path> [policy decision path]"
allowed-tools: Read Bash Grep
---

# runner-gateway-audit — runner / tool gateway 混同検出

## 目的

`tool_mutating_gateway_stub` と `runner_mutation_gateway` の混同を検出し、runner sandbox が forbidden path、dangerous command、resource cap、approval、policy decision を通過しているかを監査する。

## 必読資料

- `.claude/rules/core.md` §6
- `.claude/rules/instincts.md` §10
- `.claude/rules/ai-output-boundary.md` §9
- `.claude/reference/hard-gates-and-kpis.md`
- `.claude/reference/directory-structure.md`

## Main Agent への指示

この skill は Read / Bash / Grep による監査だけを行う。gateway 実装は変更しない。

## Step 1: gateway 名と責務の検出

検索例:

```bash
rg -n "tool_mutating_gateway_stub|runner_mutation_gateway|gateway_kind|forbidden_path|dangerous_command|resource_cap|approval|policy_decision|runner_blocked" <paths>
```

期待する分離:

| gateway | 対象 | P0 方針 |
|---|---|---|
| `tool_mutating_gateway_stub` | MCP / external tool の書込系 | deny-only |
| `runner_mutation_gateway` | runner sandbox 内 patch 適用 | policy / approval / forbidden path / command gate 後のみ |

BLOCK patterns:

- `tool_mutating_gateway_stub` で書込を allow。
- `runner_mutation_gateway` を通したことを理由に external tool write を allow。
- `tool_mutating_gateway_stub` を実装しただけで runner patch を安全扱い。
- `gateway_kind` がなく audit で tool / runner を区別できない。
- AI output patch を approval なしに repo へ適用。
- AI output command を shell に直結。

## Step 2: forbidden path / dangerous command / resource cap

Forbidden path check:

- `.env`
- `.git/config`
- secret material path。
- high-risk workflow path。
- provider key / token output path。
- private fixture expectation path。
- migration path は ADR / rollback / backup 方針なしでは high-risk BLOCK。

Dangerous command check:

- destructive recursive delete。
- pipe-to-shell install。
- permission broadening。
- fork bomb pattern。
- unrestricted network download / execution。
- direct secret print / env dump。
- broad filesystem chmod / chown。

Resource cap check:

- max wall-clock timeout。
- memory limit。
- CPU limit。
- process / pid limit。
- output size limit。
- network / egress policy。
- cancellation boundary。
- stdout / stderr redaction.

BLOCK patterns:

- forbidden path write が policy / runner で止まらない。
- dangerous command list が allowlist より後に評価される。
- resource cap が optional。
- runner stdout / stderr に secret canary raw value が残る。
- `runner_blocked` audit event がない。
- approval target が diff hash / policy version / repo_state と binding していない。

## Step 3: tests / fixtures の確認

検索例:

```bash
rg -n "forbidden_path|dangerous_command|runner_blocked|resource_cap|AC-HARD-05|AC-HARD-06|tool_mutating_gateway_stub|runner_mutation_gateway" backend tests eval config
```

期待:

- AC-HARD-05 fixture: forbidden path block。
- AC-HARD-06 fixture: dangerous command block。
- runner contract test。
- approval bypass negative test。
- canary stdout / stderr negative test。
- audit event test。

## 出力 contract

```json
{
  "skill": "runner-gateway-audit",
  "verdict": "PASS|WARN|BLOCK",
  "inputs": {
    "runner_paths": [],
    "tool_registry_paths": [],
    "policy_paths": []
  },
  "gateway_separation": {
    "tool_mutating_gateway_stub": "PASS|WARN|BLOCK",
    "runner_mutation_gateway": "PASS|WARN|BLOCK",
    "gateway_kind_audit": "PASS|WARN|BLOCK"
  },
  "findings": [
    {
      "severity": "BLOCK|WARN|INFO",
      "reason_code": "gateway_confusion|forbidden_path_bypass|dangerous_command_bypass|resource_cap_missing|approval_bypass|audit_missing",
      "path": "<path>",
      "line": 0,
      "message": "<summary>",
      "trace": ["AC-HARD-05", "AC-HARD-06"]
    }
  ],
  "required_tests": [
    "forbidden path negative",
    "dangerous command negative",
    "resource cap",
    "approval bypass",
    "runner_blocked audit",
    "canary stdout redaction"
  ]
}
```

## 失敗時の挙動

- gateway 名の混同は BLOCK。
- approval bypass は BLOCK。
- forbidden path / dangerous command の allow は BLOCK。
- resource cap 欠落は BLOCK。
- test 不足は WARN。runner 実装変更と同時なら BLOCK。
- raw secret / token / canary raw value 露出は BLOCK。
- 対象 path が曖昧な場合は WARN とし、Main Agent に追加 path 確認を戻す。

## TaskManagedAI 不変条件 trace

- `tool_mutating_gateway_stub` と `runner_mutation_gateway` を分離する。
- AC-HARD-05 forbidden path block を維持する。
- AC-HARD-06 dangerous command block を維持する。
- AC-HARD-07 prompt injection 由来の excessive agency を runner で止める。
- AI Output Boundary の diff_ready / approval / runner_or_repo_action を維持する。
- AgentRunEvent `runner_started` / `runner_completed` / `runner_blocked` に接続する。

