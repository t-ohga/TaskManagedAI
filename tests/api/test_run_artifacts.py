"""ADR-00042 L-2: AgentRun artifact metadata-only inventory endpoint の contract test.

- route 登録 (`/{run_id}/artifacts`) + route-order (`/{run_id}` に飲み込まれない)
- metadata-only schema (content / content_jsonb / content_hash を持たない)
- list_run_artifacts の生成 SQL に agent_runs 起点 + left join artifacts +
  kind <> provider_continuation_ref + soft-delete NOT EXISTS + parent self-join(case) を含み、
  content_jsonb / content_hash を SELECT しない (introspection)
- 404 (run 不可視 = 0 rows → None) vs 200-empty (run 行 + artifact null → []) vs 200 list
- parent edge: parent が provider_continuation_ref のとき parent_artifact_id=null (SQL の case で DB が
  null 化、response はそのまま写像)

注: seed-based tenant/project 越境 + soft-delete negative は CI Compose postgres で検証
(host dev は conftest test-password 不一致で実行不可)。
"""

from __future__ import annotations

import asyncio
from typing import Any, cast
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api import agent_runs as agent_runs_api
from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.repositories.artifact import ArtifactRepository


def _settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        dev_login_cookie_secret="test-cookie-secret-for-run-artifacts-api",
    )


def test_run_artifacts_route_registered() -> None:
    app = create_app(_settings())
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/v1/agent_runs/{run_id}/artifacts" in paths
    # run 詳細 route も別 path として存在 (route-order で飲み込まれない)。
    assert "/api/v1/agent_runs/{run_id}" in paths


def test_run_artifact_schema_is_metadata_only() -> None:
    fields = set(agent_runs_api.RunArtifact.model_fields.keys())
    assert fields == {
        "id",
        "kind",
        "payload_data_class",
        "trust_level",
        "exportable",
        "parent_artifact_id",
        "created_at",
    }
    # content body / hash を一切 schema に持たない (ADR-00042 metadata-only)。
    # (payload_data_class は分類 metadata なので "payload" substring は対象外)。
    for forbidden in ("content", "hash", "body"):
        assert not any(forbidden in f for f in fields)


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _CaptureSession:
    """_ensure_tenant_context を満たしつつ execute された statement を捕捉する fake session。"""

    def __init__(self, tenant_id: int, rows: list[Any]) -> None:
        self._tenant_id = tenant_id
        self._rows = rows
        self.executed: list[Any] = []

    async def scalar(self, *_args: Any, **_kwargs: Any) -> str:
        return str(self._tenant_id)

    async def execute(self, statement: Any) -> _FakeResult:
        self.executed.append(statement)
        return _FakeResult(self._rows)


def _compiled_sql(statement: Any) -> str:
    # literal_binds=True で `a.kind != 'provider_continuation_ref'` 等の定数を SQL 文字列に出す。
    return str(statement.compile(compile_kwargs={"literal_binds": True})).lower()


def _row(**kwargs: Any) -> Any:
    # SQLAlchemy Row 風の attribute アクセスを持つ stand-in。
    from types import SimpleNamespace

    return SimpleNamespace(**kwargs)


def _run(tenant_id: int, run_id: Any, rows: list[Any]) -> Any:
    session = _CaptureSession(tenant_id, rows)
    repo = ArtifactRepository(cast(AsyncSession, session))
    result = asyncio.run(repo.list_run_artifacts(tenant_id, run_id))
    return result, session


def test_list_run_artifacts_sql_has_active_scope_and_no_content() -> None:
    _result, session = _run(1, uuid4(), [])
    stmt = session.executed[-1]
    sql = _compiled_sql(stmt)
    # agent_runs 起点 + artifacts への (left) join。
    assert "from agent_runs" in sql
    assert "artifacts" in sql
    assert "left outer join" in sql
    # provider_continuation_ref 除外 (child + parent)。
    assert "provider_continuation_ref" in sql
    # soft-delete active-scope (tickets.deleted_at NOT EXISTS)。
    assert "tickets" in sql
    assert "deleted_at" in sql
    assert "not exists" in sql or "not (exists" in sql
    # parent edge の case 式。
    assert "case" in sql
    # content 本文 / hash を SELECT しない (metadata-only)。
    assert "content_jsonb" not in sql
    assert "content_hash" not in sql


def test_list_run_artifacts_returns_none_when_run_not_visible() -> None:
    # 0 rows = run 不可視 (不存在 / tenant 外 / soft-deleted ticket bound) → None (404)。
    result, _session = _run(1, uuid4(), [])
    assert result is None


def test_list_run_artifacts_returns_empty_when_visible_without_artifacts() -> None:
    # run 行あり + artifact null (LEFT JOIN sentinel) → 200 empty list。
    sentinel = _row(
        run_id=uuid4(),
        artifact_id=None,
        kind=None,
        payload_data_class=None,
        trust_level=None,
        exportable=None,
        parent_artifact_id=None,
        created_at=None,
    )
    result, _session = _run(1, uuid4(), [sentinel])
    assert result == []


def test_list_run_artifacts_maps_metadata_rows() -> None:
    aid = uuid4()
    parent = uuid4()
    created = __import__("datetime").datetime(2026, 6, 1, 10, 0, 0)
    rows = [
        _row(
            run_id=uuid4(),
            artifact_id=aid,
            kind="plan",
            payload_data_class="internal",
            trust_level="validated_artifact",
            exportable=True,
            parent_artifact_id=parent,
            created_at=created,
        ),
        # parent が provider_continuation_ref のとき DB の case で null 化 → response も null。
        _row(
            run_id=uuid4(),
            artifact_id=uuid4(),
            kind="evidence",
            payload_data_class="public",
            trust_level="untrusted_content",
            exportable=False,
            parent_artifact_id=None,
            created_at=created,
        ),
    ]
    result, _session = _run(1, uuid4(), rows)
    assert result is not None
    assert len(result) == 2
    first = result[0]
    assert first.id == aid
    assert first.kind == "plan"
    assert first.payload_data_class == "internal"
    assert first.trust_level == "validated_artifact"
    assert first.exportable is True
    assert first.parent_artifact_id == parent
    # 親が除外 ref の child は parent_artifact_id=null。
    assert result[1].parent_artifact_id is None
    # metadata-only: content/hash 属性を持たない。
    assert not hasattr(first, "content")
    assert not hasattr(first, "content_hash")
