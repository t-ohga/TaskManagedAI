"""Sprint 6 BL-0064: CLI artifact schema (Markdown frontmatter + JSON payload).

`codex exec` / `claude -p` 等の CLI agent input / output を artifact 化する際の
schema を定義する。ADR-00003 §A boundary。

5 種 (cli_input / cli_stdout / cli_stderr / cli_exit / cli_result_summary) を
固定し、既存 artifact_kind 6 種 (plan / patch / evidence / citation /
provider_continuation_ref / other、Sprint 5.5 まで) に additive only で追加。

5+ source 整合 (`.claude/rules/cross-source-enum-integrity.md §1`):
- DB CHECK: ``migrations/versions/0012_cli_artifact_kind_11.py``
- ORM CheckConstraint: ``backend.app.db.models.artifact.Artifact``
- Python Literal: ``ArtifactKind`` (本 module は ``CliArtifactKind`` subset を提供)
- Pydantic: ``CliArtifactPayload``
- pytest: ``tests/cli_artifact/test_artifact_contract.py:EXPECTED_CLI_ARTIFACT_KINDS``

caller-supplied 経路は signature レベルで物理削除 (server-owned-boundary §1):
- ``content_hash`` は server-side で payload bytes から SHA-256 で算出 (caller
  入力ではない、Pydantic Field validator で hex 64 を assert するが mutate しない)
- ``payload_data_class`` は Sprint 5.5 BL-0066 ``classify_payload_data_class``
  で server-side 算出 (本 module は読むだけ)
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.domain.artifact.data_class import PayloadDataClass
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret

CliArtifactKind = Literal[
    "cli_input",
    "cli_stdout",
    "cli_stderr",
    "cli_exit",
    "cli_result_summary",
]

ALL_CLI_ARTIFACT_KINDS: tuple[CliArtifactKind, ...] = (
    "cli_input",
    "cli_stdout",
    "cli_stderr",
    "cli_exit",
    "cli_result_summary",
)

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_SCHEMA_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")

# Markdown frontmatter delimiter (YAML in `---` block at file head).
_FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(?P<yaml>.+?)\n---\s*\n(?P<body>.*)\Z",
    re.DOTALL,
)


class CliArtifactPayload(BaseModel):
    """CLI artifact のスキーマ (Markdown frontmatter / JSON payload 両対応).

    必須 fields (ADR-00003 §A):
    - run_id: UUID (str 形式、AgentRun に紐付け)
    - artifact_kind: Literal 5 種
    - content_hash: SHA-256 hex 64 chars (server-side で payload から計算済)
    - payload_data_class: Sprint 5.5 BL-0066 で算出済 (caller-supplied 禁止)
    - source_agent: CLI binary name (e.g. "codex", "claude")
    - schema_version: semver (本 schema 自体の version、現状 "1.0.0")

    body は kind 依存:
    - cli_input: Markdown / JSON instruction content
    - cli_stdout / cli_stderr: redacted text content (raw secret 非含)
    - cli_exit: dict (exit_code / signal / duration_seconds / timeout_reached /
      cancelled_by_actor_id) を JSON で
    - cli_result_summary: dict (redacted summary、採否判定の前段)
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(..., min_length=1, max_length=64)
    artifact_kind: CliArtifactKind
    content_hash: str
    payload_data_class: PayloadDataClass
    source_agent: str = Field(..., min_length=1, max_length=128)
    schema_version: str = Field(default="1.0.0", min_length=5, max_length=32)
    body: dict[str, Any] | str

    @field_validator("content_hash")
    @classmethod
    def _content_hash_must_be_sha256_hex(cls, value: str) -> str:
        if _SHA256_HEX_RE.fullmatch(value) is None:
            raise ValueError(
                "content_hash must be a 64-char lowercase SHA-256 hex string "
                "(matches artifacts.content_hash CHECK constraint '^[0-9a-f]{64}$')"
            )
        return value

    @field_validator("schema_version")
    @classmethod
    def _schema_version_must_be_semver(cls, value: str) -> str:
        if _SCHEMA_VERSION_RE.fullmatch(value) is None:
            raise ValueError(
                "schema_version must follow semver (e.g. '1.0.0', '2.3.10')"
            )
        return value

    @field_validator("source_agent")
    @classmethod
    def _source_agent_must_be_safe_identifier(cls, value: str) -> str:
        # Reject shell-meta characters; the launcher registry is the
        # authoritative allowlist but defense-in-depth at schema layer.
        if re.search(r"[;&|`$<>(){}\\]", value):
            raise ValueError(
                "source_agent must not contain shell metacharacters"
            )
        return value

    @field_validator("body")
    @classmethod
    def _body_must_be_raw_secret_free(
        cls,
        value: dict[str, Any] | str,
    ) -> dict[str, Any] | str:
        # Codex SP6B1 R3 F-SP6B1-R3-001 adopt: schema は **fail-closed の最後の
        # gate** として dict / str の両方を共通 scanner に通す (rules/
        # ai-output-boundary.md §52: artifact に raw secret を含めない invariant)。
        # launcher 側の redaction pipeline は defense-in-depth、本 schema は
        # その最終 layer。
        assert_no_raw_secret(value, path="$cli_artifact.body")
        return value


def compute_content_hash(payload: bytes) -> str:
    """Compute the canonical SHA-256 hex digest of a CLI artifact body."""

    return hashlib.sha256(payload).hexdigest()


def parse_cli_artifact_markdown(text: str) -> tuple[dict[str, Any], str]:
    """Split a Markdown CLI artifact into (frontmatter dict, body string).

    Raises ``ValueError`` if the frontmatter is missing or malformed (YAML
    parsing handled by caller using ``yaml.safe_load``; this function only
    validates the structural delimiters).
    """

    match = _FRONTMATTER_RE.match(text)
    if match is None:
        raise ValueError(
            "CLI artifact Markdown must start with a YAML frontmatter "
            "delimited by '---' lines"
        )
    yaml_block = match.group("yaml")
    body = match.group("body")
    if not yaml_block.strip():
        raise ValueError(
            "CLI artifact Markdown frontmatter must not be empty"
        )
    # Lazy YAML import to avoid hard dependency at module level for callers
    # that only construct the schema from JSON.
    import yaml  # type: ignore[import-untyped]  # noqa: PLC0415

    parsed = yaml.safe_load(yaml_block)
    if not isinstance(parsed, dict):
        raise ValueError(
            "CLI artifact Markdown frontmatter must be a YAML mapping"
        )
    return parsed, body


__all__ = [
    "ALL_CLI_ARTIFACT_KINDS",
    "CliArtifactKind",
    "CliArtifactPayload",
    "compute_content_hash",
    "parse_cli_artifact_markdown",
]
