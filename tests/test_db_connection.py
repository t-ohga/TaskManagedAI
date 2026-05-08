from __future__ import annotations

import os
import re

import pytest
from sqlalchemy import text

from backend.app.config import Settings
from backend.app.db.session import AsyncSessionFactory

_PRODUCTION_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:prod-db-value@postgres:5432/taskmanagedai"
)
_PRODUCTION_REDIS_URL = "redis://redis:6379/0"
_PLACEHOLDER_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:REPLACE_ME@postgres:5432/taskmanagedai"
)
_DEVELOPMENT_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@postgres:5432/taskmanagedai"
)
_WEAK_CREDENTIAL_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@db.internal:5432/taskmanagedai"
)
_PLACEHOLDER_REDIS_URL = "redis://:REPLACE_ME@redis:6379/0"


@pytest.mark.parametrize(
    ("database_url", "redis_url", "expected_message"),
    [
        (
            _PLACEHOLDER_DATABASE_URL,
            _PRODUCTION_REDIS_URL,
            "TASKMANAGEDAI_DATABASE_URL must not contain placeholder values in production.",
        ),
        (
            _DEVELOPMENT_DEFAULT_DATABASE_URL,
            _PRODUCTION_REDIS_URL,
            "TASKMANAGEDAI_DATABASE_URL must not use the development default in production.",
        ),
        (
            _WEAK_CREDENTIAL_DATABASE_URL,
            _PRODUCTION_REDIS_URL,
            "TASKMANAGEDAI_DATABASE_URL must not use known weak credentials in production.",
        ),
        (
            _PRODUCTION_DATABASE_URL,
            _PLACEHOLDER_REDIS_URL,
            "TASKMANAGEDAI_REDIS_URL must not contain placeholder values in production.",
        ),
    ],
    ids=[
        "database-placeholder",
        "database-development-default",
        "database-weak-credential",
        "redis-placeholder",
    ],
)
def test_production_settings_reject_insecure_runtime_urls(
    database_url: str,
    redis_url: str,
    expected_message: str,
) -> None:
    with pytest.raises(ValueError, match=re.escape(expected_message)):
        Settings(
            environment="production",
            database_url=database_url,
            redis_url=redis_url,
            dev_login_cookie_secret="prod-cookie-value",
        )


@pytest.mark.parametrize(
    "cookie_secret",
    [
        "REPLACE_ME",
        "REPLACE_ME_PRODUCTION_COOKIE_SECRET",
        "REPLACE_ME_DEV_COOKIE",
    ],
)
def test_production_settings_reject_cookie_secret_placeholder(cookie_secret: str) -> None:
    expected_message = (
        "TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET must not contain placeholder values in production."
    )

    with pytest.raises(ValueError, match=re.escape(expected_message)):
        Settings(
            environment="production",
            database_url=_PRODUCTION_DATABASE_URL,
            redis_url=_PRODUCTION_REDIS_URL,
            dev_login_cookie_secret=cookie_secret,
        )


def test_production_settings_allows_internal_unauthenticated_redis_url() -> None:
    settings = Settings(
        environment="production",
        database_url=_PRODUCTION_DATABASE_URL,
        redis_url=_PRODUCTION_REDIS_URL,
        dev_login_cookie_secret="prod-cookie-value",
    )

    assert settings.redis_url == _PRODUCTION_REDIS_URL


@pytest.mark.asyncio
@pytest.mark.integration
async def test_db_session_can_execute_select_one() -> None:
    if os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") != "1":
        pytest.skip("Set TASKMANAGEDAI_RUN_DB_TESTS=1 with compose postgres running.")

    async with AsyncSessionFactory() as session:
        result = await session.execute(text("select 1 as health_check"))

    assert result.scalar_one() == 1

