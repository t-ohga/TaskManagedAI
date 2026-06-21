"""taskhub init/status local-host helper (SP-PHASE0 S3、minimal-but-real)。

clean Mac での local 起動 (docker compose dev + host worker、ADR-00059 loopback) を確認できる最小の
real status を返す:

- ``environment`` (Settings.environment)
- ``database_url_redacted`` (password を redact した DB URL、raw credential は出さない)
- ``db_reachable`` (DB へ ``select 1`` できたか)
- ``alembic_head_in_db`` (alembic_version table の現在 head、未適用 / 未到達なら None)
- ``alembic_head_expected`` (migrations ScriptDirectory の最新 head、**固定 revision は hardcode しない**)
- ``alembic_up_to_date`` (DB head == expected head)

固定 migration head を CLI に **hardcode しない** (Sprint Pack exit criteria: 固定 head 非記載)。expected head
は alembic ScriptDirectory から runtime 取得する。raw secret / password は一切出力しない。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"


def _redact_database_url(url: str) -> str:
    """DB URL の password component を redact する (raw credential を出力しない、Workflow review LOW adopt)。

    regex でなく ``urlsplit`` で netloc を分解し、password に ``@`` / ``/`` / ``:`` 等の特殊文字が含まれても
    取り違えず完全に mask する。parse 不能 / password 無しはそのまま返す。
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return "***"
    if parts.password is None:
        return url
    user = parts.username or ""
    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port is not None else ""
    netloc = f"{user}:***@{host}{port}" if user else f":***@{host}{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _expected_alembic_head() -> str | None:
    """migrations ScriptDirectory から最新 head revision を取得する (固定 literal を hardcode しない)。"""
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
    except ImportError:  # pragma: no cover - alembic は本 repo の依存
        return None
    if not _ALEMBIC_INI.exists():
        return None
    cfg = Config(str(_ALEMBIC_INI))
    # script_location は alembic.ini で相対 (migrations) のため repo root を base にする。
    cfg.set_main_option("script_location", str(_REPO_ROOT / "migrations"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    if len(heads) == 1:
        return heads[0]
    # 複数 head (未 merge) は曖昧 → sorted join で表示 (operator に merge 要を示す)。
    return ",".join(sorted(heads)) if heads else None


def _to_host_loopback_dsn(url: str) -> str:
    """compose-internal host (postgres/db) を host から到達可能な 127.0.0.1 へ書換える (Codex F5 adopt)。

    ``status --local`` / ``init --local`` は **host から** 起動準備を確認する。dev の
    ``settings.database_url`` は compose-internal hostname ``postgres`` を指し host からは解決不能で、
    healthy な stack でも ``db_reachable=false`` を誤報する。compose-internal host のみ 127.0.0.1 へ書換え、
    remote / 既に loopback の DSN は温存する。raw password は接続用にそのまま保持 (出力は別途 redact)。
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if parts.hostname not in ("postgres", "db"):
        return url
    user = parts.username or ""
    pw = f":{parts.password}" if parts.password is not None else ""
    auth = f"{user}{pw}@" if user or parts.password is not None else ""
    port = f":{parts.port}" if parts.port is not None else ""
    netloc = f"{auth}127.0.0.1{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def collect_local_status(database_url: str | None = None) -> dict[str, Any]:
    """local host の minimal-but-real status を dict で返す (raw secret 非出力)。"""
    from backend.app.config import get_settings

    settings = get_settings()
    if database_url is not None:
        resolved_url = database_url
    else:
        # explicit DSN 未指定時は host-local check として compose-internal host を loopback へ書換える。
        resolved_url = _to_host_loopback_dsn(settings.database_url)

    expected_head = _expected_alembic_head()

    async def _probe_db() -> tuple[bool, str | None]:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(resolved_url, pool_pre_ping=True)
        try:
            async with engine.connect() as conn:
                await conn.execute(text("select 1"))
                db_head: str | None = None
                try:
                    row = await conn.execute(text("select version_num from alembic_version"))
                    fetched = row.scalar_one_or_none()
                    db_head = str(fetched) if fetched is not None else None
                except Exception:  # noqa: BLE001 - table 未作成 (migration 未適用) は None 扱い
                    db_head = None
                return True, db_head
        except Exception:  # noqa: BLE001 - DB 未起動 / 接続不可は db_reachable=false で報告
            return False, None
        finally:
            await engine.dispose()

    db_reachable, db_head = asyncio.run(_probe_db())

    return {
        "environment": settings.environment,
        "app_name": settings.app_name,
        "database_url_redacted": _redact_database_url(resolved_url),
        "db_reachable": db_reachable,
        "alembic_head_in_db": db_head,
        "alembic_head_expected": expected_head,
        "alembic_up_to_date": (
            db_reachable and db_head is not None and db_head == expected_head
        ),
    }


__all__ = ["collect_local_status"]
