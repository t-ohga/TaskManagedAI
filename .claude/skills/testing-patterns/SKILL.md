---
name: testing-patterns
description: "TaskManagedAI の pytest/Vitest/Playwright/state machine test pattern を提案する。Triggers: testing patterns"
when_to_use: |
  新規テスト作成、弱い assertion 改善、仕様ベース branch 列挙、AgentRun/Provider/SecretBroker/tenant boundary test の雛形が必要な時。
  トリガーフレーズ: 'testing patterns', 'テスト雛形', 'pytest pattern', 'Vitest pattern', 'Playwright pattern'
argument-hint: "[--kind=pytest|vitest|playwright|contract] [--target=<feature-or-path>] [--write]"
allowed-tools: Read Bash Grep Edit Write
---

# testing-patterns — pytest / Vitest / Playwright / contract test pattern

## 目的

TaskManagedAI の仕様ベーステストを作るための reference と skeleton を提供する。弱い assertion を避け、AgentRun state machine、SecretBroker atomic claim、Provider Compliance、tenant boundary、AI output boundary を contract test として固定する。

`--write` がある場合だけ test skeleton を作成・編集してよい。それ以外は提案に留める。別 Skill / Agent を再帰起動しない。

## 必読資料

- `.claude/rules/testing.md`
- `.claude/rules/instincts.md` §6, §8, §9
- `.claude/rules/agentrun-state-machine.md`
- `.claude/rules/provider-compliance.md`
- `.claude/rules/secretbroker-boundary.md`
- `.claude/rules/ai-output-boundary.md`
- `.claude/reference/dev-commands.md`
- `.claude/reference/hard-gates-and-kpis.md`
- `.claude/agents/taskmanagedai/tdd-orchestrator.md`

## 対象

- `backend/tests/`
- `frontend/**/__tests__/`
- `frontend/**/*.test.{ts,tsx}`
- `tests/e2e/`
- `eval/`
- 関連する Sprint Pack / ADR / API / repository / service 実装

## 検査手順

1. 仕様 source を読む。

```bash
rg -n "SP-[0-9]{3}|ADR-[0-9]{5}|acceptance|受け入れ条件|検証手順|AC-HARD|AC-KPI" docs/sprints docs/adr docs/要件定義 docs/基本設計
```

2. 既存テストと弱い assertion を確認する。

```bash
rg --files backend/tests frontend tests/e2e
rg -n "toBeDefined\(\)|toBeTruthy\(\)|not\.toThrow\(\)|expect\([^)]*\)\s*;|assert\s+[^=]+$|as\s+any" backend/tests frontend tests/e2e
```

3. branch matrix を作る。

```text
normal:
- expected success
- expected event / audit
- expected DB state

negative:
- auth / actor / tenant / project boundary
- schema validation failure
- Provider deny
- SecretBroker mismatch
- runner forbidden path / dangerous command
- cancellation / timeout / retry
```

4. contract ごとの skeleton を選ぶ。

### pytest: FastAPI API contract

```python
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_endpoint_rejects_missing_actor_context(client: AsyncClient) -> None:
    response = await client.post("/api/example", json={"name": "demo"})

    assert response.status_code == 401
    body = response.json()
    assert body["error_code"] == "actor_context_required"
    assert "secret" not in body
```

### pytest: AgentRun state machine

```python
import pytest

TERMINAL_STATUSES = {
    "completed",
    "failed",
    "cancelled",
    "provider_refused",
    "repair_exhausted",
}

@pytest.mark.parametrize("terminal_status", sorted(TERMINAL_STATUSES))
def test_terminal_status_cannot_transition(transition_service, run_factory, terminal_status: str) -> None:
    run = run_factory(status=terminal_status)

    result = transition_service.try_transition(run.id, "running", actor_id=1)

    assert result.allowed is False
    assert result.error_code == "terminal_state_immutable"
```

### pytest: SecretBroker atomic claim

```python
import pytest

@pytest.mark.asyncio
async def test_atomic_claim_allows_only_one_redeem(secret_broker, issued_capability) -> None:
    first = await secret_broker.redeem(issued_capability.token, operation="provider.call")
    second = await secret_broker.redeem(issued_capability.token, operation="provider.call")

    assert first.status == "redeemed"
    assert second.status == "denied"
    assert second.reason_code == "already_used"
```

### pytest: Provider Compliance negative

```python
@pytest.mark.asyncio
async def test_provider_preflight_denies_payload_above_allowed(provider_adapter, request_factory) -> None:
    request = request_factory(payload_data_class="confidential", feature="public_only_feature")

    result = await provider_adapter.execute(request)

    assert result.status == "blocked"
    assert result.blocked_reason == "policy_blocked"
    assert result.reason_code == "payload_data_class_exceeds_allowed"
```

### pytest: tenant/project boundary

```python
def test_cross_project_parent_run_is_rejected(db_session, project_a, project_b, run_factory):
    parent = run_factory(project_id=project_a.id)
    child = run_factory(project_id=project_b.id)

    with pytest.raises(Exception):
        child.parent_run_id = parent.id
        db_session.commit()
```

### Vitest: UI state display

```ts
it("renders blocked_reason separately from AgentRun status", () => {
  render(<AgentRunStatus status="blocked" blockedReason="policy_blocked" />)

  expect(screen.getByText("blocked")).toBeVisible()
  expect(screen.getByText("policy_blocked")).toBeVisible()
})
```

### Playwright: approval flow

```ts
test("invalidates approval when diff hash changes", async ({ page }) => {
  await page.goto("/approvals")

  await expect(page.getByRole("status", { name: /invalidated/i })).toBeVisible()
})
```

5. `--write` がある場合だけ、既存 pattern に合わせて最小 skeleton を作る。既存 test helper / fixture 名を先に検索する。

```bash
rg -n "client|db_session|run_factory|provider_adapter|secret_broker|render\(|test\(" backend/tests frontend tests/e2e
```

## 出力 contract

```markdown
## Testing Pattern Proposal
Kind: pytest|vitest|playwright|contract
Target: ...

## Branch Matrix
| branch | expected behavior | assertion | fixture |
|---|---|---|---|

## Skeleton
<code block or created file path>

## Existing Test Improvements
| file:line | issue | replacement |
|---|---|---|
```

`--write` でファイルを作った場合は変更ファイルを列挙する。

## 失敗時の挙動

- 仕様 source が見つからない場合は、テスト作成前に Sprint Pack / ADR が必要と返す。
- fixture 名が不明な場合は、仮の helper を作らず既存 helper 候補を列挙する。
- 弱い assertion を含む skeleton は出さない。
- secret / provider raw response / private fixture expectation を test output に埋めない。
- 高リスク contract は実装前 ADR の有無も確認する。

## TaskManagedAI 不変条件 trace

- 弱い assertion 禁止
- AgentRun 16 状態 / blocked サブ 3 / terminal state
- SecretBroker atomic claim / one-time redeem
- Provider Compliance negative test
- tenant / project boundary negative test
- actor / principal / self-approval 境界
- AC-HARD-01〜07 / AC-KPI-01〜05

