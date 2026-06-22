"""Emergency-stop operator CLI (SP-PHASE1 B6、ADR-00048 §C/§D).

human-only な「全 AI 即停止」安全弁を **CLI からも** 操作できる導線。FastAPI endpoint
(``POST /api/v1/superintendent/emergency-stop``) と同じ ``EmergencyStopService`` を
**service 直呼び** で駆動する (``dogfooding_seed.py`` の pattern 踏襲、HTTP server 不要で testable)。

human-only 担保:
- operator actor を ``settings.default_actor_id`` (= configured P0 owner の stable id) から **DB resolve**
  し、``actor_type == 'human'`` の actor のみを使う (非 human / 別 stable id は fail-closed reject)。
- ``EmergencyStopService`` 自身も最終防衛として ``_assert_human_operator`` で actor_type=='human' を再確認する。
- API endpoint と同様、本 CLI は MCP には露出しない (AI agent surface に kill switch を出さない)。

subcommands:
    engage  : latch を engage し active run を block する。``--reason`` (任意) は service 側 broad
              secret scanner で検証される (raw secret 混入は fail-closed reject)。engage 後に Redis
              wake を best-effort publish する (DB latch が権威、publish 失敗でも各 host の DB poll で kill)。
    clear   : latch を clear し block 中 run を pre_stop_status へ復元する。``--generation`` (必須) は
              active latch の generation と一致しないと 409 相当の stale clear reject。
    status  : active latch の status (engaged / generation / engaged_at) を表示する。

usage:
    uv run python -m backend.app.cli.emergency_stop status
    uv run python -m backend.app.cli.emergency_stop engage --reason "runaway agent"
    uv run python -m backend.app.cli.emergency_stop clear --generation 3

出力には raw secret / token / pid を出さない (latch metadata + 件数のみ、service の audit と同境界)。
exit code: 0 = success、2 = operator / generation 等の precondition 違反 (engaged latch 不在・stale
generation・非 human operator・reason secret hit)、3 = 予期しないエラー。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import get_settings
from backend.app.db.models.actor import Actor
from backend.app.db.session import create_engine
from backend.app.services.superintendent.emergency_stop import (
    EmergencyStopService,
    EmergencyStopServiceError,
    NotEngagedError,
    StaleGenerationError,
)
from backend.app.services.superintendent.wake_publish import publish_emergency_stop_wake


class EmergencyStopCliError(RuntimeError):
    """operator resolution / precondition 違反を CLI exit code 2 に写像する。"""


async def _resolve_operator_actor_id(session: AsyncSession, tenant_id: int) -> UUID:
    """configured P0 owner (``settings.default_actor_id`` の stable id) を human actor として resolve。

    API endpoint の owner gate (``_require_authenticated_owner``: authenticated + human + default owner)
    に対応する CLI 側の human-only 担保。CLI には HTTP session が無いため、authenticated session の代わりに
    **configured owner stable id を DB resolve** し、``actor_type == 'human'`` を要求する (非 human / 別
    stable id / 未登録は fail-closed reject)。
    """
    default_actor_stable_id = get_settings().default_actor_id
    row = (
        await session.execute(
            sa.select(Actor.id, Actor.actor_type).where(
                Actor.tenant_id == tenant_id,
                Actor.actor_id == default_actor_stable_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise EmergencyStopCliError(
            f"configured owner actor '{default_actor_stable_id}' not found "
            f"for tenant {tenant_id}."
        )
    if row.actor_type != "human":
        raise EmergencyStopCliError(
            f"configured owner actor '{default_actor_stable_id}' is not a human actor "
            f"(actor_type={row.actor_type}); emergency-stop is human-only."
        )
    actor_id: UUID = row.id
    return actor_id


def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))  # noqa: T201


async def _engage(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: int,
    reason: str | None,
    redis_url: str,
) -> dict[str, object]:
    async with session_factory() as session:
        operator_actor_id = await _resolve_operator_actor_id(session, tenant_id)
        service = EmergencyStopService(session)
        try:
            result = await service.engage(
                tenant_id=tenant_id,
                operator_actor_id=operator_actor_id,
                reason=reason,
            )
        except EmergencyStopServiceError as exc:
            await session.rollback()
            raise EmergencyStopCliError(str(exc)) from exc
        # endpoint と同様、advisory lock を engage→block→commit まで保持する。
        await session.commit()
    # latch が durably commit された **後** に host supervisor を best-effort wake (B4 §3、endpoint 同様)。
    # DB latch が権威なので publish 失敗でも各 host の DB poll fallback で kill される。
    await publish_emergency_stop_wake(tenant_id=tenant_id, redis_url=redis_url)
    return {
        "action": "engage",
        "engaged": result.engaged,
        "generation": result.generation,
        "engaged_at": result.engaged_at.isoformat(),
        "blocked_run_count": result.blocked_run_count,
        "already_engaged": result.already_engaged,
    }


async def _clear(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: int,
    expected_generation: int,
) -> dict[str, object]:
    async with session_factory() as session:
        operator_actor_id = await _resolve_operator_actor_id(session, tenant_id)
        service = EmergencyStopService(session)
        try:
            result = await service.clear(
                tenant_id=tenant_id,
                operator_actor_id=operator_actor_id,
                expected_generation=expected_generation,
            )
        except (StaleGenerationError, NotEngagedError, EmergencyStopServiceError) as exc:
            await session.rollback()
            raise EmergencyStopCliError(str(exc)) from exc
        await session.commit()
    return {
        "action": "clear",
        "cleared": result.cleared,
        "generation": result.generation,
        "cleared_at": result.cleared_at.isoformat(),
        "resumed_run_count": result.resumed_run_count,
        "skipped_run_count": result.skipped_run_count,
    }


async def _status(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: int,
) -> dict[str, object]:
    async with session_factory() as session:
        # status は read-only だが human-only 境界を CLI でも一貫させる (configured owner のみ照会可)。
        await _resolve_operator_actor_id(session, tenant_id)
        latch = await EmergencyStopService(session).get_active(tenant_id)
    if latch is None:
        return {
            "action": "status",
            "engaged": False,
            "generation": None,
            "engaged_at": None,
        }
    return {
        "action": "status",
        "engaged": True,
        "generation": latch.generation,
        "engaged_at": latch.engaged_at.isoformat(),
    }


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    tenant_id: int = args.tenant_id if args.tenant_id is not None else settings.default_tenant_id
    engine = create_engine(settings.database_url)
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    try:
        if args.subcommand == "engage":
            payload = await _engage(
                session_factory,
                tenant_id=tenant_id,
                reason=args.reason,
                redis_url=settings.redis_url,
            )
        elif args.subcommand == "clear":
            payload = await _clear(
                session_factory,
                tenant_id=tenant_id,
                expected_generation=args.generation,
            )
        else:  # status
            payload = await _status(session_factory, tenant_id=tenant_id)
    except EmergencyStopCliError as exc:
        _print_json({"error": "emergency_stop_precondition_failed", "message": str(exc)})
        return 2
    finally:
        await engine.dispose()
    _print_json(payload)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="emergency_stop",
        description=(
            "Human-only emergency-stop operator CLI (SP-PHASE1 B6、ADR-00048). "
            "Drives EmergencyStopService directly (no HTTP server required)."
        ),
    )
    parser.add_argument(
        "--tenant-id",
        type=int,
        default=None,
        dest="tenant_id",
        help="対象 tenant (省略時は settings.default_tenant_id)。",
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    engage = sub.add_parser("engage", help="latch を engage し active run を block する。")
    engage.add_argument(
        "--reason",
        default=None,
        help="操作理由 (任意)。raw secret は service 側 broad scanner で fail-closed reject。",
    )

    clear = sub.add_parser(
        "clear", help="latch を clear し block 中 run を pre_stop_status へ復元する。"
    )
    clear.add_argument(
        "--generation",
        type=int,
        required=True,
        help="active latch の generation (CAS、stale clear reject)。",
    )

    sub.add_parser("status", help="active latch の status を表示する。")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except EmergencyStopCliError as exc:  # defensive: _run はこれを 2 に写像済
        _print_json({"error": "emergency_stop_precondition_failed", "message": str(exc)})
        return 2


if __name__ == "__main__":
    sys.exit(main())
