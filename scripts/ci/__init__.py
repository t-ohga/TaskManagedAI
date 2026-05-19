"""CI helper modules for framework intake checking (SP022-T01).

Per ADR-00020 Framework Intake Checklist, this package provides:
- check_framework_intake.sh: shell entry point invoked by .github/workflows/ci-smoke.yml
- _extract_changed_deps.py: helper to extract direct dependencies from pyproject.toml /
  frontend/package.json (PEP 503 canonicalization for PyPI, scoped name preservation for npm)
- _intake_scanner.py: Python scanner for verify items #3-#8 (no_code_embed / persistence /
  external_network / telemetry / secret_canary / tenant_boundary)
"""
