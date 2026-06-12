from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import get_settings
from backend.app.db.session import create_engine
from backend.app.seeds.initial import seed_golden_flow_fixtures as seed_golden_flow_fixtures
from backend.app.seeds.initial import seed_initial as seed_initial

__all__ = ["main", "seed_golden_flow_fixtures", "seed_initial"]


async def main() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    try:
        async with session_factory.begin() as session:
            await seed_initial(session)
            # golden-flow E2E fixture は test 環境のみ (本番 seed に pending 承認 / 完了 run を
            # 出さない、Codex adversarial R2 [high])。CI E2E は environment=test なので fixture を得る。
            if settings.environment == "test":
                await seed_golden_flow_fixtures(session)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

