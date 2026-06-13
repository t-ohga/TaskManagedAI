"""SP-029 (ADR-00055) shadow run の budget 隔離 + per-run cap unit test。

設計制約:
- §4 production budget 非擾乱: shadow run は production の global/tenant/project
  budget (``BudgetGuard``) を **一切読まない / 誘発しない**。cost は ``run.cost_usd``
  に tag 記録される。
- §5 per-run hard cap: 累計 ``run.cost_usd`` が ``shadow_run_max_cost_usd`` を超過
  したら ``running -> blocked`` (budget_blocked) へ遷移する (uncapped にしない)。
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest

from backend.app.domain.provider.result import ProviderUsage
from backend.app.services.providers import usage_logger
from backend.app.services.providers.usage_logger import (
    preflight_shadow_budget,
    preflight_shadow_request_tokens,
    record_provider_usage,
)

RUN_ID = UUID("00000000-0000-4000-8000-0000000029b1")
PROJECT_ID = UUID("00000000-0000-4000-8000-0000000029b2")
ACTOR_ID = UUID("00000000-0000-4000-8000-0000000029b3")
MATRIX_VERSION = "pcm-v1"


def _shadow_run(*, cost_usd: object = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=RUN_ID,
        tenant_id=1,
        project_id=PROJECT_ID,
        status="running",
        blocked_reason=None,
        run_mode="shadow",
        cost_usd=cost_usd,
        tokens_input=None,
        tokens_output=None,
    )


class _ExplodingBudgetGuard:
    """shadow path が production BudgetGuard を触ったら即 fail させる sentinel。"""

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError(
            "shadow run must not consult production BudgetGuard (ADR-00055 §4)."
        )


@pytest.fixture
def captured_transitions(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []

    async def fake_transition_with_event(*_args: object, **kwargs: object) -> object:
        events.append(dict(kwargs))
        return object()

    async def no_kill_switch(*_args: object, **_kwargs: object) -> bool:
        return False

    monkeypatch.setattr(usage_logger, "transition_with_event", fake_transition_with_event)
    # shadow path が production tenant/project/agent_run SPEND budget を絶対に読まないことを enforce。
    monkeypatch.setattr(usage_logger, "BudgetGuard", _ExplodingBudgetGuard)
    # cap 単体を検証するため global kill switch は無効 (engaged-case は別 test で monkeypatch)。
    monkeypatch.setattr(usage_logger, "_global_kill_switch_engaged", no_kill_switch)
    monkeypatch.setattr(
        usage_logger,
        "get_settings",
        lambda: SimpleNamespace(
            shadow_run_max_cost_usd=Decimal("1.00"),
            shadow_run_max_total_tokens=100,
            shadow_run_max_usd_per_token=Decimal("0.00002"),
        ),
    )
    return events


@pytest.mark.asyncio
async def test_shadow_under_cap_records_cost_without_block(
    captured_transitions: list[dict[str, object]],
) -> None:
    run = _shadow_run()

    result = await record_provider_usage(
        object(),
        run=run,
        usage=ProviderUsage(tokens_input=10, tokens_output=20, cost_usd=0.25),
        actor_id=ACTOR_ID,
        matrix_version=MATRIX_VERSION,
    )

    # cost は run に tag 記録される (production budget には加算されない)。
    assert run.cost_usd == Decimal("0.25")
    assert run.tokens_input == 10
    assert run.tokens_output == 20
    assert result.exceeded is False
    assert result.hard_limit_usd == Decimal("1.00")
    assert result.current_usd == Decimal("0.25")
    # cap 未超過なので budget_blocked transition は発生しない。
    assert captured_transitions == []


@pytest.mark.asyncio
async def test_shadow_over_cap_blocks_with_budget_blocked(
    captured_transitions: list[dict[str, object]],
) -> None:
    run = _shadow_run()

    result = await record_provider_usage(
        object(),
        run=run,
        usage=ProviderUsage(tokens_input=10, tokens_output=20, cost_usd=1.50),
        actor_id=ACTOR_ID,
        matrix_version=MATRIX_VERSION,
    )

    assert run.cost_usd == Decimal("1.50")
    assert result.exceeded is True
    assert result.reason == "hard_usd_exceeded"
    assert result.hard_limit_usd == Decimal("1.00")
    assert len(captured_transitions) == 1
    transition = captured_transitions[0]
    assert transition["to_state"] == "blocked"
    assert transition["event_type"] == "budget_blocked"
    assert transition["blocked_reason"] == "budget_blocked"
    assert transition["actor_id"] == ACTOR_ID
    payload = transition["payload"]
    assert isinstance(payload, dict)
    assert payload["budget_level"] == "shadow_run_cap"
    assert payload["run_mode"] == "shadow"
    assert payload["exceed_reason"] == "hard_usd_exceeded"


@pytest.mark.asyncio
async def test_shadow_token_cap_blocks_when_cost_is_zero(
    captured_transitions: list[dict[str, object]],
) -> None:
    # Codex R6 F-1: provider が cost_usd=0 を返しても token cap (100) で必ず bound する。
    run = _shadow_run()

    result = await record_provider_usage(
        object(),
        run=run,
        usage=ProviderUsage(tokens_input=80, tokens_output=80, cost_usd=0.0),
        actor_id=ACTOR_ID,
        matrix_version=MATRIX_VERSION,
    )

    # cost は token floor (160 * 0.00002 = $0.0032) で計上される (R13)、USD cap $1 未満。
    assert run.cost_usd == Decimal("0.0032")
    assert run.tokens_input == 80
    assert run.tokens_output == 80
    # USD は cap 未満だが、token 累計 160 > 100 で block。
    assert result.exceeded is True
    assert result.reason == "hard_tokens_exceeded"
    assert len(captured_transitions) == 1
    payload = captured_transitions[0]["payload"]
    assert isinstance(payload, dict)
    assert payload["budget_level"] == "shadow_run_token_cap"
    assert payload["run_mode"] == "shadow"


@pytest.mark.asyncio
async def test_preflight_blocks_shadow_at_token_cap(
    captured_transitions: list[dict[str, object]],
) -> None:
    run = _shadow_run()
    run.tokens_input = 60
    run.tokens_output = 60  # 累計 120 >= token cap 100
    result = await preflight_shadow_budget(object(), run=run, actor_id=ACTOR_ID)
    assert result is not None
    assert result.exceeded is True
    assert result.reason == "hard_tokens_exceeded"
    assert len(captured_transitions) == 1


@pytest.mark.asyncio
async def test_shadow_cost_accumulates_across_calls_until_cap(
    captured_transitions: list[dict[str, object]],
) -> None:
    run = _shadow_run()

    first = await record_provider_usage(
        object(),
        run=run,
        usage=ProviderUsage(tokens_input=1, tokens_output=1, cost_usd=0.60),
        actor_id=ACTOR_ID,
        matrix_version=MATRIX_VERSION,
    )
    assert first.exceeded is False
    assert captured_transitions == []

    # 2 回目で累計 1.20 > cap 1.00 → blocked。
    second = await record_provider_usage(
        object(),
        run=run,
        usage=ProviderUsage(tokens_input=1, tokens_output=1, cost_usd=0.60),
        actor_id=ACTOR_ID,
        matrix_version=MATRIX_VERSION,
    )
    assert run.cost_usd == Decimal("1.20")
    assert second.exceeded is True
    assert second.reason == "hard_usd_exceeded"
    assert len(captured_transitions) == 1


@pytest.mark.asyncio
async def test_shadow_cost_floored_by_tokens_when_provider_underreports(
    monkeypatch: pytest.MonkeyPatch,
    captured_transitions: list[dict[str, object]],
) -> None:
    # Codex R13 F-1: provider が cost_usd=0 と過少報告しても、token 由来の下限 cost
    # (tokens * 単価) を run.cost_usd に計上し、USD cap が累積的に効く。
    # price=0.02, usd_cap=$1, token_cap=1e6: cost=0 報告 + 60 tokens → floor $1.20 > $1 → block。
    monkeypatch.setattr(
        usage_logger,
        "get_settings",
        lambda: SimpleNamespace(
            shadow_run_max_cost_usd=Decimal("1.00"),
            shadow_run_max_total_tokens=1_000_000,
            shadow_run_max_usd_per_token=Decimal("0.02"),
        ),
    )
    run = _shadow_run()
    result = await record_provider_usage(
        object(),
        run=run,
        usage=ProviderUsage(tokens_input=60, tokens_output=0, cost_usd=0.0),
        actor_id=ACTOR_ID,
        matrix_version=MATRIX_VERSION,
    )
    # reported cost=0 でも token floor $1.20 が計上され、USD cap で block。
    assert run.cost_usd == Decimal("1.20")
    assert result.exceeded is True
    assert result.reason == "hard_usd_exceeded"


@pytest.mark.asyncio
async def test_shadow_respects_global_kill_switch(
    monkeypatch: pytest.MonkeyPatch,
    captured_transitions: list[dict[str, object]],
) -> None:
    # global kill switch (緊急停止) は shadow でも尊重する (Codex R1 F-3)。cap 未満でも block。
    async def kill_engaged(*_args: object, **_kwargs: object) -> bool:
        return True

    monkeypatch.setattr(usage_logger, "_global_kill_switch_engaged", kill_engaged)
    run = _shadow_run()

    result = await record_provider_usage(
        object(),
        run=run,
        usage=ProviderUsage(tokens_input=1, tokens_output=1, cost_usd=0.05),
        actor_id=ACTOR_ID,
        matrix_version=MATRIX_VERSION,
    )

    assert result.exceeded is True
    assert result.reason == "global_kill_switch"
    assert len(captured_transitions) == 1
    transition = captured_transitions[0]
    assert transition["to_state"] == "blocked"
    assert transition["event_type"] == "budget_blocked"
    payload = transition["payload"]
    assert isinstance(payload, dict)
    assert payload["budget_level"] == "global"
    assert payload["run_mode"] == "shadow"


@pytest.mark.asyncio
async def test_preflight_noop_for_production_run(
    captured_transitions: list[dict[str, object]],
) -> None:
    prod = SimpleNamespace(id=RUN_ID, tenant_id=1, project_id=PROJECT_ID, run_mode="production")
    result = await preflight_shadow_budget(object(), run=prod, actor_id=ACTOR_ID)
    assert result is None
    assert captured_transitions == []


@pytest.mark.asyncio
async def test_preflight_blocks_shadow_when_kill_switch_engaged(
    monkeypatch: pytest.MonkeyPatch,
    captured_transitions: list[dict[str, object]],
) -> None:
    # Codex R4 F-2: provider 課金前に kill switch を効かせる (usage の有無に依存しない)。
    async def kill_engaged(*_args: object, **_kwargs: object) -> bool:
        return True

    monkeypatch.setattr(usage_logger, "_global_kill_switch_engaged", kill_engaged)
    result = await preflight_shadow_budget(object(), run=_shadow_run(), actor_id=ACTOR_ID)
    assert result is not None
    assert result.exceeded is True
    assert result.reason == "global_kill_switch"
    assert len(captured_transitions) == 1
    assert captured_transitions[0]["event_type"] == "budget_blocked"


@pytest.mark.asyncio
async def test_preflight_blocks_shadow_already_over_cap(
    captured_transitions: list[dict[str, object]],
) -> None:
    # 既に累計 cost が cap (1.00) 超なら、次 call を課金前に block する。
    result = await preflight_shadow_budget(
        object(), run=_shadow_run(cost_usd=Decimal("1.50")), actor_id=ACTOR_ID
    )
    assert result is not None
    assert result.exceeded is True
    assert result.reason == "hard_usd_exceeded"
    assert len(captured_transitions) == 1


@pytest.mark.asyncio
async def test_preflight_blocks_shadow_at_exact_cap(
    captured_transitions: list[dict[str, object]],
) -> None:
    # Codex R5 F-3: cap ちょうど到達 (== cap) でも次 call を block する (>= cap)。
    result = await preflight_shadow_budget(
        object(), run=_shadow_run(cost_usd=Decimal("1.00")), actor_id=ACTOR_ID
    )
    assert result is not None
    assert result.exceeded is True
    assert result.reason == "hard_usd_exceeded"
    assert len(captured_transitions) == 1


@pytest.mark.asyncio
async def test_preflight_allows_shadow_under_cap(
    captured_transitions: list[dict[str, object]],
) -> None:
    result = await preflight_shadow_budget(
        object(), run=_shadow_run(cost_usd=Decimal("0.30")), actor_id=ACTOR_ID
    )
    assert result is None
    assert captured_transitions == []


@pytest.mark.asyncio
async def test_request_token_preflight_noop_for_production(
    captured_transitions: list[dict[str, object]],
) -> None:
    prod = SimpleNamespace(id=RUN_ID, tenant_id=1, project_id=PROJECT_ID, run_mode="production")
    result = await preflight_shadow_request_tokens(
        object(), run=prod, actor_id=ACTOR_ID, request_max_tokens=None
    )
    assert result is None
    assert captured_transitions == []


@pytest.mark.asyncio
async def test_request_token_preflight_blocks_unbounded_shadow_request(
    captured_transitions: list[dict[str, object]],
) -> None:
    # Codex R7: shadow は max_tokens 必須 (unbounded request 禁止)。
    result = await preflight_shadow_request_tokens(
        object(), run=_shadow_run(), actor_id=ACTOR_ID, request_max_tokens=None
    )
    assert result is not None
    assert result.exceeded is True
    assert result.reason == "hard_tokens_exceeded"
    assert len(captured_transitions) == 1
    payload = captured_transitions[0]["payload"]
    assert isinstance(payload, dict)
    assert payload["budget_level"] == "shadow_request_tokens"


@pytest.mark.asyncio
async def test_request_token_preflight_blocks_when_request_exceeds_remaining(
    captured_transitions: list[dict[str, object]],
) -> None:
    # token cap=100、現在 80 + 要求 30 = 110 > 100 → 課金前に block。
    run = _shadow_run()
    run.tokens_input = 80
    result = await preflight_shadow_request_tokens(
        object(), run=run, actor_id=ACTOR_ID, request_max_tokens=30
    )
    assert result is not None
    assert result.exceeded is True
    assert result.reason == "hard_tokens_exceeded"
    assert len(captured_transitions) == 1


@pytest.mark.asyncio
async def test_request_token_preflight_allows_bounded_request_within_cap(
    captured_transitions: list[dict[str, object]],
) -> None:
    result = await preflight_shadow_request_tokens(
        object(), run=_shadow_run(), actor_id=ACTOR_ID, request_max_tokens=50
    )
    assert result is None
    assert captured_transitions == []


@pytest.mark.asyncio
async def test_request_token_preflight_counts_estimated_input_tokens(
    captured_transitions: list[dict[str, object]],
) -> None:
    # Codex R8/R9 F-2: 巨大 prompt (estimated_input=200) + 小さい max_tokens=1 でも、
    # input を含めて 0+200+1 > token cap 100 で課金前に block する。
    result = await preflight_shadow_request_tokens(
        object(),
        run=_shadow_run(),
        actor_id=ACTOR_ID,
        request_max_tokens=1,
        estimated_input_tokens=200,
    )
    assert result is not None
    assert result.exceeded is True
    assert result.reason == "hard_tokens_exceeded"
    assert len(captured_transitions) == 1


@pytest.mark.asyncio
async def test_request_token_preflight_allows_when_input_plus_output_fits(
    captured_transitions: list[dict[str, object]],
) -> None:
    # input 40 + output 50 = 90 <= cap 100 → 通過 (USD projection も $0.0018 < $1)。
    result = await preflight_shadow_request_tokens(
        object(),
        run=_shadow_run(),
        actor_id=ACTOR_ID,
        request_max_tokens=50,
        estimated_input_tokens=40,
    )
    assert result is None
    assert captured_transitions == []


@pytest.mark.asyncio
async def test_request_preflight_blocks_when_usd_projection_exceeds_cap(
    monkeypatch: pytest.MonkeyPatch,
    captured_transitions: list[dict[str, object]],
) -> None:
    # Codex R11 F-1: token cap は通るが USD projection が cap 超過 → provider 課金前に block。
    # price=0.02/token, usd_cap=$1, token_cap=100: 60 tokens は token cap 内だが USD=$1.20 > $1。
    monkeypatch.setattr(
        usage_logger,
        "get_settings",
        lambda: SimpleNamespace(
            shadow_run_max_cost_usd=Decimal("1.00"),
            shadow_run_max_total_tokens=100,
            shadow_run_max_usd_per_token=Decimal("0.02"),
        ),
    )
    result = await preflight_shadow_request_tokens(
        object(),
        run=_shadow_run(),
        actor_id=ACTOR_ID,
        request_max_tokens=60,
        estimated_input_tokens=0,
    )
    assert result is not None
    assert result.exceeded is True
    assert result.reason == "hard_usd_exceeded"
    assert len(captured_transitions) == 1
    payload = captured_transitions[0]["payload"]
    assert isinstance(payload, dict)
    assert payload["budget_level"] == "shadow_request_usd"


@pytest.mark.asyncio
async def test_shadow_path_never_reads_production_budget(
    captured_transitions: list[dict[str, object]],
) -> None:
    # production budget を著しく超えうる cost でも、shadow は BudgetGuard を呼ばず
    # (_ExplodingBudgetGuard が AssertionError を投げない = 触れていない証跡)、
    # shadow cap のみで判定する。
    run = _shadow_run()
    result = await record_provider_usage(
        object(),
        run=run,
        usage=ProviderUsage(tokens_input=1, tokens_output=1, cost_usd=999.0),
        actor_id=ACTOR_ID,
        matrix_version=MATRIX_VERSION,
    )
    # shadow cap (1.00) 超過で blocked、production budget には到達しない。
    assert result.exceeded is True
    assert result.reason == "hard_usd_exceeded"
    # blocked transition は 1 回 (shadow cap 判定のみ)。
    assert len(captured_transitions) == 1
    assert captured_transitions[0]["event_type"] == "budget_blocked"
