"""ADR-00044 (A-5): ticket tag の検証。

host dev は conftest test-password 不一致で seed-based DB test を実行できないため、DB 越境系は
別途 SQL introspection / DB contract test に委ね、本 file は DB 不要で検証できる以下を固定する:

- route 登録 (project-scoped 6 endpoint)
- domain `assert_tag_name_safe` の secret reject + 正常 name 通過 + eval scanner drift guard (R7)
- schema の extra="forbid" (body project_id/tenant_id reject、R2) + TagColor palette
- color palette の 5+ source 整合 (migration DB CHECK / ORM / Pydantic / EXPECTED)
"""

from __future__ import annotations

import importlib.util
import pathlib
from typing import get_args

import pytest
from pydantic import ValidationError
from sqlalchemy import CheckConstraint, UniqueConstraint

from backend.app.api.router import api_router
from backend.app.db.models.base import Base
from backend.app.db.models.tag import TAG_COLORS, TagColor
from backend.app.domain.tag import _TAG_NAME_SECRET_PATTERNS, assert_tag_name_safe
from backend.app.schemas.tag import TagCreate, TagRead, TagUpdate, TicketTagAttach

EXPECTED_TAG_COLORS = (
    "slate",
    "red",
    "orange",
    "amber",
    "green",
    "teal",
    "blue",
    "purple",
    "pink",
)

EXPECTED_TAG_ROUTES = {
    "/api/v1/projects/{project_id}/tags",
    "/api/v1/projects/{project_id}/tags/{tag_id}",
    "/api/v1/projects/{project_id}/tickets/{ticket_id}/tags",
    "/api/v1/projects/{project_id}/tickets/{ticket_id}/tags/{tag_id}",
}


def test_tag_routes_registered() -> None:
    """project-scoped な tag CRUD + ticket attach/detach の 4 path が登録されている。"""
    registered = {getattr(r, "path", "") for r in api_router.routes}
    assert EXPECTED_TAG_ROUTES <= registered


def test_tag_route_methods() -> None:
    """tags は GET/POST、tag detail は PATCH/DELETE、ticket tag は POST/DELETE。"""
    methods: dict[str, set[str]] = {}
    for r in api_router.routes:
        path = getattr(r, "path", "")
        if path in EXPECTED_TAG_ROUTES:
            methods.setdefault(path, set()).update(getattr(r, "methods", set()) or set())
    assert {"GET", "POST"} <= methods["/api/v1/projects/{project_id}/tags"]
    assert {"PATCH", "DELETE"} <= methods["/api/v1/projects/{project_id}/tags/{tag_id}"]
    assert "POST" in methods["/api/v1/projects/{project_id}/tickets/{ticket_id}/tags"]
    assert (
        "DELETE"
        in methods["/api/v1/projects/{project_id}/tickets/{ticket_id}/tags/{tag_id}"]
    )


@pytest.mark.parametrize(
    "secret_name",
    [
        "sk-proj-ABCDEFGHIJKLMNOP",
        "sk-ABCDEFGHIJKLMNOP1234",
        "github_pat_" + "A" * 22,
        "ghu_" + "B" * 18,
        "ghr_" + "C" * 18,
        "AKIA" + "D" * 16,
        "CANARY-FIXTURE-" + "E" * 16,
    ],
)
def test_assert_tag_name_safe_rejects_secrets(secret_name: str) -> None:
    """tag name に raw secret / canary が含まれると ValueError (→ 422)。"""
    with pytest.raises(ValueError):
        assert_tag_name_safe(secret_name)


@pytest.mark.parametrize("name", ["bug", "優先度: 高", "needs-review", "P0", "tech debt"])
def test_assert_tag_name_safe_allows_normal_names(name: str) -> None:
    """通常の tag 名は通過する。"""
    assert_tag_name_safe(name)  # should not raise


def test_tag_name_patterns_cover_eval_scanner() -> None:
    """drift guard (R7): tag name secret pattern は eval scanner の raw secret 集合を完全に包含する。

    eval scanner (``anti_gaming`` の ``_RAW_SECRET_VALUE_PATTERNS``) に token 形式が追加されたら、
    tag helper 側で同期されるまで本 test が落ちる (cross-source integrity)。
    """
    from backend.app.services.eval.anti_gaming import _RAW_SECRET_VALUE_PATTERNS

    eval_patterns = {regex.pattern for _name, regex in _RAW_SECRET_VALUE_PATTERNS}
    tag_patterns = {regex.pattern for _name, regex in _TAG_NAME_SECRET_PATTERNS}
    missing = eval_patterns - tag_patterns
    assert not missing, f"tag helper is missing eval scanner secret patterns: {missing}"


def test_tag_create_schema_forbids_extra() -> None:
    """body の project_id / tenant_id は extra="forbid" で reject (server-owned boundary、R2)。"""
    with pytest.raises(ValidationError):
        TagCreate.model_validate(
            {"name": "bug", "color": "red", "project_id": "x", "tenant_id": 1}
        )
    # 正常 body は通る
    TagCreate.model_validate({"name": "bug", "color": "red"})


def test_tag_update_and_attach_schema_forbid_extra() -> None:
    with pytest.raises(ValidationError):
        TagUpdate.model_validate({"name": "x", "tenant_id": 1})
    with pytest.raises(ValidationError):
        TicketTagAttach.model_validate(
            {"tag_id": "00000000-0000-4000-8000-000000000001", "project_id": "x"}
        )


def test_tag_create_schema_rejects_invalid_color() -> None:
    """palette 外 color は schema validation で 422。"""
    with pytest.raises(ValidationError):
        TagCreate.model_validate({"name": "bug", "color": "magenta"})


def test_tag_read_schema_fields() -> None:
    """TagRead は id / name / color のみで secret 系 field を持たない。"""
    fields = set(TagRead.model_fields.keys())
    assert fields == {"id", "name", "color"}


def test_tag_color_palette_5plus_source_integrity() -> None:
    """color palette の 5+ source 整合: migration DB CHECK / ORM / Pydantic / EXPECTED が exact 一致。"""
    # 1) EXPECTED
    expected = set(EXPECTED_TAG_COLORS)
    # 2) ORM
    assert set(TAG_COLORS) == expected
    # 3) Pydantic Literal
    assert set(get_args(TagColor)) == expected
    # 4) migration の TAG_COLORS 定数 (DB CHECK 由来)
    migration_path = (
        pathlib.Path(__file__).resolve().parents[2]
        / "migrations"
        / "versions"
        / "0042_a5_ticket_tags.py"
    )
    spec = importlib.util.spec_from_file_location("_m_0042", migration_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert set(module.TAG_COLORS) == expected


# ── DDL metadata introspection (Codex code-review R1 HIGH-2): migration 0042 が要求する
#    境界 invariant を ORM metadata から固定する (DB 不要)。
def test_ticket_tags_fk_metadata_enforces_boundary() -> None:
    """ticket_tags の FK2 (tag) は RESTRICT、FK1 (ticket) は CASCADE、両 FK が
    (tenant_id, project_id) を共有して同一 project を構造的に強制する。"""
    table = Base.metadata.tables["ticket_tags"]
    fks = {fk.name: fk for fk in table.foreign_key_constraints}
    assert fks["ticket_tags_tag_fkey"].ondelete == "RESTRICT"  # 使用中 tag 削除を DB で拒否
    assert fks["ticket_tags_ticket_fkey"].ondelete == "CASCADE"
    tag_cols = set(fks["ticket_tags_tag_fkey"].column_keys)
    ticket_cols = set(fks["ticket_tags_ticket_fkey"].column_keys)
    assert {"tenant_id", "project_id"} <= tag_cols
    assert {"tenant_id", "project_id"} <= ticket_cols


def test_tags_table_constraints_metadata() -> None:
    """tags は project 内 name unique + FK target unique + name 長 / color palette CHECK +
    RLS-ready metadata 列を持つ。"""
    table = Base.metadata.tables["tags"]
    uniques = {c.name for c in table.constraints if isinstance(c, UniqueConstraint)}
    assert {"tags_uq_tenant_project_name", "tags_uq_tenant_project_id"} <= uniques
    checks = {c.name for c in table.constraints if isinstance(c, CheckConstraint)}
    assert {"tags_ck_name_length", "tags_ck_color"} <= checks
    project_fk = next(
        fk for fk in table.foreign_key_constraints if fk.name == "tags_project_fkey"
    )
    assert {"tenant_id", "project_id"} <= set(project_fk.column_keys)
    assert "metadata" in table.columns  # RLS-ready metadata


def test_ticket_tags_join_table_has_no_metadata_column() -> None:
    """join table は entity ではないため metadata 列を持たない (RLS は親で enforce、R3 免除)。"""
    assert "metadata" not in Base.metadata.tables["ticket_tags"].columns
