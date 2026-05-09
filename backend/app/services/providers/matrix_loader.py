from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import ValidationError

from backend.app.domain.provider.compliance import (
    ComplianceMatrix as ComplianceMatrixDocument,
)
from backend.app.domain.provider.compliance import ComplianceMatrixEntry


class ComplianceMatrix(dict[tuple[str, str], ComplianceMatrixEntry]):
    def __init__(
        self,
        entries: dict[tuple[str, str], ComplianceMatrixEntry] | None = None,
        *,
        matrix_version: str,
    ) -> None:
        super().__init__(entries or {})
        self.matrix_version = matrix_version


def load_compliance_matrix(toml_path: str | Path) -> ComplianceMatrix:
    path = Path(toml_path)
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("provider compliance matrix TOML must be an object.")

    try:
        document = ComplianceMatrixDocument.model_validate(data)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc

    matrix = ComplianceMatrix(matrix_version=document.matrix_version)
    for entry in document.entries:
        key = (entry.provider, entry.api_or_feature)
        if key in matrix:
            raise ValueError(
                "duplicate provider compliance matrix row for "
                f"provider={entry.provider!r}, api_or_feature={entry.api_or_feature!r}"
            )
        matrix[key] = entry

    return matrix


__all__ = ["ComplianceMatrix", "load_compliance_matrix"]

