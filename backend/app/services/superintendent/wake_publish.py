"""emergency-stop wake publish (SP-PHASE1 B4、ADR-00048 §F hybrid supervisor)。

engage で latch row が **durably commit された後**、host supervisor を即時 wake するための Redis
pub/sub publish (best-effort、低レイテンシ最適化)。**DB latch が権威**なので publish 失敗でも各 host の
DB poll fallback (``supervisor_poll_once``) で必ず kill される (Redis 単独障害で kill 不能にならない、
fail-closed)。

raw secret は payload に出さない (tenant_id のみ。tenant_id は Redis channel injection 防御のため
``int`` のみ受ける = server-owned)。
"""

from __future__ import annotations

import json
import logging
from typing import Protocol, cast

from backend.app.services.superintendent.supervisor import SUPERVISOR_WAKE_CHANNEL

logger = logging.getLogger(__name__)


class _RedisPublisher(Protocol):
    """redis.asyncio.Redis の publish 契約 (test で in-memory 実装に差し替え可能)。"""

    async def publish(self, channel: str, message: str) -> int: ...


def _redis_publisher_from_url(redis_url: str) -> _RedisPublisher:
    from redis.asyncio import Redis

    return cast(_RedisPublisher, Redis.from_url(redis_url, decode_responses=True))


async def publish_emergency_stop_wake(
    *,
    tenant_id: int,
    redis_url: str | None = None,
    publisher: _RedisPublisher | None = None,
    channel: str = SUPERVISOR_WAKE_CHANNEL,
) -> bool:
    """engage 後に host supervisor を wake する (best-effort)。成功で True、失敗でも raise しない。

    DB latch が権威のため、本 publish は **低レイテンシ最適化のみ**。Redis 障害 / 接続失敗 /
    publisher 不在は WARN log を残して False を返す (caller は無視してよい、DB poll が回収する)。

    payload は ``{"tenant_id": <int>}`` のみ (raw secret なし)。supervisor 側は payload を信頼せず
    wake シグナルとして扱い、DB latch を再読する (payload 改ざんで誤 kill しない)。
    """
    # LOW-5 (adversarial review adopt): 内部生成した Redis client は publish 後に必ず close する
    # (engage 毎に新 client を作って close しないと connection leak)。injected publisher (caller 所有)
    # は close しない (所有権は caller)。
    owns_client = publisher is None
    pub = publisher
    if pub is None:
        if not redis_url:
            return False
        try:
            pub = _redis_publisher_from_url(redis_url)
        except Exception:  # noqa: BLE001 — 接続失敗でも engage は成立済 (DB poll fallback)。
            logger.warning(
                "emergency_stop_wake_publisher_unavailable (DB poll fallback active)",
                extra={"tenant_id": tenant_id},
                exc_info=True,
            )
            return False
    payload = json.dumps({"tenant_id": tenant_id}, separators=(",", ":"))
    try:
        await pub.publish(channel, payload)
        return True
    except Exception:  # noqa: BLE001 — publish 失敗でも DB poll が回収する (fail-closed)。
        logger.warning(
            "emergency_stop_wake_publish_failed (DB poll fallback active)",
            extra={"tenant_id": tenant_id},
            exc_info=True,
        )
        return False
    finally:
        # LOW-5: 内部生成 client のみ close (injected は caller 所有のため触らない)。
        if owns_client:
            await _close_publisher(pub)


async def _close_publisher(pub: _RedisPublisher) -> None:
    """内部生成した Redis client を best-effort で close する (leak 防止、close 失敗は無視)。"""
    close = getattr(pub, "aclose", None) or getattr(pub, "close", None)
    if close is None:
        return
    try:
        result = close()
        if hasattr(result, "__await__"):
            await result
    except Exception:  # noqa: BLE001 — close 失敗は best-effort (engage は成立済)。
        logger.debug("emergency_stop_wake_publisher_close_failed", exc_info=True)


__all__ = ["publish_emergency_stop_wake"]
