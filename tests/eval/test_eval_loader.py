from __future__ import annotations

import asyncio
import copy
import json
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine
from backend.app.services.eval.loader import (
    DatasetVersionSyncError,
    FixtureLoadError,
    _canonical_content_hash,
    _canonical_fixture_hash,
    load_fixture_corpus,
    sync_dataset_version_to_db,
)

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_PATH = _REPO_ROOT / "eval/security/tenant_isolation"


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret=os.environ.get(
            "TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET",
            "test-cookie-secret-for-eval-loader-tests",
        ),
    )


def _run_alembic_upgrade(database_url: str) -> None:
    previous_database_url = os.environ.get("TASKMANAGEDAI_DATABASE_URL")
    os.environ["TASKMANAGEDAI_DATABASE_URL"] = database_url
    get_settings.cache_clear()

    try:
        config = Config(str(_REPO_ROOT / "alembic.ini"))
        command.upgrade(config, "head")
    finally:
        if previous_database_url is None:
            os.environ.pop("TASKMANAGEDAI_DATABASE_URL", None)
        else:
            os.environ["TASKMANAGEDAI_DATABASE_URL"] = previous_database_url
        get_settings.cache_clear()


async def _assert_database_available(settings: Settings) -> None:
    engine = create_engine(settings.database_url)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("select 1"))
    except (OSError, SQLAlchemyError, TimeoutError) as exc:
        if os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") == "1":
            raise AssertionError("Eval loader DB tests require a reachable test database.") from exc
        pytest.skip("Set TASKMANAGEDAI_RUN_DB_TESTS=1 with test PostgreSQL running.")
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    settings = _integration_settings()
    await _assert_database_available(settings)
    await asyncio.to_thread(_run_alembic_upgrade, settings.database_url)

    engine = create_engine(settings.database_url)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    try:
        yield factory
    finally:
        await engine.dispose()


def _read_sample_fixture() -> dict[str, object]:
    return json.loads((BASE_PATH / "public_regression/sample.json").read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_fixture_tree(
    base_path: Path,
    *,
    fixture: dict[str, object],
    split: str = "public_regression",
    update_hash: bool = True,
) -> None:
    manifest = json.loads((BASE_PATH / "manifest.json").read_text(encoding="utf-8"))
    manifest["splits"]["public_regression"]["expected_count"] = 1 if split == "public_regression" else 0
    manifest["splits"]["private_holdout"]["expected_count"] = 1 if split == "private_holdout" else 0
    manifest["splits"]["adversarial_new"]["expected_count"] = 1 if split == "adversarial_new" else 0

    fixture_id = fixture["fixture_id"]
    assert isinstance(fixture_id, str)
    metadata = fixture.get("metadata")
    created_at = "2026-05-16"
    if isinstance(metadata, dict) and isinstance(metadata.get("created_at"), str):
        created_at = metadata["created_at"]

    manifest["fixture_immutable_index"] = {
        fixture_id: {
            "sha256": _canonical_fixture_hash(fixture) if update_hash else "0" * 64,
            "split": split,
            "created_at": created_at,
        }
    }

    schema = json.loads((BASE_PATH / "expected_schema.json").read_text(encoding="utf-8"))
    _write_json(base_path / "manifest.json", manifest)
    _write_json(base_path / "expected_schema.json", schema)
    _write_json(base_path / split / "sample.json", fixture)


async def _reset_eval_tables(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            truncate eval_scores, eval_cases, eval_runs, dataset_versions
            restart identity cascade
            """
        )
    )


async def _ensure_tenant(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            insert into tenants (id, name, metadata)
            values (1, 'tenant-one', '{"rls_ready": true}'::jsonb)
            on conflict (id) do update set name = excluded.name
            """
        )
    )


def test_load_fixture_corpus_happy_path_loads_existing_tenant_isolation_fixtures() -> None:
    corpus = load_fixture_corpus(BASE_PATH, dataset_key="tenant_isolation")

    assert corpus.dataset_key == "tenant_isolation"
    assert corpus.version == "v2026.05.01-skeleton"
    assert corpus.content_hash == _canonical_content_hash(list(corpus.fixtures))
    assert len(corpus.fixtures) == 17
    assert {fixture.fixture_kind for fixture in corpus.fixtures} == {"public_regression"}


def test_load_fixture_corpus_detects_tampered_fixture_content(tmp_path: Path) -> None:
    fixture = _read_sample_fixture()
    _write_fixture_tree(tmp_path / "tenant_isolation", fixture=fixture)

    tampered = copy.deepcopy(fixture)
    tampered["case_key"] = "tampered_case_key"
    _write_json(tmp_path / "tenant_isolation/public_regression/sample.json", tampered)

    with pytest.raises(FixtureLoadError, match="sha256 mismatch"):
        load_fixture_corpus(tmp_path / "tenant_isolation", dataset_key="tenant_isolation")


def test_load_fixture_corpus_rejects_spoofed_fixture_kind(tmp_path: Path) -> None:
    fixture = _read_sample_fixture()
    fixture["fixture_kind"] = "private_holdout"
    _write_fixture_tree(tmp_path / "tenant_isolation", fixture=fixture, update_hash=True)

    with pytest.raises(FixtureLoadError, match="fixture_kind does not match split directory"):
        load_fixture_corpus(tmp_path / "tenant_isolation", dataset_key="tenant_isolation")


def test_load_fixture_corpus_rejects_raw_secret_key_without_echoing_value(tmp_path: Path) -> None:
    fixture = _read_sample_fixture()
    metadata = fixture["metadata"]
    assert isinstance(metadata, dict)
    metadata["api_key"] = "sk-this-value-must-not-be-echoed"
    _write_fixture_tree(tmp_path / "tenant_isolation", fixture=fixture, update_hash=True)

    with pytest.raises(FixtureLoadError, match="raw secret pattern detected") as exc_info:
        load_fixture_corpus(tmp_path / "tenant_isolation", dataset_key="tenant_isolation")

    assert "sk-this-value-must-not-be-echoed" not in str(exc_info.value)
    assert "raw_secret_key:api_key" in str(exc_info.value)


@pytest.mark.asyncio
async def test_sync_dataset_version_to_db_creates_dataset_and_eval_cases(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    corpus = load_fixture_corpus(BASE_PATH, dataset_key="tenant_isolation")
    fixture = corpus.fixtures[0]
    fixtures = [fixture]

    async with session_factory() as session:
        await _reset_eval_tables(session)
        await _ensure_tenant(session)

        dataset_version = await sync_dataset_version_to_db(
            session,
            tenant_id=1,
            dataset_key="tenant_isolation",
            version=fixture.dataset_version_id,
            fixture_kind=fixture.fixture_kind,
            content_hash=_canonical_content_hash(fixtures),
            fixtures=fixtures,
        )
        await session.commit()

        rows = await session.execute(
            text(
                """
                select dataset_version_id, case_key, metadata
                from eval_cases
                where tenant_id = 1 and dataset_version_id = :dataset_version_id
                """
            ),
            {"dataset_version_id": dataset_version.id},
        )

    cases = list(rows.mappings())
    assert len(cases) == 1
    assert cases[0]["dataset_version_id"] == dataset_version.id
    assert cases[0]["case_key"] == fixture.case_key
    assert cases[0]["metadata"]["fixture_id"] == fixture.fixture_id
    assert cases[0]["metadata"]["source_dataset_version_id"] == fixture.dataset_version_id


@pytest.mark.asyncio
async def test_sync_dataset_version_to_db_rejects_duplicate_dataset_version(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    corpus = load_fixture_corpus(BASE_PATH, dataset_key="tenant_isolation")
    fixture = corpus.fixtures[0]
    fixtures = [fixture]
    content_hash = _canonical_content_hash(fixtures)

    async with session_factory() as session:
        await _reset_eval_tables(session)
        await _ensure_tenant(session)

        await sync_dataset_version_to_db(
            session,
            tenant_id=1,
            dataset_key="tenant_isolation",
            version=fixture.dataset_version_id,
            fixture_kind=fixture.fixture_kind,
            content_hash=content_hash,
            fixtures=fixtures,
        )

        with pytest.raises(DatasetVersionSyncError, match="already exists"):
            await sync_dataset_version_to_db(
                session,
                tenant_id=1,
                dataset_key="tenant_isolation",
                version=fixture.dataset_version_id,
                fixture_kind=fixture.fixture_kind,
                content_hash=content_hash,
                fixtures=fixtures,
            )

        await session.rollback()
