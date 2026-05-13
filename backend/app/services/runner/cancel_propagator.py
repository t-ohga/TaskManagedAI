"""Sprint 7 BL-0078: Runner cancel propagation (Redis pub/sub skeleton).

Sprint 4 で AgentRun status=cancel_requested → cancelled の transition を確立、
Sprint 6 で CancelRegistry (in-process) を作成。本 module は **Redis pub/sub
経由で worker process 横断 (multi-process) に cancel signal を伝播する** 機能
の interface を確立する。

Sprint 7 batch 3 では in-memory ``MockCancelPropagator`` を実装し、
DockerRunnerAdapter (Sprint 11) で実 Redis pub/sub に置換する設計。

Cancel signal:
- `runner.cancel:{run_id}` channel に publish
- ``CancelPropagator.listen(run_id)`` は channel subscribe し、receive 時に
  ``RunnerCancelToken.cancel()`` を呼ぶ

server-owned-boundary §1:
- ``CancelPropagator`` は orchestrator が server-resolve、caller (AI / agent)
  からは直接触れない。Approval flow / API endpoint 経由でのみ cancel
  request を起こせる。
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from backend.app.services.runner.runner_adapter import RunnerCancelToken


@dataclass(slots=True)
class CancelSignal:
    """Per-run cancel signal entry."""

    run_id: str
    reason: str = "user_request"


class CancelPropagator(ABC):
    """Abstract cancel propagation interface。Redis / Mock 実装を持つ。"""

    @abstractmethod
    async def publish_cancel(self, run_id: str, reason: str = "user_request") -> None:
        """run_id 向けの cancel signal を publish。

        - Redis impl: ``PUBLISH runner.cancel:{run_id} {reason}``
        - Mock impl: in-memory queue に push + 既存 token を cancel
        """

    @abstractmethod
    async def register_token(
        self,
        run_id: str,
        token: RunnerCancelToken,
    ) -> None:
        """run_id に紐付く RunnerCancelToken を登録し、publish 時に自動 cancel。"""

    @abstractmethod
    async def unregister_token(self, run_id: str) -> None:
        """run_command 完了後に token registration を解除。"""


@dataclass(slots=True)
class MockCancelPropagator(CancelPropagator):
    """In-memory cancel propagation (Docker / Redis 不使用)。test / dev 用。

    実 Redis pub/sub は Sprint 11 で ``RedisCancelPropagator`` として実装。
    """

    _tokens: dict[str, RunnerCancelToken] = field(default_factory=dict)
    _signals: list[CancelSignal] = field(default_factory=list)

    async def publish_cancel(self, run_id: str, reason: str = "user_request") -> None:
        self._signals.append(CancelSignal(run_id=run_id, reason=reason))
        token = self._tokens.get(run_id)
        if token is not None:
            token.cancel()
        # asyncio scheduling 上の他 coroutine に context switch
        await asyncio.sleep(0)

    async def register_token(
        self,
        run_id: str,
        token: RunnerCancelToken,
    ) -> None:
        # Check for late publish (cancel arrived before token registration)
        if any(s.run_id == run_id for s in self._signals):
            token.cancel()
        self._tokens[run_id] = token

    async def unregister_token(self, run_id: str) -> None:
        self._tokens.pop(run_id, None)

    @property
    def signals(self) -> tuple[CancelSignal, ...]:
        """Test 用: 配信済 signal を read-only で取得。"""
        return tuple(self._signals)


__all__ = [
    "CancelPropagator",
    "CancelSignal",
    "MockCancelPropagator",
]
